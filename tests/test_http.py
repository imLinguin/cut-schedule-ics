"""Real Requests transport against a disposable loopback-only HTTP server."""
from collections import deque
from contextlib import contextmanager
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Thread
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from utils.load_schedule import _get, _session
from webhook import send_message


@contextmanager
def server(responses):
    pending, calls = deque(responses), []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def handle_request(self):
            data = self.rfile.read(int(self.headers.get('Content-Length', 0)))
            calls.append((self.command, self.path, dict(self.headers), data))
            status, headers, body = pending.popleft() if pending else (500, {}, b'Unexpected request')
            self.send_response(status)
            for name, value in headers.items():
                self.send_header(name, value)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        do_GET = handle_request
        do_POST = handle_request

    service = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = Thread(target=service.serve_forever, kwargs={'poll_interval': 0.01}, daemon=True)
    worker.start()
    try:
        yield f'http://127.0.0.1:{service.server_port}', calls
    finally:
        service.shutdown()
        service.server_close()
        worker.join(timeout=2)


class HTTPTests(unittest.TestCase):
    def test_real_get_retries_http_503_then_reads_success(self):
        with server([(503, {}, b'temporary'), (200, {}, b'PKworkbook')]) as (url, calls):
            with _session() as session, patch('utils.load_schedule.time.sleep'):
                self.assertEqual(b'PKworkbook', _get(session, url).content)
            self.assertEqual(2, len(calls))

    def test_authorization_is_not_forwarded_to_cross_origin_download_redirect(self):
        with server([(200, {}, b'archive')]) as (download, received):
            with server([(302, {'Location': download + '/asset'}, b'')]) as (api, original):
                with _session() as session:
                    session.headers['Authorization'] = 'Bearer fake-test-token'
                    self.assertEqual(b'archive', _get(session, api).content)
                self.assertIn('Authorization', original[0][2])
                self.assertNotIn('Authorization', received[0][2])

    def test_discord_json_wait_confirmation_and_unicode(self):
        with server([(200, {'Content-Type': 'application/json'}, b'{"id":"123"}')]) as (url, calls):
            send_message(url + '/webhook?thread_id=42', '<@&1286988227617488896>\nGrupa usunięta — GL2')
            method, path, headers, body = calls[0]
            self.assertEqual('POST', method)
            self.assertEqual({'thread_id': ['42'], 'wait': ['true']}, parse_qs(urlsplit(path).query))
            self.assertEqual('<@&1286988227617488896>\nGrupa usunięta — GL2', json.loads(body)['content'])
            self.assertEqual({'parse': [], 'roles': ['1286988227617488896']}, json.loads(body)['allowed_mentions'])

    def test_discord_rate_limit_body_retries_without_real_wait(self):
        responses = [(429, {'Content-Type': 'application/json'}, b'{"retry_after":0.1}'),
                     (200, {'Content-Type': 'application/json'}, b'{"id":"123"}')]
        with server(responses) as (url, calls), patch('webhook.time.sleep') as sleep:
            send_message(url, 'message')
            self.assertEqual(2, len(calls))
            sleep.assert_called_once_with(0.1)

    def test_large_message_is_real_multipart_with_complete_utf8_attachment(self):
        with server([(200, {}, b'{"id":"123"}')]) as (url, calls):
            text = 'Usunięto grupę — ćwiczenia\n' * 200
            send_message(url, text)
            headers, body = calls[0][2:]
            content = BytesParser(policy=policy.default).parsebytes(
                ('Content-Type: ' + headers['Content-Type'] + '\r\n\r\n').encode() + body)
            parts = {part.get_param('name', header='content-disposition'): part for part in content.iter_parts()}
            self.assertEqual(text, parts['file'].get_payload(decode=True).decode())
            self.assertLessEqual(len(json.loads(parts['payload_json'].get_payload(decode=True))['content']), 2000)

    def test_discord_redirect_is_not_followed(self):
        with server([(302, {'Location': '/unexpected'}, b'')]) as (url, calls):
            with self.assertRaisesRegex(RuntimeError, 'HTTP 302'):
                send_message(url, 'message')
            self.assertEqual(1, len(calls))

    def test_invalid_json_response_is_not_acknowledged(self):
        with server([(200, {}, b'<html>gateway error</html>')]) as (url, calls):
            with self.assertRaisesRegex(RuntimeError, 'did not confirm'):
                send_message(url, 'message')
            self.assertEqual(1, len(calls))
