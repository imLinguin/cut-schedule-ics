import json
from pathlib import Path
import tempfile
import unittest

from helpers import calendar, event, manifest
from utils.sync_state import build_digest, validate_build


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.old, self.new = self.root / "old", self.root / "new"
        for directory in (self.old, self.new):
            manifest(directory, ["group-a.ics", "group-b.ics"])
            calendar(directory / "group-a.ics", [event()])
            calendar(directory / "group-b.ics", [event(subject="Grafika")])

    def test_removed_group_is_allowed_and_other_group_still_updates(self):
        manifest(self.new, ["group-a.ics"])
        (self.new / "group-b.ics").unlink()
        calendar(self.new / "group-a.ics", [event(room="L2")])
        self.assertEqual({"group-a.ics": 1}, validate_build(self.new, self.old))
        self.assertNotEqual(build_digest(self.old), build_digest(self.new))

    def test_cancelling_a_groups_last_class_publishes_an_empty_calendar(self):
        calendar(self.new / "group-a.ics", [])
        self.assertEqual({"group-a.ics": 0, "group-b.ics": 1}, validate_build(self.new, self.old))

    def test_completely_empty_plan_is_rejected(self):
        for name in ("group-a.ics", "group-b.ics"):
            calendar(self.new / name, [])
        with self.assertRaisesRegex(ValueError, "entire timetable"):
            validate_build(self.new)

    def test_empty_combo_after_removal_of_all_members_is_allowed(self):
        calendar(self.new / "gomberman.ics", [])
        self.assertEqual(0, validate_build(self.new, self.old, {"gomberman": ["deleted"]})["gomberman.ics"])

    def test_duplicate_uid_is_rejected(self):
        calendar(self.new / "group-a.ics", [event(), event(room="L2")])
        with self.assertRaisesRegex(ValueError, "duplicate UID"):
            validate_build(self.new)

    def test_end_before_start_is_rejected(self):
        calendar(self.new / "group-a.ics", [event(end="2026-10-03T07:00")])
        with self.assertRaisesRegex(ValueError, "times"):
            validate_build(self.new)

    def test_missing_file_and_stale_file_are_rejected(self):
        (self.new / "group-a.ics").unlink()
        with self.assertRaisesRegex(ValueError, "Missing or unexpected"):
            validate_build(self.new)
        calendar(self.new / "group-a.ics", [event()])
        calendar(self.new / "old-name.ics", [event()])
        with self.assertRaisesRegex(ValueError, "Missing or unexpected"):
            validate_build(self.new)

    def test_timestamp_and_manifest_order_do_not_trigger_deployment(self):
        calendar(self.new / "group-a.ics", [event(stamp="2026-10-01T00:00")])
        data = json.loads((self.new / "calendars.json").read_text())
        (self.new / "calendars.json").write_text(json.dumps(list(reversed(data)), indent=2))
        for directory, date in ((self.old, "01/09/2026 12:00"), (self.new, "01/10/2026 14:00")):
            (directory / "index.html").write_text("Ostatnia aktualizacja: " + date)
        self.assertEqual(build_digest(self.old), build_digest(self.new))

    def test_static_page_change_triggers_deployment(self):
        (self.new / "index.html").write_text("New template")
        self.assertNotEqual(build_digest(self.old), build_digest(self.new))

    def test_content_reverting_to_a_previous_version_is_detected(self):
        digest_a = build_digest(self.old)
        calendar(self.new / "group-a.ics", [event(room="L2")])
        digest_b = build_digest(self.new)
        self.assertNotEqual(digest_a, digest_b)
        calendar(self.new / "group-a.ics", [event()])
        self.assertEqual(digest_a, build_digest(self.new))
        self.assertNotEqual(digest_b, build_digest(self.new))
