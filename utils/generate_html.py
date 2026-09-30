import datetime
from html import escape
from zoneinfo import ZoneInfo

DEGREES = {"I": "I stopień", "II": "II stopień"}


def _calendar_item(label: str, cal: str, note: str = "") -> str:
    note_html = f'<span class="note">{escape(note)}</span>' if note else ""
    return (
        '<li class="cal">'
        f'<span class="name">{escape(label)}{note_html}</span>'
        '<span class="actions">'
        f'<a class="btn primary" href="webcal://planpk.linguin.dev/{cal}">Subskrybuj</a>'
        f'<a class="btn link-copy" href="#" data-cal-url="/{cal}">Kopiuj link</a>'
        f'<a class="btn" href="/{cal}" title="Pobierz {cal}">.ics</a>'
        "</span></li>"
    )


def _subject_lists(calendars: list, with_teachers: bool = False) -> str:
    by_subject = {}
    for calendar in calendars:
        note = ", ".join(calendar["teachers"]) if with_teachers else ""
        by_subject.setdefault(calendar["subject"], []).append(
            _calendar_item(calendar["group"], calendar["file"], note)
        )
    body = ""
    for subject, items in by_subject.items():
        body += f'<div class="subject-name">{escape(subject)}</div>'
        body += '<ul class="cals">' + "".join(items) + "</ul>"
    return body


def _year_section(year: str, calendars: list) -> str:
    base = [c for c in calendars if c["kind"] == "base"]
    electives = [c for c in calendars if c["kind"] == "elective"]
    languages = [c for c in calendars if c["kind"] == "language"]

    body = ""
    if base:
        items = "".join(_calendar_item(c["label"], c["file"]) for c in base)
        body += f'<h4>Grupy podstawowe</h4><ul class="cals">{items}</ul>'
    if electives:
        body += "<h4>Przedmioty wybieralne</h4>" + _subject_lists(electives)
    if languages:
        body += "<h4>Języki (wybierz swoją grupę / prowadzącego)</h4>"
        body += _subject_lists(languages, with_teachers=True)

    count = len(calendars)
    noun = "kalendarz" if count == 1 else "kalendarze" if 2 <= count % 10 <= 4 and not 12 <= count % 100 <= 14 else "kalendarzy"
    return (
        '<details class="year">'
        f'<summary><span>{escape(year)}</span><span class="count">{count} {noun}</span></summary>'
        f'<div class="year-body">{body}</div></details>'
    )


def generate_html(calendars):
    by_degree = {}
    for calendar in calendars:
        years = by_degree.setdefault(calendar["degree"], {})
        years.setdefault(calendar["year"], []).append(calendar)

    content = ""
    for degree, years in by_degree.items():
        content += f"<h2>{escape(DEGREES.get(degree, degree))}</h2>"
        for year, year_calendars in years.items():
            content += _year_section(year, year_calendars)

    with open("index.html", "r") as f:
        template = f.read()
    time = datetime.datetime.now(ZoneInfo("Europe/Warsaw")).strftime("%d/%m/%Y %H:%M")
    page = template.replace("<!-- CALENDARS -->", content).replace("<!-- UPDATED -->", time)
    with open("build/index.html", "w") as fw:
        fw.write(page)
