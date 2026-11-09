"""Frozen D ensemble inference on synthetic normal-incidence A-scans."""

import argparse
import json
import os
from pathlib import Path

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

import numpy as np
from package_utils import ROOT, read_json, verify_package


def load_input(path, cal, expected_n_avg=None):
    import normal_ut_repair as model

    with np.load(path, allow_pickle=False) as data:
        required = {
            "RF", "observed_temperature_c", "nominal_wall_mm",
            "sampling_mhz", "probe_freq_mhz", "n_avg",
        }
        missing = required - set(data.files)
        if missing:
            raise ValueError(f"Missing NPZ fields: {sorted(missing)}")
        rf = data["RF"]
        temperature = data["observed_temperature_c"]
        nominal = data["nominal_wall_mm"]
        for field in ["sampling_mhz", "probe_freq_mhz"]:
            value = data[field]
            expected = model.m.params.get(cal, f"ut.{field}")
            if value.ndim != 0 or not np.isclose(float(value), expected, rtol=0, atol=1e-8):
                raise ValueError(f"{field} must match the calibration ({expected})")
        navg_value = data["n_avg"]
        if navg_value.ndim != 0 or float(navg_value) not in (1, 16):
            raise ValueError("n_avg must be a scalar 1 or 16")
        n_avg = int(navg_value)
    n_samples = int(model.m.params.get(cal, "ut.n_samples"))
    if rf.ndim != 2 or rf.shape[1] != n_samples or len(rf) == 0:
        raise ValueError(f"RF must have shape (N, {n_samples}), with N > 0")
    if temperature.shape != (len(rf),) or nominal.shape != (len(rf),):
        raise ValueError("Temperature and nominal thickness must have shape (N,)")
    for value in [rf, temperature, nominal]:
        if not np.issubdtype(value.dtype, np.number) or np.iscomplexobj(value):
            raise ValueError("Inputs must be real numeric arrays")
        if not np.isfinite(value).all():
            raise ValueError("Inputs must be finite; NaN/Inf are not accepted")
    if np.any(nominal <= 0):
        raise ValueError("Nominal thickness must be positive (mm)")
    if expected_n_avg is not None and n_avg != expected_n_avg:
        raise ValueError("--n-avg disagrees with the input acquisition metadata")
    return rf, temperature, nominal, n_avg


def predict(rf, temperature, nominal, n_avg, cal, frozen, operating_far=0.007):
    import normal_ut_repair as model

    features = np.asarray([
        model.m.pit.features(cal, model.m.pit.analyse(cal, wave, wall, temp))
        for wave, wall, temp in zip(rf, nominal, temperature)
    ], dtype=np.float32)
    if not np.isfinite(features).all():
        raise ValueError("Feature extraction produced non-finite values")
    scores = model.mlp_probability(features)
    groups = model.group(features, temperature, frozen["edges"][str(n_avg)])
    thresholds = np.asarray([
        frozen["thresholds"][f"{n_avg}:{operating_far}:D_new_MLP_no_hard_gate:{g}"]["threshold"]
        for g in groups
    ])
    walls = np.asarray([
        model.estimate(cal, wave, wall, temp, model.m.ut, model.m.params)
        for wave, wall, temp in zip(rf, nominal, temperature)
    ])
    return scores, groups, thresholds, walls


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "examples/ascan.npz")
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/predictions.json")
    parser.add_argument("--n-avg", type=int, choices=[1, 16])
    parser.add_argument("--operating-far", type=float, choices=[0.007, 0.01], default=0.007)
    parser.add_argument("--verify-example", action="store_true")
    args = parser.parse_args()
    files = verify_package()
    if args.verify_example and (
        args.input.resolve() != (ROOT / "examples/ascan.npz").resolve()
        or args.operating_far != 0.007
        or args.n_avg not in (None, 16)
    ):
        parser.error("--verify-example requires the bundled example and default operating point")
    cal = json.loads(read_json(ROOT / "normal_ut_reviewed_v1/calibrated_config.json"))
    frozen = json.loads(read_json(ROOT / "normal_ut_repair_v2/frozen_decisions.json"))
    rf, temperature, nominal, n_avg = load_input(args.input, cal, args.n_avg)
    scores, groups, thresholds, walls = predict(
        rf, temperature, nominal, n_avg, cal, frozen, args.operating_far
    )
    alarms = scores > thresholds
    rows = [
        {"case": i, "pit_score": float(score), "group": int(group),
         "threshold": float(threshold), "pit_alarm": bool(alarm),
         "main_wall_mm": float(wall) if np.isfinite(wall) else None,
         "wall_estimation_valid": bool(np.isfinite(wall))}
        for i, (score, group, threshold, alarm, wall) in enumerate(
            zip(scores, groups, thresholds, alarms, walls)
        )
    ]
    result = {
        "scope": "synthetic normal-incidence UT; not angle-beam or field validation",
        "n_avg": n_avg, "calibration_target_far": args.operating_far,
        "far_is_not_guaranteed_for_new_inputs": True, "rows": rows,
    }
    if args.verify_example:
        expected = json.loads(read_json(ROOT / "examples/expected.json"))
        dp = float(np.max(np.abs(scores - np.asarray(expected["probabilities"]))))
        dw = float(np.max(np.abs(walls - np.asarray(expected["wall_mm"]))))
        if not (dp < 5e-6 and dw < 1e-6 and alarms.tolist() == expected["alarms"]):
            raise RuntimeError(f"Example mismatch: score delta={dp}, wall delta={dw}")
        result["verification"] = {
            "passed": True, "cases": len(rf), "files_checked": files,
            "max_score_difference": dp, "max_wall_difference_mm": dw,
        }
    manifest = json.loads(read_json(ROOT / "manifest.json"))
    protected = {(ROOT / name).resolve() for name in manifest}
    protected.update({ROOT / "manifest.json", args.input.resolve()})
    if args.output.resolve() in protected:
        parser.error("Output must not overwrite package files or the input")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False),
                           encoding="utf-8")
    print(json.dumps(result.get("verification", {"cases": len(rows), "output": str(args.output)})))


if __name__ == "__main__":
    main()
