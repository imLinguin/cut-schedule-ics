from bs4 import BeautifulSoup
import urllib.parse
import datetime
import requests
import xlrd
from dataclasses import dataclass
import icalendar
import re
import os

#test

WEB_PAGE = 'https://it.pk.edu.pl/studenci/na-studiach/rozklady-zajec/'


@dataclass
class CalendarEntry:
    content: str
    start: datetime.datetime
    end: datetime.datetime


def generate_html(cals):
    with open("index.html", 'r') as f:
        soup = BeautifulSoup(f, 'html.parser')

        ul = soup.new_tag('ul')
        for cal in cals:
            li = soup.new_tag('li')
            a_tag = soup.new_tag('a')
            a_tag.attrs['href'] = '/' + cal
            a_tag.string = cal
            li.append(a_tag)
            ul.append(li)
        soup.body.append(ul)
        footer = soup.new_tag("footer")
        time = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
        footer.string = f"Ostatnia aktualizacja: {time}"
        soup.body.append(footer)
        with open("build/index.html", 'w') as fw:
            fw.write(soup.prettify())

def load_schedule():
    session = requests.session()
    res = session.get(WEB_PAGE) 
    body = res.content

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
    open('excel.xls', 'wb').write(excel_file)
        
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
    workbook = xlrd.open_workbook('excel.xls', formatting_info=True)
    sh = workbook.sheet_by_index(0)
    
    tags = {
        
    }
    
    location = {
        
    }
    
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
    semesters = sh.row(5)
    """
    for colx in range(2, len(semesters)):
        mapped_value = merged_values.get((5, colx), semesters[colx].value)
        if len(mapped_value)
    """
    groups = sh.row(6)
    for colx in range(3, len(groups)):
        mapped_value = merged_values.get((6, colx), groups[colx]).value
        if type(mapped_value) is float or len(mapped_value) == 3:
            semester_groups.append(mapped_value)

    timetable = {}

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
            timetable_key = (groups[group], group)
            entry = merged_values.get((rowx, column), row[column])
            entry_value = entry.value
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
        for event in value:
            SALA = None
            cal_event = icalendar.Event()
            summary = event.content
            summary = re.sub(r'\s+', ' ', summary)
            
            for tag in tags:
        # Only process if summary does not contain "język"
                if "język" not in summary.lower():
                    updated = False
                    
                    # Check and replace in summary if the tag is found
                    if tag in summary:
                        summary = re.sub(tag, tags[tag][0], summary)
                        summary = re.sub(r'\s+', ' ', summary)
                        updated = True

                    # Once either substitution or organizer update happens, break out of the loop
                    if updated:
                        break
                        
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
            
        cals.append(f'calendar-{key[1]}.ics')
        with open(f'build/calendar-{key[1]}.ics', 'wb') as f:
            f.write(cal.to_ical())
    
    generate_html(cals)

        
if __name__ == "__main__":
    main()
