from copy import deepcopy
import datetime
from pathlib import Path
import tempfile
import unittest

from icalendar import Calendar

from main import calendar_events, event_location, new_calendar, room_description
from utils.file_diff import file_diff
from utils.parse_schedule import Event, Rubric


class DisplayTests(unittest.TestCase):
    def make_event(self, activity="W", room="ONLINE", groups="K01+K02"):
        source = Event("Techniki multimedialne", activity, groups, "Jan Kowalski", room,
                       datetime.datetime(2026, 10, 3, 8), datetime.datetime(2026, 10, 3, 9, 30), "Z1")
        rubric = Rubric("I", "Rok 3 sem 5", "GL2", "i-rok-3-sem-5-gl2", events=[source])
        return calendar_events(rubric, {"L5": {"name": "L5 - 143", "campus": "Czyżyny"}}, {})[0]

    def test_online_type_subject_and_groups_in_requested_order(self):
        self.assertEqual("ONLINE – WYKŁAD Techniki multimedialne, grupa K01+K02",
                         str(self.make_event()["SUMMARY"]))

    def test_all_activity_labels_online_and_in_person(self):
        for activity, label in (("W", "WYKŁAD"), ("C", "ĆWICZENIA"), ("L", "LAB"),
                                ("P", "PROJEKT"), ("S", "SEMINARIUM")):
            for room in ("ONLINE", "L5"):
                with self.subTest(activity=activity, room=room):
                    prefix = "ONLINE – " if room == "ONLINE" else ""
                    self.assertEqual(f"{prefix}{label} Techniki multimedialne, grupa K01+K02",
                                     str(self.make_event(activity, room)["SUMMARY"]))

    def test_no_empty_group_suffix_or_extra_separator(self):
        self.assertEqual("WYKŁAD Techniki multimedialne", str(self.make_event(room="L5", groups="")["SUMMARY"]))
        self.assertEqual("ONLINE – Techniki multimedialne", str(self.make_event(activity="", groups="")["SUMMARY"]))

    def test_exercise_display_does_not_change_diff_identity(self):
        self.assertEqual("ĆW Techniki multimedialne", str(self.make_event(activity="C")["X-PK-KEY"]))

    def test_full_room_location_and_special_cases(self):
        cases = [
            ("L5", {"L5": {"name": "L5 - 143", "campus": "Czyżyny"}}, "L5 - 143, al. Jana Pawła II 37, Kraków"),
            ("S1", {"S1": {"name": "SEMINARYJNA", "campus": "Warszawska"}}, "S1 (SEMINARYJNA), ul. Warszawska 24, Kraków"),
            ("L5", {"L5": {"name": "L5 - 143", "campus": None}}, "L5 - 143"),
            ("L5", {"L5": {"name": None, "campus": "Czyżyny"}}, "L5, al. Jana Pawła II 37, Kraków"),
            ("X1", {}, "X1"),
            ("ONLINE", {}, "Online"),
            ("", {}, ""),
        ]
        for room, metadata, expected in cases:
            with self.subTest(room=room, metadata=metadata):
                self.assertEqual(expected, event_location(room, metadata))

    def test_room_description_keeps_existing_format(self):
        self.assertEqual("L5 - 143, kampus Czyżyny",
                         room_description("L5", {"L5": {"name": "L5 - 143", "campus": "Czyżyny"}}))

    def test_polish_summary_and_full_location_round_trip(self):
        value = self.make_event("C", "L5")
        restored = Calendar.from_ical(new_calendar("Test", [value]).to_ical()).walk("VEVENT")[0]
        self.assertEqual("ĆWICZENIA Techniki multimedialne, grupa K01+K02", str(restored["SUMMARY"]))
        self.assertEqual("L5 - 143, al. Jana Pawła II 37, Kraków", str(restored["LOCATION"]))

    def test_display_only_migration_does_not_notify_discord(self):
        new = self.make_event("C", "L5")
        old = deepcopy(new)
        old["SUMMARY"] = "ĆW K01+K02: Techniki multimedialne"
        old["LOCATION"] = "L5, al. Jana Pawła II 37, Kraków"
        with tempfile.TemporaryDirectory() as directory:
            before, after = Path(directory) / "before.ics", Path(directory) / "after.ics"
            before.write_bytes(new_calendar("Test", [old]).to_ical())
            after.write_bytes(new_calendar("Test", [new]).to_ical())
            self.assertEqual([], file_diff(before, after))
