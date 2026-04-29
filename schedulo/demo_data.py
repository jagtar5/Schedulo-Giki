"""
Seed the database with real GIK Institute data from formatted_data.py.
Called from routes.py when the user clicks "Load Demo Data".
"""
import re

from models import db, Teacher, Course, Room, StudentGroup, TimeSlot, CourseOffering, Schedule, LabCoursePolicy
import formatted_data as fd

courses = fd.courses
teachers = fd.teachers
groups = fd.groups
offerings = fd.offerings
rooms = fd.rooms
time_slots = fd.time_slots


def seed_database():
    """Drop existing data and populate with formatted GIK data."""
    # Recreate schema to match latest models (safe for demo reset flow).
    db.drop_all()
    db.create_all()

    # Clear in dependency order
    Schedule.query.delete()
    LabCoursePolicy.query.delete()
    CourseOffering.query.delete()
    TimeSlot.query.delete()
    StudentGroup.query.delete()
    Room.query.delete()
    Course.query.delete()
    Teacher.query.delete()
    db.session.commit()

    # ── Teachers ─────────────────────────────────────────────────────────
    for t in teachers:
        db.session.add(Teacher(
            id=t["teacher_id"],
            name=t["name"],
            department=t["department"],
            max_consecutive=1,
        ))
    db.session.flush()

    # ── Courses ──────────────────────────────────────────────────────────
    for c in courses:
        code = str(c["code"]).replace(" ", "").upper()
        name = str(c["name"]).upper()
        is_lab = ("LAB" in name) or bool(re.search(r"[A-Z0-9\-]+L$", code))
        db.session.add(Course(
            id=c["course_id"],
            code=c["code"],
            name=c["name"],
            sessions_required=c["sessions_required"],
            is_elective=c["is_elective"],
            course_type="Lab" if is_lab else "Theory",
            lab_block_slots=3 if is_lab else 1,
        ))
    db.session.flush()

    # ── Rooms ────────────────────────────────────────────────────────────
    for r in rooms:
        db.session.add(Room(
            id=r["room_id"],
            name=r["name"],
            faculty=r.get("faculty", "General"),
            capacity=r["capacity"],
            room_type=r["room_type"],
        ))
    db.session.flush()

    # ── Student Groups ───────────────────────────────────────────────────
    for g in groups:
        db.session.add(StudentGroup(
            id=g["group_id"],
            name=g["name"],
            total_students=g["total_students"],
        ))
    db.session.flush()

    # ── Time Slots (from formatted_data — real GIK schedule) ───────────
    for ts in time_slots:
        db.session.add(TimeSlot(
            id=ts["slot_id"],
            day=ts["day"],
            start_time=ts["start_time"],
            end_time=ts["end_time"],
        ))
    db.session.flush()

    # ── Course Offerings ─────────────────────────────────────────────────
    for o in offerings:
        db.session.add(CourseOffering(
            id=o["offering_id"],
            course_id=o["course_id"],
            teacher_id=o["teacher_id"],
            group_id=o["group_id"],
        ))

    # ── Lab Course Policies (from formatted_data if present) ─────────────
    formatted_lab_policies = getattr(fd, "LabCoursePolicy", None) or getattr(fd, "lab_course_policies", None) or []
    valid_course_ids = {c["course_id"] for c in courses}
    valid_lab_faculties = {r["faculty"] for r in rooms if r.get("room_type") == "Lab"}
    for p in formatted_lab_policies:
        course_id = p.get("course_id")
        faculty = p.get("faculty")
        if course_id in valid_course_ids and faculty in valid_lab_faculties:
            db.session.add(LabCoursePolicy(course_id=course_id, faculty=faculty))

    db.session.commit()
