import datetime
from email.utils import parsedate_to_datetime
import json
import os
from pathlib import Path
import time

import requests

from utils.file_diff import file_diff, ics_read
from utils.sync_state import load_manifest, summary

BUILD_DIR = "build"
OLD_BUILD_DIR = "sync-state/build"
TARGET_PREFIX = "i-rok-3-"


def dir_compare(old_dir=OLD_BUILD_DIR, new_dir=BUILD_DIR, target_prefix=TARGET_PREFIX):
    old = {entry["file"]: entry for entry in load_manifest(old_dir)}
    new = {entry["file"]: entry for entry in load_manifest(new_dir)}
    changes = []
    for name in sorted(old.keys() | new.keys()):
        calendar = new.get(name, old.get(name))
        change = {"label": f"{calendar['degree']} stopień · {calendar['year']} · {calendar['label']}"}
        if name not in new:
            # Every deleted group is reported, not only the usual third-year feed.
            change["notice"] = "Grupa usunięta z planu. Jej kalendarz nie jest już publikowany."
        elif not name.startswith(target_prefix):
            continue
        elif name not in old:
            change["notice"] = f"Nowa grupa w planie ({len(ics_read(Path(new_dir) / name))} wydarzeń)."
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
    lines = ["@everyone", "# ZMIANY W KALENDARZU"]
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


def send_message(url, message):
    if not message:
        return
    payload = {"content": message, "allowed_mentions": {"parse": ["everyone"]}}
    attachment = None
    if len(message) > 2000:
        payload["content"] = "@everyone\n# ZMIANY W KALENDARZU\nPełna lista zmian, w tym dodane/usunięte grupy, jest w załączniku."
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
            raise RuntimeError(f"Discord HTTP {response.status_code}; notification remains pending")
        time.sleep(retry_delay(response, attempt))


def main():
    old_dir = Path(os.environ.get("SYNC_STATE_DIR", "sync-state")) / "build"
    changes = dir_compare(old_dir, BUILD_DIR, os.environ.get("WEBHOOK_TARGET_PREFIX", TARGET_PREFIX))
    message = format_message(changes)
    if message:
        send_message(os.environ["DISCORD_WEBHOOK_URL"], message)
        summary(f"Discord potwierdził powiadomienie: {len(changes)} zmienionych grup.")
    else:
        summary("Brak zmian wymagających powiadomienia na Discordzie.")


if __name__ == "__main__":
    main()
