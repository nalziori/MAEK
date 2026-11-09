"""One-way network/shaft pressure -> nozzle closure -> fresh 3-phase OpenFOAM runs.

The nozzle closure holds initial liquid heads fixed over the 12-second window.
It is not a two-way evolving free-surface/nozzle coupling.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math

import numpy as np

from build_results import ROOT, VIS, UNITY, load, write
from build_case import create
import export_results as export


def prepare():
    cfg = load(ROOT/"config.json")
    base = load(VIS/"cfd/config.json")["hearth"]
    data = load(ROOT/"hydraulic_results.json")
    positions = np.array(load(VIS/"cfd/cfd_playback.json")["shaftPositions"]).reshape(-1, 3)
    bottom = positions[:, 2] == positions[:, 2].min()
    head = 9.81*(base["iron_density"]*(base["iron_height_m"]-.25)
                 +base["slag_density"]*base["slag_height_m"])
    resistance = (150000-cfg["atmosphere_pa"]+head)/base["tap_flow_m3_s"]**2
    cases = []
    for scenario in data["scenarios"][:2]:
        clip = load(ROOT/scenario["clipName"])
        # Mean lower-shaft pressure mapped from z=7.7m to the hearth roof z=7.2m.
        report = clip["unitShafts"][0]["report"]
        rho = report["gas_feed_kg_s"]/report["gas_feed_m3_s"]
        gas_pressure = float(np.mean(np.array(clip["unitShafts"][0]["pressure"])[bottom])
                             +rho*9.80665*.5)
        q = math.sqrt(max(0, gas_pressure-cfg["atmosphere_pa"]+head)/resistance)
        c = dict(base, cell_m=.25, tap_flow_m3_s=q)
        inputs = dict(config=c, gas_pressure_pa_abs=gas_pressure,
                      nozzle_resistance_pa_per_m6_s2=resistance,
                      initial_liquid_head_pa=head, atmosphere_pa=cfg["atmosphere_pa"],
                      reference_top_pressure_pa_abs=150000,
                      reference_tap_m3_s=base["tap_flow_m3_s"])
        key = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()[:10]
        path = ROOT/("hearth_"+scenario["id"]+"_"+key)
        if not path.exists():
            create(path, c)
            p = path/"0/p_rgh"
            p.write_text(p.read_text().replace("150000", f"{gas_pressure:.12g}"))
            write(path/"coupling_inputs.json", inputs)
        else:
            assert load(path/"coupling_inputs.json") == inputs
        cases.append(dict(id=scenario["id"], path=str(path), **inputs))
    write(ROOT/"hearth_run_plan.json", dict(cases=cases))
    print("HEARTH_PREPARED", [(c["id"], c["config"]["tap_flow_m3_s"]) for c in cases])


def finish():
    cases = load(ROOT/"hearth_run_plan.json")["cases"]
    units, reports = {}, []
    for case in cases:
        from pathlib import Path
        path = Path(case["path"])
        meta, xyz, data = export.load(path)
        report = export.metrics(path, case["config"])
        checks = dict(finished=report["solver_finished"], mesh=report["mesh_ok"],
                      duration=report["duration_s"] == case["config"]["duration_s"],
                      phases=report["alpha_min"] > -1e-4 and report["alpha_max"] < 1.0001,
                      phase_sum=report["phase_sum_max_error"] < 1e-4,
                      inventory=report["iron_volume_balance_relative_inventory"] < 1e-5,
                      outlet_flux=report["tap_flux_max_error_m3_s"] < 1e-10)
        checks = {key: bool(value) for key, value in checks.items()}
        assert all(checks.values()), (case["id"], report)
        h = meta["cell_m"]
        ix = np.rint((xyz[:, 0]-xyz[:, 0].min())/h).astype(int)
        iz = np.rint((xyz[:, 2]-xyz[:, 2].min())/h).astype(int)
        select = np.where((abs(xyz[:, 1]-h/2) < h*.1) & (ix % 4 == 0) &
                          (iz % 2 == 0) & (xyz[:, 2] < 2.5))[0]
        frames = [dict(time=t, iron=export.surface(alpha[:, 0], xyz, h),
                       slag=export.surface(alpha[:, 1], xyz, h),
                       vectors=np.round(vel[select], 7).ravel().tolist(),
                       pressure=np.round(p[select], 2).tolist()) for t, alpha, vel, p in data]
        units[case["id"]] = dict(frames=frames, vectorPositions=xyz[select].ravel().tolist())
        reports.append(dict(id=case["id"], status="PASS", checks=checks,
                            coupling_inputs=case, numerical=report))
    hydraulic = load(ROOT/"hydraulic_results.json")
    config = load(ROOT/"config.json")
    service = {p["id"]: p["serviceCode"] for p in load(
        VIS/"pipe_services/pipe_services.json")["pipes"]}
    for scenario in hydraulic["scenarios"]:
        for pipe in scenario["pipes"]:
            molecular, temp, _, liquid = config["fluids"][service[pipe["id"]]]
            if not liquid:
                peak_speed = max(abs(pipe["volumeFromM3S"]), abs(pipe["volumeToM3S"])) / (
                    math.pi*pipe["insideDiameterM"]**2/4)
                pipe["mach"] = peak_speed/math.sqrt(1.4*8314.462618*temp/molecular)
                assert pipe["mach"] < config["maximum_mach"]
        pipe_report = load(ROOT/(scenario["id"]+"_report.json"))
        pipe_report["max_mach"] = max(p["mach"] for p in scenario["pipes"])
        write(ROOT/(scenario["id"]+"_report.json"), pipe_report)
        clip = load(ROOT/scenario["clipName"])
        key = "reduced_blast" if scenario["id"] == "reduced_blast" else "baseline"
        clip["unitHearths"] = [dict(unit="BF1", **units[key]),
                               dict(unit="BF2", **units["baseline"])]
        clip["hearthFrames"] = units[key]["frames"]
        clip["vectorPositions"] = units[key]["vectorPositions"]
        clip["couplingLabel"] = "Network <-> 3D shaft; gas pressure -> nozzle -> VOF (one-way)"
        clip["scope"] = clip["couplingLabel"]
        write(ROOT/scenario["clipName"], clip)
        write(UNITY/"Source"/scenario["clipName"], clip)
    hydraulic["scope"] = "Two-way steady shaft hydraulics; one-way hearth pressure/nozzle boundary"
    write(ROOT/"hydraulic_results.json", hydraulic)
    write(UNITY/"Source/hydraulic_results.json", hydraulic)
    import csv
    with (ROOT/"pipe_pressure_flow.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["scenario"]+list(hydraulic["scenarios"][0]["pipes"][0]))
        writer.writeheader()
        for scenario in hydraulic["scenarios"]:
            writer.writerows(dict(scenario=scenario["id"], **p) for p in scenario["pipes"])
    write(ROOT/"hearth_coupling_report.json", dict(status="PASS", cases=reports))
    print("HEARTH_COUPLING_VERIFIED", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--export", action="store_true")
    finish() if parser.parse_args().export else prepare()
