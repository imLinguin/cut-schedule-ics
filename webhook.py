import datetime
from email.utils import parsedate_to_datetime
import json
import os
from pathlib import Path
import re
import time

import requests

from utils.file_diff import event_changes, file_diff, ics_read
from utils.sync_state import load_manifest, summary

BUILD_DIR = "build"
OLD_BUILD_DIR = "sync-state/build"
# This cohort: semesters 5/6 in 2026/27, then 7/8 in 2027/28.
COHORT_ACADEMIC_YEAR = 2026
ZAOCZNE_ROLE_ID = "1286988227617488896"
COHORT_FILE = re.compile(r"^i-rok-([34])-sem-([5-8])-")


def cohort_calendars(directory):
    calendars, populated_semesters = {}, set()
    for entry in load_manifest(directory):
        match = COHORT_FILE.match(entry["file"])
        if entry["degree"] != "I" or not match:
            continue
        year, semester = map(int, match.groups())
        if year != (semester + 1) // 2:
            continue
        events = ics_read(Path(directory) / entry["file"])
        expected_year = COHORT_ACADEMIC_YEAR + (semester - 5) // 2
        # Use the dates in the plan, not today's date: the next semester can be
        # published early. August separates academic years, including makeups.
        academic_years = {int(e["date"][:4]) - (int(e["date"][5:7]) < 8) for e in events}
        if events and expected_year not in academic_years:
            continue
        calendars[entry["file"]] = entry
        if events:
            populated_semesters.add(semester)
    return calendars, populated_semesters


def cohort_scope(old_dir, new_dir, minimum_semester=5):
    if type(minimum_semester) is not int or not 5 <= minimum_semester <= 8:
        raise ValueError("Invalid saved notification semester")
    old, old_semesters = cohort_calendars(old_dir)
    new, new_semesters = cohort_calendars(new_dir)
    semester = max({minimum_semester} | old_semesters | new_semesters)
    prefix = f"i-rok-{(semester + 1) // 2}-sem-{semester}-"
    return semester, {n: c for n, c in old.items() if n.startswith(prefix)}, {
        n: c for n, c in new.items() if n.startswith(prefix)}


def dir_compare(old_dir=OLD_BUILD_DIR, new_dir=BUILD_DIR, minimum_semester=5):
    _, old, new = cohort_scope(old_dir, new_dir, minimum_semester)
    return compare_calendars(old, new, old_dir, new_dir)


def compare_calendars(old, new, old_dir, new_dir):
    changes = []
    for name in sorted(old.keys() | new.keys()):
        calendar = new.get(name, old.get(name))
        change = {"label": f"{calendar['degree']} stopień · {calendar['year']} · {calendar['label']}"}
        if name not in new:
            change["notice"] = "Grupa usunięta z planu. Jej kalendarz nie jest już publikowany."
            change["diffs"] = event_changes(Path(old_dir) / name, "event_removed")
        elif name not in old:
            change["notice"] = f"Nowa grupa w planie ({len(ics_read(Path(new_dir) / name))} wydarzeń)."
            change["diffs"] = event_changes(Path(new_dir) / name, "event_added")
        else:
            diffs = file_diff(Path(old_dir) / name, Path(new_dir) / name)
            if not diffs:
                continue
            change["diffs"] = diffs
        changes.append(change)
    return changes


def format_message(changes):
    if not changes:
        return ""
    lines = [f"<@&{ZAOCZNE_ROLE_ID}>", "# ZMIANY W KALENDARZU"]
    for change in changes:
        lines.append(f"\n## {change['label']}")
        if "notice" in change:
            lines.append(change["notice"])
        current_date = None
        for diff in change.get("diffs", []):
            if diff["date"] != current_date:
                current_date = diff["date"]
                lines.append(f"\n**{current_date}**")
            lines.append(f"- {diff['summary']} – {diff['details']}")
    return "\n".join(lines)


def retry_delay(response, attempt):
    value = response.headers.get("Retry-After")
    try:
        delay = float(value)
    except (ValueError, TypeError):
        try:
            delay = (parsedate_to_datetime(value) - datetime.datetime.now(datetime.timezone.utc)).total_seconds()
        except (ValueError, TypeError, AttributeError):
            try:
                delay = float(response.json()["retry_after"])
            except (ValueError, KeyError, TypeError):
                delay = 2 ** attempt
    # Do not keep a runner asleep for a long rate limit; the next scheduled run
    # will retry the unacknowledged change instead.
    if delay > 60:
        raise RuntimeError("Discord rate limit exceeds retry budget; notification remains pending")
    return max(0, delay)


def discord_http_error(response):
    # Only report a numeric API code and our own labels. Response text can
    # contain request details, including the secret webhook URL.
    try:
        code = response.json().get("code")
    except (ValueError, AttributeError):
        code = None
    reason = f"Discord HTTP {response.status_code}"
    if type(code) is int:
        reason += f" (code {code})"
    if code == 10015:
        reason += ": unknown webhook; update the DISCORD_WEBHOOK_URL secret"
    elif code == 10003:
        reason += ": unknown channel; check the webhook channel and thread_id"
    elif code == 50027:
        reason += ": invalid webhook token; update the DISCORD_WEBHOOK_URL secret"
    elif response.status_code == 404:
        reason += ": endpoint not found; check DISCORD_WEBHOOK_URL and its target channel"
    return RuntimeError(reason + "; notification remains pending")


def send_message(url, message):
    if not message:
        return
    url = url.strip()
    if not url:
        raise RuntimeError("Missing DISCORD_WEBHOOK_URL secret; notification remains pending")
    payload = {"content": message, "allowed_mentions": {"parse": [], "roles": [ZAOCZNE_ROLE_ID]}}
    attachment = None
    if len(message) > 2000:
        payload["content"] = f"<@&{ZAOCZNE_ROLE_ID}>\n# ZMIANY W KALENDARZU\nPełna lista zmian dla Waszego semestru jest w załączniku."
        attachment = ("zmiany.txt", message.encode("utf-8"), "text/plain; charset=utf-8")
    for attempt in range(3):
        kwargs = {"params": {"wait": "true"}, "timeout": (10, 30), "allow_redirects": False}
        if attachment:
            kwargs.update(data={"payload_json": json.dumps(payload)}, files={"file": attachment})
        else:
            kwargs["json"] = payload
        try:
            response = requests.post(url, **kwargs)
        except requests.RequestException:
            # Never include the exception URL: it contains the webhook secret.
            if attempt == 2:
                raise RuntimeError("Discord connection failed; notification remains pending") from None
            time.sleep(2 ** attempt)
            continue
        if 200 <= response.status_code < 300:
            try:
                if response.json().get("id"):
                    return
            except (ValueError, AttributeError):
                pass
            raise RuntimeError("Discord did not confirm a saved message; notification remains pending")
        if attempt == 2 or (response.status_code != 429 and response.status_code < 500):
            raise discord_http_error(response)
        time.sleep(retry_delay(response, attempt))


def main():
    state_dir = Path(os.environ.get("SYNC_STATE_DIR", "sync-state"))
    old_dir = state_dir / "build"
    metadata = json.loads((state_dir / "state.json").read_text())
    semester, old, new = cohort_scope(old_dir, BUILD_DIR, metadata.get("notification_semester", 5))
    changes = compare_calendars(old, new, old_dir, BUILD_DIR)
    message = format_message(changes)
    if message:
        send_message(os.environ.get("DISCORD_WEBHOOK_URL", ""), message)
        summary(f"Discord potwierdził powiadomienie: {len(changes)} zmienionych grup.")
    else:
        summary("Brak zmian wymagających powiadomienia na Discordzie.")
    # Commit the cohort advance together with the completed synchronization,
    # never before Discord confirms delivery. No extra service/state store.
    next_metadata_path = Path("next-state/state.json")
    next_metadata = json.loads(next_metadata_path.read_text())
    next_metadata["notification_semester"] = semester
    next_metadata_path.write_text(json.dumps(next_metadata, ensure_ascii=False))
    summary(f"Powiadomienia: wyłącznie I stopień, rok {(semester + 1) // 2}, semestr {semester}.")


if __name__ == "__main__":
    main()
