"""Offline collector fixtures; run this file with python -I."""
import base64
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("pull_replays", ROOT / "pull_replays.py")
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)
API = p.module("test_upstream_api", ROOT / "extractor" / "api.py")
IDS = ["00000000-0000-0000-0000-%012d" % i for i in range(1, 8)]
LINKS = ["https://share.polytopia.io/g/" + value for value in IDS]


def game(state=4, version=999):
    blob = base64.b64encode(struct.pack("<ii", version, version) + b"snapshot").decode()
    return {"success": True, "errorCode": 1, "data": {"state": state,
            "currentGameStateData": blob, "initialGameStateData": blob, "unknown": {"retain": True}}}


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.csv = self.root / "queue.csv"
        self.pacer = SimpleNamespace(wait=lambda: None, backoff=lambda seconds: None)

    def classify(self, doc=None, http=200, **changes):
        raw = json.dumps(doc).encode() if not isinstance(doc, bytes) else doc
        (self.root / "response.body").write_bytes(raw)
        meta = dict(http_status=http, complete=True, transport_result="ok", body_file="response.body")
        meta.update(changes)
        return p.classify(meta, self.root, API)

    def test_har_plain_base64_escaped_order_dedup(self):
        har = self.root / "test.har"
        har.write_text(json.dumps({"entries": [LINKS[0], LINKS[1].replace("/", "\\/"),
            {"encoding": "base64", "text": base64.b64encode((LINKS[0] + " " + LINKS[2]).encode()).decode()},
            "https://evil.example/" + IDS[3], "https://share.polytopia.io/g/" + "z" * 36]}))
        self.assertEqual(list(dict.fromkeys(p.har_links(har, API.parse_game_id))), LINKS[:3])

    def test_queue_legacy_merge_all_statuses(self):
        self.csv.write_text("status,link\nt," + LINKS[0] + "\nf," + LINKS[1] + "\nseen," + LINKS[2] + "\nunseen," + LINKS[3])
        rows = p.read_queue(self.csv)
        self.assertEqual(list(rows.values()), ["saved_ended", "unseen", "saved_ended", "unseen"])
        rows = {"https://share.polytopia.io/g/00000000-0000-0000-0001-%012d" % i: status
                for i, status in enumerate(sorted(p.STATUSES))}
        p.write_queue(self.csv, rows)
        self.assertEqual(p.read_queue(self.csv), rows)

    def test_unknown_version_unfinished_missing_mismatch(self):
        self.assertEqual(self.classify(game())[0], "saved_ended")
        self.assertEqual(self.classify(game(3))[0], "saved_unfinished")
        doc = game()
        doc["data"].pop("currentGameStateData")
        self.assertEqual(self.classify(doc)[0], "saved_no_snapshot")
        doc["data"]["currentGameStateData"] = "???"
        self.assertEqual(self.classify(doc)[0], "saved_no_snapshot")
        doc["data"]["currentGameStateData"] = base64.b64encode(struct.pack("<ii", 122, 123)).decode()
        result = self.classify(doc)
        self.assertEqual(result[0], "saved_no_snapshot")
        self.assertEqual(result[2]["snapshots"]["current"]["payload_version"], 123)

    def test_http_and_api_statuses_no_bypass(self):
        for http, status in [(401, "retry_auth"), (403, "access_denied"), (429, "retry_rate_limited"),
                             (500, "retry_http"), (503, "retry_http"), (404, "api_error")]:
            with self.subTest(http=http):
                actual, fallback, _ = self.classify({}, http=http)
                self.assertEqual(actual, status)
                self.assertFalse(fallback)
        for code, status in [(1004, "retry_auth"), ("Forbidden", "access_denied"),
                             (429, "retry_rate_limited"), (500, "retry_http"), (9999, "api_error")]:
            actual, fallback, _ = self.classify({"success": False, "errorCode": code})
            self.assertEqual(actual, status)
            self.assertFalse(fallback)
        self.assertEqual(self.classify({"success": False, "errorCode": 1005})[:2], ("not_found", True))

    def test_malformed_partial_network(self):
        self.assertEqual(self.classify(b"<html>challenge</html>")[0], "retry_invalid_response")
        self.assertEqual(self.classify(game(), complete=False, transport_result="partial")[0], "retry_invalid_response")
        self.assertEqual(self.classify(None, http=None, complete=False, transport_result="network_error")[0], "retry_network")
        self.assertEqual(self.classify({"errorCode": []})[0], "retry_invalid_response")

    def fake_fetch(self, responses):
        calls = []
        def fetch(endpoint, jwt, body, directory):
            calls.append(endpoint)
            raw = json.dumps(responses[len(calls) - 1]).encode()
            (directory / "response.body").write_bytes(raw)
            return dict(endpoint=endpoint, body_file="response.body", http_status=200,
                        complete=True, transport_result="ok", retry_after_seconds=None)
        return fetch, calls

    def test_fallback_preserves_both_exact_bodies(self):
        rows = {LINKS[0]: "processing", LINKS[1]: "saved_unfinished"}
        responses = [{"success": False, "errorCode": 1005}, game()]
        fetch, calls = self.fake_fetch(responses)
        with contextlib.redirect_stdout(io.StringIO()):
            summary = p.run_batch(rows, self.csv, self.root / "data", 10, p.DEFAULT, "private", fetch, self.pacer, API)
        self.assertEqual(len(calls), 2)
        self.assertEqual(summary["processed"], 1)
        self.assertEqual(rows[LINKS[0]], "saved_ended")
        bodies = list((self.root / "data").rglob("response.body"))
        self.assertEqual(len(bodies), 2)
        self.assertEqual({b.read_bytes() for b in bodies}, {json.dumps(r).encode() for r in responses})

    def test_auth_stops_no_fallback(self):
        rows = {link: "unseen" for link in LINKS[:2]}
        fetch, calls = self.fake_fetch([{"success": False, "errorCode": 1004}])
        with contextlib.redirect_stdout(io.StringIO()):
            result = p.run_batch(rows, self.csv, self.root / "data", 10, p.DEFAULT, "private", fetch, self.pacer, API)
        self.assertEqual(result["stop_reason"], "retry_auth")
        self.assertEqual(len(calls), 1)
        self.assertEqual(rows[LINKS[1]], "unseen")

    def test_disk_failure_keeps_processing_and_stops(self):
        rows = {LINKS[0]: "unseen"}
        def fail(*args):
            raise OSError("disk fixture")
        with self.assertRaises(OSError):
            p.run_batch(rows, self.csv, self.root / "data", 1, p.DEFAULT, "private", fail, self.pacer, API)
        self.assertEqual(p.read_queue(self.csv)[LINKS[0]], "processing")

    def test_rate_limit_retry_after_persisted_and_single_attempt(self):
        rows = {LINKS[0]: "unseen", LINKS[1]: "retry_network"}
        waits = []
        pacer = SimpleNamespace(wait=lambda: None, backoff=waits.append)
        fetch, calls = self.fake_fetch([{"errorCode": 429}])
        with contextlib.redirect_stdout(io.StringIO()):
            result = p.run_batch(rows, self.csv, self.root / "data", 10, p.DEFAULT, "private", fetch, pacer, API)
        self.assertEqual(result["stop_reason"], "retry_rate_limited")
        self.assertEqual(waits, [60])
        self.assertEqual(len(calls), 1)

    def test_pacing_deadline_survives_restart(self):
        path = self.root / "pacing.json"
        clock = [1000.0]
        def sleep(seconds):
            clock[0] += seconds
        pacer = p.Pacer(3.6, path, lambda: clock[0], sleep)
        pacer.backoff(120)
        restarted = p.Pacer(3.6, path, lambda: clock[0], sleep)
        restarted.wait()
        self.assertEqual(clock[0], 1120)

    def test_lock_excludes_concurrent_writer(self):
        with p.QueueLock(self.csv):
            with self.assertRaises(RuntimeError):
                with p.QueueLock(self.csv):
                    pass

    def test_atomic_retries_transient_windows_permission_error(self):
        replace = p.os.replace
        with patch.object(p.os, "replace", side_effect=[PermissionError("sharing fixture"), None]) as mocked:
            with patch.object(p.time, "sleep"):
                p.atomic(self.root / "retry.txt", "fixture")
        self.assertEqual(mocked.call_count, 2)

    def test_atomic_failure_preserves_previous_queue(self):
        p.write_queue(self.csv, {LINKS[0]: "unseen"})
        before = self.csv.read_bytes()
        with patch.object(p.os, "replace", side_effect=OSError("fixture")):
            with self.assertRaises(OSError):
                p.write_queue(self.csv, {LINKS[0]: "saved_ended"})
        self.assertEqual(self.csv.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
