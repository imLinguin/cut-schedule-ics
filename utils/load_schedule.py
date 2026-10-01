import time

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
    for attempt in range(3):
        try:
            res = session.get(url, allow_redirects=True, timeout=(10, 60))
            res.raise_for_status()
            return res
        except requests.RequestException as exc:
            status = exc.response.status_code if exc.response is not None else None
            if attempt == 2 or (status and status != 429 and status < 500):
                # Artifact download redirects may contain signed query strings.
                # Do not leak those URLs through Requests exception tracebacks.
                reason = f"HTTP {status}" if status else "network error"
                raise RuntimeError(f"Download failed: {reason}") from None
            time.sleep(2 ** attempt)


def load_schedule() -> bool:
    """Download the source; deployment decisions use validated calendar contents."""
    print("Getting", EXCEL_URL)
    excel_file = _get(_session(), EXCEL_URL).content
    # xlsx is a zip archive, anything else is an error page
    if not excel_file.startswith(b"PK"):
        raise RuntimeError(f"{EXCEL_URL} did not return an xlsx file")

    with open(EXCEL_FILE, "wb") as f:
        f.write(excel_file)
    return True


def load_rooms(fallback=None) -> dict:
    """
    Maps room codes used in the Excel to {"campus": ..., "name": ...}.
    The Excel itself only has the short room code, so this is best effort.
    """
    try:
        state = _get(_session(), SNAPSHOT_URL).json()["state"]
        rooms = {}
        for room in state.get("rooms", []):
            rooms[room["code"]] = {"campus": room.get("campus"), "name": room.get("name")}
        for block in state.get("blocks", []):
            if block.get("room") and block.get("campus"):
                rooms.setdefault(block["room"], {"campus": block["campus"], "name": None})
        if not rooms:
            raise ValueError("Empty room list")
    except Exception as exc:
        print(f"::warning::Failed to load room list: {exc}")
        return dict(fallback or {})
    # The planner displays this room as S1 in the export
    if "SEMINARYJNA" in rooms:
        rooms.setdefault("S1", rooms["SEMINARYJNA"])
    return rooms
