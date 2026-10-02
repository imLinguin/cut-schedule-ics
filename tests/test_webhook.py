import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import requests

from helpers import calendar, event, manifest
from webhook import ZAOCZNE_ROLE_ID, dir_compare, format_message, send_message


def response(status, body=None, headers=None):
    result = Mock(status_code=status, headers=headers or {})
    result.json.return_value = body if body is not None else {"id": "123"}
    return result


class NotificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.old, self.new = Path(self.temp.name) / "old", Path(self.temp.name) / "new"

    def test_deleted_group_from_other_year_is_ignored_without_reading_its_file(self):
        manifest(self.old, ["i-rok-1-sem-1-gl1.ics", "i-rok-3-sem-5-gl2.ics"])
        manifest(self.new, ["i-rok-3-sem-5-gl2.ics"])
        for directory in (self.old, self.new):
            calendar(directory / "i-rok-3-sem-5-gl2.ics", [event()])
        message = format_message(dir_compare(self.old, self.new))
        self.assertEqual("", message)

    def test_regular_changes_outside_target_year_are_not_reported(self):
        for directory in (self.old, self.new):
            manifest(directory, ["i-rok-1-sem-1-gl1.ics"])
        calendar(self.old / "i-rok-1-sem-1-gl1.ics", [event()])
        calendar(self.new / "i-rok-1-sem-1-gl1.ics", [event(room="L2")])
        self.assertEqual([], dir_compare(self.old, self.new))

    def test_new_calendar_is_announced(self):
        manifest(self.old, ["i-rok-1-gl1.ics"])
        manifest(self.new, ["i-rok-1-gl1.ics", "i-rok-3-sem-5-gl2.ics"])
        calendar(self.new / "i-rok-3-sem-5-gl2.ics", [event()])
        self.assertIn("Nowa grupa", format_message(dir_compare(self.old, self.new)))

    @patch("webhook.requests.post")
    def test_confirmation_and_timeout_are_required(self, post):
        post.return_value = response(200)
        send_message("https://example.test/secret", "message")
        self.assertEqual({"wait": "true"}, post.call_args.kwargs["params"])
        self.assertEqual((10, 30), post.call_args.kwargs["timeout"])
        self.assertEqual({"parse": [], "roles": [ZAOCZNE_ROLE_ID]},
                         post.call_args.kwargs["json"]["allowed_mentions"])
        post.return_value = response(204, {})
        with self.assertRaisesRegex(RuntimeError, "did not confirm"):
            send_message("https://example.test/secret", "message")

    @patch("webhook.time.sleep")
    @patch("webhook.requests.post")
    def test_rate_limit_then_success(self, post, sleep):
        post.side_effect = [response(429, {"retry_after": 3}, {"Retry-After": "3"}), response(200)]
        send_message("https://example.test/secret", "message")
        self.assertEqual(2, post.call_count)
        sleep.assert_called_once_with(3)

    @patch("webhook.time.sleep")
    @patch("webhook.requests.post")
    def test_server_errors_are_retried_but_not_swallowed(self, post, sleep):
        post.return_value = response(503)
        with self.assertRaisesRegex(RuntimeError, "HTTP 503"):
            send_message("https://example.test/secret", "message")
        self.assertEqual(3, post.call_count)

    @patch("webhook.requests.post")
    def test_permanent_error_is_not_retried(self, post):
        post.return_value = response(404)
        with self.assertRaisesRegex(RuntimeError, "HTTP 404"):
            send_message("https://example.test/secret", "message")
        self.assertEqual(1, post.call_count)

    @patch("webhook.requests.post")
    def test_api_error_code_identifies_configuration_problem_without_exposing_response(self, post):
        for status, code, reason in ((404, 10015, "unknown webhook"),
                                     (404, 10003, "unknown channel"),
                                     (401, 50027, "invalid webhook token")):
            with self.subTest(code=code):
                post.reset_mock()
                post.return_value = response(status, {"code": code, "message": "https://example.test/secret-token"})
                with self.assertRaisesRegex(RuntimeError, reason) as failure:
                    send_message("https://example.test/secret-token", "message")
                self.assertIn(str(code), str(failure.exception))
                self.assertNotIn("secret-token", str(failure.exception))
                self.assertEqual(1, post.call_count)

    @patch("webhook.requests.post")
    def test_non_json_error_has_actionable_safe_message(self, post):
        post.return_value = response(404)
        post.return_value.json.side_effect = ValueError("secret-token")
        with self.assertRaisesRegex(RuntimeError, "check DISCORD_WEBHOOK_URL") as failure:
            send_message("https://example.test/secret-token", "message")
        self.assertNotIn("secret-token", str(failure.exception))

    @patch("webhook.requests.post")
    def test_missing_secret_fails_without_network_request(self, post):
        with self.assertRaisesRegex(RuntimeError, "Missing DISCORD_WEBHOOK_URL"):
            send_message("  \n", "message")
        post.assert_not_called()

    @patch("webhook.requests.post")
    def test_surrounding_whitespace_in_secret_is_ignored(self, post):
        post.return_value = response(200)
        send_message(" https://example.test/secret\n", "message")
        self.assertEqual("https://example.test/secret", post.call_args.args[0])

    @patch("webhook.time.sleep")
    @patch("webhook.requests.post")
    def test_connection_failure_does_not_expose_webhook_token(self, post, sleep):
        post.side_effect = requests.Timeout("https://example.test/secret-token")
        with self.assertRaises(RuntimeError) as failure:
            send_message("https://example.test/secret-token", "message")
        self.assertNotIn("secret-token", str(failure.exception))
        self.assertEqual(3, post.call_count)

    @patch("webhook.time.sleep")
    @patch("webhook.requests.post")
    def test_long_rate_limit_fails_without_excessive_sleep(self, post, sleep):
        post.return_value = response(429, headers={"Retry-After": "300"})
        with self.assertRaisesRegex(RuntimeError, "retry budget"):
            send_message("https://example.test/secret", "message")
        sleep.assert_not_called()

    @patch("webhook.requests.post")
    def test_large_change_list_is_attached_not_discarded(self, post):
        post.return_value = response(200)
        message = "Grupa usunięta\n" * 300
        send_message("https://example.test/secret", message)
        arguments = post.call_args.kwargs
        self.assertLessEqual(len(json.loads(arguments["data"]["payload_json"])["content"]), 2000)
        self.assertEqual(message.encode(), arguments["files"]["file"][1])
        payload = json.loads(arguments["data"]["payload_json"])
        self.assertTrue(payload["content"].startswith(f"<@&{ZAOCZNE_ROLE_ID}>"))
        self.assertNotIn("@everyone", payload["content"])
        self.assertEqual({"parse": [], "roles": [ZAOCZNE_ROLE_ID]}, payload["allowed_mentions"])

    @patch("webhook.requests.post")
    def test_no_changes_never_sends(self, post):
        send_message("https://example.test/secret", "")
        post.assert_not_called()
