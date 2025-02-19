from bs4 import BeautifulSoup
import urllib.parse
import datetime
import requests
import xlrd
from dataclasses import dataclass
import icalendar


WEB_PAGE = 'https://it.pk.edu.pl/studenci/na-studiach/rozklady-zajec/'


@dataclass
class CalendarEntry:
    content: str
    start: datetime.datetime
    end: datetime.datetime

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
        
     

def main():
    load_schedule()
    workbook = xlrd.open_workbook('excel.xls', formatting_info=True)
    sh = workbook.sheet_by_index(0)
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
    # TODO: change length
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
    for key, value in timetable.items():
        cal = icalendar.Calendar()
        cal.add('version', '2.0')
        for event in value:
            cal_event = icalendar.Event()
            cal_event.add('summary', event.content.strip().split('\t')[0].strip())
            cal_event.add('dtstart', event.start)
            cal_event.add('dtend', event.end)
            cal_event.add('dtstamp', datetime.datetime.now())
            cal.add_component(cal_event)

        with open(f'calendar-{key[1]}.ics', 'wb') as f:
            f.write(cal.to_ical())
            

        
if __name__ == "__main__":
    main()
