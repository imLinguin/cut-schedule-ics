import datetime
import re
from html import escape
from zoneinfo import ZoneInfo

DEGREES = {"I": "I stopień", "II": "II stopień"}
# "Programowanie na platformie .NET K01" -> elective subject + its group
ELECTIVE = re.compile(r"^(?P<subject>.+) (?P<group>[KPĆ]\d+)$")


def _calendar_item(label: str, cal: str) -> str:
    return (
        '<li class="cal">'
        f'<span class="name">{escape(label)}</span>'
        '<span class="actions">'
        f'<a class="btn primary" href="webcal://planpk.linguin.dev/{cal}">Subskrybuj</a>'
        f'<a class="btn link-copy" href="#" data-cal-url="/{cal}">Kopiuj link</a>'
        f'<a class="btn" href="/{cal}" title="Pobierz {cal}">.ics</a>'
        "</span></li>"
    )


def _year_section(year: str, calendars: list) -> str:
    base = []
    electives = {}
    for calendar in calendars:
        match = ELECTIVE.match(calendar["label"])
        if match:
            electives.setdefault(match["subject"], []).append(
                _calendar_item(match["group"], calendar["file"])
            )
        else:
            base.append(_calendar_item(calendar["label"], calendar["file"]))

    body = ""
    if base:
        body += '<h4>Grupy podstawowe</h4><ul class="cals">' + "".join(base) + "</ul>"
    if electives:
        body += "<h4>Przedmioty wybieralne</h4>"
        for subject, items in electives.items():
            body += f'<div class="subject-name">{escape(subject)}</div>'
            body += '<ul class="cals">' + "".join(items) + "</ul>"

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
