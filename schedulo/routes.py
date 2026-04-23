from flask import Blueprint, render_template, request, redirect, url_for, flash
from models import db, Teacher, Course, Room, StudentGroup, TimeSlot, CourseOffering, Schedule

main = Blueprint("main", __name__)


# ── Helper: generate next sequential string ID ──────────────────────────────

def _next_id(model, prefix):
    """Return the next available string ID like T079, C077, etc."""
    last = model.query.order_by(model.id.desc()).first()
    if last:
        num = int(last.id[len(prefix):]) + 1
    else:
        num = 1
    return f"{prefix}{num:03d}"


# ── Landing Page ─────────────────────────────────────────────────────────────

@main.route("/")
def index():
    stats = {
        "teachers": Teacher.query.count(),
        "courses": Course.query.count(),
        "rooms": Room.query.count(),
        "groups": StudentGroup.query.count(),
        "timeslots": TimeSlot.query.count(),
        "offerings": CourseOffering.query.count(),
        "schedules": Schedule.query.count(),
    }
    return render_template("index.html", stats=stats)


# ── Demo Data Loader ─────────────────────────────────────────────────────────

@main.route("/load-demo", methods=["POST"])
def load_demo():
    from demo_data import seed_database
    seed_database()
    flash("Demo data loaded successfully! (76 courses, 78 teachers, 50 rooms, 30 groups, 25 time slots, 153 offerings)", "success")
    return redirect(url_for("main.index"))


@main.route("/clear-data", methods=["POST"])
def clear_data():
    Schedule.query.delete()
    CourseOffering.query.delete()
    TimeSlot.query.delete()
    StudentGroup.query.delete()
    Room.query.delete()
    Course.query.delete()
    Teacher.query.delete()
    db.session.commit()
    flash("All data cleared.", "warning")
    return redirect(url_for("main.index"))


# ══════════════════════════════════════════════════════════════════════════════
#  TEACHER CRUD
# ══════════════════════════════════════════════════════════════════════════════

@main.route("/teachers")
def teachers():
    items = Teacher.query.order_by(Teacher.id).all()
    return render_template("manage_teachers.html", items=items)


@main.route("/teachers/add", methods=["POST"])
def add_teacher():
    t = Teacher(
        id=_next_id(Teacher, "T"),
        name=request.form["name"],
        department=request.form["department"],
        max_consecutive=int(request.form.get("max_consecutive", 3)),
    )
    db.session.add(t)
    db.session.commit()
    flash(f"Teacher '{t.name}' added as {t.id}.", "success")
    return redirect(url_for("main.teachers"))


@main.route("/teachers/<string:id>/edit", methods=["POST"])
def edit_teacher(id):
    t = Teacher.query.get_or_404(id)
    t.name = request.form["name"]
    t.department = request.form["department"]
    t.max_consecutive = int(request.form.get("max_consecutive", 3))
    db.session.commit()
    flash(f"Teacher '{t.name}' updated.", "info")
    return redirect(url_for("main.teachers"))


@main.route("/teachers/<string:id>/delete", methods=["POST"])
def delete_teacher(id):
    t = Teacher.query.get_or_404(id)
    db.session.delete(t)
    db.session.commit()
    flash("Teacher deleted.", "warning")
    return redirect(url_for("main.teachers"))


# ══════════════════════════════════════════════════════════════════════════════
#  COURSE CRUD
# ══════════════════════════════════════════════════════════════════════════════

@main.route("/courses")
def courses():
    items = Course.query.order_by(Course.code).all()
    return render_template("manage_courses.html", items=items)


@main.route("/courses/add", methods=["POST"])
def add_course():
    c = Course(
        id=_next_id(Course, "C"),
        code=request.form["code"],
        name=request.form["name"],
        sessions_required=int(request.form.get("sessions_required", 3)),
        is_elective="is_elective" in request.form,
    )
    db.session.add(c)
    db.session.commit()
    flash(f"Course '{c.code}' added as {c.id}.", "success")
    return redirect(url_for("main.courses"))


@main.route("/courses/<string:id>/edit", methods=["POST"])
def edit_course(id):
    c = Course.query.get_or_404(id)
    c.code = request.form["code"]
    c.name = request.form["name"]
    c.sessions_required = int(request.form.get("sessions_required", 3))
    c.is_elective = "is_elective" in request.form
    db.session.commit()
    flash(f"Course '{c.code}' updated.", "info")
    return redirect(url_for("main.courses"))


@main.route("/courses/<string:id>/delete", methods=["POST"])
def delete_course(id):
    c = Course.query.get_or_404(id)
    db.session.delete(c)
    db.session.commit()
    flash("Course deleted.", "warning")
    return redirect(url_for("main.courses"))


# ══════════════════════════════════════════════════════════════════════════════
#  ROOM CRUD
# ══════════════════════════════════════════════════════════════════════════════

@main.route("/rooms")
def rooms():
    items = Room.query.order_by(Room.id).all()
    return render_template("manage_rooms.html", items=items)


@main.route("/rooms/add", methods=["POST"])
def add_room():
    r = Room(
        id=_next_id(Room, "R"),
        name=request.form["name"],
        faculty=request.form.get("faculty", "General"),
        capacity=int(request.form.get("capacity", 40)),
        room_type=request.form.get("room_type", "Lecture"),
    )
    db.session.add(r)
    db.session.commit()
    flash(f"Room '{r.name}' added as {r.id}.", "success")
    return redirect(url_for("main.rooms"))


@main.route("/rooms/<string:id>/edit", methods=["POST"])
def edit_room(id):
    r = Room.query.get_or_404(id)
    r.name = request.form["name"]
    r.faculty = request.form.get("faculty", "General")
    r.capacity = int(request.form.get("capacity", 40))
    r.room_type = request.form.get("room_type", "Lecture")
    db.session.commit()
    flash(f"Room '{r.name}' updated.", "info")
    return redirect(url_for("main.rooms"))


@main.route("/rooms/<string:id>/delete", methods=["POST"])
def delete_room(id):
    r = Room.query.get_or_404(id)
    db.session.delete(r)
    db.session.commit()
    flash("Room deleted.", "warning")
    return redirect(url_for("main.rooms"))


# ══════════════════════════════════════════════════════════════════════════════
#  STUDENT GROUP CRUD
# ══════════════════════════════════════════════════════════════════════════════

@main.route("/groups")
def groups():
    items = StudentGroup.query.order_by(StudentGroup.id).all()
    return render_template("manage_groups.html", items=items)


@main.route("/groups/add", methods=["POST"])
def add_group():
    g = StudentGroup(
        id=_next_id(StudentGroup, "G"),
        name=request.form["name"],
        total_students=int(request.form.get("total_students", 30)),
    )
    db.session.add(g)
    db.session.commit()
    flash(f"Group '{g.name}' added as {g.id}.", "success")
    return redirect(url_for("main.groups"))


@main.route("/groups/<string:id>/edit", methods=["POST"])
def edit_group(id):
    g = StudentGroup.query.get_or_404(id)
    g.name = request.form["name"]
    g.total_students = int(request.form.get("total_students", 30))
    db.session.commit()
    flash(f"Group '{g.name}' updated.", "info")
    return redirect(url_for("main.groups"))


@main.route("/groups/<string:id>/delete", methods=["POST"])
def delete_group(id):
    g = StudentGroup.query.get_or_404(id)
    db.session.delete(g)
    db.session.commit()
    flash("Group deleted.", "warning")
    return redirect(url_for("main.groups"))


# ══════════════════════════════════════════════════════════════════════════════
#  TIME SLOT CRUD
# ══════════════════════════════════════════════════════════════════════════════

@main.route("/timeslots")
def timeslots():
    items = TimeSlot.query.order_by(TimeSlot.day, TimeSlot.start_time).all()
    return render_template("manage_timeslots.html", items=items)


@main.route("/timeslots/add", methods=["POST"])
def add_timeslot():
    ts = TimeSlot(
        id=_next_id(TimeSlot, "TS"),
        day=request.form["day"],
        start_time=request.form["start_time"],
        end_time=request.form["end_time"],
    )
    db.session.add(ts)
    db.session.commit()
    flash(f"Time Slot '{ts.day} {ts.start_time}–{ts.end_time}' added.", "success")
    return redirect(url_for("main.timeslots"))


@main.route("/timeslots/<string:id>/edit", methods=["POST"])
def edit_timeslot(id):
    ts = TimeSlot.query.get_or_404(id)
    ts.day = request.form["day"]
    ts.start_time = request.form["start_time"]
    ts.end_time = request.form["end_time"]
    db.session.commit()
    flash("Time Slot updated.", "info")
    return redirect(url_for("main.timeslots"))


@main.route("/timeslots/<string:id>/delete", methods=["POST"])
def delete_timeslot(id):
    ts = TimeSlot.query.get_or_404(id)
    db.session.delete(ts)
    db.session.commit()
    flash("Time Slot deleted.", "warning")
    return redirect(url_for("main.timeslots"))


# ══════════════════════════════════════════════════════════════════════════════
#  COURSE OFFERING CRUD
# ══════════════════════════════════════════════════════════════════════════════

@main.route("/offerings")
def offerings():
    items = CourseOffering.query.order_by(CourseOffering.id).all()
    all_teachers = Teacher.query.order_by(Teacher.name).all()
    all_courses = Course.query.order_by(Course.code).all()
    all_groups = StudentGroup.query.order_by(StudentGroup.name).all()
    return render_template(
        "manage_offerings.html",
        items=items,
        teachers=all_teachers,
        courses=all_courses,
        groups=all_groups,
    )


@main.route("/offerings/add", methods=["POST"])
def add_offering():
    o = CourseOffering(
        id=_next_id(CourseOffering, "O"),
        course_id=request.form["course_id"],
        teacher_id=request.form["teacher_id"],
        group_id=request.form["group_id"],
    )
    db.session.add(o)
    db.session.commit()
    flash(f"Course Offering {o.id} added.", "success")
    return redirect(url_for("main.offerings"))


@main.route("/offerings/<string:id>/edit", methods=["POST"])
def edit_offering(id):
    o = CourseOffering.query.get_or_404(id)
    o.course_id = request.form["course_id"]
    o.teacher_id = request.form["teacher_id"]
    o.group_id = request.form["group_id"]
    db.session.commit()
    flash(f"Course Offering {o.id} updated.", "info")
    return redirect(url_for("main.offerings"))


@main.route("/offerings/<string:id>/delete", methods=["POST"])
def delete_offering(id):
    o = CourseOffering.query.get_or_404(id)
    db.session.delete(o)
    db.session.commit()
    flash("Course Offering deleted.", "warning")
    return redirect(url_for("main.offerings"))


# ══════════════════════════════════════════════════════════════════════════════
#  TIMETABLE VIEW & GENERATE (Phase 2 placeholder)
# ══════════════════════════════════════════════════════════════════════════════

@main.route("/timetable")
def timetable():
    schedules = Schedule.query.all()
    timeslots = TimeSlot.query.order_by(TimeSlot.start_time).all()
    days = ["Mon", "Tue", "Wed", "Thu", "Fri"]

    # Build unique sorted time ranges
    time_ranges = sorted(
        list({(ts.start_time, ts.end_time) for ts in timeslots}),
        key=lambda x: x[0],
    )

    # Build grid: grid[day][time_range] = list of schedule entries
    grid = {}
    for day in days:
        grid[day] = {}
        for tr in time_ranges:
            grid[day][tr] = []

    for s in schedules:
        ts = s.timeslot
        key = (ts.start_time, ts.end_time)
        if ts.day in grid and key in grid[ts.day]:
            grid[ts.day][key].append(s)

    return render_template(
        "timetable.html",
        grid=grid,
        days=days,
        time_ranges=time_ranges,
        total=len(schedules),
    )


@main.route("/generate", methods=["POST"])
def generate():
    flash("⚙️ Algorithm engine is not implemented yet — coming in Phase 2!", "info")
    return redirect(url_for("main.timetable"))
