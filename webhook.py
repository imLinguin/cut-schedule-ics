import re
import os
from utils.file_diff import file_diff
import requests


BUILD_DIR = "build"
OLD_BUILD_DIR = "build-old"
TARGET_YEAR = 2


def has_old_build_content(directory: str = OLD_BUILD_DIR) -> bool:
    if not os.path.isdir(directory):
        return False
    with os.scandir(directory) as entries:
        return any(True for _ in entries)


if not has_old_build_content():
    raise SystemExit("old build folder missing or empty")


def get_year(file_name: str) -> "str | int":
    part = file_name.split("-")[1][:2]
    try:
        return int(part[0])
    except ValueError:
        return part


def get_exercise_group(file_name: str) -> int:
    return int(file_name[-7])


def get_lab_group(file_name: str) -> int:
    return int(file_name[-5])


def group_changes(changes_list: list):
    grouped = {}
    for entry in changes_list:
        key = (entry["year"], entry["label"])
        date_bucket = grouped.setdefault(key, {})
        for diff in entry["diffs"]:
            date = diff["date"]
            diff_without_date = {k: v for k, v in diff.items() if k != "date"}
            date_bucket.setdefault(date, []).append(diff_without_date)
    return grouped


def dir_compare(old_dir: str = OLD_BUILD_DIR, new_dir: str = BUILD_DIR) -> list:
    changes = []
    for file in os.walk(new_dir):
        root, _, files = file
        for name in files:
            if not re.fullmatch(r".*\.ics", name):
                continue
            new_path = os.path.join(new_dir, name)
            old_path = os.path.join(old_dir, name)
            try:
                diff = file_diff(new_path, old_path)
            except Exception as exc:
                raise RuntimeError(f"failed to diff {old_path} vs {new_path}") from exc
            if diff:
                changes.append({"file": name, "diffs": diff})
    return changes


changes = dir_compare()
change_info = []
for change in changes:
    file_name = change["file"]
    year = get_year(file_name)
    change_info.append(
        {
            "year": year,
            "label": f"# Grupa ćwiczeniowa {get_exercise_group(file_name)}, grupa laboratoryjna {get_lab_group(file_name)}",
            "diffs": change["diffs"],
        }
    )


grouped = group_changes(change_info)

message = "@everyone\n# ZMIANY W KALENDARZU\n"


for (year, label), dates in grouped.items():
    if year != TARGET_YEAR:  # for 2nd years webhook
        continue
    message += f"\n{label}\n"
    for date, diffs in sorted(dates.items()):
        message += f"\n**{date}**\n"
        for diff in diffs:
            message += f"- {diff['summary']} – {diff['details']}\n"

if len(message) > 2000:
    message = "@everyone\n# ZMIANY W KALENDARZU\n## zaglądnijcie w kalendarz, zmiany są gigantyczne i nie mieszczą się na discordzie XDDDD"

if message != "@everyone\n# ZMIANY W KALENDARZU\n":
    url: str = os.environ["DISCORD_WEBHOOK_URL"]
    request = {"content": message}
    requests.post(url, json=request)
