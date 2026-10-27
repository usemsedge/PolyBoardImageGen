"""Share link or .state file → GameState.

Typical use::

    from __init__ import extract, game_state_to_dict

    extracted, game_id = extract("https://share.polytopia.io/g/<uuid>")
    print(game_state_to_dict(extracted.current))

CLI::

    python3 __main__.py <finished-game-link> [-o out.json] [-s game.state]
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from api import (
    CACHE_DIR,
    STATE_ENDED,
    fetch_game_data,
    game_state_bytes,
    load_jwt,
    parse_game_id,
)
from model import GameState
from wire import (
    deserialize,
    game_state_to_dict,
    lz4_unpickle,
    write_hotseat_state_file,
    write_state_file,
)

# fetch_gamestate is defined below after deserialize is imported.


@dataclass
class Extracted:
    """Decoded boards. ``current`` is the finished / latest state."""

    initial: GameState
    current: GameState
    last_turn: Optional[GameState] = None
    pickled: Optional[bytes] = None
    meta: Optional[dict[str, Any]] = None


def _api_pair(blob: dict) -> tuple[GameState, GameState]:
    """API snapshot → (initial, current). Server already split start/end."""
    current = deserialize(game_state_bytes(blob, which="end"))
    try:
        initial = deserialize(game_state_bytes(blob, which="start"))
    except KeyError:
        initial = current
    return initial, current


def _take_gs(raw: bytes, at: int) -> tuple[GameState, int]:
    """One GameState.Serialize at `at`. deserialize() wants version + Serialize."""
    version = struct.unpack_from("<i", raw, at)[0]
    rest = raw[at:]
    try:
        return deserialize(struct.pack("<i", version) + rest), len(rest)
    except ValueError as exc:
        if "trailing" not in str(exc):
            raise
        used = len(rest) - int(str(exc).split()[1])
        return deserialize(struct.pack("<i", version) + rest[:used]), used


def split_envelope(payload: bytes) -> tuple[GameState, GameState, Optional[GameState]]:
    """Uncompressed LocalGameData / HotseatGameData.

    Layout: int version, then two GameState.Serialize blobs (initial +
    current). Hotseat adds a third (lastTurnGameState).
    """
    pos = 4
    initial, n1 = _take_gs(payload, pos)
    pos += n1
    current, n2 = _take_gs(payload, pos)
    pos += n2
    if len(payload) - pos > 2:
        try:
            last_turn, _ = _take_gs(payload, pos)
            return initial, current, last_turn
        except Exception:
            pass
    return initial, current, None


def decode_bytes(data: bytes) -> Extracted:
    """Bytes → boards.

    .state envelope: lz4_unpickle → split → current is the finished board.
    API dump: deserialize the single uncompressed GameState.
    K4os V0 stores pickle version in the low 3 bits of the first byte.
    """
    if data and (data[0] & 7) == 0:
        initial, current, last_turn = split_envelope(lz4_unpickle(data))
        return Extracted(initial, current, last_turn, pickled=data)
    gs = deserialize(data)
    return Extracted(gs, gs)


def extract(
    replay: str,
    *,
    allow_unfinished: bool = False,
    use_cache: bool = True,
) -> tuple[Extracted, str]:
    """Share URL/UUID or local file → (Extracted, game id)."""
    src = Path(replay).expanduser()
    if src.is_file():
        raw = src.read_bytes()
        if src.suffix.lower() == ".json" or raw[:1] in (b"{", b"["):
            initial, current = _api_pair(json.loads(raw.decode("utf-8")))
            return Extracted(initial, current), src.stem
        return decode_bytes(raw), src.stem
    meta = fetch_game_data(
        replay, allow_unfinished=allow_unfinished, use_cache=use_cache, which="end"
    )
    initial, current = _api_pair(meta)
    return Extracted(initial, current, meta=meta), str(parse_game_id(replay))


def write_state(path: Path, extracted: Extracted) -> Path:
    """Write a K4os .state: copy an existing envelope, else rebuild from blobs."""
    dest = path if path.is_absolute() else Path.cwd() / path
    if extracted.pickled:
        dest.write_bytes(extracted.pickled)
    elif extracted.last_turn is not None:
        write_hotseat_state_file(
            dest, extracted.initial, extracted.current, extracted.last_turn
        )
    else:
        write_state_file(
            dest,
            extracted.initial,
            extracted.current,
            int(extracted.current.current_command or 0),
        )
    return dest


def fetch_gamestate(
    share_link: str,
    *,
    jwt: Optional[str] = None,
    allow_unfinished: bool = False,
    use_cache: bool = True,
    which: str = "end",
) -> GameState:
    """Share URL/UUID → deserialized GameState (start or end board)."""
    from api import fetch_game_data as _fetch, normalize_snapshot

    snapshot = normalize_snapshot(which)
    out = _fetch(
        share_link,
        jwt=jwt,
        allow_unfinished=allow_unfinished,
        use_cache=use_cache,
        which=snapshot,
    )
    return deserialize(game_state_bytes(out, which=snapshot))


def _cwd(path: Path) -> Path:
    """Relative names land in the process cwd, not next to this package."""
    return path if path.is_absolute() else Path.cwd() / path


def main(argv=None) -> int:
    """Share link or local .state → final GameState JSON (optional .state via -s)."""
    p = argparse.ArgumentParser(
        prog="python3 __main__.py",
        description=(
            "Finished Polytopia game (ended share link) → GameState JSON. "
            "The game must have finished (server state Ended). "
            "Local .state files: lz4_unpickle, split initial+current (or hotseat), "
            "deserialize, then game_state_to_dict."
        ),
    )
    p.add_argument(
        "replay",
        metavar="FINISHED_GAME_LINK",
        help=(
            "finished game share URL (https://share.polytopia.io/g/<uuid>), "
            "bare game UUID, or a local .state/.bin/.json"
        ),
    )
    p.add_argument("-o", "--output", type=Path, help="JSON path (default: ./<id>.json in cwd)")
    p.add_argument("-s", dest="state", type=Path, metavar="FILE", help="also write a K4os .state")
    p.add_argument(
        "--allow-unfinished",
        "--allow_unfinished",
        action="store_true",
        help="accept in-progress games (server state is not Ended)",
    )
    p.add_argument("--no-cache", action="store_true")
    args = p.parse_args(argv)

    try:
        extracted, game_id = extract(
            args.replay.strip(),
            allow_unfinished=args.allow_unfinished,
            use_cache=not args.no_cache,
        )
    except Exception as exc:
        print(f"extract failed: {exc}", file=sys.stderr)
        print(
            "Pass a finished game share link (https://share.polytopia.io/g/<uuid>). "
            "In-progress games need --allow-unfinished.",
            file=sys.stderr,
        )
        return 1

    gs = extracted.current
    out = _cwd(args.output or Path(f"{game_id}.json"))
    out.write_text(json.dumps(game_state_to_dict(gs), indent=2) + "\n")
    written = [str(out)]
    if args.state is not None:
        written.append(str(write_state(_cwd(args.state), extracted)))

    name = (gs.settings.game_name if gs.settings else "") or ""
    w = gs.map.width if gs.map else 0
    h = gs.map.height if gs.map else 0
    extra = ""
    if extracted.meta is not None:
        extra = (
            f" state={extracted.meta.get('state')} "
            f"cache={'hit' if extracted.meta.get('_from_cache') else 'miss'}"
        )
    print(
        f"wrote {' '.join(written)}  {name!r} v{gs.version} turn={gs.current_turn} "
        f"{w}x{h} players={len(gs.player_states)} commands={len(gs.command_stack)}{extra}",
        file=sys.stderr,
    )
    return 0


__all__ = [
    "Extracted",
    "GameState",
    "CACHE_DIR",
    "STATE_ENDED",
    "decode_bytes",
    "deserialize",
    "extract",
    "fetch_game_data",
    "fetch_gamestate",
    "game_state_bytes",
    "game_state_to_dict",
    "load_jwt",
    "lz4_unpickle",
    "main",
    "parse_game_id",
    "split_envelope",
    "write_state",
]
