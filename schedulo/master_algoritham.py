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
- A lab session occupies `Course.lab_block_slots` consecutive slots on the same day.
- If `LabCoursePolicy` exists for the lab course, the lab room must be in that `Room.faculty`.
"""

from __future__ import annotations

import random
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import DefaultDict, Iterable, Optional

from models import Course, CourseOffering, LabCoursePolicy, Room, TimeSlot

DAY_ORDER = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4}


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
    if span <= 1:
        return [(ts.id,) for ts in timeslots_in_day]
    if len(timeslots_in_day) < span:
        return []
    return [
        tuple(ts.id for ts in timeslots_in_day[i : i + span])
        for i in range(0, len(timeslots_in_day) - span + 1)
    ]


def _build_tasks(
    offerings: list[CourseOffering],
    courses_by_id: dict[str, Course],
    policies_by_course_id: dict[str, LabCoursePolicy],
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

    demand_by_faculty: Counter[str] = Counter()
    for t in tasks:
        if t.room_type == "Lab" and t.policy_faculty:
            demand_by_faculty[t.policy_faculty] += t.span

    for fac, dem in demand_by_faculty.items():
        cap = len(lab_room_ids_by_faculty.get(fac, [])) * slots_per_week
        if dem > cap:
            return False, f"Infeasible: lab demand exceeds lab capacity for faculty '{fac}' ({dem} > {cap})."

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
    max_restarts: int = 1500,
    seed: int = 42,
    time_limit_s: float = 120.0,
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
        "time_complexity": "O(R * N * K)",
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

    tasks = _order_tasks(_build_tasks(offerings, courses_by_id, policies_by_course_id))
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

    slots_by_day = _timeslots_by_day(timeslots)
    lecture_slot_ids = [ts.id for ts in timeslots]

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

    for restart in range(max_restarts):
        if time.perf_counter() >= deadline:
            break

        metrics["restarts_used"] = restart

        # Fresh RNG per restart so restarts actually explore new schedules.
        rng = random.Random(int(seed) + int(restart))

        teacher_busy: set[tuple[str, str]] = set()
        group_busy: set[tuple[str, str]] = set()
        room_busy: set[tuple[str, str]] = set()
        assignments: list[Assignment] = []

        tasks_run = list(tasks)
        rng.shuffle(tasks_run)
        # Keep the shuffled order; tasks are already fail-first ordered globally.

        placed = 0
        for task in tasks_run:
            if time.perf_counter() >= deadline:
                break

            if task.room_type == "Lecture":
                slot_candidates = list(lecture_slot_ids)
                rng.shuffle(slot_candidates)

                placed_this = False
                for sid in slot_candidates:
                    if time.perf_counter() >= deadline:
                        break
                    if not _people_free(task, (sid,), teacher_busy=teacher_busy, group_busy=group_busy):
                        continue

                    room_candidates = list(lecture_room_ids)
                    rng.shuffle(room_candidates)
                    for rid in room_candidates:
                        if time.perf_counter() >= deadline:
                            break
                        if (rid, sid) in room_busy:
                            continue
                        _place(
                            task,
                            rid,
                            (sid,),
                            teacher_busy=teacher_busy,
                            group_busy=group_busy,
                            room_busy=room_busy,
                            out=assignments,
                        )
                        placed_this = True
                        placed += 1
                        break
                    if placed_this:
                        break

                if not placed_this:
                    break

            else:  # Lab
                blocks = list(lab_blocks_by_span.get(task.span, []))
                rng.shuffle(blocks)
                placed_this = False

                if task.policy_faculty:
                    allowed_rooms = list(lab_room_ids_by_faculty.get(task.policy_faculty, []))
                else:
                    allowed_rooms = [rid for fac in lab_room_ids_by_faculty.values() for rid in fac]
                rng.shuffle(allowed_rooms)

                for block in blocks:
                    if time.perf_counter() >= deadline:
                        break
                    if not _people_free(task, block, teacher_busy=teacher_busy, group_busy=group_busy):
                        continue

                    for rid in allowed_rooms:
                        if time.perf_counter() >= deadline:
                            break
                        if not _room_free(rid, block, room_busy=room_busy):
                            continue
                        _place(
                            task,
                            rid,
                            block,
                            teacher_busy=teacher_busy,
                            group_busy=group_busy,
                            room_busy=room_busy,
                            out=assignments,
                        )
                        placed_this = True
                        placed += 1
                        break

                    if placed_this:
                        break

                if not placed_this:
                    break

        if placed > best_partial:
            best_partial = placed
            best_partial_assignments = list(assignments)

        if placed == len(tasks):
            metrics["hard_valid"] = True
            metrics["computation_time_ms"] = int((time.perf_counter() - t0) * 1000)
            return {
                "success": True,
                "message": "Timetable generated (hard constraints satisfied).",
                "assignments": [
                    {"offering_id": a.offering_id, "room_id": a.room_id, "timeslot_id": a.timeslot_id}
                    for a in assignments
                ],
                "metrics": metrics,
            }

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

