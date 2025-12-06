from collections import Counter
import datetime
import xlrd
from dataclasses import dataclass
import icalendar
import re
import os
from utils.legenda import legenda
from utils.geo import GEO
from utils.clean_ics import clean_ics
from utils.generate_html import generate_html
from utils.load_schedule import load_schedule
from utils.handle_type import handle_type


@dataclass
class CalendarEntry:
    content: str
    start: datetime.datetime
    end: datetime.datetime


"""
Both of the following functions take data from the Excel sheet, yet this data is incomplete and not always accurate.
Fixing would require hard-coding this data, which is not a good idea, since it may change throughout the years.
"""


def main():
    os.makedirs("build", exist_ok=True)
    load_schedule()
    clean_ics()

    workbook = xlrd.open_workbook("excel.xls", formatting_info=True)
    sh = workbook.sheet_by_index(0)

    tags = {}
    location = {}

    leg = legenda(sh)

    assert leg is not None

    for row in range(leg + 2, sh.nrows):
        if sh.row(row)[4].value:
            full_name = ""
            name = str(sh.row(row)[4].value).split(" ")
            for element in name:
                if (
                    any(character.isupper() for character in element)
                    and "PK" not in element
                ):
                    full_name += element + " "
            full_name = re.sub(r"[^\w\s-]", "", full_name.strip(), flags=re.UNICODE)
            tags[sh.row(row)[3].value] = (full_name, sh.row(row)[12].value)

    ge = GEO(sh)

    assert ge is not None

    for row in range(ge + 1, sh.nrows):
        if sh.row(row)[19].value:
            location[str(sh.row(row)[19].value).split("-")[0].strip()] = (
                str(sh.row(row)[19].value).split("-")[1].strip()
            )

    mc = sh.merged_cells

    # Map values for merged cells
    merged_values = {}
    for r1, r2, c1, c2 in mc:
        value = sh.cell(r1, c1)
        for row in range(r1, r2):
            for col in range(c1, c2):
                merged_values[(row, col)] = value

    semester_groups = list()
    years = sh.row(5)
    groups = sh.row(6)

    prev_group = None
    lab = 0
    group_occurences = Counter()
    for colx in range(3, len(groups)):
        mapped_degree = merged_values.get((4, colx), sh.row(4)[colx]).value
        mapped_year = merged_values.get((5, colx), years[colx]).value
        mapped_value = merged_values.get((6, colx), groups[colx]).value
        if not mapped_value or not mapped_year:
            continue
        # Force the float
        if type(mapped_value) is float:
            mapped_value = str(round(mapped_value))
        if mapped_year != prev_group:
            lab = 0
            prev_group = mapped_year
        group_occurences[mapped_value] += 1
        lab += 1
        group_id = f"{mapped_value}-{group_occurences[mapped_value]}"
        # degree, year, practice group, laboratory group, groupid
        semester_groups.append(
            (mapped_degree, mapped_year, mapped_value[1], lab, group_id)
        )

    timetable = {}
    for i in range(len(semester_groups)):
        timetable[i] = []

    for rowx in range(7, sh.nrows, 3):
        row = sh.row(rowx)
        value = merged_values.get((rowx, 0), row[0])
        if value.ctype != 3:
            continue

        date = xlrd.xldate_as_datetime(value.value, workbook.datemode)
        hour_range = merged_values.get((rowx, 1), row[1])
        start, end = hour_range.value.split("-")
        if "." in start:
            start_h, start_m = start.split(".")
        else:
            start_h, start_m = start.split(":")

        if "." in start:
            end_h, end_m = end.split(".")
        else:
            end_h, end_m = end.split(":")

        date_start = date + datetime.timedelta(hours=int(start_h), minutes=int(start_m))
        date_end = date + datetime.timedelta(hours=int(end_h), minutes=int(end_m))
        group = 0

        for column in range(3, len(row)):
            timetable_key = group
            if not merged_values.get((6, column), sh.row(6)[column]).value:
                continue
            entry = merged_values.get((rowx, column), row[column])
            entry_value = entry.value

            if entry.ctype == 3 or (
                entry_value
                and re.match(r"\d\d?.\d\d-", entry_value)
                and len(entry_value) <= 11
            ):
                continue
            if entry.ctype != 3 and entry_value:
                entry = timetable.get(timetable_key, [])
                if re.match(r"\d\d?.\d\d-", entry_value):
                    date_start = date + datetime.timedelta(
                        hours=int(entry_value[:2]),
                        minutes=int(entry_value[3:5]),  # slicing > regex
                    )
                    date_end = date + datetime.timedelta(
                        hours=int(entry_value[6:8]), minutes=int(entry_value[9:11])
                    )
                    entry_value = entry_value[13:]
                elif re.match(r"^[0-2][0-9]:[0-5][0-9]", entry_value):
                    date_start_temp = date + datetime.timedelta(
                        hours=int(entry_value[:2]),
                        minutes=int(entry_value[3:5]),  # slicing > regex
                    )
                    date_end = date_end + (date_start_temp - date_start)
                    date_start = date_start_temp
                    entry_value = entry_value[6:]
                cal = CalendarEntry(entry_value, date_start, date_end)
                entry.append(cal)
                timetable.update({timetable_key: entry})
            group += 1

    # TODO to be optimized
    cals = []
    for key, value in timetable.items():
        cal = icalendar.Calendar()
        cal.add("prodid", "-//linguin.dev//cut-calendar-ics//PL")
        cal.add("version", "2.0")
        cal.add("X-WR-TIMEZONE", "Europe/Warsaw")
        for event in value:
            SALA = None
            cal_event = icalendar.Event()
            summary = event.content
            summary = re.sub(r"\s+", " ", summary)
            #     for tag in tags:
            # # Only process if summary does not contain "język"
            #         if "język" not in summary.lower():
            #             updated = False

            #             # Check and replace in summary if the tag is found
            #             if tag in summary:
            #                 summary = re.sub(tag, tags[tag][0], summary)
            #                 summary = re.sub(r'\s+', ' ', summary)
            #                 updated = True

            #             # Once either substitution or organizer update happens, break out of the loop
            #             if updated:
            #                 break

            if "ZDALNIE" in summary.upper():
                summary = re.sub(r"(?i)ZDALNIE", "", summary).strip()
                SALA = "ZDALNIE"

            elif "s." in summary:
                pos = summary.index("s.")
                SALA = summary[pos + len("s.") :].strip().replace("s.", "")
                summary = summary[:pos].strip()

            cal_event.add("summary", summary)
            if SALA:
                cal_event.add("description", SALA)
                for loc in location:
                    if SALA in loc:
                        cal_event.add("location", "Kraków" + " " + location[loc])
            cal_event.add("dtstart", event.start)
            cal_event.add("dtend", event.end)
            cal_event.add("dtstamp", datetime.datetime.now())
            cal.add_component(cal_event)
            cal_event.add("category", handle_type(summary))

        group_id = semester_groups[key][4]
        cals.append(f"calendar-{group_id}.ics")
        with open(f"build/calendar-{group_id}.ics", "wb") as f:
            f.write(cal.to_ical())

    generate_html(cals, semester_groups)


if __name__ == "__main__":
    main()
