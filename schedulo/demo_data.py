"""
Seed the database with real GIK Institute data from formatted_data.py.
Called from routes.py when the user clicks "Load Demo Data".
"""
from models import db, Teacher, Course, Room, StudentGroup, TimeSlot, CourseOffering, Schedule
from formatted_data import courses, teachers, groups, offerings, rooms, time_slots


def seed_database():
    """Drop existing data and populate with formatted GIK data."""
    # Clear in dependency order
    Schedule.query.delete()
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
        db.session.add(Course(
            id=c["course_id"],
            code=c["code"],
            name=c["name"],
            sessions_required=c["sessions_required"],
            is_elective=c["is_elective"],
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

    db.session.commit()
