# Board Capture Loop

A PolyMod mod that adds a **Loop** button to Polytopia's home screen. It reads replay links in CSV order, downloads their final game states, and captures up to ten completed replays with exactly two players. The nature player is excluded; eliminated or resigned participants still count.

Each replay produces four views of the same final state:

- Player A, normal fog of war and technology-dependent resource visibility.
- Player B, normal fog of war and technology-dependent resource visibility.
- Player A, fully revealed, including technology-hidden resources.
- Player B, fully revealed, including technology-hidden resources.

Press Escape or use the menu's Cancel button to stop a running batch. Completed replays stay completed; an interrupted replay is retried on a later run.

Every view produces a clean `.png`, matching `.grid.json` geometry, and `.grid.png` overlay. A full batch therefore produces **40 clean images, 40 grid overlays, and 40 metadata files**. Resolution scales with board size to target **128 pixels along each projected tile edge**, independently of the game window's pixel resolution (its aspect ratio is retained). Set `BOARDCAPTURELOOP_TILE_PIXELS` before launching to choose an integer target from 32 to 512. This is native offscreen rendering, not PNG upscaling. The grid metadata records the requested target and achieved edge lengths. GPU texture limits and a 16-million-pixel safety cap are enforced; requests that exceed them fail clearly instead of silently reducing quality. Larger targets consume more memory and take longer. The setting applies to new captures; valid completed replay outputs and CSV progress are not reset. Supported maps are square with 1–100 tiles per side; unsupported shapes are reported, not silently cropped.

## Replay queue and progress

Place `Polytopia Tribe Evaluator Calculator - Google Form.csv` **beside `BoardCaptureLoop.polymod` in the game's `Mods` folder**. The input must contain a `REPLAY LINK` column with links such as `https://share.polytopia.io/g/<replay-uuid>`. Other columns are preserved. The repository CSV is an initial seed; the mod updates only the runtime copy.

On this machine the installation directory is:

```text
C:\Program Files\Epic Games\TheBattleofPolytopiaACfMZ\Mods
```

Copy the CSV only on first installation. **Do not overwrite it on upgrades**, because its added `capture_status`, `capture_output`, and `capture_error` columns hold processing progress. Set `BOARDCAPTURELOOP_CSV` before launching the game to override the default CSV path. Close spreadsheet editors before starting a batch. The mod locks the queue and refuses to overwrite externally changed CSV data; updates use atomic replacement with a backup.

Replay UUIDs are deduplicated, including links appearing in multiple rows. The batch scans past confirmed non-two-player replays to find ten eligible unfinished replays. Completed entries are marked `done` only after all four views and their overlays/metadata have been validated and published. Confirmed non-two-player entries are marked `skipped_non_two_player`; download, authentication, decoding, and rendering failures remain retryable. If there are fewer than ten successful replays available, the completion message reports the actual count.

Outputs live under the game's `Maps/replay-captures/<replay-uuid>/` directory, with prefixes `player-<id>-normal` and `player-<id>-revealed`. Each published directory contains a completion manifest with artifact checksums. Startup recovery can repair CSV completion after a crash between publishing outputs and updating the CSV; incomplete attempts are not treated as done.

## Authentication and rendering

Sign into Polytopia before running the batch. Replay retrieval follows [PolytopiaReplayExtractor](https://github.com/usemsedge/PolytopiaReplayExtractor): authenticated `get_game_view_model` with `spectate_game` fallback, using the final `currentGameStateData` rather than the initial state. Only ended replays are captured. Missing/expired authentication requires signing into Polytopia again; credentials are never written into capture output or logs.

The mod uses native C# HTTP and game deserialization; **Python is not a runtime dependency**. Every view loads independently to avoid revealed information leaking into normal POVs. Capture sessions suppress their own saves and restore normal replay visibility when finished or cancelled. The supplied state is not advanced or replaced by a generated map.

## Standalone grid overlay

`scripts/draw_grid.py` redraws red tile boundaries on a saved board PNG using its matching `.grid.json` metadata. It requires Python 3 and only the standard library; no pip packages are needed. The mod already draws grid overlays itself, so this utility is optional and is not a mod runtime dependency.

```powershell
python .\scripts\draw_grid.py "map-01-16x16.grid.json" "map-01-16x16.png"
```

The default output is `map-01-16x16.grid.png`. Supply a third argument to choose another output path. An existing output file is replaced, but the tool refuses to overwrite the input image. Input PNGs must be non-interlaced, 8-bit RGB or RGBA, and their dimensions must match the metadata.

Run the regression tests from the project directory:

```powershell
python -m unittest discover -s scripts -p "test_draw_grid.py" -v
```

## Tests

The isolated .NET tests exercise CSV selection/progress, HTTP responses, output validation, and restart recovery without Unity or game credentials:

```powershell
dotnet test .\tests\BoardCaptureLoop.Tests.csproj --configuration Release --nologo
```

`dotnet test` builds and restores its dependencies automatically. The mod's native replay loading, player POV mapping, fog/resource visibility, and save isolation still require validation inside Polytopia; unit tests cannot verify IL2CPP runtime behavior.

## Build the `.polymod` from source

On Windows, install the .NET 8 SDK (which builds this `net6.0` project). From the project directory in PowerShell, run:

```powershell
dotnet build .\BoardCaptureLoop.csproj --configuration Release --nologo
$files = @(
    ".\package\manifest.json",
    ".\package\patch.json",
    ".\bin\Release\net6.0\BoardCaptureLoop.dll"
)
$zip = ".\dist\BoardCaptureLoop.zip"
$mod = ".\dist\BoardCaptureLoop.polymod"
New-Item -ItemType Directory -Force .\dist | Out-Null
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -LiteralPath $files -DestinationPath $zip
Move-Item -Force $zip $mod
```

`dotnet build` restores the PolyMod NuGet dependency automatically; the configured feeds must be reachable. A `.polymod` is a ZIP archive with `manifest.json`, `patch.json`, and `BoardCaptureLoop.dll` **at the archive root**, not inside `package/` or `net6.0/`. If `dist\BoardCaptureLoop.polymod` already exists, the final command replaces that build artifact. Inspect its entries with `Add-Type -AssemblyName System.IO.Compression; ([IO.Compression.ZipFile]::OpenRead((Resolve-Path .\dist\BoardCaptureLoop.polymod))).Entries.FullName`; it should list exactly those three names.

