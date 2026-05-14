import re
from formatted_data import courses, rooms

lecture = sum(
    1
    for c in courses
    if not ("LAB" in c["name"].upper() or re.search(r"[A-Z0-9\-]+L$", c["code"].upper()))
)
lab = len(courses) - lecture
print("courses total", len(courses), "lecture", lecture, "lab", lab)
print(
    "lecture sample",
    [
        c["code"]
        for c in courses
        if not ("LAB" in c["name"].upper() or re.search(r"[A-Z0-9\-]+L$", c["code"].upper()))
    ][:10],
)
print(
    "lab sample",
    [
        c["code"]
        for c in courses
        if ("LAB" in c["name"].upper() or re.search(r"[A-Z0-9\-]+L$", c["code"].upper()))
    ][:10],
)
print(
    "rooms total",
    len(rooms),
    "lecture rooms",
    sum(1 for r in rooms if r["room_type"] == "Lecture"),
    "lab rooms",
    sum(1 for r in rooms if r["room_type"] == "Lab"),
)
