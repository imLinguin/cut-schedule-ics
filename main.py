from bs4 import BeautifulSoup
from collections import Counter
import urllib.parse
import datetime
import requests
import xlrd
from dataclasses import dataclass
import icalendar
import re
import os
import hashlib


WEB_PAGE = 'https://it.pk.edu.pl/studenci/na-studiach/rozklady-zajec/'


@dataclass
class CalendarEntry:
    content: str
    start: datetime.datetime
    end: datetime.datetime

def clean_ics():
    for entry in os.listdir('build'):
        if entry.endswith('.ics'):
            os.remove(f'build/{entry}')

def generate_html(cals, groups):
    with open("index.html", 'r') as f:
        soup = BeautifulSoup(f, 'html.parser')

        ul = None
        prev_semester = None
        prev_degree = None
        for group_i in range(len(groups)):
            degree, semester, practice_group, lab_group, _identifier = groups[group_i]
            cal = cals[group_i]

            if semester != prev_semester:
                prev_semester = semester
                if ul:
                    soup.body.append(ul)
                if degree != prev_degree:
                    prev_degree = degree
                    h2 = soup.new_tag('h2')
                    h2.string = degree
                    soup.body.append(h2)
                h3 = soup.new_tag('h3')
                h3.string = semester
                soup.body.append(h3)
                ul = soup.new_tag('ul')
            li = soup.new_tag('li')
            if practice_group.isnumeric():
                li.string = f'Grupa ćwiczeniowa {practice_group} grupa laboratoryjna {lab_group}'
            else:
                li.string = f'Grupa {_identifier[:-2]}'
            # Create a link to download
            a_tag = soup.new_tag('a')
            a_tag.attrs['href'] = '/' + cal
            a_tag.string = cal
            li.append(a_tag)

            # Create a subscription link (supported by some email clients)
            sup_tag = soup.new_tag('sup')
            a_tag = soup.new_tag('a')
            a_tag.attrs['href'] = 'webcal://planpk.linguin.dev/' + cal
            a_tag.string = 'subskrybuj'
            sup_tag.append(a_tag)
            li.append(sup_tag)

            sup_tag = soup.new_tag('sup')
            a_tag = soup.new_tag('a')
            a_tag.attrs['href'] = '#'
            a_tag.attrs['class'] = 'link-copy'
            a_tag.attrs['data-cal-url'] = '/' + cal
            a_tag.string = 'kopiuj link'
            sup_tag.append(a_tag)
            li.append(sup_tag)

            ul.append(li)
        if ul:
            soup.body.append(ul)
        footer = soup.new_tag("footer")
        time = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
        p_tag = soup.new_tag('p')
        p_tag.string = f"Ostatnia aktualizacja: {time}"
        repo_link = soup.new_tag('a')
        repo_link.attrs['href'] = 'https://github.com/imLinguin/cut-schedule-ics'
        repo_link.string = 'GitHub'
        p_tag.append(repo_link)
        footer.append(p_tag)
        soup.body.append(footer)
        with open("build/index.html", 'w') as fw:
            fw.write(soup.prettify())

def load_schedule():
    session = requests.session()
    res = session.get(WEB_PAGE) 
    body = res.content
    existing_hash = None
    if os.path.exists('excel.xls'):
        existing_hash = hashlib.md5()
        with open('excel.xls', 'rb') as f:
            while data := f.read(1024):
                existing_hash.update(data)
            existing_hash = existing_hash.hexdigest()

    soup = BeautifulSoup(body, 'html.parser')
    links = soup.find_all('a')

    found_link = None
    for link in links:
        if 'Kierunek: Informatyka' in link.get_text():
            found_link = link.get('href')

    if not found_link:
        print('Failed to get a link')
        return

    if 'sharepoint.com' in found_link:
        parsed_link = urllib.parse.urlparse(found_link)
        query = urllib.parse.parse_qsl(parsed_link.query)
        query.append(('download', '1'))
        query = urllib.parse.urlencode(query)
        parsed_link = parsed_link._replace(query=query)
        found_link = urllib.parse.urlunparse(parsed_link)

    print('Getting', found_link)
    res = session.get(found_link, allow_redirects=True)
    excel_file = res.content
    new_hash = hashlib.md5(excel_file).hexdigest()
    print(f'::notice::Cached file hash is {existing_hash}')
    print(f'::notice::Downloaded file hash is {new_hash}')
    open('excel.xls', 'wb').write(excel_file)
    if 'CI' in os.environ and existing_hash and existing_hash == new_hash:
        print(f'::notice::Files are the same, skipping deployment')
        exit(1) 
        
def handle_type(summary):
    lower_summary = summary.lower()

    if "wykład" in lower_summary:
        return "wykład"
    elif "ćwiczenia" in lower_summary:
        return "ćwiczenia"
    elif "laboratorium" in lower_summary:
        return "laboratorium"
    elif "seminarium" in lower_summary:
        return "seminarium"
    elif "projekt" in lower_summary:
        return "projekt"
    elif "konsultacje" in lower_summary:
        return "konsultacje"
    
    
'''
Both of the following functions take data from the Excel sheet, yet this data is incomplete and not always accurate.
Fixing would require hard-coding this data, which is not a good idea, since it may change throughout the years.
'''    
    
def legenda(sh):
    for row in range(sh.nrows-1, 0, -1):
        for col in range(sh.ncols):
            if "legenda" in str(sh.cell(row, col).value).lower():
                return row
            
def GEO(sh):
    for row in range(sh.nrows-1, 0, -1):
        for col in range(sh.ncols):
            if "sale" in str(sh.cell(row, col).value).lower():
                return row

def main():
    os.makedirs("build", exist_ok=True)
    load_schedule()
    clean_ics()
    
    workbook = xlrd.open_workbook('excel.xls', formatting_info=True)
    sh = workbook.sheet_by_index(0)
    
    tags = {}
    location = {}
    
    for row in range(legenda(sh)+2, sh.nrows):
        if sh.row(row)[4].value:
            full_name = ""
            name = sh.row(row)[4].value.split(' ')
            for element in name:
                if any(character.isupper() for character in element) and "PK" not in element:
                    full_name += element + " "
            full_name = re.sub(r'[^\w\s-]', '', full_name.strip(), flags=re.UNICODE)
            tags[sh.row(row)[3].value] = (full_name, sh.row(row)[12].value)
            
    for row in range(GEO(sh)+1, sh.nrows):
        if sh.row(row)[19].value:
            location[sh.row(row)[19].value.split('-')[0].strip()] = sh.row(row)[19].value.split('-')[1].strip()
    
    
    mc = sh.merged_cells

    # Map values for merged cells
    merged_values = {}
    for (r1, r2, c1, c2) in mc:
        value = sh.cell(r1,c1)
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
        group_id = f'{mapped_value}-{group_occurences[mapped_value]}'
        # degree, year, practice group, laboratory group, groupid
        semester_groups.append((mapped_degree, mapped_year, mapped_value[1], lab, group_id))

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
        start, end = hour_range.value.split('-')
        start_h, start_m = start.split('.')
        end_h, end_m = end.split('.')
        date_start = date + datetime.timedelta(hours=int(start_h), minutes=int(start_m))
        date_end = date + datetime.timedelta(hours=int(end_h), minutes=int(end_m))
        group = 0

        for column in range(3, len(row)):
            timetable_key = group
            if not merged_values.get((6, column), sh.row(6)[column]).value:
                continue
            entry = merged_values.get((rowx, column), row[column])
            entry_value = entry.value
            if entry.ctype == 3 or (entry_value and re.match(r"\d\d?.\d\d-", entry_value) and len(entry_value) <= 11):
                continue
            if entry.ctype != 3 and entry_value:
                entry = timetable.get(timetable_key, [])
                cal = CalendarEntry(entry_value, date_start, date_end)
                entry.append(cal)
                timetable.update({timetable_key: entry})
            group += 1    
        
    
    #TODO to be optimized
    cals = []
    for key, value in timetable.items():
        cal = icalendar.Calendar()
        cal.add('prodid', '-//linguin.dev//cut-calendar-ics//PL')
        cal.add('version', '2.0')
        cal.add('X-WR-TIMEZONE', 'Europe/Warsaw')
        for event in value:
            SALA = None
            cal_event = icalendar.Event()
            summary = event.content
            summary = re.sub(r'\s+', ' ', summary)
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
                summary = re.sub(r'(?i)ZDALNIE', '', summary).strip()
                SALA = "ZDALNIE"
                
            elif "s." in summary:
                pos = summary.index("s.")
                SALA = summary[pos + len("s."):].strip().replace("s.", "")
                summary = summary[:pos].strip()
            
            cal_event.add('summary', summary)
            if SALA:
                cal_event.add('description', SALA)
                for loc in location:
                    if SALA in loc:
                        cal_event.add('location', "Kraków" + " " + location[loc])
            cal_event.add('dtstart', event.start)
            cal_event.add('dtend', event.end)
            cal_event.add('dtstamp', datetime.datetime.now())
            cal.add_component(cal_event)
            cal_event.add("category", handle_type(summary))

        group_id = semester_groups[key][4]
        cals.append(f'calendar-{group_id}.ics')
        with open(f'build/calendar-{group_id}.ics', 'wb') as f:
            f.write(cal.to_ical())
    
    generate_html(cals, semester_groups)

        
if __name__ == "__main__":
    main()
