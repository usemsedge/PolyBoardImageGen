# Board Capture Loop

Captures final replay POVs with tile annotations, optional grid overlays, and resumable progress. The [output specification](output_format.md) defines the contract; [ML tooling](ml/README.md) trains a separate pretrained tile classifier for each annotation. Native edge cases still require in-game validation.

## Use

1. Install `BoardCaptureLoop.polymod` in the game's `Mods` folder.
2. Put `settings.json` beside it:

```json
{
  "show_grid_overlay": true,
  "num_iterations": 10,
  "csv_filename": "replays.csv",
  "target_tile_pixels": 128
}
```

3. Supply a CSV with a `REPLAY LINK` column containing `https://share.polytopia.io/g/<replay-uuid>` links. Relative CSV paths start at the settings directory.
4. Choose `"input_mode": "links"` for authenticated direct downloads, or `"input_mode": "gamestates"` for local saved responses. Local mode reads `<replay-uuid>.json` from `gamestates_directory` (default `gamestates`, relative to settings), containing the original successful API response with an ended `data.currentGameStateData` snapshot. It does not read credentials or call the replay API; missing/invalid files fail locally without network fallback. Both modes use the CSV to select/order replay UUIDs. Omitted input_mode preserves legacy `links` behavior.
5. Press **Loop**. Direct-link mode requires signing in first. Escape or **Cancel** stops the batch. Local snapshots still require native game-version compatibility and exactly two non-Nature players; successful downloads do not guarantee renderability.

Missing/invalid settings stop the run. Preserve the runtime CSV on upgrades; close spreadsheet editors while capturing. Progress uses `capture_status`, `capture_output`, and `capture_error`, not an index. Lock the queue, detect external edits, and write CSV updates atomically with backups.

## Workflow

- Capture ended replays with exactly two non-Nature players; eliminated/resigned players count.
- Process UUIDs in CSV order, skipping duplicates and validated completed captures.
- Count only newly successful captures toward `num_iterations`. Log failures, continue, and retry them on a later run; attempt each UUID once per run. Mark non-two-player replays `skipped_non_two_player`.
- Produce only each player's normal view of the same final state: two screenshots per replay, no fully revealed screenshots. Load views independently, never advance the state, suppress capture-session saves, and restore visibility after completion/cancellation.
- Validate both normal views before publishing and marking the CSV `done`. Recover interrupted progress without double-counting. Existing valid four-view captures remain recoverable and are not deleted.
- Leave completed captures untouched when settings change.

Use native C# HTTP and game deserialization, following [PolytopiaReplayExtractor](https://github.com/usemsedge/PolytopiaReplayExtractor): `get_game_view_model`, then `spectate_game` fallback, using final `currentGameStateData`. Expired authentication requires signing in again. Never log credentials. Python is not a mod dependency.

## Outputs and implementation

Save to `Maps/replay-captures/<replay-uuid>/`: two clean PNGs, two grid JSONs, two tile-annotation JSONs, optional grid PNGs, and a checksum manifest. Cumulative `output.json` at the capture root counts the POV player's tribe/skin once per clean image. See [output_format.md](output_format.md) for the contract.

Settings, annotations, and pinned mappings are embedded in the mod; publication and cumulative statistics are validated and crash-safe. Render offscreen without PNG upscaling; retain window aspect ratio. Support square maps of side 1-100, enforcing GPU limits and a 16-million-pixel cap; fail rather than crop or silently lower quality.

**One-time migration:** delete old captures, reset their completion statuses, and rebuild statistics from annotated captures. Preserve CSV links. Do not repeat this on ordinary runs/upgrades; editing these documents deletes nothing.

## Machine learning

[ml/README.md](ml/README.md) covers preprocessing and training 11 independent pretrained ResNet18 classifiers: fog, improvement, resource, terrain, road, terrain tribe/skin, main-unit type/tribe-skin/color/HP, and icon type. Crops retain upright unit/icon context, letterbox to RGB 224x224, and use ImageNet normalization. Split by replay, not tile, to prevent leakage between POVs. Training needs PyTorch, torchvision, Pillow, cached pretrained weights, and at least three distinct annotated replays.

## Build and verify

Use .NET 8 SDK to build this `net6.0` mod:

```powershell
dotnet build .\BoardCaptureLoop.csproj --configuration Release --nologo
New-Item -ItemType Directory -Force .\dist | Out-Null
$zip = ".\dist\BoardCaptureLoop.zip"
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -LiteralPath .\package\manifest.json, .\package\patch.json, .\bin\Release\net6.0\BoardCaptureLoop.dll -DestinationPath $zip
Move-Item -Force $zip .\dist\BoardCaptureLoop.polymod
```

The archive root contains only `manifest.json`, `patch.json`, and `BoardCaptureLoop.dll`; embed mappings in the DLL. Build/test restore dependencies automatically. Packaging replaces the build artifact, not captures.

```powershell
dotnet test .\tests\BoardCaptureLoop.Tests.csproj --configuration Release --nologo
python -m unittest discover -s scripts -p "test_draw_grid.py" -v
```

Tests cover settings, queue/retries, HTTP, annotation rules, optional files, migration, statistics, and recovery. Verify native POV, fog/resources/cloaks, icon visibility/type, appearance, HP scale, alignment, and save isolation in-game. Use matching-version APIs; generated stubs and old reverse-engineering notes do not prove current rendering behavior.

Optional Python 3 overlay utility (standard library only):

```powershell
python .\scripts\draw_grid.py "player-1-normal.grid.json" "player-1-normal.png" "preview.grid.png"
```

Run it outside completed capture directories. It replaces its output but not its input; inputs must be matching-size, non-interlaced 8-bit RGB/RGBA PNGs. Omitting the third argument produces `<image-stem>.grid.png`. Preview files are not manifest artifacts.
