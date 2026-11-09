"""Load saved thermal samples and evaluate class-level image detection."""

from __future__ import annotations

import io
import json
import math
from pathlib import Path
from zipfile import ZipFile

import numpy as np
from PIL import Image

from maek import thermal_render as tr

CLASS_NAMES = ("background", "wet_insulation", "insulation_damage", "steam_leak")


def wilson95(successes, n):
    if n < 0 or successes < 0 or successes > n:
        raise ValueError("expected 0 <= successes <= n")
    if n == 0:
        return None
    z = 1.959963984540054
    p = successes / n
    den = 1 + z * z / n
    center = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return [max(0, center - half), min(1, center + half)]


def _index_jobs(raw, condition):
    jobs = json.loads(raw)
    if not isinstance(jobs, list):
        raise TypeError("jobs.json must contain a list")
    indexed = {}
    for job in jobs:
        job_id = job["job_id"]
        if not isinstance(job_id, str) or not job_id or Path(job_id).name != job_id:
            raise ValueError(f"Invalid job ID: {job_id!r}")
        if job_id in indexed:
            raise ValueError(f"Duplicate job ID: {job_id}")
        if job.get("condition") != condition:
            raise ValueError(f"Unexpected condition for {job_id}")
        indexed[job_id] = job
    return indexed


def _split_ids(raw, jobs):
    result, seen = [], set()
    for line in raw.decode("utf-8").splitlines():
        entry = line.strip()
        if not entry:
            continue
        if not entry.startswith("./images/") or not entry.endswith(".png"):
            raise ValueError(f"Invalid split entry: {entry!r}")
        job_id = entry[len("./images/"):-len(".png")]
        if not job_id or "/" in job_id or "\\" in job_id or job_id not in jobs:
            raise ValueError(f"Unknown image ID: {job_id!r}")
        if job_id in seen:
            raise ValueError(f"Duplicate split ID: {job_id}")
        seen.add(job_id)
        result.append(job_id)
    return result


def _decode_sample(image_bytes, mask_bytes, job):
    with Image.open(io.BytesIO(image_bytes)) as image:
        raw = np.asarray(image)
    with Image.open(io.BytesIO(mask_bytes)) as image:
        mask = np.asarray(image)
    if raw.dtype != np.uint16 or raw.ndim != 2:
        raise ValueError(f"{job['job_id']}: expected 16-bit grayscale image")
    if mask.ndim != 2 or mask.shape != raw.shape or not np.isin(mask, (0, 1, 2, 3)).all():
        raise ValueError(f"{job['job_id']}: invalid class mask")
    return {"job": job,
            "temperature": raw.astype(np.float32) / np.float32(100) - np.float32(50),
            "mask": mask.astype(np.uint8)}


def load_split(root, split):
    """Yield saved samples from an extracted condition directory."""
    root = Path(root)
    if split not in ("train", "val"):
        raise ValueError(f"Unknown split: {split}")
    jobs = _index_jobs((root / "jobs.json").read_bytes(), root.name)
    ids = _split_ids((root / f"{split}.txt").read_bytes(), jobs)
    for job_id in ids:
        yield _decode_sample((root / "images" / f"{job_id}.png").read_bytes(),
                             (root / "masks" / f"{job_id}.png").read_bytes(), jobs[job_id])


def load_zip(archive, condition, split):
    """Yield samples from the original ZIP without extracting or modifying it."""
    if condition not in ("train", "shifted"):
        raise ValueError(f"Unknown condition: {condition}")
    if split not in ("train", "val"):
        raise ValueError(f"Unknown split: {split}")
    prefix = f"thermal/{condition}"
    with ZipFile(archive) as dataset:
        names = dataset.namelist()
        if len(names) != len(set(names)):
            raise ValueError("ZIP contains duplicate member names")
        jobs = _index_jobs(dataset.read(f"{prefix}/jobs.json"), condition)
        ids = _split_ids(dataset.read(f"{prefix}/{split}.txt"), jobs)
        for job_id in ids:
            yield _decode_sample(dataset.read(f"{prefix}/images/{job_id}.png"),
                                 dataset.read(f"{prefix}/masks/{job_id}.png"), jobs[job_id])


def evaluate_arrays(pairs):
    """Image hit requires >=30% correctly classified ground-truth class pixels."""
    confusion = np.zeros((4, 4), dtype=np.int64)
    denominators = np.zeros(4, dtype=np.int64)
    hits = np.zeros(4, dtype=np.int64)
    normal_count = normal_false_alarms = image_count = 0
    legacy_fp = 0
    class_fp = {name: 0 for name in CLASS_NAMES[1:]}
    outcomes = []
    for truth, prediction in pairs:
        truth, prediction = np.asarray(truth), np.asarray(prediction)
        if truth.ndim != 2 or truth.shape != prediction.shape:
            raise ValueError("Truth and prediction must be equally shaped 2-D arrays")
        if not np.isin(truth, (0, 1, 2, 3)).all() or not np.isin(
            prediction, (0, 1, 2, 3)
        ).all():
            raise ValueError("Class values must be 0 through 3")
        truth, prediction = truth.astype(np.int64), prediction.astype(np.int64)
        confusion += np.bincount(4 * truth.ravel() + prediction.ravel(),
                                 minlength=16).reshape(4, 4)
        image_count += 1
        outcome = {"hits": {}, "normal": not bool(np.any(truth)),
                   "alarm": bool(np.any(prediction))}
        if not np.any(truth):
            normal_count += 1
            normal_false_alarms += int(np.any(prediction))
        for c in range(1, 4):
            positives = truth == c
            count = int(positives.sum())
            if count:
                denominators[c] += 1
                hit = int(np.count_nonzero(positives & (prediction == c)) / count >= 0.3)
                hits[c] += hit
                outcome['hits'][CLASS_NAMES[c]] = hit
            positive = prediction == c
            if positive.any():
                labels, n = tr.label_components(tr._dilate(positive, 2))
                for k in range(1, n + 1):
                    region = labels == k
                    legacy_fp += int(not np.any(truth[region] != 0))
                    class_fp[CLASS_NAMES[c]] += int(not np.any(truth[region] == c))
        outcomes.append(outcome)
    classes = {}
    for c, name in enumerate(CLASS_NAMES[1:], start=1):
        tp = int(confusion[c, c])
        union = int(confusion[c, :].sum() + confusion[:, c].sum() - tp)
        den, hit = int(denominators[c]), int(hits[c])
        classes[name] = {"iou": tp / union if union else None,
                         "image_recall": hit / den if den else None,
                         "image_hits": hit, "image_denominator": den,
                         "image_recall_ci95": wilson95(hit, den),
                         "true_positive_pixels": tp, "union_pixels": union}
    return {"image_count": image_count, "classes": classes, "confusion": confusion.tolist(),
            "sample_outcomes": outcomes,
            "legacy_fp_per_image": legacy_fp / image_count if image_count else None,
            "class_fp_per_image": {c: n / image_count if image_count else None
                                   for c, n in class_fp.items()},
            "normal_images": normal_count, "normal_false_alarms": normal_false_alarms,
            "normal_image_false_alarm_ci95": wilson95(normal_false_alarms, normal_count),
            "normal_image_false_alarm_rate": (
                normal_false_alarms / normal_count if normal_count else None)}
