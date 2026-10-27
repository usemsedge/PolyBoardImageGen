"""GameState model: dump.cs enums, dataclasses, and tribe colours."""
from __future__ import annotations

from enum import IntEnum
import json
from dataclasses import dataclass, field
from typing import Any, ClassVar, Dict, List, Optional, Tuple

from enum import IntEnum


class Terrain(IntEnum):
    NONE = 0; WATER = 1; OCEAN = 2; FIELD = 3; MOUNTAIN = 4
    FOREST = 5; ICE = 6; WETLAND = 7; MANGROVE = 8


class Resource(IntEnum):
    NONE = 0; GAME = 1; CROP = 2; FISH = 3; WHALE = 4
    METAL = 5; FRUIT = 6; SPORES = 7; STARFISH = 8; AQUACROP = 9


class Improvement(IntEnum):
    NONE = 0; CITY = 1; RUIN = 2; ROAD = 3; CUSTOMS_HOUSE = 4; FARM = 5
    WINDMILL = 6; FISHING = 7; PORT = 8; HUNTING = 9; CLEAR_FOREST = 10
    BURN_FOREST = 11; LUMBER_HUT = 12; SAWMILL = 13; GROW_FOREST = 14
    HARVEST_FRUIT = 15; WHALE_HUNTING = 16; TEMPLE = 17; FOREST_TEMPLE = 18
    WATER_TEMPLE = 19; MOUNTAIN_TEMPLE = 20; MINE = 21; FORGE = 22
    MONUMENT1 = 23; MONUMENT2 = 24; MONUMENT3 = 25; MONUMENT4 = 26
    MONUMENT5 = 27; MONUMENT6 = 28; MONUMENT7 = 29; ENCHANT_ANIMAL = 30
    ENCHANT_WHALE = 31; SANCTUARY = 32; OUTPOST = 33; ICE_BANK = 34
    ICE_TEMPLE = 35; POLARIS_CLIMATE = 36; FUNGI = 37; ALGAE = 38
    MYCELIUM = 39; BURN_SPORES = 40; CLATHRUS = 41; HIDDEN_SANCTUARY = 42
    HARVEST_SPORES = 43; NULL_BUILDING = 44; CULTIVATE = 45; STAR_FISHING = 46
    LIGHTHOUSE = 47; BRIDGE = 48; AQUAFARM = 49; MARKET = 50; ATOLL = 51
    CANAL = 52; FERTILIZE = 53; LANDFILL = 54; ALGAE_SPAWN = 55


class Unit(IntEnum):
    NONE = 0; SCOUT = 1; WARRIOR = 2; RIDER = 3; KNIGHT = 4; DEFENDER = 5
    SHIP = 6; BATTLESHIP = 7; CATAPULT = 8; ARCHER = 9; MINDBENDER = 10
    SWORDSMAN = 11; GIANT = 12; BUNNY = 13; BOAT = 14; POLYTAUR = 15
    NAVALON = 16; DRAGON_EGG = 17; BABY_DRAGON = 18; FIRE_DRAGON = 19
    AMPHIBIAN = 20; TRIDENTION = 21; MOONI = 22; BATTLE_SLED = 23
    ICE_FORTRESS = 24; ICE_ARCHER = 25; CRAB = 26; GAAMI = 27; HEXAPOD = 28
    DOOMUX = 29; PHYCHI = 30; KITON = 31; EXIDA = 32; CENTIPEDE = 33
    SEGMENT = 34; RAYCHI = 35; SHAMAN = 36; DAGGER = 37; CLOAK = 38
    CLOAK_BOAT = 39; PIRATE = 40; BOMBERSHIP = 41; SCOUTSHIP = 42
    TRANSPORTSHIP = 43; RAMMERSHIP = 44; JUGGERNAUT = 45; MERMAID_WARRIOR = 46
    MERMAID_ARCHER = 47; MERMAID_SWORDSMAN = 48; MERMAID_DEFENDER = 49
    MERMAID_CLOAK = 50; MERMAID_DAGGER = 51; JELLY = 52; SHARK = 53
    SIREN = 54; AQUAPULT = 55; BOOMCHI = 56; ISLAND = 57; CIRU = 58
    MANTIS = 59; BUG_EGG = 60; MOTH = 61; LARVA = 62

# Tribe IDs are mostly alphabetical now
# GameState climate uses tribetype
# Original Tribe IDs (legacy tribe order) is the same order as they are in the tribe choosing menu

class Tribe(IntEnum):
    NONE = 0; NATURE = 1; AIMO = 2; AQUARION = 3; BARDUR = 4; ELYRION = 5
    HOODRICK = 6; IMPERIUS = 7; KICKOO = 8; LUXIDOOR = 9; OUMAJI = 10
    QUETZALI = 11; VENGIR = 12; XINXI = 13; YADAKK = 14; ZEBASI = 15
    POLARIS = 16; CYMANTI = 17

# GameLogicData.legacyTribeTypesOrder — index is the serialized TileData.climate
# "style", value is TribeType. Nature/None are not unique slots (they share
# Bardur's index 3). Engine: GetTribeTypeFromLegacyIndex (0x6E817C).
LEGACY_TRIBE_ORDER = (
    Tribe.NONE,      # 0
    Tribe.XINXI,     # 1
    Tribe.IMPERIUS,  # 2
    Tribe.BARDUR,    # 3
    Tribe.OUMAJI,    # 4
    Tribe.KICKOO,    # 5
    Tribe.HOODRICK,  # 6
    Tribe.LUXIDOOR,  # 7
    Tribe.VENGIR,    # 8
    Tribe.ZEBASI,    # 9
    Tribe.AIMO,      # 10
    Tribe.AQUARION,  # 11
    Tribe.QUETZALI,  # 12
    Tribe.ELYRION,   # 13
    Tribe.YADAKK,    # 14
    Tribe.POLARIS,   # 15
    Tribe.CYMANTI,   # 16
)


def GetTribeTypeFromLegacyIndex(style: int) -> int:
    """GameLogicData.GetTribeTypeFromLegacyIndex(int style).

    Negative styles clamp to 0; indexes past the last entry clamp to Cymanti.
    """
    idx = int(style)
    if idx < 0:
        idx = 0
    last = len(LEGACY_TRIBE_ORDER) - 1
    if idx > last:
        idx = last
    return int(LEGACY_TRIBE_ORDER[idx])


class Skin(IntEnum):
    NONE = -1; DEFAULT = 0; RANGER = 1; NINJA = 2; BAERION = 3; SCHOLAR = 5
    MERCENARY = 7; SFINX = 8; SKELETON = 9; ARTY = 10; PIRATE = 11; AIBO = 12
    URKAZ = 13; IKARUS = 14; DARKELF = 15; SWAMP = 17; MAGMA = 18; CUTE = 19


class MapPreset(IntEnum):
    """dump.cs MapPreset (TypeDef 12153)."""
    NONE = 0; DRYLAND = 1; LAKES = 2; CONTINENTS = 3
    ARCHIPELAGO = 4; WATER_WORLD = 5; PANGEA = 6


class MapSize(IntEnum):
    """dump.cs MapSize (TypeDef 12155). Widths via MapSizeExtensions."""
    NONE = 0; TINY = 1; SMALL = 2; NORMAL = 3; LARGE = 4; HUGE = 5; MASSIVE = 6


# MapSizeExtensions constants (dump.cs 832027–832036).
MAP_SIZE_WIDTH = {
    MapSize.NONE: 0,
    MapSize.TINY: 11,
    MapSize.SMALL: 14,
    MapSize.NORMAL: 16,
    MapSize.LARGE: 18,
    MapSize.HUGE: 20,
    MapSize.MASSIVE: 30,
}
MAP_SIZE_MIN = 11
MAP_SIZE_MAX = 30


class TileEffect(IntEnum):
    NONE = 0; FLOODED = 1; SWAMPED = 2; TENTACLE = 3; ALGAE = 4; FOAM = 5


class CityReward(IntEnum):
    NONE = 0; CITY_WALL = 1; PARK = 2; WORKSHOP = 3; EXPLORER = 4
    BORDER_GROWTH = 5; SUPER_UNIT = 6; RESOURCES = 7; POPULATION_GROWTH = 8
    REBELLION = 11; POISON = 13; TUTORIAL_EXPLORER = 100


class ImprovementEffect(IntEnum):
    DECOMPOSING = 0; ROBBED = 1


class UnitEffect(IntEnum):
    FROZEN = 0; POISONED = 1; BOOSTED = 2; INVISIBLE = 3; BUBBLE = 4
    PETRIFIED = 5; SWIFT = 6; DOUBLE_READY = 7; CHARMED = 8


class GridDirection(IntEnum):
    SW = 0; W = 1; NW = 2; N = 3; NE = 4; E = 5; SE = 6; S = 7; NONE = 8


class CommandType(IntEnum):
    """dump.cs CommandType (TypeDef 10554). Gaps are unused in this build."""
    NONE = 0; BUILD = 1; ATTACK = 2; RECOVER = 3; HEAL_OTHERS = 4
    TRAIN = 5; MOVE = 6; CAPTURE = 7; RESEARCH = 8; DESTROY = 9
    DISBAND = 10; CITY_REWARD = 11; PROMOTE = 13; EXAMINE_RUINS = 14
    END_TURN = 15; UPGRADE = 16; FREEZE_AREA = 17; BREAK_ICE = 18
    SELECT_TRIBE = 19; START_MATCH = 20; STAY = 21; END_MATCH = 22
    HARVEST = 23; EXPLODE = 24; BOOST = 25; DECOMPOSE = 26
    PEACE_TREATY = 27; PEACE_REQUEST_RESPONSE = 28; BREAK_PEACE = 29
    ESTABLISH_EMBASSY = 30; DESTROY_EMBASSY = 32; HIDE = 33; RESIGN = 35
    DISEMBARK = 36; FLOOD = 37; SWARM = 38; CLEAR_TILE_EFFECT = 39


class ActionType(IntEnum):
    """dump.cs ActionType (TypeDef 10517). Gaps are unused in this build."""
    NONE = 0; BUILD = 1; ATTACK = 2; RECOVER = 3; HEAL_OTHERS = 4
    TRAIN = 5; MOVE = 6; RULE_AREA = 7; RESEARCH = 8
    DESTROY_IMPROVEMENT = 9; DISBAND_UNIT = 10; CITY_REWARD = 11
    MEET = 12; PROMOTE = 13; EXAMINE_RUINS = 14; END_TURN = 15
    UPGRADE = 16; FREEZE_AREA = 17; BREAK_ICE = 18; BUILD_ROAD = 19
    CAPTURE_CITY = 20; CITY_LEVEL_UP = 21; UPDATE_ROUTES = 22
    KILL_UNIT = 23; MODIFY_PRODUCTION = 24; EXPLORE = 25
    INCREASE_POPULATION = 26; INCREASE_SCORE = 27; INCREASE_CURRENCY = 28
    START_TURN = 29; SCOUT_MOVE = 30; UPDATE_CITY_CONNECTIONS = 31
    DECREASE_POPULATION = 32; EMBARK = 34; DISEMBARK = 35
    SELECT_TRIBE = 36; GAME_OVER = 37; HEAL = 38; START_MATCH = 39
    IMPROVEMENT_LEVEL_UP = 40; IMPROVEMENT_LEVEL_DOWN = 41; CONVERT = 42
    FREEZE_UNIT = 43; ENABLE_TASK = 44; TASK_COMPLETED = 45
    FREEZE_TILE = 46; CLIMATE_CHANGE = 47; RESELECT = 48
    WIPE_PLAYER = 49; CREATE_RESOURCE = 50; DESTROY_RESOURCE = 51
    MODIFY_SCORE = 52; PASS_PLAYER = 53; CONNECT_CITY = 54
    DISCONNECT_CITY = 55; CHANGE_CITY_CONNECTION = 56; BREAK_ICE_AREA = 57
    EXPAND_CITY = 58; DECREASE_SCORE = 59; END_MATCH = 60
    WIPE_PLAYER_END = 61; END_COMMAND = 62; POISON = 63; EAT = 64
    HARVEST_IMPROVEMENT = 66; BOOST = 68; BOOST_OTHERS = 69
    EXPLODE = 70; DECOMPOSE = 71; RECEIVE_DIPLOMACY_MESSAGE = 72
    PEACE_REQUEST_RESPONSE = 73; PEACE_TREATY = 74; BREAK_PEACE = 75
    ESTABLISH_EMBASSY = 76; REVEAL_CAPITAL = 77; DESTROY_EMBASSY = 79
    HIDE = 80; REVEAL = 81; INFILTRATE = 82; INFILTRATION_REWARD = 83
    RESIGN = 84; RUN_DEFERRED = 85; BUBBLE = 86; FLOOD_TILE = 87
    CLEAR_EFFECT = 88


class CommandTriggerType(IntEnum):
    """dump.cs CommandTriggerType (TypeDef 10609)."""
    NONE = 0; CITY_LEVEL_UP = 1; PEACE_REQUEST = 2


# Sub-layer sort offsets (recon/draworder_color.md §2; MapRenderer constants).
# Within one tile: sortingOrder = rowDepth + offset (0..99 band).
SORT_BORDERS_BACK = 0
SORT_TERRAIN = 1
SORT_TRANSPORT = 2
SORT_TERRAIN_FEATURE = 3
SORT_RESOURCE_OUTLINE = 4
SORT_RESOURCE = 5
SORT_HOUSES = 6
SORT_WALLS = 97
SORT_BUILDINGS = 98
SORT_BORDERS_FRONT = 99

# Unity Sorting Layers above the world tile stack (TagManager order):
#   Units → CityStatusDisplays/Text → UnitStatusDisplays/Text
# Flattened into sublayer ints so a single ascending sort matches layer order.
SORT_UNIT = 100                 # Units sorting layer
SORT_UNIT_CONNECTOR = 98        # Centipede SegmentConnector (under units)
SORT_CITY_STATUS = 110          # CityStatusDisplays + CityStatusText
SORT_UNIT_STATUS = 120          # UnitStatusDisplays + UnitStatusText


# Tribe value -> lowercase theme suffix (recon/asset_map.json tribe_theme).
# Renderer GameState climate is a TribeType. Serialized TileData.climate is a
# legacy index; map it with GetTribeTypeFromLegacyIndex before theming.
TRIBE_THEME = {
    Tribe.NATURE: "nature", Tribe.AIMO: "aimo", Tribe.AQUARION: "aquarion",
    Tribe.BARDUR: "bardur", Tribe.ELYRION: "elyrion", Tribe.HOODRICK: "hoodrick",
    Tribe.IMPERIUS: "imperius", Tribe.KICKOO: "kickoo", Tribe.LUXIDOOR: "luxidoor",
    Tribe.OUMAJI: "oumaji", Tribe.QUETZALI: "quetzali", Tribe.VENGIR: "vengir",
    Tribe.XINXI: "xinxi", Tribe.YADAKK: "yadakk", Tribe.ZEBASI: "zebasi",
    Tribe.POLARIS: "polaris", Tribe.CYMANTI: "cymanti",
}

SKIN_THEME = {
    Skin.RANGER: "ranger", Skin.NINJA: "ninja", Skin.BAERION: "baerion",
    Skin.SCHOLAR: "scholar", Skin.MERCENARY: "mercenary", Skin.SFINX: "sfinx",
    Skin.SKELETON: "skeleton", Skin.ARTY: "arty", Skin.PIRATE: "pirate",
    Skin.AIBO: "aibo", Skin.URKAZ: "urkaz", Skin.IKARUS: "ikarus",
    Skin.DARKELF: "darkelf", Skin.SWAMP: "swamp", Skin.MAGMA: "magma",
    Skin.CUTE: "cute",
}

# style index -> TribeType (same table as LEGACY_TRIBE_ORDER, skipping 0).
CLIMATE_STYLE_TO_TRIBE = {
    i: t for i, t in enumerate(LEGACY_TRIBE_ORDER) if i > 0
}


def tribe_from_climate_style(climate: int) -> int:
    """Map a serialized climate style to TribeType. 0 stays unset."""
    if not climate:
        return 0
    return GetTribeTypeFromLegacyIndex(climate)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Shared value types
# ---------------------------------------------------------------------------

@dataclass
class WorldCoordinates:
    """dump.cs ``struct WorldCoordinates`` (TypeDef 10710)."""
    x: int = 0                             # C#: int x
    y: int = 0                             # C#: int y


@dataclass
class Shoreline:
    """dump.cs ``class TileData.Shoreline`` (TypeDef 10585)."""
    visible: bool = False                   # C#: bool visible
    sprite_ext: str = ""                   # C#: string spriteExt  ("" or "_swamp")


@dataclass
class Shorelines:
    """dump.cs ``class TileData.Shorelines`` (TypeDef 10586)."""
    any: bool = False                       # C#: bool any
    N: Shoreline = field(default_factory=Shoreline)  # C#: TileData.Shoreline N
    S: Shoreline = field(default_factory=Shoreline)  # C#: TileData.Shoreline S
    E: Shoreline = field(default_factory=Shoreline)  # C#: TileData.Shoreline E
    W: Shoreline = field(default_factory=Shoreline)  # C#: TileData.Shoreline W


@dataclass
class ResourceState:
    """dump.cs ``class ResourceState`` (TypeDef 10631)."""
    type: int                               # C#: ResourceData.Type type


@dataclass
class ImprovementState:
    """dump.cs ``class ImprovementState`` (TypeDef 10628)."""
    type: int                               # C#: ImprovementData.Type type
    owner: int = 0                          # C#: byte owner  (obsolete; tile.owner is authoritative)
    founder: int = 0                       # C#: byte founder
    level: int = 1                         # C#: ushort level
    founded: int = 0                       # C#: ushort founded
    xp: int = 0                            # C#: short xp
    population: int = 0                    # C#: short population
    production: int = 0                    # C#: ushort production
    base_score: int = 0                    # C#: ushort baseScore
    border_size: int = 0                    # C#: ushort borderSize
    upgrade: int = 0                       # C#: ushort upgrade
    connected_to_capital_of_player: int = 0  # C#: byte connectedToCapitalOfPlayer
    name: str = ""                         # C#: string name
    rewards: List[int] = field(default_factory=list)   # C#: List<CityReward> rewards
    effects: List[int] = field(default_factory=list)   # C#: List<ImprovementEffect> effects
    # Renderer-only (not in dump). Ordered player ids who discovered this
    # LightHouse (tower drums). Empty = fall back to built_unique_improvements.
    discovered_by: List[int] = field(default_factory=list)

    def has_reward(self, reward: int) -> bool:
        """ImprovementDataExtensions.HasReward."""
        return reward in self.rewards

    def reward_count(self, reward: int) -> int:
        """ImprovementDataExtensions.RewardCount."""
        return sum(1 for r in self.rewards if r == reward)


@dataclass
class UnitState:
    """dump.cs ``class UnitState`` (TypeDef 10633)."""
    id: int = 0                            # C#: uint id
    leader: int = 0                        # C#: uint leader
    follower: int = 0                      # C#: uint follower
    owner: int = 0                         # C#: byte owner
    birth_climate: int = 0                # C#: TribeType birthClimate
    birth_climate_skin_type: int = 0      # C#: SkinType birthClimateSkinType
    type: int = 0                          # C#: UnitData.Type type
    previous_turn_end_coordinates: WorldCoordinates = field(
        default_factory=WorldCoordinates)     # C#: WorldCoordinates previousTurnEndCoordinates
    coordinates: WorldCoordinates = field(default_factory=WorldCoordinates)  # C#: WorldCoordinates coordinates
    home: WorldCoordinates = field(default_factory=WorldCoordinates)  # C#: WorldCoordinates home
    passenger_unit: Optional["UnitState"] = None  # C#: UnitState passengerUnit
    health: int = 100                      # C#: ushort health  (tenths; display HP = ceil(health/10))
    promotion_level: int = 0              # C#: ushort promotionLevel
    xp: int = 0                            # C#: ushort xp
    moved: bool = False                    # C#: bool moved
    attacked: bool = False                  # C#: bool attacked
    direction: int = 8                    # C#: GridDirection direction  (NONE=8)
    flipped: bool = False                   # C#: bool flipped
    created_turn: int = 0                 # C#: ushort createdTurn
    unit_data: Any = None                   # C#: UnitData UnitData  (not modeled)
    effects: List[int] = field(default_factory=list)  # C#: List<UnitEffect> effects
    is_temporary_explorer_unit: bool = False  # C#: bool isTemporaryExplorerUnit

    # Ergonomic aliases for the embedded WorldCoordinates (not extra C fields).
    @property
    def x(self) -> int:
        return self.coordinates.x

    @property
    def y(self) -> int:
        return self.coordinates.y


@dataclass
class WorldContinent:
    """dump.cs ``class WorldContinent`` (TypeDef 10709)."""
    tiles: List[WorldCoordinates] = field(default_factory=list)  # C#: List<WorldCoordinates> tiles
    climate: int = 0                       # C#: TribeType climate
    skin_type: int = 0                     # C#: SkinType skinType
    crop: float = 0.0                      # C#: float crop
    fish: float = 0.0                      # C#: float fish
    fruit: float = 0.0                     # C#: float fruit
    game: float = 0.0                      # C#: float game
    metal: float = 0.0                     # C#: float metal
    whale: float = 0.0                     # C#: float whale
    spores: float = 0.0                    # C#: float spores
    aquacrop: float = 0.0                  # C#: float aquacrop
    water: float = 0.0                     # C#: float water
    ocean: float = 0.0                     # C#: float ocean
    field: float = 0.0                     # C#: float field
    mountain: float = 0.0                  # C#: float mountain
    forest: float = 0.0                    # C#: float forest
    ice: float = 0.0                       # C#: float ice
    has_alien_climate: bool = False         # C#: bool hasAlienClimate
    land_tile_count: int = 0               # C#: int LandTileCount
    number_of_capitals: int = 0            # C#: int NumberOfCapitals
    max_size: int = 0                      # C#: int MaxSize


@dataclass
class TileData:
    """dump.cs ``class TileData`` (TypeDef 10588)."""
    coordinates: WorldCoordinates            # C#: WorldCoordinates coordinates
    terrain: int                            # C#: TerrainData.Type terrain
    climate: int = 0                       # C#: TribeType climate  (in-memory; save file is legacy index)
    skin: int = 0                          # C#: SkinType _skin
    effects: List[int] = field(default_factory=list)  # C#: List<TileData.EffectType> effects
    altitude: int = 0                      # C#: int altitude
    owner: int = 0                         # C#: byte owner
    capital_of: int = 0                    # C#: byte capitalOf
    explorers: List[int] = field(default_factory=list)  # C#: List<byte> explorers
    shorelines: Shorelines = field(default_factory=Shorelines)  # C#: TileData.Shorelines shorelines
    ruling_city_coordinates: WorldCoordinates = field(
        default_factory=lambda: WorldCoordinates(-1, -1))  # C#: WorldCoordinates rulingCityCoordinates
    improvement: Optional[ImprovementState] = None  # C#: ImprovementState improvement
    resource: Optional[ResourceState] = None  # C#: ResourceState resource
    unit: Optional[UnitState] = None        # C#: UnitState unit
    has_road: bool = False                   # C#: bool hasRoad
    has_route: bool = False                  # C#: bool hasRoute
    continent: Optional[WorldContinent] = None  # C#: WorldContinent continent
    had_route: bool = False                  # C#: bool hadRoute
    upgrade_tech: Dict[int, float] = field(default_factory=dict)  # C#: Dictionary<TechData.Type, float> upgradeTech
    last_population_check: int = 0         # C#: long lastPopulationCheck
    available_population: int = 0         # C#: int availablePopulation

    @property
    def x(self) -> int:
        return self.coordinates.x

    @property
    def y(self) -> int:
        return self.coordinates.y

    def is_owner_capital(self) -> bool:
        """True when this is the current owner's own capital, not a captured one.

        ``capital_of`` is the founding player and stays set after capture; the
        crown/icon only belongs to that player while they still own the tile.
        """
        cap = int(self.capital_of or 0)
        return cap != 0 and cap == int(self.owner or 0)


@dataclass
class PlayerState:
    """dump.cs ``class PlayerState`` (TypeDef 10630)."""
    NO_PLAYER_ID: ClassVar[int] = 0        # C#: const byte NO_PLAYER_ID
    NATURE_PLAYER_ID: ClassVar[int] = 255  # C#: const byte NATURE_PLAYER_ID

    id: int = 0                            # C#: byte Id
    user_name: str = ""                    # C#: string UserName
    account_id: Any = None                  # C#: Nullable<Guid> AccountId
    auto_play: bool = False                 # C#: bool AutoPlay
    start_tile: WorldCoordinates = field(default_factory=WorldCoordinates)  # C#: WorldCoordinates startTile
    tribe: int = 0                         # C#: TribeType tribe
    tribe_mix: int = 0                     # C#: TribeType tribeMix
    climate: int = 0                      # C#: TribeType _climate
    has_chosen_tribe: bool = False          # C#: bool hasChosenTribe
    handicap: int = 0                     # C#: int handicap
    resigned_turn: int = 0                # C#: int resignedTurn
    resigned_at_command_index: int = 0      # C#: int resignedAtCommandIndex
    wiped_at_command_index: int = 0        # C#: int wipedAtCommandIndex
    available_tech: List[int] = field(default_factory=list)  # C#: List<TechData.Type> availableTech
    tasks: List[Any] = field(default_factory=list)  # C#: List<TaskBase> tasks
    aggressions: Dict[int, int] = field(default_factory=dict)  # C#: Dictionary<byte, int> aggressions
    known_players: List[int] = field(default_factory=list)  # C#: List<byte> knownPlayers
    built_unique_improvements: List[int] = field(default_factory=list)  # C#: List<ImprovementData.Type> builtUniqueImprovements
    relations: Dict[int, Any] = field(default_factory=dict)  # C#: Dictionary<byte, DiplomacyRelation> relations
    messages: List[Any] = field(default_factory=list)  # C#: List<DiplomacyMessage> messages
    skin_type: int = 0                     # C#: SkinType skinType
    currency: int = 0                     # C#: int currency
    score: int = 0                         # C#: uint score
    end_score: int = 0                     # C#: uint endScore
    cities: int = 0                        # C#: int cities
    kills: int = 0                         # C#: uint kills
    casualities: int = 0                   # C#: uint casualities
    wipe_outs: int = 0                     # C#: uint wipeOuts
    killer_id: int = 0                     # C#: byte killerId
    killed_turn: int = 0                   # C#: uint killedTurn
    color: int = 0                         # C#: int color
    ai_state: Any = None                    # C#: AIState aiState
    unlocked_tech_cache: List[Any] = field(default_factory=list)  # C#: List<TechData> unlockedTechCache
    block_train_units: bool = False          # C#: bool blockTrainUnits
    capital_count_cache: int = 0          # C#: int capitalCountCache
    opinions: Any = None                   # C#: OpinionManager opinions


@dataclass
class MapData:
    """dump.cs ``class MapData`` (TypeDef 10577)."""
    width: int                             # C#: ushort width
    height: int                            # C#: ushort height
    tiles: List[TileData]                  # C#: TileData[] tiles
    continents: List[WorldContinent] = field(default_factory=list)  # C#: WorldContinent[] continents

    def tile_at(self, x: int, y: int) -> Optional[TileData]:
        if 0 <= x < self.width and 0 <= y < self.height:
            return self.tiles[y * self.width + x]
        return None


@dataclass
class GameSettings:
    """dump.cs ``sealed class GameSettings`` (TypeDef 10606) — mapgen subset."""
    map_preset: int = 0                    # C#: MapPreset mapPreset
    map_size: int = 0                      # C#: int MapSize  (enum or raw width when > 6)
    game_name: str = ""                     # C#: string GameName
    game_type: int = 0                     # C#: GameType GameType
    opponent_count: int = 0                # C#: int OpponentCount
    disabled_tribes: List[int] = field(default_factory=list)  # C#: List<TribeType> disabledTribes
    west_map_placement_user_id: Any = None   # C#: Nullable<Guid> WestMapPlacementUserId
    # Fields required to round-trip BinaryWriter GameSettings (not used by the renderer).
    wire: Dict[str, Any] = field(default_factory=dict)

    def GetMapGeneratorSettings(self):
        """GameSettings.GetMapGeneratorSettings → CreateFromPreset(mapPreset)."""
        # Lazy import: mapgenerator.settings imports gamestate types.
        from mapgenerator.settings import MapGeneratorSettings
        return MapGeneratorSettings.CreateFromPreset(self.map_preset)

    def map_width(self) -> int:
        """Resolve MapSize enum or raw width to tile count (square maps)."""
        ms = int(self.map_size)
        if 0 < ms <= int(MapSize.MASSIVE):
            w = MAP_SIZE_WIDTH.get(MapSize(ms), 0)
            if w:
                return w
        if MAP_SIZE_MIN <= ms <= MAP_SIZE_MAX:
            return ms
        return MAP_SIZE_WIDTH[MapSize.NORMAL]


@dataclass
class CommandTrigger:
    """dump.cs ``struct CommandTrigger`` (TypeDef 10610)."""
    player_id: int = 0                      # C#: byte playerId
    opponent_id: int = 0                    # C#: byte opponentId
    type: int = 0                          # C#: CommandTriggerType type
    coordinates: WorldCoordinates = field(default_factory=WorldCoordinates)  # C#: WorldCoordinates coordinates


@dataclass
class CommandRecord:
    """One ``GameState.CommandStack`` entry: ``CommandType`` ushort + ``CommandBase`` body."""
    type: int                              # C#: CommandType  (ushort on the wire)
    player_id: int = 0                     # C#: from CommandBase.playerId (byte)
    fields: Dict[str, Any] = field(default_factory=dict)  # flattened CommandBase subclass fields


@dataclass
class ActionRecord:
    """One ``GameState.ActionStack`` entry: ``ActionType`` ushort + ``ActionBase`` body."""
    type: int                              # C#: ActionType  (ushort on the wire)
    player_id: int = 0                     # C#: from ActionBase.playerId (byte)
    fields: Dict[str, Any] = field(default_factory=dict)  # flattened ActionBase subclass fields


@dataclass
class GameState:
    """dump.cs ``class GameState`` (TypeDef 10622)."""
    # GameState.State: Unknown=0 Lobby=1 Started=2 FinalTurn=3 Ended=4
    version: int = 0                       # C#: int Version
    seed: int = 0                          # C#: int Seed
    village_name_seed: int = 0            # C#: int VillageNameSeed
    current_turn: int = 0                 # C#: uint CurrentTurn
    current_player_index: int = 0         # C#: byte CurrentPlayerIndex
    current_unit_id: int = 0              # C#: uint CurrentUnitId
    current_state: int = 0                # C#: GameState.State CurrentState
    settings: Optional[GameSettings] = None  # C#: GameSettings Settings
    map: Optional[MapData] = None           # C#: MapData Map
    player_states: List[PlayerState] = field(default_factory=list)  # C#: List<PlayerState> PlayerStates
    current_command: int = 0              # C#: ushort CurrentCommand
    command_stack: List[CommandRecord] = field(default_factory=list)  # C#: List<CommandBase> CommandStack
    action_stack: List[ActionRecord] = field(default_factory=list)  # C#: List<ActionBase> ActionStack
    pending_command_triggers: List[CommandTrigger] = field(default_factory=list)  # C#: List<CommandTrigger> pendingCommandTriggers
    has_flagged_need_for_update_routes: bool = False  # C#: bool HasFlaggedNeedForUpdateRoutes
    random_hash: Any = None                 # C#: XXHash randomHash
    village_name_hash: Any = None           # C#: XXHash villageNameHash
    mocked_game_logic_data: Any = None       # C#: GameLogicData mockedGameLogicData

    def player_by_id(self, pid: int) -> Optional[PlayerState]:
        for p in self.player_states:
            if p.id == pid:
                return p
        return None

    @property
    def viewer(self) -> Optional[PlayerState]:
        if 0 <= self.current_player_index < len(self.player_states):
            return self.player_states[self.current_player_index]
        return None

    @property
    def PlayerCount(self) -> int:
        return sum(1 for p in self.player_states
                   if p.id != PlayerState.NATURE_PLAYER_ID
                   and p.id != PlayerState.NO_PLAYER_ID)


# ---------------------------------------------------------------------------
# JSON loader
# ---------------------------------------------------------------------------

def _coords(d: Optional[dict], default_x: int = 0, default_y: int = 0) -> WorldCoordinates:
    if d is None:
        return WorldCoordinates(default_x, default_y)
    return WorldCoordinates(int(d.get("x", default_x)), int(d.get("y", default_y)))


def _shoreline(d: dict) -> Shoreline:
    return Shoreline(visible=bool(d.get("visible", False)),
                     sprite_ext=d.get("sprite_ext", ""))


def _shorelines(d: Optional[dict]) -> Shorelines:
    if not d:
        return Shorelines()
    return Shorelines(
        any=bool(d.get("any", False)),
        N=_shoreline(d.get("N", {})), S=_shoreline(d.get("S", {})),
        E=_shoreline(d.get("E", {})), W=_shoreline(d.get("W", {})),
    )


def _improvement(d: Optional[dict]) -> Optional[ImprovementState]:
    if d is None:
        return None
    # Migrate legacy invented fields → rewards / connected_to_capital_of_player.
    rewards = list(d.get("rewards", []))
    if d.get("has_wall") and 1 not in rewards:          # CityReward.CityWall
        rewards.append(1)
    if d.get("has_workshop") and 3 not in rewards:      # CityReward.Workshop
        rewards.append(3)
    park_n = int(d.get("park_count", 0) or 0)
    while rewards.count(2) < park_n:                    # CityReward.Park
        rewards.append(2)
    connected = d.get("connected_to_capital_of_player",
                      d.get("connected_to_capital_of", 0))
    return ImprovementState(
        type=d["type"],
        owner=d.get("owner", 0),
        founder=d.get("founder", 0),
        level=d.get("level", 1),
        founded=d.get("founded", 0),
        xp=d.get("xp", 0),
        population=d.get("population", 0),
        production=d.get("production", 0),
        base_score=d.get("base_score", 0),
        border_size=d.get("border_size", 0),
        upgrade=d.get("upgrade", 0),
        connected_to_capital_of_player=connected,
        name=d.get("name", ""),
        rewards=rewards,
        effects=list(d.get("effects", [])),
        discovered_by=list(d.get("discovered_by", [])),
    )


def _unit(d: Optional[dict]) -> Optional[UnitState]:
    if d is None:
        return None
    coords = d.get("coordinates")
    if coords is None and ("x" in d or "y" in d):
        coords = {"x": d.get("x", 0), "y": d.get("y", 0)}
    home = d.get("home")
    # Legacy home_x / home_y
    if home is None and ("home_x" in d or "home_y" in d):
        home = {"x": d.get("home_x", 0), "y": d.get("home_y", 0)}
    passenger = d.get("passenger_unit")
    if passenger is None and d.get("passenger_type") is not None:
        passenger = {"type": d["passenger_type"]}
    skin = d.get("birth_climate_skin_type", d.get("skin_type", 0))
    return UnitState(
        id=d.get("id", 0),
        leader=d.get("leader", 0),
        follower=d.get("follower", 0),
        owner=d.get("owner", 0),
        birth_climate=d.get("birth_climate", 0),
        birth_climate_skin_type=skin,
        type=d["type"],
        previous_turn_end_coordinates=_coords(d.get("previous_turn_end_coordinates")),
        coordinates=_coords(coords),
        home=_coords(home, -1, -1) if home is not None else WorldCoordinates(-1, -1),
        passenger_unit=_unit(passenger),
        health=d.get("health", 100),
        promotion_level=d.get("promotion_level", 0),
        xp=d.get("xp", 0),
        moved=bool(d.get("moved", False)),
        attacked=bool(d.get("attacked", False)),
        direction=d.get("direction", 8),
        flipped=bool(d.get("flipped", False)),
        created_turn=d.get("created_turn", 0),
        effects=list(d.get("effects", [])),
        is_temporary_explorer_unit=bool(d.get("is_temporary_explorer_unit", False)),
    )


def _resource(d: Optional[dict]) -> Optional[ResourceState]:
    if d is None:
        return None
    return ResourceState(type=d["type"])


def _tile(d: dict) -> TileData:
    coords = d.get("coordinates")
    if coords is None:
        coords = {"x": d["x"], "y": d["y"]}
    ruling = d.get("ruling_city_coordinates")
    if ruling is None and ("ruling_city_x" in d or "ruling_city_y" in d):
        ruling = {"x": d.get("ruling_city_x", -1), "y": d.get("ruling_city_y", -1)}
    capital_of = d.get("capital_of", 0)
    # Legacy: improvement.is_capital_of → tile.capital_of
    imp = d.get("improvement")
    if not capital_of and isinstance(imp, dict):
        capital_of = imp.get("is_capital_of", imp.get("capital_of", 0)) or 0
    return TileData(
        coordinates=_coords(coords),
        terrain=d["terrain"],
        climate=d.get("climate", 0),
        skin=d.get("skin", 0),
        effects=list(d.get("effects", [])),
        altitude=d.get("altitude", 0),
        owner=d.get("owner", 0),
        capital_of=capital_of,
        explorers=list(d.get("explorers", [])),
        shorelines=_shorelines(d.get("shorelines")),
        ruling_city_coordinates=_coords(ruling, -1, -1),
        improvement=_improvement(d.get("improvement")),
        resource=_resource(d.get("resource")),
        unit=_unit(d.get("unit")),
        has_road=bool(d.get("has_road", False)),
        has_route=bool(d.get("has_route", False)),
        had_route=bool(d.get("had_route", False)),
        upgrade_tech={int(k): float(v) for k, v in (d.get("upgrade_tech") or {}).items()},
        last_population_check=d.get("last_population_check", 0),
        available_population=d.get("available_population", 0),
    )


def _player(d: dict) -> PlayerState:
    return PlayerState(
        id=d["id"],
        user_name=d.get("user_name", ""),
        auto_play=bool(d.get("auto_play", False)),
        start_tile=_coords(d.get("start_tile")),
        tribe=d["tribe"],
        tribe_mix=d.get("tribe_mix", 0),
        climate=d.get("climate", 0),
        has_chosen_tribe=bool(d.get("has_chosen_tribe", False)),
        handicap=d.get("handicap", 0),
        available_tech=list(d.get("available_tech", [])),
        known_players=list(d.get("known_players", [])),
        built_unique_improvements=list(d.get("built_unique_improvements", [])),
        skin_type=d.get("skin_type", 0),
        currency=d.get("currency", 0),
        score=d.get("score", 0),
        color=d.get("color", 0),
    )


def from_dict(d: dict) -> GameState:
    m = d["map"]
    tiles = [_tile(t) for t in m["tiles"]]
    mapdata = MapData(
        width=m["width"], height=m["height"], tiles=tiles,
        continents=[],  # not serialized in our JSON yet
    )
    # Accept legacy "players" key as alias for player_states.
    plist = d.get("player_states", d.get("players", []))

    def _trigger(t: dict) -> CommandTrigger:
        return CommandTrigger(
            player_id=int(t.get("player_id", 0)),
            opponent_id=int(t.get("opponent_id", 0)),
            type=int(t.get("type", 0)),
            coordinates=_coords(t.get("coordinates")),
        )

    def _command(c: dict) -> CommandRecord:
        return CommandRecord(
            type=int(c["type"]),
            player_id=int(c.get("player_id", 0)),
            fields=dict(c.get("fields") or {}),
        )

    def _action(a: dict) -> ActionRecord:
        return ActionRecord(
            type=int(a["type"]),
            player_id=int(a.get("player_id", 0)),
            fields=dict(a.get("fields") or {}),
        )

    return GameState(
        version=d.get("version", 0),
        seed=d.get("seed", 0),
        village_name_seed=d.get("village_name_seed", 0),
        current_turn=d.get("current_turn", 0),
        current_player_index=d.get("current_player_index", 0),
        current_unit_id=d.get("current_unit_id", 0),
        current_state=d.get("current_state", 0),
        current_command=d.get("current_command", 0),
        map=mapdata,
        player_states=[_player(p) for p in plist],
        pending_command_triggers=[
            _trigger(t) for t in d.get("pending_command_triggers", [])
        ],
        command_stack=[_command(c) for c in d.get("command_stack", [])],
        action_stack=[_action(a) for a in d.get("action_stack", [])],
        has_flagged_need_for_update_routes=bool(
            d.get("has_flagged_need_for_update_routes", False)
        ),
    )


def load(path: str) -> GameState:
    with open(path) as f:
        return from_dict(json.load(f))


# ---------------------------------------------------------------------------
# Tribe colours
# ---------------------------------------------------------------------------

TRIBE_COLOR = {
    0: 0, 1: 13816530, 2: 3596970, 3: 15958913, 4: 3482900, 5: 16711833,
    6: 10053120, 7: 255, 8: 65280, 9: 11221974, 10: 16776960, 11: 2579530,
    12: 16777215, 13: 13369344, 14: 8200988, 15: 16750848, 16: 11968901, 17: 12778752,
}
SKIN_COLOR = {17: 6786096}
WHITE = 0xFFFFFF


def get_tribe_color(tribe: int, skin: int = 0) -> int:
    sc = SKIN_COLOR.get(skin)
    if sc is not None and sc > 0:
        return sc
    tc = TRIBE_COLOR.get(tribe)
    if tc is not None:
        return tc
    return WHITE


def get_tribe_rgb(tribe: int, skin: int = 0) -> Tuple[int, int, int]:
    c = get_tribe_color(tribe, skin) & 0xFFFFFF
    return ((c >> 16) & 0xFF, (c >> 8) & 0xFF, c & 0xFF)
