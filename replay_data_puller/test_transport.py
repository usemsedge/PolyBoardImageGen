"""Offline transport tests; run this file by absolute path with python -I."""

import datetime as dt
import email.message
import errno
import http.client
import importlib.util
import io
import json
from pathlib import Path
import ssl
import subprocess
import tempfile
import unittest
from unittest import mock
import urllib.error

_SPEC = importlib.util.spec_from_file_location(
    "capture_transport_under_test", Path(__file__).with_name("transport.py"))
transport = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(transport)
ENDPOINT = "https://example.invalid/api/game"
JWT = "private-test-token"


def headers(pairs=()):
    result = email.message.Message()
    for key, value in pairs:
        result[key] = value
    return result


class Response(io.BytesIO):
    def __init__(self, content=b"", status=200, pairs=()):
        super().__init__(content)
        self.code = status
        self.headers = headers(pairs)


class PartialResponse(Response):
    read1 = None

    def __init__(self, content, error):
        super().__init__(content)
        self.error = error
        self.first = True
        self.read1 = self.read

    def read(self, size=-1):
        if self.first:
            self.first = False
            return super().read(size)
        raise self.error


class FakeProcess:
    def __init__(self, content, code=0):
        self.stdin = io.BytesIO()
        self.stdout = io.BytesIO(content)
        self.code = code
        self.killed = False
        self.input = None
        original_close = self.stdin.close

        def close():
            if not self.stdin.closed:
                self.input = self.stdin.getvalue()
            original_close()

        self.stdin.close = close

    def kill(self):
        self.killed = True

    def wait(self, timeout=None):
        return self.code

    def poll(self):
        return self.code


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        # Fail closed if any test forgets to mock the network/subprocess.
        self.opener = mock.Mock()
        self.opener.open.side_effect = AssertionError("unexpected network")
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(transport, "_make_opener", return_value=self.opener).start()
        self.popen = mock.patch.object(transport.subprocess, "Popen",
                                       side_effect=AssertionError("unexpected subprocess")).start()

    def fetch(self, response=None, **kwargs):
        if response is not None:
            self.opener.open.side_effect = None
            self.opener.open.return_value = response
        return transport.fetch(ENDPOINT, JWT, {"GameId": "fixture"},
                               self.directory, **kwargs)

    def assert_archive(self, metadata, content):
        self.assertEqual((self.directory / "response.body").read_bytes(), content)
        stored = json.loads((self.directory / "response.json").read_text())
        self.assertEqual(stored["body_bytes"], len(content))
        self.assertEqual(stored["transport_result"], metadata["transport_result"])
        self.assertNotIn(JWT, json.dumps(stored))
        self.assertEqual(sorted(path.name for path in self.directory.iterdir()),
                         ["response.body", "response.json"])

    def certificate(self, process):
        self.opener.open.side_effect = urllib.error.URLError(
            ssl.SSLCertVerificationError(1, "secret diagnostic " + JWT))
        self.popen.side_effect = None
        self.popen.return_value = process

    def test_exact_binary_and_duplicate_server_headers(self):
        content = b'\x00\xff\r\n{ "unknown": true }\n'
        result = self.fetch(Response(content, pairs=[("Set-Cookie", "a=1"),
                                                     ("Set-Cookie", "b=2")]))
        self.assertTrue(result["complete"])
        self.assertEqual(result["http_status"], 200)
        self.assertEqual(result["response_headers"], [("Set-Cookie", "a=1"),
                                                       ("Set-Cookie", "b=2")])
        self.assert_archive(result, content)
        request = self.opener.open.call_args.args[0]
        self.assertEqual(request.method, "POST")
        self.assertEqual(request.get_header("Authorization"), "Bearer " + JWT)

    def test_http_errors_preserve_body_and_status(self):
        for status in (301, 302, 307, 308, 400, 401, 403, 404, 429, 500, 503):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as work:
                self.directory = Path(work)
                content = b'not JSON\r\n\xff'
                self.opener.open.side_effect = urllib.error.HTTPError(
                    ENDPOINT, status, "private diagnostic", headers([("Retry-After", "12")]),
                    io.BytesIO(content))
                result = self.fetch()
                self.assertEqual(result["http_status"], status)
                self.assertEqual(result["transport_result"], "ok")
                self.assertEqual(result["retry_after_seconds"], 12)
                self.assert_archive(result, content)
                self.popen.assert_not_called()

    def test_network_failure_is_safe(self):
        self.opener.open.side_effect = urllib.error.URLError("secret " + JWT)
        result = self.fetch()
        self.assertEqual(result["transport_result"], "network_error")
        self.assertEqual(result["transport_error"], "network_error")
        self.assert_archive(result, b"")

    def test_partial_read_preserves_bytes(self):
        result = self.fetch(PartialResponse(b"abc\x00", TimeoutError("secret")))
        self.assertEqual(result["transport_result"], "partial")
        self.assertEqual(result["transport_error"], "timeout")
        self.assert_archive(result, b"abc\x00")

    def test_incomplete_read_exception_carries_bytes(self):
        response = PartialResponse(b"", http.client.IncompleteRead(b"tail", 9))
        response.first = False
        result = self.fetch(response)
        self.assertEqual(result["transport_result"], "partial")
        self.assert_archive(result, b"tail")

    def test_content_length_truncation(self):
        result = self.fetch(Response(b"short", pairs=[("Content-Length", "50")]))
        self.assertEqual(result["transport_result"], "partial")
        self.assert_archive(result, b"short")

    def test_oversized_is_bounded(self):
        result = self.fetch(Response(b"0123456789"), max_bytes=4)
        self.assertEqual(result["transport_result"], "oversized")
        self.assertFalse(result["complete"])
        self.assert_archive(result, b"0123")

    def test_exact_limit_is_complete(self):
        result = self.fetch(Response(b"1234"), max_bytes=4)
        self.assertTrue(result["complete"])
        self.assert_archive(result, b"1234")

    def test_precheck_space_propagates_before_network(self):
        with mock.patch.object(transport.shutil, "disk_usage") as usage:
            usage.return_value.free = 1
            with self.assertRaises(OSError) as caught:
                self.fetch()
        self.assertEqual(caught.exception.errno, errno.ENOSPC)
        self.opener.open.assert_not_called()
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_body_write_error_is_not_network_error(self):
        original = Path.open
        failing = mock.MagicMock()
        failing.__enter__.return_value.write.side_effect = OSError(errno.ENOSPC, "disk")

        def open_path(path, *args, **kwargs):
            if path.name == "response.body":
                return failing
            return original(path, *args, **kwargs)

        with mock.patch.object(Path, "open", open_path):
            with self.assertRaises(OSError) as caught:
                self.fetch(Response(b"body"))
        self.assertEqual(caught.exception.errno, errno.ENOSPC)
        self.assertFalse((self.directory / "response.json").exists())

    def test_atomic_metadata_failure_propagates_and_cleans_temp(self):
        with mock.patch.object(transport.os, "replace", side_effect=OSError("disk")):
            with self.assertRaises(OSError):
                self.fetch(Response(b"persisted"))
        self.assertEqual((self.directory / "response.body").read_bytes(), b"persisted")
        self.assertEqual([p.name for p in self.directory.iterdir()], ["response.body"])

    def test_refuses_to_overwrite_attempt(self):
        (self.directory / "response.body").write_bytes(b"old")
        with self.assertRaises(FileExistsError):
            self.fetch()
        self.assertEqual((self.directory / "response.body").read_bytes(), b"old")
        self.opener.open.assert_not_called()

    def test_verified_curl_credentials_only_stdin(self):
        process = FakeProcess(b"HTTP/1.1 503 Busy\r\nRetry-After: 6\r\n"
                              b"Set-Cookie: private\r\n\r\n\xffbody")
        self.certificate(process)
        result = self.fetch()
        self.assert_archive(result, b"\xffbody")
        self.assertEqual(result["http_status"], 503)
        self.assertEqual(result["retry_after_seconds"], 6)
        argv = self.popen.call_args.args[0]
        self.assertEqual(argv[:2], ["curl", "-q"])
        self.assertNotIn(JWT, repr(argv))
        self.assertNotIn(ENDPOINT, repr(argv))
        self.assertNotIn("-k", argv)
        self.assertNotIn("--insecure", argv)
        self.assertNotIn("--location", argv)
        self.assertIn(b"Authorization: Bearer " + JWT.encode(), process.input)
        self.assertEqual(self.popen.call_args.kwargs["stderr"], subprocess.DEVNULL)

    def test_curl_write_failure_propagates_and_reaps_process(self):
        process = FakeProcess(b"HTTP/2 200\r\n\r\nbody")
        self.certificate(process)
        original = Path.open
        failing = mock.MagicMock()
        failing.__enter__.return_value.write.side_effect = OSError(errno.ENOSPC, "disk")

        def open_path(path, *args, **kwargs):
            if path.name == "response.body" and args and args[0] == "wb":
                return failing
            return original(path, *args, **kwargs)

        with mock.patch.object(Path, "open", open_path):
            with self.assertRaises(OSError) as caught:
                self.fetch()
        self.assertEqual(caught.exception.errno, errno.ENOSPC)
        self.assertTrue(process.stdout.closed)
        self.assertFalse((self.directory / "response.json").exists())
        self.assertFalse(any(p.name.startswith(".curl-") for p in self.directory.iterdir()))

    def test_curl_partial_nonzero_keeps_body(self):
        self.certificate(FakeProcess(b"HTTP/2 200\r\n\r\npartial", code=18))
        result = self.fetch()
        self.assertEqual(result["transport_result"], "partial")
        self.assert_archive(result, b"partial")

    def test_curl_oversize_keeps_only_limit(self):
        self.certificate(FakeProcess(b"HTTP/2 200\r\n\r\n1234567", code=63))
        result = self.fetch(max_bytes=3)
        self.assertEqual(result["transport_result"], "oversized")
        self.assert_archive(result, b"123")

    def test_curl_wait_timeout_preserves_received_bytes(self):
        process = FakeProcess(b"HTTP/2 200\r\n\r\nreceived")
        process.wait = mock.Mock(side_effect=[subprocess.TimeoutExpired("curl", 1), 0, 0])
        self.certificate(process)
        result = self.fetch()
        self.assertEqual(result["transport_result"], "partial")
        self.assertEqual(result["transport_error"], "timeout")
        self.assertTrue(process.killed)
        self.assert_archive(result, b"received")

    def test_curl_oversize_takes_priority_over_timeout(self):
        process = FakeProcess(b"HTTP/2 200\r\n\r\n123456")
        process.wait = mock.Mock(side_effect=[subprocess.TimeoutExpired("curl", 1), 0, 0])
        self.certificate(process)
        result = self.fetch(max_bytes=3)
        self.assertEqual(result["transport_result"], "oversized")
        self.assert_archive(result, b"123")

    def test_curl_known_oversize_without_body(self):
        self.certificate(FakeProcess(b"HTTP/2 200\r\nContent-Length: 99\r\n\r\n", code=63))
        result = self.fetch(max_bytes=3)
        self.assertEqual(result["transport_result"], "oversized")
        self.assert_archive(result, b"")

    def test_curl_unavailable(self):
        self.certificate(None)
        self.popen.side_effect = FileNotFoundError("secret " + JWT)
        result = self.fetch()
        self.assertEqual(result["transport_error"], "curl_unavailable")
        self.assert_archive(result, b"")

    def test_curl_bounded_headers(self):
        process = FakeProcess(b"HTTP/2 200\r\nX: " + b"x" * (transport._HEADER_LIMIT + 10))
        self.certificate(process)
        result = self.fetch()
        self.assertFalse(result["complete"])
        self.assertTrue(process.killed)
        self.assert_archive(result, b"")

    def test_curl_interim_headers(self):
        self.certificate(FakeProcess(b"HTTP/1.1 100 Continue\r\nX: ignored\r\n\r\n"
                                      b"HTTP/2 201\r\nX: kept\r\n\r\ndata"))
        result = self.fetch()
        self.assertEqual(result["http_status"], 201)
        self.assertEqual(result["response_headers"], [("X", "kept")])
        self.assert_archive(result, b"data")

    def test_noncertificate_tls_does_not_fallback(self):
        self.opener.open.side_effect = urllib.error.URLError(ssl.SSLError("secret"))
        result = self.fetch()
        self.assertEqual(result["transport_error"], "tls_error")
        self.popen.assert_not_called()

    def test_redirect_handler_rejects_all_destinations(self):
        handler = transport._NoRedirect()
        for target in (ENDPOINT, "https://other.invalid/private"):
            self.assertIsNone(handler.redirect_request(None, None, 302, "", {}, target))

    def test_retry_after_date_integer_invalid_and_past(self):
        now = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
        for value, expected in (("120", 120), ("Thu, 01 Jan 2026 00:01:00 GMT", 60),
                                ("Wed, 31 Dec 2025 23:59:00 GMT", 0),
                                ("-1", None), ("bad", None), ("1.5", None)):
            with self.subTest(value=value):
                self.assertEqual(transport._retry_after([("Retry-After", value)], now), expected)

    def test_invalid_input_never_networks(self):
        for endpoint in ("http://example.invalid", "https://user:password@example.invalid",
                         "https://example.invalid/#secret", "https://example.invalid/\n"):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                transport.fetch(endpoint, JWT, {}, self.directory)
        with self.assertRaises(ValueError):
            transport.fetch(ENDPOINT, "token\r\nInjected: yes", {}, self.directory)
        self.opener.open.assert_not_called()


if __name__ == "__main__":
    unittest.main()
