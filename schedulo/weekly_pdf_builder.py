"""
Build context for the weekly-style timetable PDF (days × time columns).
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any


def _minutes(hhmm: str) -> int:
    parts = (hhmm or "00:00").strip().split(":")
    h = int(parts[0]) if parts else 0
    m = int(parts[1]) if len(parts) > 1 else 0
    return h * 60 + m


def _slot_time_key(ts) -> tuple[str, str]:
    return (ts.start_time or "", ts.end_time or "")


def pick_reference_slots(slots_by_day: dict[str, list], days_order: list[str]) -> list:
    for d in days_order:
        slots = slots_by_day.get(d) or []
        if slots:
            return sorted(slots, key=lambda s: (s.start_time or "", s.end_time or "", s.id))
    return []


def build_column_plan(reference_slots: list) -> list[dict[str, Any]]:
    """
    Ordered columns: optional BREAK when gap between consecutive slots is large,
    then slot descriptors with stable time labels for cross-day matching.
    """
    ordered = sorted(reference_slots, key=lambda s: (_minutes(s.start_time), _minutes(s.end_time)))
    out: list[dict[str, Any]] = []
    prev_end_min = None
    min_break_gap_min = 45
    for ts in ordered:
        start_min = _minutes(ts.start_time)
        if prev_end_min is not None and start_min - prev_end_min >= min_break_gap_min:
            out.append({"kind": "break", "label": "BREAK"})
        prev_end_min = _minutes(ts.end_time)
        label = f"{ts.start_time}-{ts.end_time}"
        out.append(
            {
                "kind": "slot",
                "label": label,
                "start": ts.start_time,
                "end": ts.end_time,
                "time_key": _slot_time_key(ts),
            }
        )
    return out


def _day_slot_by_time(slots_for_day: list) -> dict[tuple[str, str], Any]:
    m: dict[tuple[str, str], Any] = {}
    for ts in slots_for_day or []:
        m[_slot_time_key(ts)] = ts
    return m


def consecutive_runs(indices: list[int]) -> list[tuple[int, int]]:
    if not indices:
        return []
    idx = sorted(set(indices))
    runs: list[tuple[int, int]] = []
    a = b = idx[0]
    for x in idx[1:]:
        if x == b + 1:
            b = x
        else:
            runs.append((a, b))
            a = b = x
    runs.append((a, b))
    return runs


def build_weekly_grid_rows(
    *,
    days_order: list[str],
    column_plan: list[dict[str, Any]],
    slots_by_day: dict[str, list],
    schedules: list,
) -> tuple[list[dict[str, Any]], list[str]]:
    """
    Each row = one weekday; list of PdfCell serialized for Jinja.
    """
    color_classes = [
        "pastel-a",
        "pastel-b",
        "pastel-c",
        "pastel-d",
        "pastel-e",
        "pastel-f",
        "pastel-g",
        "pastel-h",
    ]

    def color_class(course_code: str) -> str:
        h = sum(ord(c) for c in (course_code or ""))
        return color_classes[h % len(color_classes)]

    rows_out: list[dict[str, Any]] = []
    day_labels = {
        "Mon": "Monday",
        "Tue": "Tuesday",
        "Wed": "Wednesday",
        "Thu": "Thursday",
        "Fri": "Friday",
    }

    for day in days_order:
        day_slots = slots_by_day.get(day) or []
        by_time = _day_slot_by_time(day_slots)

        # Map column index -> list of schedules in that slot column
        col_schedules: dict[int, list] = defaultdict(list)
        day_schedules = [s for s in schedules if s.timeslot.day == day]
        for sched in day_schedules:
            matched_col = None
            for col_idx, desc in enumerate(column_plan):
                if desc["kind"] != "slot":
                    continue
                key = desc["time_key"]
                ts = by_time.get(key)
                if ts and ts.id == sched.timeslot_id:
                    matched_col = col_idx
                    break
            if matched_col is not None:
                col_schedules[matched_col].append(sched)

        # Offering -> sorted slot column indices it occupies this day
        by_offering_cols: dict[str, list[int]] = defaultdict(list)
        for col_idx, ss in col_schedules.items():
            for s in ss:
                by_offering_cols[s.offering_id].append(col_idx)
        for oid in by_offering_cols:
            by_offering_cols[oid] = sorted(set(by_offering_cols[oid]))

        # Decide merged runs per offering (only if consecutive cols are exclusive to that offering for those cols)
        merge_spans: dict[tuple[int, int], str] = {}  # (start_col,end_col) -> offering_id
        skip_cols: set[int] = set()
        for oid, cols in by_offering_cols.items():
            for start, end in consecutive_runs(cols):
                span_cols = list(range(start, end + 1))
                ok = True
                for ci in span_cols:
                    here = col_schedules.get(ci, [])
                    if not all(s.offering_id == oid for s in here):
                        ok = False
                        break
                if ok and end > start:
                    merge_spans[(start, end)] = oid
                    for ci in span_cols[1:]:
                        skip_cols.add(ci)

        cells: list[dict[str, Any]] = []
        col_idx = 0
        while col_idx < len(column_plan):
            desc = column_plan[col_idx]
            if desc["kind"] == "break":
                cells.append({"kind": "break", "colspan": 1, "blocks": None})
                col_idx += 1
                continue

            if col_idx in skip_cols:
                col_idx += 1
                continue

            # Slot column — colspan merge?
            span_end = col_idx
            offering_for_merge = None
            for (a, b), oid in merge_spans.items():
                if a == col_idx:
                    span_end = b
                    offering_for_merge = oid
                    break

            if offering_for_merge is not None:
                sched = next(
                    s
                    for s in col_schedules[col_idx]
                    if s.offering_id == offering_for_merge
                )
                blocks = [
                    {
                        "course_code": sched.offering.course.code,
                        "venue": sched.room.name if sched.room else "",
                        "css": color_class(sched.offering.course.code),
                    }
                ]
                cells.append(
                    {
                        "kind": "slot",
                        "colspan": span_end - col_idx + 1,
                        "blocks": blocks,
                    }
                )
                col_idx = span_end + 1
                continue

            # Single column (possibly stacked offerings)
            stacked = col_schedules.get(col_idx, [])
            blocks = []
            seen = set()
            for sched in stacked:
                key = (sched.offering_id, sched.timeslot_id)
                if key in seen:
                    continue
                seen.add(key)
                blocks.append(
                    {
                        "course_code": sched.offering.course.code,
                        "venue": sched.room.name if sched.room else "",
                        "css": color_class(sched.offering.course.code),
                    }
                )
            cells.append({"kind": "slot", "colspan": 1, "blocks": blocks if blocks else None})
            col_idx += 1

        rows_out.append(
            {
                "day_key": day,
                "day_title": day_labels.get(day, day),
                "cells": cells,
            }
        )

    header_labels = []
    for desc in column_plan:
        if desc["kind"] == "break":
            header_labels.append(desc.get("label") or "BREAK")
        else:
            header_labels.append(desc["label"])

    return rows_out, header_labels
