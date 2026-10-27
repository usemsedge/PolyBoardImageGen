"""Share-link fetch: local jwtToken + polytopia-prod GameState blobs."""
from __future__ import annotations

import base64
import json
import os
import re
import ssl
import sys
import traceback
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional
from uuid import UUID

# Unity persistentDataPath: macOS Application Support, Windows LocalLow, Linux unity3d.
DIR_GLOBS = (
    "com.midjiwan.polytopia*",
    "*polytopia*",
    "*Polytopia*",
    "*midjiwan*",
    "*Midjiwan*",
)


def _data_roots() -> list[Path]:
    home = Path.home()
    roots: list[Path] = []
    if sys.platform == "darwin":
        roots.append(home / "Library" / "Application Support")
    elif sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        roots.extend(
            [
                home / "AppData" / "LocalLow",
                Path(local) if local else home / "AppData" / "Local",
                home / "AppData" / "Roaming",
            ]
        )
    else:
        xdg = os.environ.get("XDG_CONFIG_HOME")
        roots.append(Path(xdg) / "unity3d" if xdg else home / ".config" / "unity3d")
        roots.append(home / ".local" / "share")
    # Always try the common Unity folders so mixed/WSL layouts still work.
    roots.extend(
        [
            home / "Library" / "Application Support",
            home / "AppData" / "LocalLow",
            home / ".config" / "unity3d",
        ]
    )
    out: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        try:
            resolved = root.resolve()
        except OSError:
            continue
        if resolved in seen or not resolved.is_dir():
            continue
        seen.add(resolved)
        out.append(resolved)
    return out


def find_jwt_files() -> list[Path]:
    found: list[Path] = []
    seen: set[Path] = set()
    for base in _data_roots():
        for pattern in DIR_GLOBS:
            for root in base.glob(pattern):
                if not root.is_dir():
                    continue
                for path in root.rglob("jwtToken"):
                    if not path.is_file():
                        continue
                    resolved = path.resolve()
                    if resolved in seen:
                        continue
                    seen.add(resolved)
                    found.append(path)
    return found


def newest_jwt() -> Path | None:
    files = find_jwt_files()
    if not files:
        return None
    return max(files, key=lambda p: p.stat().st_mtime)


def load_jwt() -> str:
    """Return the newest jwtToken file contents (stripped). Raises FileNotFoundError."""
    path = newest_jwt()
    if path is None:
        raise FileNotFoundError(
            "No jwtToken file found. Log into Polytopia, then look for a file "
            "named jwtToken (macOS: ~/Library/Application Support; "
            "Windows: %USERPROFILE%\\AppData\\LocalLow\\Midjiwan)."
        )
    token = path.read_text(encoding="utf-8").strip()
    if not token:
        raise FileNotFoundError(f"Empty jwtToken file: {path}")
    return token


BACKEND = "https://polytopia-prod.net"
GET_GAME_VIEW_MODEL = f"{BACKEND}/api/game/get_game_view_model"
SPECTATE_GAME = f"{BACKEND}/api/game/spectate_game"

# GameSessionState.Ended (dump / summary responses).
STATE_ENDED = 4

# Ended snapshots are reused; in-progress (state 3) always refetches.
CACHE_DIR = Path(__file__).resolve().parent / ".share_cache"


def cache_path(game_id: UUID) -> Path:
    return CACHE_DIR / f"{game_id}.json"


def read_cached_game_data(game_id: UUID) -> Optional[dict[str, Any]]:
    path = cache_path(game_id)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or not data.get("current_game_state_data"):
        return None
    return data


def write_cached_game_data(game_id: UUID, out: dict[str, Any]) -> None:
    """Keep an Ended snapshot; replace in-progress cache with the latest fetch."""
    path = cache_path(game_id)
    payload = {k: v for k, v in out.items() if not str(k).startswith("_")}
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            existing = None
        if isinstance(existing, dict) and existing.get("state") == STATE_ENDED:
            if existing.get("initial_game_state_data"):
                return
            initial = payload.get("initial_game_state_data")
            if initial:
                existing["initial_game_state_data"] = initial
                payload = existing
            else:
                return
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    tmp.replace(path)


_SHARE_RE = re.compile(
    r"(?:share\.polytopia\.io/g/|opengame\?id=)?([0-9a-fA-F]{8}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"
)


def parse_game_id(link_or_id: str) -> UUID:
    text = link_or_id.strip()
    try:
        return UUID(text)
    except ValueError:
        pass
    m = _SHARE_RE.search(text)
    if not m:
        raise ValueError(f"Could not parse game id from: {link_or_id!r}")
    return UUID(m.group(1))


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _print_fetch_error(where: str, err: BaseException, extra: str = "") -> None:
    print(f"[get_game_data] {where}: {err}", file=sys.stderr)
    if extra:
        print(extra, file=sys.stderr)
    traceback.print_exception(type(err), err, err.__traceback__)


def api_post(path: str, jwt: str, body: dict[str, Any]) -> dict[str, Any]:
    req = urllib.request.Request(
        path,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {jwt}",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, context=_ssl_context(), timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace") if e.fp is not None else ""
        _print_fetch_error(
            f"HTTP {e.code} {path}",
            e,
            extra=raw or e.reason,
        )
        raise
    except urllib.error.URLError as e:
        # macOS Python often lacks certs; fall back to curl which uses system trust.
        if "CERTIFICATE_VERIFY_FAILED" not in str(e):
            _print_fetch_error(f"URLError {path}", e)
            raise
        print(
            f"[get_game_data] cert verify failed for {path}; retrying with curl",
            file=sys.stderr,
        )
        return _api_post_curl(path, jwt, body)
    except Exception as e:
        _print_fetch_error(f"api_post {path}", e)
        raise


def _api_post_curl(path: str, jwt: str, body: dict[str, Any]) -> dict[str, Any]:
    import subprocess
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tmp:
        json.dump(body, tmp)
        tmp_path = tmp.name
    try:
        proc = subprocess.run(
            [
                "curl",
                "-sS",
                "-X",
                "POST",
                path,
                "-H",
                "Content-Type: application/json",
                "-H",
                f"Authorization: Bearer {jwt}",
                "--data-binary",
                f"@{tmp_path}",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        _print_fetch_error(
            f"curl {path} exit {e.returncode}",
            e,
            extra=f"stdout:\n{e.stdout}\nstderr:\n{e.stderr}",
        )
        raise
    finally:
        Path(tmp_path).unlink(missing_ok=True)
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        _print_fetch_error(
            f"curl {path} invalid JSON",
            e,
            extra=proc.stdout,
        )
        raise


def fetch_game_view_model(game_id: UUID, jwt: str) -> dict[str, Any]:
    payload = {"GameId": str(game_id)}
    resp = api_post(GET_GAME_VIEW_MODEL, jwt, payload)
    if resp.get("success") and resp.get("data"):
        return resp
    print(
        f"[get_game_data] get_game_view_model failed for {game_id}: "
        f"{json.dumps(resp, default=str)}",
        file=sys.stderr,
    )
    # Not a participator / restricted — try spectate.
    spec = api_post(SPECTATE_GAME, jwt, payload)
    if spec.get("success") and spec.get("data"):
        return spec
    print(
        f"[get_game_data] spectate_game failed for {game_id}: "
        f"{json.dumps(spec, default=str)}",
        file=sys.stderr,
    )
    err = resp.get("errorMessage") or spec.get("errorMessage") or "unknown error"
    code = resp.get("errorCode", spec.get("errorCode"))
    raise RuntimeError(f"Failed to fetch game {game_id}: errorCode={code} {err}")


def build_output(resp: dict[str, Any]) -> dict[str, Any]:
    data = resp["data"]
    current_b64 = data.get("currentGameStateData")
    if not current_b64:
        raise RuntimeError("Response missing currentGameStateData")
    return {
        "id": data.get("id"),
        "state": data.get("state"),
        "date_created": data.get("dateCreated"),
        "date_last_command": data.get("dateLastCommand"),
        "owner_id": data.get("ownerId"),
        "game_settings_json": data.get("gameSettingsJson"),
        "timer_settings": data.get("timerSettings"),
        "game_context": data.get("gameContext"),
        # Finished board — same bytes OpenSession uses for the live/final state.
        "current_game_state_data": current_b64,
        "initial_game_state_data": data.get("initialGameStateData"),
        "_comment": (
            "current_game_state_data is the finished/latest IBinarySerializable "
            "GameState (base64); initial_game_state_data is the opening board. "
            "Decode with deserialize_gamestate.py --which start|end."
        ),
    }


DEFAULT_SHARE_LINK = (
    "https://share.polytopia.io/g/600d9435-991c-4cad-bd0f-08def66897ab"
)


def fetch_game_data(
    share_link: str,
    *,
    jwt: Optional[str] = None,
    allow_unfinished: bool = False,
    use_cache: bool = True,
    which: str = "end",
) -> dict[str, Any]:
    """Share URL/UUID → metadata dict with start and end GameState blobs.

    Raises ``RuntimeError`` if the game is not Ended unless ``allow_unfinished``.
    Uses ``load_jwt()`` when ``jwt`` is omitted.

    When ``use_cache`` is true (default), an Ended (state 4) snapshot is reused
    and the API is not called. In-progress cache (state 3, etc.) is ignored so
    the latest board is fetched. ``which`` is ``"start"`` or ``"end"`` (aliases
    accepted); a cached Ended file missing the requested blob is ignored so the
    API can fill it in.
    """
    game_id = parse_game_id(share_link)
    snapshot = normalize_snapshot(which)
    if use_cache:
        cached = read_cached_game_data(game_id)
        if cached is not None and cached.get("state") == STATE_ENDED:
            if snapshot == "start":
                has_blob = (
                    cached.get("initial_game_state_data")
                    or cached.get("initialGameStateData")
                )
            else:
                has_blob = (
                    cached.get("current_game_state_data")
                    or cached.get("currentGameStateData")
                )
            if has_blob:
                cached = dict(cached)
                cached["_from_cache"] = True
                return cached

    token = jwt if jwt is not None else load_jwt()
    out = build_output(fetch_game_view_model(game_id, token))
    state = out.get("state")
    if state != STATE_ENDED and not allow_unfinished:
        raise RuntimeError(
            f"Game state is {state}, expected Ended ({STATE_ENDED}). "
            f"Pass allow_unfinished=True to fetch anyway."
        )
    if use_cache:
        write_cached_game_data(game_id, out)
    out = dict(out)
    out["_from_cache"] = False
    return out


def normalize_snapshot(which: Optional[str] = None) -> str:
    """Map UI/CLI aliases onto ``"start"`` or ``"end"`` (default end)."""
    if which is None or which is False:
        return "end"
    if which is True:
        return "start"
    text = str(which).strip().lower()
    if text in ("", "end", "current", "final", "finished"):
        return "end"
    if text in ("start", "initial", "begin", "beginning"):
        return "start"
    raise ValueError(f"unknown snapshot {which!r}; use 'start' or 'end'")


def game_state_bytes(out: dict[str, Any], *, which: str = "end") -> bytes:
    """Decode start (``initial_game_state_data``) or end (``current_game_state_data``)."""
    snapshot = normalize_snapshot(which)
    if snapshot == "start":
        b64 = out.get("initial_game_state_data") or out.get("initialGameStateData")
        if not b64:
            raise KeyError("no initial_game_state_data in response")
        return base64.b64decode(b64)
    b64 = out.get("current_game_state_data") or out.get("currentGameStateData")
    if not b64:
        raise KeyError("no current_game_state_data in response")
    return base64.b64decode(b64)
