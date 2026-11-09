"""Freeze rules on independent DR data before evaluating saved v3 thermal images."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np

from maek import params, thermal_rules
from maek import thermal_render as tr
from maek.thermal_dataset import evaluate_arrays, load_zip

SEED = 20261108
DR_COUNT = 120
DR_VALUES = {"thermal.conditions.train.sky_offset_k": [-45, -2],
             "thermal.conditions.train.wind_mps": [0, 9],
             "thermal.conditions.train.sun_k": [0, 12],
             "thermal.eps_set_error.train": 0.1}
CANDIDATES = {"baseline": {}, **thermal_rules.STEAM_CANDIDATES}


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def source_hashes():
    return {name: sha256(ROOT / name) for name in
            ("maek/thermal_render.py", "maek/thermal_rules.py", "maek/thermal_dataset.py",
             "config/default.yaml",
             "scripts/evaluate_thermal_v3.py")}


def mean_recall(metrics):
    values = [row["image_recall"] for row in metrics["classes"].values()]
    return None if any(x is None for x in values) else sum(values) / len(values)


def evaluate(cfg, samples, candidate="baseline"):
    return evaluate_arrays((s["mask"], thermal_rules.detect_ir(
        cfg, s["temperature"], tr.pipe_mask(s["job"]), candidate))
                           for s in samples)


def load_dr(cfg):
    samples = []
    for i, job in enumerate(tr.make_ir_jobs(cfg, DR_COUNT, SEED, "train")):
        temp, mask, _ = tr._render(cfg, job, np.random.default_rng([SEED, i]))
        raw = np.clip(np.rint((temp + 50) * 100), 0, 65535).astype(np.uint16)
        samples.append({"job": job, "temperature": raw.astype(np.float32) / 100 - 50,
                        "mask": mask})
    return samples


def candidate_passes(candidate, baseline):
    dr, base_dr = candidate["dr"], baseline["dr"]
    train, base_train = candidate["train_val"], baseline["train_val"]
    scores = [mean_recall(m) for m in (dr, base_dr, train, base_train)]
    rates = [m["normal_image_false_alarm_rate"] for m in (dr, base_dr, train, base_train)]
    if any(x is None for x in scores + rates):
        return False
    return (scores[0] - scores[1] >= 0.05 and rates[0] - rates[1] <= 0.02
            and scores[2] - scores[3] >= -0.02 and rates[2] - rates[3] <= 0.02
            and all(dr["classes"][c]["image_recall"]
                    - base_dr["classes"][c]["image_recall"] >= -0.05 for c in dr["classes"]))


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                    encoding="utf-8")


def select(args):
    args.output.mkdir(parents=True, exist_ok=True)
    if (args.output / "selection.json").exists():
        raise FileExistsError("Selection already frozen; choose a new output folder")
    cfg = params.load_config()
    dr = load_dr(params.with_values(cfg, DR_VALUES))
    train = list(load_zip(args.zip, "train", "val"))
    if len(train) != 188:
        raise ValueError("Expected 188 train validation images")
    results = {}
    for name, values in CANDIDATES.items():
        results[name] = {"values": values, "dr": evaluate(cfg, dr, name),
                         "train_val": evaluate(cfg, train, name)}
        print(name, "DR", mean_recall(results[name]["dr"]),
              "FA", results[name]["dr"]["normal_image_false_alarm_rate"], flush=True)
    eligible = [n for n in CANDIDATES if n != "baseline"
                and candidate_passes(results[n], results["baseline"])]
    chosen = max(eligible, key=lambda n: mean_recall(results[n]["dr"])) if eligible else "baseline"
    write_json(args.output / "selection.json", {
        "stage": "selection_frozen", "zip_sha256": sha256(args.zip),
        "source_hashes": source_hashes(), "python": sys.version, "platform": platform.platform(),
        "numpy": np.__version__, "dr_seed": SEED, "dr_count": DR_COUNT,
        "dr_parameters": DR_VALUES, "shifted_accessed": False,
        "metric": "Class image recall: >=30% correct GT class pixels; NOT defect recall",
        "pipe_mask": "Synthetic job geometry known (oracle)",
        "selected": chosen, "selected_values": CANDIDATES[chosen], "results": results,
        "reason": "Passed DR selection guards" if eligible else "No candidate passed; retain baseline",
        "criteria": "DR macro +5pp; DR/train FA <=+2pp; train macro >=-2pp; DR class >=-5pp"})
    print("Frozen:", chosen, flush=True)


def final(args):
    frozen = args.output / "selection.json"
    selection = json.loads(frozen.read_text(encoding="utf-8"))
    if selection["stage"] != "selection_frozen" or selection["shifted_accessed"]:
        raise ValueError("Invalid selection")
    if selection["zip_sha256"] != sha256(args.zip) or selection["source_hashes"] != source_hashes():
        raise ValueError("Source or dataset differs from frozen selection")
    if (args.output / "final.json").exists():
        raise FileExistsError("Final evaluation already exists")
    cfg = params.load_config()
    methods = list(dict.fromkeys(["baseline", selection["selected"]]))
    splits = {"train_val": list(load_zip(args.zip, "train", "val")),
              "shifted": list(load_zip(args.zip, "shifted", "train"))
                         + list(load_zip(args.zip, "shifted", "val"))}
    for split, expected in (("train_val", 188), ("shifted", 300)):
        ids = [s["job"]["job_id"] for s in splits[split]]
        if len(ids) != expected or len(set(ids)) != expected:
            raise ValueError("Wrong sample count or duplicate IDs")
    results = {split: {name: evaluate(cfg, samples, name) for name in methods}
               for split, samples in splits.items()}
    write_json(args.output / "final.json", {"selection_sha256": sha256(frozen),
               "zip_sha256": selection["zip_sha256"], "metric": selection["metric"],
               "pipe_mask": selection["pipe_mask"], "results": results})
    rows = []
    for split, methods_result in results.items():
        for method, m in methods_result.items():
            for name, row in m["classes"].items():
                rows.append({"condition": split, "method": method, "class": name,
                             "images": m["image_count"], **row,
                             "normal_images": m["normal_images"],
                             "normal_false_alarms": m["normal_false_alarms"],
                             "legacy_fp_per_image": m["legacy_fp_per_image"],
                             "class_fp_per_image": m["class_fp_per_image"][name],
                             "normal_image_false_alarm_rate": m["normal_image_false_alarm_rate"]})
    with (args.output / "thermal-performance.csv").open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print("Final evaluation written", flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--stage", required=True, choices=("select", "final"))
    p.add_argument("--zip", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    (select if a.stage == "select" else final)(a)


if __name__ == "__main__":
    main()
