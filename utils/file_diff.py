import re
from collections import defaultdict

from icalendar import Calendar


OLD_TITLE = re.compile(r"^(?P<subject>.+) \((?P<short>[WĆLPS])\)$")
OLD_PREFIXES = {"W": "WYKŁAD", "Ć": "ĆW", "L": "LAB", "P": "PROJEKT", "S": "SEMINARIUM"}


def _normalize_summary(summary):
    match = OLD_TITLE.match(summary)
    return f"{OLD_PREFIXES[match['short']]} {match['subject']}" if match else summary


def ics_read(file):
    with open(file, "rb") as stream:
        calendar = Calendar.from_ical(stream.read())
    events = []
    for event in calendar.walk("VEVENT"):
        summary = str(event.get("SUMMARY", ""))
        if summary == "BRAK ZAJĘĆ":
            continue
        try:
            description = dict(
                line.split(": ", 1) for line in str(event.get("DESCRIPTION", "")).splitlines()
                if ": " in line
            )
            events.append({
                "key": str(event.get("X-PK-KEY") or _normalize_summary(summary)),
                "summary": summary,
                "date": event["DTSTART"].dt.date().isoformat(),
                "start": event["DTSTART"].dt.strftime("%H:%M"),
                "end": event["DTEND"].dt.strftime("%H:%M"),
                # Our description contains the full room identity in old and
                # new exports. Merely enriching LOCATION is not a room change.
                "room": description.get("Sala") or str(event.get("LOCATION", "")),
                "teacher": description.get("Prowadzący", ""),
                "groups": description.get("Grupa", ""),
            })
        except (KeyError, AttributeError, ValueError) as exc:
            raise ValueError(f"Invalid event in {file}") from exc
    return sorted(events, key=lambda e: tuple(e.values()))


def _signature(event):
    # Ignore title formatting, but preserve the number of identical occurrences.
    return tuple(event[k] for k in ("key", "date", "start", "end", "room", "teacher", "groups"))


def _changes(old, new):
    entries = []

    def add(kind, details):
        entries.append({"date": new["date"], "summary": new["summary"],
                        "change_type": kind, "details": details})

    if old["date"] != new["date"]:
        add("date_changed", f"Zmiana dnia: {old['date']} -> {new['date']}")
    if (old["start"], old["end"]) != (new["start"], new["end"]):
        add("time_changed", f"Zmiana godziny: {old['start']} - {old['end']} -> {new['start']} - {new['end']}")
    for field, kind, label in (("room", "room_changed", "Zmiana sali"),
                               ("teacher", "teacher_changed", "Zmiana prowadzącego"),
                               ("groups", "groups_changed", "Zmiana grupy")):
        if old[field] != new[field]:
            add(kind, f"{label}: {old[field] or 'brak'} -> {new[field] or 'brak'}")
    return entries


def _event_change(event, kind):
    label = "Nowe wydarzenie" if kind == "event_added" else "Wydarzenie usunięte"
    return {"date": event["date"], "summary": event["summary"], "change_type": kind,
            "details": (f"{label}: {event['start']} - {event['end']}, sala {event['room'] or 'brak'}; "
                        f"prowadzący: {event['teacher'] or 'brak'}; grupa: {event['groups'] or 'brak'}")}


def event_changes(path, kind):
    return [_event_change(event, kind) for event in ics_read(path)]


def file_diff(old_file, new_file):
    old_events, new_events = ics_read(old_file), ics_read(new_file)
    # Remove unchanged occurrences before matching edits. Occurrence numbering
    # would turn deletion of the first lecture into a cascade of false changes.
    unchanged = defaultdict(list)
    for i, event in enumerate(new_events):
        unchanged[_signature(event)].append(i)
    old_remaining, matched = [], set()
    for event in old_events:
        candidates = unchanged[_signature(event)]
        if candidates:
            matched.add(candidates.pop())
        else:
            old_remaining.append(event)
    new_remaining = [e for i, e in enumerate(new_events) if i not in matched]
    entries = []
    # Pair only unambiguous occurrences, first on the same day, then across dates.
    for fields in (("key", "date"), ("key",)):
        old_groups, new_groups = defaultdict(list), defaultdict(list)
        for i, event in enumerate(old_remaining):
            old_groups[tuple(event[f] for f in fields)].append(i)
        for i, event in enumerate(new_remaining):
            new_groups[tuple(event[f] for f in fields)].append(i)
        old_used, new_used = set(), set()
        for key in sorted(old_groups.keys() & new_groups.keys()):
            if len(old_groups[key]) == len(new_groups[key]) == 1:
                a, b = old_groups[key][0], new_groups[key][0]
                entries.extend(_changes(old_remaining[a], new_remaining[b]))
                old_used.add(a)
                new_used.add(b)
        old_remaining = [e for i, e in enumerate(old_remaining) if i not in old_used]
        new_remaining = [e for i, e in enumerate(new_remaining) if i not in new_used]
    for events, kind in ((old_remaining, "event_removed"), (new_remaining, "event_added")):
        for event in events:
            entries.append(_event_change(event, kind))
    return sorted(entries, key=lambda e: (e["date"], e["summary"], e["change_type"], e["details"]))
