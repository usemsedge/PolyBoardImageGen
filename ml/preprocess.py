"""Geometry-only helpers import without Pillow or PyTorch."""
from dataclasses import asdict, dataclass
import math


@dataclass(frozen=True)
class CropConfig:
    # Extra fractions of the projected ground bounding-box width/height.
    left: float = 0.25
    right: float = 0.5
    above: float = 1.5
    below: float = 0.25
    image_size: int = 224

    def __post_init__(self):
        if any(not math.isfinite(v) or v < 0 for v in
               (self.left, self.right, self.above, self.below)):
            raise ValueError("Context extents must be finite and nonnegative")
        if self.image_size != 224:
            raise ValueError("The pretrained pipeline uses 224 x 224 inputs")

    def to_dict(self):
        return asdict(self)


def validate_grid(grid):
    for key in ("size", "width", "height"):
        value = grid[key]
        if type(value) is not int or value <= 0:
            raise ValueError(f"Invalid grid {key}")
    if grid["size"] > 100 or grid["width"] * grid["height"] > 16_000_000:
        raise ValueError("Grid exceeds capture limits")
    for key in ("anchor", "stepX", "stepY"):
        v = grid[key]
        if len(v) != 2 or any(type(n) not in (int, float) or not math.isfinite(n) for n in v):
            raise ValueError(f"Invalid grid vector {key}")
    a, b = grid["stepX"], grid["stepY"]
    if abs(a[0] * b[1] - a[1] * b[0]) < 1e-10:
        raise ValueError("Degenerate grid")


def crop_box(grid, x, y, config=CropConfig()):
    """Axis-aligned bounds around all four ground corners plus upright context.

    Do NOT affine-rectify the diamond: it shears heads, HP text and the badge.
    Out-of-image bounds are intentionally retained and padded, never clipped.
    """
    validate_grid(grid)
    if not (0 <= x < grid["size"] and 0 <= y < grid["size"]):
        raise ValueError("Tile coordinates outside map")
    sx, sy = grid["stepX"], grid["stepY"]
    cx = grid["anchor"][0] + x * sx[0] + y * sy[0]
    cy = grid["anchor"][1] + x * sx[1] + y * sy[1]
    half_w = (abs(sx[0]) + abs(sy[0])) / 2
    half_h = (abs(sx[1]) + abs(sy[1])) / 2
    if half_w == 0 or half_h == 0:
        raise ValueError("Empty projected tile")
    return (math.floor(cx - half_w - config.left * 2 * half_w),
            math.floor(cy - half_h - config.above * 2 * half_h),
            math.ceil(cx + half_w + config.right * 2 * half_w),
            math.ceil(cy + half_h + config.below * 2 * half_h))


def letterbox(image, size=224):
    from PIL import Image
    image = image.convert("RGB")
    scale = min(size / image.width, size / image.height)
    width = max(1, min(size, round(image.width * scale)))
    height = max(1, min(size, round(image.height * scale)))
    resized = image.resize((width, height), Image.Resampling.BILINEAR)
    canvas = Image.new("RGB", (size, size), (124, 116, 104))
    canvas.paste(resized, ((size - width) // 2, (size - height) // 2))
    return canvas


def tile_image(image, grid, x, y, config=CropConfig()):
    from PIL import Image
    box = crop_box(grid, x, y, config)
    # Fill missing edge context consistently with the letterbox, not black.
    patch = Image.new("RGB", (box[2] - box[0], box[3] - box[1]), (124, 116, 104))
    intersection = (max(0, box[0]), max(0, box[1]),
                    min(image.width, box[2]), min(image.height, box[3]))
    if intersection[0] < intersection[2] and intersection[1] < intersection[3]:
        patch.paste(image.crop(intersection).convert("RGB"),
                    (intersection[0] - box[0], intersection[1] - box[1]))
    return letterbox(patch, config.image_size)


def main():
    import argparse
    import json
    from pathlib import Path
    parser = argparse.ArgumentParser(description="Export a model-input RGB tile crop for inspection")
    parser.add_argument("--image", required=True, type=Path)
    parser.add_argument("--grid", required=True, type=Path)
    parser.add_argument("--x", required=True, type=int)
    parser.add_argument("--y", required=True, type=int)
    parser.add_argument("--output", required=True, type=Path)
    for name, default in (("left", 0.25), ("right", 0.5), ("above", 1.5), ("below", 0.25)):
        parser.add_argument("--context-" + name, type=float, default=default)
    args = parser.parse_args()
    if args.image.name.endswith(".grid.png"):
        parser.error("Use clean capture PNG, never a grid overlay")
    grid = json.loads(args.grid.read_text(encoding="utf-8-sig"))
    crop = CropConfig(args.context_left, args.context_right, args.context_above, args.context_below)
    from PIL import Image
    with Image.open(args.image) as image:
        if image.format != "PNG" or image.size != (grid["width"], grid["height"]):
            raise ValueError("Clean PNG/grid dimensions mismatch")
        result = tile_image(image, grid, args.x, args.y, crop)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result.save(args.output, format="PNG")
    print(f"Saved 224x224 RGB crop to {args.output}")


def tensor_transform():
    from torchvision import transforms
    # No orientation, spatial or color augmentation: all labels share this input.
    return transforms.Compose([
        transforms.ToTensor(),
        transforms.Normalize(mean=(0.485, 0.456, 0.406), std=(0.229, 0.224, 0.225)),
    ])


if __name__ == "__main__":
    main()
