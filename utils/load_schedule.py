import hashlib
import os

import requests

PLAN_URL = "https://ii.pk.edu.pl/~fkruzel/fk-planer-lti/public/plan-ns/"
EXCEL_URL = PLAN_URL + "download.php"
SNAPSHOT_URL = PLAN_URL + "snapshot.php"
EXCEL_FILE = "plan.xlsx"


def _session():
    session = requests.session()
    session.headers["User-Agent"] = (
        "Mozilla/5.0 (X11; Linux x86_64; rv:143.0) Gecko/20100101 Firefox/143.0"
    )
    return session


def _get(session, url):
    retry = 5
    while True:
        try:
            res = session.get(url, allow_redirects=True, timeout=60)
            res.raise_for_status()
            return res
        except Exception:
            retry -= 1
            if retry == 0:
                raise
            print("Retrying...")


def _file_hash(path):
    if not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()


def load_schedule() -> bool:
    """Downloads the Excel, returns False when CI should skip the deployment."""
    existing_hash = _file_hash(EXCEL_FILE)

    print("Getting", EXCEL_URL)
    excel_file = _get(_session(), EXCEL_URL).content
    # xlsx is a zip archive, anything else is an error page
    if not excel_file.startswith(b"PK"):
        raise RuntimeError(f"{EXCEL_URL} did not return an xlsx file")

    new_hash = hashlib.md5(excel_file).hexdigest()
    print(f"::notice::Cached file hash is {existing_hash}")
    print(f"::notice::Downloaded file hash is {new_hash}")
    with open(EXCEL_FILE, "wb") as f:
        f.write(excel_file)
    # Pushes and manual runs always deploy, so code changes go live right away
    forced = os.environ.get("FORCE_DEPLOY") == "true"
    if "CI" in os.environ and not forced and existing_hash == new_hash:
        print("::notice::Files are the same, skipping deployment")
        return False
    return True


def load_rooms() -> dict:
    """
    Maps room codes used in the Excel to {"campus": ..., "name": ...}.
    The Excel itself only has the short room code, so this is best effort.
    """
    try:
        state = _get(_session(), SNAPSHOT_URL).json()["state"]
    except Exception as exc:
        print(f"::warning::Failed to load room list: {exc}")
        return {}
    rooms = {}
    for room in state.get("rooms", []):
        rooms[room["code"]] = {"campus": room.get("campus"), "name": room.get("name")}
    for block in state.get("blocks", []):
        if block.get("room") and block.get("campus"):
            rooms.setdefault(block["room"], {"campus": block["campus"], "name": None})
    # The planner displays this room as S1 in the export
    if "SEMINARYJNA" in rooms:
        rooms.setdefault("S1", rooms["SEMINARYJNA"])
    return rooms
