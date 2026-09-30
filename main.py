import datetime
import hashlib
import json
import os
from zoneinfo import ZoneInfo

import icalendar

from utils.clean_ics import clean_ics
from utils.generate_html import generate_html
from utils.load_schedule import EXCEL_FILE, load_rooms, load_schedule
from utils.parse_schedule import ACTIVITIES, parse_schedule

TIMEZONE = ZoneInfo("Europe/Warsaw")
TEACHERS_FILE = os.path.join(os.path.dirname(__file__), "data", "teachers.json")
CAMPUS_ADDRESSES = {
    "Czyżyny": "al. Jana Pawła II 37, Kraków",
    "Warszawska": "ul. Warszawska 24, Kraków",
}


def event_location(room: str, rooms: dict) -> str:
    if not room or room == "ONLINE":
        return "Online" if room else ""
    campus = rooms.get(room, {}).get("campus")
    address = CAMPUS_ADDRESSES.get(campus, campus)
    return f"{room}, {address}" if address else room


def room_description(room: str, rooms: dict) -> str:
    if room == "ONLINE":
        return "online (zdalnie)"
    info = rooms.get(room, {})
    name, campus = info.get("name"), info.get("campus")
    # Planner names look like "L4 - 136 (GPU)", keep the code the Excel uses in front
    text = name if name and name.startswith(room) else f"{room} ({name})" if name else room
    return f"{text}, kampus {campus}" if campus and campus not in text else text


def load_teachers() -> dict:
    # Academic titles from the faculty staff list, see scripts/update_teachers.py
    with open(TEACHERS_FILE) as f:
        teachers = json.load(f)
    return {frozenset(name.lower().split()): entry for name, entry in teachers.items()}


def teacher_names(teacher: str, teachers: dict) -> str:
    """ "Białas Jerzy / Skabek Krzysztof" -> "dr inż. Białas Jerzy / Skabek Krzysztof" """
    names = []
    for name in teacher.split(" / "):
        name = name.strip()
        # The plan mixes "Surname Name" and "Name Surname", so match word sets
        entry = teachers.get(frozenset(name.lower().replace("–", "-").split()))
        if entry:
            name = f"{entry['title']} {name}" + (f", {entry['suffix']}" if entry.get("suffix") else "")
        names.append(name)
    return " / ".join(names)


def event_description(rubric, event, rooms: dict, teachers: dict) -> str:
    lines = [f"Prowadzący: {teacher_names(event.teacher, teachers)}"]
    if event.groups:
        lines.append(f"Grupa: {event.groups}")
    lines.append(f"Sala: {room_description(event.room, rooms)}")
    lines.append(f"Zjazd: {event.weekend}")
    lines.append(f"Kalendarz: {rubric.year} · {rubric.label}")
    return "\n".join(lines)


def build_calendar(rubric, rooms: dict, teachers: dict) -> icalendar.Calendar:
    cal = icalendar.Calendar()
    cal.add("prodid", "-//linguin.dev//cut-calendar-ics//PL")
    cal.add("version", "2.0")
    cal.add("X-WR-CALNAME", f"PK {rubric.year} {rubric.label}")
    cal.add("X-WR-TIMEZONE", "Europe/Warsaw")
    # Hint for clients that support it (Apple, Outlook), Google ignores it
    cal.add(
        "REFRESH-INTERVAL",
        icalendar.vDuration(datetime.timedelta(hours=1)),
        parameters={"VALUE": "DURATION"},
    )
    cal.add("X-PUBLISHED-TTL", "PT1H")
    if rubric.events:
        first = min(event.start for event in rubric.events).date()
        last = max(event.end for event in rubric.events).date()
        cal.add_component(
            icalendar.Timezone.from_tzid(
                "Europe/Warsaw",
                first_date=first - datetime.timedelta(days=366),
                last_date=last + datetime.timedelta(days=366),
            )
        )
    now = datetime.datetime.now(datetime.timezone.utc)
    for event in sorted(rubric.events, key=lambda e: (e.start, e.subject)):
        prefix, category = ACTIVITIES.get(event.activity, (event.activity, None))
        # "LAB GL2: Podstawy sieci komputerowych", group exactly as written in the plan
        marker = " ".join(part for part in (prefix, event.groups) if part)
        summary = f"{marker}: {event.subject}" if marker else event.subject
        if event.room == "ONLINE":
            summary = f"ONLINE: {summary}"
        # Stable UID so calendar apps update events instead of duplicating them
        uid_source = f"{rubric.slug}|{event.start.isoformat()}|{event.subject}|{event.activity}"
        uid = hashlib.sha1(uid_source.encode()).hexdigest()

        cal_event = icalendar.Event()
        cal_event.add("uid", f"{uid}@planpk.linguin.dev")
        cal_event.add("summary", summary)
        cal_event.add("dtstart", event.start.replace(tzinfo=TIMEZONE))
        cal_event.add("dtend", event.end.replace(tzinfo=TIMEZONE))
        cal_event.add("dtstamp", now)
        cal_event.add("description", event_description(rubric, event, rooms, teachers))
        # Format independent identity of the event, used by the webhook diff
        cal_event.add("X-PK-KEY", f"{prefix} {event.subject}")
        location = event_location(event.room, rooms)
        if location:
            cal_event.add("location", location)
        if category:
            cal_event.add("categories", [category])
        cal.add_component(cal_event)
    return cal


def set_output(name: str, value: str):
    # Step output read by the workflow, ignored when running locally
    if "GITHUB_OUTPUT" in os.environ:
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"{name}={value}\n")


def main():
    os.makedirs("build", exist_ok=True)
    if not load_schedule():
        set_output("changed", "false")
        return
    clean_ics()

    rubrics = parse_schedule(EXCEL_FILE)
    rooms = load_rooms()
    teachers = load_teachers()

    manifest = []
    for rubric in rubrics:
        file_name = f"{rubric.slug}.ics"
        with open(f"build/{file_name}", "wb") as f:
            f.write(build_calendar(rubric, rooms, teachers).to_ical())
        manifest.append(
            {
                "file": file_name,
                "degree": rubric.degree,
                "year": rubric.year,
                "label": rubric.label,
                "kind": rubric.kind,
                "subject": rubric.subject,
                "group": rubric.group,
                # Shown next to language groups, so people can pick their teacher
                "teachers": sorted({teacher_names(e.teacher, teachers) for e in rubric.events}),
            }
        )

    with open("build/calendars.json", "w") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    generate_html(manifest)
    set_output("changed", "true")


if __name__ == "__main__":
    main()
