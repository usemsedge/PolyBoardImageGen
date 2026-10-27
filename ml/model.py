"""Lazy imports let schema/preprocessing tests run without ML dependencies."""
import random
from pathlib import Path


def seed_everything(seed):
    import torch
    random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True


def seed_worker(worker_id):
    import torch
    random.seed(torch.initial_seed() % 2**32)


def resolve_device(name):
    import torch
    if name == "auto":
        name = "cuda" if torch.cuda.is_available() else "cpu"
    if name == "cuda" and not torch.cuda.is_available():
        raise ValueError("CUDA requested but unavailable")
    return torch.device(name)


def make_model(classes, pretrained=False):
    import torch
    from torchvision.models import ResNet18_Weights, resnet18
    cached = None
    if pretrained:
        weights = ResNet18_Weights.IMAGENET1K_V1
        filename = weights.url.rsplit("/", 1)[-1]
        cached = Path(torch.hub.get_dir()) / "checkpoints" / filename
        if not cached.is_file():
            raise FileNotFoundError(
                f"Pretrained weights are not cached: {cached}. Obtain the official torchvision "
                "ResNet18 IMAGENET1K_V1 weights separately; this CLI never downloads weights.")
        import hashlib
        digest = hashlib.sha256()
        with cached.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        expected_prefix = filename.rsplit("-", 1)[-1].split(".")[0]
        if not digest.hexdigest().startswith(expected_prefix):
            raise ValueError("Cached pretrained checkpoint hash does not match the official weights")
    # Load directly from disk: even a cache race cannot trigger a network download.
    model = resnet18(weights=None)
    if cached is not None:
        model.load_state_dict(torch.load(cached, map_location="cpu", weights_only=True))
    model.fc = torch.nn.Linear(model.fc.in_features, classes)
    return model


def load_checkpoint(path, device):
    import torch
    checkpoint = torch.load(path, map_location="cpu", weights_only=True)
    if checkpoint["format_version"] != 1 or checkpoint["architecture"] != "resnet18":
        raise ValueError("Unsupported checkpoint")
    model = make_model(len(checkpoint["vocabulary"]))
    model.load_state_dict(checkpoint["state_dict"])
    model.to(device).eval()
    return model, checkpoint
