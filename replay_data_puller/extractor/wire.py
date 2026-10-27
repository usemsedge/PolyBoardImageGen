"""Binary GameState codec: layouts, deserialize, K4os pickle, .state envelopes."""
from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from model import (
    GetTribeTypeFromLegacyIndex,
    LEGACY_TRIBE_ORDER,
    ActionRecord,
    CommandRecord,
    CommandTrigger,
    GameSettings,
    GameState,
    ImprovementState,
    MapData,
    PlayerState,
    ResourceState,
    TileData,
    UnitState,
    WorldCoordinates,
)

# Command / action Serialize field order
Field = Tuple[str, str]
Layout = List[Field]

COMMAND_LAYOUTS: Dict[int, Layout] = {
    1: [("player", "player_id"), ("ushort", "type"), ("coords", "coordinates")],
    2: [
        ("player", "player_id"),
        ("uint", "unit_id"),
        ("coords", "origin"),
        ("coords", "target"),
    ],
    3: [("player", "player_id"), ("coords", "coordinates")],
    4: [("player", "player_id"), ("coords", "coordinates")],
    5: [("player", "player_id"), ("ushort", "type"), ("coords", "coordinates")],
    6: [
        ("player", "player_id"),
        ("coords", "from"),
        ("coords", "to"),
        ("uint", "unit_id"),
    ],
    7: [
        ("player", "player_id"),
        ("uint", "unit_id"),
        ("coords", "coordinates"),
    ],
    8: [("player", "player_id"), ("ushort", "type")],
    9: [("player", "player_id"), ("coords", "coordinates")],
    10: [("player", "player_id"), ("coords", "coordinates")],
    # CityReward: coordinates then reward (Serialize order).
    11: [
        ("player", "player_id"),
        ("coords", "coordinates"),
        ("ushort", "reward"),
    ],
    13: [("player", "player_id"), ("coords", "coordinates")],
    14: [("player", "player_id"), ("coords", "coordinates")],
    15: [("player", "player_id")],
    16: [("player", "player_id"), ("ushort", "type"), ("coords", "coordinates")],
    17: [("player", "player_id"), ("coords", "coordinates")],
    # BreakIce: What is not serialized.
    18: [("player", "player_id"), ("coords", "coordinates")],
    20: [("player", "player_id")],
    21: [("player", "player_id"), ("coords", "coordinates")],
    22: [("player", "player_id")],
    24: [("player", "player_id"), ("coords", "coordinates")],
    25: [("player", "player_id"), ("coords", "coordinates")],
    26: [("player", "player_id"), ("coords", "coordinates")],
    27: [
        ("player", "player_id"),
        ("coords", "coordinates"),
        ("byte", "opponent_id"),
    ],
    28: [
        ("player", "player_id"),
        ("byte", "opponent_id"),
        ("bool", "accepted"),
    ],
    29: [
        ("player", "player_id"),
        ("coords", "coordinates"),
        ("byte", "opponent_id"),
    ],
    30: [
        ("player", "player_id"),
        ("coords", "coordinates"),
        ("byte", "opponent_id"),
    ],
    32: [
        ("player", "player_id"),
        ("coords", "coordinates"),
        ("byte", "opponent_id"),
    ],
    33: [("player", "player_id"), ("coords", "coordinates")],
    # Resign: kicker + was_kicked only when version >= 0x5d (handled in reader).
    35: [
        ("player", "player_id"),
        ("byte", "resigned_player_id"),
        ("byte", "kicker_player_id"),
        ("bool", "was_kicked"),
    ],
    36: [("player", "player_id"), ("coords", "coordinates")],
    37: [("player", "player_id"), ("coords", "coordinates")],
    38: [("player", "player_id"), ("coords", "coordinates")],
    # ClearTileEffect: effect ushort before coordinates.
    39: [
        ("player", "player_id"),
        ("ushort", "effect"),
        ("coords", "coordinates"),
    ],
}

# ActionType -> body layout (Action*.Serialize). Hand-checked for common types;
# remaining entries mirror Serialize field order from GameAssembly.
ACTION_LAYOUTS: Dict[int, Layout] = {
    1: [
        ("player", "player_id"),
        ("ushort", "type"),
        ("coords", "coordinates"),
        ("bool", "deduct_cost"),
    ],
    2: [
        ("player", "player_id"),
        ("int", "damage"),
        ("coords", "origin"),
        ("coords", "target"),
        ("ushort", "animation"),
        ("bool", "should_move_to_target"),
        ("ushort", "delay"),
    ],
    3: [("player", "player_id"), ("coords", "coordinates")],
    4: [("player", "player_id"), ("coords", "coordinates")],
    5: [
        ("player", "player_id"),
        ("ushort", "type"),
        ("coords", "coordinates"),
        ("int", "cost"),
    ],
    6: [
        ("player", "player_id"),
        ("uint", "unit_id"),
        ("coords_list", "path"),
        ("bool", "should_animate"),
        ("byte", "reason"),
    ],
    7: [("player", "player_id"), ("coords", "coordinates")],
    8: [("player", "player_id"), ("ushort", "type"), ("int", "cost")],
    9: [("player", "player_id"), ("coords", "coordinates")],
    10: [
        ("player", "player_id"),
        ("coords", "coordinates"),
        ("coords", "home_coordinates"),
        ("bool", "get_paid"),
    ],
    11: [
        ("player", "player_id"),
        ("coords", "coordinates"),
        ("ushort", "reward"),
    ],
    12: [
        ("player", "player_id"),
        ("byte", "other_player_id"),
        ("coords", "coordinates"),
    ],
    13: [("player", "player_id"), ("coords", "coordinates")],
    14: [
        ("player", "player_id"),
        ("coords", "coordinates"),
        ("ushort", "reward"),
    ],
    15: [("player", "player_id")],
    16: [
        ("player", "player_id"),
        ("ushort", "type"),
        ("coords", "coordinates"),
        ("int", "cost"),
    ],
    17: [
        ("player", "player_id"),
        ("coords", "coordinates"),
        ("ushort", "radius"),
        ("bool", "freeze_units"),
        ("bool", "only_owned_tiles"),
    ],
    18: [("player", "player_id")],
    19: [("player", "player_id"), ("coords", "coordinates")],
    20: [
        ("player", "player_id"),
        ("coords", "coordinates"),
        ("byte", "old_owner_id"),
    ],
    21: [("player", "player_id"), ("coords", "coordinates")],
    22: [("player", "player_id")],
    23: [("player", "player_id"), ("coords", "coordinates")],
    24: [("player", "player_id"), ("coords", "source")],
    25: [("player", "player_id"), ("coords", "coordinates")],
    26: [
        ("player", "player_id"),
        ("int", "delay"),
        ("coords", "source"),
        ("coords", "target"),
    ],
    27: [
        ("player", "player_id"),
        ("int", "amount"),
        ("int", "delay"),
        ("coords", "source"),
    ],
    28: [
        ("player", "player_id"),
        ("int", "delay"),
        ("coords", "source"),
        ("int", "amount"),
    ],
    29: [("player", "player_id")],
    30: [
        ("player", "player_id"),
        ("uint", "unit_id"),
        ("uint", "remaining_moves"),
        ("uint", "seed"),
        ("coords", "from"),
        ("coords_list", "path"),
    ],
    31: [("player", "player_id"), ("byte_list", "players_to_update")],
    32: [
        ("player", "player_id"),
        ("int", "delay"),
        ("coords", "target"),
    ],
    34: [("player", "player_id"), ("coords", "coordinates")],
    35: [("player", "player_id"), ("coords", "coordinates")],
    36: [("player", "player_id"), ("ushort", "tribe")],
    37: [("player", "player_id"), ("byte", "winning_player_id")],
    38: [
        ("player", "player_id"),
        ("coords", "coordinates"),
        ("ushort", "fixed_heal_amount"),
    ],
    39: [("player", "player_id")],
    40: [("player", "player_id"), ("coords", "coordinates")],
    41: [
        ("player", "player_id"),
        ("coords", "coordinates"),
        ("ushort", "amount"),
    ],
    42: [
        ("player", "player_id"),
        ("coords", "origin"),
        ("coords", "target"),
    ],
    43: [
        ("player", "player_id"),
        ("int", "damage"),
        ("coords", "origin"),
        ("coords", "target"),
    ],
    44: [("player", "player_id"), ("int", "type")],
    45: [("player", "player_id")],
    46: [("player", "player_id"), ("coords", "coordinates")],
    47: [
        ("player", "player_id"),
        ("coords", "coordinates"),
        ("int", "climate"),
    ],
    48: [("player", "player_id"), ("uint", "unit_id")],
    49: [("player", "player_id"), ("byte", "target_player_id")],
    50: [
        ("player", "player_id"),
        ("ushort", "type"),
        ("coords", "coordinates"),
        ("ushort", "reason"),
    ],
    51: [("player", "player_id"), ("coords", "coordinates")],
    52: [("player", "player_id"), ("coords", "target")],
    53: [("player", "player_id")],
    54: [("player", "player_id"), ("coords", "coordinates")],
    55: [("player", "player_id"), ("coords", "coordinates")],
    56: [("player", "player_id"), ("coords", "coordinates")],
    57: [
        ("player", "player_id"),
        ("coords", "coordinates"),
        ("ushort", "radius"),
    ],
    58: [("player", "player_id")],
    59: [("player", "player_id"), ("int", "amount")],
    60: [("player", "player_id")],
    61: [("player", "player_id"), ("byte", "target_player_id")],
    62: [("player", "player_id"), ("ushort", "command_type")],
    63: [
        ("player", "player_id"),
        ("coords", "origin"),
        ("coords", "target"),
    ],
    64: [
        ("player", "player_id"),
        ("ushort", "eater"),
        ("coords", "coordinates"),
    ],
    66: [("player", "player_id"), ("coords", "coordinates")],
    68: [("player", "player_id"), ("coords", "coordinates")],
    69: [("player", "player_id"), ("coords", "coordinates")],
    70: [
        ("player", "player_id"),
        ("coords", "coordinates"),
        ("coords", "home_coordinates"),
    ],
    71: [("player", "player_id"), ("coords", "coordinates")],
    72: [("player", "player_id"), ("byte", "sender_id")],
    73: [
        ("player", "player_id"),
        ("byte", "sender_id"),
        ("bool", "accepted"),
    ],
    74: [("player", "player_id"), ("byte", "opponent_id")],
    75: [("player", "player_id"), ("byte", "opponent_id")],
    76: [("player", "player_id"), ("byte", "opponent_id")],
    77: [("player", "player_id"), ("coords", "coordinates")],
    79: [("player", "player_id"), ("byte", "opponent_id")],
    80: [("player", "player_id"), ("coords", "coordinates")],
    81: [
        ("player", "player_id"),
        ("coords", "coordinates"),
        ("coords", "origin"),
        ("bool", "show_reveal_popup"),
    ],
    82: [("player", "player_id"), ("coords", "coordinates")],
    83: [
        ("player", "player_id"),
        ("coords", "coordinates"),
        ("ushort", "reward"),
        ("ushort", "unit_type"),
    ],
    # Resign: trigger list then ids when version >= 0x5d (handled in reader).
    84: [
        ("player", "player_id"),
        ("trigger_list", "pending_command_triggers"),
        ("byte", "resigned_player_id"),
        ("byte", "kicker_player_id"),
        ("bool", "was_kicked"),
    ],
    85: [("player", "player_id")],
    86: [("player", "player_id"), ("uint", "unit_id"), ("bool", "add_bubble")],
    87: [("player", "player_id"), ("coords", "coordinates")],
    88: [
        ("player", "player_id"),
        ("ushort", "effect"),
        ("coords", "target"),
    ],
}


# ---------------------------------------------------------------------------
# Deserialize
# ---------------------------------------------------------------------------

# TaskData.Type values that carry an extra int after the two TaskBase bools.
_TASK_WITH_COUNTER = {1, 5, 7, 9}  # Pacifist, Killer, Explorer, Convert


class BinaryReader:
    """Little-endian reader matching ``System.IO.BinaryReader`` primitives."""

    def __init__(self, data: bytes, pos: int = 0) -> None:
        self.data = data
        self.pos = pos

    def remaining(self) -> int:
        return len(self.data) - self.pos

    def take(self, n: int) -> bytes:
        if self.pos + n > len(self.data):
            raise EOFError(
                f"need {n} bytes at {self.pos}, only {self.remaining()} left"
            )
        out = self.data[self.pos : self.pos + n]
        self.pos += n
        return out

    def u8(self) -> int:
        return self.take(1)[0]

    def i8(self) -> int:
        return struct.unpack("<b", self.take(1))[0]

    def bool(self) -> bool:
        return self.u8() != 0

    def u16(self) -> int:
        return struct.unpack("<H", self.take(2))[0]

    def i16(self) -> int:
        return struct.unpack("<h", self.take(2))[0]

    def u32(self) -> int:
        return struct.unpack("<I", self.take(4))[0]

    def i32(self) -> int:
        return struct.unpack("<i", self.take(4))[0]

    def f32(self) -> float:
        return struct.unpack("<f", self.take(4))[0]

    def string(self) -> str:
        # BinaryWriter 7-bit encoded length + UTF-8
        n = 0
        shift = 0
        while True:
            b = self.u8()
            n |= (b & 0x7F) << shift
            if not (b & 0x80):
                break
            shift += 7
            if shift > 35:
                raise ValueError("invalid 7-bit string length")
        return self.take(n).decode("utf-8")

    def coords(self) -> WorldCoordinates:
        return WorldCoordinates(self.i32(), self.i32())


def _read_improvement(r: BinaryReader) -> ImprovementState:
    typ = r.u16()
    level = r.u16()
    founded = r.u16()
    xp = r.i16()
    population = r.i16()
    production = r.u16()
    base_score = r.u16()
    border_size = r.u16()
    upgrade = r.u16()
    connected = r.u8()
    has_name = r.bool()
    name = r.string() if has_name else ""
    founder = r.u8()
    n_rewards = r.u16()
    rewards = [r.u16() for _ in range(n_rewards)]
    n_effects = r.u16()
    effects = [r.u16() for _ in range(n_effects)]
    return ImprovementState(
        type=typ,
        founder=founder,
        level=level,
        founded=founded,
        xp=xp,
        population=population,
        production=production,
        base_score=base_score,
        border_size=border_size,
        upgrade=upgrade,
        connected_to_capital_of_player=connected,
        name=name,
        rewards=rewards,
        effects=effects,
    )


def _read_unit(r: BinaryReader, version: int) -> UnitState:
    uid = r.u32()
    owner = r.u8()
    typ = r.u16()
    follower = r.u32()
    leader = r.u32()
    coordinates = r.coords()
    home = r.coords()
    health = r.u16()
    promotion_level = r.u16()
    xp = r.u16()
    moved = r.bool()
    attacked = r.bool()
    flipped = r.bool()
    created_turn = r.u16()
    passenger = _read_unit(r, version) if r.bool() else None
    n_effects = r.u16()
    effects = [r.u16() for _ in range(n_effects)]
    # i16 TribeType; Skin.NONE (-1) is stored as 65535 after a uint mask and
    # must not be treated as a real tribe (that falls through to Nature art).
    birth_climate = r.i16()
    if birth_climate < 0:
        birth_climate = 0
    direction = r.u8()
    birth_skin = r.u16() if version >= 0x57 else 0
    if birth_skin == 0xFFFF:
        birth_skin = 0
    return UnitState(
        id=uid,
        leader=leader,
        follower=follower,
        owner=owner,
        birth_climate=birth_climate,
        birth_climate_skin_type=birth_skin,
        type=typ,
        coordinates=coordinates,
        home=home,
        passenger_unit=passenger,
        health=health,
        promotion_level=promotion_level,
        xp=xp,
        moved=moved,
        attacked=attacked,
        direction=direction,
        flipped=flipped,
        created_turn=created_turn,
        effects=effects,
    )


def _read_tile(r: BinaryReader, version: int) -> TileData:
    coordinates = r.coords()
    terrain = r.u16()
    # TileData.climate is a legacy tribe index (aimo=10, xinxi=1, …), not TribeType.
    climate = GetTribeTypeFromLegacyIndex(r.i16() & 0xFFFF)
    altitude = r.i16()
    owner = r.u8()
    capital_of = r.u8()
    ruling = r.coords()
    resource = ResourceState(type=r.u16()) if r.bool() else None
    improvement = _read_improvement(r) if r.bool() else None
    unit = _read_unit(r, version) if r.bool() else None
    n_vis = r.u8()
    explorers = [r.u8() for _ in range(n_vis)]
    has_road = r.bool()
    has_route = r.bool()
    skin = 0
    effects: List[int] = []
    if version >= 0x56:
        skin = r.i32()
        if version >= 0x69:
            n_eff = r.u8()
            effects = [r.i32() for _ in range(n_eff)]
    return TileData(
        coordinates=coordinates,
        terrain=terrain,
        climate=climate,
        skin=skin,
        effects=effects,
        altitude=altitude,
        owner=owner,
        capital_of=capital_of,
        explorers=explorers,
        ruling_city_coordinates=ruling,
        improvement=improvement,
        resource=resource,
        unit=unit,
        has_road=has_road,
        has_route=has_route,
    )


def _read_task(r: BinaryReader, version: int) -> Dict[str, Any]:
    """Read one task (type ushort + body). Returned as a plain dict."""
    typ = r.u16()
    is_started = r.bool()
    is_completed = r.bool()
    counter = None
    if typ in _TASK_WITH_COUNTER:
        counter = r.i32()
    return {
        "type": typ,
        "is_started": is_started,
        "is_completed": is_completed,
        "counter": counter,
    }


def _read_diplomacy_relation(r: BinaryReader, version: int) -> Dict[str, Any]:
    state = r.u8()
    last_attack = r.i32()
    embassy_level = r.u8()
    last_peace_broken = r.i32()
    first_meet = r.i32()
    embassy_build = r.i32()
    previous_attack = r.i32() if version >= 0x51 else -100
    return {
        "state": state,
        "last_attack_turn": last_attack,
        "embassy_level": embassy_level,
        "last_peace_broken_turn": last_peace_broken,
        "first_meet": first_meet,
        "embassy_build_turn": embassy_build,
        "previous_attack_turn": previous_attack,
    }


def _read_player(r: BinaryReader, version: int) -> PlayerState:
    pid = r.u8()
    user_name = r.string()
    account_id = r.string()  # Nullable<Guid> as string (empty if none)
    auto_play = r.bool()
    start_tile = r.coords()
    tribe = r.u16()
    has_chosen_tribe = r.bool()
    handicap = r.i32()

    aggressions: Dict[int, int] = {}
    if version <= 0x70:
        n_agg = r.u16()
        for _ in range(n_agg):
            k = r.u8()
            v = r.i32()
            aggressions[k] = v

    currency = r.i32()
    score = r.u32()
    end_score = r.u32()
    cities = r.u16()

    n_tech = r.u16()
    available_tech = [r.u16() for _ in range(n_tech)]

    n_known = r.u16()
    known_players = [r.u8() for _ in range(n_known)]

    n_tasks = r.u16()
    tasks = [_read_task(r, version) for _ in range(n_tasks)]

    kills = r.u32()
    casualities = r.u32()
    wipe_outs = r.u32()
    color = r.i32()
    tribe_mix = r.u8()

    n_unique = r.u16()
    built_unique = [r.i16() & 0xFFFF for _ in range(n_unique)]

    relations: Dict[int, Any] = {}
    messages: List[Any] = []
    killer_id = 0
    killed_turn = 0
    resigned_at = 0
    wiped_at = 0
    skin_type = 0
    resigned_turn = 0
    climate = 0

    if version >= 0x3C:
        n_rel = r.u16()
        for _ in range(n_rel):
            other = r.u8()
            relations[other] = _read_diplomacy_relation(r, version)
        n_msg = r.u16()
        messages = [{"type": r.u8(), "sender": r.u8()} for _ in range(n_msg)]
        killer_id = r.u8()
        killed_turn = r.u32()
        if version > 0x45:
            resigned_at = r.i32()
            wiped_at = r.i32()
            if version >= 0x56:
                skin_type = r.u16()
                if version >= 0x5D:
                    resigned_turn = r.i32()
                    if version >= 0x79:
                        climate = GetTribeTypeFromLegacyIndex(r.u8())

    return PlayerState(
        id=pid,
        user_name=user_name,
        account_id=account_id or None,
        auto_play=auto_play,
        start_tile=start_tile,
        tribe=tribe,
        tribe_mix=tribe_mix,
        climate=climate or tribe,
        has_chosen_tribe=has_chosen_tribe,
        handicap=handicap,
        resigned_turn=resigned_turn,
        resigned_at_command_index=resigned_at,
        wiped_at_command_index=wiped_at,
        available_tech=available_tech,
        tasks=tasks,
        aggressions=aggressions,
        known_players=known_players,
        built_unique_improvements=built_unique,
        relations=relations,
        messages=messages,
        skin_type=skin_type,
        currency=currency,
        score=score,
        end_score=end_score,
        cities=cities,
        kills=kills,
        casualities=casualities,
        wipe_outs=wipe_outs,
        killer_id=killer_id,
        killed_turn=killed_turn,
        color=color,
    )


def _read_settings(r: BinaryReader, version: int) -> GameSettings:
    # GameRules.SerializeDefault
    turn_limit = r.i32()
    score_limit = r.i32()
    win_by_capital = r.bool()
    allow_mirror = r.bool()
    allow_special = r.bool()
    win_by_exterm = r.bool()
    allow_tech_share = r.bool()
    death_cond = r.u16()

    base_mode = r.u8()
    rules_mode = r.u8()
    game_name = r.string()
    map_size = r.i32()

    n_dis = r.u16()
    disabled = [r.u16() for _ in range(n_dis)]
    n_unl = r.u16()
    unlocked = [r.u16() for _ in range(n_unl)]

    difficulty = r.u16()
    opponent_count = r.i32()
    game_type = r.u16()
    map_preset = r.u8()
    time_limit = r.i32()
    tb_city = r.f32()
    tb_pop = r.f32()
    base_time = r.f32()
    use_dyn = r.bool()
    use_banks = r.bool()
    live = r.bool()
    autoskip = r.bool()

    skins: List[tuple] = []
    west = ""
    if version >= 0x56:
        n_skins = r.i32()
        skins = [(r.u16(), r.u16()) for _ in range(n_skins)]
        if version >= 0x7A:
            west = r.string()

    return GameSettings(
        map_preset=map_preset,
        map_size=map_size,
        game_name=game_name,
        game_type=game_type,
        opponent_count=opponent_count,
        disabled_tribes=disabled,
        west_map_placement_user_id=west or None,
        wire={
            "turn_limit": turn_limit,
            "score_limit": score_limit,
            "win_by_capital": win_by_capital,
            "allow_mirror": allow_mirror,
            "allow_special": allow_special,
            "win_by_exterm": win_by_exterm,
            "allow_tech_share": allow_tech_share,
            "death_cond": death_cond,
            "base_mode": base_mode,
            "rules_mode": rules_mode,
            "unlocked": unlocked,
            "difficulty": difficulty,
            "time_limit": time_limit,
            "tb_city": tb_city,
            "tb_pop": tb_pop,
            "base_time": base_time,
            "use_dyn": use_dyn,
            "use_banks": use_banks,
            "live": live,
            "autoskip": autoskip,
            "skins": skins,
        },
    )


def _read_coords(r: BinaryReader) -> WorldCoordinates:
    return WorldCoordinates(r.i32(), r.i32())


def _read_command_trigger(r: BinaryReader, version: int) -> CommandTrigger:
    """CommandTrigger.Serialize: playerId, type(ushort), coords, [opponentId]."""
    player_id = r.u8()
    trigger_type = r.u16()
    coordinates = _read_coords(r)
    opponent_id = r.u8() if version >= 0x3C else 0
    return CommandTrigger(
        player_id=player_id,
        opponent_id=opponent_id,
        type=trigger_type,
        coordinates=coordinates,
    )


def _read_layout_fields(
    r: BinaryReader,
    layout: List[tuple],
    version: int,
) -> Dict[str, Any]:
    """Read Serialize body fields into a plain dict (coords as {x,y})."""
    out: Dict[str, Any] = {}
    for kind, name in layout:
        if kind in ("player", "byte"):
            out[name] = r.u8()
        elif kind == "bool":
            out[name] = r.bool()
        elif kind == "ushort":
            out[name] = r.u16()
        elif kind == "int":
            out[name] = r.i32()
        elif kind == "uint":
            out[name] = r.u32()
        elif kind == "coords":
            c = _read_coords(r)
            out[name] = {"x": c.x, "y": c.y}
        elif kind == "coords_list":
            n = r.i32()
            if n < 0 or n > 10_000:
                raise ValueError(f"coords_list {name} count={n}")
            out[name] = [
                {"x": c.x, "y": c.y}
                for c in (_read_coords(r) for _ in range(n))
            ]
        elif kind == "byte_list":
            n = r.i32()
            if n < 0 or n > 10_000:
                raise ValueError(f"byte_list {name} count={n}")
            out[name] = [r.u8() for _ in range(n)]
        elif kind == "trigger_list":
            n = r.u16()
            out[name] = [
                {
                    "player_id": t.player_id,
                    "opponent_id": t.opponent_id,
                    "type": t.type,
                    "coordinates": {
                        "x": t.coordinates.x,
                        "y": t.coordinates.y,
                    },
                }
                for t in (
                    _read_command_trigger(r, version) for _ in range(n)
                )
            ]
        else:
            raise ValueError(f"unknown layout kind {kind!r}")
    return out


def _read_command(r: BinaryReader, version: int) -> CommandRecord:
    ctype = r.u16()
    layout = COMMAND_LAYOUTS.get(ctype)
    if layout is None:
        raise ValueError(f"unsupported CommandType {ctype} at pos {r.pos - 2}")
    fields_layout = list(layout)
    # ResignCommand: kicker + was_kicked only when version >= 0x5d.
    if ctype == 35 and version < 0x5D:
        fields_layout = fields_layout[:2]
    body = _read_layout_fields(r, fields_layout, version)
    player_id = int(body.pop("player_id", 0))
    return CommandRecord(type=ctype, player_id=player_id, fields=body)


def _read_action(r: BinaryReader, version: int) -> ActionRecord:
    atype = r.u16()
    layout = ACTION_LAYOUTS.get(atype)
    if layout is None:
        raise ValueError(f"unsupported ActionType {atype} at pos {r.pos - 2}")
    fields_layout = list(layout)
    # ResignAction: resigned/kicker/was_kicked only when version >= 0x5d.
    if atype == 84 and version < 0x5D:
        fields_layout = [
            f for f in fields_layout if f[0] in ("player", "trigger_list")
        ]
    body = _read_layout_fields(r, fields_layout, version)
    player_id = int(body.pop("player_id", 0))
    return ActionRecord(type=atype, player_id=player_id, fields=body)


def _read_history(
    r: BinaryReader, version: int
) -> tuple:
    """pendingCommandTriggers, CommandStack, ActionStack, then trailing flags."""
    n_triggers = r.u16()
    triggers = [_read_command_trigger(r, version) for _ in range(n_triggers)]

    n_commands = r.u16()
    commands = [_read_command(r, version) for _ in range(n_commands)]

    n_actions = r.u16()
    actions = [_read_action(r, version) for _ in range(n_actions)]

    flagged = False
    village_seed = 0
    if version >= 0x62:
        flagged = r.bool()
    if version >= 0x7A:
        village_seed = r.i32()

    return triggers, commands, actions, flagged, village_seed


def deserialize(data: bytes) -> GameState:
    """Parse API / disk ``GameState`` bytes into a Python ``GameState``."""
    r = BinaryReader(data)
    # Disk/API wrapper writes the format version, then GameState.Serialize
    # which writes Version again (same int).
    outer_version = r.i32()
    version = r.i32()
    if version != outer_version:
        raise ValueError(
            f"version mismatch: outer={outer_version} GameState.Version={version}"
        )

    current_command = r.u16()
    current_turn = r.u32()
    current_player_index = r.u8()
    current_unit_id = r.u32()
    current_state = r.u8()
    seed = r.i32()

    settings = _read_settings(r, version)

    width = r.u16()
    height = r.u16()
    tiles = [_read_tile(r, version) for _ in range(width * height)]
    # Ensure row-major order by coordinates (serializer already emits x + y*w).
    tiles.sort(key=lambda t: (t.coordinates.y, t.coordinates.x))

    n_players = r.u16()
    players = [_read_player(r, version) for _ in range(n_players)]

    triggers, commands, actions, flagged, village_seed = _read_history(r, version)

    if r.remaining() != 0:
        raise ValueError(
            f"trailing {r.remaining()} bytes after GameState at pos {r.pos}"
        )

    return GameState(
        version=version,
        seed=seed,
        village_name_seed=village_seed,
        current_turn=current_turn,
        current_player_index=current_player_index,
        current_unit_id=current_unit_id,
        current_state=current_state,
        settings=settings,
        map=MapData(width=width, height=height, tiles=tiles),
        player_states=players,
        current_command=current_command,
        command_stack=commands,
        action_stack=actions,
        pending_command_triggers=triggers,
        has_flagged_need_for_update_routes=flagged,
    )


def load_bytes(path: Path, *, which: str = "end") -> bytes:
    raw = path.read_bytes()
    if path.suffix.lower() == ".json" or raw[:1] in (b"{", b"["):
        obj = json.loads(raw.decode("utf-8"))
        from api import game_state_bytes
        return game_state_bytes(obj, which=which)
    return raw


def game_state_summary(gs: GameState) -> dict:
    m = gs.map
    assert m is not None
    cities = [
        {
            "x": t.x,
            "y": t.y,
            "name": t.improvement.name if t.improvement else "",
            "owner": t.owner,
            "type": t.improvement.type if t.improvement else None,
        }
        for t in m.tiles
        if t.improvement and t.improvement.name
    ]
    return {
        "version": gs.version,
        "seed": gs.seed,
        "turn": gs.current_turn,
        "state": gs.current_state,
        "name": gs.settings.game_name if gs.settings else "",
        "map": f"{m.width}x{m.height}",
        "players": [
            {
                "id": p.id,
                "name": p.user_name,
                "tribe": p.tribe,
                "score": p.score,
                "currency": p.currency,
            }
            for p in gs.player_states
        ],
        "cities": cities,
        "units": sum(1 for t in m.tiles if t.unit),
        "improvements": sum(1 for t in m.tiles if t.improvement),
        "commands": len(gs.command_stack),
        "actions": len(gs.action_stack),
        "pending_triggers": len(gs.pending_command_triggers),
    }


def _tile_to_dict(t: TileData) -> dict:
    d: dict = {
        "coordinates": {"x": t.x, "y": t.y},
        "terrain": t.terrain,
        "climate": t.climate,
        "skin": t.skin,
        "effects": t.effects,
        "altitude": t.altitude,
        "owner": t.owner,
        "capital_of": t.capital_of,
        "explorers": t.explorers,
        "ruling_city_coordinates": {
            "x": t.ruling_city_coordinates.x,
            "y": t.ruling_city_coordinates.y,
        },
        "has_road": t.has_road,
        "has_route": t.has_route,
    }
    if t.resource:
        d["resource"] = {"type": t.resource.type}
    if t.improvement:
        imp = t.improvement
        d["improvement"] = {
            "type": imp.type,
            "founder": imp.founder,
            "level": imp.level,
            "founded": imp.founded,
            "xp": imp.xp,
            "population": imp.population,
            "production": imp.production,
            "base_score": imp.base_score,
            "border_size": imp.border_size,
            "upgrade": imp.upgrade,
            "connected_to_capital_of_player": imp.connected_to_capital_of_player,
            "name": imp.name,
            "rewards": imp.rewards,
            "effects": imp.effects,
        }
    if t.unit:
        u = t.unit
        d["unit"] = {
            "id": u.id,
            "leader": u.leader,
            "follower": u.follower,
            "owner": u.owner,
            "birth_climate": u.birth_climate,
            "birth_climate_skin_type": u.birth_climate_skin_type,
            "type": u.type,
            "coordinates": {"x": u.coordinates.x, "y": u.coordinates.y},
            "home": {"x": u.home.x, "y": u.home.y},
            "health": u.health,
            "promotion_level": u.promotion_level,
            "xp": u.xp,
            "moved": u.moved,
            "attacked": u.attacked,
            "direction": u.direction,
            "flipped": u.flipped,
            "created_turn": u.created_turn,
            "effects": u.effects,
        }
    return d


def _trigger_to_dict(t: CommandTrigger) -> dict:
    return {
        "player_id": t.player_id,
        "opponent_id": t.opponent_id,
        "type": t.type,
        "coordinates": {"x": t.coordinates.x, "y": t.coordinates.y},
    }


def _command_to_dict(c: CommandRecord) -> dict:
    return {"type": c.type, "player_id": c.player_id, "fields": c.fields}


def _action_to_dict(a: ActionRecord) -> dict:
    return {"type": a.type, "player_id": a.player_id, "fields": a.fields}


def game_state_to_dict(gs: GameState) -> dict:
    """Export a JSON-friendly dict compatible with ``gamestate.from_dict`` basics."""
    assert gs.map is not None
    settings = gs.settings
    return {
        "version": gs.version,
        "seed": gs.seed,
        "village_name_seed": gs.village_name_seed,
        "current_turn": gs.current_turn,
        "current_player_index": gs.current_player_index,
        "current_unit_id": gs.current_unit_id,
        "current_state": gs.current_state,
        "current_command": gs.current_command,
        "has_flagged_need_for_update_routes": gs.has_flagged_need_for_update_routes,
        "settings": {
            "map_preset": settings.map_preset if settings else 0,
            "map_size": settings.map_size if settings else 0,
            "game_name": settings.game_name if settings else "",
            "game_type": settings.game_type if settings else 0,
            "opponent_count": settings.opponent_count if settings else 0,
            "disabled_tribes": list(settings.disabled_tribes) if settings else [],
        },
        "map": {
            "width": gs.map.width,
            "height": gs.map.height,
            "tiles": [_tile_to_dict(t) for t in gs.map.tiles],
        },
        "player_states": [
            {
                "id": p.id,
                "user_name": p.user_name,
                "account_id": p.account_id,
                "auto_play": p.auto_play,
                "start_tile": {"x": p.start_tile.x, "y": p.start_tile.y},
                "tribe": p.tribe,
                "tribe_mix": p.tribe_mix,
                "climate": p.climate,
                "has_chosen_tribe": p.has_chosen_tribe,
                "handicap": p.handicap,
                "available_tech": p.available_tech,
                "known_players": p.known_players,
                "built_unique_improvements": p.built_unique_improvements,
                "skin_type": p.skin_type,
                "currency": p.currency,
                "score": p.score,
                "end_score": p.end_score,
                "cities": p.cities,
                "kills": p.kills,
                "casualities": p.casualities,
                "wipe_outs": p.wipe_outs,
                "killer_id": p.killer_id,
                "killed_turn": p.killed_turn,
                "color": p.color,
                "resigned_turn": p.resigned_turn,
            }
            for p in gs.player_states
        ],
        "pending_command_triggers": [
            _trigger_to_dict(t) for t in gs.pending_command_triggers
        ],
        "command_stack": [_command_to_dict(c) for c in gs.command_stack],
        "action_stack": [_action_to_dict(a) for a in gs.action_stack],
    }


# ---------------------------------------------------------------------------
# Serialize / K4os .state
# ---------------------------------------------------------------------------

CURRENT_VERSION = 0x7A  # 122, dump.cs GAME_VERSION
# Local .state files this Mac client actually wrote are still v116. Resume of a
# v122 synthetic hit ErrorCode.GameStateDeserializationFailed (1012).
LOCAL_SAVE_VERSION = 0x74  # 116
# Live Epic client (plist GameVersion 123) writes Pass & Play as 123.
LIVE_SAVE_VERSION = 0x7B  # 123
EMPTY_GUID = "00000000-0000-0000-0000-000000000000"

class BinaryWriter:
    """Little-endian writer matching ``System.IO.BinaryWriter`` primitives."""

    def __init__(self) -> None:
        self._buf = bytearray()

    def dumps(self) -> bytes:
        return bytes(self._buf)

    def raw(self, data: bytes) -> None:
        self._buf.extend(data)

    def u8(self, v: int) -> None:
        self._buf.append(int(v) & 0xFF)

    def bool(self, v: bool) -> None:
        self.u8(1 if v else 0)

    def u16(self, v: int) -> None:
        self._buf.extend(struct.pack("<H", int(v) & 0xFFFF))

    def i16(self, v: int) -> None:
        self._buf.extend(struct.pack("<h", int(v)))

    def u32(self, v: int) -> None:
        self._buf.extend(struct.pack("<I", int(v) & 0xFFFFFFFF))

    def i32(self, v: int) -> None:
        self._buf.extend(struct.pack("<i", int(v)))

    def f32(self, v: float) -> None:
        self._buf.extend(struct.pack("<f", float(v)))

    def string(self, s: str) -> None:
        encoded = (s or "").encode("utf-8")
        n = len(encoded)
        while True:
            b = n & 0x7F
            n >>= 7
            if n:
                self.u8(b | 0x80)
            else:
                self.u8(b)
                break
        self.raw(encoded)

    def coords(self, c: Optional[WorldCoordinates]) -> None:
        if c is None:
            self.i32(0)
            self.i32(0)
            return
        self.i32(c.x)
        self.i32(c.y)


def legacy_index_for_tribe(tribe: int) -> int:
    """Inverse of ``GetTribeTypeFromLegacyIndex`` for unique tribe slots."""
    t = int(tribe)
    for i, mapped in enumerate(LEGACY_TRIBE_ORDER):
        if int(mapped) == t:
            return i
    return 0


def _w(w: BinaryWriter, kind: str, value: Any) -> None:
    if kind in ("player", "byte"):
        w.u8(int(value or 0))
    elif kind == "bool":
        w.bool(bool(value))
    elif kind == "ushort":
        w.u16(int(value or 0))
    elif kind == "int":
        w.i32(int(value or 0))
    elif kind == "uint":
        w.u32(int(value or 0))
    elif kind == "coords":
        if isinstance(value, WorldCoordinates):
            w.coords(value)
        else:
            w.i32(int((value or {}).get("x", 0)))
            w.i32(int((value or {}).get("y", 0)))
    elif kind == "coords_list":
        items = value or []
        w.i32(len(items))
        for item in items:
            if isinstance(item, WorldCoordinates):
                w.coords(item)
            else:
                w.i32(int(item.get("x", 0)))
                w.i32(int(item.get("y", 0)))
    elif kind == "byte_list":
        items = value or []
        w.i32(len(items))
        for x in items:
            w.u8(int(x))
    elif kind == "trigger_list":
        items = value or []
        w.u16(len(items))
        for item in items:
            if isinstance(item, CommandTrigger):
                _write_trigger(w, item, CURRENT_VERSION)
            else:
                w.u8(int(item.get("player_id", 0)))
                w.u16(int(item.get("type", 0)))
                c = item.get("coordinates") or {}
                w.i32(int(c.get("x", 0)))
                w.i32(int(c.get("y", 0)))
                w.u8(int(item.get("opponent_id", 0)))
    else:
        raise ValueError(f"unknown layout kind {kind!r}")


def _write_trigger(w: BinaryWriter, t: CommandTrigger, version: int) -> None:
    w.u8(t.player_id)
    w.u16(t.type)
    w.coords(t.coordinates)
    if version >= 0x3C:
        w.u8(t.opponent_id)


def _write_improvement(w: BinaryWriter, imp: ImprovementState) -> None:
    w.u16(imp.type)
    w.u16(imp.level)
    w.u16(imp.founded)
    w.i16(imp.xp)
    w.i16(imp.population)
    w.u16(imp.production)
    w.u16(imp.base_score)
    w.u16(imp.border_size)
    w.u16(imp.upgrade)
    w.u8(imp.connected_to_capital_of_player)
    has_name = bool(imp.name)
    w.bool(has_name)
    if has_name:
        w.string(imp.name)
    w.u8(imp.founder)
    w.u16(len(imp.rewards))
    for x in imp.rewards:
        w.u16(x)
    w.u16(len(imp.effects))
    for x in imp.effects:
        w.u16(x)


def _write_unit(w: BinaryWriter, u: UnitState, version: int) -> None:
    w.u32(u.id)
    w.u8(u.owner)
    w.u16(u.type)
    w.u32(u.follower)
    w.u32(u.leader)
    w.coords(u.coordinates)
    w.coords(u.home)
    w.u16(u.health)
    w.u16(u.promotion_level)
    w.u16(u.xp)
    w.bool(u.moved)
    w.bool(u.attacked)
    w.bool(u.flipped)
    w.u16(u.created_turn)
    w.bool(u.passenger_unit is not None)
    if u.passenger_unit is not None:
        _write_unit(w, u.passenger_unit, version)
    w.u16(len(u.effects))
    for e in u.effects:
        w.u16(e)
    w.i16(u.birth_climate)
    w.u8(u.direction)
    if version >= 0x57:
        w.u16(u.birth_climate_skin_type)


def _write_tile(w: BinaryWriter, t: TileData, version: int) -> None:
    w.coords(t.coordinates)
    w.u16(t.terrain)
    w.i16(legacy_index_for_tribe(t.climate))
    w.i16(t.altitude)
    w.u8(t.owner)
    w.u8(t.capital_of)
    w.coords(t.ruling_city_coordinates)
    w.bool(t.resource is not None)
    if t.resource is not None:
        w.u16(t.resource.type)
    w.bool(t.improvement is not None)
    if t.improvement is not None:
        _write_improvement(w, t.improvement)
    w.bool(t.unit is not None)
    if t.unit is not None:
        _write_unit(w, t.unit, version)
    w.u8(len(t.explorers))
    for p in t.explorers:
        w.u8(p)
    w.bool(t.has_road)
    w.bool(t.has_route)
    if version >= 0x56:
        w.i32(t.skin)
        if version >= 0x69:
            w.u8(len(t.effects))
            for e in t.effects:
                w.i32(e)


def _write_task(w: BinaryWriter, task: Dict[str, Any]) -> None:
    typ = int(task.get("type", 0))
    w.u16(typ)
    w.bool(bool(task.get("is_started", False)))
    w.bool(bool(task.get("is_completed", False)))
    if typ in _TASK_WITH_COUNTER:
        w.i32(int(task.get("counter") or 0))


def _write_relation(w: BinaryWriter, rel: Dict[str, Any], version: int) -> None:
    w.u8(int(rel.get("state", 0)))
    w.i32(int(rel.get("last_attack_turn", -100)))
    w.u8(int(rel.get("embassy_level", 0)))
    w.i32(int(rel.get("last_peace_broken_turn", -100)))
    w.i32(int(rel.get("first_meet", -100)))
    w.i32(int(rel.get("embassy_build_turn", -100)))
    if version >= 0x51:
        w.i32(int(rel.get("previous_attack_turn", -100)))


def _write_player(w: BinaryWriter, p: PlayerState, version: int) -> None:
    w.u8(p.id)
    w.string(p.user_name or "")
    # C# writes Nullable<Guid> as Guid.ToString(); empty is not a valid Guid
    # (Guid.Parse("") throws → error 1012). Real saves use Guid.Empty.
    acct = p.account_id
    if acct is None or str(acct).strip() == "":
        w.string(EMPTY_GUID)
    else:
        w.string(str(acct))
    w.bool(p.auto_play)
    w.coords(p.start_tile)
    w.u16(p.tribe)
    w.bool(p.has_chosen_tribe)
    w.i32(p.handicap)
    if version <= 0x70:
        w.u16(len(p.aggressions))
        for k, v in p.aggressions.items():
            w.u8(k)
            w.i32(v)
    w.i32(p.currency)
    w.u32(p.score)
    w.u32(p.end_score)
    w.u16(p.cities)
    w.u16(len(p.available_tech))
    for t in p.available_tech:
        w.u16(t)
    w.u16(len(p.known_players))
    for k in p.known_players:
        w.u8(k)
    w.u16(len(p.tasks))
    for task in p.tasks:
        _write_task(w, task)
    w.u32(p.kills)
    w.u32(p.casualities)
    w.u32(p.wipe_outs)
    w.i32(p.color)
    w.u8(p.tribe_mix)
    w.u16(len(p.built_unique_improvements))
    for x in p.built_unique_improvements:
        w.i16(x)
    if version >= 0x3C:
        w.u16(len(p.relations))
        for other, rel in p.relations.items():
            w.u8(int(other))
            _write_relation(w, rel, version)
        w.u16(len(p.messages))
        for msg in p.messages:
            w.u8(int(msg.get("type", 0)))
            w.u8(int(msg.get("sender", 0)))
        w.u8(p.killer_id)
        w.u32(p.killed_turn)
        if version > 0x45:
            w.i32(p.resigned_at_command_index)
            w.i32(p.wiped_at_command_index)
            if version >= 0x56:
                w.u16(p.skin_type)
                if version >= 0x5D:
                    w.i32(p.resigned_turn)
                    if version >= 0x79:
                        w.u8(legacy_index_for_tribe(p.climate or p.tribe))


def _write_settings(w: BinaryWriter, s: GameSettings, version: int) -> None:
    wire = s.wire or {}
    w.i32(int(wire.get("turn_limit", 0)))
    w.i32(int(wire.get("score_limit", 0)))
    w.bool(bool(wire.get("win_by_capital", True)))
    w.bool(bool(wire.get("allow_mirror", True)))
    w.bool(bool(wire.get("allow_special", True)))
    w.bool(bool(wire.get("win_by_exterm", True)))
    w.bool(bool(wire.get("allow_tech_share", False)))
    w.u16(int(wire.get("death_cond", 0)))
    w.u8(int(wire.get("base_mode", 0)))
    w.u8(int(wire.get("rules_mode", 0)))
    w.string(s.game_name or "")
    w.i32(s.map_size)
    w.u16(len(s.disabled_tribes))
    for t in s.disabled_tribes:
        w.u16(t)
    unlocked = list(wire.get("unlocked") or [])
    w.u16(len(unlocked))
    for t in unlocked:
        w.u16(t)
    w.u16(int(wire.get("difficulty", 0)))
    w.i32(s.opponent_count)
    w.u16(s.game_type)
    w.u8(s.map_preset)
    w.i32(int(wire.get("time_limit", 0)))
    w.f32(float(wire.get("tb_city", 0.0)))
    w.f32(float(wire.get("tb_pop", 0.0)))
    w.f32(float(wire.get("base_time", 0.0)))
    w.bool(bool(wire.get("use_dyn", False)))
    w.bool(bool(wire.get("use_banks", False)))
    w.bool(bool(wire.get("live", False)))
    w.bool(bool(wire.get("autoskip", False)))
    if version >= 0x56:
        skins = list(wire.get("skins") or [])
        w.i32(len(skins))
        for a, b in skins:
            w.u16(a)
            w.u16(b)
        if version >= 0x7A:
            west = s.west_map_placement_user_id or ""
            w.string("" if west is None else str(west))


def _write_command(w: BinaryWriter, cmd: CommandRecord, version: int) -> None:
    w.u16(cmd.type)
    layout = COMMAND_LAYOUTS.get(cmd.type)
    if layout is None:
        raise ValueError(f"unsupported CommandType {cmd.type}")
    fields_layout = list(layout)
    if cmd.type == 35 and version < 0x5D:
        fields_layout = fields_layout[:2]
    body = dict(cmd.fields)
    body["player_id"] = cmd.player_id
    for kind, name in fields_layout:
        _w(w, kind, body.get(name))


def _write_action(w: BinaryWriter, act: ActionRecord, version: int) -> None:
    w.u16(act.type)
    layout = ACTION_LAYOUTS.get(act.type)
    if layout is None:
        raise ValueError(f"unsupported ActionType {act.type}")
    fields_layout = list(layout)
    if act.type == 84 and version < 0x5D:
        fields_layout = [f for f in fields_layout if f[0] in ("player", "trigger_list")]
    body = dict(act.fields)
    body["player_id"] = act.player_id
    for kind, name in fields_layout:
        _w(w, kind, body.get(name))


def write_game_state_serialize(w: BinaryWriter, gs: GameState) -> None:
    """``GameState.Serialize`` — version field then body."""
    version = int(gs.version)
    w.i32(version)
    w.u16(gs.current_command)
    w.u32(gs.current_turn)
    w.u8(gs.current_player_index)
    w.u32(gs.current_unit_id)
    w.u8(gs.current_state)
    w.i32(gs.seed)
    assert gs.settings is not None
    _write_settings(w, gs.settings, version)
    m = gs.map
    assert m is not None
    w.u16(m.width)
    w.u16(m.height)
    tiles = sorted(m.tiles, key=lambda t: (t.coordinates.y, t.coordinates.x))
    if len(tiles) != m.width * m.height:
        raise ValueError("tile count does not match width*height")
    for t in tiles:
        _write_tile(w, t, version)
    w.u16(len(gs.player_states))
    for p in gs.player_states:
        _write_player(w, p, version)
    w.u16(len(gs.pending_command_triggers))
    for t in gs.pending_command_triggers:
        _write_trigger(w, t, version)
    w.u16(len(gs.command_stack))
    for c in gs.command_stack:
        _write_command(w, c, version)
    w.u16(len(gs.action_stack))
    for a in gs.action_stack:
        _write_action(w, a, version)
    if version >= 0x62:
        w.bool(gs.has_flagged_need_for_update_routes)
    if version >= 0x7A:
        w.i32(gs.village_name_seed)


def serialize_api_blob(gs: GameState) -> bytes:
    """API / ``currentGameStateData`` bytes: outer version + ``Serialize``."""
    w = BinaryWriter()
    w.i32(int(gs.version))
    write_game_state_serialize(w, gs)
    return w.dumps()


def serialize_local_game_data(
    initial: GameState,
    current: GameState,
    last_seen_command: int = 0,
) -> bytes:
    """Uncompressed payload written by ``ToLZ4CompressedByteArray<LocalGameData>``."""
    version = int(current.version)
    w = BinaryWriter()
    w.i32(version)
    write_game_state_serialize(w, initial)
    write_game_state_serialize(w, current)
    w.u16(last_seen_command)
    return w.dumps()


def lz4_pickle(src: bytes) -> bytes:
    """K4os ``LZ4Pickler.Pickle`` V0 compressed header."""
    import lz4.block

    enc = lz4.block.compress(src, store_size=False)
    diff = len(src) - len(enc)
    # Size field is signed (see lz4_unpickle). Unsigned 255/65535 overflow.
    if diff <= 0:
        return bytes([0]) + src
    if diff <= 127:
        n = 1
    elif diff <= 32767:
        n = 2
    elif diff <= 0x7FFFFFFF:
        n = 4
    else:
        return bytes([0]) + src
    encode_size_of = 3 if n == 4 else n
    flags = (encode_size_of & 3) << 6
    return bytes([flags]) + int(diff).to_bytes(n, "little", signed=True) + enc


def lz4_unpickle(data: bytes) -> bytes:
    """Inverse of ``lz4_pickle`` / K4os Unpickle V0."""
    import lz4.block

    flags = data[0]
    version = flags & 7
    if version != 0:
        raise ValueError(f"unsupported pickle version {version}")
    size_code = (flags >> 6) & 3
    n = {0: 0, 1: 1, 2: 2, 3: 4}[size_code]
    # Header 0 = uncompressed (K4os EncodeUncompressedHeaderV0).
    if n == 0:
        return data[1:]
    diff = int.from_bytes(data[1 : 1 + n], "little", signed=True)
    payload = data[1 + n :]
    source_len = len(payload) + diff
    return lz4.block.decompress(payload, uncompressed_size=source_len)


def serialize_hotseat_game_data(
    initial: GameState,
    current: GameState,
    last_turn: GameState,
    last_seen_commands: List[int],
) -> bytes:
    """Uncompressed ``ToLZ4CompressedByteArray<HotseatGameData>`` payload.

    ``lastSeenCommands`` is a ``ushort[]`` written as ``ushort count`` then values
    (verified against a live Pass & Play ``.state``).
    """
    version = int(current.version)
    w = BinaryWriter()
    w.i32(version)
    write_game_state_serialize(w, initial)
    write_game_state_serialize(w, current)
    write_game_state_serialize(w, last_turn)
    cmds = list(last_seen_commands)
    w.u16(len(cmds))
    for x in cmds:
        w.u16(int(x) & 0xFFFF)
    return w.dumps()


def write_state_file(
    path: Path,
    initial: GameState,
    current: Optional[GameState] = None,
    last_seen_command: int = 0,
) -> None:
    raw = serialize_local_game_data(
        initial, current if current is not None else initial, last_seen_command
    )
    path.write_bytes(lz4_pickle(raw))


def write_hotseat_state_file(
    path: Path,
    initial: GameState,
    current: GameState,
    last_turn: Optional[GameState] = None,
    last_seen_commands: Optional[List[int]] = None,
) -> None:
    raw = serialize_hotseat_game_data(
        initial,
        current,
        last_turn if last_turn is not None else initial,
        last_seen_commands if last_seen_commands is not None else [1, 0, 0],
    )
    path.write_bytes(lz4_pickle(raw))


def _take_gs(raw: bytes, at: int) -> tuple[GameState, int]:
    version = struct.unpack_from("<i", raw, at)[0]
    rest = raw[at:]
    try:
        gs = deserialize(struct.pack("<i", version) + rest)
        return gs, len(rest)
    except ValueError as e:
        msg = str(e)
        if "trailing" not in msg:
            raise
        ntrail = int(msg.split()[1])
        used = len(rest) - ntrail
        gs = deserialize(struct.pack("<i", version) + rest[:used])
        return gs, used


def parse_local_payload(raw: bytes) -> tuple[GameState, GameState, int]:
    """Parse uncompressed LocalGameData bytes."""
    pos = 4
    gs1, n1 = _take_gs(raw, pos)
    pos += n1
    gs2, n2 = _take_gs(raw, pos)
    pos += n2
    last_seen = struct.unpack_from("<H", raw, pos)[0]
    return gs1, gs2, last_seen


def parse_hotseat_payload(
    raw: bytes,
) -> tuple[GameState, GameState, GameState, List[int]]:
    """Parse uncompressed HotseatGameData bytes."""
    pos = 4
    gs1, n1 = _take_gs(raw, pos)
    pos += n1
    gs2, n2 = _take_gs(raw, pos)
    pos += n2
    gs3, n3 = _take_gs(raw, pos)
    pos += n3
    n_cmds = struct.unpack_from("<H", raw, pos)[0]
    pos += 2
    last_seen = list(struct.unpack_from("<" + "H" * n_cmds, raw, pos))
    return gs1, gs2, gs3, last_seen
