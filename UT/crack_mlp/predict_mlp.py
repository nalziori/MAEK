"""Frozen synthetic crack MLP inference; nominal metadata only, no truth input."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import torch

ROOT = Path(__file__).resolve().parent


def default_baseline():
    candidates = [ROOT.parent/"crack_retrain_v4_20261109", ROOT.parent/"crack_cnn/crack_retraining_v4"]
    return next((p for p in candidates if p.is_dir()), candidates[0])


class FrozenMLP:
    def __init__(self, baseline=None):
        base = Path(baseline or default_baseline()).resolve()
        sys.dont_write_bytecode = True
        sys.path[:0] = [str(base), str(base/"runtime"), str(base/"crack_cnn")]
        import crack_mlp
        import train_crack_gpu_v4

        self.core = crack_mlp
        self.v4 = train_crack_gpu_v4
        self.cfg = json.loads((ROOT/"run/config_snapshot.json").read_text(encoding="utf-8"))
        self.point = json.loads((ROOT/"run/frozen_operating_point.json").read_text(encoding="utf-8"))
        self.norm = json.loads((ROOT/"run/normalization.json").read_text(encoding="utf-8"))
        freeze = json.loads((ROOT/"run/pretest_freeze.json").read_text(encoding="utf-8"))
        weights = ROOT/f"run/mlp_seed{self.point['selected_seed']}.pt"
        if hashlib.sha256(weights.read_bytes()).hexdigest() != self.point["weight_sha256"]:
            raise ValueError("Checkpoint hash mismatch")
        for file, expected in [(ROOT/"run/normalization.json", freeze["normalization_sha256"]),
                               (ROOT/"run/frozen_operating_point.json", freeze["point_sha256"]),
                               (ROOT/"crack_mlp.py", freeze["source_hashes"]["crack_mlp.py"])]:
            if hashlib.sha256(file.read_bytes()).hexdigest() != expected:
                raise ValueError("Frozen artifact hash mismatch")
        if self.norm["feature_names"] != self.core.FEATURE_NAMES:
            raise ValueError("Feature order mismatch")
        self.model = self.core.CrackMLP()
        self.model.load_state_dict(torch.load(weights,map_location="cpu",weights_only=True))
        self.model.eval()

    def predict(self, rf, nominal_wall_mm, nominal_angle_deg, observed_temp_c,
                *, sampling_mhz, probe_mhz, n_avg, origin):
        if (sampling_mhz, probe_mhz, n_avg, origin) != (100,5,16,"synthetic"):
            raise ValueError("Qualified only for synthetic 5MHz/100MHz/16-shot profile")
        rf = np.asarray(rf,np.float32)
        obs = [np.asarray(v,float) for v in (nominal_wall_mm,nominal_angle_deg,observed_temp_c)]
        if rf.ndim != 2 or rf.shape[1] != 4096 or not np.isfinite(rf).all():
            raise ValueError("Require finite RF (N,4096)")
        if any(v.shape != (len(rf),) or not np.isfinite(v).all() for v in obs):
            raise ValueError("Require finite aligned metadata")
        if not np.all((obs[0]>=3)&(obs[0]<=12)) or not np.isin(obs[1],[45.,60.,70.]).all():
            raise ValueError("Outside nominal geometry profile")
        data = self.v4.prepare(self.cfg,rf,*obs)
        features = self.core.extract(self.cfg,rf,data["windows"],*obs)
        x = self.core.normalize(features,self.norm["mean"],self.norm["scale"])
        z = self.v4.inference(self.model,x)
        threshold = np.array([self.point["angle_thresholds"][str(float(a))] for a in obs[1]])
        pred = data["gate"] & data["quality"] & (z>threshold)
        followup = (~data["quality"] | data["clipped"]) & ~pred
        return {"logits":z,"thresholds":threshold,"indication":pred,"gate":data["gate"],
                "quality":data["quality"],"partial_window":data["clipped"],
                "followup_required":followup,"features":features,"windows":data["windows"]}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--input",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--baseline",type=Path,default=None)
    parser.add_argument("--sampling-mhz",type=float,required=True)
    parser.add_argument("--probe-mhz",type=float,required=True)
    parser.add_argument("--n-avg",type=int,required=True)
    args=parser.parse_args()
    if args.output.exists():
        raise FileExistsError("Refusing to overwrite output")
    torch.set_num_threads(1)
    model=FrozenMLP(args.baseline)
    with np.load(args.input,allow_pickle=False) as data:
        result=model.predict(data["rf"],data["nominal_wall_mm"],data["nominal_angle_deg"],data["observed_temp_c"],
                             sampling_mhz=args.sampling_mhz,probe_mhz=args.probe_mhz,n_avg=args.n_avg,origin="synthetic")
    # Exclusive creation also protects input if caller accidentally selected same path.
    with args.output.open("x",encoding="utf-8") as f:
        json.dump({k:v.tolist() for k,v in result.items() if k not in ("features","windows")},f,indent=2,allow_nan=False)


if __name__=="__main__":
    main()
