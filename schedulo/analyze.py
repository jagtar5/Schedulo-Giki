"""
Validate formatted_data.py before seeding the database.

Usage:
    python analyze.py

What it checks:
1) Required top-level datasets exist and are lists.
2) Required keys exist in each record.
3) IDs are unique per dataset.
4) Referential integrity for offerings -> course/teacher/group.
5) Basic value sanity (sessions, capacities, day labels, time ordering).
6) Load and feasibility summaries useful for timetable generation.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


VALID_DAYS = {"Mon", "Tue", "Wed", "Thu", "Fri"}
ID_PATTERNS = {
    "courses": re.compile(r"^C\d{3,}$"),
    "teachers": re.compile(r"^T\d{3,}$"),
    "groups": re.compile(r"^G\d{3,}$"),
    "rooms": re.compile(r"^R\d{3,}$"),
    "time_slots": re.compile(r"^TS\d{3,}$"),
    "offerings": re.compile(r"^O\d{3,}$"),
}


def _infer_required_room_type(course: dict[str, Any]) -> str:
    """Keep this aligned with master_algoritham.py lab/lecture inference."""
    code = str(course.get("code", "")).replace(" ", "").upper()
    name = str(course.get("name", "")).upper()
    if "LAB" in name or re.search(r"[A-Z0-9\-]+L$", code):
        return "Lab"
    return "Lecture"


def _load_module(module_path: Path):
    spec = importlib.util.spec_from_file_location("formatted_data", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from: {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _to_minutes(hhmm: str) -> int:
    hh, mm = hhmm.split(":")
    return int(hh) * 60 + int(mm)


def _check_required_list(module: Any, name: str, errors: list[str]) -> list[dict[str, Any]]:
    if not hasattr(module, name):
        errors.append(f"Missing required dataset: `{name}`")
        return []
    value = getattr(module, name)
    if not isinstance(value, list):
        errors.append(f"Dataset `{name}` must be a list, got {type(value).__name__}")
        return []
    return value


def _check_record_keys(
    dataset_name: str,
    rows: list[dict[str, Any]],
    required_keys: set[str],
    errors: list[str],
) -> None:
    for i, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            errors.append(f"`{dataset_name}` row #{i} is not a dict")
            continue
        missing = required_keys - set(row.keys())
        if missing:
            errors.append(f"`{dataset_name}` row #{i} missing keys: {sorted(missing)}")


def _check_unique_ids(
    dataset_name: str,
    rows: list[dict[str, Any]],
    id_key: str,
    errors: list[str],
) -> set[str]:
    seen: set[str] = set()
    dupes: set[str] = set()
    for row in rows:
        rid = row.get(id_key)
        if rid in seen:
            dupes.add(str(rid))
        else:
            seen.add(str(rid))
    if dupes:
        errors.append(f"`{dataset_name}` has duplicate {id_key}: {sorted(dupes)[:10]}")
    return seen


def _check_id_patterns(dataset_name: str, id_values: set[str], errors: list[str]) -> None:
    pattern = ID_PATTERNS.get(dataset_name)
    if pattern is None:
        return
    bad = [v for v in id_values if not pattern.match(v)]
    if bad:
        errors.append(f"`{dataset_name}` has malformed IDs (first 10): {bad[:10]}")


def main() -> int:
    here = Path(__file__).resolve().parent
    data_file = here / "formatted_data.py"
    if not data_file.exists():
        print(f"[FATAL] Missing file: {data_file}")
        return 2

    try:
        mod = _load_module(data_file)
    except Exception as exc:
        print(f"[FATAL] Could not import formatted_data.py: {exc}")
        return 2

    errors: list[str] = []
    warnings: list[str] = []

    courses = _check_required_list(mod, "courses", errors)
    teachers = _check_required_list(mod, "teachers", errors)
    groups = _check_required_list(mod, "groups", errors)
    rooms = _check_required_list(mod, "rooms", errors)
    time_slots = _check_required_list(mod, "time_slots", errors)
    offerings = _check_required_list(mod, "offerings", errors)

    _check_record_keys("courses", courses, {"course_id", "code", "name", "sessions_required", "is_elective"}, errors)
    _check_record_keys("teachers", teachers, {"teacher_id", "name", "department"}, errors)
    _check_record_keys("groups", groups, {"group_id", "name", "total_students"}, errors)
    _check_record_keys("rooms", rooms, {"room_id", "name", "capacity", "room_type"}, errors)
    _check_record_keys("time_slots", time_slots, {"slot_id", "day", "start_time", "end_time"}, errors)
    _check_record_keys("offerings", offerings, {"offering_id", "course_id", "teacher_id", "group_id"}, errors)

    course_ids = _check_unique_ids("courses", courses, "course_id", errors)
    teacher_ids = _check_unique_ids("teachers", teachers, "teacher_id", errors)
    group_ids = _check_unique_ids("groups", groups, "group_id", errors)
    room_ids = _check_unique_ids("rooms", rooms, "room_id", errors)
    slot_ids = _check_unique_ids("time_slots", time_slots, "slot_id", errors)
    offering_ids = _check_unique_ids("offerings", offerings, "offering_id", errors)

    _check_id_patterns("courses", course_ids, errors)
    _check_id_patterns("teachers", teacher_ids, errors)
    _check_id_patterns("groups", group_ids, errors)
    _check_id_patterns("rooms", room_ids, errors)
    _check_id_patterns("time_slots", slot_ids, errors)
    _check_id_patterns("offerings", offering_ids, errors)

    # Referential integrity + offering-level warnings
    for i, o in enumerate(offerings, start=1):
        cid = o.get("course_id")
        tid = o.get("teacher_id")
        gid = o.get("group_id")
        if cid not in course_ids:
            errors.append(f"`offerings` row #{i} references unknown course_id: {cid}")
        if tid not in teacher_ids:
            errors.append(f"`offerings` row #{i} references unknown teacher_id: {tid}")
        if gid not in group_ids:
            errors.append(f"`offerings` row #{i} references unknown group_id: {gid}")

    # Basic value sanity
    for c in courses:
        s = c.get("sessions_required", 0)
        if not isinstance(s, int) or s <= 0:
            errors.append(f"Invalid sessions_required for course {c.get('course_id')}: {s}")
    for g in groups:
        n = g.get("total_students", 0)
        if not isinstance(n, int) or n <= 0:
            warnings.append(f"Non-positive total_students for group {g.get('group_id')}: {n}")
    for r in rooms:
        cap = r.get("capacity", 0)
        rtype = str(r.get("room_type", "")).strip()
        if not isinstance(cap, int) or cap <= 0:
            errors.append(f"Invalid room capacity for room {r.get('room_id')}: {cap}")
        if rtype not in {"Lecture", "Lab"}:
            warnings.append(f"Room {r.get('room_id')} has non-standard room_type: {rtype}")
    for ts in time_slots:
        day = ts.get("day")
        st = ts.get("start_time")
        et = ts.get("end_time")
        if day not in VALID_DAYS:
            errors.append(f"Invalid day in timeslot {ts.get('slot_id')}: {day}")
        try:
            if _to_minutes(st) >= _to_minutes(et):
                errors.append(f"Timeslot {ts.get('slot_id')} has start >= end ({st}-{et})")
        except Exception:
            errors.append(f"Invalid time format in timeslot {ts.get('slot_id')}: {st}-{et}")

    # Duplicate offering tuple check (can be warning instead of hard error)
    offering_tuple_counts = Counter((o.get("course_id"), o.get("teacher_id"), o.get("group_id")) for o in offerings)
    duplicate_tuples = [k for k, v in offering_tuple_counts.items() if v > 1]
    if duplicate_tuples:
        warnings.append(
            f"Duplicate (course_id, teacher_id, group_id) offerings: {len(duplicate_tuples)} tuples "
            "(may be intentional but usually indicates duplicate data)."
        )

    # Feasibility-style summary for quick health check
    sessions_by_course = {c["course_id"]: c["sessions_required"] for c in courses if "course_id" in c}
    total_sessions_required = sum(sessions_by_course.get(o.get("course_id"), 0) for o in offerings)
    total_room_slots = len(rooms) * len(time_slots)
    room_types = Counter(str(r.get("room_type", "")).strip() for r in rooms)
    inferred_lab_courses = sum(1 for c in courses if _infer_required_room_type(c) == "Lab")
    group_load = Counter()
    teacher_load = Counter()
    for o in offerings:
        course_id = o.get("course_id")
        req = sessions_by_course.get(course_id, 0)
        group_load[o.get("group_id")] += req
        teacher_load[o.get("teacher_id")] += req
    max_group_load = max(group_load.values()) if group_load else 0
    max_teacher_load = max(teacher_load.values()) if teacher_load else 0

    # ---- Timetable feasibility audit (for "will algorithm likely finish?") ----
    # These checks do not prove solvability, but they catch hard impossibilities and
    # flag bottlenecks that often cause long runtimes.
    slots_per_week = len(time_slots)
    room_count_by_type = Counter(str(r.get("room_type", "")).strip() for r in rooms)
    total_capacity_by_type = {
        "Lecture": room_count_by_type.get("Lecture", 0) * slots_per_week,
        "Lab": room_count_by_type.get("Lab", 0) * slots_per_week,
    }
    type_demand = Counter()
    for o in offerings:
        cid = o.get("course_id")
        c = next((x for x in courses if x.get("course_id") == cid), None)
        if c is None:
            continue
        required_type = _infer_required_room_type(c)
        type_demand[required_type] += int(c.get("sessions_required", 0))

    # Hard feasibility failures
    if total_sessions_required > total_room_slots:
        errors.append(
            "Infeasible: total required sessions exceed total room-slot capacity "
            f"({total_sessions_required} > {total_room_slots})."
        )
    if type_demand["Lecture"] > total_capacity_by_type["Lecture"]:
        errors.append(
            "Infeasible: lecture demand exceeds lecture room-slot capacity "
            f"({type_demand['Lecture']} > {total_capacity_by_type['Lecture']})."
        )
    if type_demand["Lab"] > total_capacity_by_type["Lab"]:
        errors.append(
            "Infeasible: lab demand exceeds lab room-slot capacity "
            f"({type_demand['Lab']} > {total_capacity_by_type['Lab']})."
        )

    overbooked_groups = [(gid, load) for gid, load in group_load.items() if load > slots_per_week]
    if overbooked_groups:
        errors.append(
            "Infeasible: some student groups require more sessions than available weekly slots "
            f"({slots_per_week}). Examples: {overbooked_groups[:8]}"
        )

    overbooked_teachers = [(tid, load) for tid, load in teacher_load.items() if load > slots_per_week]
    if overbooked_teachers:
        errors.append(
            "Infeasible: some teachers require more sessions than available weekly slots "
            f"({slots_per_week}). Examples: {overbooked_teachers[:8]}"
        )

    # Runtime pressure / bottleneck warnings (solver may feel "stuck")
    if total_room_slots > 0:
        utilization = total_sessions_required / total_room_slots
        if utilization > 0.8:
            warnings.append(
                f"High global utilization ({utilization:.1%}); generation may be slow."
            )
    for rtype in ("Lecture", "Lab"):
        cap = total_capacity_by_type[rtype]
        dem = type_demand[rtype]
        if cap > 0:
            ratio = dem / cap
            if ratio > 0.85:
                warnings.append(
                    f"High {rtype} utilization ({ratio:.1%}); room-type bottleneck likely."
                )

    # Hot pairs: same teacher-group handling many sessions can create local bottlenecks.
    tg_load = Counter()
    for o in offerings:
        req = sessions_by_course.get(o.get("course_id"), 0)
        tg_load[(o.get("teacher_id"), o.get("group_id"))] += req
    hot_pairs = [(k, v) for k, v in tg_load.items() if v >= max(6, slots_per_week // 6)]
    if hot_pairs:
        warnings.append(
            f"{len(hot_pairs)} teacher-group pairs have high shared load; may increase backtracking. "
            f"Top examples: {sorted(hot_pairs, key=lambda x: x[1], reverse=True)[:6]}"
        )

    # Output
    print("=== Data Analysis Report (formatted_data.py) ===")
    print(f"Courses: {len(courses)}")
    print(f"Teachers: {len(teachers)}")
    print(f"Groups: {len(groups)}")
    print(f"Rooms: {len(rooms)} | by type: {dict(room_types)}")
    print(f"Time slots: {len(time_slots)}")
    print(f"Offerings: {len(offerings)}")
    print(f"Total sessions required: {total_sessions_required}")
    print(f"Total room-slot capacity: {total_room_slots}")
    print(
        "Demand by room type: "
        f"Lecture={type_demand['Lecture']}, Lab={type_demand['Lab']}"
    )
    print(
        "Capacity by room type: "
        f"Lecture={total_capacity_by_type['Lecture']}, Lab={total_capacity_by_type['Lab']}"
    )
    print(f"Inferred lab courses: {inferred_lab_courses}")
    print(f"Max sessions assigned to one group (required load): {max_group_load}")
    print(f"Max sessions assigned to one teacher (required load): {max_teacher_load}")
    print("")

    if warnings:
        print("Warnings:")
        for w in warnings:
            print(f"- {w}")
        print("")

    if errors:
        print("Errors:")
        for e in errors:
            print(f"- {e}")
        print("")
        print(f"Result: FAILED ({len(errors)} errors, {len(warnings)} warnings)")
        return 1

    print(f"Result: OK (0 errors, {len(warnings)} warnings)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

