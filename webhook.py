import json
import os
from utils.file_diff import file_diff
import requests


BUILD_DIR = "build"
OLD_BUILD_DIR = "build-old"
# Only calendars whose file name starts with this are reported (I stopień, rok 3, both semesters)
TARGET_PREFIX = os.environ.get("WEBHOOK_TARGET_PREFIX", "i-rok-3-")


def has_old_build_content(directory: str = OLD_BUILD_DIR) -> bool:
    if not os.path.isdir(directory):
        return False
    with os.scandir(directory) as entries:
        return any(True for _ in entries)


if not has_old_build_content():
    # Happens on the first run after the cache expires, the next run will have it
    print("::notice::old build folder missing or empty, nothing to compare")
    raise SystemExit(0)


def load_calendars(directory: str = BUILD_DIR) -> list:
    with open(os.path.join(directory, "calendars.json")) as f:
        return json.load(f)


def dir_compare(calendars: list, old_dir: str = OLD_BUILD_DIR, new_dir: str = BUILD_DIR) -> list:
    changes = []
    for calendar in calendars:
        name = calendar["file"]
        if not name.startswith(TARGET_PREFIX):
            continue
        new_path = os.path.join(new_dir, name)
        old_path = os.path.join(old_dir, name)
        # New calendar, nothing to compare against
        if not os.path.exists(old_path):
            continue
        try:
            diff = file_diff(old_path, new_path)
        except Exception as exc:
            raise RuntimeError(f"failed to diff {old_path} vs {new_path}") from exc
        if diff:
            changes.append({"label": f"{calendar['year']} · {calendar['label']}", "diffs": diff})
    return changes


def group_by_date(diffs: list):
    grouped = {}
    for diff in diffs:
        diff_without_date = {k: v for k, v in diff.items() if k != "date"}
        grouped.setdefault(diff["date"], []).append(diff_without_date)
    return grouped


changes = dir_compare(load_calendars())

message = "@everyone\n# ZMIANY W KALENDARZU\n"

for change in changes:
    message += f"\n# {change['label']}\n"
    for date, diffs in sorted(group_by_date(change["diffs"]).items()):
        message += f"\n**{date}**\n"
        for diff in diffs:
            message += f"- {diff['summary']} – {diff['details']}\n"

if len(message) > 2000:
    message = "@everyone\n# ZMIANY W KALENDARZU\n## zaglądnijcie w kalendarz, zmiany są gigantyczne i nie mieszczą się na discordzie XDDDD"

if message != "@everyone\n# ZMIANY W KALENDARZU\n":
    url: str = os.environ["DISCORD_WEBHOOK_URL"]
    request = {"content": message}
    requests.post(url, json=request)
