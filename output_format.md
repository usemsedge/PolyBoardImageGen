# Replay capture specification

This document defines the target implementation. Tile annotations are required now, not deferred to a future phase. Updating this specification does not itself implement these features or delete existing captures.

## Input settings

`settings.json` lives beside the installed BoardCaptureLoop mod. Relative paths in `csv_filename` resolve against that directory; absolute paths are allowed. Missing or invalid settings stop the run with a clear error.

Required fields:
- `show_grid_overlay`: boolean. Generate extra PNGs with red tile boundaries when true; omit them when false.
- `num_iterations`: positive integer. Maximum number of newly successful replay captures in this run, not the number of CSV entries attempted. Each successful replay produces four complete annotated views. Fewer successes are allowed if the pending input is exhausted.
- `csv_filename`: nonempty string. Path to the replay CSV, using the existing replay-link/UUID parsing rules.

Optional field:
- `target_tile_pixels`: integer from 32 through 512, default 128. Requested projected tile-edge length in pixels. Record the requested target and actual geometry in each grid metadata file; existing capture safety limits still apply.

Example:

```json
{
  "show_grid_overlay": true,
  "num_iterations": 10,
  "csv_filename": "replays.csv",
  "target_tile_pixels": 128
}
```

There is no `index` setting. Durable progress uses per-replay UUID/status tracking instead of a single cursor.

## Progress, failures, and retries

- Deduplicate replay links by UUID and preserve input order for pending entries.
- Skip validated completed captures without counting them toward `num_iterations`.
- A replay is complete only after all four images, grid metadata files, annotation files, required optional artifacts, and its manifest have been validated and published.
- Mark completion in the CSV only after successful publication. An interrupted attempt must not count as complete.
- Log download, rendering, annotation, or validation failures and continue to the next pending replay. Attempt a failed replay at most once per run; retain it for retry on the next run.
- Log and skip ineligible replays, including those without exactly two non-Nature participants. They do not count toward the success limit.
- If an annotation requires an unsupported enum, tribe/skin appearance, or other unsupported mapping, log the replay ID and offending value, skip publication of that replay, and retain it for retry after support is added. Do not silently map unsupported content to `NONE`. Unknown color values are supported through the `other` color category.
- Validate completed outputs against their recorded schema and capture settings. Changing current `target_tile_pixels` or `show_grid_overlay` does not invalidate or regenerate a completed capture; new settings apply only to new captures.

### One-time migration

Before the first run of the annotation-enabled implementation, delete all old captures in `Maps/replay-captures/`, reset their completion statuses so their source replays can be captured again, and reset/rebuild aggregate statistics from new annotated captures. This is a one-time migration, not deletion on every run. Preserve the source replay CSV and links. No deletion is performed merely by editing this document.

## Replay capture output

Outputs live in `Maps/replay-captures/<replay-uuid>/`. Each completed two-player replay produces four views of its final game state:
- Player A normal POV.
- Player B normal POV.
- Player A fully revealed POV.
- Player B fully revealed POV.

Nature is not a participant. Eliminated and resigned players still count. File names use actual player IDs, not fixed A/B IDs or player-state array indexes.

Normal views preserve that player's fog and technology-dependent resource visibility. Fully revealed views remove fog and reveal technology-hidden resources, while preserving the final game state. Resource labels still describe what is actually rendered, not hidden underlying contents covered by improvements. Native POV, fog, resource, unit-icon, and annotation alignment behavior must be validated in-game; static code inspection alone does not establish screenshot correctness.

Each view writes:
- `player-<id>-<normal|revealed>.png`: clean world-camera image.
- `player-<id>-<normal|revealed>.grid.json`: square map side length (`size`), image `width` and `height`, `anchor`, `stepX`, `stepY`, `targetTilePixels`, and actual `sideLengthPixels` / `otherSideLengthPixels`.
- `player-<id>-<normal|revealed>.tiles.json`: per-tile annotations.
- `player-<id>-<normal|revealed>.grid.png`: image with red tile boundaries, only when this capture's `show_grid_overlay` is true.

Image coordinates have their origin at the top left, with Y increasing downward. Annotation coordinates use the same map axes and tile-center convention as the corresponding grid metadata. Tile centers are located by `anchor + x * stepX + y * stepY`; consumers must use the emitted geometry rather than assuming generic pixel positions.

### Completion manifest

Each replay directory contains `manifest.json`, identifying the schema version, replay UUID, source snapshot/version, map size, participants, views, capture settings, annotation mapping version, completion time, and artifact names, byte lengths, and SHA-256 checksums.

Participant metadata records each player's raw tribe and skin IDs and compact tribe/skin label, allowing statistics to be recovered without recapturing images. Annotation metadata also preserves the raw IDs used to resolve visible terrain and main-unit appearances.

Validate all artifacts before atomically publishing the replay directory. Include annotation files in validation and checksums. Require overlays only when the manifest records that they were enabled; absence is valid otherwise. The manifest does not include a checksum of itself.

For `N` newly successful replays, a full run produces `N` replay directories, `4N` clean PNGs, `4N` grid metadata files, `4N` annotation files, and `N` manifests. It also produces `4N` overlay PNGs if overlays are enabled. Existing completed directories may remain alongside the new outputs. Ten is an example configuration, not a fixed batch size.

## Cumulative tribe/skin statistics

`Maps/replay-captures/output.json` contains cumulative counts across runs:

```json
{
  "imperius": {
    "skin": 2,
    "default": 6
  },
  "bardur": {
    "skin": 4,
    "default": 8
  }
}
```

- Count the POV player's tribe/skin once per successfully committed clean image. Each participant contributes twice per completed replay: normal and revealed.
- These are image counts, not skin IDs, terrain-tile counts, or unit counts. Overlays and annotation files do not contribute.
- `default` counts default appearances; `skin` counts the supported premium appearance. Use stable lowercase tribe names and include supported tribes with zero counts.
- Update statistics only after the whole replay is published, never after individual staging images. Log failures without counting abandoned attempts.
- Derive/reconcile counts from validated committed manifests at startup and after publication, and replace the aggregate file atomically. This makes recovery idempotent if a crash occurs between publication, statistics updates, and CSV completion updates.
- Duplicate links, retries, and recovered completed captures must never count the same clean image twice. A missing aggregate file can be rebuilt from manifests.

## Tile annotations

Each view has one `.tiles.json` file containing every map tile, including empty and fogged tiles: exactly `size * size` entries. Use a flat `tiles` list with explicit integer `x`, `y`, ordered by increasing `y`, then increasing `x`; both coordinates range from 0 through `size - 1`.

Top-level metadata includes `schema_version`, `replay_id`, `player_id`, `view` (`normal` or `revealed`), `size`, `grid_file`, and `mapping_version`.

### Visibility and masking

Annotation sources are field-specific: improvements and roads use game state on unfogged tiles; resources, terrain appearance, main units, and circular icons follow the rules below. Current main-unit HP is always labeled for visible main units, even when its text is not drawn. Fog overrides every annotation except game-map coordinates.

- `fog` follows the game's actual fog rendering in the active captured view, using native visibility and replay context rather than manually interpreting explorer membership. Fully revealed views have `fog=false` on every tile.
- When `fog` is true, preserve `x` and `y`, but set all other classification/HP labels and raw-ID placeholders to `0`, `road` to false, and the color fields to their absent representation. All those fields are masked/ignored, not evidence of actual absence.
- On an unfogged tile, an improvement in game state always overrides the resource: set `resource=0` whenever an improvement exists, regardless of whether its artwork is visible or the player has resource technology.
- Otherwise, label a resource only if the player can see it in this view. Technology-hidden, absent, or otherwise non-visible resources use `0`; do not expose their underlying resource IDs. Revealed views bypass technology hiding but still apply the improvement override.
- Main units are labeled only when visible to the player. Consult native unit visibility as well as tile fog; hidden enemy cloaks must not leak into labels. An absent or invisible main unit has all main-unit fields set to their absent representation.
- Evaluate the circular icon's actual display independently. An absent or fogged icon uses type `0`; passenger state alone does not establish that an icon is displayed.
- Apply these same field-specific rules to fully revealed views, using their active rendering context.

### Fields per tile

- `x`, `y`: zero-based game-map coordinates, not screen coordinates. Preserve them even when fogged.
- `fog`: boolean determined by the active view's actual fog rendering.
- `improvement`: the tile's game-state improvement type mapped to the pinned enum, regardless of artwork visibility or occlusion. Use `0` when absent or fogged.
- `resource`: resource type mapped to the pinned enum only when player-visible and no improvement exists on the tile. Otherwise use `0`, including when fogged.
- `terrain`: visible, effect-modified terrain category mapped to the pinned terrain enum; use `0` when fogged. Wetland is `WETLAND=7`, including terrain rendered as wetland after flooding. Treat each tile as one terrain category, not separate ground/topper annotations; do not add a terrain-layer mismatch rejection rule.
- `road`: the tile's explicit game-state road flag on unfogged tiles, regardless of visible road segments or other occupants; false when fogged. Cities and bridges do not imply roads. Do not substitute an implicit connectivity property such as `HasRoad`, or treat a route flag as a road flag.
- `terrain_tribe_skin`: compact label for the terrain's effective rendered appearance, including skin overrides, not automatically its owner's tribe or unadjusted stored climate.
- `terrain_appearance`: metadata object with normalized `tribe_id` and effective source `skin_id` used to produce `terrain_tribe_skin`, not original stored values before rendering overrides. Use zero placeholders when fogged.
- `main_unit`: object containing `type`, `tribe_skin`, `tribe_id`, `skin_id`, `color_rgb`, `color_name`, and `hp`, only for a player-visible main unit.
- `top_right_unit_icon`: object containing only `type`, identifying the unit actually depicted in the displayed circular icon at the tile's top right: passenger type when depicted, otherwise main-unit type when depicted. Use `0` when no icon is displayed or the tile is fogged. Do not infer/export icon color, tribe/skin, or HP.

`main_unit.type` describes the visible main unit, not its passenger. Its single tribe/skin label follows the whole unit's effective rendered identity, even when different from its owner's tribe/skin. `main_unit.tribe_id` and `skin_id` preserve the effective appearance IDs used to produce `tribe_skin`, not the owner's original IDs when different. The head and body are expected to resolve to the same identity: if a genuine head/body tribe/skin mismatch is found, log the replay, view, tile, and conflicting identities, skip publication of the entire replay, and retain it for retry. Do not choose one part arbitrarily or change the rendered appearance. The icon slot is separately resolved from the displayed icon; it is not an arbitrary second unit in the underlying tile state.

For absent or fogged main units, use `type`, `tribe_skin`, `tribe_id`, `skin_id`, and `hp` equal to `0`, `color_rgb` equal to `[0, 0, 0]`, and `color_name` equal to `none`. Unit presence and the fog mask disambiguate this placeholder from a real black color.

These are separate attributes with applicability dependencies, not statistically independent traits. The unit-icon type is an additional attribute beyond the original main-unit traits.

### Enum mapping

Use the definitions in `pyrender_UPDATED/enums.py` from PolytopiaBoardRenderer commit `54457a8bdef9baa863ebc0926eb8c31ea0d06c41` as the pinned mapping:

https://github.com/usemsedge/PolytopiaBoardRenderer/blob/54457a8bdef9baa863ebc0926eb8c31ea0d06c41/pyrender_UPDATED/enums.py

Record this source/version in `mapping_version` and ship the complete machine-readable enum/appearance/color mapping with the implementation. Preserve its terrain, resource, improvement, and unit IDs; do not assume all game/runtime enums or serialized climate IDs use the same numbering.

Terrain IDs are `NONE=0`, `WATER=1`, `OCEAN=2`, `FIELD=3`, `MOUNTAIN=4`, `FOREST=5`, `ICE=6`, `WETLAND=7`, and `MANGROVE=8`. Other examples: `Resource.NONE=0`; `Unit.NONE=0`, `WARRIOR=2`. Map the improvement type actually stored on the tile, including supported operation-like values if present in that state; do not require visible improvement artwork or derive the label from unrelated pending actions. A road remains separately represented by the explicit game-state `road` flag.

### Compact tribe/skin labels

Normalized source tribe IDs are:

| Tribe | Source ID | Default label | Premium label |
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

- `0`: absent, masked, unset, or Nature/non-playable terrain appearance, as distinguished by other fields.
- Default playable label: `normalized_tribe_id - 1` (1-16).
- Supported premium label: default label plus 16 (17-32).
- These are custom compact labels, not raw tribe or skin enum IDs. Premium skin IDs are sparse; use the pinned tribe-to-skin mapping in `pyrender_UPDATED/tribe_colors.json`.
- Normalize climate IDs only when reading a legacy serialized representation that uses style indexes. Current typed runtime `TribeType` values are already normalized and must not be remapped a second time. For example, Luxidoor's normalized source ID is 9, while its legacy climate index is different.
- Resolve effective rendered terrain/unit appearance before assigning the compact label. Account for special skin rules and cross-climate appearances; do not simply test whether a stored skin ID is positive.
- For visible Nature terrain, set `terrain_tribe_skin` to `0`, preserve its applicable raw appearance IDs, and label its other visible attributes normally. Log a summary per view with replay ID, player ID, view, and number of Nature terrain tiles. Do not treat Nature terrain as an unsupported replay.

### Unit color

- Store the visible main unit's base team/tint RGB as `color_rgb: [r, g, b]`, with integer channels 0-255, alongside a stable palette-based readable name in `color_name`. Exclude poison, freezing, boosting, other temporary status overlays, exhaustion washes, lighting, and shading; do not sample final screenshot pixels.
- Define readable color names from the pinned renderer palette, not from tribe names. Ship the exact name-to-RGB table as part of the mapping. Match palette entries by exact RGB, never by nearest-color approximation; use `other` for non-palette colors while preserving their RGB.
- Use the effective color of the rendered main unit, including stored player-color precedence and skin overrides where applicable. Do not derive color from tile climate or assume exactly 16 colors.
- The renderer has 16 playable default tribe colors, an additional Swamp skin color, Nature/NONE entries, and support for explicitly stored player colors.

### Main-unit health

Always label current displayed-scale HP for a visible main unit, even if the numeric health text is not drawn in the screenshot. This is an intentional exception to strictly pixel-visible labels.

Use the main unit's current displayed HP, not maximum HP or the passenger's HP, and convert stored tenths using `ceil(raw_health / 10)` where that is the applicable source representation. Do not apply this conversion again to an already displayed-scale value. Fogged or absent units have `hp=0`. Do not label health for the top-right icon.

### Validation and logging

Before publication, validate tile count, unique/in-range coordinates, enum and appearance mappings, color/HP representations, fog masking, view/participant identity, and consistency with the corresponding image and grid metadata. Every required view must pass; do not publish a partially annotated replay.

Logs identify the replay and view where applicable, describe failures/unsupported values, and include per-view Nature-terrain summaries. Failures continue the run and remain retryable. Native visual correctness and alignment require in-game checks in addition to schema validation.
