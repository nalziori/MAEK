"""Validated synthetic registered thermal-change observations, not defect truth.

The three input channels use measured reference/current apparent temperatures
only. Registration and a valid matched reference are dataset prerequisites; this
loader does not establish either, or infer cracks, wall loss or operational safety.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
from collections.abc import Sequence
from pathlib import Path, PurePosixPath, PureWindowsPath

import numpy as np

TRAINING_SCOPE = "synthetic_registered_thermal_change_segmentation"


def encode_pair(reference, current):
    """Return float32 [reference, current, difference] asinh channels (3,H,W).

    Fixed Celsius center=25, absolute scale=50, difference scale=2. Computation
    in float64 preserves the input float32 difference without intermediate
    overflow. There is no image-specific normalization or clean-field access.
    """
    reference, current = np.asarray(reference), np.asarray(current)
    if (reference.ndim != 2 or reference.shape != current.shape or not reference.size
            or reference.dtype.kind not in "fiu" or current.dtype.kind not in "fiu"):
        raise ValueError("reference/current must be matching nonempty numeric HxW arrays")
    if not np.isfinite(reference).all() or not np.isfinite(current).all():
        raise ValueError("reference/current contain nonfinite temperatures")
    reference, current = reference.astype(np.float64), current.astype(np.float64)
    with np.errstate(over="ignore", invalid="ignore"):
        channels = np.stack((np.arcsinh((reference - 25) / 50),
                             np.arcsinh((current - 25) / 50),
                             np.arcsinh((current - reference) / 2))).astype(np.float32)
    if not np.isfinite(channels).all():
        raise ValueError("Encoded temperatures exceed supported numeric range")
    return channels


class ThermalObservationDataset(Sequence):
    """Index a validated synthetic dataset without importing a training framework.

    ``require_validated=False`` is for the independent dataset validator.
    ``verify_hashes=False`` disables sample integrity checks explicitly; neither
    switch changes allowed training scope, labels or group separation checks.
    Every indexed scene belongs to one split, including unrequested splits.
    """

    def __init__(self, root, split, verify_hashes=True, require_validated=True):
        self.root = Path(root).resolve()
        self.verify_hashes = verify_hashes
        if not self.root.is_dir():
            raise ValueError("Dataset root does not exist")
        self.protocol = self._json("protocol.json")
        self.manifest = self._json("manifest.json")
        if self.manifest.get("training_eligible_scope") != TRAINING_SCOPE:
            raise ValueError(f"Unsupported training scope; required {TRAINING_SCOPE!r}")
        if require_validated:
            validation = self._json("validation.json")
            if validation.get("status") != "passed":
                raise ValueError("Dataset validation status must be passed")
            if validation.get("training_eligible_scope") != TRAINING_SCOPE:
                raise ValueError("Dataset validation scope must match the eligible training scope")
            for key, name in (("manifest_sha256", "manifest.json"),
                              ("protocol_sha256", "protocol.json"),
                              ("index_sha256", "index.jsonl")):
                expected = validation.get(key)
                try:
                    actual = hashlib.sha256(self._path(name).read_bytes()).hexdigest()
                except OSError as exc:
                    raise ValueError(f"Missing metadata for dataset validation: {name}") from exc
                if (not isinstance(expected, str)
                        or not re.fullmatch(r"[0-9a-fA-F]{64}", expected)
                        or actual != expected.lower()):
                    raise ValueError(f"Dataset validation SHA256 mismatch: {name}")
        try:
            lines = self._path("index.jsonl").read_text(encoding="utf-8-sig").splitlines()
            index = [json.loads(line) for line in lines if line.strip()]
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("Missing or invalid index.jsonl") from exc
        ids, paths, groups = set(), set(), {}
        required = ("sample_id", "base_scene_id", "split", "relative_path", "sha256")
        for row in index:
            if not isinstance(row, dict) or any(
                not isinstance(row.get(key), str) or not row[key].strip() for key in required
            ):
                raise ValueError("Invalid index row: missing nonempty string metadata")
            if row["sample_id"] in ids:
                raise ValueError("Duplicate sample_id in index")
            ids.add(row["sample_id"])
            path = self._path(row["relative_path"])
            if path.suffix.lower() != ".npz" or not path.is_file():
                raise ValueError("Sample path must point to an existing .npz file")
            if path in paths:
                raise ValueError("Duplicate sample path in index")
            paths.add(path)
            if not re.fullmatch(r"[0-9a-fA-F]{64}", row["sha256"]):
                raise ValueError("Invalid sha256 in index")
            group = row["base_scene_id"]
            if group in groups and groups[group] != row["split"]:
                raise ValueError("base_scene_id crosses dataset split boundaries")
            groups[group] = row["split"]
        if not isinstance(split, str) or split not in {row["split"] for row in index}:
            raise ValueError(f"Unknown or empty dataset split: {split!r}")
        self._rows = [row for row in index if row["split"] == split]

    def _path(self, relative):
        if (not isinstance(relative, str) or "\\" in relative
                or PurePosixPath(relative).is_absolute() or PureWindowsPath(relative).drive
                or ".." in PurePosixPath(relative).parts):
            raise ValueError("Unsafe dataset relative path")
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("Dataset path escapes root")
        return path

    def _json(self, name):
        try:
            value = json.loads(self._path(name).read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"Missing or invalid {name}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"Invalid object in {name}")  # noqa: TRY004 - serialized schema
        return value

    def __len__(self):
        return len(self._rows)

    def __getitem__(self, index):
        if isinstance(index, slice):
            return [self[i] for i in range(*index.indices(len(self)))]
        row = self._rows[index]
        # Resolve and hash again on access, including after construction.
        payload = self._path(row["relative_path"]).read_bytes()
        if (self.verify_hashes
                and hashlib.sha256(payload).hexdigest() != row["sha256"].lower()):
            raise ValueError(f"Sample SHA256 mismatch: {row['sample_id']}")
        with np.load(io.BytesIO(payload), allow_pickle=False) as arrays:
            if not {"reference_c", "current_c", "target"} <= set(arrays.files):
                raise ValueError("Sample lacks required measured arrays or target")
            reference, current, target = (arrays[k] for k in ("reference_c", "current_c", "target"))
        if reference.dtype != np.float32 or current.dtype != np.float32:
            raise ValueError("Measured reference/current arrays must be float32")
        inputs = encode_pair(reference, current)
        if (target.dtype != np.uint8 or target.shape != reference.shape
                or not np.isin(target, [0, 1, 255]).all()):
            raise ValueError("target must be matching uint8 HxW with labels 0, 1 or 255")
        return {"input": inputs, "target": target,
                "sample_id": row["sample_id"], "base_scene_id": row["base_scene_id"]}
