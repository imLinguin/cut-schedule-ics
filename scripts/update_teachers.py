"""
Fetches academic titles of the teachers in the plan into data/teachers.json,
from the PK staff directory (spispracownikow.pk.edu.pl). The plan itself has no titles.
Existing entries are kept, so the file only grows. Run manually when new teachers appear:

    python scripts/update_teachers.py
"""

import json
import os
import sys
import time

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from utils.load_schedule import EXCEL_FILE, load_schedule  # noqa: E402
from utils.parse_schedule import parse_schedule  # noqa: E402

DIRECTORY_URL = "https://spispracownikow.pk.edu.pl/data.php"
OUTPUT = os.path.join(os.path.dirname(__file__), "..", "data", "teachers.json")


def words(name: str) -> frozenset:
    return frozenset(name.lower().replace("–", "-").split())


def search(surname: str) -> list:
    res = requests.post(
        DIRECTORY_URL,
        data={"id": surname, "ou": "", "child": "1", "offset": "0", "wybor_szukaj": "1"},
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=60,
    )
    res.raise_for_status()
    return res.json().get("list", [])


def lookup(name: str):
    """ "Skabek Krzysztof" or "Krzysztof Skabek" -> ("Krzysztof Skabek", {"title": "dr inż."}) """
    found = {}
    # The plan mixes "Surname Name" and "Name Surname", so try every word as the surname
    for surname in name.split():
        for person in search(surname):
            full_name = f"{person.get('givenName', '')} {person.get('sn', '')}".strip()
            if words(full_name) != words(name):
                continue
            entry = {}
            title = person.get("pleduPersonDegree") or ""
            if title and title != "---":
                entry["title"] = title
            if (person.get("employeeType") or {}).get("0") == "true":
                entry["suffix"] = "prof. PK"
            found[json.dumps(entry, sort_keys=True)] = (full_name, entry)
        time.sleep(0.3)
    # Nobody, or several people with the same name and different titles
    if len(found) != 1:
        return None
    full_name, entry = next(iter(found.values()))
    return (full_name, entry) if entry.get("title") else None


def main():
    if not os.path.exists(EXCEL_FILE):
        load_schedule()
    names = sorted(
        {
            part.strip()
            for rubric in parse_schedule(EXCEL_FILE)
            for event in rubric.events
            for part in event.teacher.split(" / ")
            if part.strip()
        }
    )

    teachers = {}
    if os.path.exists(OUTPUT):
        with open(OUTPUT) as f:
            teachers = json.load(f)
    known = {words(name) for name in teachers}

    missing = []
    for name in names:
        if words(name) in known:
            continue
        result = lookup(name)
        if result:
            teachers[result[0]] = result[1]
        else:
            missing.append(name)

    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    with open(OUTPUT, "w") as f:
        json.dump(dict(sorted(teachers.items())), f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"{len(names)} teachers in the plan, {len(names) - len(missing)} with a title")
    if missing:
        print("Not found:", ", ".join(missing))


if __name__ == "__main__":
    main()
