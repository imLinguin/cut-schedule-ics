"""Small, versioned snapshots of the last completed deploy + notification."""
import datetime
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import time
import zipfile

from icalendar import Calendar

from utils.load_schedule import _get, _session

SITE_URL = "https://planpk.linguin.dev"
STATE_DIR = Path("sync-state")
NEXT_STATE_DIR = Path("next-state")
CALENDAR_FILE = re.compile(r"[a-z0-9][a-z0-9-]*\.ics\Z")


def set_output(name, value):
    if "GITHUB_OUTPUT" in os.environ:
        with open(os.environ["GITHUB_OUTPUT"], "a") as stream:
            stream.write(f"{name}={value}\n")


def summary(message):
    print(message)
    if "GITHUB_STEP_SUMMARY" in os.environ:
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as stream:
            stream.write(message + "\n\n")


def load_manifest(directory):
    manifest = json.loads((Path(directory) / "calendars.json").read_text())
    if not isinstance(manifest, list) or not manifest:
        raise ValueError("Missing or empty calendar manifest")
    seen = set()
    for entry in manifest:
        name = entry["file"]
        if not CALENDAR_FILE.fullmatch(name) or name in seen:
            raise ValueError(f"Invalid or duplicate calendar filename: {name}")
        seen.add(name)
        for field in ("degree", "year", "label"):
            if not isinstance(entry.get(field), str) or not entry[field]:
                raise ValueError(f"Missing {field} in {name}")
    return manifest


def read_calendar(path):
    cal = Calendar.from_ical(Path(path).read_bytes())
    if cal.name != "VCALENDAR":
        raise ValueError(f"Not a calendar: {path}")
    return cal


def validate_build(directory, previous=None, combos=None):
    directory = Path(directory)
    manifest = load_manifest(directory)
    public_files = {entry["file"] for entry in manifest}
    combos = combos or {}
    expected = public_files | {f"{name}.ics" for name in combos}
    if expected != {p.name for p in directory.glob("*.ics")}:
        raise ValueError("Missing or unexpected calendar files")
    counts = {}
    for name in sorted(expected):
        events = read_calendar(directory / name).walk("VEVENT")
        uids = set()
        for event in events:
            uid = str(event.get("UID", ""))
            if not uid or uid in uids:
                raise ValueError(f"Missing or duplicate UID in {name}")
            uids.add(uid)
            start, end = event.decoded("DTSTART"), event.decoded("DTEND")
            if not isinstance(start, datetime.datetime) or not isinstance(end, datetime.datetime) or end <= start:
                raise ValueError(f"Invalid event times in {name}")
        counts[name] = len(events)
        # A deleted column is allowed. A surviving, unexpectedly empty column is
        # suspicious. Empty combos are allowed when all their groups were deleted.
        if name in public_files and not events and previous:
            old = Path(previous) / name
            if old.exists() and read_calendar(old).walk("VEVENT"):
                raise ValueError(f"Previously populated calendar is now empty: {name}")
    if not any(counts[name] for name in public_files):
        raise ValueError("The entire timetable is empty")
    return counts


def _calendar_content(path):
    cal = read_calendar(path)
    for event in cal.walk("VEVENT"):
        event.pop("DTSTAMP", None)
    cal.subcomponents.sort(key=lambda component: component.to_ical())
    return cal.to_ical()


def build_digest(directory):
    """Compare the full published output, excluding only generated timestamps."""
    digest = hashlib.sha256()
    for path in sorted(Path(directory).rglob("*")):
        if not path.is_file():
            continue
        data = path.read_bytes()
        if path.suffix == ".ics":
            data = _calendar_content(path)
        elif path.name == "calendars.json":
            data = json.dumps(sorted(json.loads(data), key=lambda c: c["file"]),
                              sort_keys=True, ensure_ascii=False).encode()
        elif path.name == "index.html":
            data = re.sub(rb"(Ostatnia aktualizacja: )\d{2}/\d{2}/\d{4} \d{2}:\d{2}", rb"\1", data)
        digest.update(str(path.relative_to(directory)).encode() + b"\0")
        digest.update(hashlib.sha256(data).digest())
    return digest.hexdigest()


def stage_state(build, rooms, target=NEXT_STATE_DIR):
    target = Path(target)
    target.mkdir(parents=True, exist_ok=False)
    shutil.copytree(build, target / "build")
    _write_metadata(target, rooms)


def _write_metadata(target, rooms):
    files = sorted(path.name for path in (target / "build").glob("*.ics"))
    (target / "state.json").write_text(json.dumps(
        {"version": 1, "rooms": rooms, "files": files}, ensure_ascii=False))


def _extract_state(content, target):
    target = Path(target)
    target.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        for entry in archive.infolist():
            path = target / entry.filename
            if not path.resolve().is_relative_to(target.resolve()):
                raise ValueError("Invalid state archive path")
        archive.extractall(target)
    metadata = json.loads((target / "state.json").read_text())
    if metadata.get("version") != 1:
        raise ValueError("Unsupported synchronization state")
    if not isinstance(metadata.get("rooms"), dict):
        raise ValueError("Missing room metadata in checkpoint")
    files = metadata.get("files")
    if not isinstance(files, list) or not files or any(
        not isinstance(name, str) or not CALENDAR_FILE.fullmatch(name) for name in files
    ):
        raise ValueError("Missing or invalid calendar inventory in checkpoint")
    actual = sorted(path.name for path in (target / "build").glob("*.ics"))
    if sorted(files) != actual:
        raise ValueError("Incomplete checkpoint: calendar files do not match inventory")
    public = {entry["file"] for entry in load_manifest(target / "build")}
    validate_build(target / "build", combos={Path(name).stem: [] for name in files if name not in public})


def restore_state():
    """Use only completed checkpoints; never use a mere generator artifact."""
    repo = os.environ["GITHUB_REPOSITORY"]
    token = os.environ["GITHUB_TOKEN"]
    with _session() as session:
        session.headers.update({"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"})
        page, latest_deployment, saw_managed_deployment = 1, 0, False
        while True:
            artifacts = _get(session, f"https://api.github.com/repos/{repo}/actions/artifacts?per_page=100&page={page}").json()["artifacts"]
            candidates = []
            for item in artifacts:
                run = item.get("workflow_run", {})
                if run.get("head_branch") != "main":
                    continue
                if run.get("head_repository_id") != run.get("repository_id"):
                    continue
                if item["name"] == "github-pages" or item["name"].startswith("github-pages-"):
                    latest_deployment = max(latest_deployment, item["id"])
                    saw_managed_deployment |= item["name"].startswith("github-pages-")
                if not item["name"].startswith("sync-state-"):
                    continue
                candidates.append(item)
            if candidates:
                newest = max(candidates, key=lambda item: (item["created_at"], item["id"]))
                if newest["expired"]:
                    raise RuntimeError("Synchronization checkpoint expired; recover it before continuing")
                content = _get(session, newest["archive_download_url"]).content
                _extract_state(content, STATE_DIR)
                set_output("bootstrap", "false")
                # A Pages artifact newer than the completed checkpoint means a
                # deployment may have happened without a notification/checkpoint.
                # Republish even if the source reverted to the checkpoint's plan.
                set_output("force_deploy", str(latest_deployment > newest["id"]).lower())
                summary("Odtworzono ostatni zakończony stan synchronizacji.")
                return
            if len(artifacts) < 100:
                break
            page += 1
    if saw_managed_deployment:
        raise RuntimeError("Missing checkpoint after an attempted deployment; recover it before continuing")
    # First migration only: persist this baseline BEFORE deploying anything, so
    # even a failed first notification can be retried against the same snapshot.
    with open("data/combos.json") as stream:
        combos = json.load(stream)
    build = STATE_DIR / "build"
    build.mkdir(parents=True, exist_ok=False)
    with _session() as session:
        suffix = f"?sync={time.time_ns()}"
        manifest_bytes = _get(session, SITE_URL + "/calendars.json" + suffix).content
        (build / "calendars.json").write_bytes(manifest_bytes)
        manifest = load_manifest(build)
        names = {c["file"] for c in manifest} | {f"{name}.ics" for name in combos}
        for name in sorted(names):
            (build / name).write_bytes(_get(session, SITE_URL + "/" + name + suffix).content)
        # Refuse a visibly changing manifest instead of bootstrapping mixed lists.
        if _get(session, SITE_URL + "/calendars.json" + suffix).content != manifest_bytes:
            raise RuntimeError("Published manifest changed during initialization; retry")
    validate_build(build, combos=combos)
    _write_metadata(STATE_DIR, {})
    set_output("bootstrap", "true")
    set_output("force_deploy", "true")
    summary("Pierwsza inicjalizacja z opublikowanych kalendarzy; wcześniejsze dostarczenie powiadomień nie jest weryfikowalne.")


if __name__ == "__main__":
    restore_state()
