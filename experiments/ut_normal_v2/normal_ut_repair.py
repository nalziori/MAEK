"""Small repair after v1 became development evidence. Fresh final geometries required."""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from scipy.stats import beta

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import normal_ut_comparison as m
from wall_profile import estimate

OLD = ROOT / "normal_ut_reviewed_v1"
OUT = ROOT / "normal_ut_repair_v2"
ARMS = ["B_existing_MLP_no_hard_gate", "C_MF_CFAR_no_extra_gate", "D_new_MLP_no_hard_gate"]


def mlp_probability(X):
    import torch
    from torch import nn

    torch.set_num_threads(1)
    probs = []
    for seed in [1601, 1602, 1603]:
        ck = torch.load(OLD / f"mlp_{seed}.pt", map_location="cpu", weights_only=True)
        model = nn.Sequential(nn.Linear(7, 16), nn.Tanh(), nn.Linear(16, 1))
        model.load_state_dict(ck["state"])
        model.eval()
        with torch.inference_mode():
            probs.append(
                torch.sigmoid(
                    model(
                        torch.tensor(
                            (X - np.asarray(ck["mean"])) / np.asarray(ck["std"]),
                            dtype=torch.float32,
                        )
                    )
                ).numpy()[..., 0]
            )
    return np.mean(probs, axis=0)


def make_calibration(n, seed, name, base, truth, cal):
    rng = np.random.default_rng(seed)
    X = np.empty((2, n, 7), np.float32)
    scores = np.empty((2, n, 3))
    RF = np.empty((2, n, 4096), np.float32)
    observed = np.empty(n)
    audit = np.empty((n, 6))
    model = m.pit.load_shipped(m.REPO_ROOT / "maek/pit_model.json")["learned"]
    for i in range(n):
        shifted = rng.random() < 0.5
        wall = rng.uniform(3, 16)
        temp = rng.uniform(100, 175) if shifted else rng.uniform(10, 80)
        coupling = rng.uniform(0.3, 0.7) if shifted else rng.uniform(0.7, 1.0)
        noise = 3 if shifted else 1
        observed[i] = temp + rng.normal(0, 15 if shifted else 2)
        nominal = max(0.5, wall + rng.normal(0, 0.05))
        rfseed = int(rng.integers(0, 2**63 - 1))
        audit[i] = wall, temp, coupling, noise, nominal, rfseed % (2**52)
        for ni, navg in enumerate([1, 16]):
            rf = m.ut.simulate_straight(
                truth,
                np.random.default_rng(rfseed),
                wall,
                temp_c=temp,
                coupling=coupling,
                noise_scale=noise,
                n_avg=navg,
            )
            RF[ni, i] = rf
            a = m.pit.analyse(cal, rf, nominal, observed[i])
            f = m.pit.features(cal, a)
            X[ni, i] = f
            scores[ni, i, 0] = m.pit.predict_proba(model, f)[0]
            scores[ni, i, 1] = m.pit.detect_rule(cal, rf, nominal, observed[i], a=a)["score"]
        if (i + 1) % 1000 == 0:
            print(json.dumps({"stage": name, "done": i + 1, "total": n}), flush=True)
    scores[..., 2] = mlp_probability(X)
    np.savez_compressed(
        OUT / f"{name}.npz", X=X, scores=scores, observed=observed, RF=RF, audit=audit
    )
    return {"X": X, "scores": scores, "observed": observed}


def group(X, observed, edges):
    temperature = (observed >= 90).astype(int)
    return 2 * temperature + (X[..., 3] > np.where(temperature == 0, edges[0], edges[1])).astype(
        int
    )


def nongated_scores(d, cal):
    model = m.pit.load_shipped(m.REPO_ROOT / "maek/pit_model.json")["learned"]
    s = np.empty((*d["X"].shape[:2], 3))
    for ni in [0, 1]:
        s[ni, :, 0] = m.pit.predict_proba(model, d["X"][ni])
    s[..., 1] = d["scores"][..., 2]
    s[..., 2] = mlp_probability(d["X"])
    return s


def decisions(scores, X, observed, frozen, far, arm):
    found = np.zeros(scores.shape[:2], bool)
    for ni, na in enumerate([1, 16]):
        g = group(X[ni], observed, frozen["edges"][str(na)])
        for gi in range(4):
            threshold = frozen["thresholds"][f"{na}:{far}:{ARMS[arm]}:{gi}"]["threshold"]
            found[ni, g == gi] = scores[ni, g == gi, arm] > threshold
    return found


def prepare(resume=False):
    if not resume:
        OUT.mkdir(exist_ok=False)
    protocol = {
        "version": "normal_ut_repair_v2",
        "seeds": {
            "edge": 202611091701,
            "calibration": 202611091702,
            "test_ordinary": 202611091703,
            "test_shifted": 202611091704,
        },
        "n_edge_normals": 1000,
        "n_calibration_normals": 12000,
        "n_test_per_condition": 4000,
        "classes_per_test_condition": {"normal": 2000, "pit": 2000},
        "arms": ARMS,
        "changes": [
            "same trained weights, remove prerequisite hard gate",
            "independent edge set then fresh normal-only thresholds",
            "observed temperature90C then observed backwallSNR median: four strata per averaging",
            "nominal exact-binomial upper design with Bonferroni over eight strata",
            "nominal-record constrained four-echo RF timing fit, positive nuisance amplitudes",
        ],
        "confidence": 0.95,
        "operating_far": [0.007, 0.01],
        "model_selection": "existing validation positives, highest overall recall at each FAR and averaging; C wins ties",
        "wall_selection": "all existing validation rows: lower overall MAE and no increase in >.1mm count",
        "inference_scope": "same linear-pulse synthetic instrument; width/curvature and devices unvalidated",
        "nominal_prior": "record sigma.05mm assumption, search+-max(.5mm,10%nominal); no truth input",
        "original_test_role": "v1 now development evidence, never reused as v2 final",
        "note": "CP nominal calibration design does not certify unseen distributions or physical FAR",
    }
    if not resume:
        m.write(OUT / "protocol.json", protocol)
    base, truth = m.configs()
    cal = json.loads((OLD / "calibrated_config.json").read_text())
    if resume:
        edge = dict(np.load(OUT / "edge_normals.npz"))
        normal = dict(np.load(OUT / "calibration_normals.npz"))
    else:
        edge = make_calibration(1000, protocol["seeds"]["edge"], "edge_normals", base, truth, cal)
        normal = make_calibration(
            12000, protocol["seeds"]["calibration"], "calibration_normals", base, truth, cal
        )
    edges = {}
    thresholds = {}
    for ni, na in enumerate([1, 16]):
        edges[str(na)] = [
            float(np.median(edge["X"][ni, sel, 3]))
            for sel in [edge["observed"] < 90, edge["observed"] >= 90]
        ]
        groups = group(normal["X"][ni], normal["observed"], edges[str(na)])
        for far in [0.007, 0.01]:
            for gi in range(4):
                n = int((groups == gi).sum())
                alpha = 0.05 / 8
                allowed = [
                    k for k in range(int(n * far) + 1) if beta.ppf(1 - alpha, k + 1, n - k) <= far
                ]
                if not allowed:
                    raise RuntimeError("calibration stratum too small")
                k = max(allowed)
                for ai, arm in enumerate(ARMS):
                    z = np.sort(normal["scores"][ni, groups == gi, ai])
                    threshold = float(z[n - k - 1])
                    thresholds[f"{na}:{far}:{arm}:{gi}"] = {
                        "threshold": threshold,
                        "n": n,
                        "allowed_fp": k,
                        "observed_fp": int((z > threshold).sum()),
                        "nominal_upper": float(beta.ppf(1 - alpha, k + 1, n - k)),
                    }
    frozen = {"edges": edges, "thresholds": thresholds}
    val = dict(np.load(OLD / "validation.npz"))
    scores = nongated_scores(val, cal)
    selection = {}
    vresults = []
    for far in [0.007, 0.01]:
        for ni, na in enumerate([1, 16]):
            rows = []
            for ai, arm in enumerate(ARMS):
                found = decisions(scores, val["X"], val["labels"][:, 4], frozen, far, ai)[ni]
                row = dict(arm=arm, **m.counts(found.astype(float), val["y"], 0.5))
                rows.append(row)
                vresults.append(dict(target_far=far, n_avg=na, **row))
            winner = min(
                rows, key=lambda x: (-x["recall"], x["far"], 0 if x["arm"] == ARMS[1] else 1)
            )
            selection[f"{na}:{far}"] = winner["arm"]
    # Dev comparison uses the whole prior validation set, not v2 final geometries.
    profile = np.empty((2, len(val["y"])))
    for ni, na in enumerate([1, 16]):
        for i in range(len(val["y"])):
            profile[ni, i] = estimate(
                cal, val["RF"][ni, i], val["labels"][i, 5], val["labels"][i, 4], m.ut, m.params
            )
            if (i + 1) % 500 == 0:
                print(
                    json.dumps({"stage": "validation_wall_profile", "n_avg": na, "done": i + 1}),
                    flush=True,
                )
    error = np.abs(profile - val["labels"][None, :, 0])
    old = np.abs(val["thickness"][..., 1] - val["labels"][None, :, 0])
    choose = bool(
        np.isfinite(error).all()
        and error.mean() < old.mean()
        and (error > 0.1).sum() <= (old > 0.1).sum()
    )
    wall_development = {
        "profile_mae": float(error.mean()),
        "old_mae": float(old.mean()),
        "profile_over01": int((error > 0.1).sum()),
        "old_over01": int((old > 0.1).sum()),
        "profile_selected": choose,
    }
    np.savez_compressed(OUT / "validation_wall_profile.npz", estimates=profile)
    frozen.update(
        selection=selection,
        validation=vresults,
        wall_development=wall_development,
        wall_estimator="profile" if choose else "old",
        hashes={
            str(p): m.sha(p)
            for p in [
                Path(__file__),
                ROOT / "wall_profile.py",
                ROOT / "normal_ut_comparison.py",
                OUT / "protocol.json",
                OLD / "calibrated_config.json",
                *[OLD / f"mlp_{s}.pt" for s in [1601, 1602, 1603]],
            ]
        },
    )
    m.write(OUT / "frozen_decisions.json", frozen)
    print(
        json.dumps(
            {"prepared": True, "selection": selection, "wall_development": wall_development}
        ),
        flush=True,
    )


def evaluate():
    if (OUT / "final_results.json").exists():
        raise RuntimeError("already evaluated")
    frozen = json.loads((OUT / "frozen_decisions.json").read_text())
    for path, digest in frozen["hashes"].items():
        assert m.sha(Path(path)) == digest
    protocol = json.loads((OUT / "protocol.json").read_text())
    base, truth = m.configs()
    cal = json.loads((OLD / "calibrated_config.json").read_text())
    results = []
    thickness = []
    for condition in ["ordinary", "shifted"]:
        d = m.dataset(
            4000,
            protocol["seeds"][f"test_{condition}"],
            condition,
            base,
            truth,
            cal,
            OUT,
            f"test_{condition}",
        )
        scores = nongated_scores(d, cal)
        observed = d["labels"][:, 4]
        for far in [0.007, 0.01]:
            for ai, arm in enumerate(ARMS):
                decisions_all = decisions(scores, d["X"], observed, frozen, far, ai)
                for ni, na in enumerate([1, 16]):
                    metrics = m.counts(decisions_all[ni].astype(float), d["y"], 0.5)
                    results.append(
                        dict(
                            condition=condition,
                            n_avg=na,
                            operating_far=far,
                            arm=arm,
                            **metrics,
                            far_wilson_ci95=m.wilson(metrics["fp"], metrics["n_neg"]),
                            recall_wilson_ci95=m.wilson(metrics["tp"], metrics["n_pos"]),
                        )
                    )
        profile = np.full((2, len(d["y"])), np.nan)
        if frozen["wall_estimator"] == "profile":
            for ni, na in enumerate([1, 16]):
                for i in range(len(d["y"])):
                    profile[ni, i] = estimate(
                        cal, d["RF"][ni, i], d["labels"][i, 5], observed[i], m.ut, m.params
                    )
                    if (i + 1) % 1000 == 0:
                        print(
                            json.dumps(
                                {
                                    "stage": "final_wall_profile",
                                    "condition": condition,
                                    "n_avg": na,
                                    "done": i + 1,
                                }
                            ),
                            flush=True,
                        )
        for ni, na in enumerate([1, 16]):
            for arm, pred in [
                ("old_calibrated_autocorrelation", d["thickness"][ni, :, 1]),
                ("nominal_record", d["labels"][:, 5]),
                ("selected_profile", profile[ni]),
            ]:
                if arm == "selected_profile" and frozen["wall_estimator"] != "profile":
                    continue
                error = np.abs(pred - d["labels"][:, 0])
                valid = np.isfinite(error)
                thickness.append(
                    {
                        "condition": condition,
                        "n_avg": na,
                        "arm": arm,
                        "n": len(error),
                        "valid": int(valid.sum()),
                        "failed": int((~valid).sum()),
                        "valid_only_mae_mm": float(error[valid].mean()),
                        "valid_only_p95_mm": float(np.quantile(error[valid], 0.95)),
                        "within01": int((valid & (error <= 0.1)).sum()),
                        "within01_all": float((valid & (error <= 0.1)).mean()),
                    }
                )
        np.savez_compressed(
            OUT / f"test_{condition}_predictions.npz", scores=scores, wall_profile=profile, y=d["y"]
        )
    m.write(
        OUT / "final_results.json",
        {
            "detection": results,
            "thickness": thickness,
            "selection": frozen["selection"],
            "wall_estimator": frozen["wall_estimator"],
            "test_evaluations": 1,
            "geometry_units": 8000,
            "domain": "normal-incidence synthetic internal consistency; not angle-beam validation",
        },
    )
    print("V2 FINAL EVALUATION COMPLETE", flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("stage", choices=["prepare", "prepare_resume", "evaluate"])
    p.add_argument(
        "--work-dir",
        type=Path,
        required=True,
        help="Directory containing normal_ut_reviewed_v1; writes normal_ut_repair_v2",
    )
    a = p.parse_args()
    work_dir = a.work_dir.resolve()
    OLD = work_dir / "normal_ut_reviewed_v1"
    OUT = work_dir / "normal_ut_repair_v2"
    prepare(a.stage == "prepare_resume") if a.stage.startswith("prepare") else evaluate()
