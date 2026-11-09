"""Finite GPU fine-tuning study; synthetic angle-beam scenes, not field validation.

Run in an isolated bundle containing runtime/, crack_cnn/, and this file.
All generation, split construction, training and evaluation occur on the server.
"""
import os
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import platform
import sys
import time

import numpy as np
import pandas as pd
from scipy.signal import hilbert, resample_poly
from scipy.stats import binom
import torch

ROOT = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT / "runtime"), str(ROOT / "crack_cnn")]
from maek import params, ut
import angle_crack_runtime as old
import crack_helpers
import ut_design_v2 as arch

SOURCES = ("general", "shifted", "geometry", "thermal_geometry")
SEEDS = (4101, 4102, 4103)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, data):
    path.write_text(json.dumps(data, indent=2, allow_nan=False), encoding="utf-8")


def generate(cfg, count, split_id, source_id, normal=False):
    """No empirical acquisition is claimed; each unit has its own synthetic geometry."""
    rng = np.random.default_rng([20261109, 4100, split_id, source_id])
    shots = np.random.default_rng([20261109, 4100, split_id, source_id, 16])
    p = ut._p(cfg)
    actual_cfg = copy.deepcopy(cfg)
    rf = np.empty((count, p["n"]), np.float32)
    rows = []
    # Exactly balanced class/angle schedules, shuffled independently of geometry.
    angles = np.resize(np.array([45., 60., 70.]), count)
    rng.shuffle(angles)
    labels = np.zeros(count, bool) if normal else np.arange(count) % 2 == 0
    rng.shuffle(labels)
    source = SOURCES[source_id]
    for i in range(count):
        wall = float(rng.uniform(3., 12.))
        true_wall = wall + (rng.normal(0., .25) if source_id >= 2 else 0.)
        temp = float(rng.uniform(10., 60.) if source_id == 0 else rng.uniform(100., 175.))
        observed_temp = temp + rng.normal(0., 2. if source_id == 0 else 15.)
        angle = float(angles[i])
        true_angle = angle
        if source_id == 3:
            true_angle = float(old.snell_angle_at_measured_temperature(cfg, [angle], [temp])[0])
        if source_id >= 2:
            true_angle += rng.normal(0., .1 if source_id == 3 else .5)
        delay_error = float(rng.normal(0., 25e-9)) if source_id >= 2 else 0.
        actual_cfg["ut"]["interface_delay_us"]["value"] = (p["t0"] + delay_error)*1e6
        height = float(true_wall*rng.uniform(*params.get(cfg, "ut.dataset.crack_height_frac_range"))) if labels[i] else 0.
        coupling = float(rng.uniform(.8, 1.) if source_id == 0 else rng.uniform(.3, .7))
        rf[i] = ut.simulate_angle(actual_cfg, rng, true_wall, height, true_angle, temp,
                                  coupling, 1. if source_id == 0 else 3., n_avg=16, avg_rng=shots)
        rows.append(dict(unit_id=f"v4:{split_id}:{source_id}:{i}", source=source,
                         nominal_wall_mm=wall, nominal_angle_deg=angle, measured_temp_c=observed_temp,
                         crack=bool(labels[i]), crack_height_mm=height, true_wall_mm=true_wall,
                         true_angle_deg=true_angle, true_temp_c=temp, delay_error_s=delay_error,
                         coupling=coupling))
    return rf, pd.DataFrame(rows)


def prepare(cfg, rf, nominal_wall, nominal_angle, observed_temp):
    """Truth-free union of fixed-angle and cold-wedge hypotheses with bounded errors.

    Bounds are development assumptions, not calibrated physical confidence bounds.
    Partial recording windows remain flagged and negatives require follow-up.
    """
    p = ut._p(cfg)
    fs, n = p["fs"], p["n"]
    pulse = ut._pulse(cfg, np.arange(-64, 65)/fs, 0.)
    windows = np.zeros((len(rf), 2), int)
    clipped = np.zeros(len(rf), bool)
    gate, quality = np.zeros(len(rf), bool), np.ones(len(rf), bool)
    noise = np.ones(len(rf))
    for i, (wall, angle, temperature) in enumerate(zip(nominal_wall, nominal_angle, observed_temp)):
        times = []
        for trial_t in (temperature-30., temperature+30.):
            corrected = float(old.snell_angle_at_measured_temperature(cfg, [angle], [trial_t])[0])
            for trial_angle in (angle-1., angle+1., corrected-1., corrected+1.):
                for trial_wall in (max(.5, wall-.5), wall+.5):
                    times.append(ut.corner_trap_time(cfg, trial_wall, trial_angle, trial_t))
        half = params.get(cfg, "ut.gate_halfwidth_us")*1e-6 + 75e-9
        raw_lo, raw_hi = math.floor((min(times)-half)*fs), math.ceil((max(times)+half)*fs)+1
        clipped[i] = raw_lo < 48 or raw_hi > n-48
        lo, hi = max(48, min(n-49, raw_lo)), max(49, min(n-48, raw_hi))
        windows[i] = lo, hi
        signal = rf[i]
        filtered = arch.matched_filter(signal, pulse)
        power = np.abs(hilbert(filtered))**2
        found, threshold = arch.ca_cfar_power(power)
        outside = np.r_[signal[int(p["t0"]*fs):max(int(p["t0"]*fs), lo-48)], signal[min(n, hi+48):]]
        sigma = float(1.4826*np.median(np.abs(outside-np.median(outside)))) if len(outside) >= 64 else 0.
        quality[i] = hi > lo and sigma > 1e-8 and np.isfinite(threshold[lo:hi]).all()
        gate[i] = quality[i] and bool(found[lo:hi].any())
        noise[i] = max(sigma, 1e-6)
    reduced = resample_poly(rf, 1, 4, axis=-1).astype(np.float32)
    rf_ch = np.arcsinh(reduced/noise[:, None]/4).astype(np.float32)
    env = np.arcsinh(np.abs(hilbert(reduced, axis=-1))/noise[:, None]/4).astype(np.float32)
    mask = crack_helpers.window_mask(windows, n).reshape(len(rf), -1, 4).any(axis=-1)
    channels = np.stack([rf_ch, env, mask.astype(np.float32)], axis=1)
    assert np.isfinite(channels).all()
    return dict(x=channels, gate=gate, quality=quality, clipped=clipped, windows=windows)


def inference(model, x):
    model.eval()
    device = next(model.parameters()).device
    with torch.no_grad():
        return np.concatenate([model(torch.from_numpy(x[i:i+128]).to(device)).cpu().numpy()
                               for i in range(0, len(x), 128)])


def fit(train, validation, initial, seed, out, epochs):
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    model = arch.SmallWaveCNN().cuda()
    model.load_state_dict(initial)
    optim = torch.optim.AdamW(model.parameters(), lr=.0002, weight_decay=.0001)
    loss_fn = torch.nn.BCEWithLogitsLoss()
    best, stale, best_epoch = float("inf"), 0, 0
    history, state = [], None
    for epoch in range(1, epochs+1):
        model.train()
        losses = []
        for start in np.array_split(rng.permutation(len(train["x"])), math.ceil(len(train["x"])/64)):
            x = torch.from_numpy(train["x"][start]).cuda()
            y = torch.from_numpy(train["y"][start].astype(np.float32)).cuda()
            optim.zero_grad(set_to_none=True)
            loss = loss_fn(model(x), y)
            loss.backward()
            optim.step()
            losses.append(float(loss.detach().cpu()))
        z = inference(model, validation["x"])
        vl = float(loss_fn(torch.from_numpy(z), torch.from_numpy(validation["y"].astype(np.float32))))
        if not np.isfinite(vl) or not np.isfinite(losses).all():
            raise RuntimeError("Nonfinite loss; abort without selecting weights")
        row = dict(epoch=epoch, train_bce=float(np.mean(losses)), validation_bce=vl)
        history.append(row)
        print("GPU_EPOCH", seed, json.dumps(row), flush=True)
        if vl < best-1e-6:
            best, stale, best_epoch = vl, 0, epoch
            state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
            torch.save(state, out/f"seed{seed}_best.pt")
        else:
            stale += 1
        save(out/f"seed{seed}_history.json", history)
        if stale >= 4:
            break
    model.load_state_dict(state)
    return model, dict(seed=seed, best_validation_bce=best, best_epoch=best_epoch)


def rates(pred, y, quality, clipped):
    tp, fp = int((pred & y).sum()), int((pred & ~y).sum())
    pos, neg = int(y.sum()), int((~y).sum())
    return dict(tp=tp, positive_units=pos, fp=fp, normal_units=neg,
                recall=tp/pos if pos else None, far=fp/neg if neg else None,
                invalid_count=int((~quality).sum()), partial_window_count=int(clipped.sum()),
                followup_required_count=int(((~quality | clipped) & ~pred).sum()))


def calibrate(z, data):
    angles, sources = data["labels"].nominal_angle_deg.to_numpy(), data["labels"].source.to_numpy()
    score = np.where(data["gate"] & data["quality"], z, -1e30)
    thresholds, details = {}, []
    # Simultaneous 95% bound over 2 compared candidates x 4 sources x 3 angles.
    delta = .05/24
    for angle in (45., 60., 70.):
        limits = []
        for source in SOURCES:
            values = np.sort(score[(angles == angle) & (sources == source)])
            n = len(values)
            acceptable = np.flatnonzero(binom.cdf(np.arange(n), n, .99) >= 1-delta)
            if not len(acceptable):
                threshold = 1e30  # insufficient normals; abstain from positive decisions
                rank = None
            else:
                rank = int(acceptable[0])
                threshold = float(values[rank])
            limits.append(threshold)
            details.append(dict(angle=angle, source=source, n=n, zero_based_rank=rank, threshold=threshold))
        thresholds[str(angle)] = max(limits)
    return dict(angle_thresholds=thresholds, strata=details, delta_each=delta)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--output", default=None)
    args = parser.parse_args()
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA required: CPU training is prohibited")
    torch.cuda.set_per_process_memory_fraction(min(1., (4*1024**3)/torch.cuda.get_device_properties(0).total_memory))
    torch.use_deterministic_algorithms(True)
    torch.backends.cudnn.benchmark = False
    if args.output and Path(args.output).name != args.output:
        raise ValueError("output must be a single directory name")
    out = ROOT/(args.output or ("smoke" if args.smoke else "run"))
    out.mkdir(exist_ok=False)
    cfg = json.loads((ROOT/"crack_cnn/crack_training_v1/config_snapshot.json").read_text())
    initial_path = ROOT/"crack_cnn/crack_training_v1/crack_cnn_seed1110.pt"
    assert digest(initial_path) == "384f85dfdd1ec6ec62f90ccdc956b865eb612c60ab948ac1c4345ed5c3665ad7"
    initial = torch.load(initial_path, map_location="cpu", weights_only=True)
    source_hashes = {str(p.relative_to(ROOT)):digest(p) for p in ROOT.rglob("*.py") if "run" not in p.parts and "smoke" not in p.parts}
    if not args.smoke:
        checked = json.loads((ROOT/"smoke_checked/results.json").read_text())
        checked_protocol = json.loads((ROOT/"smoke_checked/protocol.json").read_text())
        assert checked["status"] == "completed" and checked_protocol["source_hashes"] == source_hashes
    # Deterministic calibration contract check, independent of simulation and labels.
    toy_labels = pd.DataFrame([dict(nominal_angle_deg=a, source=s) for s in SOURCES for a in (45.,60.,70.) for _ in range(1000)])
    toy = dict(labels=toy_labels, gate=np.ones(12000,bool), quality=np.ones(12000,bool))
    check = calibrate(np.tile(np.arange(1000,dtype=float),12), toy)
    assert all(x["zero_based_rank"] == 998 for x in check["strata"])
    assert all(x == 998. for x in check["angle_thresholds"].values())
    counts = dict(fit=48, validation=24, calibration=60, test=24) if args.smoke else dict(fit=1200, validation=300, calibration=3000, test=2400)
    seeds = SEEDS[:1] if args.smoke else SEEDS
    protocol = dict(status="frozen_before_generation", origin="synthetic only; no measured angle-beam performance",
                    sources=list(SOURCES), counts_per_source=counts, model_seeds=list(seeds),
                    split_seeds="SeedSequence([20261109,4100,split_id,source_id]); split_id 1 fit,2 val,3 calibration,4 test",
                    model="existing 3-channel SmallWaveCNN warm start seed1110", initial_sha256=digest(initial_path),
                    epochs=1 if args.smoke else 20, early_stopping="4 stale epochs; validation BCE only",
                    model_selection="minimum validation BCE across seeds BEFORE calibration and test; control weights unchanged",
                    calibration="normal-only order statistics per source/angle; maximum source threshold per angle; 95% family bound over 24 strata; strict >",
                    acquisition=dict(n_samples=4096, sampling_mhz=100, probe_mhz=5, coherent_shots=16),
                    bounds=dict(wall_mm=.5, angle_deg=1., observed_temperature_c=30., delay_ns=75.),
                    hypotheses="union nominal angle and fixed cold wedge Snell; no wedge heating/curved pipe/scattering solver",
                    truth_inputs=False, class_balance=.5, clipping="recorded separately; partial-window negative requires follow-up",
                    runtime=dict(python=platform.python_version(), torch=torch.__version__, gpu=torch.cuda.get_device_name(0), threads=1, torch_cap_gib=4),
                    source_hashes=source_hashes,
                    evaluation_scope="fresh held-out scenes from source families also present in fitting; not unseen-domain or field generalization",
                    targets=dict(recall_general=1., recall_shifted=.912, far=.01),
                    pod_status="not computed in this initial retraining run; requires separate size-response assessment")
    save(out/"protocol.json", protocol)
    save(out/"config_snapshot.json", cfg)
    save(out/"process.json", dict(pid=os.getpid(), cuda=True, started_unix=time.time()))
    print("CUDA_READY", json.dumps(protocol["runtime"]), flush=True)
    seen = set()
    wave_hashes = set()

    def dataset(split, split_id):
        chunks = []
        for source_id, source in enumerate(SOURCES):
            rf, labels = generate(cfg, counts[split], split_id, source_id, normal=split == "calibration")
            assert not (seen & set(labels.unit_id))
            seen.update(labels.unit_id)
            hashes = [hashlib.sha256(row.tobytes()).hexdigest() for row in rf]
            assert len(set(hashes)) == len(hashes) and not (set(hashes) & wave_hashes)
            wave_hashes.update(hashes)
            labels["rf_sha256"] = hashes
            data = prepare(cfg, rf, labels.nominal_wall_mm.to_numpy(), labels.nominal_angle_deg.to_numpy(), labels.measured_temp_c.to_numpy())
            # Evaluation-only diagnostic; these columns never enter prepare/model inputs.
            p = ut._p(cfg)
            arrivals = np.array([(p["t0"]+r.delay_error_s+2*r.true_wall_mm/1000/(ut.velocity_shear(cfg,r.true_temp_c)*np.cos(np.deg2rad(r.true_angle_deg))))*p["fs"] for r in labels.itertuples()])
            labels["true_echo_outside_window"] = (arrivals < data["windows"][:,0]) | (arrivals >= data["windows"][:,1])
            labels["true_echo_outside_record"] = (arrivals < 0) | (arrivals >= p["n"])
            data["y"], data["labels"] = labels.crack.to_numpy(bool), labels
            labels.to_csv(out/f"{split}_{source}_truth.csv", index=False)
            np.savez_compressed(out/f"{split}_{source}_inputs.npz", rf=rf,
                                nominal_wall_mm=labels.nominal_wall_mm.to_numpy(),
                                nominal_angle_deg=labels.nominal_angle_deg.to_numpy(),
                                observed_temp_c=labels.measured_temp_c.to_numpy(),
                                channels=data["x"], gate=data["gate"], quality=data["quality"],
                                windows=data["windows"], partial_window=data["clipped"])
            chunks.append(data)
            print("PREPARED", split, source, len(rf), "partial", int(data["clipped"].sum()), flush=True)
        return {k: pd.concat([d[k] for d in chunks], ignore_index=True) if k == "labels" else np.concatenate([d[k] for d in chunks]) for k in chunks[0]}

    train, val = dataset("fit", 1), dataset("validation", 2)
    models, histories = {}, []
    for seed in seeds:
        model, history = fit(train, val, initial, seed, out, protocol["epochs"])
        models[seed] = model.cpu()
        histories.append(history)
    selected = min(histories, key=lambda x: x["best_validation_bce"])["seed"]
    save(out/"selection.json", dict(selected_seed=selected, candidates=histories))
    del train, val
    model = models[selected].cuda()
    control = arch.SmallWaveCNN().cuda()
    control.load_state_dict(initial)
    calibration = dataset("calibration", 3)
    points = {name:calibrate(inference(m, calibration["x"]), calibration) for name,m in (("retrained",model),("old_weights_wide_window",control))}
    save(out/"frozen_operating_points.json", dict(selected_seed=selected, candidates=points))
    del calibration
    test = dataset("test", 4)
    results = {}
    predictions = test["labels"].copy()
    predictions["gate_pass"] = test["gate"]
    predictions["quality"] = test["quality"]
    predictions["partial_window"] = test["clipped"]
    for name, m in (("retrained",model),("old_weights_wide_window",control)):
        z = inference(m, test["x"])
        thresholds = np.array([points[name]["angle_thresholds"][str(float(a))] for a in test["labels"].nominal_angle_deg])
        pred = test["gate"] & test["quality"] & (z > thresholds)
        predictions[name+"_logit"], predictions[name+"_prediction"] = z, pred
        predictions[name+"_threshold"] = thresholds
        results[name] = {}
        for source in SOURCES:
            mask = test["labels"].source.to_numpy() == source
            result = rates(pred[mask],test["y"][mask],test["quality"][mask],test["clipped"][mask])
            result["positive_true_echo_outside_window"] = int((test["labels"].true_echo_outside_window.to_numpy() & mask & test["y"]).sum())
            result["positive_true_echo_outside_record"] = int((test["labels"].true_echo_outside_record.to_numpy() & mask & test["y"]).sum())
            result["angles"] = {str(a):rates(pred[mask & (test["labels"].nominal_angle_deg.to_numpy()==a)],test["y"][mask & (test["labels"].nominal_angle_deg.to_numpy()==a)],test["quality"][mask & (test["labels"].nominal_angle_deg.to_numpy()==a)],test["clipped"][mask & (test["labels"].nominal_angle_deg.to_numpy()==a)]) for a in (45.,60.,70.)}
            results[name][source] = result
    predictions.to_csv(out/"test_predictions.csv", index=False)
    save(out/"results.json", dict(status="completed", scope=protocol["origin"], selected_seed=selected,
                                  results=results, measured_validation=False,
                                  peak_torch_allocated_bytes=torch.cuda.max_memory_allocated(),
                                  peak_torch_reserved_bytes=torch.cuda.max_memory_reserved(), unique_units=len(seen)))
    save(out/"data_audit.json",dict(unique_unit_ids=len(seen), unique_rf_sha256=len(wave_hashes),
                                   split_rf_duplicates=0, caveat="RF hash uniqueness does not prove independent real specimens; all scenes synthetic"))
    save(out/"hashes.json", {p.name:digest(p) for p in out.iterdir() if p.is_file()})
    print("COMPLETED", json.dumps({k:{s:{m:v for m,v in row.items() if m != "angles"} for s,row in value.items()} for k,value in results.items()}), flush=True)


if __name__ == "__main__":
    main()
