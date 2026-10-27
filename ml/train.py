"""Train a separate pretrained ResNet18 for each semantic annotation target."""
import argparse
from collections import Counter
from pathlib import Path

from .dataset import TARGETS, TileDataset, load_partition, read_json, save_json, sha256, verify_sources
from .evaluate import score
from .model import make_model, resolve_device, seed_everything, seed_worker
from .preprocess import CropConfig, tensor_transform


def train_target(args, metadata, rows, target, device, crop):
    import torch
    seed_everything(args.seed)
    vocabulary = metadata["vocabularies"][target]
    training = TileDataset(rows["train"], target, vocabulary, crop, tensor_transform())
    validation = TileDataset(rows["val"], target, vocabulary, crop, tensor_transform())
    if not len(training) or not len(validation) or len(validation) == validation.unknown_count:
        raise ValueError(f"{target}: train/validation require applicable known labels")
    if training.unknown_count:
        raise ValueError("Training vocabulary does not match split records")
    counts = Counter(row["labels"][target] for row in training.rows)
    weights = None
    if args.class_balance == "inverse":
        weights = torch.tensor([len(training) / (len(vocabulary) * counts[value]) for value in vocabulary],
                               dtype=torch.float32, device=device)
    generator = torch.Generator().manual_seed(args.seed)
    loader = torch.utils.data.DataLoader(training, batch_size=args.batch_size, shuffle=True,
                  num_workers=args.num_workers, worker_init_fn=seed_worker, generator=generator)
    validation_loader = torch.utils.data.DataLoader(validation, batch_size=args.batch_size,
                                                   num_workers=args.num_workers, worker_init_fn=seed_worker)
    model = make_model(len(vocabulary), pretrained=True).to(device)
    for parameter in model.parameters():
        parameter.requires_grad = False
    for parameter in model.fc.parameters():
        parameter.requires_grad = True
    optimizer = torch.optim.AdamW(model.fc.parameters(), lr=args.learning_rate, weight_decay=args.weight_decay)
    criterion = torch.nn.CrossEntropyLoss(weight=weights)
    folder = args.output / target.replace(".", "_")
    folder.mkdir(parents=True)
    save_json(folder / "vocabulary.json", {"target": target, "values": vocabulary})
    best, history = -1.0, []
    for epoch in range(args.epochs):
        if epoch == args.head_epochs:
            for parameter in model.parameters():
                parameter.requires_grad = True
            optimizer = torch.optim.AdamW([
                {"params": [p for name, p in model.named_parameters() if not name.startswith("fc.")],
                 "lr": args.learning_rate * 0.1},
                {"params": model.fc.parameters(), "lr": args.learning_rate},
            ], weight_decay=args.weight_decay)
        head_only = epoch < args.head_epochs
        # Keep frozen backbone batch normalization statistics fixed during warmup.
        model.eval() if head_only else model.train()
        model.fc.train()
        loss_total, examples = 0.0, 0
        for images, labels in loader:
            # Singleton batches cannot update final-stage BatchNorm safely.
            if not head_only and images.shape[0] == 1:
                for module in model.modules():
                    if isinstance(module, torch.nn.BatchNorm2d):
                        module.eval()
            elif not head_only:
                model.train()
            images, labels = images.to(device), labels.to(device)
            optimizer.zero_grad(set_to_none=True)
            loss = criterion(model(images), labels)
            loss.backward()
            optimizer.step()
            loss_total += loss.item() * len(labels)
            examples += len(labels)
        metrics = score(model, validation_loader, device, vocabulary)
        entry = {"epoch": epoch + 1, "head_only": head_only, "train_loss": loss_total / examples,
                 "validation": metrics}
        history.append(entry)
        save_json(folder / "metrics.json", history)
        selection = metrics["macro_f1_supported"]
        if selection is not None and selection > best:
            best = selection
            checkpoint = {"format_version": 1, "architecture": "resnet18", "pretrained": "IMAGENET1K_V1",
                          "target": target, "vocabulary": vocabulary, "crop": crop.to_dict(),
                          "sources": metadata["sources"], "groups": metadata["groups"],
                          "color_palette": metadata["color_palette"], "seed": args.seed,
                          "epoch": epoch + 1, "selection": "validation macro_f1_supported",
                          "class_counts": [counts[value] for value in vocabulary],
                          "state_dict": {key: value.detach().cpu() for key, value in model.state_dict().items()}}
            temporary = folder / "best.pt.tmp"
            torch.save(checkpoint, temporary)
            temporary.replace(folder / "best.pt")
        print(f"{target} epoch={epoch + 1} val_macro_f1={selection}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--target", choices=("all",) + TARGETS, default="all")
    parser.add_argument("--epochs", type=int, default=10)
    parser.add_argument("--head-epochs", type=int, default=2)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--num-workers", type=int, default=0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--learning-rate", type=float, default=1e-3)
    parser.add_argument("--weight-decay", type=float, default=1e-4)
    parser.add_argument("--class-balance", choices=("inverse", "none"), default="inverse")
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    for name, default in (("left", 0.25), ("right", 0.5), ("above", 1.5), ("below", 0.25)):
        parser.add_argument("--context-" + name, type=float, default=default)
    args = parser.parse_args()
    if args.epochs < 1 or not 1 <= args.head_epochs <= args.epochs or args.batch_size < 1 or args.num_workers < 0:
        parser.error("Require positive epochs/batch size, 1 <= head epochs <= epochs, nonnegative workers")
    import math
    if not math.isfinite(args.learning_rate) or args.learning_rate <= 0 or not math.isfinite(args.weight_decay) or args.weight_decay < 0:
        parser.error("Learning rate must be positive and weight decay nonnegative and finite")
    if args.output.exists() and any(args.output.iterdir()):
        parser.error("Use a new/empty output directory; runs never overwrite checkpoints")
    crop = CropConfig(args.context_left, args.context_right, args.context_above, args.context_below)
    metadata = read_json(args.dataset / "dataset.json")
    verify_sources(metadata)
    rows = {split: load_partition(args.dataset, metadata, split) for split in ("train", "val")}
    device = resolve_device(args.device)
    # Fail before creating run outputs if the official pretrained cache is absent.
    make_model(1, pretrained=True)
    args.output.mkdir(parents=True, exist_ok=True)
    config = {key: str(value) if isinstance(value, Path) else value for key, value in vars(args).items()}
    save_json(args.output / "run.json", {"arguments": config, "dataset_sha256": sha256(args.dataset / "dataset.json"),
              "crop": crop.to_dict(), "device": str(device), "sources": metadata["sources"], "groups": metadata["groups"]})
    for target in TARGETS if args.target == "all" else (args.target,):
        train_target(args, metadata, rows, target, device, crop)


if __name__ == "__main__":
    main()
