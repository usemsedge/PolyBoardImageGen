"""Predict one tile with one or several independent target checkpoints."""
import argparse
from pathlib import Path

from .dataset import read_json, save_json
from .model import load_checkpoint, resolve_device
from .preprocess import CropConfig, tensor_transform, tile_image, validate_grid


def apply_dependencies(values):
    """Keep raw per-model outputs separately; normalize only their semantic labels."""
    if values.get("fog") is True:
        for key in list(values):
            if key != "fog":
                values[key] = "none" if key == "main_unit.color_name" else False if key == "road" else 0
    elif values.get("main_unit.type") == 0:
        for key in ("main_unit.tribe_skin", "main_unit.color_name", "main_unit.hp"):
            if key in values:
                values[key] = "none" if key.endswith("color_name") else 0
    if values.get("improvement", 0) != 0 and "resource" in values:
        values["resource"] = 0
    return values


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, type=Path, help="Clean capture PNG, never .grid.png")
    parser.add_argument("--grid", required=True, type=Path)
    parser.add_argument("--x", required=True, type=int)
    parser.add_argument("--y", required=True, type=int)
    parser.add_argument("--checkpoint", required=True, type=Path, nargs="+")
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.image.name.endswith(".grid.png"):
        parser.error("Use the clean image, not a grid overlay")
    import torch
    from PIL import Image
    grid = read_json(args.grid)
    validate_grid(grid)
    device = resolve_device(args.device)
    predictions, labels, palette = {}, {}, None
    mapping_versions = None
    with Image.open(args.image) as source:
        if source.format != "PNG" or source.size != (grid["width"], grid["height"]):
            raise ValueError("Clean image/grid dimensions mismatch")
        source = source.convert("RGB")
        for path in args.checkpoint:
            model, checkpoint = load_checkpoint(path, device)
            target = checkpoint["target"]
            if target in predictions:
                raise ValueError(f"Duplicate checkpoint target {target}")
            current_mapping = {str(s["mapping_version"]) for s in checkpoint["sources"]}
            if mapping_versions is not None and mapping_versions != current_mapping:
                raise ValueError("Cannot combine checkpoints with different mapping versions")
            mapping_versions = current_mapping
            if palette is not None and palette != checkpoint["color_palette"]:
                raise ValueError("Cannot combine checkpoints with different palettes")
            palette = checkpoint["color_palette"]
            patch = tile_image(source, grid, args.x, args.y, CropConfig(**checkpoint["crop"]))
            tensor = tensor_transform()(patch).unsqueeze(0).to(device)
            with torch.inference_mode():
                probabilities = model(tensor).softmax(1)[0]
                confidence, index = probabilities.max(0)
            value = checkpoint["vocabulary"][int(index.item())]
            labels[target] = value
            predictions[target] = {"label": value, "confidence": float(confidence.item())}
    labels = apply_dependencies(labels)
    color = labels.get("main_unit.color_name")
    # A named color can map to the exact observed palette RGB. 'other' is not invertible.
    rgb = [0, 0, 0] if color == "none" else (palette or {}).get(color)
    save_json(args.output, {"x": args.x, "y": args.y, "labels": labels,
                           "raw_predictions": predictions, "main_unit.color_rgb": rgb,
                           "note": "RGB null for other/unseen palette; exact RGB is not recoverable from that class."})
    print(f"Saved tile predictions to {args.output}")


if __name__ == "__main__":
    main()
