import datetime
import json
from pathlib import Path

from icalendar import Calendar, Event

UTC = datetime.timezone.utc


def event(start="2026-10-03T08:00", end="2026-10-03T09:30", subject="Sieci", room="L1",
          teacher="Jan Kowalski", groups="GL2", uid=None, stamp="2026-09-01T00:00"):
    value = Event()
    value.add("UID", uid or f"{subject}-{start}")
    value.add("DTSTART", datetime.datetime.fromisoformat(start).replace(tzinfo=UTC))
    value.add("DTEND", datetime.datetime.fromisoformat(end).replace(tzinfo=UTC))
    value.add("DTSTAMP", datetime.datetime.fromisoformat(stamp).replace(tzinfo=UTC))
    value.add("SUMMARY", f"LAB {groups}: {subject}")
    value.add("X-PK-KEY", f"LAB {subject}")
    value.add("LOCATION", room)
    value.add("DESCRIPTION", f"Prowadzący: {teacher}\nGrupa: {groups}")
    return value


def calendar(path, events):
    cal = Calendar()
    cal.add("VERSION", "2.0")
    cal.add("PRODID", "tests")
    for value in events:
        cal.add_component(value)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(cal.to_ical())
    return path


def manifest(directory, names):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    entries = [{"file": name, "degree": "I", "year": "Rok 3 sem 5", "label": name[:-4]}
               for name in names]
    (directory / "calendars.json").write_text(json.dumps(entries))
    return entries
