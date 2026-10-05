# Replay capture output

Each completed two-player replay produces four views of its final game state:
- Player A normal POV
- Player B normal POV
- Player A fully revealed POV
- Player B fully revealed POV

Fully revealed views include technology-hidden resources. Normal views preserve that player's fog and technology-dependent visibility. Nature is not a participant; eliminated players still count.

Each view writes:
- `player-<id>-<normal|revealed>.png`: clean world-camera image
- `player-<id>-<normal|revealed>.grid.json`: square map size, image dimensions, anchor, tile-step vectors, `targetTilePixels`, and actual `sideLengthPixels` / `otherSideLengthPixels`
- `player-<id>-<normal|revealed>.grid.png`: image with red tile boundaries

A full batch contains 10 replay directories: 40 clean PNGs, 40 overlays, and 40 grid metadata files. A completion manifest identifies the replay, players, views, and artifact checksums. Runtime CSV completion is written only after the whole replay's output has been published.

## Future tile annotations

Replay capture does not currently export per-tile training labels. The intended attributes are:
- Improvement
- Resource
- Road
- Terrain
- Tribe type of the terrain
- Unit type
- Unit health
- Unit color

These are eight independent traits. Labels must distinguish absent, unknown/obscured, and not applicable values.
