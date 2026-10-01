import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import requests

from utils.load_schedule import _get, load_rooms, load_schedule


class LoadingTests(unittest.TestCase):
    def setUp(self):
        output = patch("sys.stdout", new_callable=io.StringIO)
        output.start()
        self.addCleanup(output.stop)

    @patch("utils.load_schedule.time.sleep")
    def test_get_retries_transient_errors_and_hides_signed_urls(self, sleep):
        session = Mock()
        session.get.side_effect = requests.Timeout("https://example.test/?secret=token")
        with self.assertRaisesRegex(RuntimeError, "network error") as failure:
            _get(session, "https://example.test")
        self.assertEqual(3, session.get.call_count)
        self.assertNotIn("secret", str(failure.exception))

    @patch("utils.load_schedule.time.sleep")
    def test_get_does_not_retry_permanent_errors(self, sleep):
        session = Mock()
        response = Mock(status_code=404)
        session.get.return_value.raise_for_status.side_effect = requests.HTTPError(response=response)
        with self.assertRaisesRegex(RuntimeError, "HTTP 404"):
            _get(session, "https://example.test")
        self.assertEqual(1, session.get.call_count)
        sleep.assert_not_called()

    @patch("utils.load_schedule._get")
    def test_identical_download_is_still_parsed_in_ci(self, get):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "plan.xlsx"
            file.write_bytes(b"PKsame-content")
            get.return_value.content = b"PKsame-content"
            with patch("utils.load_schedule.EXCEL_FILE", str(file)), patch.dict(os.environ, {"CI": "true"}):
                self.assertTrue(load_schedule())

    @patch("utils.load_schedule._get")
    def test_html_error_page_does_not_replace_source(self, get):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "plan.xlsx"
            file.write_bytes(b"previous-source")
            get.return_value.content = b"<html>Error</html>"
            with patch("utils.load_schedule.EXCEL_FILE", str(file)), self.assertRaises(RuntimeError):
                load_schedule()
            self.assertEqual(b"previous-source", file.read_bytes())

    @patch("utils.load_schedule._get")
    def test_room_failure_uses_last_known_metadata(self, get):
        old = {"L1": {"campus": "Czyżyny", "name": "L1"}}
        for broken in ({"state": {"rooms": [{}]}}, {"state": {}}):
            get.return_value.json.return_value = broken
            self.assertEqual(old, load_rooms(fallback=old))
        get.side_effect = RuntimeError("network error")
        self.assertEqual(old, load_rooms(fallback=old))
