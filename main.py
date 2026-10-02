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
from utils.sync_state import build_digest, set_output, stage_state, summary, validate_build

TIMEZONE = ZoneInfo("Europe/Warsaw")
TEACHERS_FILE = os.path.join(os.path.dirname(__file__), "data", "teachers.json")
COMBOS_FILE = os.path.join(os.path.dirname(__file__), "data", "combos.json")
CAMPUS_ADDRESSES = {
    "Czyżyny": "al. Jana Pawła II 37, Kraków",
    "Warszawska": "ul. Warszawska 24, Kraków",
}


def room_name(room: str, rooms: dict) -> str:
    name = rooms.get(room, {}).get("name")
    # Keep the code from the Excel, including aliases such as S1.
    return name if name and name.startswith(room) else f"{room} ({name})" if name else room


def event_location(room: str, rooms: dict) -> str:
    if not room or room == "ONLINE":
        return "Online" if room else ""
    campus = rooms.get(room, {}).get("campus")
    address = CAMPUS_ADDRESSES.get(campus, campus)
    label = room_name(room, rooms)
    return f"{label}, {address}" if address else label


def room_description(room: str, rooms: dict) -> str:
    if room == "ONLINE":
        return "online (zdalnie)"
    info = rooms.get(room, {})
    campus = info.get("campus")
    # Planner names look like "L4 - 136 (GPU)", keep the code the Excel uses in front
    text = room_name(room, rooms)
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


def new_calendar(name: str, events: list) -> icalendar.Calendar:
    cal = icalendar.Calendar()
    cal.add("prodid", "-//linguin.dev//cut-calendar-ics//PL")
    cal.add("version", "2.0")
    cal.add("X-WR-CALNAME", name)
    cal.add("X-WR-TIMEZONE", "Europe/Warsaw")
    # Hint for clients that support it (Apple, Outlook), Google ignores it
    cal.add(
        "REFRESH-INTERVAL",
        icalendar.vDuration(datetime.timedelta(hours=1)),
        parameters={"VALUE": "DURATION"},
    )
    cal.add("X-PUBLISHED-TTL", "PT1H")
    if events:
        first = min(event["DTSTART"].dt for event in events).date()
        last = max(event["DTEND"].dt for event in events).date()
        cal.add_component(
            icalendar.Timezone.from_tzid(
                "Europe/Warsaw",
                first_date=first - datetime.timedelta(days=366),
                last_date=last + datetime.timedelta(days=366),
            )
        )
    for event in sorted(events, key=lambda e: (e["DTSTART"].dt, str(e["SUMMARY"]))):
        cal.add_component(event)
    return cal


def calendar_events(rubric, rooms: dict, teachers: dict) -> list:
    now = datetime.datetime.now(datetime.timezone.utc)
    events = []
    uid_occurrences = {}
    # Sort tied occurrences so reordering Excel rows does not change their IDs.
    for event in sorted(rubric.events, key=lambda e: (
        e.start, e.subject, e.activity, e.groups, e.room, e.teacher, e.end, e.weekend
    )):
        prefix, category = ACTIVITIES.get(event.activity, (event.activity, None))
        # Display names may change; keep the existing X-PK-KEY prefixes stable.
        display_prefix = "ĆWICZENIA" if event.activity == "C" else prefix
        summary = " ".join(part for part in (display_prefix, event.subject) if part)
        if event.groups:
            summary += f", grupa {event.groups}"
        if event.room == "ONLINE":
            summary = f"‼️ONLINE‼️ – {summary}"
        # Preserve existing UIDs. This scheme keeps room/teacher edits in place,
        # but moving the start or renaming the subject creates a new UID.
        uid_source = f"{rubric.slug}|{event.start.isoformat()}|{event.subject}|{event.activity}"
        uid = hashlib.sha1(uid_source.encode()).hexdigest()
        occurrence = uid_occurrences.get(uid, 0)
        uid_occurrences[uid] = occurrence + 1
        # Preserve existing IDs; distinguish only simultaneous occurrences that
        # share the old identity. Both entries must remain in the full feed.
        if occurrence:
            uid = f"{uid}-{occurrence}"

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
        events.append(cal_event)
    return events


def build_combos(events_by_slug: dict):
    """
    Hidden calendars that are just the sum of existing ones, see data/combos.json.
    They are not listed on the page nor in calendars.json, so the webhook skips them.
    """
    with open(COMBOS_FILE) as f:
        combos = json.load(f)
    for name, parts in combos.items():
        events = {}
        for slug in parts:
            if slug not in events_by_slug:
                # Keep publishing the rest instead of failing every calendar
                print(f"::warning::Combo {name}: calendar {slug} no longer exists")
                continue
            for event in events_by_slug[slug]:
                key = (event["DTSTART"].dt, event["DTEND"].dt, str(event["X-PK-KEY"]),
                       str(event.get("LOCATION", "")),
                       tuple(str(event["DESCRIPTION"]).splitlines()[:-1]))
                events.setdefault(key, event)
        with open(f"build/{name}.ics", "wb") as f:
            f.write(new_calendar(f"PK {name}", list(events.values())).to_ical())


def main():
    state_dir = os.environ.get("SYNC_STATE_DIR")
    previous, old_rooms = None, {}
    if state_dir:
        previous = os.path.join(state_dir, "build")
        with open(os.path.join(state_dir, "state.json")) as f:
            old_rooms = json.load(f)["rooms"]
    os.makedirs("build", exist_ok=True)
    load_schedule()
    rubrics = parse_schedule(EXCEL_FILE)
    rooms = load_rooms(fallback=old_rooms)
    teachers = load_teachers()
    clean_ics()

    manifest = []
    events_by_slug = {}
    for rubric in rubrics:
        file_name = f"{rubric.slug}.ics"
        events = calendar_events(rubric, rooms, teachers)
        events_by_slug[rubric.slug] = events
        with open(f"build/{file_name}", "wb") as f:
            f.write(new_calendar(f"PK {rubric.year} {rubric.label}", events).to_ical())
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

    build_combos(events_by_slug)

    with open("build/calendars.json", "w") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    generate_html(manifest)
    with open(COMBOS_FILE) as f:
        combos = json.load(f)
    counts = validate_build("build", previous=previous, combos=combos)
    changed = (os.environ.get("FORCE_DEPLOY") == "true" or previous is None
               or build_digest("build") != build_digest(previous))
    if state_dir:
        stage_state("build", rooms)
    set_output("changed", str(changed).lower())
    summary(f"Sprawdzono {len(manifest)} grup i {len(combos)} kalendarze łączone; "
            f"{sum(counts.values())} wydarzeń. " + ("Wymagana publikacja." if changed else "Brak zmian."))


if __name__ == "__main__":
    main()
