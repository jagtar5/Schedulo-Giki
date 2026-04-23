from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


# ── Core Entities ────────────────────────────────────────────────────────────

class Teacher(db.Model):
    __tablename__ = "teachers"
    id = db.Column(db.String(10), primary_key=True)          # "T001", "T002", …
    name = db.Column(db.String(120), nullable=False)
    department = db.Column(db.String(80), nullable=False)
    max_consecutive = db.Column(db.Integer, default=3)

    # Relationships
    offerings = db.relationship("CourseOffering", backref="teacher", lazy=True)

    def __repr__(self):
        return f"<Teacher {self.id} {self.name}>"


class Course(db.Model):
    __tablename__ = "courses"
    id = db.Column(db.String(10), primary_key=True)          # "C001", "C002", …
    code = db.Column(db.String(20), nullable=False)
    name = db.Column(db.String(150), nullable=False)
    sessions_required = db.Column(db.Integer, nullable=False, default=3)
    is_elective = db.Column(db.Boolean, default=False)

    # Relationships
    offerings = db.relationship("CourseOffering", backref="course", lazy=True)

    def __repr__(self):
        return f"<Course {self.code}>"


class Room(db.Model):
    __tablename__ = "rooms"
    id = db.Column(db.String(10), primary_key=True)          # "R001", "R002", …
    name = db.Column(db.String(30), nullable=False)
    faculty = db.Column(db.String(30), nullable=False, default="General")  # Building / faculty
    capacity = db.Column(db.Integer, nullable=False, default=40)
    room_type = db.Column(db.String(20), nullable=False, default="Lecture")  # Lecture / Lab

    # Relationships
    schedules = db.relationship("Schedule", backref="room", lazy=True)

    def __repr__(self):
        return f"<Room {self.name}>"


class StudentGroup(db.Model):
    __tablename__ = "student_groups"
    id = db.Column(db.String(10), primary_key=True)          # "G001", "G002", …
    name = db.Column(db.String(80), nullable=False)
    total_students = db.Column(db.Integer, nullable=False, default=30)

    # Relationships
    offerings = db.relationship("CourseOffering", backref="group", lazy=True)

    def __repr__(self):
        return f"<StudentGroup {self.name}>"


class TimeSlot(db.Model):
    __tablename__ = "time_slots"
    id = db.Column(db.String(10), primary_key=True)          # "TS001", …
    day = db.Column(db.String(10), nullable=False)            # Mon, Tue, …
    start_time = db.Column(db.String(10), nullable=False)     # "08:00"
    end_time = db.Column(db.String(10), nullable=False)       # "09:00"

    # Relationships
    schedules = db.relationship("Schedule", backref="timeslot", lazy=True)

    def __repr__(self):
        return f"<TimeSlot {self.day} {self.start_time}-{self.end_time}>"


# ── Analytical / Junction Entities ───────────────────────────────────────────

class CourseOffering(db.Model):
    """The entity the algorithm actually schedules —
    one specific (Course × Teacher × StudentGroup) instance."""
    __tablename__ = "course_offerings"
    id = db.Column(db.String(10), primary_key=True)          # "O001", …
    course_id = db.Column(db.String(10), db.ForeignKey("courses.id"), nullable=False)
    teacher_id = db.Column(db.String(10), db.ForeignKey("teachers.id"), nullable=False)
    group_id = db.Column(db.String(10), db.ForeignKey("student_groups.id"), nullable=False)

    # Relationships
    schedules = db.relationship("Schedule", backref="offering", lazy=True)

    def __repr__(self):
        return f"<CourseOffering {self.id}>"


class Schedule(db.Model):
    """Output table — populated only when the algorithm runs."""
    __tablename__ = "schedules"
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    offering_id = db.Column(db.String(10), db.ForeignKey("course_offerings.id"), nullable=False)
    room_id = db.Column(db.String(10), db.ForeignKey("rooms.id"), nullable=False)
    timeslot_id = db.Column(db.String(10), db.ForeignKey("time_slots.id"), nullable=False)
