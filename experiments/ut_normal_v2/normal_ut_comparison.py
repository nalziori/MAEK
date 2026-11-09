"""Normal-incidence synthetic UT model used in the 2026-11-09 B report.

Dependencies: repository requirements plus scipy and torch. Training requires CUDA;
inference and reference calibration can run on CPU with OMP_NUM_THREADS=1.
Run from a repository checkout, using an output directory outside the source folder:

    python experiments/ut_normal_v2/normal_ut_comparison.py prepare \
        --out <run-directory>/normal_ut_reviewed_v1
    python experiments/ut_normal_v2/normal_ut_repair.py prepare --work-dir <run-directory>
    python experiments/ut_normal_v2/normal_ut_repair.py evaluate --work-dir <run-directory>

The first command trains three 7->16->1 MLPs and prepares calibration/validation.
The second freezes v2 thresholds and estimator selection; the third evaluates.
Trained weights, generated waveforms and result reports are deliberately not bundled.
Results are conditional synthetic normal-UT results, not angle-beam/field performance.
Portability changes are limited to repository/output paths and returning the saved RF
array (the original evaluation recovered this array from its NPZ file).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("OMP_NUM_THREADS", "1")
import numpy as np

ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parents[1]
sys.path.insert(0, str(REPO_ROOT))
from maek import params, pit, ut


def write(p, value):
    p.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def protocol():
    return {
        "version": "normal_ut_v1",
        "domain": "normal longitudinal SYNTHETIC, not angle-beam",
        "train_n": 2000,
        "validation_n": 2000,
        "test_n_per_condition": 2000,
        "seeds": {
            "train": 202611091601,
            "validation": 202611091602,
            "test_ordinary": 202611091603,
            "test_shifted": 202611091604,
            "references": 202611091605,
        },
        "averaging": [1, 16],
        "model_seeds": [1601, 1602, 1603],
        "optimizer": {"steps": 1500, "lr": 0.01, "weight_decay": 0.001, "hidden": 16},
        "operating_far": [0.007, 0.01],
        "selection": "validation maxRecall at <=.01; .007 also frozen",
        "estimator_inputs": [
            "RF",
            "acquisition n_avg",
            "independently perturbed nominal wall",
            "measured temperature",
            "independent reference calibration",
        ],
        "geometry": "independent wall/depth/beam-area-fraction draws; no independent curvature/width physics",
        "assumptions": {
            "c20_stress_mps": 70,
            "delay_stress_ns": 50,
            "nominal_wall_sigma_mm": 0.05,
            "temp_error_c": [2, 15],
            "calibration_blocks_mm": [5, 15],
            "calibration_temp_c": [20, 140],
            "calibration_repeats": 8,
            "calibration_shots_per_repeat": 16,
            "primary_reference_labels": "exact, internal consistency only",
            "sensitivity_reference_length_sigma_mm": 0.02,
            "sensitivity_reference_temp_sigma_c": 2,
        },
        "final_goals_unchanged": {"pit_recall": 0.889, "pit_far": 0.007},
        "exclusions": [
            "curvature/width physical validation",
            "actual angle-beam performance",
            "pit-bottom minimum wall",
            "field qualification",
        ],
        "failure_policy": "retain all denominators; valid-only MAE labeled; .1mm rate uses all rows",
    }


def configs():
    base = params.load_config(REPO_ROOT / "config/default.yaml")
    truth = params.with_values(
        base,
        {
            "ut.v_long": params.get(base, "ut.v_long") + 70,
            "ut.interface_delay_us": params.get(base, "ut.interface_delay_us") + 0.05,
        },
    )
    return base, truth


def references(base, truth, out):
    rng = np.random.default_rng(protocol()["seeds"]["references"])
    rows = []
    for temp in [20.0, 140.0]:
        for wall in [5.0, 15.0]:
            for repeat in range(8):
                rf = ut.simulate_straight(
                    truth, rng, wall, temp_c=temp, coupling=0.8, noise_scale=1, n_avg=16
                )
                env = np.abs(pit.analytic(base, rf))
                center = (
                    ut._p(base)["t0"] + 2 * wall * 1e-3 / ut.velocity_long(base, temp)
                ) * ut._p(base)["fs"]
                lo = max(0, int(center - 35))
                hi = min(len(rf), int(center + 36))
                j = lo + int(np.argmax(env[lo:hi]))
                t = ut._parabolic(env, j) / ut._p(base)["fs"]
                rows.append([temp, wall, t, repeat])
    rows = np.asarray(rows)

    def fit(labels):
        speeds = []
        offsets = []
        for temp in [20.0, 140.0]:
            sel = rows[:, 0] == temp
            # Labels may be perturbed independently; actual reference RF stays fixed.
            slope, offset = np.linalg.lstsq(
                np.c_[2 * labels[sel, 1] * 1e-3, np.ones(sel.sum())], rows[sel, 2], rcond=None
            )[0]
            speeds.append(1 / slope)
            offsets.append(offset)
        tc = [labels[rows[:, 0] == t, 0].mean() for t in [20.0, 140.0]]
        coeff = (speeds[1] - speeds[0]) / (tc[1] - tc[0])
        c20 = speeds[0] + coeff * (20 - tc[0])
        return {
            "c20_mps": float(c20),
            "coefficient_mps_per_c": float(coeff),
            "offset_us": float(np.mean(offsets) * 1e6),
        }

    estimate = fit(rows[:, :2])
    sens = []
    # Block dimension/temperature errors shared across its 8 repeated acquisitions.
    for _ in range(200):
        lab = rows[:, :2].copy()
        for t in [20.0, 140.0]:
            for w in [5.0, 15.0]:
                sel = (rows[:, 0] == t) & (rows[:, 1] == w)
                lab[sel, 0] += rng.normal(0, 2)
                lab[sel, 1] += rng.normal(0, 0.02)
        sens.append(fit(lab))
    write(
        out / "reference_calibration.json",
        {
            "estimate": estimate,
            "reference_rows": rows.tolist(),
            "sensitivity_draws": sens,
            "total_calibration_shots": 4 * 8 * 16,
            "limitation": "same generator pulse used in analysis; no independent physics validation",
        },
    )
    return params.with_values(
        base,
        {
            "ut.v_long": estimate["c20_mps"],
            "ut.temp_coeff_mps_per_c": estimate["coefficient_mps_per_c"],
            "ut.interface_delay_us": estimate["offset_us"],
        },
    )


def gate_score(cfg, a):
    k = pit.cfar_k(cfg, pit._corr_cells(cfg, a["n_win"]), pit._q(cfg, "gate_k_margin"))
    return bool(len(a["stat"]) and a["stat"].max() > k)


def current_score(cfg, a, model, navg):
    f = pit.features(cfg, a, False)
    p = float(pit.predict_proba(model, f)[0])
    choices = np.asarray(model["n_avg_choices"])
    i = int(np.argmin(np.abs(np.log(choices) - np.log(navg))))
    band = int(np.digitize(f[pit.FEATURES.index("bw_snr")], model["edges"][i]))
    return p / max(model["thresholds"][i][band], 1e-9) if gate_score(cfg, a) else -1e30


def dataset(n, seed, condition, base, truth, cal, out, name):
    started = time.time()
    rng = np.random.default_rng(seed)
    model = pit.load_shipped(REPO_ROOT / "maek/pit_model.json")["learned"]
    X = np.zeros((2, n, 7), np.float32)
    scores = np.zeros((2, n, 3))
    gates = np.zeros((2, n), bool)
    thick = np.full((2, n, 2), np.nan)
    RF = np.zeros((2, n, 4096), np.float32)
    # Audit columns never enter model tensor: wall,depth,fraction,trueT,observedT,nominalwall,coupling,noise.
    labels = np.zeros((n, 8))
    y = np.arange(n) % 2 == 1
    for i in range(n):
        wall = rng.uniform(3, 16)
        depth = wall * rng.uniform(0.1, 0.6) if y[i] else 0.0
        frac = rng.uniform(0.1, 0.5) if y[i] else 0.0
        shifted = condition == "shifted" or (condition == "dr" and rng.random() < 0.5)
        temp = rng.uniform(100, 175) if shifted else rng.uniform(10, 80)
        coup = rng.uniform(0.3, 0.7) if shifted else rng.uniform(0.7, 1)
        noise = 3.0 if shifted else 1.0
        observed = temp + rng.normal(0, 15 if shifted else 2)
        nominal = max(0.5, wall + rng.normal(0, 0.05))
        labels[i] = wall, depth, frac, temp, observed, nominal, coup, noise
        rfseed = int(rng.integers(0, 2**63 - 1))
        for ni, navg in enumerate([1, 16]):
            # Identical grain and first electronic-noise shot; extra independent shots only at16.
            rf = ut.simulate_straight(
                truth, np.random.default_rng(rfseed), wall, depth, frac, temp, coup, noise, navg
            )
            RF[ni, i] = rf
            aa = pit.analyse(base, rf, nominal, observed)
            ab = pit.analyse(cal, rf, nominal, observed)
            X[ni, i] = pit.features(cal, ab)
            gates[ni, i] = gate_score(cal, ab)
            scores[ni, i, 0] = current_score(base, aa, model, navg)
            scores[ni, i, 1] = current_score(cal, ab, model, navg)
            scores[ni, i, 2] = pit.detect_rule(cal, rf, nominal, observed, a=ab)["score"]
            for ci, cfg in enumerate([base, cal]):
                try:
                    thick[ni, i, ci] = ut.estimate_thickness(cfg, rf, observed)
                except (ValueError, IndexError, FloatingPointError):
                    pass
        if (i + 1) % 250 == 0:
            print(
                json.dumps(
                    {
                        "stage": name,
                        "done": i + 1,
                        "total": n,
                        "seconds": round(time.time() - started, 1),
                    }
                ),
                flush=True,
            )
    ids = np.array([f"{name}:{i}" for i in range(n)])
    np.savez_compressed(
        out / f"{name}.npz",
        X=X,
        scores=scores,
        gate=gates,
        thickness=thick,
        RF=RF,
        labels=labels,
        y=y,
        group_id=ids,
    )
    return {
        "X": X,
        "scores": scores,
        "gate": gates,
        "thickness": thick,
        "RF": RF,
        "labels": labels,
        "y": y,
        "group_id": ids,
    }


def gpu_train(train, out):
    import torch
    from torch import nn

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA required; refusing CPU model training")
    torch.set_num_threads(1)
    torch.cuda.set_per_process_memory_fraction(
        min(0.1, 4 * 1024**3 / torch.cuda.get_device_properties(0).total_memory)
    )
    torch.use_deterministic_algorithms(True)
    x = train["X"].reshape(-1, 7)
    y = np.tile(train["y"], 2).astype(np.float32)
    mu = x.mean(0)
    sd = np.maximum(x.std(0), 1e-6)
    xt = torch.tensor((x - mu) / sd, device="cuda")
    yt = torch.tensor(y, device="cuda")
    allstates = []
    for seed in protocol()["model_seeds"]:
        torch.manual_seed(seed)
        torch.cuda.manual_seed_all(seed)
        model = nn.Sequential(nn.Linear(7, 16), nn.Tanh(), nn.Linear(16, 1)).cuda()
        optim = torch.optim.AdamW(model.parameters(), lr=0.01, weight_decay=0.001)
        for step in range(1500):
            optim.zero_grad(set_to_none=True)
            loss = nn.functional.binary_cross_entropy_with_logits(model(xt).flatten(), yt)
            loss.backward()
            optim.step()
        state = {k: v.detach().cpu() for k, v in model.state_dict().items()}
        torch.save(
            {"state": state, "mean": mu.tolist(), "std": sd.tolist(), "seed": seed},
            out / f"mlp_{seed}.pt",
        )
        allstates.append({"seed": seed, "loss": float(loss.detach().cpu())})
        print(json.dumps(dict(stage="gpu_train", **allstates[-1])), flush=True)
    write(
        out / "training.json",
        {
            "models": allstates,
            "device": torch.cuda.get_device_name(0),
            "torch": torch.__version__,
            "peak_allocated_bytes": torch.cuda.max_memory_allocated(),
            "train_groups": len(train["y"]),
            "train_rows": len(y),
            "parameters": 145,
        },
    )


def predict(d, out):
    import torch
    from torch import nn

    probs = []
    for seed in protocol()["model_seeds"]:
        ck = torch.load(out / f"mlp_{seed}.pt", map_location="cpu", weights_only=True)
        model = nn.Sequential(nn.Linear(7, 16), nn.Tanh(), nn.Linear(16, 1))
        model.load_state_dict(ck["state"])
        model.eval()
        z = (d["X"] - np.asarray(ck["mean"])) / np.asarray(ck["std"])
        with torch.inference_mode():
            probs.append(torch.sigmoid(model(torch.tensor(z, dtype=torch.float32))).numpy()[..., 0])
    score = np.mean(probs, axis=0)
    score[~d["gate"]] = -1e30
    branch = d["scores"].copy()
    branch[..., 2][~d["gate"]] = -1e30  # C/D use exactly the same prerequisite gate.
    return np.concatenate([branch, score[..., None]], axis=2)


def threshold(s, y, far):
    z = np.sort(s[~y])
    allowed = int(np.floor(far * len(z) + 1e-10))
    return float(max(z[len(z) - allowed - 1], -1e20))


def counts(s, y, t):
    found = s > t
    tp = int(found[y].sum())
    fp = int(found[~y].sum())
    return {
        "tp": tp,
        "n_pos": int(y.sum()),
        "fp": fp,
        "n_neg": int((~y).sum()),
        "recall": tp / int(y.sum()),
        "far": fp / int((~y).sum()),
    }


def select(val, out):
    s = predict(val, out)
    thresholds = {}
    selection = {}
    arms = [
        "A_current_MLP",
        "B_calibrated_same_MLP",
        "C_calibrated_MF_CFAR",
        "D_calibrated_new_MLP",
    ]
    for ni, navg in enumerate([1, 16]):
        for far in [0.007, 0.01]:
            rows = []
            for ai, arm in enumerate(arms):
                t = threshold(s[ni, :, ai], val["y"], far)
                key = f"{navg}:{far}:{arm}"
                thresholds[key] = t
                rows.append(dict(arm=arm, threshold=t, **counts(s[ni, :, ai], val["y"], t)))
            # Fixed tie order favors simpler C, then A, B, D. No test scores used.
            order = {
                "C_calibrated_MF_CFAR": 0,
                "A_current_MLP": 1,
                "B_calibrated_same_MLP": 2,
                "D_calibrated_new_MLP": 3,
            }
            winner = min(rows, key=lambda r: (-r["recall"], r["far"], order[r["arm"]]))
            selection[f"{navg}:{far}"] = {"winner": winner["arm"], "validation": rows}
    write(
        out / "frozen_thresholds.json",
        {
            "thresholds": thresholds,
            "selection": selection,
            "checkpoint_sha256": {p.name: sha(p) for p in out.glob("mlp_*.pt")},
            "protocol_sha256": sha(out / "protocol.json"),
            "script_sha256": sha(Path(__file__)),
        },
    )


def bootstrap(found, y, rng):
    ci = {}
    for key, mask in [("recall", y), ("far", ~y)]:
        v = found[mask].astype(float)
        n = len(v)
        draws = np.array([v[rng.integers(0, n, n)].mean() for _ in range(500)])
        ci[key + "_geometry_bootstrap_ci95"] = np.quantile(draws, [0.025, 0.975]).tolist()
    return ci


def wilson(k, n):
    z = 1.959963984540054
    p = k / n
    den = 1 + z * z / n
    center = (p + z * z / (2 * n)) / den
    half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return [max(0.0, float(center - half)), min(1.0, float(center + half))]


def evaluate(out):
    frozen = json.loads((out / "frozen_thresholds.json").read_text())
    assert sha(out / "protocol.json") == frozen["protocol_sha256"]
    if "calibrated_config_sha256" in frozen:
        assert sha(out / "calibrated_config.json") == frozen["calibrated_config_sha256"]
    if sha(Path(__file__)) != frozen["script_sha256"]:
        raise RuntimeError("script changed after freeze")
    for name, digest in frozen["checkpoint_sha256"].items():
        assert sha(out / name) == digest
    if (out / "final_results.json").exists():
        raise RuntimeError("final test already evaluated; no overwrite")
    base, truth = configs()
    cal = json.loads((out / "calibrated_config.json").read_text())
    results = []
    thickness = []
    rng = np.random.default_rng(1609)
    arms = [
        "A_current_MLP",
        "B_calibrated_same_MLP",
        "C_calibrated_MF_CFAR",
        "D_calibrated_new_MLP",
    ]
    for condition in ["ordinary", "shifted"]:
        name = f"test_{condition}"
        d = dataset(2000, protocol()["seeds"][name], condition, base, truth, cal, out, name)
        s = predict(d, out)
        for ni, navg in enumerate([1, 16]):
            for far in [0.007, 0.01]:
                for ai, arm in enumerate(arms):
                    t = frozen["thresholds"][f"{navg}:{far}:{arm}"]
                    metrics = counts(s[ni, :, ai], d["y"], t)
                    results.append(
                        dict(
                            condition=condition,
                            n_avg=navg,
                            operating_far=far,
                            arm=arm,
                            threshold=t,
                            **metrics,
                            recall_wilson_ci95=wilson(metrics["tp"], metrics["n_pos"]),
                            far_wilson_ci95=wilson(metrics["fp"], metrics["n_neg"]),
                            **bootstrap(s[ni, :, ai] > t, d["y"], rng),
                        )
                    )
            for ci, arm in enumerate(["A_current_calibration", "B_reference_calibration"]):
                pred = d["thickness"][ni, :, ci]
                e = np.abs(pred - d["labels"][:, 0])
                valid = np.isfinite(e)
                thickness.append(
                    {
                        "condition": condition,
                        "n_avg": navg,
                        "arm": arm,
                        "n": len(e),
                        "valid": int(valid.sum()),
                        "failed": int((~valid).sum()),
                        "failure_rate": float((~valid).mean()),
                        "valid_only_mae_mm": float(e[valid].mean()),
                        "valid_only_p95_mm": float(np.quantile(e[valid], 0.95)),
                        "within_01_count": int((valid & (e <= 0.1)).sum()),
                        "within_01_all": float((valid & (e <= 0.1)).mean()),
                    }
                )
            ne = np.abs(d["labels"][:, 5] - d["labels"][:, 0])
            thickness.append(
                {
                    "condition": condition,
                    "n_avg": navg,
                    "arm": "nominal_record_only",
                    "n": len(ne),
                    "valid": len(ne),
                    "failed": 0,
                    "failure_rate": 0.0,
                    "valid_only_mae_mm": float(ne.mean()),
                    "valid_only_p95_mm": float(np.quantile(ne, 0.95)),
                    "within_01_count": int((ne <= 0.1).sum()),
                    "within_01_all": float((ne <= 0.1).mean()),
                }
            )
        np.savez_compressed(
            out / f"{name}_predictions.npz", scores=s, y=d["y"], group_id=d["group_id"]
        )
    write(
        out / "final_results.json",
        {
            "detection": results,
            "thickness": thickness,
            "selection": frozen["selection"],
            "scope": protocol()["domain"],
            "test_evaluations": 1,
            "independent_geometry_units": 4000,
            "paired_acquisition_rows": 8000,
        },
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["prepare", "evaluate"])
    parser.add_argument("--out", type=Path, required=True)
    a = parser.parse_args()
    out = a.out.resolve()
    if a.stage == "prepare":
        out.parent.mkdir(parents=True, exist_ok=True)
        out.mkdir(exist_ok=False)
        write(out / "protocol.json", protocol())
        base, truth = configs()
        cal = references(base, truth, out)
        write(out / "calibrated_config.json", cal)
        train = dataset(2000, protocol()["seeds"]["train"], "dr", base, truth, cal, out, "train")
        val = dataset(
            2000, protocol()["seeds"]["validation"], "dr", base, truth, cal, out, "validation"
        )
        gpu_train(train, out)
        select(val, out)
        print("PREPARATION COMPLETE; FINAL TEST NOT GENERATED", flush=True)
    else:
        evaluate(out)
        print("FINAL EVALUATION COMPLETE", flush=True)


if __name__ == "__main__":
    main()
