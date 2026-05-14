"""
Master timetable scheduling engine (Phase 1: hard constraints only).

Hard constraints (PRD):
- Teacher overlap: a teacher cannot teach two offerings in the same time slot.
- Room overlap: a room cannot host two offerings in the same time slot.
- Student group overlap: a group cannot attend two offerings in the same time slot.
- Session fulfillment: each offering must be scheduled exactly `Course.sessions_required` times.

Additional hard rules (updated models / project context):
- Theory sessions use one time slot and must be placed in a `Room.room_type == "Lecture"`.
- Lab sessions must be placed in a `Room.room_type == "Lab"`.
- A lab session occupies `Course.lab_block_slots` consecutive slots on the same day that are
  **physically contiguous** (no institutional break between end of one slot and start of the next).
- If `LabCoursePolicy` exists for the lab course, the lab room must be in that `Room.faculty`.
"""

from __future__ import annotations

import random
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import DefaultDict, Dict, Iterable, Optional, Tuple

from models import Course, CourseOffering, LabCoursePolicy, Room, TimeSlot, StudentGroup, Teacher

DAY_ORDER = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4}

# Labs must not span across lunch / breaks: if gap between slot end and next slot start exceeds
# this many minutes, those slots cannot belong to the same lab block (typical passing gaps ~10 min).
_MAX_ADJACENT_GAP_MINUTES_FOR_LAB_BLOCK = 30


def _hhmm_to_minutes(hhmm: str) -> int:
    parts = (hhmm or "00:00").strip().split(":")
    h = int(parts[0]) if parts else 0
    m = int(parts[1]) if len(parts) > 1 else 0
    return h * 60 + m


def _gap_minutes_slot_boundary(prev_ts: TimeSlot, next_ts: TimeSlot) -> int:
    """Minutes between prev slot end and next slot start (same day)."""
    return _hhmm_to_minutes(next_ts.start_time) - _hhmm_to_minutes(prev_ts.end_time)


def _lab_chunk_physically_contiguous(chunk: list[TimeSlot]) -> bool:
    if len(chunk) <= 1:
        return True
    return all(
        _gap_minutes_slot_boundary(a, b) <= _MAX_ADJACENT_GAP_MINUTES_FOR_LAB_BLOCK
        for a, b in zip(chunk, chunk[1:])
    )


@dataclass(frozen=True)
class Task:
    offering_id: str
    course_id: str
    teacher_id: str
    group_id: str
    room_type: str  # "Lecture" or "Lab"
    span: int  # 1 for lecture; >= 1 for lab blocks
    policy_faculty: Optional[str]
    session_index: int
    group_size: int
    is_elective: bool
    teacher_max_consecutive: int


@dataclass(frozen=True)
class Assignment:
    offering_id: str
    room_id: str
    timeslot_id: str


def _sorted_timeslots(timeslots: Iterable[TimeSlot]) -> list[TimeSlot]:
    return sorted(
        timeslots,
        key=lambda ts: (DAY_ORDER.get(ts.day, 99), ts.start_time, ts.end_time, ts.id),
    )


def _timeslots_by_day(timeslots: list[TimeSlot]) -> dict[str, list[TimeSlot]]:
    by_day: DefaultDict[str, list[TimeSlot]] = defaultdict(list)
    for ts in timeslots:
        by_day[ts.day].append(ts)
    for day, rows in by_day.items():
        rows.sort(key=lambda ts: (ts.start_time, ts.end_time, ts.id))
    return dict(by_day)


def _consecutive_blocks(timeslots_in_day: list[TimeSlot], span: int) -> list[tuple[str, ...]]:
    """Lab-admissible blocks: same-day slots contiguous in the timetable list with no large gap."""
    if span <= 1:
        return [(ts.id,) for ts in timeslots_in_day]
    if len(timeslots_in_day) < span:
        return []
    out: list[tuple[str, ...]] = []
    for i in range(0, len(timeslots_in_day) - span + 1):
        chunk = timeslots_in_day[i : i + span]
        if _lab_chunk_physically_contiguous(chunk):
            out.append(tuple(ts.id for ts in chunk))
    return out


def _build_timeslot_metadata(timeslots: list[TimeSlot]) -> tuple[dict[str, tuple[str, int]], dict[str, list[TimeSlot]]]:
    slots_by_day = _timeslots_by_day(timeslots)
    slot_meta: dict[str, tuple[str, int]] = {}
    for day, day_slots in slots_by_day.items():
        for index, ts in enumerate(day_slots):
            slot_meta[ts.id] = (day, index)
    return slot_meta, slots_by_day


def _longest_consecutive_run(sorted_indexes: list[int]) -> int:
    if not sorted_indexes:
        return 0
    longest = 1
    current = 1
    for left, right in zip(sorted_indexes, sorted_indexes[1:]):
        if right == left + 1:
            current += 1
            longest = max(longest, current)
        else:
            current = 1
    return longest


def _build_tasks(
    offerings: list[CourseOffering],
    courses_by_id: dict[str, Course],
    policies_by_course_id: dict[str, LabCoursePolicy],
    teachers_by_id: dict[str, Teacher],
    groups_by_id: dict[str, StudentGroup],
) -> list[Task]:
    tasks: list[Task] = []
    for off in offerings:
        course = courses_by_id.get(off.course_id)
        if course is None:
            continue

        room_type = "Lab" if str(course.course_type).strip() == "Lab" else "Lecture"
        sessions_required = max(1, int(course.sessions_required or 1))

        if room_type == "Lab":
            span = max(1, int(course.lab_block_slots or 1))
            policy = policies_by_course_id.get(course.id)
            policy_faculty = policy.faculty if policy is not None else None
        else:
            span = 1
            policy_faculty = None

        teacher = teachers_by_id.get(off.teacher_id)
        group = groups_by_id.get(off.group_id)
        group_size = int(group.total_students if group is not None else 0)
        teacher_max = int(teacher.max_consecutive if teacher is not None else 3)

        for k in range(sessions_required):
            tasks.append(
                Task(
                    offering_id=off.id,
                    course_id=off.course_id,
                    teacher_id=off.teacher_id,
                    group_id=off.group_id,
                    room_type=room_type,
                    span=span,
                    policy_faculty=policy_faculty,
                    session_index=k,
                    group_size=group_size,
                    is_elective=bool(course.is_elective),
                    teacher_max_consecutive=max(1, teacher_max),
                )
            )
    return tasks


def _order_tasks(tasks: list[Task]) -> list[Task]:
    teacher_load = Counter(t.teacher_id for t in tasks)
    group_load = Counter(t.group_id for t in tasks)
    return sorted(
        tasks,
        key=lambda t: (
            -int(t.room_type == "Lab"),
            -t.span,
            -(teacher_load[t.teacher_id] + group_load[t.group_id]),
            t.offering_id,
            t.session_index,
        ),
    )


def _max_disjoint_blocks_in_day(timeslots_in_day: list[TimeSlot], span: int) -> int:
    """Max non-overlapping physically valid lab blocks that fit in one day (greedy by finish time)."""
    if span <= 1:
        return len(timeslots_in_day)
    if len(timeslots_in_day) < span:
        return 0
    intervals: list[tuple[int, int]] = []
    for i in range(0, len(timeslots_in_day) - span + 1):
        chunk = timeslots_in_day[i : i + span]
        if _lab_chunk_physically_contiguous(chunk):
            intervals.append((i, i + span))
    if not intervals:
        return 0
    intervals.sort(key=lambda iv: iv[1])
    count = 0
    last_end = -1
    for start, end in intervals:
        if start >= last_end:
            count += 1
            last_end = end
    return count


def _precheck_capacity(
    *,
    tasks: list[Task],
    timeslots: list[TimeSlot],
    lecture_room_ids: list[str],
    lab_room_ids_by_faculty: dict[str, list[str]],
) -> tuple[bool, str]:
    if not timeslots:
        return False, "No time slots available."

    slots_per_week = len(timeslots)
    lecture_capacity = len(lecture_room_ids) * slots_per_week
    lab_capacity = sum(len(v) for v in lab_room_ids_by_faculty.values()) * slots_per_week

    lecture_demand = sum(1 for t in tasks if t.room_type == "Lecture")
    lab_slot_demand = sum(t.span for t in tasks if t.room_type == "Lab")

    if lecture_demand > lecture_capacity:
        return False, f"Infeasible: lecture demand exceeds lecture capacity ({lecture_demand} > {lecture_capacity})."
    if lab_slot_demand > lab_capacity:
        return False, f"Infeasible: lab demand exceeds lab capacity ({lab_slot_demand} > {lab_capacity})."

    slots_by_day = _timeslots_by_day(timeslots)
    lab_block_capacity_by_span: dict[int, int] = {
        span: sum(_max_disjoint_blocks_in_day(day_slots, span) for day_slots in slots_by_day.values())
        for span in {t.span for t in tasks if t.room_type == "Lab"}
    }

    demand_by_faculty: Counter[str] = Counter()
    for t in tasks:
        if t.room_type == "Lab" and t.policy_faculty:
            demand_by_faculty[t.policy_faculty] += t.span

    for fac, dem in demand_by_faculty.items():
        cap = len(lab_room_ids_by_faculty.get(fac, [])) * slots_per_week
        if dem > cap:
            return False, f"Infeasible: lab demand exceeds lab capacity for faculty '{fac}' ({dem} > {cap})."

    teacher_lab_span_demand: Counter[tuple[str, int]] = Counter()
    group_lab_span_demand: Counter[tuple[str, int]] = Counter()
    teacher_slot_demand: Counter[str] = Counter()
    group_slot_demand: Counter[str] = Counter()

    for t in tasks:
        teacher_slot_demand[t.teacher_id] += t.span
        group_slot_demand[t.group_id] += t.span
        if t.room_type == "Lab":
            teacher_lab_span_demand[(t.teacher_id, t.span)] += 1
            group_lab_span_demand[(t.group_id, t.span)] += 1

    for (teacher_id, span), block_count in teacher_lab_span_demand.items():
        cap = lab_block_capacity_by_span.get(span, 0)
        if block_count > cap:
            return (
                False,
                f"Infeasible: teacher '{teacher_id}' requires {block_count} lab blocks of span {span}, but only {cap} disjoint blocks are possible in the schedule."
            )

    for (group_id, span), block_count in group_lab_span_demand.items():
        cap = lab_block_capacity_by_span.get(span, 0)
        if block_count > cap:
            return (
                False,
                f"Infeasible: student group '{group_id}' requires {block_count} lab blocks of span {span}, but only {cap} disjoint blocks are possible in the schedule."
            )

    for teacher_id, slot_count in teacher_slot_demand.items():
        if slot_count > slots_per_week:
            return (
                False,
                f"Infeasible: teacher '{teacher_id}' needs {slot_count} total slots but only {slots_per_week} exist in the week."
            )

    for group_id, slot_count in group_slot_demand.items():
        if slot_count > slots_per_week:
            return (
                False,
                f"Infeasible: student group '{group_id}' needs {slot_count} total slots but only {slots_per_week} exist in the week."
            )

    return True, "OK"


def _people_free(
    task: Task,
    slot_ids: tuple[str, ...],
    *,
    teacher_busy: set[tuple[str, str]],
    group_busy: set[tuple[str, str]],
) -> bool:
    for sid in slot_ids:
        if (task.teacher_id, sid) in teacher_busy:
            return False
        if (task.group_id, sid) in group_busy:
            return False
    return True


def _room_free(room_id: str, slot_ids: tuple[str, ...], *, room_busy: set[tuple[str, str]]) -> bool:
    return all((room_id, sid) not in room_busy for sid in slot_ids)


def _offering_day_free(
    task: Task,
    slot_ids: tuple[str, ...],
    *,
    offering_day_used: dict[str, set[str]],
    slot_meta: dict[str, tuple[str, int]],
) -> bool:
    day = slot_meta[slot_ids[0]][0]
    return day not in offering_day_used.get(task.offering_id, set())


def _assignment_cost(
    task: Task,
    slot_ids: tuple[str, ...],
    room_capacity: int,
    *,
    teacher_schedule: dict[tuple[str, str], list[int]],
    group_schedule: dict[tuple[str, str], list[int]],
    elective_count_by_slot: Counter,
    teacher_slot_budget: dict[str, int],
    slot_meta: dict[str, tuple[str, int]],
    days_count: int,
) -> float:
    day = slot_meta[slot_ids[0]][0]
    slot_indexes = [slot_meta[sid][1] for sid in slot_ids]
    teacher_key = (task.teacher_id, day)
    group_key = (task.group_id, day)
    teacher_indexes = sorted(teacher_schedule.get(teacher_key, []) + slot_indexes)
    group_indexes = sorted(group_schedule.get(group_key, []) + slot_indexes)

    cost = 0.0
    cost += sum(max(0, group_indexes[i + 1] - group_indexes[i] - 1) * 2 for i in range(len(group_indexes) - 1))

    if teacher_indexes:
        teacher_run = _longest_consecutive_run(teacher_indexes)
        if teacher_run > task.teacher_max_consecutive:
            cost += (teacher_run - task.teacher_max_consecutive) * 4

    if group_indexes:
        group_run = _longest_consecutive_run(group_indexes)
        if group_run > 3:
            cost += (group_run - 3) * 4

    if room_capacity < task.group_size:
        cost += (task.group_size - room_capacity) * 10
    else:
        cost += ((room_capacity - task.group_size) / max(1, room_capacity)) * 2

    total_teacher_slots = teacher_slot_budget.get(task.teacher_id, task.span)
    target_load = total_teacher_slots / max(1, days_count)
    day_load = len(teacher_schedule.get(teacher_key, [])) + len(slot_ids)
    cost += ((day_load - target_load) ** 2) * 0.15

    if task.is_elective:
        cost += sum(max(0, elective_count_by_slot.get(sid, 0)) * 4 for sid in slot_ids)

    return cost


def _score_schedule(
    assignments: list[Assignment],
    tasks_by_offering: dict[str, Task],
    room_capacity_by_id: dict[str, int],
    slot_meta: dict[str, tuple[str, int]],
    days_count: int,
) -> float:
    penalty = 0.0
    teacher_daily: DefaultDict[tuple[str, str], list[int]] = defaultdict(list)
    group_daily: DefaultDict[tuple[str, str], list[int]] = defaultdict(list)
    elective_count_by_slot: Counter[str] = Counter()

    for assignment in assignments:
        task = tasks_by_offering.get(assignment.offering_id)
        if task is None:
            continue

        day, index = slot_meta[assignment.timeslot_id]
        teacher_daily[(task.teacher_id, day)].append(index)
        group_daily[(task.group_id, day)].append(index)
        if task.is_elective:
            elective_count_by_slot[assignment.timeslot_id] += 1

        room_capacity = room_capacity_by_id.get(assignment.room_id, 0)
        if room_capacity < task.group_size:
            penalty += (task.group_size - room_capacity) * 10
        else:
            penalty += ((room_capacity - task.group_size) / max(1, room_capacity)) * 2

    for indexes in group_daily.values():
        sorted_indexes = sorted(indexes)
        penalty += sum(max(0, sorted_indexes[i + 1] - sorted_indexes[i] - 1) * 2 for i in range(len(sorted_indexes) - 1))
        longest = _longest_consecutive_run(sorted_indexes)
        if longest > 3:
            penalty += (longest - 3) * 4

    teacher_loads: DefaultDict[str, list[int]] = defaultdict(list)
    for (teacher_id, _), indexes in teacher_daily.items():
        longest = _longest_consecutive_run(sorted(indexes))
        task = next((t for t in tasks_by_offering.values() if t.teacher_id == teacher_id), None)
        max_consecutive = task.teacher_max_consecutive if task is not None else 3
        if longest > max_consecutive:
            penalty += (longest - max_consecutive) * 4
        teacher_loads[teacher_id].append(len(indexes))

    for teacher_id, daily_counts in teacher_loads.items():
        total = sum(daily_counts)
        target_load = total / max(1, days_count)
        penalty += sum(((count - target_load) ** 2) * 0.15 for count in daily_counts)

    for count in elective_count_by_slot.values():
        if count > 1:
            penalty += (count - 1) * 4

    return penalty


def _select_lecture_assignment(
    task: Task,
    lecture_slot_ids: list[str],
    lecture_room_ids: list[str],
    *,
    teacher_busy: set[tuple[str, str]],
    group_busy: set[tuple[str, str]],
    room_busy: set[tuple[str, str]],
    offering_day_used: dict[str, set[str]],
    teacher_schedule: dict[tuple[str, str], list[int]],
    group_schedule: dict[tuple[str, str], list[int]],
    elective_count_by_slot: Counter,
    teacher_slot_budget: dict[str, int],
    room_capacity_by_id: dict[str, int],
    slot_meta: dict[str, tuple[str, int]],
    days_count: int,
    rng: random.Random,
    eval_cap: Optional[int] = 900,
) -> Optional[tuple[str, tuple[str, ...]]]:
    """Two-phase search: capped stochastic exploration, then exhaustive fallback."""
    for phase in (1, 2):
        use_cap = phase == 1 and eval_cap is not None
        slot_order = list(lecture_slot_ids)
        room_order = list(lecture_room_ids)
        if use_cap:
            rng.shuffle(slot_order)
            rng.shuffle(room_order)
        cap = eval_cap if use_cap else None

        best_cost = None
        best_options: list[tuple[tuple[str, ...], str]] = []
        evaluated = 0

        for sid in slot_order:
            if cap is not None and evaluated >= cap:
                break
            if not _people_free(task, (sid,), teacher_busy=teacher_busy, group_busy=group_busy):
                continue
            if not _offering_day_free(task, (sid,), offering_day_used=offering_day_used, slot_meta=slot_meta):
                continue

            for rid in room_order:
                if cap is not None and evaluated >= cap:
                    break
                if (rid, sid) in room_busy:
                    continue
                evaluated += 1
                cost = _assignment_cost(
                    task,
                    (sid,),
                    room_capacity_by_id.get(rid, 0),
                    teacher_schedule=teacher_schedule,
                    group_schedule=group_schedule,
                    elective_count_by_slot=elective_count_by_slot,
                    teacher_slot_budget=teacher_slot_budget,
                    slot_meta=slot_meta,
                    days_count=days_count,
                )
                if best_cost is None or cost < best_cost:
                    best_cost = cost
                    best_options = [((sid,), rid)]
                elif cost == best_cost:
                    best_options.append(((sid,), rid))
                if best_cost == 0.0:
                    slot_ids, room_id = rng.choice(best_options)
                    return room_id, slot_ids

            if cap is not None and evaluated >= cap:
                break

        if best_options:
            slot_ids, room_id = rng.choice(best_options)
            return room_id, slot_ids

    return None


def _select_lab_assignment(
    task: Task,
    blocks: list[tuple[str, ...]],
    lab_room_ids_by_faculty: dict[str, list[str]],
    *,
    teacher_busy: set[tuple[str, str]],
    group_busy: set[tuple[str, str]],
    room_busy: set[tuple[str, str]],
    offering_day_used: dict[str, set[str]],
    teacher_schedule: dict[tuple[str, str], list[int]],
    group_schedule: dict[tuple[str, str], list[int]],
    elective_count_by_slot: Counter,
    teacher_slot_budget: dict[str, int],
    room_capacity_by_id: dict[str, int],
    slot_meta: dict[str, tuple[str, int]],
    days_count: int,
    rng: random.Random,
    eval_cap: Optional[int] = 1200,
) -> Optional[tuple[str, tuple[str, ...]]]:
    allowed_rooms = (
        list(lab_room_ids_by_faculty.get(task.policy_faculty, []))
        if task.policy_faculty
        else [rid for fac in lab_room_ids_by_faculty.values() for rid in fac]
    )
    if not allowed_rooms:
        return None

    for phase in (1, 2):
        use_cap = phase == 1 and eval_cap is not None
        block_order = list(blocks)
        if use_cap:
            rng.shuffle(block_order)
        cap = eval_cap if use_cap else None

        best_cost = None
        best_options: list[tuple[tuple[str, ...], str]] = []
        evaluated = 0

        for block in block_order:
            if cap is not None and evaluated >= cap:
                break
            if not _people_free(task, block, teacher_busy=teacher_busy, group_busy=group_busy):
                continue
            if not _offering_day_free(task, block, offering_day_used=offering_day_used, slot_meta=slot_meta):
                continue

            room_order = list(allowed_rooms)
            if use_cap:
                rng.shuffle(room_order)

            for rid in room_order:
                if cap is not None and evaluated >= cap:
                    break
                if not _room_free(rid, block, room_busy=room_busy):
                    continue
                evaluated += 1
                cost = _assignment_cost(
                    task,
                    block,
                    room_capacity_by_id.get(rid, 0),
                    teacher_schedule=teacher_schedule,
                    group_schedule=group_schedule,
                    elective_count_by_slot=elective_count_by_slot,
                    teacher_slot_budget=teacher_slot_budget,
                    slot_meta=slot_meta,
                    days_count=days_count,
                )
                if best_cost is None or cost < best_cost:
                    best_cost = cost
                    best_options = [(block, rid)]
                elif cost == best_cost:
                    best_options.append((block, rid))
                if best_cost == 0.0:
                    block, room_id = rng.choice(best_options)
                    return room_id, block

        if best_options:
            block, room_id = rng.choice(best_options)
            return room_id, block

    return None


def _place(
    task: Task,
    room_id: str,
    slot_ids: tuple[str, ...],
    *,
    teacher_busy: set[tuple[str, str]],
    group_busy: set[tuple[str, str]],
    room_busy: set[tuple[str, str]],
    out: list[Assignment],
) -> None:
    for sid in slot_ids:
        teacher_busy.add((task.teacher_id, sid))
        group_busy.add((task.group_id, sid))
        room_busy.add((room_id, sid))
        out.append(Assignment(offering_id=task.offering_id, room_id=room_id, timeslot_id=sid))


def generate_hard_timetable(
    *,
    max_restarts: int = 48,
    seed: int = 42,
    time_limit_s: float = 10.0,
    lecture_eval_cap: Optional[int] = 900,
    lab_eval_cap: Optional[int] = 1200,
    stop_on_first_complete: bool = True,
) -> dict:
    t0 = time.perf_counter()
    deadline = t0 + float(time_limit_s)

    courses_by_id = {c.id: c for c in Course.query.all()}
    policies_by_course_id = {p.course_id: p for p in LabCoursePolicy.query.all()}
    offerings = CourseOffering.query.all()
    rooms = Room.query.all()
    timeslots = _sorted_timeslots(TimeSlot.query.all())

    metrics = {
        "computation_time_ms": 0,
        "restarts_used": 0,
        "total_tasks": 0,
        "hard_valid": False,
        "fitness": 0.0,
        "penalty_total": 0.0,
        "time_complexity": "O(restarts × tasks × capped_assign_eval)",
        "space_complexity": "O(N + BusySets + Rooms)",
    }

    if not offerings or not rooms or not timeslots:
        metrics["computation_time_ms"] = int((time.perf_counter() - t0) * 1000)
        return {
            "success": False,
            "message": "Missing offerings, rooms, or timeslots. Please load data first.",
            "assignments": [],
            "metrics": metrics,
        }

    lecture_room_ids = [r.id for r in rooms if str(r.room_type).strip() == "Lecture"]
    lab_room_ids_by_faculty: DefaultDict[str, list[str]] = defaultdict(list)
    for r in rooms:
        if str(r.room_type).strip() == "Lab":
            lab_room_ids_by_faculty[str(r.faculty).strip()].append(r.id)
    for fac in lab_room_ids_by_faculty:
        lab_room_ids_by_faculty[fac].sort()

    if not lecture_room_ids:
        metrics["computation_time_ms"] = int((time.perf_counter() - t0) * 1000)
        return {
            "success": False,
            "message": "No lecture rooms found (Room.room_type == 'Lecture').",
            "assignments": [],
            "metrics": metrics,
        }

    if not any(lab_room_ids_by_faculty.values()):
        # It's okay if there are no lab courses; capacity check handles demand.
        pass

    teachers_by_id = {t.id: t for t in Teacher.query.all()}
    groups_by_id = {g.id: g for g in StudentGroup.query.all()}
    tasks = _order_tasks(_build_tasks(offerings, courses_by_id, policies_by_course_id, teachers_by_id, groups_by_id))
    metrics["total_tasks"] = len(tasks)

    ok, msg = _precheck_capacity(
        tasks=tasks,
        timeslots=timeslots,
        lecture_room_ids=lecture_room_ids,
        lab_room_ids_by_faculty=dict(lab_room_ids_by_faculty),
    )
    if not ok:
        metrics["computation_time_ms"] = int((time.perf_counter() - t0) * 1000)
        return {"success": False, "message": msg, "assignments": [], "metrics": metrics}

    slot_meta, slots_by_day = _build_timeslot_metadata(timeslots)
    lecture_slot_ids = [ts.id for ts in timeslots]
    room_capacity_by_id = {r.id: int(r.capacity) for r in rooms}
    teacher_slot_budget: Counter[str] = Counter()
    for t in tasks:
        teacher_slot_budget[t.teacher_id] += t.span
    tasks_by_offering = {t.offering_id: t for t in tasks}
    days_count = len(slots_by_day)

    lab_blocks_by_span: dict[int, list[tuple[str, ...]]] = {}
    for t in tasks:
        if t.room_type == "Lab":
            lab_blocks_by_span.setdefault(t.span, [])
    for span in lab_blocks_by_span.keys():
        blocks: list[tuple[str, ...]] = []
        for _, day_slots in slots_by_day.items():
            blocks.extend(_consecutive_blocks(day_slots, span))
        lab_blocks_by_span[span] = blocks

    best_partial: int = 0
    best_partial_assignments: list[Assignment] = []
    best_partial_penalty: float = float("inf")
    best_complete_assignments: Optional[list[Assignment]] = None
    best_complete_penalty: float = float("inf")

    for restart in range(max_restarts):
        if time.perf_counter() >= deadline:
            break

        metrics["restarts_used"] = restart

        # Fresh RNG per restart so restarts actually explore new schedules.
        rng = random.Random(int(seed) + int(restart))

        teacher_busy: set[tuple[str, str]] = set()
        group_busy: set[tuple[str, str]] = set()
        room_busy: set[tuple[str, str]] = set()
        offering_day_used: dict[str, set[str]] = defaultdict(set)
        teacher_schedule: DefaultDict[tuple[str, str], list[int]] = defaultdict(list)
        group_schedule: DefaultDict[tuple[str, str], list[int]] = defaultdict(list)
        elective_count_by_slot: Counter[str] = Counter()
        assignments: list[Assignment] = []

        lab_tasks = [t for t in tasks if t.room_type == "Lab"]
        lec_tasks = [t for t in tasks if t.room_type == "Lecture"]
        rng.shuffle(lab_tasks)
        rng.shuffle(lec_tasks)
        tasks_run = lab_tasks + lec_tasks
        placed = 0
        for task in tasks_run:
            if time.perf_counter() >= deadline:
                break

            if task.room_type == "Lecture":
                assignment = _select_lecture_assignment(
                    task,
                    lecture_slot_ids,
                    lecture_room_ids,
                    teacher_busy=teacher_busy,
                    group_busy=group_busy,
                    room_busy=room_busy,
                    offering_day_used=offering_day_used,
                    teacher_schedule=teacher_schedule,
                    group_schedule=group_schedule,
                    elective_count_by_slot=elective_count_by_slot,
                    teacher_slot_budget=teacher_slot_budget,
                    room_capacity_by_id=room_capacity_by_id,
                    slot_meta=slot_meta,
                    days_count=days_count,
                    rng=rng,
                    eval_cap=lecture_eval_cap,
                )
            else:
                blocks = lab_blocks_by_span.get(task.span, [])
                assignment = _select_lab_assignment(
                    task,
                    blocks,
                    lab_room_ids_by_faculty,
                    teacher_busy=teacher_busy,
                    group_busy=group_busy,
                    room_busy=room_busy,
                    offering_day_used=offering_day_used,
                    teacher_schedule=teacher_schedule,
                    group_schedule=group_schedule,
                    elective_count_by_slot=elective_count_by_slot,
                    teacher_slot_budget=teacher_slot_budget,
                    room_capacity_by_id=room_capacity_by_id,
                    slot_meta=slot_meta,
                    days_count=days_count,
                    rng=rng,
                    eval_cap=lab_eval_cap,
                )

            if assignment is None:
                break

            room_id, slot_ids = assignment
            _place(
                task,
                room_id,
                slot_ids,
                teacher_busy=teacher_busy,
                group_busy=group_busy,
                room_busy=room_busy,
                out=assignments,
            )
            placed += 1

            day = slot_meta[slot_ids[0]][0]
            offering_day_used[task.offering_id].add(day)
            teacher_key = (task.teacher_id, day)
            group_key = (task.group_id, day)
            for sid in slot_ids:
                index = slot_meta[sid][1]
                teacher_schedule[teacher_key].append(index)
                group_schedule[group_key].append(index)
                if task.is_elective:
                    elective_count_by_slot[sid] += 1

        current_penalty = _score_schedule(assignments, tasks_by_offering, room_capacity_by_id, slot_meta, days_count)
        if placed > best_partial or (placed == best_partial and current_penalty < best_partial_penalty):
            best_partial = placed
            best_partial_penalty = current_penalty
            best_partial_assignments = list(assignments)

        if placed == len(tasks):
            if best_complete_assignments is None or current_penalty < best_complete_penalty:
                best_complete_penalty = current_penalty
                best_complete_assignments = list(assignments)
            if stop_on_first_complete:
                break

    if best_complete_assignments is not None:
        metrics["hard_valid"] = True
        metrics["penalty_total"] = best_complete_penalty
        metrics["fitness"] = max(0.0, 100.0 - min(best_complete_penalty, 100.0))
        metrics["computation_time_ms"] = int((time.perf_counter() - t0) * 1000)
        return {
            "success": True,
            "message": "Timetable generated with hard constraints satisfied and soft-constraint fitness optimization.",
            "assignments": [
                {"offering_id": a.offering_id, "room_id": a.room_id, "timeslot_id": a.timeslot_id}
                for a in best_complete_assignments
            ],
            "metrics": metrics,
        }

    metrics["penalty_total"] = best_partial_penalty if best_partial_penalty != float("inf") else 0.0
    metrics["fitness"] = max(0.0, 100.0 - min(metrics["penalty_total"], 100.0))
    metrics["computation_time_ms"] = int((time.perf_counter() - t0) * 1000)
    timed_out = time.perf_counter() >= deadline
    return {
        "success": False,
        "message": (
            f"Failed to generate a full feasible timetable within limits. Best partial: {best_partial}/{len(tasks)}."
            + (" (Timed out)" if timed_out else "")
        ),
        "assignments": [
            {"offering_id": a.offering_id, "room_id": a.room_id, "timeslot_id": a.timeslot_id}
            for a in best_partial_assignments
        ],
        "metrics": metrics,
    }


def generate_timetable(**kwargs) -> dict:
    return generate_hard_timetable(**kwargs)

