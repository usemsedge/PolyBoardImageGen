"""Local, resumable raw-response replay collector. Run with python -I."""
from __future__ import annotations
import argparse
import base64
from collections import Counter
import csv
from datetime import datetime, timezone
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import random
import re
import struct
import sys
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parent
STATUSES = set("unseen processing saved_ended saved_unfinished saved_no_snapshot not_found access_denied api_error retry_network retry_http retry_rate_limited retry_auth retry_invalid_response error".split())
DEFAULT = {"unseen", "processing"} | {s for s in STATUSES if s.startswith("retry_")}
LINK = re.compile(r"https?://share\.polytopia\.io/g/([0-9a-f-]{36})(?![0-9a-f-])", re.I)


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    sys.modules[name] = result
    spec.loader.exec_module(result)
    return result


def now():
    return datetime.now(timezone.utc).isoformat()


def atomic(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        # Windows scanners/readers can briefly prevent replacing a closed file.
        # Retry only local persistence; never repeat networking here.
        for retry in range(6):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if retry == 5:
                    raise
                time.sleep(0.1 * 2 ** retry)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def save_json(path, value):
    atomic(path, json.dumps(value, indent=2, ensure_ascii=True) + "\n")


class QueueLock:
    def __init__(self, path):
        self.path = Path(str(path) + ".lock")

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+b")
        self.handle.seek(0, 2)
        if self.handle.tell() == 0:
            self.handle.write(b"0")
            self.handle.flush()
        self.handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.handle.close()
            raise RuntimeError("Another collector holds the queue lock") from None
        return self

    def __exit__(self, *exc):
        self.handle.close()


def canonical(link, parse=uuid.UUID):
    match = LINK.search(link.replace("\\/", "/"))
    if not match:
        raise ValueError("Invalid replay link")
    return "https://share.polytopia.io/g/" + str(parse(match.group(1)))


def read_queue(path):
    rows = {}
    if not path.exists():
        return rows
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != ["status", "link"]:
            raise ValueError("Expected exactly status,link columns")
        for row in reader:
            status = row["status"].strip().lower()
            status = {"t": "saved_ended", "seen": "saved_ended", "f": "unseen"}.get(status, status)
            if status not in STATUSES:
                raise ValueError("Unknown queue status")
            link = canonical(row["link"])
            if link not in rows or rows[link] == "unseen":
                rows[link] = status
    return rows


def write_queue(path, rows):
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["status", "link"])
    writer.writerows((status, link) for link, status in rows.items())
    atomic(path, output.getvalue())


def har_links(path, parse=uuid.UUID):
    with path.open(encoding="utf-8-sig") as handle:
        stack = [json.load(handle)]
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            values = list(value.values())
            if value.get("encoding") == "base64" and isinstance(value.get("text"), str):
                try:
                    values.append(base64.b64decode(value["text"], validate=True).decode("utf-8", "replace"))
                except ValueError:
                    pass
            stack.extend(reversed(values))
        elif isinstance(value, list):
            stack.extend(reversed(value))
        elif isinstance(value, str):
            text = value.replace("\\/", "/").replace("\\u002f", "/").replace("\\u002F", "/")
            for match in LINK.finditer(text):
                try:
                    yield canonical(match.group(), parse)
                except ValueError:
                    pass


def field(obj, name, default=None):
    if isinstance(obj, dict):
        return next((v for k, v in obj.items() if k.lower() == name.lower()), default)
    return default


def snapshot(data, which, api=None):
    key = "initialGameStateData" if which == "start" else "currentGameStateData"
    value = field(data, key)
    if not isinstance(value, str) or not value:
        return {"present": False}
    try:
        blob = base64.b64decode(value, validate=True)
        if api:
            blob = api.game_state_bytes({key: value}, which=which)
    except (ValueError, KeyError):
        return {"present": True, "issue": "invalid_base64"}
    result = {"present": True, "bytes": len(blob)}
    if len(blob) < 8:
        return dict(result, issue="truncated_header")
    outer, inner = struct.unpack_from("<ii", blob)
    result.update(wrapper_version=outer, payload_version=inner)
    if outer != inner:
        result["issue"] = "version_mismatch"
    return result


def classify(meta, directory, api=None):
    http = meta.get("http_status")
    for codes, status in [({429}, "retry_rate_limited"), ({401}, "retry_auth"),
                          ({403, 407, 451}, "access_denied"), ({408, 425}, "retry_http")]:
        if http in codes:
            return status, False, {}
    if http is not None and 500 <= http < 600:
        return "retry_http", False, {}
    if meta.get("transport_result") == "network_error":
        return "retry_network", False, {}
    if not meta.get("complete"):
        return "retry_invalid_response", False, {}
    try:
        doc = json.loads((directory / meta["body_file"]).read_bytes())
    except (ValueError, UnicodeError, KeyError):
        return "retry_invalid_response", False, {}
    if not isinstance(doc, dict):
        return "retry_invalid_response", False, {}
    code = field(doc, "errorCode")
    details = {"api_error_code": code}
    if not isinstance(code, (str, int, type(None))):
        return "retry_invalid_response", False, {}
    if code in (1002, 1003, 1004, "LoginFailed", "Unauthorized", "AuthenticationFailed"):
        return "retry_auth", False, details
    if code in ("AccessDenied", "Forbidden", "ChallengeRequired"):
        return "access_denied", False, details
    if code in (429, "TooManyRequests", "RateLimited"):
        return "retry_rate_limited", False, details
    if code in (404, 500, 1001, "ConnectionError", "InternalServerError", "SubmitFailedBusy"):
        return "retry_http", False, details
    if code in (1005, "GameNotFound"):
        return "not_found", True, details
    if http is None or not 200 <= http < 300:
        return "api_error", False, details
    if code not in (0, 1, None, "None", "Success") or field(doc, "success") is False:
        eligible = code in (1011, 1012, 1023, 1024, 1026, 1028, 1030,
                            "NoGameStateData", "UnsupportedOpenVersion", "ReplayGameStillOngoing")
        return "api_error", eligible, details
    data = field(doc, "data")
    if not isinstance(data, dict):
        return "retry_invalid_response", False, details
    state = field(data, "state")
    details.update(game_state=state, snapshots={"initial": snapshot(data, "start", api),
                                              "current": snapshot(data, "end", api)})
    current = details["snapshots"]["current"]
    if not current["present"] or "issue" in current:
        return "saved_no_snapshot", False, details
    return ("saved_ended" if state in (4, "Ended", "ended") else "saved_unfinished"), False, details


class Pacer:
    def __init__(self, delay, path, clock=time.time, sleep=time.sleep):
        self.delay, self.path, self.clock, self.sleep = delay, path, clock, sleep
        self.next_at, self.requests = 0, 0
        if path.exists():
            self.next_at = float(json.loads(path.read_text(encoding="utf-8")).get("next_request_at", 0))
        if not math.isfinite(self.next_at):
            raise ValueError("Invalid saved pacing deadline")

    def wait(self):
        self.sleep(max(0, self.next_at - self.clock()))
        self.requests += 1
        gap = self.delay * random.uniform(1, 1.15)
        if self.requests % 50 == 0:
            gap += min(300, random.lognormvariate(math.log(30), 0.4))
        self.next_at = self.clock() + gap
        save_json(self.path, {"next_request_at": self.next_at})

    def backoff(self, seconds):
        self.next_at = max(self.next_at, self.clock() + seconds)
        save_json(self.path, {"next_request_at": self.next_at})


def run_batch(rows, csv_path, output, limit, selected, jwt, fetch, pacer, api):
    candidates = [link for link, status in rows.items() if status in selected][:limit]
    counts, versions = Counter(), Counter()
    failures, stop = 0, None
    for link in candidates:
        game_id = link.rsplit("/", 1)[1]
        attempt = output / game_id / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ") + "-" + uuid.uuid4().hex[:8])
        attempt.mkdir(parents=True, exist_ok=False)
        record = {"game_id": game_id, "started_at": now(), "status": "processing", "responses": []}
        save_json(attempt / "attempt.json", record)
        rows[link] = "processing"
        write_queue(csv_path, rows)
        try:
            for index, endpoint in enumerate((api.GET_GAME_VIEW_MODEL, api.SPECTATE_GAME)):
                directory = attempt / ("primary" if index == 0 else "fallback")
                directory.mkdir()
                pacer.wait()
                meta = fetch(endpoint, jwt, {"GameId": game_id}, directory)
                status, fallback, details = classify(meta, directory, api)
                meta.update(details)
                save_json(directory / "response.json", meta)
                record["responses"].append({"directory": directory.name, "status": status})
                save_json(attempt / "attempt.json", record)
                for snap in details.get("snapshots", {}).values():
                    if "wrapper_version" in snap:
                        versions[str(snap["wrapper_version"])] += 1
                if not fallback or index == 1:
                    break
            record.update(status=status, finished_at=now())
            save_json(attempt / "attempt.json", record)
            rows[link] = status
            write_queue(csv_path, rows)
        except OSError:
            raise  # Leave durable processing state; stop on persistence failure.
        except Exception as exc:
            record.update(status="error", finished_at=now(), local_error=type(exc).__name__)
            save_json(attempt / "attempt.json", record)
            rows[link] = "error"
            write_queue(csv_path, rows)
            counts["error"] += 1
            stop = "local_error"
            break
        counts[status] += 1
        print(f"Processed {sum(counts.values())}/{len(candidates)}: {status}", flush=True)
        transient = status in {"retry_network", "retry_http"}
        failures = failures + 1 if transient else 0
        retry_after = meta.get("retry_after_seconds") or 0
        if retry_after or transient or status == "retry_rate_limited":
            pacer.backoff(max(retry_after, 60 if status == "retry_rate_limited" else 10 * 2 ** min(failures, 6)))
        if status in {"retry_auth", "retry_rate_limited", "access_denied", "retry_invalid_response"}:
            stop = status
            break
        if failures >= 3:
            stop = "repeated_transient_failures"
            break
    return {"processed": sum(counts.values()), "attempt_statuses": dict(counts),
            "observed_wrapper_versions": dict(versions), "stop_reason": stop}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--har", type=Path, action="append")
    parser.add_argument("--csv", type=Path, default=ROOT / "replays.csv")
    parser.add_argument("--output", type=Path, default=ROOT / "data")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--delay", type=float, default=3.6)
    parser.add_argument("--import-only", action="store_true")
    parser.add_argument("--retry-status", action="append", choices=sorted(STATUSES), default=[])
    args = parser.parse_args(argv)
    if args.limit < 0 or not math.isfinite(args.delay) or args.delay < 3.6:
        parser.error("--limit must be nonnegative and --delay at least 3.6")
    started = time.monotonic()
    try:
        with QueueLock(args.csv):
            api = module("collector_upstream_api", ROOT / "extractor" / "api.py")
            rows = read_queue(args.csv)
            original = len(rows)
            hars = args.har if args.har is not None else [Path.home() / "Downloads" / "10_27_26_all_polychamps_replays.har"]
            for path in hars:
                for link in har_links(path, api.parse_game_id):
                    rows.setdefault(link, "unseen")
            write_queue(args.csv, rows)
            summary = {"unique_links": len(rows), "new_links": len(rows) - original}
            print(json.dumps(summary), flush=True)
            if not args.import_only:
                transport = module("collector_transport", ROOT / "transport.py")
                try:
                    jwt = api.load_jwt()
                except (FileNotFoundError, UnicodeError):
                    jwt = None
                if not jwt:
                    summary.update(processed=0, stop_reason="retry_auth")
                    print("Authentication unavailable; sign in normally in Polytopia. No requests sent.")
                else:
                    args.output.mkdir(parents=True, exist_ok=True)
                    pacer = Pacer(args.delay, args.csv.with_suffix(".pacing.json"))
                    summary.update(run_batch(rows, args.csv, args.output, args.limit,
                                             DEFAULT | set(args.retry_status), jwt, transport.fetch, pacer, api))
            summary.update(statuses=dict(Counter(rows.values())), remaining=sum(s in DEFAULT for s in rows.values()),
                           elapsed_seconds=round(time.monotonic() - started, 2),
                           csv=str(args.csv.resolve()), output=str(args.output.resolve()))
            save_json(args.csv.with_suffix(".summary.json"), summary)
            print(json.dumps(summary, indent=2))
            return 0 if not summary.get("stop_reason") else 2
    except KeyboardInterrupt:
        print("Interrupted; processing entries recover on the next invocation.", file=sys.stderr)
        return 130
    except Exception as exc:
        print("Stopped safely: " + type(exc).__name__ + ". Progress preserved.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
