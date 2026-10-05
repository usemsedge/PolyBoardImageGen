"""Regression tests for the standalone angled-grid overlay."""

import json
from pathlib import Path
import tempfile
import unittest

import importlib.util

MODULE_PATH = Path(__file__).with_name("draw_grid.py")
spec = importlib.util.spec_from_file_location("draw_grid", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
draw_line = module.draw_line
grid_lines = module.grid_lines
load_grid = module.load_grid
overlay = module.overlay
read_png = module.read_png
write_png = module.write_png


class GridOverlayTests(unittest.TestCase):
    def test_draws_every_boundary_for_supported_sizes(self):
        for size in (1, 8, 16, 20, 30, 100):
            with self.subTest(size=size):
                lines = list(grid_lines(size, (30.0, 60.0), (4.0, -2.0), (-4.0, -2.0)))
                self.assertEqual(len(lines), 2 * (size + 1))
                self.assertEqual(lines[0][0], (30.0, 62.0))
                self.assertEqual(lines[-1][1], (30.0, 60.0 - 4.0 * (size - 0.5)))
                self.assertEqual(lines[-1][0], (28.0 - 4.0 * (size - 0.5), 61.0 - 2.0 * (size - 0.5)))

    def test_rgb_png_round_trip_and_grid_overlay(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            image = path / "map.png"
            output = path / "map.grid.png"
            grid = path / "map.grid.json"
            pixels = bytearray([255] * (8 * 8 * 3))
            write_png(image, 8, 8, 3, pixels)
            grid.write_text(json.dumps({
                "size": 2, "width": 8, "height": 8,
                "anchor": [3, 5], "stepX": [2, -1], "stepY": [-2, -1],
            }), encoding="utf-8")
            original = image.read_bytes()
            overlay(grid, image, output)
            self.assertEqual(image.read_bytes(), original)
            width, height, channels, result = read_png(output)
            self.assertEqual((width, height, channels), (8, 8, 3))
            self.assertIn(b"\xff\x00\x00", result)
            self.assertEqual(read_png(image)[3], pixels)

    def test_preserves_fractional_grid_coordinates(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            grid = path / "fractional.grid.json"
            values = {
                "size": 16, "width": 80, "height": 60,
                "anchor": [43.125, 51.875],
                "stepX": [2.625, -1.375],
                "stepY": [-2.625, -1.375],
            }
            grid.write_text(json.dumps(values), encoding="utf-8")
            size, _, _, anchor, step_x, step_y = load_grid(grid)
            self.assertEqual((size, anchor, step_x, step_y),
                             (16, (43.125, 51.875), (2.625, -1.375), (-2.625, -1.375)))
            lines = list(grid_lines(size, anchor, step_x, step_y))
            self.assertEqual(lines[0][0], (43.125, 53.25))

    def test_twenty_by_twenty_overlay(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            image = path / "twenty.png"
            grid = path / "twenty.grid.json"
            output = path / "twenty.grid.png"
            write_png(image, 160, 100, 3, bytearray([255] * (160 * 100 * 3)))
            grid.write_text(json.dumps({
                "size": 20, "width": 160, "height": 100,
                "anchor": [80, 80], "stepX": [3, -1.5], "stepY": [-3, -1.5],
            }), encoding="utf-8")
            overlay(grid, image, output)
            result = read_png(output)[3]
            self.assertIn(b"\xff\x00\x00", result)
            self.assertEqual(len(result), 160 * 100 * 3)

    def test_rgba_and_clipped_lines(self):
        pixels = bytearray([0] * (4 * 4 * 4))
        draw_line(pixels, 4, 4, 4, (-5000.0, 1.0), (5000.0, 1.0))
        self.assertEqual(pixels[(1 * 4 + 0) * 4:(1 * 4 + 0) * 4 + 4], b"\xff\x00\x00\xff")
        self.assertEqual(pixels[(1 * 4 + 3) * 4:(1 * 4 + 3) * 4 + 4], b"\xff\x00\x00\xff")

    def test_rejects_out_of_range_size_and_invalid_vectors(self):
        with tempfile.TemporaryDirectory() as directory:
            grid = Path(directory) / "map.grid.json"
            valid = {"size": 100, "width": 80, "height": 40,
                     "anchor": [40, 30], "stepX": [2, -1], "stepY": [-2, -1]}
            grid.write_text(json.dumps(valid), encoding="utf-8")
            self.assertEqual(load_grid(grid)[0], 100)
            for invalid in (0, 101, 1.5, True):
                with self.subTest(size=invalid):
                    grid.write_text(json.dumps({**valid, "size": invalid}), encoding="utf-8")
                    with self.assertRaises(ValueError):
                        load_grid(grid)
            grid.write_text(json.dumps({**valid, "stepY": [4, -2]}), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_grid(grid)

    def test_rejects_dimensions_that_do_not_match_image(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            image = path / "map.png"
            grid = path / "map.grid.json"
            write_png(image, 2, 2, 3, bytearray(2 * 2 * 3))
            grid.write_text(json.dumps({
                "size": 1, "width": 3, "height": 2,
                "anchor": [1, 1], "stepX": [1, 0], "stepY": [0, 1],
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "dimensions"):
                overlay(grid, image, path / "out.png")


if __name__ == "__main__":
    unittest.main()
