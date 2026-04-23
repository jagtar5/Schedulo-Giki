import random
import re
import time
from collections import Counter, defaultdict

from models import Course, CourseOffering, Room, TimeSlot


DAY_ORDER = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4}


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

    def try_local_repair(order, fail_idx, chosen, teacher_busy, group_busy, room_busy):
        start = max(0, fail_idx - backtrack_window)
        for p in range(start, fail_idx):
            assignment = chosen[p]
            if assignment is not None:
                _unassign(order[p], assignment[0], assignment[1], teacher_busy, group_busy, room_busy)
                chosen[p] = None

        def dfs(pos):
            if pos > fail_idx:
                return True
            task = order[pos]
            for timeslot_id, room_id in _task_options(task, timeslots, candidate_room_ids):
                if _is_free(task, timeslot_id, room_id, teacher_busy, group_busy, room_busy):
                    _assign(task, timeslot_id, room_id, teacher_busy, group_busy, room_busy)
                    chosen[pos] = (timeslot_id, room_id)
                    if dfs(pos + 1):
                        return True
                    _unassign(task, timeslot_id, room_id, teacher_busy, group_busy, room_busy)
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
        chosen = [None] * len(order)

        i = 0
        success = True
        while i < len(order):
            task = order[i]
            placed = False
            for timeslot_id, room_id in _task_options(task, timeslots, candidate_room_ids):
                if _is_free(task, timeslot_id, room_id, teacher_busy, group_busy, room_busy):
                    _assign(task, timeslot_id, room_id, teacher_busy, group_busy, room_busy)
                    chosen[i] = (timeslot_id, room_id)
                    placed = True
                    break

            if placed:
                i += 1
                continue

            repaired = try_local_repair(order, i, chosen, teacher_busy, group_busy, room_busy)
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
