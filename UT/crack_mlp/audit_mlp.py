"""Full MLP RF replay and paired statistical summaries; never changes thresholds."""
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from predict_mlp import FrozenMLP, default_baseline
from scipy.stats import beta, binomtest

ROOT=Path(__file__).resolve().parent


def clean(x):
    if isinstance(x,dict): return {str(k):clean(v) for k,v in x.items()}
    if isinstance(x,(list,tuple)): return [clean(v) for v in x]
    if isinstance(x,np.generic): x=x.item()
    return None if isinstance(x,float) and not np.isfinite(x) else x


def rates(pred,y):
    tp,fp=int((pred&y).sum()),int((pred&~y).sum())
    p,n=int(y.sum()),int((~y).sum())
    def interval(k,n):
        return [float(beta.ppf(.025,k,n-k+1)) if k else 0.,float(beta.ppf(.975,k+1,n-k)) if k<n else 1.]
    return {"tp":tp,"positive_units":p,"fp":fp,"normal_units":n,"recall":tp/p,"far":fp/n,
            "recall_ci95":interval(tp,p),"far_ci95":interval(fp,n)}


def main():
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    baseline=default_baseline()
    model=FrozenMLP(baseline)
    sys.path.insert(0,str(baseline))
    from pod_metrics_snapshot import pod_summary
    results=json.loads((ROOT/"run/results.json").read_text())
    frames=[]
    reports={}
    max_diff=0.
    for source in model.v4.SOURCES:
        frame=pd.read_csv(ROOT/f"run/fresh_{source}_predictions.csv")
        with np.load(ROOT/f"run/fresh_{source}_inputs.npz",allow_pickle=False) as data:
            hashes=[hashlib.sha256(row.tobytes()).hexdigest() for row in data["rf"]]
            if hashes!=frame.rf_sha256.tolist(): raise ValueError("RF mismatch")
            replay=model.predict(data["rf"],data["nominal_wall_mm"],data["nominal_angle_deg"],data["observed_temp_c"],
                                 sampling_mhz=100,probe_mhz=5,n_avg=16,origin="synthetic")
            np.testing.assert_array_equal(replay["features"],data["features"])
            np.testing.assert_array_equal(replay["gate"],data["gate"])
            np.testing.assert_array_equal(replay["indication"],frame.mlp_prediction.to_numpy(bool))
            diff=float(np.max(np.abs(replay["logits"]-frame.mlp_logit.to_numpy())))
            max_diff=max(max_diff,diff)
            np.testing.assert_allclose(replay["logits"],frame.mlp_logit.to_numpy(),rtol=3e-5,atol=3e-5)
            try:
                model.predict(data["rf"][:1],data["nominal_wall_mm"][:1],data["nominal_angle_deg"][:1],data["observed_temp_c"][:1],
                              sampling_mhz=100,probe_mhz=5,n_avg=1,origin="synthetic")
            except ValueError:
                pass
            else:
                raise AssertionError("Mismatched averaging accepted")
        y=frame.crack.to_numpy(bool)
        reports[source]={}
        for name in ("mlp","cnn"):
            pred=frame[name+"_prediction"].to_numpy(bool)
            row=rates(pred,y)
            for key in ("tp","fp","positive_units","normal_units"):
                if row[key]!=results["results"][source][name][key]: raise ValueError("Count mismatch")
            row["pod"]=pod_summary(frame.crack_height_mm.to_numpy()[y],pred[y],300,2026110951)
            reports[source][name]=row
        mp=frame.mlp_prediction.to_numpy(bool)
        cp=frame.cnn_prediction.to_numpy(bool)
        m_only=int((mp&~cp&y).sum())
        c_only=int((cp&~mp&y).sum())
        reports[source]["paired_positive_difference"]={"mlp_only_hits":m_only,"cnn_only_hits":c_only,
            "recall_difference":float(mp[y].mean()-cp[y].mean()),
            "mcnemar_exact_two_sided_p":float(binomtest(m_only,m_only+c_only,.5).pvalue) if m_only+c_only else 1.}
        frames.append(frame)
        print("MLP_RF_REPLAY",source,len(frame),"max_logit_difference",diff,flush=True)
    all_rows=pd.concat(frames,ignore_index=True)
    pooled={name:rates(all_rows[name+"_prediction"].to_numpy(bool),all_rows.crack.to_numpy(bool)) for name in ("mlp","cnn")}
    summary={"status":"verified","full_mlp_rf_replay_units":len(all_rows),"exact_mlp_decisions":True,
             "max_cpu_gpu_logit_difference":max_diff,"sources":reports,"pooled":pooled,
             "source_hashes":{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (Path(__file__),ROOT/"predict_mlp.py")},
             "note":"same-generator synthetic cases; pooled equal source weighting; per-source paired p values exploratory not multiplicity corrected"}
    (ROOT/"run/audit.json").write_text(json.dumps(clean(summary),indent=2,allow_nan=False),encoding="utf-8")
    print("AUDIT_COMPLETED",flush=True)


if __name__=="__main__":main()
