from icalendar import Calendar


def _event_context(event):
    def _format(value):
        if value is None:
            return None
        if hasattr(value, "dt"):
            return str(value.dt)
        return str(value)

    return {
        "summary": _format(event.get("SUMMARY")),
        "dtstart": _format(event.get("DTSTART")),
        "dtend": _format(event.get("DTEND")),
        "description": _format(event.get("DESCRIPTION")),
    }


def ics_read(file: str):
    events = []
    with open(file, "r") as stream:
        calendar = Calendar.from_ical(stream.read())
    for event in calendar.events:  # type: ignore
        summary_value = event.get("SUMMARY")
        summary_text = str(summary_value) if summary_value is not None else None
        if summary_text == "BRAK ZAJĘĆ":
            continue
        try:
            start_time = event["DTSTART"].dt.time()
            end_time = event["DTEND"].dt.time()
            extracted = {
                "summary": summary_text or "",
                "date": str(event["DTSTART"].dt.date()),
                "start": start_time.strftime("%H:%M"),
                "end": end_time.strftime("%H:%M"),
                "room": str(event.get("DESCRIPTION") or ""),
            }
        except Exception as exc:
            context = _event_context(event)
            raise RuntimeError(
                f"failed to parse event in {file} (partial={context})"
            ) from exc
        events.append(extracted)
    return events


def _group_by_summary_date(events: list):
    grouped = {}
    for event in events:
        grouped[(event["summary"], event["date"])] = event
    return grouped


def _sorted_keys(keys):
    return sorted(keys, key=lambda key: key[1])


def file_diff(old_file: str, new_file: str):
    old_events = _group_by_summary_date(ics_read(old_file))
    new_events = _group_by_summary_date(ics_read(new_file))

    entries = []

    shared_keys = set(old_events) & set(new_events)
    for key in _sorted_keys(shared_keys):
        old_event = old_events[key]
        new_event = new_events[key]
        start_changed = old_event["start"] != new_event["start"]
        room_changed = old_event["room"] != new_event["room"]
        if room_changed:
            entries.append(
                {
                    "date": new_event["date"],
                    "summary": new_event["summary"],
                    "change_type": "room_changed",
                    "details": f"Zmiana sali: {old_event['room']} -> {new_event['room']}",
                }
            )
        if start_changed:
            entries.append(
                {
                    "date": new_event["date"],
                    "summary": new_event["summary"],
                    "change_type": "start_changed",
                    "details": f"Zmiana godziny: {old_event['start']} - {old_event['end']} -> {new_event['start']} - {new_event['end']}",
                }
            )

    added_keys = set(new_events) - set(old_events)
    removed_keys = set(old_events) - set(new_events)
    removed_by_summary = {}
    for key in _sorted_keys(removed_keys):
        summary = key[0]
        removed_by_summary.setdefault(summary, []).append(key)

    date_shifted_pairs = []
    matched_removed_keys = set()
    matched_added_keys = set()
    for key in _sorted_keys(added_keys):
        summary = key[0]
        if not removed_by_summary[summary]:
            continue
        old_key = removed_by_summary[summary].pop(0)
        matched_removed_keys.add(old_key)
        matched_added_keys.add(key)
        date_shifted_pairs.append((old_key, key))

    remaining_added_keys = sorted(
        (key for key in added_keys if key not in matched_added_keys),
        key=lambda key: key[1],
    )
    remaining_removed_keys = sorted(
        (key for key in removed_keys if key not in matched_removed_keys),
        key=lambda key: key[1],
    )

    for old_key, new_key in date_shifted_pairs:
        old_event = old_events[old_key]
        new_event = new_events[new_key]
        entries.append(
            {
                "date": new_event["date"],
                "summary": new_event["summary"],
                "change_type": "date_changed",
                "details": f"Zmiana dnia: {old_event['date']} -> {new_event['date']}",
            }
        )
        if old_event["room"] != new_event["room"]:
            entries.append(
                {
                    "date": new_event["date"],
                    "summary": new_event["summary"],
                    "change_type": "room_changed",
                    "details": f"Zmiana sali: {old_event['room']} -> {new_event['room']}",
                }
            )

    for key in remaining_added_keys:
        event = new_events[key]
        entries.append(
            {
                "date": event["date"],
                "summary": event["summary"],
                "change_type": "event_added",
                "details": f"Nowe wydarzenie: {event['start']} - {event['end']}, sala {event['room']}",
            }
        )

    for key in remaining_removed_keys:
        event = old_events[key]
        entries.append(
            {
                "date": event["date"],
                "summary": event["summary"],
                "change_type": "event_removed",
                "details": f"Wydarzenie usunięte: {event['start']} - {event['end']}, sala {event['room']}",
            }
        )

    return entries
