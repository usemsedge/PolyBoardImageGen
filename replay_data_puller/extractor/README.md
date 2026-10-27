# Polytopia Replay Extractor

Turn a **finished** Polytopia share link into GameState JSON (optional `.state` file).

## Setup

Needs Python 3.10+ and Polytopia logged in on this machine so a `jwtToken` file exists:

- **macOS:** `~/Library/Application Support/com.midjiwan.polytopia*`
- **Windows:** `%USERPROFILE%\AppData\LocalLow\Midjiwan` (also `AppData\Local` and `Roaming`)

ReplayExtractor searches your device for your polytopia JWT to pull a replay from the server. If the API returns 401, open Polytopia while logged in so it writes a new `jwtToken` (it may not exist or have expireed).

```bash
pip3 install -r requirements.txt
chmod +x install-cli.sh
./install-cli.sh
```

If `replayextractor` is not found, add the printed bin directory to `PATH`.

## Use

```bash
replayextractor https://share.polytopia.io/g/<uuid>
replayextractor https://share.polytopia.io/g/<uuid> -s game.state
python3 __main__.py https://share.polytopia.io/g/<uuid>   # without the shortcut
```
