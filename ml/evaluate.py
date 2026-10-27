"""Held-out accuracy, macro F1, per-class scores and explicit unseen-label counts."""
import argparse
from pathlib import Path

from .dataset import TileDataset, load_partition, read_json, save_json, verify_sources
from .model import load_checkpoint, resolve_device
from .preprocess import CropConfig, tensor_transform


def score(model, loader, device, vocabulary):
    import torch
    n = len(vocabulary)
    matrix = [[0] * n for _ in range(n)]
    unknown = 0
    total_loss, known = 0.0, 0
    model.eval()
    with torch.inference_mode():
        for images, labels in loader:
            images, labels = images.to(device), labels.to(device)
            logits = model(images)
            mask = labels >= 0
            unknown += int((~mask).sum().item())
            if mask.any():
                total_loss += torch.nn.functional.cross_entropy(logits[mask], labels[mask], reduction="sum").item()
                known += int(mask.sum().item())
                for actual, predicted in zip(labels[mask].tolist(), logits[mask].argmax(1).tolist()):
                    matrix[actual][predicted] += 1
    per_class = []
    for i, value in enumerate(vocabulary):
        tp = matrix[i][i]
        support = sum(matrix[i])
        predicted = sum(row[i] for row in matrix)
        precision = tp / predicted if predicted else 0.0
        recall = tp / support if support else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_class.append({"label": value, "support": support, "precision": precision, "recall": recall, "f1": f1})
    supported = [item for item in per_class if item["support"]]
    correct = sum(matrix[i][i] for i in range(n))
    return {"known_examples": known, "unknown_label_examples": unknown,
            "loss": total_loss / known if known else None,
            "accuracy_known": correct / known if known else None,
            "accuracy_all": correct / (known + unknown) if known + unknown else None,
            "macro_f1_supported": sum(item["f1"] for item in supported) / len(supported) if supported else None,
            "per_class": per_class, "confusion_matrix": matrix}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--split", choices=("val", "test"), default="test")
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--num-workers", type=int, default=0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.batch_size < 1 or args.num_workers < 0:
        parser.error("Positive batch size and nonnegative workers required")
    import torch
    metadata = read_json(args.dataset / "dataset.json")
    verify_sources(metadata)
    device = resolve_device(args.device)
    model, checkpoint = load_checkpoint(args.checkpoint, device)
    if metadata["sources"] != checkpoint["sources"] or metadata["groups"] != checkpoint["groups"]:
        raise ValueError("Evaluation dataset must match the checkpoint source identities and split")
    dataset = TileDataset(load_partition(args.dataset, metadata, args.split), checkpoint["target"],
                          checkpoint["vocabulary"], CropConfig(**checkpoint["crop"]), tensor_transform())
    loader = torch.utils.data.DataLoader(dataset, batch_size=args.batch_size, num_workers=args.num_workers)
    metrics = score(model, loader, device, checkpoint["vocabulary"])
    save_json(args.output, {"target": checkpoint["target"], "split": args.split, **metrics})
    print(f"Saved {args.split} metrics to {args.output}")


if __name__ == "__main__":
    main()
