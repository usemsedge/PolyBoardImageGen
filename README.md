# Board Capture Loop

A PolyMod mod that adds one **Loop** button to Polytopia's home screen. Clicking it creates ten sequential terrain-only game states, each with a random 10–20 tile side length. Every run writes three files for each board under `Maps/Loop-<timestamp>/`:

- `map-NN-<size>x<size>.png` — the unmarked Unity-rendered board.
- `map-NN-<size>x<size>.grid.json` — decimal-valued anchor, tile-step vectors, and image dimensions.
- `map-NN-<size>x<size>.grid.png` — the same board with red tile boundaries.

Each capture is taken after the game reports its level ready and a few rendered frames. The batch returns to the menu between boards. It needs PolyMod and Polytopia; it does not invoke Python. Pixel resolution follows the game window.

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

