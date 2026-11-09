"""Post-training recount/replay and paired legacy comparison; never selects weights."""
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import torch
from scipy.stats import beta

ROOT=Path(__file__).resolve().parent
sys.path[:0]=[str(ROOT),str(ROOT/'runtime'),str(ROOT/'crack_cnn')]
import train_crack_gpu_v4 as study
import angle_crack_runtime as old
import ut_design_v2 as arch
from pod_metrics_snapshot import pod_summary


def clean(x):
    if isinstance(x,dict): return {str(k):clean(v) for k,v in x.items()}
    if isinstance(x,(list,tuple)): return [clean(v) for v in x]
    if isinstance(x,np.generic): x=x.item()
    return None if isinstance(x,float) and not np.isfinite(x) else x


def metrics(pred,y):
    tp,fp=int((pred & y).sum()),int((pred & ~y).sum())
    p,n=int(y.sum()),int((~y).sum())
    return dict(tp=tp,positive_units=p,fp=fp,normal_units=n,recall=tp/p,far=fp/n,
                recall_ci95=[float(beta.ppf(.025,tp,p-tp+1)) if tp else 0.,float(beta.ppf(.975,tp+1,p-tp)) if tp<p else 1.],
                far_ci95=[float(beta.ppf(.025,fp,n-fp+1)) if fp else 0.,float(beta.ppf(.975,fp+1,n-fp)) if fp<n else 1.])


def main():
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    out=ROOT/'run'
    results=json.loads((out/'results.json').read_text())
    frozen=json.loads((out/'frozen_operating_points.json').read_text())
    cfg=json.loads((out/'config_snapshot.json').read_text())
    predictions=pd.read_csv(out/'test_predictions.csv')
    selected=results['selected_seed']
    model=arch.SmallWaveCNN()
    model.load_state_dict(torch.load(out/f'seed{selected}_best.pt',map_location='cpu',weights_only=True))
    baseline=old.FrozenCrackRuntime()
    reports={}
    max_logit_error=0.
    total_hashes=0
    all_ids=[]
    all_hashes=[]
    for path in sorted(out.glob('*_truth.csv')):
        df=pd.read_csv(path)
        all_ids.extend(df.unit_id)
        all_hashes.extend(df.rf_sha256)
    assert len(set(all_ids))==len(all_ids) and len(set(all_hashes))==len(all_hashes)
    for source in study.SOURCES:
        frame=predictions[predictions.source==source].copy()
        arrays=np.load(out/f'test_{source}_inputs.npz',allow_pickle=False)
        rf=arrays['rf']
        assert [hashlib.sha256(x.tobytes()).hexdigest() for x in rf]==frame.rf_sha256.tolist()
        total_hashes+=len(rf)
        # Replay RF preprocessing and selected CPU inference on 48 evenly spaced units.
        ids=np.linspace(0,len(rf)-1,48,dtype=int)
        prep=study.prepare(cfg,rf[ids],arrays['nominal_wall_mm'][ids],arrays['nominal_angle_deg'][ids],arrays['observed_temp_c'][ids])
        np.testing.assert_array_equal(prep['x'],arrays['channels'][ids])
        np.testing.assert_array_equal(prep['gate'],arrays['gate'][ids])
        z=study.inference(model,prep['x'])
        saved_z=frame.retrained_logit.to_numpy()[ids]
        error=float(np.max(np.abs(z-saved_z)))
        max_logit_error=max(max_logit_error,error)
        np.testing.assert_allclose(z,saved_z,rtol=2e-5,atol=2e-5)
        thresholds=np.array([frozen['candidates']['retrained']['angle_thresholds'][str(float(a))] for a in arrays['nominal_angle_deg'][ids]])
        np.testing.assert_array_equal(prep['gate'] & prep['quality'] & (z>thresholds),frame.retrained_prediction.to_numpy(bool)[ids])
        # Same new RF, original frozen v3 API/thresholds; diagnostic comparison only.
        prior=baseline.predict(rf,nominal_wall_mm=arrays['nominal_wall_mm'],nominal_probe_angle_deg=arrays['nominal_angle_deg'],
                               measured_temp_c=arrays['observed_temp_c'],sampling_hz=100e6,probe_frequency_hz=5e6,
                               origin='synthetic',material_profile='generic_carbon_steel_assumed')
        frame['original_v3_prediction']=prior['indication']
        frame.to_csv(out/f'audited_test_{source}.csv',index=False)
        y=frame.crack.to_numpy(bool)
        reports[source]={}
        for name,col in [('retrained','retrained_prediction'),('old_weights_wide_window','old_weights_wide_window_prediction'),('original_v3','original_v3_prediction')]:
            pred=frame[col].to_numpy(bool)
            row=metrics(pred,y)
            if name!='original_v3':
                for k in ('tp','fp','positive_units','normal_units'):
                    assert row[k]==results['results'][name][source][k]
            row['pod']=pod_summary(frame.crack_height_mm.to_numpy()[y],pred[y],300,2026110941)
            row['angles']={str(a):metrics(pred[frame.nominal_angle_deg.to_numpy()==a],y[frame.nominal_angle_deg.to_numpy()==a]) for a in (45.,60.,70.)}
            reports[source][name]=row
        print('AUDITED',source,json.dumps({k:{m:v for m,v in r.items() if m in ('tp','fp','recall','far')} for k,r in reports[source].items()}),flush=True)
    summary=dict(status='verified',no_model_or_threshold_changes=True,unique_unit_ids=len(all_ids),unique_rf_hashes=len(all_hashes),
                 test_rf_hashes_verified=total_hashes,rf_preprocessing_replay_units=192,cpu_gpu_logit_max_difference=max_logit_error,
                 paired_comparison_scope='same new test RF; original v3 has its old calibration, wide-weight control shares new calibration procedure',
                 sources=reports,selected_seed=selected,measured_angle_validation=False,
                 source_hashes={p.name:study.digest(p) for p in (Path(__file__),ROOT/'pod_metrics_snapshot.py',ROOT/'pod_snapshot.py')})
    (out/'independent_audit.json').write_text(json.dumps(clean(summary),indent=2,allow_nan=False),encoding='utf-8')
    print('AUDIT_COMPLETED',max_logit_error,flush=True)


if __name__=='__main__': main()
