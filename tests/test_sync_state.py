import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile

from helpers import calendar, event, manifest
from utils.sync_state import _extract_state, restore_state, stage_state


def archive_bytes(include_calendar=True):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("state.json", json.dumps({"version": 1, "rooms": {}, "files": ["group.ics"]}))
        archive.writestr("build/calendars.json", json.dumps([
            {"file": "group.ics", "degree": "I", "year": "Rok 3", "label": "GL2"}]))
        if include_calendar:
            from icalendar import Calendar
            cal = Calendar()
            cal.add("version", "2.0")
            cal.add_component(event())
            archive.writestr("build/group.ics", cal.to_ical())
    return stream.getvalue()


def artifact(name, identity=1, expired=False, branch="main"):
    return {"name": name, "id": identity, "created_at": "2026-09-01T00:00:00Z",
            "expired": expired, "archive_download_url": "https://example.test/archive",
            "workflow_run": {"head_branch": branch, "head_repository_id": 1, "repository_id": 1}}


class StateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        old_cwd = Path.cwd()
        os.chdir(self.temp.name)
        self.addCleanup(os.chdir, old_cwd)
        env = patch.dict(os.environ, {"GITHUB_REPOSITORY": "owner/repo", "GITHUB_TOKEN": "test"}, clear=True)
        env.start()
        self.addCleanup(env.stop)

    @patch("utils.sync_state._get")
    def test_restores_checkpoint_even_after_more_than_seven_days(self, get):
        get.side_effect = [Mock(json=Mock(return_value={"artifacts": [artifact("sync-state-1-1")]})),
                           Mock(content=archive_bytes())]
        restore_state()
        self.assertTrue(Path("sync-state/state.json").exists())
        self.assertEqual(2, get.call_count)

    @patch("utils.sync_state._get")
    def test_ignores_uncommitted_page_artifacts_and_other_branches(self, get):
        get.side_effect = [Mock(json=Mock(return_value={"artifacts": [
            artifact("github-pages-99-2", 3), artifact("sync-state-2-1", 2, branch="feature"),
            artifact("sync-state-1-1", 1)]})), Mock(content=archive_bytes())]
        os.environ["GITHUB_OUTPUT"] = str(Path("outputs.txt").resolve())
        restore_state()
        self.assertEqual("https://example.test/archive", get.call_args.args[1])
        self.assertIn("force_deploy=true", Path("outputs.txt").read_text())

    @patch("utils.sync_state._get")
    def test_completed_checkpoint_after_deployment_does_not_force_republish(self, get):
        get.side_effect = [Mock(json=Mock(return_value={"artifacts": [
            artifact("sync-state-3-1", 3), artifact("github-pages", 2),
            artifact("sync-state-1-1", 1)]})), Mock(content=archive_bytes())]
        os.environ["GITHUB_OUTPUT"] = str(Path("outputs.txt").resolve())
        restore_state()
        self.assertIn("force_deploy=false", Path("outputs.txt").read_text())

    @patch("utils.sync_state._get")
    def test_expired_state_is_not_silently_treated_as_no_changes(self, get):
        get.return_value.json.return_value = {"artifacts": [artifact("sync-state-1-1", expired=True)]}
        with self.assertRaisesRegex(RuntimeError, "expired"):
            restore_state()

    @patch("utils.sync_state._get")
    def test_corrupt_checkpoint_does_not_fall_back_to_a_different_baseline(self, get):
        get.side_effect = [Mock(json=Mock(return_value={"artifacts": [artifact("sync-state-1-1")]})),
                           Mock(content=b"invalid zip")]
        with self.assertRaises(zipfile.BadZipFile):
            restore_state()
        self.assertEqual(2, get.call_count)

    def test_archive_cannot_write_outside_state_directory(self):
        content = io.BytesIO()
        with zipfile.ZipFile(content, "w") as archive:
            archive.writestr("../escape.txt", "bad")
        with self.assertRaisesRegex(ValueError, "archive path"):
            _extract_state(content.getvalue(), "sync-state")
        self.assertFalse(Path("escape.txt").exists())

    def test_checkpoint_without_its_calendar_files_is_rejected(self):
        with self.assertRaises((ValueError, FileNotFoundError)):
            _extract_state(archive_bytes(include_calendar=False), "sync-state")

    @patch("utils.sync_state._get")
    def test_newest_expired_checkpoint_does_not_fall_back_to_older_state(self, get):
        get.side_effect = [Mock(json=Mock(return_value={"artifacts": [
            artifact("sync-state-2-1", 2, expired=True), artifact("sync-state-1-1", 1)]})),
            Mock(content=archive_bytes())]
        with self.assertRaisesRegex(RuntimeError, "expired"):
            restore_state()

    @patch("utils.sync_state._get")
    def test_missing_checkpoint_after_managed_deploy_is_not_a_first_run(self, get):
        get.return_value.json.return_value = {"artifacts": [artifact("github-pages-10-1", 10)]}
        with self.assertRaisesRegex(RuntimeError, "checkpoint"):
            restore_state()

    @patch("utils.sync_state._get")
    def test_pagination_preserves_newer_unfinished_deployment(self, get):
        first_page = [artifact("unrelated", i) for i in range(101, 200)]
        first_page.append(artifact("github-pages-200-1", 200))
        get.side_effect = [Mock(json=Mock(return_value={"artifacts": first_page})),
                           Mock(json=Mock(return_value={"artifacts": [artifact("sync-state-100-1", 100)]})),
                           Mock(content=archive_bytes())]
        os.environ["GITHUB_OUTPUT"] = str(Path("outputs.txt").resolve())
        restore_state()
        self.assertIn("page=2", get.call_args_list[1].args[1])
        self.assertIn("force_deploy=true", Path("outputs.txt").read_text())

    def test_candidate_snapshot_does_not_overwrite_completed_state(self):
        manifest("build", ["group.ics"])
        calendar("build/group.ics", [event()])
        stage_state("build", {}, "sync-state")
        old = Path("sync-state/build/group.ics").read_bytes()
        calendar("build/group.ics", [event(room="L2")])
        stage_state("build", {})
        self.assertEqual(old, Path("sync-state/build/group.ics").read_bytes())
        self.assertNotEqual(old, Path("next-state/build/group.ics").read_bytes())

    @patch("utils.sync_state._get")
    def test_first_run_preserves_published_baseline_before_deployment(self, get):
        Path("data").mkdir()
        Path("data/combos.json").write_text(json.dumps({"gomberman": ["group"], "sztywne-gity": ["group"]}))
        manifest("published", ["group.ics"])
        content = calendar("published/group.ics", [event()]).read_bytes()
        manifest_content = Path("published/calendars.json").read_bytes()
        get.side_effect = [Mock(json=Mock(return_value={"artifacts": []})),
                           Mock(content=manifest_content),
                           Mock(content=content), Mock(content=content), Mock(content=content),
                           Mock(content=manifest_content)]
        os.environ["GITHUB_OUTPUT"] = str(Path("outputs.txt").resolve())
        restore_state()
        self.assertIn("bootstrap=true", Path("outputs.txt").read_text())
        self.assertEqual(content, Path("sync-state/build/group.ics").read_bytes())
        self.assertTrue(Path("sync-state/build/gomberman.ics").exists())
        self.assertFalse(Path("next-state").exists())
