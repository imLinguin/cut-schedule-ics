<p align="center">
<img src="build/favicon.ico" width="75" />
</p>

<h1 align="center">cut-schedule-ics</h1>
<p align="center">Parser for the part-time (niestacjonarne) Computer Science schedule at Cracow Univiersity of Technology (CUT)</p>

## Availablility

The page with calendars is currently available at https://planpk.linguin.dev  
A CI action checks the plan every two hours at minute 17 (UTC), except in July and August,
and deploys when calendar contents or the page change. GitHub may delay scheduled runs.

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

`data/combos.json` defines hidden calendars that are the sum of existing ones
(e.g. `gomberman.ics`). They are not listed on the page and have no webhook notifications.
If a source group is removed, its events disappear from these combined calendars;
the combined calendar URLs remain unchanged, even when no groups remain.

## Synchronization and recovery

The workflow serializes runs and executes generation, validation, Pages deployment,
and Discord notification in that order. A `sync-state-*` Actions artifact records the
last completed synchronization, including its calendars. It is refreshed on every
successful check with 90-day retention, including checks without timetable changes.
The first run downloads the existing published calendars and saves that baseline
before any deployment. It cannot reconstruct notifications lost before this migration.

A failed deploy or notification leaves the previous checkpoint intact, so a later run
retries against it even if the Excel is unchanged. Discord failures turn the run red.
The Pages artifact is retained for the same period: if it is newer than the completed
checkpoint, the next run republishes even if the source has reverted to its old contents.
An uncertain HTTP result or failure saving the checkpoint can cause a repeated message;
delivery is not exactly-once. Intermediate source edits between checks are not an audit log.
If the latest checkpoint expires or no checkpoint remains, the workflow automatically
downloads and validates the published calendars, then saves that baseline before deploying.
Actions displays a warning: pending notifications about changes already published may
be lost. Future changes are compared normally. Do not delete artifacts as routine cleanup.
API/network errors, corrupt or incomplete checkpoints, and invalid published calendars
still stop the run; they never silently reset the notification baseline.

Removing a group removes its public link and ICS file. Discord notifies **only this
cohort**: I stopień, semesters 5/6 in academic year 2026/27 and 7/8 in 2027/28.
It switches when the next semester has classes in the source, using their dates
(academic years separated in August), not the current date or the largest semester
number belonging to other students. The reached semester is saved in the completed
checkpoint and never decreases; it stops at 8. Empty future columns do not advance it.
Edits, additions and removals outside that semester never notify, including deleted groups.
Messages identify the group, list detailed changes and mention only the `zaoczne`
role (`1286988227617488896`). Longer lists are attached in full.
Removed calendar subscriptions
may retain old events in client apps after their URL disappears. Surviving filenames
and the two combined-calendar URLs stay unchanged. A renamed source column is treated
as a removed group plus a new one; intentional renames need an explicit code mapping
if the old URL must be kept.

Malformed input, duplicate UIDs, invalid times or an entirely empty plan stops
publication. Removing a group or cancelling its last class does not; a surviving
group with no classes keeps its URL and publishes an empty calendar.
The workflow summary reports checks and completed steps; it is not an independent
monitor for GitHub's scheduler. Check Actions after the summer break, especially if
GitHub has disabled scheduling due to repository inactivity.

Run the regression tests without external services or a real Discord webhook.
Transport tests briefly bind an HTTP server to `127.0.0.1` on a random free port:

```sh
python -m unittest discover -s tests -v
```
