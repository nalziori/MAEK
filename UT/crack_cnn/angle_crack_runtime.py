"""Replay-only frozen v3 crack inference with explicit nominal, not truth, inputs.

This model is qualified ONLY for its declared synthetic 5-MHz carbon-steel profile.
It is not a measured UT or Jetson validation and supplies no pit/thickness classifier.
"""
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import torch
from scipy.signal import hilbert, resample_poly

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runtime"))
import crack_helpers as legacy
import ut_design_v2 as candidate

from maek import params, ut

ROOT=Path(__file__).resolve().parent


def prepare_nominal_inputs(cfg,rf,nominal_wall_mm,analysis_angle_deg,measured_temp_c):
    rf=np.asarray(rf,dtype=np.float32)
    nominal=np.asarray(nominal_wall_mm,dtype=float)
    angles=np.asarray(analysis_angle_deg,dtype=float)
    temps=np.asarray(measured_temp_c,dtype=float)
    if rf.ndim!=2 or rf.shape[1]!=params.get(cfg,"ut.n_samples"):
        raise ValueError("RF length must match frozen model protocol")
    if any(a.shape!=(len(rf),) or not np.isfinite(a).all() for a in (nominal,angles,temps)) or not np.isfinite(rf).all():
        raise ValueError("Require finite RF and aligned nominal metadata")
    fs=params.get(cfg,"ut.sampling_mhz")*1e6
    pulse=ut._pulse(cfg,np.arange(-64,65)/fs,0.)
    windows=legacy.crack_windows(cfg,nominal,angles,temps)
    gate=np.zeros(len(rf),bool)
    ratio=np.zeros(len(rf))
    noise=np.zeros(len(rf))
    quality=np.ones(len(rf),bool)
    for i,(signal,(lo,hi)) in enumerate(zip(rf,windows)):
        filtered=candidate.matched_filter(signal,pulse)
        power=np.abs(hilbert(filtered))**2
        passed,threshold=candidate.ca_cfar_power(power)
        quality[i]=hi>lo and np.isfinite(threshold[lo:hi]).all()
        gate[i]=passed[lo:hi].any() if quality[i] else False
        local=power[lo:hi]/threshold[lo:hi]
        finite=local[np.isfinite(local)]
        ratio[i]=float(finite.max()) if len(finite) else 0.
        start=int(ut._p(cfg)["t0"]*fs)
        outside=np.r_[signal[start:lo],signal[hi:]]
        sigma=1.4826*np.median(np.abs(outside-np.median(outside))) if len(outside) else 0.
        quality[i]&=sigma>1e-8
        noise[i]=max(sigma,1e-6)
    reduced=resample_poly(rf,1,4,axis=-1).astype(np.float32)
    x=np.arcsinh(reduced/noise[:,None]/4).astype(np.float32)
    envelope=np.arcsinh(np.abs(hilbert(reduced,axis=-1))/noise[:,None]/4).astype(np.float32)
    fullmask=legacy.window_mask(windows,rf.shape[1])
    mask=fullmask.reshape(len(rf),-1,4).any(axis=-1)
    return {"channels": np.stack([x,envelope,mask.astype(np.float32)],axis=1),"gate": gate,"gate_ratio": ratio,
                "quality": quality,"windows": windows}


def snell_angle_at_measured_temperature(cfg,nominal_angle_deg,measured_temp_c):
    """Candidate correction assuming fixed wedge incident angle AND constant wedge speed.

    sin(theta_steel(T))/sin(theta_steel(20)) = Vs(T)/Vs(20).
    Wedge heating changes this ratio too and is not modeled/calibrated here.
    """
    nominal=np.asarray(nominal_angle_deg,float)
    temperature=np.asarray(measured_temp_c,float)
    base=ut.velocity_shear(cfg,20.)
    velocities=np.array([ut.velocity_shear(cfg,t) for t in temperature])
    sine=velocities/base*np.sin(np.deg2rad(nominal))
    if not np.isfinite(sine).all() or (np.abs(sine)>=1).any():
        raise ValueError("Unsupported refraction/critical-angle state")
    return np.rad2deg(np.arcsin(sine))


def snell_angles_or_abstain(cfg,nominal_angle_deg,measured_temp_c):
    """Batch-safe candidate correction: invalid rows stay NaN, valid rows continue."""
    nominal=np.asarray(nominal_angle_deg,float)
    measured=np.asarray(measured_temp_c,float)
    if nominal.ndim!=1 or measured.shape!=nominal.shape:
        raise ValueError("Aligned per-observation angle/temperature required")
    corrected=np.full(len(nominal),np.nan)
    valid=np.isfinite(nominal)&np.isfinite(measured)
    for i in np.flatnonzero(valid):
        try:
            corrected[i]=snell_angle_at_measured_temperature(cfg,[nominal[i]],[measured[i]])[0]
        except ValueError:
            valid[i]=False
    return corrected,valid


class FrozenCrackRuntime:
    def __init__(self):
        original=ROOT/"crack_training_v1"
        self.cfg=json.loads((original/"config_snapshot.json").read_text(encoding="utf-8"))
        self.point=json.loads((ROOT/"crack_profile_v3/frozen_operating_point.json").read_text(encoding="utf-8"))
        path=original/f"crack_cnn_seed{self.point['selected_seed']}.pt"
        if hashlib.sha256(path.read_bytes()).hexdigest()!=self.point["model_sha256"]:
            raise ValueError("Frozen model weight hash mismatch")
        self.model=candidate.SmallWaveCNN()
        self.model.load_state_dict(torch.load(path,map_location="cpu",weights_only=True))
        self.model.eval()

    def predict(self,rf,*,nominal_wall_mm,nominal_probe_angle_deg,measured_temp_c,
                sampling_hz,probe_frequency_hz,origin,material_profile,
                analysis_angle_deg=None):
        if origin!="synthetic" or material_profile!="generic_carbon_steel_assumed":
            raise ValueError("Unqualified measured/material domain; no validated operating point")
        if sampling_hz!=params.get(self.cfg,"ut.sampling_mhz")*1e6 or probe_frequency_hz!=params.get(self.cfg,"ut.probe_freq_mhz")*1e6:
            raise ValueError("Sampling/probe mismatch with frozen 5MHz/100MHz model")
        nominal=np.asarray(nominal_wall_mm,float)
        key_angles=np.asarray(nominal_probe_angle_deg,float)
        angles=key_angles if analysis_angle_deg is None else np.asarray(analysis_angle_deg,float)
        rf=np.asarray(rf,dtype=np.float32)
        measured=np.asarray(measured_temp_c,float)
        if rf.ndim!=2 or rf.shape[1]!=params.get(self.cfg,"ut.n_samples"):
            raise ValueError("RF length must match frozen model protocol")
        n=len(rf)
        if any(a.shape!=(n,) for a in (nominal,key_angles,angles,measured)):
            raise ValueError("Metadata rows must align with RF observations")
        low,high=params.get(self.cfg,"ut.dataset.wall_range_mm")
        numeric=np.isfinite(rf).all(axis=1)&np.isfinite(nominal)&np.isfinite(key_angles)&np.isfinite(angles)&np.isfinite(measured)
        geometry=(nominal>=low)&(nominal<=high)&np.isin(key_angles,[45.,60.,70.])&(angles>0)&(angles<80)
        computable=numeric&geometry
        processed=np.flatnonzero(computable)
        channels=np.zeros((n,3,rf.shape[1]//4),np.float32)
        gate=np.zeros(n,bool)
        quality=np.zeros(n,bool)
        windows=np.zeros((n,2),int)
        if len(processed):
            data=prepare_nominal_inputs(self.cfg,rf[processed],nominal[processed],angles[processed],measured[processed])
            channels[processed]=data["channels"]
            gate[processed]=data["gate"]
            quality[processed]=data["quality"]
            windows[processed]=data["windows"]
        supported=computable&quality
        diagnostic=supported&~np.isclose(angles,key_angles,rtol=0,atol=1e-10)
        thresholds=np.array([self.point["angle_thresholds"].get(str(float(a)),np.inf) for a in key_angles])
        z=np.full(n,np.nan)
        with torch.no_grad():
            valid_ids=np.flatnonzero(supported)
            for start in range(0,len(valid_ids),128):
                batch=valid_ids[start:start+128]
                z[batch]=self.model(torch.from_numpy(channels[batch])).numpy()
        indication=supported&gate&(z>thresholds)
        statuses=np.full(n,"indeterminate",dtype="U24")
        statuses[numeric&~geometry]="unsupported_domain"
        statuses[supported&~diagnostic&~indication]="no_anomaly_observed"
        statuses[supported&~diagnostic&indication]="anomaly_observed"
        flags=[]
        for i in range(n):
            if not numeric[i]: reason=["invalid_per_observation_input"]
            elif not geometry[i]: reason=["outside_frozen_geometry_profile"]
            elif not quality[i]: reason=["unusable_noise_or_CFAR_reference"]
            elif diagnostic[i]: reason=["diagnostic_angle_correction_uncalibrated"]
            else: reason=[]
            flags.append(reason)
        return {"logits": z,"thresholds": thresholds,"gate": gate,"supported": supported,
                    "indication": indication,"windows": windows,"channels": channels,
                    "assessment_status": statuses,"quality_flags": flags,
                    "calibrated_operating_point": supported&~diagnostic,
                    "followup_required": np.isin(statuses,["indeterminate","unsupported_domain"])}
