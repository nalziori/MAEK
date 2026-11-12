"""Colab follow-up: diagnose v1, calibrate independently, and train a DR CNN.

No training or large simulation is performed on import. Local diagnosis is CPU-only.
Ground-truth wall thickness is never supplied to the benchmark MLP.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import random
import shutil
import sys
import time
import zipfile
from pathlib import Path

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

import numpy as np
import pandas as pd
import torch
from scipy.stats import beta, rankdata
from torch import nn
from torch.utils.data import DataLoader, TensorDataset


class PitCNN(nn.Module):
    """Same architecture as v1: isolate data/preprocessing from capacity changes."""

    def __init__(self):
        super().__init__()
        self.features = nn.Sequential(
            nn.Conv1d(1, 16, 9, padding=4), nn.ReLU(), nn.MaxPool1d(2),
            nn.Conv1d(16, 32, 7, padding=3), nn.ReLU(), nn.MaxPool1d(2),
            nn.Conv1d(32, 64, 5, padding=2), nn.ReLU(), nn.MaxPool1d(2),
            nn.AdaptiveAvgPool1d(32),
        )
        self.classifier = nn.Sequential(
            nn.Flatten(), nn.Linear(2048, 64), nn.ReLU(),
            nn.Dropout(0.2), nn.Linear(64, 1),
        )

    def forward(self, x):
        return self.classifier(self.features(x)).squeeze(-1)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_once(path, obj):
    path = Path(path)
    if path.exists():
        if read(path) != obj:
            raise ValueError(f"Existing record differs: {path}")
    else:
        path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")


def auc(y, scores):
    y = np.asarray(y, bool)
    p, n = int(y.sum()), int((~y).sum())
    if not p or not n:
        return None
    return float((rankdata(scores)[y].sum() - p * (p + 1) / 2) / (p * n))


def select_threshold(normal, confidence=0.95, target=0.007):
    normal = np.asarray(normal, dtype=float)
    if normal.ndim != 1 or not len(normal) or not np.isfinite(normal).all():
        raise ValueError("Expected a finite, nonempty normal-score vector")
    n = len(normal)
    k = np.arange(n)
    upper = beta.ppf(confidence, k + 1, n - k)
    feasible = k[upper <= target]
    if not len(feasible):
        raise ValueError("Insufficient independent normal calibration samples")
    allowed = int(feasible[-1])
    threshold = float(np.sort(normal)[n - allowed - 1])
    return {"threshold": threshold, "normal_n": n,
            "allowed": allowed, "upper": float(upper[allowed]),
            "observed_fp": int((normal > threshold).sum()),
            "confidence": confidence, "target_far": target}


def summary(name, domain, y, scores, threshold):
    positive = np.asarray(y, bool)
    predicted = np.asarray(scores) > threshold
    row = {"model": name, "domain": domain, "threshold": threshold,
           "auc": auc(positive, scores)}
    for key, mask in [("recall", positive), ("far", ~positive)]:
        n = int(mask.sum())
        hits = int(predicted[mask].sum())
        row[key] = hits / n if n else None
        row[key + "_count"] = hits
        row[key + "_n"] = n
        row[key + "_lo"] = float(beta.ppf(.025, hits, n - hits + 1)) if hits else 0.
        row[key + "_hi"] = float(beta.ppf(.975, hits + 1, n - hits)) if hits < n else 1.
    return row


def checkpoint(path, device="cpu"):
    ck = torch.load(path, map_location="cpu", weights_only=True)
    net = PitCNN().to(device)
    net.load_state_dict(ck["state_dict"])
    net.eval()
    return net, ck


def logits(net, signals, prep, device="cpu"):
    outputs = []
    with torch.inference_mode():
        for start in range(0, len(signals), 256):
            x = (signals[start:start + 256].astype(np.float32) - prep["rf_mean"]) / prep["rf_std"]
            x = torch.from_numpy(np.ascontiguousarray(x[:, None])).to(device)
            outputs.append(net(x).cpu().numpy())
    result = np.concatenate(outputs)
    if not np.isfinite(result).all():
        raise ValueError("Nonfinite logits")
    return result


def archive_data(path, split):
    with zipfile.ZipFile(path) as z:
        with np.load(io.BytesIO(z.read(f"ut/{split}/ut_straight.npz")), allow_pickle=False) as a:
            x = a["signals"].astype(np.float32)
        meta = pd.read_csv(z.open(f"ut/{split}/ut_labels.csv"))
    if len(x) != len(meta) or x.shape[1:] != (4096,) or not np.isfinite(x).all():
        raise ValueError("Invalid waveform archive")
    if set(meta.n_avg.unique()) != {16}:
        raise ValueError("This experiment requires n_avg=16")
    return x, meta, (meta.pit_depth_mm.to_numpy() > 0).astype(np.int64)


def mlp_scores(signals, temperatures, cal, baseline):
    from maek import pit, ut

    started = time.perf_counter()
    features = []
    for i, (rf, temperature) in enumerate(zip(signals, temperatures, strict=True)):
        # No oracle wall: the absent nominal wall is estimated from this A-scan.
        wall = float(ut.estimate_thickness(cal, rf, float(temperature)))
        if not np.isfinite(wall) or wall <= 0:
            raise ValueError(f"Invalid waveform-estimated thickness at row {i}")
        features.append(pit.features(cal, pit.analyse(cal, rf, wall, float(temperature))))
        if (i + 1) % 500 == 0:
            print(f"MLP 특징 추출 {i + 1}/{len(signals)}", flush=True)
    features = np.asarray(features, np.float32)
    predictions = []
    for seed in (1601, 1602, 1603):
        ck = torch.load(baseline / f"mlp_{seed}.pt", map_location="cpu", weights_only=True)
        model = nn.Sequential(nn.Linear(7, 16), nn.Tanh(), nn.Linear(16, 1)).eval()
        model.load_state_dict(ck["state"])
        with torch.inference_mode():
            x = (features - np.asarray(ck["mean"])) / np.asarray(ck["std"])
            predictions.append(model(torch.tensor(x, dtype=torch.float32)).sigmoid().numpy()[:, 0])
    scores = np.mean(predictions, axis=0)
    if not np.isfinite(scores).all():
        raise ValueError("Nonfinite MLP scores")
    print(f"MLP 특징 추출+CPU 추론: {time.perf_counter() - started:.2f}초", flush=True)
    return scores


def diagnose(run, archive, out):
    record = read(run / "cnn_threshold.json")
    if sha(archive) != record["dataset_sha256"] or sha(run / "cnn_best.pt") != record["model_sha256"]:
        raise ValueError("Original model/data hash mismatch")
    if sha(run / "cnn_split_indices.npz") != record["split_sha256"]:
        raise ValueError("Original split hash mismatch")
    with np.load(run / "cnn_split_indices.npz", allow_pickle=False) as f:
        split = {k: f[k].copy() for k in f.files}
    x, meta, y = archive_data(archive, "train")
    sx, sm, sy = archive_data(archive, "shifted")
    normal = split["calibration"][y[split["calibration"]] == 0]
    packs = {"calibration": (x[normal], meta.iloc[normal], y[normal]),
             "ordinary": (x[split["test"]], meta.iloc[split["test"]], y[split["test"]]),
             "shifted": (sx, sm, sy)}
    cal = read(run / "baseline/normal_ut_reviewed_v1/calibrated_config.json")
    net, ck = checkpoint(run / "cnn_best.pt")
    scores = {}
    frames = []
    for domain, (rf, metadata, labels) in packs.items():
        cache = out / f"diagnostic_{domain}.npz"
        if cache.exists():
            with np.load(cache, allow_pickle=False) as d:
                m, c = d["mlp"].copy(), d["cnn_logit"].copy()
        else:
            m = mlp_scores(rf, metadata.temp_meas_c.to_numpy(), cal,
                           run / "baseline/normal_ut_reviewed_v1")
            c = logits(net, rf, ck["preprocessing"])
            np.savez_compressed(cache, mlp=m, cnn_logit=c, y=labels)
        scores[domain] = (m, c)
        frames.append(pd.DataFrame({"domain": domain, "y": labels, "mlp": m, "cnn_logit": c}))
    threshold = select_threshold(scores["calibration"][0])
    old_logit_threshold = float(np.log(record["threshold"] / (1 - record["threshold"])))
    rows = []
    for domain in ("ordinary", "shifted"):
        labels = packs[domain][2]
        rows.append(summary("MLP_waveform_wall", domain, labels, scores[domain][0], threshold["threshold"]))
        rows.append(summary("CNN_v1_frozen", domain, labels, scores[domain][1], old_logit_threshold))
    table = pd.DataFrame(rows)
    table.to_csv(out / "diagnosis.csv", index=False)
    pd.concat(frames).to_csv(out / "diagnostic_scores.csv", index=False)
    write_once(out / "diagnosis_conditions.json", {
        "mlp_input": "7 features; waveform-estimated wall + measured temperature, no oracle wall",
        "mlp_threshold": threshold,
        "cnn_score": "logit (avoids saturated float32 sigmoid ties)",
        "status": "development diagnosis; original shifted already inspected",
    })
    print(table.to_string(index=False), flush=True)


def averaged_array(path, key):
    """Read only averaging index 1 from a compressed NPY member (bounded memory)."""
    with zipfile.ZipFile(path) as archive, archive.open(key + ".npy") as stream:
        version = np.lib.format.read_magic(stream)
        if version not in ((1, 0), (2, 0)):
            raise ValueError("Unsupported NPY header")
        reader = np.lib.format.read_array_header_1_0 if version == (1, 0) else np.lib.format.read_array_header_2_0
        shape, fortran, dtype = reader(stream)
        if fortran or dtype.hasobject or shape[0] != 2:
            raise ValueError("Expected numeric C-order data with two averaging settings")
        nbytes = int(np.prod(shape[1:])) * dtype.itemsize
        stream.seek(nbytes, 1)
        raw = stream.read(nbytes)
        if len(raw) != nbytes:
            raise ValueError("Truncated NPY member")
        return np.frombuffer(raw, dtype=dtype).reshape(shape[1:])


def diagnose_b(run, source, out):
    """B-team original benchmark, preserving saved feature priors and thresholds."""
    original = read(run / "cnn_threshold.json")
    if sha(run / "cnn_best.pt") != original["model_sha256"]:
        raise ValueError("Original CNN checkpoint changed")
    files = ["calibration_normals.npz", "test_ordinary.npz", "test_shifted.npz",
             "test_ordinary_predictions.npz", "test_shifted_predictions.npz",
             "frozen_decisions.json", "final_results.json"]
    write_once(out / "b_source_hashes.json", {name: sha(source / name) for name in files})
    frozen = read(source / "frozen_decisions.json")
    reference = read(source / "final_results.json")
    net, ck = checkpoint(run / "cnn_best.pt")
    cal_cache = out / "b_cnn_calibration_logits.npy"
    if cal_cache.exists():
        calibration_scores = np.load(cal_cache, allow_pickle=False)
    else:
        rf = averaged_array(source / "calibration_normals.npz", "RF")
        calibration_scores = logits(net, rf, ck["preprocessing"])
        np.save(cal_cache, calibration_scores)
        del rf
    with np.load(source / "calibration_normals.npz", allow_pickle=False) as d:
        temperature = d["observed"]
    # Use observed temperature only, independent of labels/scores.
    thresholds = {name: select_threshold(calibration_scores[mask], .975) for name, mask in
                  [("below90", temperature < 90), ("at_least90", temperature >= 90)]}
    threshold = max(row["threshold"] for row in thresholds.values())
    write_once(out / "b_cnn_recalibration.json", {
        "threshold_logit": threshold, "strata": thresholds,
        "model_sha256": sha(run / "cnn_best.pt"),
        "rule": "logit > threshold; one global conservative threshold",
        "scope": "B-team historical benchmark; independent normal calibration, no test threshold tuning",
    })
    old_threshold = float(np.log(original["threshold"] / (1 - original["threshold"])))
    rows = []
    arms = ["B_existing_MLP_no_hard_gate", "C_MF_CFAR_no_extra_gate", "D_new_MLP_no_hard_gate"]
    for domain in ("ordinary", "shifted"):
        path = source / f"test_{domain}.npz"
        with np.load(path, allow_pickle=False) as d:
            labels, audit = d["y"], d["labels"]
        features = averaged_array(path, "X")
        with np.load(source / f"test_{domain}_predictions.npz", allow_pickle=False) as d:
            if not np.array_equal(labels, d["y"]):
                raise ValueError("Saved prediction labels differ")
            saved = d["scores"][1]
        # Replay all original threshold groups and verify integer counts.
        hot = audit[:, 4] >= 90
        edges = frozen["edges"]["16"]
        groups = hot.astype(int) * 2 + (features[:, 3] > np.where(hot, edges[1], edges[0])).astype(int)
        predictions = {"y": labels.astype(int)}
        for i, arm in enumerate(arms):
            per_row = np.array([frozen["thresholds"][f"16:0.007:{arm}:{g}"]["threshold"] for g in groups])
            decision = saved[:, i] > per_row
            expected = next(r for r in reference["detection"] if r["condition"] == domain
                            and r["n_avg"] == 16 and r["operating_far"] == .007 and r["arm"] == arm)
            tp, fp = int(decision[labels].sum()), int(decision[~labels].sum())
            if (tp, fp) != (expected["tp"], expected["fp"]):
                raise ValueError(f"B-team count mismatch: {domain}, {arm}")
            row = summary(arm, domain, labels, decision.astype(float), .5)
            row["threshold"] = "original four strata"
            row["auc"] = auc(labels, saved[:, i])
            row["provenance"] = "saved scores + replayed original decisions"
            rows.append(row)
            predictions[arm] = saved[:, i]
        cache = out / f"b_cnn_{domain}_logits.npy"
        if cache.exists():
            values = np.load(cache, allow_pickle=False)
        else:
            rf = averaged_array(path, "RF")
            values = logits(net, rf, ck["preprocessing"])
            np.save(cache, values)
            del rf
        for label, th in [("CNN_v1_original", old_threshold), ("CNN_v1_recalibrated", threshold)]:
            row = summary(label, domain, labels, values, th)
            row["provenance"] = "new CPU inference, frozen v1 weights"
            rows.append(row)
        predictions["cnn_logit"] = values
        pd.DataFrame(predictions).to_csv(out / f"b_{domain}_predictions.csv", index=False)
    table = pd.DataFrame(rows)
    table.to_csv(out / "b_comparison.csv", index=False)
    print(table.to_string(index=False), flush=True)


def protocol():
    return {
        "version": 1, "seed_model": 2026110908,
        "seeds": {"train": 202611091801, "validation": 202611091802,
                  "calibration_ordinary": 202611091803, "calibration_shifted": 202611091804,
                  "final_ordinary": 202611091805, "final_shifted": 202611091806},
        "counts": {"train": 8000, "validation": 2000,
                   "calibration_ordinary": 6000, "calibration_shifted": 6000,
                   "final_ordinary": 4000, "final_shifted": 4000},
        "architecture": "same PitCNN as v1 (145281 parameters)",
        "max_epochs": 45, "patience": 8, "lr": 0.001, "batch_size": 128,
        "selection": "minimum mixed-domain validation BCE; no final-test selection",
        "calibration": "max of two domain thresholds, 97.5% each, target FAR 0.007",
        "generator": {
            "wall_mm": [3, 16], "depth_fraction": [.1, .6], "pit_area_fraction": [.1, .5],
            "ordinary": {"temperature": [10, 80], "coupling": [.7, 1], "noise": 1, "temp_error_sd": 2},
            "shifted": {"temperature": [100, 175], "coupling": [.3, .7], "noise": 3, "temp_error_sd": 15},
            "v_long_offset": [-70, 70], "pulse_frequency_multiplier": [.9, 1.1],
            "pulse_width_multiplier": [.85, 1.15], "delay_offset_us": [-.03, .03],
            "n_avg": 16, "storage": "float16 roundtrip then float32 (same as data-v3)",
        },
        "limitation": "Independent draws from the same approximate forward-model family, not field validation",
    }


def load_dataset(path, name, spec):
    n = spec["counts"][name]
    shapes = {"RF": (n, 4096), "y": (n,), "domain": (n,),
              "observed_temperature": (n,), "audit": (n, 8)}
    with np.load(path, allow_pickle=False) as data:
        if set(data.files) != set(shapes):
            raise ValueError("Dataset keys differ from protocol")
        result = {key: data[key] for key in shapes}
    for key, shape in shapes.items():
        if result[key].shape != shape or not np.isfinite(result[key]).all():
            raise ValueError(f"Invalid dataset array: {key}")
    if not np.isin(result["y"], [0, 1]).all() or not np.isin(result["domain"], [0, 1]).all():
        raise ValueError("Invalid labels/domain")
    if name.startswith("calibration") and result["y"].any():
        raise ValueError("Calibration must contain normals only")
    if name not in ("train", "validation") and not (
        result["domain"] == int(name.endswith("shifted"))
    ).all():
        raise ValueError("Unexpected domain")
    return result


def save_dataset(target, result, name, spec):
    # Publish the final name only after the archive is closed and read-back verified.
    # Drive sync is not a transaction; validation is still required on every resume.
    temporary = target.with_suffix(".npz.partial")
    print(f"{name}: 압축 저장 및 검증 중", flush=True)
    with temporary.open("wb") as stream:
        np.savez_compressed(stream, **result)
    load_dataset(temporary, name, spec)
    os.replace(temporary, target)
    print(f"{name}: 저장 완료", flush=True)


def recover_data(source, out, spec):
    if read(source / "protocol.json") != spec:
        raise ValueError("Recovery protocol differs")
    previous, current = read(source / "inputs.json"), read(out / "inputs.json")
    old_script = previous.pop("script_sha256")
    current.pop("script_sha256")
    if old_script != "70f673cf23e4798100d8e661e33e82548656ae6dfd477c839fa947a710c604f4" or previous != current:
        raise ValueError("Recovery inputs differ from the known original experiment")
    for name in ("train", "validation", "calibration_ordinary", "calibration_shifted"):
        src, target = source / f"{name}.npz", out / f"{name}.npz"
        if target.exists() or not src.exists():
            continue
        print(f"복구 검사: {name}", flush=True)
        try:
            load_dataset(src, name, spec)
        except (zipfile.BadZipFile, EOFError, ValueError, OSError) as error:
            print(f"재생성 필요: {name} ({type(error).__name__}); 원본 보존", flush=True)
            continue
        temporary = target.with_suffix(".npz.partial")
        shutil.copyfile(src, temporary)
        if sha(src) != sha(temporary):
            raise ValueError("Recovery copy hash mismatch")
        load_dataset(temporary, name, spec)
        os.replace(temporary, target)
        print(f"정상 파일 복구 완료: {name}", flush=True)


def generate(name, out, cfg, spec):
    from maek import params, ut

    target = out / f"{name}.npz"
    if target.exists():
        print(f"{name}: 기존 파일 검증 중", flush=True)
        result = load_dataset(target, name, spec)
        print(f"{name}: 검증 완료, 재사용", flush=True)
        return result
    rng = np.random.default_rng(spec["seeds"][name])
    n = spec["counts"][name]
    print(f"{name}: 생성 시작 (총 {n}개)", flush=True)
    y = np.zeros(n, np.int64) if name.startswith("calibration") else np.arange(n) % 2
    rng.shuffle(y)
    domain = rng.integers(0, 2, n) if name in ("train", "validation") else np.full(n, int(name.endswith("shifted")))
    signals = np.empty((n, 4096), np.float32)
    observed = np.empty(n, np.float32)
    audit = np.empty((n, 8), np.float64)
    for i in range(n):
        g = spec["generator"]
        d = g["shifted" if domain[i] else "ordinary"]
        wall = rng.uniform(*g["wall_mm"])
        depth = wall * rng.uniform(*g["depth_fraction"]) if y[i] else 0.
        area = rng.uniform(*g["pit_area_fraction"]) if y[i] else 0.
        temperature = rng.uniform(*d["temperature"])
        coupling = rng.uniform(*d["coupling"])
        observed[i] = temperature + rng.normal(0, d["temp_error_sd"])
        velocity = params.get(cfg, "ut.v_long") + rng.uniform(*g["v_long_offset"])
        frequency = params.get(cfg, "ut.probe_freq_mhz") * rng.uniform(*g["pulse_frequency_multiplier"])
        width = params.get(cfg, "ut.pulse_sigma_us") * rng.uniform(*g["pulse_width_multiplier"])
        delay = params.get(cfg, "ut.interface_delay_us") + rng.uniform(*g["delay_offset_us"])
        varied = params.with_values(cfg, {"ut.v_long": velocity, "ut.probe_freq_mhz": frequency,
                                         "ut.pulse_sigma_us": width, "ut.interface_delay_us": delay})
        signals[i] = ut.simulate_straight(varied, rng, wall, depth, area, temperature,
                                          coupling, d["noise"], 16).astype(np.float16).astype(np.float32)
        audit[i] = wall, depth, area, temperature, coupling, velocity, frequency, width
        if (i + 1) % 1000 == 0:
            print(f"{name}: {i + 1}/{n}", flush=True)
    result = {"RF": signals, "y": y, "domain": domain, "observed_temperature": observed, "audit": audit}
    save_dataset(target, result, name, spec)
    return result


def prepare(out, cfg, spec):
    for name in ("train", "validation", "calibration_ordinary", "calibration_shifted"):
        generate(name, out, cfg, spec)
    print("학습·검증·정상 보정 데이터 준비 완료. 최종 평가 데이터는 아직 생성하지 않았습니다.", flush=True)


def train(out, spec):
    if not torch.cuda.is_available():
        raise RuntimeError("GPU training must run on Colab/vast, not this CPU laptop")
    destination = out / "cnn_dr.pt"
    if destination.exists():
        raise FileExistsError("Training is complete; keep the existing checkpoint")
    seed = spec["seed_model"]
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True
    with np.load(out / "train.npz", allow_pickle=False) as f:
        x, y = f["RF"], f["y"]
    prep = {"rf_mean": float(x.mean(dtype=np.float64)), "rf_std": float(x.std(dtype=np.float64))}
    ds = TensorDataset(torch.from_numpy(((x - prep["rf_mean"]) / prep["rf_std"])[:, None]),
                       torch.from_numpy(y.astype(np.float32)))
    loader = DataLoader(ds, batch_size=spec["batch_size"], shuffle=True, num_workers=0,
                        generator=torch.Generator().manual_seed(seed))
    with np.load(out / "validation.npz", allow_pickle=False) as f:
        vx, vy, vd = f["RF"], f["y"], f["domain"]
    net = PitCNN().cuda()
    opt = torch.optim.AdamW(net.parameters(), lr=spec["lr"], weight_decay=1e-4)
    loss_fn = nn.BCEWithLogitsLoss()
    best, stale, history = float("inf"), 0, []
    start = time.perf_counter()
    temporary = out / "cnn_dr_in_progress.pt"
    for epoch in range(1, spec["max_epochs"] + 1):
        net.train()
        total = 0.
        for xx, yy in loader:
            opt.zero_grad(set_to_none=True)
            loss = loss_fn(net(xx.cuda()), yy.cuda())
            if not torch.isfinite(loss):
                raise ValueError("Nonfinite training loss")
            loss.backward()
            nn.utils.clip_grad_norm_(net.parameters(), 5.)
            opt.step()
            total += float(loss.detach()) * len(yy)
        net.eval()
        v = logits(net, vx, prep, "cuda")
        val_loss = float(np.mean(np.logaddexp(0, v) - vy * v))
        row = {"epoch": epoch, "train_bce": total / len(ds), "validation_bce": val_loss,
               "ordinary_auc": auc(vy[vd == 0], v[vd == 0]), "shifted_auc": auc(vy[vd == 1], v[vd == 1])}
        history.append(row)
        if val_loss < best:
            best, stale = val_loss, 0
            torch.save({"state_dict": {k: v.detach().cpu().clone() for k, v in net.state_dict().items()},
                        "preprocessing": prep, "epoch": epoch, "validation_loss": best,
                        "protocol": spec}, temporary)
        else:
            stale += 1
        pd.DataFrame(history).to_csv(out / "training_history.csv", index=False)
        print(row, flush=True)
        if stale >= spec["patience"]:
            break
    temporary.rename(destination)
    write_once(out / "training_time.json", {"seconds": time.perf_counter() - start,
                                             "device": torch.cuda.get_device_name(0)})


def freeze(run, out):
    if not (out / "cnn_dr.pt").exists():
        raise FileNotFoundError("Train the DR CNN before freezing")
    calibration = {}
    for label, path in [("v1_recalibrated", run / "cnn_best.pt"), ("cnn_dr", out / "cnn_dr.pt")]:
        net, ck = checkpoint(path)
        by_domain = {}
        for domain in ("ordinary", "shifted"):
            with np.load(out / f"calibration_{domain}.npz", allow_pickle=False) as d:
                values = logits(net, d["RF"], ck["preprocessing"])
            by_domain[domain] = select_threshold(values, confidence=.975)
        calibration[label] = {"model_sha256": sha(path), "domains": by_domain,
                              "threshold": max(v["threshold"] for v in by_domain.values())}
    cal = read(run / "baseline/normal_ut_reviewed_v1/calibrated_config.json")
    by_domain = {}
    for domain in ("ordinary", "shifted"):
        cache = out / f"mlp_calibration_{domain}.npy"
        if cache.exists():
            values = np.load(cache, allow_pickle=False)
        else:
            with np.load(out / f"calibration_{domain}.npz", allow_pickle=False) as d:
                values = mlp_scores(d["RF"], d["observed_temperature"], cal,
                                    run / "baseline/normal_ut_reviewed_v1")
            np.save(cache, values)
        by_domain[domain] = select_threshold(values, confidence=.975)
    calibration["mlp_waveform_wall"] = {
        "domains": by_domain, "threshold": max(v["threshold"] for v in by_domain.values())}
    write_once(out / "frozen_comparison.json", calibration)
    return calibration


def evaluate(run, out, cfg, spec):
    frozen = freeze(run, out)
    rows = []
    cal = read(run / "baseline/normal_ut_reviewed_v1/calibrated_config.json")
    for domain in ("ordinary", "shifted"):
        data = generate("final_" + domain, out, cfg, spec)
        predictions = {"y": data["y"]}
        for label, path in [("v1_recalibrated", run / "cnn_best.pt"), ("cnn_dr", out / "cnn_dr.pt")]:
            if sha(path) != frozen[label]["model_sha256"]:
                raise ValueError("Frozen checkpoint changed")
            net, ck = checkpoint(path)
            values = logits(net, data["RF"], ck["preprocessing"])
            predictions[label] = values
            rows.append(summary(label, domain, data["y"], values, frozen[label]["threshold"]))
            if label == "v1_recalibrated":
                old = read(run / "cnn_threshold.json")["threshold"]
                rows.append(summary("v1_original_threshold", domain, data["y"], values,
                                    float(np.log(old / (1 - old)))))
        values = mlp_scores(data["RF"], data["observed_temperature"], cal,
                            run / "baseline/normal_ut_reviewed_v1")
        predictions["mlp_waveform_wall"] = values
        rows.append(summary("mlp_waveform_wall", domain, data["y"], values,
                            frozen["mlp_waveform_wall"]["threshold"]))
        pd.DataFrame(predictions).to_csv(out / f"final_{domain}_predictions.csv", index=False)
    table = pd.DataFrame(rows)
    table.to_csv(out / "final_comparison.csv", index=False)
    print(table.to_string(index=False), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["diagnose", "diagnose-b", "prepare", "train", "evaluate"])
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--b-source", type=Path)
    parser.add_argument("--recover-from", type=Path)
    args = parser.parse_args()
    sys.path.insert(0, str(args.repo.resolve()))
    from maek import params

    torch.set_num_threads(1)
    args.out.mkdir(parents=True, exist_ok=True)
    print("입력 파일 해시 확인 중", flush=True)
    write_once(args.out / "inputs.json", {
        "script_sha256": sha(__file__), "model_sha256": sha(args.run / "cnn_best.pt"),
        "archive_sha256": sha(args.archive), "split_sha256": sha(args.run / "cnn_split_indices.npz"),
        "repo_sources": {name: sha(args.repo / name) for name in
                         ["maek/ut.py", "maek/pit.py", "maek/params.py", "config/default.yaml"]},
        "baseline": {p.name: sha(p) for p in (args.run / "baseline/normal_ut_reviewed_v1").iterdir() if p.is_file()},
    })
    spec = protocol()
    write_once(args.out / "protocol.json", spec)
    cfg = params.load_config(args.repo / "config/default.yaml")
    if args.stage == "diagnose":
        diagnose(args.run, args.archive, args.out)
    elif args.stage == "diagnose-b":
        if args.b_source is None:
            raise ValueError("--b-source is required")
        diagnose_b(args.run, args.b_source, args.out)
    elif args.stage == "prepare":
        if args.recover_from is not None:
            recover_data(args.recover_from, args.out, spec)
        prepare(args.out, cfg, spec)
    elif args.stage == "train":
        train(args.out, spec)
    else:
        evaluate(args.run, args.out, cfg, spec)


if __name__ == "__main__":
    main()
