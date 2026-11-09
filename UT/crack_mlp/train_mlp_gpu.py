"""Frozen feature-MLP study against CNN-v4, synthetic only; GPU training required."""
import os

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import torch

ROOT = Path(__file__).resolve().parent


def save(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False), encoding="utf-8")


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda:f.read(8*1024*1024), b""):
            h.update(chunk)
    return h.hexdigest()


def baseline_path():
    candidates = [ROOT.parent/"crack_retrain_v4_20261109", ROOT.parent/"crack_cnn/crack_retraining_v4"]
    return next((p for p in candidates if p.is_dir()), candidates[0])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, default=baseline_path())
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    base = args.baseline.resolve()
    sys.dont_write_bytecode = True
    sys.path[:0] = [str(base), str(base/"runtime"), str(base/"crack_cnn")]
    import crack_mlp as mlp
    import train_crack_gpu_v4 as v4

    if Path(mlp.__file__).resolve() != ROOT/"crack_mlp.py":
        raise RuntimeError("Unexpected MLP module path")

    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    if not torch.cuda.is_available():
        raise RuntimeError("GPU is required")
    torch.cuda.set_per_process_memory_fraction((4*1024**3)/torch.cuda.get_device_properties(0).total_memory)
    torch.use_deterministic_algorithms(True)
    torch.backends.cudnn.benchmark = False
    out = ROOT/("smoke_v2" if args.smoke else "run")
    out.mkdir(exist_ok=False)
    cfg = json.loads((base/"run/config_snapshot.json").read_text())
    sources = v4.SOURCES
    code_hash = {p.name:sha(p) for p in (Path(__file__), ROOT/"crack_mlp.py")}
    if not args.smoke:
        smoke = json.loads((ROOT/"smoke_v2/completed.json").read_text())
        assert smoke["source_hashes"] == code_hash
    protocol = {"status": "frozen_before_training", "scope": "synthetic same-generator held-out, no physical acquisition needed",
                    "structure": "32 features -> Linear32 ReLU -> Linear16 ReLU -> Linear1", "feature_names": mlp.FEATURE_NAMES,
                    "seeds": [5101,5102,5103], "max_epochs": 120, "patience": 15, "optimizer": "AdamW lr.001 wd.0001 batch128",
                    "selection": "minimum validation BCE, including epoch selection; before calibration or test access",
                    "normalization": "mean/std of fitting features only; minimum std1e-6; no test normalization fitting",
                    "inherited_splits": "same CNN-v4 fit4800, validation1200, normal calibration12000; source file hashes saved",
                    "calibration": "same v4 normal strata/order statistics and max-source threshold per nominal angle; .05/24",
                    "primary_test": "fresh v4 generator split_id51; 2400/source, 1200positive+1200normal; no post-test adjustment",
                    "secondary_test": "previous v4 test9600 already observed; comparison only, not independent final evidence",
                    "comparison": "CNN-v4 selected4103 frozen weights and thresholds, same RF/window/CFAR; different training ancestry",
                    "acquisition": "16 shots,4096samples,100MHz sampling,5MHz probe,45/60/70degrees",
                    "source_hashes": code_hash, "baseline_source_hash": sha(base/"train_crack_gpu_v4.py"),
                    "baseline_point_hash": sha(base/"run/frozen_operating_points.json"),
                    "targets": {"general_recall": 1., "shifted_recall": .912, "far": .01, "a90_mm": 1.22},
                    "pod": "report only using existing ln-size logistic/bootstrap300, no model selection; degenerate fits not certified",
                    "cpu_threads": 1, "torch_memory_cap_gib": 4, "torch_version": torch.__version__,
                    "gpu": torch.cuda.get_device_name(0), "started_unix": time.time()}
    save(out/"protocol.json", protocol)
    save(out/"process.json", {"pid": os.getpid(), "cuda": True})
    save(out/"config_snapshot.json", cfg)
    file_hashes = {}

    def load_split(split):
        groups = []
        for source in sources:
            npz = base/f"run/{split}_{source}_inputs.npz"
            csv = base/f"run/{split}_{source}_truth.csv"
            file_hashes[str(npz.relative_to(base))] = sha(npz)
            file_hashes[str(csv.relative_to(base))] = sha(csv)
            labels = pd.read_csv(csv)
            with np.load(npz, allow_pickle=False) as data:
                take = slice(0, 24 if args.smoke else len(labels))
                features = mlp.extract(cfg, data["rf"][take], data["windows"][take],
                                       data["nominal_wall_mm"][take], data["nominal_angle_deg"][take],data["observed_temp_c"][take])
                group = {"features": features, "gate": data["gate"][take], "quality": data["quality"][take],
                             "clipped": data["partial_window"][take], "labels": labels.iloc[take].reset_index(drop=True)}
            group["y"] = group["labels"].crack.to_numpy(bool)
            groups.append(group)
            print("FEATURES", split, source, len(features), flush=True)
        return {k:pd.concat([g[k] for g in groups],ignore_index=True) if k=="labels" else np.concatenate([g[k] for g in groups]) for k in groups[0]}

    train, val = load_split("fit"), load_split("validation")
    calibration = load_split("calibration")
    mean = train["features"].mean(axis=0)
    scale = np.maximum(train["features"].std(axis=0), 1e-6)
    norm = {"feature_names": mlp.FEATURE_NAMES, "mean": mean.tolist(), "scale": scale.tolist()}
    save(out/"normalization.json", norm)
    save(out/"feature_scale_audit.json", {name:float(np.max(np.abs(mlp.normalize(data["features"],mean,scale)))) for name,data in (("fit",train),("validation",val),("calibration",calibration))})
    np.savez_compressed(out/"training_features.npz",fit=train["features"],fit_y=train["y"],validation=val["features"],validation_y=val["y"])
    for data in (train, val):
        data["x"] = mlp.normalize(data["features"], mean, scale)
    histories = []
    for seed in ([5101] if args.smoke else protocol["seeds"]):
        torch.manual_seed(seed)
        rng = np.random.default_rng(seed)
        model = mlp.CrackMLP().cuda()
        optim = torch.optim.AdamW(model.parameters(),lr=.001,weight_decay=.0001)
        loss_fn = torch.nn.BCEWithLogitsLoss()
        best, stale, history, best_epoch = float("inf"), 0, [], 0
        for epoch in range(1, 3 if args.smoke else 121):
            model.train()
            losses = []
            for ids in np.array_split(rng.permutation(len(train["x"])), int(np.ceil(len(train["x"])/128))):
                optim.zero_grad(set_to_none=True)
                loss = loss_fn(model(torch.from_numpy(train["x"][ids]).cuda()),torch.from_numpy(train["y"][ids].astype(np.float32)).cuda())
                loss.backward()
                optim.step()
                losses.append(float(loss.detach().cpu()))
            vl = float(loss_fn(torch.from_numpy(v4.inference(model,val["x"])),torch.from_numpy(val["y"].astype(np.float32))))
            if not np.isfinite(vl) or not np.isfinite(losses).all():
                raise RuntimeError("Nonfinite loss")
            history.append({"epoch": epoch,"train_bce": float(np.mean(losses)),"validation_bce": vl})
            if vl < best-1e-6:
                best, stale, best_epoch = vl, 0, epoch
                torch.save({k:v.detach().cpu().clone() for k,v in model.state_dict().items()},out/f"mlp_seed{seed}.pt")
            else:
                stale += 1
            if epoch==1 or epoch%10==0:
                print("GPU_MLP_EPOCH",seed,epoch,"validation_bce",vl,flush=True)
            save(out/f"history_{seed}.json",history)
            if stale >= 15:
                break
        histories.append({"seed": seed,"best_epoch": best_epoch,"best_validation_bce": best,"epochs": len(history)})
    selected = min(histories,key=lambda x:x["best_validation_bce"])["seed"]
    save(out/"selection.json",{"selected_seed": selected,"candidates": histories})
    model = mlp.CrackMLP().cuda()
    model.load_state_dict(torch.load(out/f"mlp_seed{selected}.pt",map_location="cpu",weights_only=True))
    assert not calibration["y"].any()
    point = v4.calibrate(v4.inference(model,mlp.normalize(calibration["features"],mean,scale)),calibration)
    save(out/"frozen_operating_point.json",dict(selected_seed=selected,weight_sha256=sha(out/f"mlp_seed{selected}.pt"),**point))
    save(out/"inherited_data_hashes.json",file_hashes)
    if args.smoke:
        # Exercise finite-threshold selection without treating 24 normals as adequate.
        toy = {"labels": pd.DataFrame([{"nominal_angle_deg": a,"source": s} for s in sources for a in (45.,60.,70.) for _ in range(1000)]),"gate": np.ones(12000,bool),"quality": np.ones(12000,bool)}
        check = v4.calibrate(np.tile(np.arange(1000,dtype=float),12),toy)
        assert all(x==998. for x in check["angle_thresholds"].values())
    cnn = v4.arch.SmallWaveCNN().cuda()
    cnn_point = json.loads((base/"run/frozen_operating_points.json").read_text())
    cnn_seed = cnn_point["selected_seed"]
    if cnn_seed != 4103:
        raise RuntimeError("Unexpected CNN comparator checkpoint")
    cnn.load_state_dict(torch.load(base/f"run/seed{cnn_seed}_best.pt",map_location="cpu",weights_only=True))
    # Sources and final seed fixed before training. Check fresh hashes against ALL older data.
    existing_hashes = set()
    truth_files = list((base/"run").glob("*_truth.csv"))
    if len(truth_files) != 16:
        raise RuntimeError("Incomplete previous split inventory")
    for path in truth_files:
        existing_hashes.update(pd.read_csv(path).rf_sha256)
    save(out/"pretest_freeze.json", {"protocol_sha256":sha(out/"protocol.json"),"point_sha256":sha(out/"frozen_operating_point.json"),
                                    "normalization_sha256":sha(out/"normalization.json"),"source_hashes":code_hash,
                                    "cnn_weight_sha256":sha(base/f"run/seed{cnn_seed}_best.pt"),"frozen_unix":time.time()})
    final_hashes = set()
    reports, frames = {}, []
    for source_id, source in enumerate(sources):
        rf, labels = v4.generate(cfg,12 if args.smoke else 2400,9051 if args.smoke else 51,source_id)
        hashes = [hashlib.sha256(row.tobytes()).hexdigest() for row in rf]
        if len(set(hashes)) != len(hashes) or (set(hashes) & (existing_hashes|final_hashes)):
            raise RuntimeError("Repeated RF in fresh evaluation")
        final_hashes.update(hashes)
        labels["rf_sha256"] = hashes
        observed = [labels.nominal_wall_mm.to_numpy(),labels.nominal_angle_deg.to_numpy(),labels.measured_temp_c.to_numpy()]
        data = v4.prepare(cfg,rf,*observed)
        features = mlp.extract(cfg,rf,data["windows"],*observed)
        x = mlp.normalize(features,mean,scale)
        mlp_z, cnn_z = v4.inference(model,x), v4.inference(cnn,data["x"])
        y = labels.crack.to_numpy(bool)
        rows = {}
        for name,z,thresholds in (("mlp",mlp_z,point["angle_thresholds"]),("cnn",cnn_z,cnn_point["candidates"]["retrained"]["angle_thresholds"])):
            threshold = np.array([thresholds[str(float(a))] for a in observed[1]])
            pred = data["gate"] & data["quality"] & (z>threshold)
            rows[name] = v4.rates(pred,y,data["quality"],data["clipped"])
            rows[name]["angles"] = {str(a):v4.rates(pred[observed[1]==a],y[observed[1]==a],data["quality"][observed[1]==a],data["clipped"][observed[1]==a]) for a in (45.,60.,70.)}
            labels[name+"_logit"], labels[name+"_threshold"], labels[name+"_prediction"] = z, threshold, pred
        labels["gate"], labels["quality"], labels["partial_window"] = data["gate"],data["quality"],data["clipped"]
        frames.append(labels)
        reports[source] = rows
        labels.to_csv(out/f"fresh_{source}_predictions.csv",index=False)
        np.savez_compressed(out/f"fresh_{source}_inputs.npz",rf=rf,features=features,nominal_wall_mm=observed[0],
                            nominal_angle_deg=observed[1],observed_temp_c=observed[2],windows=data["windows"],
                            gate=data["gate"],quality=data["quality"],partial_window=data["clipped"])
        print("FRESH_TEST",source,json.dumps({k:{m:v for m,v in r.items() if m!='angles'} for k,r in rows.items()}),flush=True)
    pd.concat(frames,ignore_index=True).to_csv(out/"fresh_predictions.csv",index=False)
    save(out/"results.json",{"status": "completed","selected_seed": selected,"scope": protocol["scope"],
                                  "results": reports,"parameter_count": sum(p.numel() for p in model.parameters()),
                                  "cnn_parameter_count": sum(p.numel() for p in cnn.parameters()),
                                  "fresh_units": len(final_hashes),"fresh_vs_previous_rf_duplicates": len(final_hashes & existing_hashes),
                                  "peak_torch_allocated_bytes": torch.cuda.max_memory_allocated(),
                                  "peak_torch_reserved_bytes": torch.cuda.max_memory_reserved()})
    save(out/"hashes.json",{p.name:sha(p) for p in out.iterdir() if p.is_file()})
    if args.smoke:
        save(out/"completed.json",{"source_hashes":code_hash,"cuda":True,"features":len(mlp.FEATURE_NAMES),"fresh_smoke_units":len(final_hashes),"smoke_seed_id":9051})
        print("SMOKE_COMPLETED",flush=True)
    print("MLP_TRAINING_AND_FRESH_TEST_COMPLETED",flush=True)


if __name__ == "__main__":
    main()
