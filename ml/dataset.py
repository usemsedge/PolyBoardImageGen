"""Strict capture ingestion, semantic labels and replay-grouped split manifests."""
import argparse
import hashlib
import json
from pathlib import Path
import uuid

from .preprocess import CropConfig, tile_image, validate_grid

TARGETS = (
    "fog", "improvement", "resource", "terrain", "road", "terrain_tribe_skin",
    "main_unit.type", "main_unit.tribe_skin", "main_unit.color_name", "main_unit.hp",
    "top_right_unit_icon.type",
)


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def save_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def field(obj, snake, pascal):
    if snake in obj:
        return obj[snake]
    return obj[pascal]


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_id(value):
    return str(uuid.UUID(str(value)))


def integer(value, minimum=0, maximum=None):
    if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
        raise ValueError(f"Invalid integer label: {value!r}")
    return value


def validate_tile(tile):
    integer(tile["x"])
    integer(tile["y"])
    if type(tile["fog"]) is not bool or type(tile["road"]) is not bool:
        raise ValueError("Fog/road must be booleans")
    for key in ("improvement", "resource", "terrain"):
        integer(tile[key], maximum=8 if key == "terrain" else None)
    integer(tile["terrain_tribe_skin"], maximum=32)
    appearance = tile["terrain_appearance"]
    integer(appearance["tribe_id"], maximum=17)
    integer(appearance["skin_id"], minimum=-1)
    unit = tile["main_unit"]
    for key in ("type", "tribe_id", "hp"):
        integer(unit[key])
    integer(unit["skin_id"], minimum=-1)
    integer(unit["tribe_skin"], maximum=32)
    rgb = unit["color_rgb"]
    if not isinstance(rgb, list) or len(rgb) != 3:
        raise ValueError("RGB must contain three channels")
    for channel in rgb:
        integer(channel, maximum=255)
    if not isinstance(unit["color_name"], str) or not unit["color_name"].strip():
        raise ValueError("Missing readable color name")
    integer(tile["top_right_unit_icon"]["type"], maximum=62)
    if tile["improvement"] > 55 or tile["resource"] > 9 or unit["type"] > 62:
        raise ValueError("Unsupported pinned enum label")
    if tile["improvement"] and tile["resource"]:
        raise ValueError("Improvement must override resource")
    if unit["type"] == 0 and (any(unit[k] for k in ("tribe_skin", "tribe_id", "skin_id", "hp"))
                              or rgb != [0, 0, 0] or unit["color_name"] != "none"):
        raise ValueError("Absent unit attributes must use documented placeholders")
    if unit["type"] != 0 and unit["color_name"] == "none":
        raise ValueError("Present unit cannot have absent color")
    if tile["fog"] and (any(tile[k] for k in ("improvement", "resource", "terrain", "road", "terrain_tribe_skin"))
                         or any(appearance.values()) or unit["type"] or tile["top_right_unit_icon"]["type"]):
        raise ValueError("Fogged tile does not obey masking contract")


def label(tile, target):
    if target not in TARGETS:
        raise ValueError(f"Unsupported target {target}")
    if tile["fog"] and target != "fog":
        return None
    # HP=0 for an absent unit is a placeholder, not a displayed-HP observation.
    if target == "main_unit.hp" and tile["main_unit"]["type"] == 0:
        return None
    value = tile
    for part in target.split("."):
        value = value[part]
    return value


def load_replay(directory):
    """Validate all recorded artifacts before returning clean-image tile records."""
    directory = Path(directory).resolve()
    manifest = read_json(directory / "manifest.json")
    replay_id = canonical_id(field(manifest, "replay_id", "ReplayId"))
    if canonical_id(directory.name) != replay_id:
        raise ValueError("Replay directory/manifest identity mismatch")
    size = integer(field(manifest, "map_size", "MapSize"), 1, 100)
    schema = integer(field(manifest, "schema_version", "SchemaVersion"), 2, 2)
    mapping = field(manifest, "mapping_version", "MappingVersion")
    if not isinstance(mapping, (str, int)) or isinstance(mapping, bool) or str(mapping) == "":
        raise ValueError("Missing mapping version; recapture legacy non-annotated outputs")
    players = field(manifest, "player_ids", "PlayerIds")
    if len(players) != 2 or len(set(players)) != 2:
        raise ValueError("Exactly two distinct player IDs required")
    for player in players:
        integer(player)
    views = field(manifest, "views", "Views")
    expected = {f"player-{p}-{v}" for p in players for v in ("normal", "revealed")}
    if len(views) != 4 or set(views) != expected:
        raise ValueError("Four player normal/revealed views required")
    artifacts = field(manifest, "artifacts", "Artifacts")
    recorded = {}
    for artifact in artifacts:
        name = field(artifact, "name", "Name")
        if not isinstance(name, str) or Path(name).name != name or "/" in name or "\\" in name or name == "manifest.json":
            raise ValueError("Unsafe artifact name")
        if name in recorded:
            raise ValueError("Duplicate artifact name")
        path = directory / name
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"Missing or linked artifact {name}")
        expected_length = integer(field(artifact, "length", "Length"), 1)
        digest = field(artifact, "sha256", "Sha256")
        if not isinstance(digest, str) or len(digest) != 64 or path.stat().st_size != expected_length or sha256(path) != digest.lower():
            raise ValueError(f"Artifact length/hash mismatch: {path}")
        recorded[name] = digest.lower()
    required = {v + suffix for v in expected for suffix in (".png", ".grid.json", ".tiles.json")}
    allowed = required | {v + ".grid.png" for v in expected}
    if not required <= recorded.keys() or not recorded.keys() <= allowed:
        raise ValueError("Manifest missing annotations or contains unexpected artifacts")
    settings = manifest.get("capture_settings", manifest.get("CaptureSettings", manifest.get("Settings", {})))
    overlay = settings.get("show_grid_overlay", settings.get("ShowGridOverlay"))
    overlay_names = {v + ".grid.png" for v in expected}
    if overlay is True and not overlay_names <= recorded.keys():
        raise ValueError("Enabled overlays missing from manifest")
    if overlay is False and overlay_names & recorded.keys():
        raise ValueError("Disabled overlays unexpectedly recorded")
    from PIL import Image
    records = []
    palette = {}
    for stem in sorted(expected):
        grid = read_json(directory / (stem + ".grid.json"))
        validate_grid(grid)
        if grid["size"] != size:
            raise ValueError("Grid map size mismatch")
        image_path = directory / (stem + ".png")
        with Image.open(image_path) as image:
            if image.format != "PNG" or image.size != (grid["width"], grid["height"]):
                raise ValueError("Clean PNG/grid dimensions mismatch")
            image.verify()
        overlay_path = directory / (stem + ".grid.png")
        if overlay_path.name in recorded:
            with Image.open(overlay_path) as image:
                if image.format != "PNG" or image.size != (grid["width"], grid["height"]):
                    raise ValueError("Overlay dimensions mismatch")
                image.verify()
        annotations = read_json(directory / (stem + ".tiles.json"))
        player, view = stem[len("player-"):].rsplit("-", 1)
        if (canonical_id(annotations["replay_id"]) != replay_id or annotations["player_id"] != int(player)
                or annotations["view"] != view or annotations["size"] != size
                or annotations["grid_file"] != stem + ".grid.json"
                or str(annotations["mapping_version"]) != str(mapping)):
            raise ValueError("Annotation identity/geometry/mapping mismatch")
        if str(annotations["schema_version"]) != "1":
            raise ValueError("Unsupported tile annotation schema")
        tiles = annotations["tiles"]
        if len(tiles) != size * size:
            raise ValueError("Annotation tile count mismatch")
        for index, tile in enumerate(tiles):
            validate_tile(tile)
            if (tile["x"], tile["y"]) != (index % size, index // size):
                raise ValueError("Tiles must have unique ordered y/x coordinates")
            if view == "revealed" and tile["fog"]:
                raise ValueError("Revealed tile cannot be fogged")
            unit = tile["main_unit"]
            color = unit["color_name"]
            if color not in ("none", "other"):
                palette.setdefault(color, set()).add(tuple(unit["color_rgb"]))
            records.append({"replay_id": replay_id, "image": str(image_path), "grid": grid,
                            "x": tile["x"], "y": tile["y"],
                            "labels": {target: label(tile, target) for target in TARGETS}})
    return records, {"replay_id": replay_id, "manifest_sha256": sha256(directory / "manifest.json"),
                     "directory": str(directory), "mapping_version": mapping, "schema_version": schema}, palette


def split_replays(ids, seed=42, fractions=(0.7, 0.15, 0.15)):
    if len(ids) < 3 or len(set(ids)) != len(ids):
        raise ValueError("Need at least three distinct replays for train/val/test")
    if len(fractions) != 3 or any(v <= 0 for v in fractions) or abs(sum(fractions) - 1) > 1e-8:
        raise ValueError("Three positive split fractions must sum to one")
    ordered = sorted(ids, key=lambda replay: hashlib.sha256(f"{seed}:{replay}".encode()).hexdigest())
    n_test = max(1, round(len(ids) * fractions[2]))
    n_val = max(1, round(len(ids) * fractions[1]))
    if n_test + n_val >= len(ids):
        raise ValueError("Split fractions leave no training replay")
    return {"train": ordered[: -n_val - n_test], "val": ordered[-n_val - n_test: -n_test], "test": ordered[-n_test:]}


def prepare(root, output, seed=42):
    output = Path(output)
    if output.exists() and any(output.iterdir()):
        raise ValueError("Use an empty output directory to avoid mixing datasets")
    records, sources, palette = [], [], {}
    for manifest in sorted(Path(root).glob("*/manifest.json")):
        if manifest.parent.name.startswith("."):
            continue
        rows, source, colors = load_replay(manifest.parent)
        records.extend(rows)
        sources.append(source)
        for name, values in colors.items():
            palette.setdefault(name, set()).update(values)
    if len({str(s["mapping_version"]) for s in sources}) > 1:
        raise ValueError("Cannot mix mapping versions")
    groups = split_replays([s["replay_id"] for s in sources], seed)
    train_ids = set(groups["train"])
    vocabs = {}
    for target in TARGETS:
        values = {row["labels"][target] for row in records
                  if row["replay_id"] in train_ids and row["labels"][target] is not None}
        if not values:
            raise ValueError(f"No applicable training examples for {target}")
        vocabs[target] = sorted(values)
    for name, values in palette.items():
        if len(values) != 1:
            raise ValueError(f"Palette name {name!r} maps to inconsistent RGB values")
    partitions = {name: [row for row in records if row["replay_id"] in set(ids)] for name, ids in groups.items()}
    for name, rows in partitions.items():
        save_json(output / (name + ".json"), rows)
    save_json(output / "dataset.json", {"format_version": 1, "seed": seed, "groups": groups,
              "sources": sources, "vocabularies": vocabs,
              "partition_sha256": {name: sha256(output / (name + ".json")) for name in partitions},
              "color_palette": {name: list(next(iter(values))) for name, values in palette.items()}})
    return {name: len(rows) for name, rows in partitions.items()}


def load_partition(directory, metadata, split):
    path = Path(directory) / (split + ".json")
    if sha256(path) != metadata["partition_sha256"][split]:
        raise ValueError("Split manifest changed since preparation")
    rows = read_json(path)
    allowed = set(metadata["groups"][split])
    if any(row["replay_id"] not in allowed for row in rows):
        raise ValueError("Split contains a replay assigned to another partition")
    return rows


def verify_sources(metadata):
    for source in metadata["sources"]:
        _, actual, _ = load_replay(source["directory"])
        if actual != source:
            raise ValueError("Capture changed since dataset preparation; prepare a new dataset")


class TileDataset:
    def __init__(self, rows, target, vocabulary, crop=CropConfig(), transform=None):
        self.target, self.vocabulary, self.crop, self.transform = target, vocabulary, crop, transform
        self.rows = [row for row in rows if row["labels"][target] is not None]
        self.lookup = {value: index for index, value in enumerate(vocabulary)}
        self.unknown_count = sum(row["labels"][target] not in self.lookup for row in self.rows)

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, index):
        from PIL import Image
        row = self.rows[index]
        with Image.open(row["image"]) as image:
            patch = tile_image(image, row["grid"], row["x"], row["y"], self.crop)
        if self.transform:
            patch = self.transform(patch)
        return patch, self.lookup.get(row["labels"][self.target], -1)


def main():
    parser = argparse.ArgumentParser(description="Validate annotation-enabled captures and split by replay")
    parser.add_argument("--captures", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--seed", default=42, type=int)
    args = parser.parse_args()
    print(json.dumps(prepare(args.captures, args.output, args.seed), indent=2))


if __name__ == "__main__":
    main()
