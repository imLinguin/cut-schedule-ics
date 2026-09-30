<p align="center">
<img src="build/favicon.ico" width="75" />
</p>

<h1 align="center">cut-schedule-ics</h1>
<p align="center">Parser for the part-time (niestacjonarne) Computer Science schedule at Cracow Univiersity of Technology (CUT)</p>

## Availablility

The page with calendars is currently available at https://planpk.linguin.dev  
An CI action runs every two hours to ensure the data is up-to date and automatically deploys updated calendars as needed

The data comes from the Excel export of [FK Planer](https://ii.pk.edu.pl/~fkruzel/fk-planer-lti/public/plan-ns/).
Every column of that sheet (e.g. `GL1`, `Programowanie na platformie .NET K01`) becomes a separate calendar,
so everyone can subscribe to their base group plus the elective groups they are enrolled in.

## Running locally

Basic knowledge of python tooling including virtual environment (venv) management is required.

It is recommended to use a venv and run the code in there  
*or install dependencies globally with package manager, if on Linux*

Currently used dependencies:

- requests
  - Arch: python-requests
  - Ubuntu: python3-requests
  - Fedora: python3-requests
- openpyxl
  - Arch: python-openpyxl
  - Ubuntu: python3-openpyxl
  - Fedora: python3-openpyxl
- icalendar
  - Arch - python-icalendar
  - Ubuntu - python3-icalendar
  - Fedora - python3-icalendar

Create venv

```sh
python -m venv venv
```

Activate it

```
. venv/bin/activate # Unix
.\venv\scripts\activate # Windows
```

Install dependencies

```
pip install -r requirements.txt
```

Run the code

```
python main.py
```

The `build/` directory will contain all necessary files for hosting

Academic titles of teachers are not in the plan, they are stored in `data/teachers.json`
(from the [PK staff directory](https://spispracownikow.pk.edu.pl)).
When new teachers appear in the plan, refresh it with

```
python scripts/update_teachers.py
```
