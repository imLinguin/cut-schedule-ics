import datetime
import hashlib
import json
import os
from zoneinfo import ZoneInfo

import icalendar

from utils.clean_ics import clean_ics
from utils.generate_html import generate_html
from utils.load_schedule import EXCEL_FILE, load_room_campuses, load_schedule
from utils.parse_schedule import ACTIVITIES, parse_schedule

TIMEZONE = ZoneInfo("Europe/Warsaw")
CAMPUS_ADDRESSES = {
    "Czyżyny": "al. Jana Pawła II 37, Kraków",
    "Warszawska": "ul. Warszawska 24, Kraków",
}


def event_location(room: str, campuses: dict) -> str:
    if not room or room == "ONLINE":
        return "Online" if room else ""
    campus = campuses.get(room)
    address = CAMPUS_ADDRESSES.get(campus, campus)
    return f"{room}, {address}" if address else room


def build_calendar(rubric, campuses: dict) -> icalendar.Calendar:
    cal = icalendar.Calendar()
    cal.add("prodid", "-//linguin.dev//cut-calendar-ics//PL")
    cal.add("version", "2.0")
    cal.add("X-WR-CALNAME", f"PK {rubric.year} {rubric.label}")
    cal.add("X-WR-TIMEZONE", "Europe/Warsaw")
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
        short, category = ACTIVITIES.get(event.activity, (event.activity, None))
        summary = f"{event.subject} ({short})" if short else event.subject
        # Stable UID so calendar apps update events instead of duplicating them
        uid_source = f"{rubric.slug}|{event.start.isoformat()}|{event.subject}|{event.activity}"
        uid = hashlib.sha1(uid_source.encode()).hexdigest()

        description = [event.teacher]
        if event.groups:
            description.append(f"Grupy: {event.groups}")
        description.append(f"Sala: {event.room}")
        description.append(f"Zjazd {event.weekend}")

        cal_event = icalendar.Event()
        cal_event.add("uid", f"{uid}@planpk.linguin.dev")
        cal_event.add("summary", summary)
        cal_event.add("dtstart", event.start.replace(tzinfo=TIMEZONE))
        cal_event.add("dtend", event.end.replace(tzinfo=TIMEZONE))
        cal_event.add("dtstamp", now)
        cal_event.add("description", "\n".join(description))
        location = event_location(event.room, campuses)
        if location:
            cal_event.add("location", location)
        if category:
            cal_event.add("categories", [category])
        cal.add_component(cal_event)
    return cal


def main():
    os.makedirs("build", exist_ok=True)
    load_schedule()
    clean_ics()

    rubrics = parse_schedule(EXCEL_FILE)
    campuses = load_room_campuses()

    manifest = []
    for rubric in rubrics:
        file_name = f"{rubric.slug}.ics"
        with open(f"build/{file_name}", "wb") as f:
            f.write(build_calendar(rubric, campuses).to_ical())
        manifest.append(
            {
                "file": file_name,
                "degree": rubric.degree,
                "year": rubric.year,
                "label": rubric.label,
            }
        )

    with open("build/calendars.json", "w") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    generate_html(manifest)


if __name__ == "__main__":
    main()
