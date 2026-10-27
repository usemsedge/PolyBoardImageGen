# Tile annotation classifiers

Independent Python/PyTorch tooling for the annotation-enabled captures specified in
`../output_format.md`. Nothing here changes or runs the game mod. No packages or
weights have been downloaded and no training quality is claimed.

## Setup and commands

Run commands from the repository root, with Python 3.10+ in a virtual environment.
Install `ml/requirements.txt` yourself after selecting a compatible torch/torchvision
pair for your CPU or CUDA runtime. Python 3.10-3.12 generally has broad wheel support.
For example, in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r ml/requirements.txt
python -m unittest discover -s ml/tests -v
python -m ml.dataset --captures Maps/replay-captures --output ml-data
python -m ml.preprocess --image Maps/replay-captures/REPLAY/player-1-normal.png --grid Maps/replay-captures/REPLAY/player-1-normal.grid.json --x 3 --y 4 --output crop.png
python -m ml.train --dataset ml-data --output ml-runs/first --target all --device auto
python -m ml.evaluate --dataset ml-data --checkpoint ml-runs/first/terrain/best.pt --output ml-runs/first/terrain/test.json
python -m ml.predict --image Maps/replay-captures/REPLAY/player-1-normal.png --grid Maps/replay-captures/REPLAY/player-1-normal.grid.json --x 3 --y 4 --checkpoint ml-runs/first/terrain/best.pt --output prediction.json
```

Training requires the **official torchvision ResNet18 IMAGENET1K_V1** checkpoint
already present in `torch.hub.get_dir()/checkpoints/resnet18-f37072fd.pth`.
Provision that file separately from a trusted source before training. The CLI
fails when it is absent; it does not silently download weights or fall back to
random initialization. Evaluation/prediction reconstruct the network without
pretrained weights, then load the trained state. Use trusted local checkpoints
only (`torch.load(..., weights_only=True)`).

Use `--target terrain` (or another target below) for one classifier. `all` trains
11 separate networks sequentially, each with its own copied pretrained backbone,
classification head, vocabulary, checkpoint and metrics. There is no shared
multi-head model. Default training: 10 epochs, 2 head-only warmup epochs, then full
fine-tuning at a 10x smaller backbone learning rate. Set `--head-epochs` equal to
`--epochs` to train only the head. CLI help lists learning rate, batch size,
weight decay, class weighting, seed and context options. Training is not resumable.
Use a new output directory for each experiment.

`--device auto|cpu|cuda` is supported. `--num-workers 0` is the Windows-safe
default; module entry points are guarded for multiprocessing spawn. Seeds cover
Python, torch, CUDA and loader workers; deterministic cuDNN is requested, but
bitwise equivalence across hardware/versions is not guaranteed. No automatic mixed
precision or external experiment service is required.

## Input validation and grouping

Only published UUID directories containing `manifest.json` are considered; staging
and invalid directories are ignored. At least **three distinct replays** are
required so every split can contain a replay. Legacy image-only exports are
rejected: recapture using the annotation-enabled mod first.

The loader accepts PascalCase or snake_case manifest identity/artifact properties;
annotation/grid property names follow `output_format.md`. It requires two players,
all four normal/revealed views, clean PNG + grid JSON + annotation JSON for each,
and a mapping version. Every listed artifact's byte length/SHA-256 is checked,
including overlays when present; enabled overlays must all exist and disabled
ones must not be listed. Overlays are never model inputs. Clean PNG dimensions,
grid vectors/determinant, annotation identities, row order, tile count, coordinate
uniqueness, fog placeholders, categorical types and basic label ranges are checked.
The ingestion layer assumes the producer already enforced the pinned full enum,
appearance and exact readable-palette tables; it does not invent replacements for
that authoritative mapping. It rejects mixed mapping versions.

Replay UUIDs are canonicalized before grouping. SHA-256 ordering of `seed:UUID`
produces deterministic approximately 70/15/15 train/validation/test partitions,
with at least one replay each. All tiles and four views of a replay stay together.
Adding replays can change assignments: persist/reuse a prepared dataset, do not
independently prepare train and test. This is replay grouping, not stratification;
very rare labels may be absent from train or validation.

Preparation writes `dataset.json` with replay groups, source manifest hashes,
mapping versions, training-only target vocabularies and observed name-to-exact-RGB
palette, plus `train.json`, `val.json`, `test.json` records with absolute source
paths. Keep the source captures in place. Training/evaluation revalidate original
capture artifacts and prepared partition hashes. Moving data requires preparing a
new dataset. These metadata files are trusted local build products, not a secure
signed dataset format.

Vocabularies contain **training labels only**, never held-out labels. Unseen
validation/test labels get index -1: report them explicitly and count them as
incorrect in `accuracy_all`, while known-label loss/F1/confusion counts exclude
them. Validation selects the best checkpoint by macro F1 across supported known
classes; targets with no applicable known validation examples fail rather than
select meaningless weights. Inspect unknown counts before interpreting results.
A one-class dataset is accepted as a trivial baseline, not evidence of learning.

## Crop and pretrained input

The exported center is `anchor + x*stepX + y*stepY`. The four tile corners are the
center plus/minus half each basis vector. An axis-aligned bounding crop extends
beyond the ground diamond by these configurable fractions of its projected
bounding-box width/height:

- left 0.25; right 0.50 (top-right circular icon context);
- above 1.50 (upright unit/head/HP/badge); below 0.25.

For example: `--context-above 2 --context-right 0.75`. Context settings are saved
with every checkpoint and reused exactly for evaluation/prediction. Units can
exceed these heuristic defaults: inspect representative crops and tune before
long training. Neighboring artwork can enter context; this is a contextual tile
classifier, not an instance segmentation system. Occluded or undrawn ground-state
labels can be intrinsically ambiguous from pixels.

**Do not affine-rectify the isometric ground** for this shared input: doing so
shears upright unit art, text and badges. Preserve screen orientation and aspect
ratio; pad out-of-frame context, resize with bilinear interpolation and letterbox
to RGB 224x224 without stretching or center cropping. Padding uses approximately
ImageNet mean RGB. Apply ImageNet mean/std tensor normalization, appropriate to
the pretrained ResNet18. No flip, rotation, perspective, random spatial crop, or
color jitter is used in either training or inference. In particular, jitter would
corrupt the base-color task. There is deliberately no augmentation in this baseline.

## Semantic targets and applicability

All values are semantic **categorical** labels, including numeric enum IDs and HP:

| Independent classifier | Labels / applicability |
| --- | --- |
| `fog` | Boolean; every tile, including fogged ones. |
| `improvement`, `resource`, `terrain` | Exported enum category; zero is an ordinary valid absent/NONE class when unfogged. |
| `road` | Exported explicit boolean, not inferred connectivity. |
| `terrain_tribe_skin` | Compact effective appearance 0-32. |
| `main_unit.type` | Visible main unit type, including 0 absent. |
| `main_unit.tribe_skin` | Compact effective unit appearance, including 0 absent. |
| `main_unit.color_name` | Exact readable palette name, `other`, or `none` absent. |
| `main_unit.hp` | Nonnegative integer displayed HP as categories; **exclude absent main units** rather than teach their placeholder zero. Present unit HP=0, if exported, remains a class. |
| `top_right_unit_icon.type` | Actually displayed icon type, including 0 absent; not assumed equal to main unit. |

Fogged tiles are excluded from **every target except fog**. Their zero labels are
masked unknowns, not absence observations. Unfogged absent units retain zero/none
classes for type/appearance/color; HP has the explicit exclusion above. Dependencies
remain important despite independent models. Prediction retains raw labels and
confidence, then masks semantic outputs when a supplied fog classifier says true,
and normalizes main-unit attributes when a supplied type classifier says absent.
An icon is independent and is not zeroed merely because the main unit is absent.
Without those gate checkpoints, prediction cannot enforce their dependencies.

Coordinates, player/replay IDs, grid/image geometry, source tribe/skin IDs and raw
RGB are **metadata, not additional classifiers**. `terrain_appearance` and the
unit's `tribe_id`/`skin_id` duplicate the compact identity target; decoding them
requires the pinned source mapping, not separately trained contradictory models.
Color classification uses readable palette names, not arbitrary RGB triples.
Preparation saves observed exact name-to-RGB mappings and rejects conflicting RGB
for a single named color; prediction provides this RGB for named classes. `none`
maps to absent [0,0,0]. `other` cannot recover an arbitrary original RGB, so predicted
RGB is null. Preserve source RGB in original annotations for exact ground truth.

## Outputs and limitations

Each target directory contains `vocabulary.json`, `best.pt`, and per-epoch
`metrics.json`; the run root stores arguments, crop, split/source identities and
seed in `run.json`. Checkpoints include architecture, preprocessing, pretrained
identity, training class counts, source/split metadata, palette and target vocabulary.
Inverse-frequency weighted cross entropy is default (`--class-balance none` disables
it); it uses only training counts. Evaluation writes loss, known/all accuracy,
supported-class macro F1, per-class precision/recall/F1/support and numeric confusion
matrix. No test data participates in optimization or checkpoint selection.

No dataset is bundled. No training, accuracy, unit visibility, crop coverage, or
in-game annotation correctness has been demonstrated. Geometry/semantic tests run
with the standard library; Pillow integration tests skip when Pillow is unavailable.
An actual cached-weight CPU/CUDA smoke test and evaluation on held-out captures are
still required before using model outputs downstream. Full-capture decoding,
instance detection, calibrated confidence, experiment resumption, OCR-specific HP
heads, and exact arbitrary RGB regression are out of scope for this baseline.
