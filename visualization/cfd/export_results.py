"""Validate OpenFOAM fields and export actual 3-D surfaces/fields for playback."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

import numpy as np
from scipy.interpolate import LinearNDInterpolator
from skimage.measure import marching_cubes

ROOT = Path(__file__).resolve().parent


def field(path, count, vector=False):
    text = path.read_text()
    match = re.search(r"internalField\s+nonuniform\s+List<\w+>\s+(\d+)\s*\((.*?)\)\s*;",
                      text, re.S)
    if match:
        values = np.fromstring(match[2].replace("(", " ").replace(")", " "), sep=" ")
        assert int(match[1]) == count, (path, match[1], count)
        return values.reshape(count, 3) if vector else values
    match = re.search(r"internalField\s+uniform\s+([^;]+);", text)
    if not match:
        raise ValueError(f"Unsupported or missing ASCII field: {path}")
    values = np.fromstring(match[1].replace("(", " ").replace(")", " "), sep=" ")
    return np.tile(values, (count, 1)) if vector else np.full(count, values[0])


def load(case):
    meta = json.loads((case/"mesh_manifest.json").read_text())
    xyz = np.array(meta["centres"])
    if not (case/"0/C").exists():
        raise ValueError("Run foamPostProcess -func writeCellCentres -time 0 first")
    actual = field(case/"0/C", len(xyz), True)
    np.testing.assert_allclose(actual, xyz, atol=1e-9)
    times = sorted(float(p.name) for p in case.iterdir() if p.is_dir()
                   and re.fullmatch(r"\d+(?:\.\d+)?", p.name))
    data = []
    for t in times:
        folder = case/f"{t:g}"
        if t > 0 and (folder/"alpha.iron").stat().st_mtime < (case/"0/U").stat().st_mtime-1:
            raise ValueError(f"Stale CFD time {folder}; generate a fresh case directory")
        phases = np.array([field(folder/("alpha."+p), len(xyz))
                           for p in ("iron", "slag", "gas")]).T
        velocity = field(folder/"U", len(xyz), True)
        pressure = field(folder/"p_rgh", len(xyz))
        data.append((t, phases, velocity, pressure))
    return meta, xyz, data


def surface(values, xyz, h):
    # The padding closes the outside of the volume; no invented interface displacement.
    low = xyz.min(axis=0)-h
    ijk = np.rint((xyz-low)/h).astype(int)
    shape = ijk.max(axis=0)+2
    volume = np.zeros(shape, dtype=np.float32)
    volume[tuple(ijk.T)] = values
    if volume.max() <= .5:
        return {"vertices": [], "triangles": []}
    verts, faces, _, _ = marching_cubes(volume, .5, spacing=(h, h, h))
    verts += low
    return {"vertices": np.round(verts, 6).reshape(-1).tolist(),
            "triangles": faces.reshape(-1).tolist()}


def metrics(case, cfg):
    meta, xyz, data = load(case)
    h = meta["cell_m"]
    initial = data[0][1].sum(axis=0)*h**3
    volumes = np.array([row[1].sum(axis=0)*h**3 for row in data])
    time = np.array([row[0] for row in data])
    phase_values = np.concatenate([row[1].flatten() for row in data])
    sum_error = max(np.max(np.abs(row[1].sum(axis=1)-1)) for row in data)
    log = (case/"log.foamRun").read_text()
    # Opening remains submerged in iron; compare removed iron with imposed volume flux.
    expected = cfg["tap_flow_m3_s"]*time
    removed = initial[0]-volumes[:, 0]
    balance = float(np.max(np.abs(removed-expected)))
    qfiles = list((case/"postProcessing/tapFlux").glob("*/surfaceFieldValue.dat"))
    flux = np.loadtxt(qfiles[-1])
    return {"case": case.name, "cells": meta["cells"], "cell_m": h,
            "duration_s": float(time[-1]), "mesh_ok": "Mesh OK." in (case/"log.checkMesh").read_text(),
            "solver_finished": log.rstrip().endswith("End"),
            "alpha_min": float(phase_values.min()), "alpha_max": float(phase_values.max()),
            "phase_sum_max_error": float(sum_error),
            "iron_volume_balance_error_m3": balance,
            "iron_volume_balance_relative_inventory": balance/initial[0],
            "tap_flux_max_error_m3_s": float(np.max(np.abs(flux[:, 1]-cfg["tap_flow_m3_s"]))),
            "initial_phase_volume_m3": initial.tolist(),
            "final_phase_volume_m3": volumes[-1].tolist(),
            "max_speed_m_s": float(max(np.linalg.norm(row[2], axis=1).max() for row in data)),
            "time": time.tolist(), "iron_out_m3": removed.tolist(),
            "declared_tap_m3": expected.tolist()}


def run(case_name):
    cfg = json.loads((ROOT/"config.json").read_text())
    case = ROOT/case_name
    meta, xyz, data = load(case)
    report = metrics(case, cfg["hearth"])
    frames = []
    h = meta["cell_m"]
    # Sparse vectors on the central slice, indexed from solved velocities.
    ix = np.rint((xyz[:, 0]-xyz[:, 0].min())/h).astype(int)
    iz = np.rint((xyz[:, 2]-xyz[:, 2].min())/h).astype(int)
    select = np.where((abs(xyz[:, 1]-h/2) < h*.1) & (ix % 4 == 0) &
                      (iz % 2 == 0) & (xyz[:, 2] < 2.5))[0]
    for time, alpha, vel, pressure in data:
        frames.append({"time": time, "iron": surface(alpha[:, 0], xyz, h),
                       "slag": surface(alpha[:, 1], xyz, h),
                       "vectors": np.round(vel[select], 7).flatten().tolist(),
                       "pressure": np.round(pressure[select], 2).tolist()})
    shaft = json.loads((ROOT/"shaft_result.json").read_text())
    result = {"version": 1, "solver": "OpenFOAM Foundation 14 incompressibleMultiphaseVoF",
              "scope": "3D isothermal iron/slag/gas VOF + separate 3D reactive Darcy shaft. "
                       "Not a fully coupled industrial furnace model.",
              "hearthCellM": h, "hearthCells": meta["cells"],
              "vectorPositions": xyz[select].flatten().tolist(), "hearthFrames": frames,
              "shaftCellM": shaft["cell_m"],
              "shaftPositions": np.array(shaft["positions"]).flatten().tolist(),
              "shaftVelocity": np.array(shaft["velocity"]).flatten().tolist(),
              "shaftPressure": shaft["pressure"], "shaftFrames": shaft["frames"]}
    target = ROOT.parent.parent/"unity/MAEKInspection/Assets/MAEK/Source/cfd_playback.json"
    text = json.dumps(result, separators=(",", ":"))
    if target.parent.is_dir():
        target.write_text(text, encoding="utf-8")
    (ROOT/"cfd_playback.json").write_text(text, encoding="utf-8")
    report["playback_sha256"] = hashlib.sha256(text.encode()).hexdigest()
    report["shaft"] = shaft["report"]
    report["checks"] = {
        "mesh": report["mesh_ok"], "solver": report["solver_finished"],
        "duration": report["duration_s"] == cfg["hearth"]["duration_s"],
        "bounded_phases": report["alpha_min"] > -1e-4 and report["alpha_max"] < 1.0001,
        "phase_sum": report["phase_sum_max_error"] < 1e-4,
        "inventory_balance": report["iron_volume_balance_relative_inventory"] < 1e-5,
        "tap_flux": report["tap_flux_max_error_m3_s"] < 1e-10,
        "shaft_atoms": max(abs(v) for v in shaft["report"]["atom_residual_kmol"]) < 1e-7,
        "shaft_energy": abs(shaft["report"]["energy_residual_j"]) < 1,
        "saved_surfaces": all(len(f["iron"]["triangles"]) > 0 and
                              len(f["slag"]["triangles"]) > 0 for f in frames),
    }
    coarse_meta, coarse_xyz, coarse_data = load(ROOT/"hearth")
    coarse_report = metrics(ROOT/"hearth", cfg["hearth"])
    fine_velocity_at_coarse = LinearNDInterpolator(xyz, data[-1][2])(coarse_xyz)
    valid = np.isfinite(fine_velocity_at_coarse).all(axis=1) & (coarse_data[-1][1][:, 0] > .9)
    difference = fine_velocity_at_coarse[valid]-coarse_data[-1][2][valid]
    report["mesh_sensitivity"] = {
        "coarse_cells": coarse_meta["cells"], "fine_cells": meta["cells"],
        "liquid_velocity_rms_difference_m_s": float(np.sqrt(np.mean(difference**2))),
        "fine_liquid_velocity_rms_m_s": float(np.sqrt(np.mean(fine_velocity_at_coarse[valid]**2))),
        "iron_out_coarse_m3": coarse_report["iron_out_m3"][-1],
        "iron_out_fine_m3": report["iron_out_m3"][-1],
        "interpretation": "Two meshes only: sensitivity measurement, NOT grid independence."}
    equilibrium_meta, _, equilibrium_data = load(ROOT/"hearth_equilibrium")
    liquid_speed = max(np.linalg.norm(row[2][row[1][:, 0] > .9], axis=1).max()
                       for row in equilibrium_data)
    equilibrium_drift = (equilibrium_data[-1][1]-equilibrium_data[0][1]).sum(axis=0) * (
        equilibrium_meta["cell_m"]**3)
    report["hydrostatic_check"] = {
        "duration_s": equilibrium_data[-1][0],
        "max_iron_speed_m_s": float(liquid_speed),
        "max_gas_or_interface_speed_m_s": float(max(
            np.linalg.norm(row[2], axis=1).max() for row in equilibrium_data)),
        "phase_volume_drift_m3": equilibrium_drift.tolist(),
        "interpretation": "Stationary liquid check; nonzero gas/interface spurious currents remain."}
    report["checks"]["stationary_iron"] = liquid_speed < 1e-4
    report["checks"]["closed_phase_inventory"] = np.max(abs(equilibrium_drift)) < 1e-3
    report["checks"] = {key: bool(value) for key, value in report["checks"].items()}
    report["status"] = "PASS" if all(report["checks"].values()) else "FAIL"
    (ROOT/"verification.json").write_text(json.dumps(report, indent=2))
    print(json.dumps({k: v for k, v in report.items() if k not in
                      ("time", "iron_out_m3", "declared_tap_m3")}, indent=2))
    if report["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", default="hearth_fine")
    run(parser.parse_args().case)
