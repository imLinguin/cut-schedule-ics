<p align="center">
<img src="build/favicon.ico" width="75" />
</p>

<h1 align="center">cut-schedule-ics</h1>
<p align="center">Parser for xls formatted schedule at Cracow Univiersity of Technology (CUT)</p>

## Availablility

The page with calendars is currently available at https://planpk.linguin.dev  
An CI action runs every two hours to ensure the data is up-to date and automatically deploys updated calendars as needed

## Running locally

Basic knowledge of python tooling including virtual environment (venv) management is required.

It is recommended to use a venv and run the code in there  
*or install dependencies globally with package manager, if on Linux*

Currently used dependencies:

- BeautifulSoup4
  - Arch: python-beautifulsoup4
  - Ubuntu: python3-bs4
  - Fedora: python3-beautifulsoup4
- requests
  - Arch: python-requests
  - Ubuntu: python3-requests
  - Fedora: python3-requests
- xlrd
  - Arch: python-xlrd
  - Ubuntu: python3-xlrd
  - Fedora: python3-xlrd
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
