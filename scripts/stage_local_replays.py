"""Stage and install archived replay responses while Polytopia is closed."""
import base64
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import uuid
import zipfile

ROOT = Path(__file__).resolve().parents[1]
GAME = Path(r"C:\Program Files\Epic Games\TheBattleofPolytopiaACfMZ")
PULLER = ROOT / "replay_data_puller"


def main():
    check = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Polytopia.exe", "/FO", "CSV", "/NH"], capture_output=True, check=True)
    if b'"Polytopia.exe"' in check.stdout:
        raise RuntimeError("Close Polytopia before installing")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    stage = ROOT / "dist" / ("local-gamestates-" + stamp)
    stage.mkdir(exist_ok=False)
    states = stage / "gamestates"
    states.mkdir()
    with (PULLER / "replays.csv").open(encoding="utf-8-sig", newline="") as handle:
        links = [row["link"] for row in csv.DictReader(handle) if row["status"] == "saved_ended"]
    versions = {}
    with (stage / "all-found-replays.csv").open("x", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["REPLAY LINK", "capture_status", "capture_output", "capture_error"])
        for link in links:
            game_id = str(uuid.UUID(link.rsplit("/", 1)[1]))
            found = False
            for attempt in sorted((PULLER / "data" / game_id).iterdir(), reverse=True):
                for endpoint in ("primary", "fallback"):
                    directory = attempt / endpoint
                    metadata = directory / "response.json"
                    if not metadata.is_file():
                        continue
                    meta = json.loads(metadata.read_text(encoding="utf-8"))
                    if not meta.get("complete") or meta.get("http_status") != 200:
                        continue
                    raw = (directory / "response.body").read_bytes()
                    doc = json.loads(raw)
                    data = doc.get("data")
                    if doc.get("success") is not True or not isinstance(data, dict) or data.get("state") != 4:
                        continue
                    if data.get("id") is not None and str(uuid.UUID(data["id"])) != game_id:
                        raise ValueError("Archive identity mismatch")
                    blob = base64.b64decode(data["currentGameStateData"], validate=True)
                    if len(blob) <= 8:
                        raise ValueError("Truncated snapshot")
                    outer, inner = struct.unpack_from("<ii", blob)
                    if outer <= 0 or outer != inner:
                        raise ValueError("Snapshot header mismatch")
                    target = states / (game_id + ".json")
                    target.write_bytes(raw)
                    if hashlib.sha256(target.read_bytes()).digest() != hashlib.sha256(raw).digest():
                        raise OSError("Staging verification failed")
                    versions[str(outer)] = versions.get(str(outer), 0) + 1
                    writer.writerow([link, "", "", ""])
                    found = True
                    break
                if found:
                    break
            if not found:
                raise ValueError("Saved replay has no usable archived response")
    settings = {"show_grid_overlay": False, "num_iterations": len(links),
                "csv_filename": "all-found-replays.csv", "target_tile_pixels": 128,
                "input_mode": "gamestates", "gamestates_directory": "gamestates"}
    (stage / "settings.json").write_bytes((json.dumps(settings, indent=2) + "\n").replace("\n", "\r\n").encode())
    with zipfile.ZipFile(stage / "BoardCaptureLoop.polymod", "x", compression=zipfile.ZIP_DEFLATED) as package:
        for name in ("manifest.json", "patch.json"):
            package.write(ROOT / "package" / name, name)
        package.write(ROOT / "bin" / "Release" / "net6.0" / "BoardCaptureLoop.dll", "BoardCaptureLoop.dll")
    mods = GAME / "Mods"
    backup = GAME / ("BoardCaptureLoop-backup-" + stamp)
    (backup / "Mods").mkdir(parents=True, exist_ok=False)
    # Only BoardCaptureLoop inputs/settings/package are moved; other mods stay put.
    names = {"settings.json", "BoardCaptureLoop.polymod", "annotation-smoke.csv",
             "Polytopia Tribe Evaluator Calculator - Google Form.csv", "random-replays-10-20261027.csv",
             "all-found-replays.csv", "gamestates"}
    for path in list(mods.iterdir()):
        if path.name in names or any(path.name == n + suffix for n in names for suffix in (".bak", ".lock")) or path.name.startswith("settings.before-"):
            shutil.move(str(path), str(backup / "Mods" / path.name))
    for name in ("replay-captures",):
        path = GAME / "Maps" / name
        if path.exists():
            (backup / "Maps").mkdir(exist_ok=True)
            shutil.move(str(path), str(backup / "Maps" / name))
    for name in ("gamestates", "all-found-replays.csv", "settings.json", "BoardCaptureLoop.polymod"):
        source, target = stage / name, mods / name
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)
    if len(list((mods / "gamestates").glob("*.json"))) != len(links):
        raise OSError("Installed snapshot count mismatch")
    print(json.dumps({"installed": True, "count": len(links), "versions": versions,
                      "input_mode": "gamestates", "backup": str(backup), "stage": str(stage)}, indent=2))


if __name__ == "__main__":
    main()
