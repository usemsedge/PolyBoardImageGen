# Board Capture Loop

**Implementation roadmap, not a claim of completed features.** The [output specification](output_format.md) defines the settings, files, and annotation rules. Tile annotations are part of this implementation.

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
4. Sign into Polytopia and press **Loop**. Escape or **Cancel** stops the batch.

Missing/invalid settings stop the run. Preserve the runtime CSV on upgrades; close spreadsheet editors while capturing. Progress uses `capture_status`, `capture_output`, and `capture_error`, not an index. Lock the queue, detect external edits, and write CSV updates atomically with backups.

## Workflow

- Capture ended replays with exactly two non-Nature players; eliminated/resigned players count.
- Process UUIDs in CSV order, skipping duplicates and validated completed captures.
- Count only newly successful captures toward `num_iterations`. Log failures, continue, and retry them on a later run; attempt each UUID once per run. Mark non-two-player replays `skipped_non_two_player`.
- Produce each player's normal and fully revealed views of the same final state. Load views independently, never advance the state, suppress capture-session saves, and restore visibility after completion/cancellation.
- Validate all four views before publishing and marking the CSV `done`. Recover interrupted progress without double-counting.
- Leave completed captures untouched when settings change.

Use native C# HTTP and game deserialization, following [PolytopiaReplayExtractor](https://github.com/usemsedge/PolytopiaReplayExtractor): `get_game_view_model`, then `spectate_game` fallback, using final `currentGameStateData`. Expired authentication requires signing in again. Never log credentials. Python is not a mod dependency.

## Outputs and implementation

Save to `Maps/replay-captures/<replay-uuid>/`: four clean PNGs, four grid JSONs, four tile-annotation JSONs, optional grid PNGs, and a checksum manifest. Cumulative `output.json` at the capture root counts the POV player's tribe/skin once per clean image. See [output_format.md](output_format.md) for the contract.

Implement settings, annotations and embedded mappings, optional overlays, validated atomic publication, and crash-safe statistics. Render offscreen without PNG upscaling; retain window aspect ratio. Support square maps of side 1-100, enforcing GPU limits and a 16-million-pixel cap; fail rather than crop or silently lower quality.

**One-time migration:** delete old captures, reset their completion statuses, and rebuild statistics from annotated captures. Preserve CSV links. Do not repeat this on ordinary runs/upgrades; editing these documents deletes nothing.

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

Add tests for settings, queue/retries, HTTP, annotation rules, optional files, migration, statistics, cancellation, and recovery. Verify native POV, fog/resources/cloaks, icon visibility/type, appearance, HP scale, alignment, and save isolation in-game. Use matching-version APIs; generated stubs and old reverse-engineering notes do not prove current rendering behavior.

Optional Python 3 overlay utility (standard library only):

```powershell
python .\scripts\draw_grid.py "player-1-normal.grid.json" "player-1-normal.png" "preview.grid.png"
```

Run it outside completed capture directories. It replaces its output but not its input; inputs must be matching-size, non-interlaced 8-bit RGB/RGBA PNGs. Omitting the third argument produces `<image-stem>.grid.png`. Preview files are not manifest artifacts.
