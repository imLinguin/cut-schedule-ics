"""Synthetic full-feed updates: edits, cancellations, additions and overlaps."""
from dataclasses import replace
import datetime
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from icalendar import Calendar

from helpers import manifest
from main import build_combos, calendar_events, new_calendar
from utils.file_diff import file_diff
from utils.parse_schedule import Event, Rubric
from utils.sync_state import validate_build


class CalendarUpdateTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.source = Event("Sieci", "L", "GL2", "Jan Kowalski", "L5",
                            datetime.datetime(2026, 10, 24, 8),
                            datetime.datetime(2026, 10, 24, 9, 30), "Z1")
        self.rubric = Rubric("I", "Rok 3 sem 5", "GL2", "i-rok-3-sem-5-gl2")

    def export(self, name, events, rubric=None):
        rubric = replace(rubric or self.rubric, events=events)
        raw = new_calendar("Synthetic test", calendar_events(rubric, {}, {})).to_ical()
        path = self.root / name
        path.write_bytes(raw)
        return path, Calendar.from_ical(raw).walk("VEVENT")

    def test_mutation_matrix_through_serialized_ics(self):
        day = datetime.timedelta(days=1)
        hour = datetime.timedelta(hours=1)
        cases = [
            ("no change", {}, True, set()),
            ("teacher", {"teacher": "Anna Nowak"}, True, {"teacher_changed"}),
            ("room", {"room": "L4"}, True, {"room_changed"}),
            ("online", {"room": "ONLINE"}, True, {"room_changed"}),
            ("missing room", {"room": ""}, True, {"room_changed"}),
            ("groups", {"groups": "GL3"}, True, {"groups_changed"}),
            ("merged groups", {"groups": "GL2+GL3"}, True, {"groups_changed"}),
            ("end only", {"end": self.source.end + hour}, True, {"time_changed"}),
            ("start only", {"start": self.source.start + hour}, False, {"time_changed"}),
            ("whole time slot", {"start": self.source.start + hour, "end": self.source.end + hour}, False, {"time_changed"}),
            ("next day across DST", {"start": self.source.start + day, "end": self.source.end + day}, False, {"date_changed"}),
            ("subject spelling", {"subject": "Sieci komputerowe"}, False, {"event_added", "event_removed"}),
            ("activity", {"activity": "C"}, False, {"event_added", "event_removed"}),
            ("weekend label", {"weekend": "Z2"}, True, set()),
            ("time room teacher together", {"start": self.source.start + hour,
             "end": self.source.end + hour, "room": "L4", "teacher": "Anna Nowak"},
             False, {"time_changed", "room_changed", "teacher_changed"}),
        ]
        old_path, old = self.export("old.ics", [self.source])
        for label, changes, same_uid, diff_kinds in cases:
            with self.subTest(change=label):
                new_path, new = self.export("new.ics", [replace(self.source, **changes)])
                self.assertEqual(1, len(new))
                self.assertEqual(same_uid, old[0]["UID"] == new[0]["UID"])
                self.assertEqual(diff_kinds, {d["change_type"] for d in file_diff(old_path, new_path)})
                # The latest full feed contains no stale old-time occurrence.
                self.assertEqual(changes.get("start", self.source.start), new[0]["DTSTART"].dt.replace(tzinfo=None))

    def test_existing_uid_formula_is_preserved_by_display_changes(self):
        _, events = self.export("feed.ics", [self.source])
        old_identity = "i-rok-3-sem-5-gl2|2026-10-24T08:00:00|Sieci|L"
        expected = hashlib.sha1(old_identity.encode()).hexdigest() + "@planpk.linguin.dev"
        self.assertEqual(expected, str(events[0]["UID"]))

    def test_calendar_label_change_preserves_uid_but_slug_change_does_not(self):
        _, old = self.export("old.ics", [self.source])
        _, label = self.export("label.ics", [self.source], replace(self.rubric, label="Grupa GL2"))
        _, slug = self.export("slug.ics", [self.source], replace(self.rubric, slug="i-rok-3-sem-5-gl3"))
        self.assertEqual(old[0]["UID"], label[0]["UID"])
        self.assertNotEqual(old[0]["UID"], slug[0]["UID"])

    def test_removal_addition_and_reordering_do_not_renumber_other_occurrences(self):
        second = replace(self.source, start=self.source.start + datetime.timedelta(hours=2),
                         end=self.source.end + datetime.timedelta(hours=2))
        added = replace(self.source, subject="Grafika")
        old_path, old = self.export("old.ics", [self.source, second])
        reordered_path, reordered = self.export("reordered.ics", [second, self.source])
        self.assertEqual([e["UID"] for e in old], [e["UID"] for e in reordered])
        self.assertEqual([], file_diff(old_path, reordered_path))
        removed_path, removed = self.export("removed.ics", [second])
        self.assertEqual(old[1]["UID"], removed[0]["UID"])
        self.assertEqual(["event_removed"], [d["change_type"] for d in file_diff(old_path, removed_path)])
        added_path, current = self.export("added.ics", [self.source, second, added])
        self.assertEqual(3, len({e["UID"] for e in current}))
        self.assertEqual(["event_added"], [d["change_type"] for d in file_diff(old_path, added_path)])

    def test_multiple_moved_occurrences_are_preserved_without_guessing_pairs(self):
        second = replace(self.source, start=self.source.start + datetime.timedelta(hours=2),
                         end=self.source.end + datetime.timedelta(hours=2))
        moved = [replace(e, start=e.start + datetime.timedelta(days=1),
                         end=e.end + datetime.timedelta(days=1)) for e in (self.source, second)]
        old_path, old = self.export("old.ics", [self.source, second])
        new_path, new = self.export("new.ics", moved)
        self.assertEqual(2, len(new))
        self.assertTrue({e["UID"] for e in old}.isdisjoint({e["UID"] for e in new}))
        kinds = [d["change_type"] for d in file_diff(old_path, new_path)]
        self.assertEqual(2, kinds.count("event_added"))
        self.assertEqual(2, kinds.count("event_removed"))

    def test_move_then_revert_restores_original_uid(self):
        _, old = self.export("old.ics", [self.source])
        _, moved = self.export("moved.ics", [replace(self.source, start=self.source.start + datetime.timedelta(hours=1))])
        _, restored = self.export("restored.ics", [self.source])
        self.assertNotEqual(old[0]["UID"], moved[0]["UID"])
        self.assertEqual(old[0]["UID"], restored[0]["UID"])

    def test_overlaps_with_distinct_start_or_subject_remain_in_feed(self):
        for other in (replace(self.source, subject="Grafika"),
                      replace(self.source, start=self.source.start + datetime.timedelta(minutes=30))):
            with self.subTest(other=other):
                _, events = self.export("feed.ics", [self.source, other])
                manifest(self.root, ["feed.ics"])
                self.assertEqual(2, len(events))
                self.assertEqual(2, validate_build(self.root)["feed.ics"])

    def test_same_subject_activity_and_start_keep_both_distinct_entries(self):
        for changes in ({"room": "L4"}, {"groups": "GL3"}, {"teacher": "Anna Nowak"},
                        {"end": self.source.end + datetime.timedelta(minutes=30)}):
            with self.subTest(changes=changes):
                _, events = self.export("feed.ics", [self.source, replace(self.source, **changes)])
                manifest(self.root, ["feed.ics"])
                self.assertEqual(2, len(events))
                self.assertNotEqual(events[0]["UID"], events[1]["UID"])
                self.assertEqual(2, validate_build(self.root)["feed.ics"])

    def test_reordering_simultaneous_entries_keeps_their_ids(self):
        sources = [self.source, replace(self.source, room="L4"), replace(self.source, teacher="Anna Nowak")]
        _, old = self.export("old.ics", sources)
        _, new = self.export("new.ics", list(reversed(sources)))
        def identities(events):
            return {(str(e["LOCATION"]), str(e["DESCRIPTION"])): str(e["UID"]) for e in events}
        self.assertEqual(3, len({e["UID"] for e in old}))
        self.assertEqual(identities(old), identities(new))

    def test_three_identical_source_entries_still_have_unique_ids(self):
        _, events = self.export("feed.ics", [self.source] * 3)
        manifest(self.root, ["feed.ics"])
        self.assertEqual(3, len({e["UID"] for e in events}))
        self.assertEqual(3, validate_build(self.root)["feed.ics"])

    def test_combo_shared_event_changes_uid_when_first_source_is_removed(self):
        cwd = Path.cwd()
        self.addCleanup(os.chdir, cwd)
        os.chdir(self.root)
        Path("build").mkdir()
        combos = self.root / "combos.json"
        combos.write_text(json.dumps({"gomberman": ["first", "second"]}))
        events = {slug: calendar_events(replace(self.rubric, slug=slug, events=[self.source]), {}, {})
                  for slug in ("first", "second")}
        with patch("main.COMBOS_FILE", str(combos)), patch("builtins.print"):
            build_combos(events)
            old = Calendar.from_ical(Path("build/gomberman.ics").read_bytes()).walk("VEVENT")
            build_combos({"second": events["second"]})
            new = Calendar.from_ical(Path("build/gomberman.ics").read_bytes()).walk("VEVENT")
        self.assertEqual(1, len(old))
        self.assertEqual(1, len(new))
        self.assertEqual(old[0]["SUMMARY"], new[0]["SUMMARY"])
        self.assertEqual(old[0]["DTSTART"].dt, new[0]["DTSTART"].dt)
        self.assertNotEqual(old[0]["UID"], new[0]["UID"])
