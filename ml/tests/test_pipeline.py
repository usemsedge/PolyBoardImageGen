import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from ml.dataset import (TARGETS, label, load_partition, load_replay, prepare,
                        save_json, sha256, split_replays, validate_tile)
from ml.predict import apply_dependencies
from ml.preprocess import CropConfig, crop_box, validate_grid


GRID = {"size": 2, "width": 400, "height": 300,
        "anchor": [100, 100], "stepX": [40, 20], "stepY": [-40, 20]}


def tile(x=0, y=0):
    return {"x": x, "y": y, "fog": False, "improvement": 0, "resource": 0,
            "terrain": 3, "road": False, "terrain_tribe_skin": 1,
            "terrain_appearance": {"tribe_id": 2, "skin_id": 0},
            "main_unit": {"type": 2, "tribe_skin": 1, "tribe_id": 2, "skin_id": 0,
                          "color_rgb": [1, 2, 3], "color_name": "blue", "hp": 10},
            "top_right_unit_icon": {"type": 2}}


class GeometryTests(unittest.TestCase):
    def test_context_preserves_ground_head_and_badge(self):
        ground = crop_box(GRID, 0, 0, CropConfig(0, 0, 0, 0))
        self.assertEqual(ground, (60, 80, 140, 120))
        context = crop_box(GRID, 0, 0)
        self.assertEqual(context, (40, 20, 180, 130))
        self.assertLess(context[1], ground[1])
        self.assertGreater(context[2], ground[2])

    def test_coordinates_use_both_basis_vectors(self):
        self.assertEqual(crop_box(GRID, 1, 1), (40, 60, 180, 170))

    def test_edge_context_is_not_clipped(self):
        grid = dict(GRID, anchor=[0, 0])
        self.assertLess(crop_box(grid, 0, 0)[0], 0)
        self.assertLess(crop_box(grid, 0, 0)[1], 0)

    def test_invalid_geometry(self):
        for grid in (dict(GRID, stepY=[80, 40]), dict(GRID, anchor=[float("nan"), 0])):
            with self.assertRaises(ValueError):
                validate_grid(grid)
        with self.assertRaises(ValueError):
            CropConfig(above=-1)
        with self.assertRaises(ValueError):
            crop_box(GRID, 2, 0)


class SemanticTests(unittest.TestCase):
    def test_fog_mask_excludes_every_other_target(self):
        row = tile()
        row["fog"] = True
        for target in TARGETS:
            self.assertEqual(label(row, target), True if target == "fog" else None)

    def test_absent_hp_excluded_other_none_classes_retained(self):
        row = tile()
        row["main_unit"]["type"] = 0
        row["main_unit"]["hp"] = 0
        self.assertIsNone(label(row, "main_unit.hp"))
        self.assertEqual(label(row, "main_unit.type"), 0)

    def test_hp_is_categorical_nonnegative_integer(self):
        validate_tile(tile())
        for invalid in (-1, 1.5, True):
            row = tile()
            row["main_unit"]["hp"] = invalid
            with self.assertRaises(ValueError):
                validate_tile(row)

    def test_source_none_skin_is_supported(self):
        row = tile()
        row["terrain_appearance"]["skin_id"] = -1
        row["main_unit"]["skin_id"] = -1
        validate_tile(row)

    def test_improvement_overrides_resource(self):
        row = tile()
        row["improvement"] = 1
        row["resource"] = 1
        with self.assertRaises(ValueError):
            validate_tile(row)

    def test_prediction_dependencies(self):
        values = {target: 7 for target in TARGETS}
        values["fog"] = True
        result = apply_dependencies(values)
        self.assertIs(result["road"], False)
        self.assertEqual(result["main_unit.color_name"], "none")
        self.assertEqual(result["terrain"], 0)

    def test_prediction_improvement_suppresses_resource(self):
        self.assertEqual(apply_dependencies({"improvement": 1, "resource": 6})["resource"], 0)

    def test_split_is_deterministic_disjoint_replay_grouped(self):
        ids = [f"r{i}" for i in range(20)]
        split = split_replays(ids)
        self.assertEqual(split, split_replays(list(reversed(ids))))
        self.assertEqual(set(ids), set().union(*map(set, split.values())))
        self.assertEqual(sum(map(len, split.values())), len(ids))
        self.assertTrue(all(split.values()))
        with self.assertRaises(ValueError):
            split_replays(["a", "b"])

    def test_split_manifest_detects_modification(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "train.json"
            save_json(path, [{"replay_id": "a"}])
            metadata = {"partition_sha256": {"train": sha256(path)}, "groups": {"train": ["a"]}}
            self.assertEqual(len(load_partition(folder, metadata, "train")), 1)
            save_json(path, [{"replay_id": "b"}])
            with self.assertRaises(ValueError):
                load_partition(folder, metadata, "train")


@unittest.skipUnless(importlib.util.find_spec("PIL"), "Pillow not installed; no downloads in tests")
class ImageTests(unittest.TestCase):
    def test_rgb_letterbox_preserves_aspect(self):
        from PIL import Image
        from ml.preprocess import letterbox
        output = letterbox(Image.new("RGBA", (100, 50), (255, 0, 0, 255)))
        self.assertEqual(output.mode, "RGB")
        self.assertEqual(output.size, (224, 224))
        self.assertEqual(output.getpixel((112, 55)), (124, 116, 104))
        self.assertEqual(output.getpixel((112, 56)), (255, 0, 0))
        self.assertEqual(output.getpixel((112, 167)), (255, 0, 0))
        self.assertEqual(output.getpixel((112, 168)), (124, 116, 104))

    def test_edge_padding(self):
        from PIL import Image
        from ml.preprocess import tile_image
        result = tile_image(Image.new("RGB", (400, 300), "red"), dict(GRID, anchor=[0, 0]), 0, 0)
        self.assertEqual(result.size, (224, 224))
        self.assertEqual(result.getpixel((0, 0)), (124, 116, 104))

    @staticmethod
    def capture(root, number):
        from PIL import Image
        replay_id = f"00000000-0000-0000-0000-{number:012d}"
        directory = Path(root) / replay_id
        directory.mkdir()
        artifacts = []
        views = [f"player-{p}-{v}" for p in (1, 2) for v in ("normal", "revealed")]
        for stem in views:
            Image.new("RGB", (400, 300), "green").save(directory / (stem + ".png"))
            save_json(directory / (stem + ".grid.json"), GRID)
            player, view = stem[len("player-"):].rsplit("-", 1)
            save_json(directory / (stem + ".tiles.json"), {
                "schema_version": 1, "replay_id": replay_id, "player_id": int(player), "view": view,
                "size": 2, "grid_file": stem + ".grid.json", "mapping_version": "test-pinned",
                "tiles": [tile(x, y) for y in range(2) for x in range(2)]})
            for suffix in (".png", ".grid.json", ".tiles.json"):
                path = directory / (stem + suffix)
                artifacts.append({"Name": path.name, "Length": path.stat().st_size, "Sha256": sha256(path)})
        save_json(directory / "manifest.json", {"ReplayId": replay_id, "MapSize": 2, "SchemaVersion": 1,
                  "MappingVersion": "test-pinned", "PlayerIds": [1, 2], "Views": views, "Artifacts": artifacts,
                  "CaptureSettings": {"ShowGridOverlay": False}})
        return directory

    def test_clean_manifest_and_grouped_prepare(self):
        with tempfile.TemporaryDirectory() as root:
            for number in range(1, 4):
                self.capture(root, number)
            output = Path(root) / "prepared"
            self.assertEqual(prepare(root, output), {"train": 16, "val": 16, "test": 16})
            metadata = json.loads((output / "dataset.json").read_text())
            for split in ("train", "val", "test"):
                rows = load_partition(output, metadata, split)
                self.assertEqual(len({row["replay_id"] for row in rows}), 1)
                self.assertTrue(all(not row["image"].endswith(".grid.png") for row in rows))
            self.assertEqual(metadata["vocabularies"]["main_unit.hp"], [10])

    def test_manifest_tampering_and_legacy_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            directory = self.capture(root, 1)
            load_replay(directory)
            path = directory / "player-1-normal.tiles.json"
            path.write_text("{}")
            with self.assertRaises(ValueError):
                load_replay(directory)


if __name__ == "__main__":
    unittest.main()
