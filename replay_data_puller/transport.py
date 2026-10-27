"""Private, bounded response capture. Pacing and API fallback belong to the caller."""

import contextlib
import datetime as dt
import email.parser
import email.utils
import errno
import http.client
import json
import math
import os
from pathlib import Path
import shutil
import socket
import ssl
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

_CHUNK = 64 * 1024
_HEADER_LIMIT = 64 * 1024
_DISK_MARGIN = 1024 * 1024


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _make_opener():
    return urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=ssl.create_default_context()),
        _NoRedirect(),
    )


def _utcnow():
    return dt.datetime.now(dt.timezone.utc)


def _category(error):
    if isinstance(error, urllib.error.URLError):
        return _category(error.reason)
    if isinstance(error, ssl.SSLCertVerificationError):
        return "tls_certificate"
    if isinstance(error, (TimeoutError, socket.timeout)):
        return "timeout"
    if isinstance(error, http.client.IncompleteRead):
        return "incomplete_read"
    if isinstance(error, ssl.SSLError):
        return "tls_error"
    return "network_error"


def _retry_after(headers, now):
    for key, value in headers:
        if key.lower() != "retry-after":
            continue
        value = value.strip()
        if value.isascii() and value.isdigit():
            try:
                return int(value)
            except ValueError:
                return None
        try:
            date = email.utils.parsedate_to_datetime(value)
            if date.tzinfo is None:
                date = date.replace(tzinfo=dt.timezone.utc)
            return max(0, math.ceil((date - now).total_seconds()))
        except (ValueError, TypeError, OverflowError):
            return None
    return None


def _set_failure(metadata, category):
    metadata["complete"] = False
    metadata["transport_result"] = (
        "partial" if metadata["body_bytes"] else "network_error"
    )
    metadata["transport_error"] = category


def _capture(reader, output, metadata, max_bytes, deadline):
    """Only reader operations are caught: persistence errors must escape."""
    while True:
        failed = None
        try:
            if time.monotonic() >= deadline:
                raise TimeoutError()
            # urllib exposes its socket through HTTPResponse.fp; cap each read
            # by the remaining whole-response deadline, not another full timeout.
            raw = getattr(getattr(reader, "fp", None), "raw", None)
            connection = getattr(raw, "_sock", None)
            if isinstance(connection, socket.socket):
                connection.settimeout(max(0.001, deadline - time.monotonic()))
            # read1 avoids repeatedly filling a large buffer on a trickling peer.
            read = getattr(reader, "read1", reader.read)
            chunk = read(min(_CHUNK, max_bytes - metadata["body_bytes"] + 1))
        except http.client.IncompleteRead as error:
            chunk, failed = error.partial, _category(error)
        except (OSError, http.client.HTTPException, urllib.error.URLError) as error:
            chunk, failed = b"", _category(error)
        remaining = max_bytes - metadata["body_bytes"]
        if chunk:
            saved = chunk[:remaining]
            output.write(saved)
            metadata["body_bytes"] += len(saved)
        if len(chunk) > remaining:
            metadata.update(complete=False, transport_result="oversized",
                            transport_error="oversized")
            return
        if failed:
            _set_failure(metadata, failed)
            return
        if not chunk:
            metadata.update(complete=True, transport_result="ok", transport_error=None)
            return


def _check_length(metadata):
    if not metadata["complete"]:
        return
    # Transfer-Encoding takes precedence over Content-Length.
    headers = metadata["response_headers"]
    if any(key.lower() == "transfer-encoding" for key, _ in headers):
        return
    for key, value in headers:
        if key.lower() == "content-length":
            try:
                expected = int(value)
            except ValueError:
                return
            if expected != metadata["body_bytes"]:
                _set_failure(metadata, "incomplete_read")
            return


def _config_quote(value):
    # curl's config grammar supports these escapes inside double quotes.
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace(
        "\r", "\\r").replace("\n", "\\n").replace("\t", "\\t") + '"'


def _curl_headers(stream):
    """Read bounded header blocks, discarding interim informational responses."""
    total = 0
    while True:
        lines = []
        while True:
            line = stream.readline(_HEADER_LIMIT - total + 1)
            total += len(line)
            if total > _HEADER_LIMIT:
                raise ValueError("header_limit")
            if not line:
                raise http.client.IncompleteRead(b"")
            lines.append(line)
            if line in (b"\r\n", b"\n"):
                break
        status_parts = lines[0].split()
        if len(status_parts) < 2 or not status_parts[0].startswith(b"HTTP/"):
            raise ValueError("invalid_headers")
        status = int(status_parts[1])
        if not 100 <= status <= 599:
            raise ValueError("invalid_headers")
        if 100 <= status < 200 and status != 101:
            continue
        headers = email.parser.BytesParser().parsebytes(b"".join(lines[1:]))
        return status, list(headers.raw_items())


def _curl(endpoint, jwt, payload, directory, output_path, metadata, timeout, max_bytes):
    # No shell, curlrc, verbose output, redirects, request credentials in argv,
    # or unbounded communicate() buffers. stderr is deliberately discarded.
    config = ("url = " + _config_quote(endpoint) + "\n"
              "request = \"POST\"\n"
              "header = " + _config_quote("Authorization: Bearer " + jwt) + "\n"
              "header = \"Content-Type: application/json\"\n"
              "data-binary = " + _config_quote(payload.decode("utf-8")) + "\n")
    argv = ["curl", "-q", "--config", "-", "--silent", "--include",
            "--suppress-connect-headers", "--proto", "=https",
            "--proto-redir", "=https", "--max-redirs", "0",
            "--max-time", str(timeout), "--connect-timeout", str(timeout),
            "--max-filesize", str(max_bytes), "--output", "-"]
    with tempfile.TemporaryDirectory(prefix=".curl-", dir=directory) as work:
        # Write straight to the authoritative file: even a local flush/write
        # failure must not delete bytes already received during temporary cleanup.
        with output_path.open("wb") as output:
            try:
                process = subprocess.Popen(
                    argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL, cwd=work,
                )
            except OSError:
                _set_failure(metadata, "curl_unavailable")
            else:
                expired = threading.Event()

                def expire():
                    expired.set()
                    try:
                        process.kill()
                    except OSError:
                        pass

                deadline = time.monotonic() + timeout
                timer = threading.Timer(timeout, expire)
                timer.daemon = True
                timer.start()
                try:
                    try:
                        process.stdin.write(config.encode("utf-8"))
                        process.stdin.close()
                        status, headers = _curl_headers(process.stdout)
                    except (OSError, ValueError, http.client.HTTPException):
                        _set_failure(metadata, "curl_headers")
                    else:
                        metadata["http_status"] = status
                        metadata["response_headers"] = headers
                        _capture(process.stdout, output, metadata, max_bytes, deadline)
                    if not metadata["complete"]:
                        with contextlib.suppress(OSError):
                            process.kill()
                    try:
                        code = process.wait(timeout=max(0.001, deadline - time.monotonic()))
                    except subprocess.TimeoutExpired:
                        expire()
                        code = process.wait()
                    if code == 63 or metadata["transport_result"] == "oversized":
                        metadata.update(complete=False, transport_result="oversized",
                                        transport_error="oversized")
                    elif expired.is_set():
                        _set_failure(metadata, "timeout")
                    elif code:
                        _set_failure(metadata, "curl_error")
                    _check_length(metadata)
                finally:
                    timer.cancel()
                    # Always reap, including when output.write or flush fails.
                    if process.poll() is None:
                        with contextlib.suppress(OSError):
                            process.kill()
                    process.wait()
                    timer.join()
                    with contextlib.suppress(OSError):
                        process.stdin.close()
                    process.stdout.close()


def _persist(directory, metadata):
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                                         dir=directory, prefix=".response-",
                                         suffix=".tmp", delete=False) as output:
            name = output.name
            json.dump(metadata, output, ensure_ascii=True, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(name, directory / "response.json")
    finally:
        if name is not None:
            try:
                os.unlink(name)
            except FileNotFoundError:
                pass


def fetch(endpoint: str, jwt: str, body: dict, directory: Path, *,
          timeout=60, max_bytes=64 * 1024 * 1024) -> dict:
    """Archive one POST, including HTTP errors. Never retry API endpoints here.

    Directory must already exist and belong exclusively to this call. Tests can
    patch _make_opener and subprocess.Popen without performing live requests.
    Local validation/persistence failures propagate; transport failures are data.
    """
    parsed = urllib.parse.urlsplit(endpoint)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or parsed.fragment
            or any(ord(char) < 32 or ord(char) == 127 for char in endpoint)):
        raise ValueError("endpoint must be an HTTPS URL without userinfo or fragment")
    if not isinstance(jwt, str) or any(ord(char) < 32 or ord(char) == 127 for char in jwt):
        raise ValueError("invalid authorization value")
    if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes < 1:
        raise ValueError("max_bytes must be a positive integer")
    if not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be positive and finite")
    directory = Path(directory)
    if shutil.disk_usage(directory).free < 2 * max_bytes + _DISK_MARGIN:
        raise OSError(errno.ENOSPC, "insufficient archive space")
    if (directory / "response.json").exists():
        raise FileExistsError("attempt metadata already exists")
    payload = json.dumps(body, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    metadata = dict(endpoint=endpoint, started_at=_utcnow().isoformat(),
                    finished_at=None, http_status=None, response_headers=[],
                    body_file="response.body", body_bytes=0, complete=False,
                    transport_result="network_error", transport_error=None,
                    retry_after_seconds=None)
    request = urllib.request.Request(endpoint, data=payload, method="POST", headers={
        "Authorization": "Bearer " + jwt, "Content-Type": "application/json",
    })
    certificate_failure = False
    deadline = time.monotonic() + timeout
    with (directory / "response.body").open("xb") as output:
        response = None
        try:
            response = _make_opener().open(request, timeout=timeout)
        except urllib.error.HTTPError as error:
            response = error
        except (OSError, urllib.error.URLError, http.client.HTTPException) as error:
            category = _category(error)
            certificate_failure = category == "tls_certificate"
            _set_failure(metadata, category)
        if response is not None:
            try:
                metadata["http_status"] = response.code
                metadata["response_headers"] = list(response.headers.raw_items())
                _capture(response, output, metadata, max_bytes, deadline)
                _check_length(metadata)
            finally:
                response.close()
    if certificate_failure:
        _curl(endpoint, jwt, payload, directory, directory / "response.body",
              metadata, timeout, max_bytes)
    metadata["finished_at"] = _utcnow().isoformat()
    metadata["retry_after_seconds"] = _retry_after(metadata["response_headers"], _utcnow())
    _persist(directory, metadata)
    return metadata
