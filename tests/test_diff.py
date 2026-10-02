from pathlib import Path
import tempfile
import unittest

from helpers import calendar, event
from utils.file_diff import file_diff


class DiffTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def diff(self, old, new):
        return file_diff(calendar(self.root / "old.ics", old), calendar(self.root / "new.ics", new))

    def test_timestamp_alone_is_not_a_change(self):
        self.assertEqual([], self.diff([event()], [event(stamp="2026-10-01T00:00")]))

    def test_end_time_only(self):
        result = self.diff([event()], [event(end="2026-10-03T10:15")])
        self.assertEqual(["time_changed"], [d["change_type"] for d in result])
        self.assertIn("10:15", result[0]["details"])

    def test_teacher_and_group(self):
        result = self.diff([event()], [event(teacher="Anna Nowak", groups="GL1")])
        self.assertEqual({"teacher_changed", "groups_changed"}, {d["change_type"] for d in result})

    def test_added_academic_title_is_not_a_teacher_change(self):
        old = event(teacher="Świszcz Łukasz")
        self.assertEqual([], self.diff([old], [event(teacher="mgr inż. Świszcz Łukasz")]))
        self.assertEqual([], self.diff([old], [event(teacher="dr hab. inż. Świszcz Łukasz, prof. PK")]))
        result = self.diff([old], [event(teacher="dr Anna Nowak")])
        self.assertEqual(["teacher_changed"], [d["change_type"] for d in result])
        self.assertIn("dr Anna Nowak", result[0]["details"])

    def test_academic_titles_with_multiple_teachers_preserve_actual_changes(self):
        old = event(teacher="Jan Kowalski / Anna Nowak")
        titled = event(teacher="prof. dr hab. inż. Jan Kowalski / mgr Anna Nowak")
        self.assertEqual([], self.diff([old], [titled]))
        result = self.diff([titled], [event(teacher="prof. dr hab. inż. Jan Kowalski")])
        self.assertEqual(["teacher_changed"], [change["change_type"] for change in result])

    def test_moved_day_includes_time_and_room(self):
        result = self.diff([event()], [event(start="2026-10-04T10:00", end="2026-10-04T12:00", room="L2")])
        self.assertEqual({"date_changed", "time_changed", "room_changed"}, {d["change_type"] for d in result})

    def test_deleting_first_occurrence_does_not_move_the_second(self):
        later = event(start="2026-10-03T12:00", end="2026-10-03T13:30")
        result = self.diff([event(), later], [later])
        self.assertEqual(["event_removed"], [d["change_type"] for d in result])
        self.assertIn("08:00", result[0]["details"])

    def test_unchanged_occurrence_matched_before_edited_one(self):
        later = event(start="2026-10-03T12:00", end="2026-10-03T13:30")
        result = self.diff([event(), later], [event(end="2026-10-03T10:00"), later])
        self.assertEqual(["time_changed"], [d["change_type"] for d in result])

    def test_ambiguous_moves_are_additions_and_removals(self):
        result = self.diff(
            [event(), event(start="2026-10-03T12:00", end="2026-10-03T13:30")],
            [event(start="2026-10-04T08:00", end="2026-10-04T09:30"),
             event(start="2026-10-04T12:00", end="2026-10-04T13:30")])
        self.assertEqual(2, sum(d["change_type"] == "event_added" for d in result))
        self.assertEqual(2, sum(d["change_type"] == "event_removed" for d in result))

    def test_legacy_title_can_be_compared(self):
        old = event()
        old.pop("X-PK-KEY")
        old["SUMMARY"] = "Sieci (L)"
        self.assertEqual([], self.diff([old], [event()]))

    def test_event_order_does_not_matter(self):
        a, b = event(), event(subject="Grafika")
        self.assertEqual([], self.diff([a, b], [b, a]))

    def test_real_room_change_is_detected_using_full_description(self):
        old, new = event(room="L5, Kraków"), event(room="L4 - 136, Kraków")
        old["DESCRIPTION"] += "\nSala: L5 - 143, kampus Czyżyny"
        new["DESCRIPTION"] += "\nSala: L4 - 136, kampus Czyżyny"
        result = self.diff([old], [new])
        self.assertEqual(["room_changed"], [d["change_type"] for d in result])
        self.assertIn("L4 - 136", result[0]["details"])
