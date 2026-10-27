# Replay capture specification

**Capture contract.** See [README.md](README.md) for setup, workflow, migration, build instructions, and ML tooling. Native rendering edge cases require in-game verification.

## Settings

Read `settings.json` beside the installed mod. Missing/invalid settings stop the run. Relative CSV paths start at that directory; absolute paths are allowed. No index or legacy environment-variable configuration is required.

| Field | Rule |
| --- | --- |
| `show_grid_overlay` | Required boolean; generate red tile-boundary PNGs when true. |
| `num_iterations` | Required positive integer; maximum newly successful replays, not attempts. |
| `csv_filename` | Required nonempty path to a CSV with a `REPLAY LINK` column. |
| `target_tile_pixels` | Optional integer 32-512, default 128; requested projected tile-edge length. |

## Capture and progress

- Use ended replays' final state, with exactly two non-Nature participants; eliminated/resigned players count.
- Create four independent views: each player's normal and revealed POV. Normal preserves native fog/resource visibility; revealed removes fog and technology-based resource hiding without changing game state.
- Deduplicate UUIDs, preserve pending CSV order, and skip validated completed outputs. They do not count toward the limit.
- Log failures and continue; attempt a failed UUID once per run and retry on later runs. Log/skip ineligible entries. Stop at the success limit, cancellation, or queue exhaustion.
- Publish only a complete, validated replay, then mark CSV completion. Recover crashes without double-counting. Changes to settings affect new captures only; validate old captures against their recorded settings.
- Log/skip the entire replay for unsupported required mappings or a genuine unit head/body tribe/skin mismatch; keep it retryable. Never guess an enum or choose one conflicting unit part. Unmatched RGB is supported as `other`.

Before the first annotation-enabled run, delete old captures, reset their completion statuses/statistics, and recapture. Preserve source CSV links. This migration is one-time; editing the roadmap deletes nothing.

## Files

Root: `Maps/replay-captures/`. Each replay has a `<replay-uuid>/` directory. For each actual player ID and view (`normal` or `revealed`), write:

| File | Contents |
| --- | --- |
| `player-<id>-<view>.png` | Clean world-camera image. |
| `player-<id>-<view>.grid.json` | `size`, `width`, `height`, `anchor`, `stepX`, `stepY`, `targetTilePixels`, `sideLengthPixels`, `otherSideLengthPixels`. |
| `player-<id>-<view>.tiles.json` | All tiles and annotation metadata. |
| `player-<id>-<view>.grid.png` | Red-boundary overlay; only when enabled. |

For `N` new successes: `4N` clean PNGs, `4N` grid JSONs, `4N` annotation JSONs, `N` manifests, and optionally `4N` overlays.

Render natively offscreen, retaining window aspect ratio, without upscaling. Support square maps with side 1-100; enforce GPU limits and a 16-million-pixel cap. Fail instead of cropping or lowering quality. Grid metadata records requested and actual geometry.

Image origin is top-left, Y downward. Tile centers follow `anchor + x * stepX + y * stepY`, using game-map coordinates; use the exported geometry for alignment.

### Manifest and statistics

`manifest.json` records schema/mapping versions, replay UUID, snapshot hash/serialization version, map size, players, views, capture settings, completion time, and each artifact's name, length, and SHA-256. Player metadata includes source tribe/skin IDs and compact labels. Hash/validate annotation files and overlays only when enabled; do not hash the manifest itself. Validate staging files before atomic publication.

Root `output.json` contains cumulative image counts for every supported lowercase tribe name, including zero counts:

```json
{
  "imperius": { "skin": 2, "default": 6 },
  "bardur": { "skin": 4, "default": 8 }
}
```

Count the POV player's default/premium skin once per committed clean image: twice per participant per replay. Do not count overlays, tiles, abandoned attempts, or duplicate/recovered outputs. Rebuild/reconcile from validated manifests at startup and after publication; replace statistics atomically. Counts persist across runs and can be recovered if the file is missing.

## Tile annotations

Each `.tiles.json` contains metadata `schema_version`, `replay_id`, `player_id`, `view`, `size`, `grid_file`, `mapping_version`, and a flat `tiles` list. Include exactly `size * size` entries, ordered by `y`, then `x`; coordinates range from 0 to `size - 1`.

**Fog overrides everything except coordinates.** Keep `fog=true`, zero numeric labels/appearance IDs, set `road=false`, and use absent unit/color values. These are masked values, not proof of absence. Revealed views have `fog=false` throughout.

On unfogged tiles:

| Field | How to set it |
| --- | --- |
| `x`, `y` | Game-map coordinates, not pixels. |
| `fog` | Active view's actual native fog state; do not replace replay visibility with an explorers-list guess. |
| `improvement` | Game-state improvement type, even if artwork is covered/not drawn; `0` if absent. Include supported operation-like types actually stored on the tile, not unrelated pending actions. |
| `resource` | Player-visible resource type; `0` if absent/hidden **or any game-state improvement exists**. Revealed mode bypasses technology hiding, not the improvement override. |
| `terrain` | Visible, effect-modified terrain enum category, e.g. wetland=`7`. One category per tile; no separate ground/topper labels or terrain-layer mismatch rejection. |
| `road` | Explicit game-state road flag, regardless of visible segments. Cities/bridges do not imply roads; routes and implicit `HasRoad` connectivity are not this flag. |
| `terrain_tribe_skin` | Compact label for effective rendered terrain tribe/skin, including overrides, not automatically owner or stored climate. |
| `terrain_appearance` | `{tribe_id, skin_id}` for the normalized tribe/effective source skin used to produce that label, not pre-override IDs. |
| `main_unit` | Always-present object described below; populate only for a player-visible main unit. Hidden enemy cloaks use absent values. |
| `top_right_unit_icon` | Always-present `{type}` for the actually displayed circular icon: passenger type when depicted, otherwise main-unit type when depicted; `0` when absent. No color, tribe/skin, or HP. Check icon visibility independently. |

### Main unit

| Field | How to set it |
| --- | --- |
| `type` | Visible main-unit enum type, not passenger type. |
| `tribe_skin` | Compact effective appearance label for the whole unit. Head/body must share an identity; log/skip the replay if they genuinely differ. Do not change the rendered unit. |
| `tribe_id`, `skin_id` | Effective source appearance IDs used for the compact label, not owner's IDs when different. |
| `color_rgb` | Base team/tint `[r,g,b]`, integer channels 0-255, including applicable stored-player/skin overrides. Exclude status effects, exhaustion, lighting, and shading; do not sample pixels or use tile climate. |
| `color_name` | Exact match in the embedded readable palette; unmatched RGB=`other`. Never use nearest-color matching or tribe names as color names. |
| `hp` | Current displayed main-unit HP, even if its text is not drawn. Not max/passenger HP. Convert stored tenths with `ceil(raw_health / 10)` only when applicable; never convert displayed-scale HP again. |

Absent, invisible, or fogged main unit:

```json
{
  "type": 0,
  "tribe_skin": 0,
  "tribe_id": 0,
  "skin_id": 0,
  "color_rgb": [0, 0, 0],
  "color_name": "none",
  "hp": 0
}
```

Unit presence/fog distinguish these placeholders from a real black color. Attributes have applicability dependencies; they are not statistically independent.

## Mappings

Pin [PolytopiaBoardRenderer enums](https://github.com/usemsedge/PolytopiaBoardRenderer/blob/54457a8bdef9baa863ebc0926eb8c31ea0d06c41/pyrender_UPDATED/enums.py) and `tribe_colors.json` at commit `54457a8bdef9baa863ebc0926eb8c31ea0d06c41`. Embed complete enum, appearance, and exact readable color-name/RGB tables in the mod DLL; record their version. Preserve enum IDs, explicitly mapping native values rather than assuming identical numbering.

Terrain: `NONE=0`, `WATER=1`, `OCEAN=2`, `FIELD=3`, `MOUNTAIN=4`, `FOREST=5`, `ICE=6`, `WETLAND=7`, `MANGROVE=8`. Examples: `Resource.NONE=0`, `Unit.NONE=0`, `WARRIOR=2`.

Compact playable tribe/skin labels:
- Default: normalized tribe ID minus 1 (labels 1-16).
- Supported premium skin: default label plus 16 (17-32). Use the pinned tribe-to-skin mapping, not merely `skin_id > 0`; source skin IDs are sparse.
- `0`: absent, fogged, unset, or Nature/non-playable terrain. For visible Nature, preserve source appearance IDs and other labels; log its tile count per replay/player/view without rejecting it.
- Resolve rendering overrides before encoding. Normalize legacy serialized style indexes only when needed; do not remap current typed `TribeType` values twice.

| Tribe | Source ID | Default | Premium |
| --- | --- | --- | --- |
| Aimo | 2 | 1 | 17 |
| Aquarion | 3 | 2 | 18 |
| Bardur | 4 | 3 | 19 |
| Elyrion | 5 | 4 | 20 |
| Hoodrick | 6 | 5 | 21 |
| Imperius | 7 | 6 | 22 |
| Kickoo | 8 | 7 | 23 |
| Luxidoor | 9 | 8 | 24 |
| Oumaji | 10 | 9 | 25 |
| Quetzali | 11 | 10 | 26 |
| Vengir | 12 | 11 | 27 |
| Xinxi | 13 | 12 | 28 |
| Yadakk | 14 | 13 | 29 |
| Zebasi | 15 | 14 | 30 |
| Polaris | 16 | 15 | 31 |
| Cymanti | 17 | 16 | 32 |

Do not assume 16 colors: the palette includes 16 playable defaults, a Swamp override, Nature/NONE, and explicitly stored player colors. Preserve RGB even for `other`.

## Validation

Check file checksums, required views, tile count/unique coordinates, enums/appearances, color/HP values, fog masks, participant identity, and image/grid alignment before publication. Log replay/view/tile and offending values for failures; log Nature counts per view. Reject partial replays and retain failures for retry. Verify native visibility, appearances, icons, HP scale, alignment, and save isolation in-game; static checks alone do not prove correct screenshots.
