"""
Timetable engine: hard constraints (feasibility) + soft constraints (fitness).

Complexity overview (for CS378 report):
- generate_hard_timetable: O(X * N * T * R) time, O(N + T + R) space (see docstring below).
- evaluate_soft_fitness: O(N + G*D*S + H*D) time where N = session rows, G = groups,
  D = weekdays, S = slots per day, H = teachers; effectively linear in N plus a scan
  over (group|teacher) × day buckets built from N assignments. Space O(N + T + G*D + H*D)
  for session lists and index maps.
- generate_timetable: O(K * (hard + soft)) = O(K * X * N * T * R + K * soft) with K = best_of_seeds.
"""
import random
import re
import time
from collections import Counter, defaultdict

from models import Course, CourseOffering, Room, StudentGroup, Teacher, TimeSlot


DAY_ORDER = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4}
DEFAULT_GROUP_CONSEC_CAP = 3


def _infer_required_room_type(course):
    """Infer whether a course needs a Lab or Lecture room."""
    code = (course.code or "").replace(" ", "").upper()
    name = (course.name or "").upper()
    if "LAB" in name:
        return "Lab"
    if re.search(r"[A-Z0-9]+L$", code):
        return "Lab"
    return "Lecture"


def _sorted_timeslots(timeslots):
    return sorted(
        timeslots,
        key=lambda ts: (DAY_ORDER.get(ts.day, 99), ts.start_time, ts.end_time, ts.id),
    )


def _task_options(task, timeslots, candidate_room_ids):
    for ts in timeslots:
        for room_id in candidate_room_ids[task["idx"]]:
            yield (ts.id, room_id)


def _is_free(task, timeslot_id, room_id, teacher_busy, group_busy, room_busy):
    teacher_key = (task["teacher_id"], timeslot_id)
    group_key = (task["group_id"], timeslot_id)
    room_key = (room_id, timeslot_id)
    return (
        teacher_key not in teacher_busy
        and group_key not in group_busy
        and room_key not in room_busy
    )


def _assign(task, timeslot_id, room_id, teacher_busy, group_busy, room_busy):
    teacher_busy.add((task["teacher_id"], timeslot_id))
    group_busy.add((task["group_id"], timeslot_id))
    room_busy.add((room_id, timeslot_id))


def _unassign(task, timeslot_id, room_id, teacher_busy, group_busy, room_busy):
    teacher_busy.remove((task["teacher_id"], timeslot_id))
    group_busy.remove((task["group_id"], timeslot_id))
    room_busy.remove((room_id, timeslot_id))


def _assign_with_placement_meta(
    task, timeslot_id, room_id, teacher_busy, group_busy, room_busy, slot_pos, tg_day_slots, teacher_day_load
):
    """Hard-assign plus structures for same-(teacher,group) spacing and teacher-day balance."""
    _assign(task, timeslot_id, room_id, teacher_busy, group_busy, room_busy)
    day, idx, _ = slot_pos[timeslot_id]
    t, g = task["teacher_id"], task["group_id"]
    tg_day_slots[(t, g, day)].add(idx)
    teacher_day_load[(t, day)] += 1


def _unassign_with_placement_meta(
    task, timeslot_id, room_id, teacher_busy, group_busy, room_busy, slot_pos, tg_day_slots, teacher_day_load
):
    day, idx, _ = slot_pos[timeslot_id]
    t, g = task["teacher_id"], task["group_id"]
    tg_day_slots[(t, g, day)].discard(idx)
    if not tg_day_slots[(t, g, day)]:
        del tg_day_slots[(t, g, day)]
    teacher_day_load[(t, day)] -= 1
    if teacher_day_load[(t, day)] <= 0:
        del teacher_day_load[(t, day)]
    _unassign(task, timeslot_id, room_id, teacher_busy, group_busy, room_busy)


def _ranked_valid_placements(
    task,
    timeslots,
    candidate_room_ids,
    slot_pos,
    tg_day_slots,
    teacher_day_load,
    teacher_busy,
    group_busy,
    room_busy,
):
    """
    Among hard-feasible (slot, room) pairs, prefer:
    1) No back-to-back same teacher + same group on that day (avoid adjacent slot indices).
    2) Lower teacher load on that day (spread workload across weekdays).

    Time: O(T * R) candidates, each O(1) lookups in sets/counters.
    """
    t, g = task["teacher_id"], task["group_id"]
    scored = []
    for ts in timeslots:
        timeslot_id = ts.id
        day, idx, _ = slot_pos[timeslot_id]
        placed = tg_day_slots.get((t, g, day), set())
        adjacent = int((idx - 1) in placed) + int((idx + 1) in placed)
        day_load = int(teacher_day_load.get((t, day), 0))
        for room_id in candidate_room_ids[task["idx"]]:
            if not _is_free(task, timeslot_id, room_id, teacher_busy, group_busy, room_busy):
                continue
            scored.append(
                (
                    adjacent,
                    day_load,
                    DAY_ORDER.get(day, 99),
                    ts.start_time,
                    timeslot_id,
                    room_id,
                )
            )
    scored.sort()
    return [(row[-2], row[-1]) for row in scored]


def _build_day_slot_positions(timeslots):
    """
    Map each timeslot id to (day, index_within_day) for soft-constraint scans.
    Time: O(T), Space: O(T).
    """
    by_day = defaultdict(list)
    for ts in timeslots:
        by_day[ts.day].append(ts)
    for day in by_day:
        by_day[day].sort(key=lambda x: (x.start_time, x.id))
    slot_pos = {}
    for day, lst in by_day.items():
        for i, ts in enumerate(lst):
            slot_pos[ts.id] = (day, i, len(lst))
    return slot_pos, by_day


def _max_run_of_consecutive(sorted_indices):
    """Longest run of consecutive integers; Time O(k) for k sorted indices."""
    if not sorted_indices:
        return 0
    best = run = 1
    for j in range(1, len(sorted_indices)):
        if sorted_indices[j] == sorted_indices[j - 1] + 1:
            run += 1
            best = max(best, run)
        else:
            run = 1
    return best


def _internal_gaps(sorted_indices):
    """Empty slot-indices between first and last class on a day (PRD: student gaps). O(k)."""
    if len(sorted_indices) < 2:
        return 0
    gaps = 0
    for j in range(len(sorted_indices) - 1):
        gaps += max(0, sorted_indices[j + 1] - sorted_indices[j] - 1)
    return gaps


def evaluate_soft_fitness(assignments):
    """
    PRD soft constraints as additive penalties; fitness = max(0, min(100, 100 - penalty/55))
    (higher is better; same formula across seeds so argmax is order-preserving).

    Implemented (simple proxies, all explainable in a report):
    1) Student gaps — per (group, day): internal free slots between first/last class.
    2) Consecutive cap — per (teacher, day) and (group, day): penalize runs over cap
       (teacher cap from DB max_consecutive; group uses DEFAULT_GROUP_CONSEC_CAP).
    3) Capacity — penalize overcrowding; mild penalty for very under-filled rooms.
    4) Workload spread — per teacher: (max sessions on a day) - (min over active days).
    5) Electives — per (group, day): penalize stacking multiple elective sessions same day.

    Time complexity: O(N) to build session rows + O(B) over buckets B = sum over
    (groups, teachers) × days with entries; B <= N in practice. Dominated by O(N + T)
    for maps plus bucket scans ~ O(N).
    Space: O(N) for session list + O(G*D + H*D) for bucket keys.
    """
    if not assignments:
        return {
            "fitness": 0.0,
            "penalty_total": 0.0,
            "breakdown": {},
            "soft_time_complexity": "O(N + G*D + H*D)",
        }

    offerings = {o.id: o for o in CourseOffering.query.all()}
    courses = {c.id: c for c in Course.query.all()}
    rooms = {r.id: r for r in Room.query.all()}
    groups = {g.id: g for g in StudentGroup.query.all()}
    teachers = {t.id: t for t in Teacher.query.all()}
    timeslots = _sorted_timeslots(TimeSlot.query.all())
    slot_pos, _by_day = _build_day_slot_positions(timeslots)

    sessions = []
    for a in assignments:
        oid = a["offering_id"]
        o = offerings.get(oid)
        if o is None:
            continue
        c = courses.get(o.course_id)
        r = rooms.get(a["room_id"])
        ts_id = a["timeslot_id"]
        pos = slot_pos.get(ts_id)
        if c is None or r is None or pos is None:
            continue
        day, idx, _n_in_day = pos
        sessions.append(
            {
                "offering_id": oid,
                "group_id": o.group_id,
                "teacher_id": o.teacher_id,
                "course_id": o.course_id,
                "is_elective": bool(c.is_elective),
                "day": day,
                "slot_idx": idx,
                "students": int(groups[o.group_id].total_students) if o.group_id in groups else 30,
                "capacity": int(r.capacity),
            }
        )

    # Same offering = same teacher + same group + same course; penalize back-to-back on one day.
    penalty_same_offering_adjacent = 0.0
    by_offering_day = defaultdict(list)
    for s in sessions:
        by_offering_day[(s["offering_id"], s["day"])].append(s["slot_idx"])
    for _key, idxs in by_offering_day.items():
        idxs = sorted(idxs)
        for j in range(len(idxs) - 1):
            if idxs[j + 1] == idxs[j] + 1:
                penalty_same_offering_adjacent += 10.0

    # --- 1) Gaps + 2) consecutive (group) + 5) electives per (group, day) ---
    by_group_day = defaultdict(list)  # (g, day) -> list of slot_idx
    by_teacher_day = defaultdict(list)
    elective_group_day = defaultdict(int)

    for s in sessions:
        by_group_day[(s["group_id"], s["day"])].append(s["slot_idx"])
        by_teacher_day[(s["teacher_id"], s["day"])].append(s["slot_idx"])
        if s["is_elective"]:
            elective_group_day[(s["group_id"], s["day"])] += 1

    penalty_gaps = 0.0
    penalty_group_consec = 0.0
    penalty_elective_stack = 0.0

    for key, idxs in by_group_day.items():
        idxs = sorted(idxs)
        penalty_gaps += 1.5 * _internal_gaps(idxs)
        run = _max_run_of_consecutive(idxs)
        if run > DEFAULT_GROUP_CONSEC_CAP:
            penalty_group_consec += 2.0 * (run - DEFAULT_GROUP_CONSEC_CAP)

    for (_g, _d), cnt in elective_group_day.items():
        if cnt > 1:
            penalty_elective_stack += 3.0 * (cnt - 1)

    penalty_teacher_consec = 0.0
    for (tid, _day), idxs in by_teacher_day.items():
        idxs = sorted(idxs)
        tchr = teachers.get(tid)
        cap = int(tchr.max_consecutive) if tchr and tchr.max_consecutive else DEFAULT_GROUP_CONSEC_CAP
        run = _max_run_of_consecutive(idxs)
        if run > cap:
            penalty_teacher_consec += 3.5 * (run - cap)

    # --- 3) Capacity (PRD: avoid severe mismatch; lecture halls > section size is normal) ---
    penalty_capacity = 0.0
    for s in sessions:
        st, cap = s["students"], s["capacity"]
        if st > cap:
            penalty_capacity += 8.0 * (st - cap)
        elif st > 0 and cap > 4 * st + 30:
            penalty_capacity += 0.2 * (cap - 4 * st - 30)

    # --- 4) Teacher workload spread across days ---
    penalty_spread = 0.0
    by_teacher = defaultdict(Counter)
    for s in sessions:
        by_teacher[s["teacher_id"]][s["day"]] += 1
    for _tid, day_counts in by_teacher.items():
        if len(day_counts) < 2:
            continue
        counts = list(day_counts.values())
        penalty_spread += 4.0 * (max(counts) - min(counts))

    penalty_total = (
        penalty_gaps
        + penalty_group_consec
        + penalty_teacher_consec
        + penalty_capacity
        + penalty_spread
        + penalty_elective_stack
        + penalty_same_offering_adjacent
    )
    # Simple interpretable map for UI/report: linear in total penalty, capped [0, 100].
    # Tuning divisor scales how strict "100" is; multi-seed search still compares relative totals.
    fitness = max(0.0, min(100.0, round(100.0 - penalty_total / 55.0, 2)))

    return {
        "fitness": fitness,
        "penalty_total": round(penalty_total, 2),
        "breakdown": {
            "gaps": round(penalty_gaps, 2),
            "group_consecutive": round(penalty_group_consec, 2),
            "teacher_consecutive": round(penalty_teacher_consec, 2),
            "capacity": round(penalty_capacity, 2),
            "teacher_day_spread": round(penalty_spread, 2),
            "elective_same_day": round(penalty_elective_stack, 2),
            "same_offering_adjacent_slots": round(penalty_same_offering_adjacent, 2),
        },
        "soft_time_complexity": "O(N + G*D + H*D)",
    }


def generate_timetable(best_of_seeds=3, **hard_kwargs):
    """
    Run hard-constraint solver with several seeds; keep feasible schedule with best soft fitness.

    Time: O(K * T_hard + K * T_soft) with K = best_of_seeds, T_soft = O(N) from evaluate_soft_fitness.
    Space: O(N) for the best assignment kept in memory.
    """
    t0 = time.perf_counter()
    last_hard = None
    best = None
    best_fitness = -1.0

    for k in range(best_of_seeds):
        seed = 42 + k * 97
        res = generate_hard_timetable(seed=seed, **hard_kwargs)
        last_hard = res
        if not res.get("success"):
            continue
        soft = evaluate_soft_fitness(res["assignments"])
        fit = soft["fitness"]
        if fit > best_fitness:
            best_fitness = fit
            merged_metrics = dict(res.get("metrics", {}))
            merged_metrics["fitness"] = soft["fitness"]
            merged_metrics["penalty_total"] = soft["penalty_total"]
            merged_metrics["soft_breakdown"] = soft["breakdown"]
            merged_metrics["soft_time_complexity"] = soft["soft_time_complexity"]
            merged_metrics["generate_timetable_time_complexity"] = (
                f"O(K * (X*N*T*R + N)), K={best_of_seeds}"
            )
            best = {
                "success": True,
                "message": "Timetable generated (hard constraints satisfied; best soft fitness over seeds).",
                "assignments": res["assignments"],
                "metrics": merged_metrics,
                "seeds_tried": k + 1,
            }

    if best is not None:
        best["metrics"]["computation_time_ms"] = int((time.perf_counter() - t0) * 1000)
        best["metrics"]["seeds_evaluated"] = best.get("seeds_tried", best_of_seeds)
        return best

    if last_hard is not None:
        last_hard["metrics"]["computation_time_ms"] = int((time.perf_counter() - t0) * 1000)
        return last_hard

    return {
        "success": False,
        "message": "No feasible timetable from any seed.",
        "assignments": [],
        "metrics": {
            "computation_time_ms": int((time.perf_counter() - t0) * 1000),
            "fitness": 0.0,
        },
    }


def generate_hard_timetable(max_restarts=20, backtrack_window=8, seed=42):
    """
    Hard-constraints-only timetable generator.
    Hybrid approach: greedy assignment + bounded local backtracking + random restarts.

    Complexity (matching implementation):
    - Let N = total session tasks, T = time slots, R = candidate rooms/task, X = restarts.
    - Time: O(X * N * T * R) in bounded practical worst-case.
      The local repair explores only a bounded window (`backtrack_window`), so it is a
      capped additive overhead in practice.
    - Space: O(N + T + R) for task state, occupancy sets, and candidates.
    """
    t0 = time.perf_counter()

    courses = {c.id: c for c in Course.query.all()}
    rooms = Room.query.all()
    offerings = CourseOffering.query.all()
    timeslots = _sorted_timeslots(TimeSlot.query.all())
    slot_pos, _ = _build_day_slot_positions(timeslots)

    if not offerings or not rooms or not timeslots:
        return {
            "success": False,
            "message": "Missing offerings, rooms, or timeslots. Please load data first.",
            "assignments": [],
            "metrics": {
                "computation_time_ms": int((time.perf_counter() - t0) * 1000),
                "time_complexity": "O(X * N * T * R)",
                "space_complexity": "O(N + T + R)",
                "total_tasks": 0,
            },
        }

    room_ids_by_type = defaultdict(list)
    for room in rooms:
        room_type = (room.room_type or "Lecture").strip()
        room_ids_by_type[room_type].append(room.id)

    tasks = []
    teacher_load = Counter()
    group_load = Counter()
    for offering in offerings:
        course = courses.get(offering.course_id)
        if course is None:
            continue
        required_type = _infer_required_room_type(course)
        sessions = max(1, int(course.sessions_required or 1))
        for session_index in range(sessions):
            tasks.append(
                {
                    "offering_id": offering.id,
                    "teacher_id": offering.teacher_id,
                    "group_id": offering.group_id,
                    "required_type": required_type,
                    "session_index": session_index,
                }
            )
            teacher_load[offering.teacher_id] += 1
            group_load[offering.group_id] += 1

    for i, task in enumerate(tasks):
        task["idx"] = i

    candidate_room_ids = {}
    for task in tasks:
        room_candidates = room_ids_by_type.get(task["required_type"], [])
        if not room_candidates:
            return {
                "success": False,
                "message": f"No rooms available for type '{task['required_type']}'.",
                "assignments": [],
                "metrics": {
                    "computation_time_ms": int((time.perf_counter() - t0) * 1000),
                    "time_complexity": "O(X * N * T * R)",
                    "space_complexity": "O(N + T + R)",
                    "total_tasks": len(tasks),
                },
            }
        candidate_room_ids[task["idx"]] = list(room_candidates)

    base_order = list(tasks)
    base_order.sort(
        key=lambda task: (
            len(candidate_room_ids[task["idx"]]),
            -(teacher_load[task["teacher_id"]] + group_load[task["group_id"]]),
            task["offering_id"],
            task["session_index"],
        )
    )

    rng = random.Random(seed)

    def try_local_repair(
        order, fail_idx, chosen, teacher_busy, group_busy, room_busy, tg_day_slots, teacher_day_load
    ):
        start = max(0, fail_idx - backtrack_window)
        for p in range(start, fail_idx):
            assignment = chosen[p]
            if assignment is not None:
                ts_id, room_id = assignment
                _unassign_with_placement_meta(
                    order[p], ts_id, room_id, teacher_busy, group_busy, room_busy, slot_pos, tg_day_slots, teacher_day_load
                )
                chosen[p] = None

        def dfs(pos):
            if pos > fail_idx:
                return True
            task = order[pos]
            for timeslot_id, room_id in _ranked_valid_placements(
                task,
                timeslots,
                candidate_room_ids,
                slot_pos,
                tg_day_slots,
                teacher_day_load,
                teacher_busy,
                group_busy,
                room_busy,
            ):
                _assign_with_placement_meta(
                    task,
                    timeslot_id,
                    room_id,
                    teacher_busy,
                    group_busy,
                    room_busy,
                    slot_pos,
                    tg_day_slots,
                    teacher_day_load,
                )
                chosen[pos] = (timeslot_id, room_id)
                if dfs(pos + 1):
                    return True
                _unassign_with_placement_meta(
                    task,
                    timeslot_id,
                    room_id,
                    teacher_busy,
                    group_busy,
                    room_busy,
                    slot_pos,
                    tg_day_slots,
                    teacher_day_load,
                )
                chosen[pos] = None
            return False

        return dfs(start)

    for restart in range(max_restarts):
        order = list(base_order)
        if restart > 0:
            rng.shuffle(order)
            order.sort(
                key=lambda task: (
                    len(candidate_room_ids[task["idx"]]),
                    -(teacher_load[task["teacher_id"]] + group_load[task["group_id"]]),
                )
            )

        teacher_busy = set()
        group_busy = set()
        room_busy = set()
        tg_day_slots = defaultdict(set)
        teacher_day_load = defaultdict(int)
        chosen = [None] * len(order)

        i = 0
        success = True
        while i < len(order):
            task = order[i]
            placed = False
            # Greedy: O(T * R log(T*R)) to sort valid placements; prefer no adjacent same-(teacher,group) and balanced teacher-days.
            ranked = _ranked_valid_placements(
                task,
                timeslots,
                candidate_room_ids,
                slot_pos,
                tg_day_slots,
                teacher_day_load,
                teacher_busy,
                group_busy,
                room_busy,
            )
            for timeslot_id, room_id in ranked:
                _assign_with_placement_meta(
                    task,
                    timeslot_id,
                    room_id,
                    teacher_busy,
                    group_busy,
                    room_busy,
                    slot_pos,
                    tg_day_slots,
                    teacher_day_load,
                )
                chosen[i] = (timeslot_id, room_id)
                placed = True
                break

            if placed:
                i += 1
                continue

            repaired = try_local_repair(
                order, i, chosen, teacher_busy, group_busy, room_busy, tg_day_slots, teacher_day_load
            )
            if repaired:
                i += 1
            else:
                success = False
                break

        if success:
            assignments = []
            for idx, task in enumerate(order):
                timeslot_id, room_id = chosen[idx]
                assignments.append(
                    {
                        "offering_id": task["offering_id"],
                        "timeslot_id": timeslot_id,
                        "room_id": room_id,
                    }
                )

            elapsed_ms = int((time.perf_counter() - t0) * 1000)
            return {
                "success": True,
                "message": "Timetable generated with hard constraints satisfied.",
                "assignments": assignments,
                "metrics": {
                    "computation_time_ms": elapsed_ms,
                    "time_complexity": "O(X * N * T * R), with bounded local repair window",
                    "space_complexity": "O(N + T + R)",
                    "total_tasks": len(tasks),
                    "restarts_used": restart + 1,
                    "hard_valid": True,
                },
            }

    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    return {
        "success": False,
        "message": "Unable to find a hard-constraint-valid timetable with current restart bounds.",
        "assignments": [],
        "metrics": {
            "computation_time_ms": elapsed_ms,
            "time_complexity": "O(X * N * T * R), with bounded local repair window",
            "space_complexity": "O(N + T + R)",
            "total_tasks": len(tasks),
            "restarts_used": max_restarts,
            "hard_valid": False,
        },
    }
