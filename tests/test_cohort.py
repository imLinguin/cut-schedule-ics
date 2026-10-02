import json
from pathlib import Path
import tempfile
import unittest

from helpers import calendar, event, manifest
from webhook import ZAOCZNE_ROLE_ID, cohort_scope, dir_compare, format_message


def name(semester, group="gl2", degree="i"):
    return f"{degree}-rok-{(semester + 1) // 2}-sem-{semester}-{group}.ics"


class CohortTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.old, self.new = Path(temp.name) / "old", Path(temp.name) / "new"

    def write(self, directory, entries):
        # Keep a non-target calendar so the overall timetable remains valid.
        entries = {"i-rok-1-sem-1-gl1.ics": "2026-10-03", **entries}
        manifest(directory, list(entries))
        for filename, day in entries.items():
            events = [] if day is None else [event(start=day + "T08:00", end=day + "T09:30")]
            calendar(directory / filename, events)

    def test_current_cohort_does_not_follow_older_students_in_semester_seven(self):
        entries = {name(5): "2026-10-03", name(7): "2026-10-03", name(5, degree="ii"): "2026-10-03"}
        for directory in (self.old, self.new):
            self.write(directory, entries)
        for filename in entries:
            calendar(self.new / filename, [event(room="L4")])
        changes = dir_compare(self.old, self.new)
        self.assertEqual(1, len(changes))
        self.assertIn(name(5)[:-4], changes[0]["label"])
        self.assertEqual(["room_changed"], [d["change_type"] for d in changes[0]["diffs"]])

    def test_sixth_semester_is_selected_as_soon_as_its_plan_appears(self):
        self.write(self.old, {name(5): "2026-10-03", name(7): "2026-10-03"})
        self.write(self.new, {name(5): "2026-10-03", name(6): "2027-02-27", name(7): "2026-10-03"})
        semester, _, selected = cohort_scope(self.old, self.new)
        self.assertEqual(6, semester)
        self.assertEqual({name(6)}, selected.keys())
        changes = dir_compare(self.old, self.new)
        self.assertEqual(1, len(changes))
        self.assertIn("Nowa grupa", changes[0]["notice"])
        self.assertEqual("2027-02-27", changes[0]["diffs"][0]["date"])

    def test_empty_future_columns_do_not_advance_the_cohort(self):
        self.write(self.old, {name(5): "2026-10-03"})
        self.write(self.new, {name(5): "2026-10-03", name(6): None, name(7): None, name(8): None})
        self.assertEqual(5, cohort_scope(self.old, self.new)[0])
        self.assertEqual([], dir_compare(self.old, self.new))

    def test_seventh_semester_uses_new_academic_year_not_old_cohorts_feed(self):
        self.write(self.old, {name(6): "2027-03-06", name(7): "2026-10-03"})
        self.write(self.new, {name(5): "2027-10-03", name(7): "2027-10-03"})
        semester, old, new = cohort_scope(self.old, self.new, 6)
        self.assertEqual(7, semester)
        self.assertEqual({}, old)
        self.assertEqual({name(7)}, new.keys())
        changes = dir_compare(self.old, self.new, 6)
        self.assertEqual(1, len(changes))
        self.assertIn("Nowa grupa", changes[0]["notice"])

    def test_eighth_semester_and_no_following_new_cohorts_after_graduation(self):
        self.write(self.old, {name(7): "2027-10-03", name(8): "2027-03-06"})
        self.write(self.new, {name(6): "2028-03-04", name(8): "2028-03-04"})
        semester, old, new = cohort_scope(self.old, self.new, 7)
        self.assertEqual(8, semester)
        self.assertEqual({}, old)
        self.assertEqual({name(8)}, new.keys())
        for directory in (self.old, self.new):
            self.write(directory, {name(5): "2028-10-07", name(7): "2028-10-07", name(8): "2029-03-03"})
        self.assertEqual([], dir_compare(self.old, self.new, 8))
        self.assertEqual(8, cohort_scope(self.old, self.new, 8)[0])

    def test_saved_semester_never_regresses_to_a_previous_semester(self):
        self.write(self.old, {name(5): "2026-10-03"})
        self.write(self.new, {name(5): "2026-10-04"})
        self.assertEqual([], dir_compare(self.old, self.new, 6))

    def test_only_removed_group_from_selected_semester_is_reported(self):
        self.write(self.old, {name(5): "2026-10-03", name(7): "2026-10-03"})
        self.write(self.new, {})
        changes = dir_compare(self.old, self.new)
        self.assertEqual(1, len(changes))
        self.assertIn("Grupa usunięta", changes[0]["notice"])
        self.assertEqual(["event_removed"], [d["change_type"] for d in changes[0]["diffs"]])

    def test_last_class_cancellation_is_reported_for_existing_empty_calendar(self):
        self.write(self.old, {name(5): "2026-10-03"})
        self.write(self.new, {name(5): None})
        changes = dir_compare(self.old, self.new)
        self.assertEqual(1, len(changes))
        self.assertNotIn("notice", changes[0])
        self.assertEqual("event_removed", changes[0]["diffs"][0]["change_type"])

    def test_group_heading_role_and_precise_change_details(self):
        filename = name(5, "techniki-multimedialne-k01")
        for directory in (self.old, self.new):
            self.write(directory, {filename: "2026-10-03"})
            path = directory / "calendars.json"
            entries = json.loads(path.read_text())
            entries[-1].update(year="Rok 3 sem 5", label="Techniki multimedialne K01")
            path.write_text(json.dumps(entries))
        calendar(self.new / filename, [event(end="2026-10-03T10:15", room="L4", teacher="Anna Nowak", groups="K01")])
        message = format_message(dir_compare(self.old, self.new))
        self.assertTrue(message.startswith(f"<@&{ZAOCZNE_ROLE_ID}>"))
        self.assertNotIn("@everyone", message)
        for detail in ("Techniki multimedialne K01", "2026-10-03", "09:30 -> 08:00 - 10:15", "L1 -> L4", "Jan Kowalski -> Anna Nowak", "GL2 -> K01"):
            self.assertIn(detail, message)

    def test_invalid_saved_semester_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "semester"):
            cohort_scope(self.old, self.new, 9)
