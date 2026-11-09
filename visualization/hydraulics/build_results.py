"""Solve all 247 pipes and recompute spatial shaft fields for each boundary scenario."""
from __future__ import annotations

import copy
import csv
import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np

from solver import Edge, Network, RU

ROOT = Path(__file__).resolve().parent
VIS = ROOT.parent
UNITY = VIS.parent / "unity/MAEKInspection/Assets/MAEK"
sys.path.insert(0, str(VIS / "cfd"))
from reactive_shaft import Shaft


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1, allow_nan=False),
                    encoding="utf-8")


def response_matrix(config):
    columns = []
    for k in range(8):
        c = dict(config, inlet_flows_m3_s=np.eye(8)[k].tolist())
        shaft = Shaft(c)
        columns.append(shaft.pressure[shaft.inlet])
    return np.array(columns).T


def make_network(net, catalog, cfg, scenario, response):
    nodes = {k: v["position"][2] for k, v in net["nodes"].items()}
    service = {p["id"]: p for p in catalog["pipes"]}
    by_node = {}
    edges = []
    for pipe in net["lines"]:
        code = service[pipe["id"]]["serviceCode"]
        for n in (pipe["from"], pipe["to"]):
            by_node.setdefault(n, (code, pipe["radius_m"]*2))
        a, b = pipe["from"], pipe["to"]
        closed = pipe["state"] == "closed"
        if pipe["id"] == "UTIL-N002" and scenario["utility_open"]:
            closed = False
        edges.append(Edge(pipe["id"], a, b,
                          2*pipe["radius_m"]*cfg["inside_to_outside_diameter"],
                          sum(math.dist(a, b) for a, b in zip(pipe["points"],
                                                            pipe["points"][1:])),
                          cfg["pipe_minor_k"], cfg["fluids"][code], nodes[b]-nodes[a],
                          closed=closed, service=code))
    default = dict(AIR="COLD_BLAST", BFG="BFG_CLEAN", CW="CW_SUPPLY",
                   N2="N2", INSTR_AIR="INSTR_AIR", FLUE="FLUE", COMB_AIR="COMB_AIR",
                   WASH="WASH", SLURRY="SLURRY")
    for k, link in enumerate(net["internal_connections"]):
        a, b = link["from"], link["to"]
        code, diameter = by_node.get(a, by_node.get(b, (default[net["nodes"][a]["medium"]], 1)))
        rise = 0
        if a.endswith("CB.INTAKE"):
            rise = cfg["blast_rise_pa"] * (scenario["bf1_blast_factor"]
                                           if a.startswith("BF1") else 1)
        elif a.endswith("CA.INTAKE"):
            rise = cfg["combustion_air_rise_pa"]
        elif a.endswith("CP.IN"):
            rise = cfg["cooling_pump_rise_pa"]
        elif a.endswith("WP.IN"):
            rise = cfg["wash_pump_rise_pa"]
        elif a.endswith("TRAIN.P.IN"):
            rise = cfg["training_pump_rise_pa"]
        closed = not link["active"]
        if a == "UTIL.N2.VALVE.IN" and scenario["utility_open"]:
            closed = False
        edges.append(Edge("INTERNAL-"+str(k), a, b,
                          diameter*cfg["inside_to_outside_diameter"], 1,
                          cfg["equipment_k"], cfg["fluids"][code], nodes[b]-nodes[a],
                          rise=rise, closed=closed))
    fixed = {}
    demands = {}
    x = cfg["raceway_oxygen_mole_fraction"]
    gas_mass_ratio = (1+x)*28.01/28.85
    for unit in ("BF1", "BF2"):
        for suffix in ("CB.INTAKE", "CA.INTAKE", "BS.VENT", "STK.VENT",
                       "MW.OUT", "SL.IN"):
            fixed[unit+"."+suffix] = cfg["atmosphere_pa"]
        fixed[unit+".CP.IN"] = cfg["cooling_anchor_pa_abs"]
        fixed[unit+".CASTHOUSE.TRAIN.P.IN"] = cfg["cooling_anchor_pa_abs"]
        top = unit+".CFD.TOP"
        nodes[top] = .5*(nodes[unit+".BF.G1"]+nodes[unit+".BF.G2"])
        for port in ("G1", "G2"):
            b = unit+".BF."+port
            edges.append(Edge(unit+"-CFD-OUT-"+port, top, b, 1.89, 1, 1,
                              cfg["fluids"]["BFG_RAW"], nodes[b]-nodes[top]))
        for k in range(12):
            a = unit+".BF.T"+str(k)
            diameter = by_node[a][1]*cfg["inside_to_outside_diameter"]
            sector = int(round(k*8/12)) % 8
            edges.append(Edge(unit+"-CFD-IN-"+str(k), a, top, diameter, 0,
                              cfg["furnace_port_k"], cfg["fluids"]["HOT_BLAST"],
                              nodes[top]-nodes[a], ratio=gas_mass_ratio,
                              furnace=unit, sector=sector))
    fixed["UTIL.N2.SOURCE.OUT"] = cfg["nitrogen_source_pa_abs"]
    fixed["UTIL.N2.RECOVERY.IN"] = cfg["nitrogen_receiver_pa_abs"]
    fixed["UTIL.IA.SOURCE.OUT"] = cfg["instrument_source_pa_abs"]
    demands["UTIL.N2.ACT.AIR"] = (cfg["actuation_demand_kg_s"]
                                   if scenario["utility_open"] else 0)
    result = Network(nodes, edges, fixed, demands, cfg["roughness_m"], response,
                     cfg["shaft_temperature_k"], cfg["trapped_reference_pa_abs"],
                     cfg["mass_tolerance_kg_s"], cfg["pressure_tolerance_pa"])
    return result.solve()


def shaft_case(network, unit, cfg, base_shaft):
    top_pressure = network.pressure[unit+".CFD.TOP"]
    density = top_pressure*28.01/(RU*cfg["shaft_temperature_k"])
    inlet = [e for e in network.edges if e.furnace == unit]
    q8 = np.bincount([e.sector for e in inlet],
                     weights=[e.ratio*network.mass[e.id]/density for e in inlet], minlength=8)
    if np.min(q8) <= 0:
        raise ValueError("Backflow/zero-flow shaft chemistry is not supported")
    c = dict(base_shaft, inlet_flows_m3_s=q8.tolist(), gas_feed_m3_s=float(q8.sum()),
             gas_total_kmol_m3=top_pressure/(RU*cfg["shaft_temperature_k"]),
             inlet_temperature_k=cfg["shaft_temperature_k"],
             inlet_co_fraction=2*cfg["raceway_oxygen_mole_fraction"] / (
                 1+cfg["raceway_oxygen_mole_fraction"]))
    shaft = Shaft(c)
    frames = []
    for time in np.arange(0, cfg["shaft_duration_s"]+.0001, cfg["shaft_write_interval_s"]):
        shaft.advance(time-shaft.time)
        frames.append(dict(time=float(time), temperature=shaft.temperature.tolist(),
                           co=(shaft.moles[:, 0]/shaft.pore/c["gas_total_kmol_m3"]).tolist(),
                           reduction=(shaft.moles[:, 4]/(2*c["ore_kmol_m3"]*shaft.vol)).tolist()))
    mismatch = []
    for e in inlet:
        mass = network.mass[e.id]
        air_rho = .5*(network.pressure[e.a]+top_pressure)*e.fluid[0]/(RU*e.fluid[1])
        local_loss = e.k*mass*abs(mass)/(2*air_rho*(np.pi*e.diameter**2/4)**2)
        predicted = top_pressure+shaft.pressure[shaft.inlet[e.sector]]+density*9.80665*e.dz
        mismatch.append(network.pressure[e.a]-local_loss-predicted)
    report = shaft.report()
    report.update(unit=unit, top_pressure_pa_abs=top_pressure,
                  gas_feed_m3_s=float(q8.sum()), gas_feed_kg_s=float(q8.sum()*density),
                  blast_mass_kg_s=float(sum(network.mass[e.id] for e in inlet)),
                  inlet_flows_m3_s=q8.tolist(),
                  coupling_pressure_residual_pa=float(max(abs(x) for x in mismatch)))
    if report["coupling_pressure_residual_pa"] > cfg["pressure_tolerance_pa"]:
        raise AssertionError(report)
    absolute = (shaft.pressure+top_pressure+density*9.80665*(
        network.elevations[unit+".CFD.TOP"]-(7.2+shaft.xyz[:, 2])))
    return dict(unit=unit, frames=frames, velocity=shaft.velocity.ravel().tolist(),
                pressure=absolute.tolist(), report=report)


def build():
    cfg = load(ROOT/"config.json")
    net = load(VIS/"pipe_services/services_network.json")
    catalog = load(VIS/"pipe_services/pipe_services.json")
    original_clip = load(VIS/"cfd/cfd_playback.json")
    base_shaft = load(VIS/"cfd/config.json")["shaft"]
    response = response_matrix(base_shaft)
    write(ROOT/"shaft_port_response.json", dict(units="Pa / (m3/s)", matrix=response.tolist()))
    cases = []
    cache = {}
    for scenario in cfg["scenarios"]:
        print("SOLVING", scenario["id"], flush=True)
        network = make_network(net, catalog, cfg, scenario, response)
        pipes = [network.values(e) for e in network.edges if e.service]
        assert len(pipes) == 247
        if max(p["mach"] for p in pipes) > cfg["maximum_mach"]:
            raise AssertionError("Low-Mach model invalid: adjust declared boundary assumptions")
        unit_results = []
        for unit in ("BF1", "BF2"):
            key = (unit, scenario["bf1_blast_factor"] if unit == "BF1" else 1)
            if key not in cache:
                cache[key] = shaft_case(network, unit, cfg, base_shaft)
            unit_results.append(cache[key])
        clip = copy.deepcopy(original_clip)
        clip["unitShafts"] = unit_results
        clip["shaftFrames"] = unit_results[0]["frames"]
        clip["shaftPressure"] = unit_results[0]["pressure"]
        clip["shaftVelocity"] = unit_results[0]["velocity"]
        clip["couplingLabel"] = "Pipe network <-> 3D Darcy shaft; hearth VOF remains independent"
        clip["scope"] = clip["couplingLabel"]
        clip_name = "coupled_cfd_"+scenario["id"]+".json"
        write(ROOT/clip_name, clip)
        write(UNITY/"Source"/clip_name, clip)
        report = dict(status="PASS", components=network.reports,
                      assumed_trapped_pressure_anchors=network.assumed_anchors,
                      max_mach=max(p["mach"] for p in pipes),
                      shaft=[u["report"] for u in unit_results],
                      nodal_pressure_pa_abs=network.pressure,
                      internal_mass_kg_s=network.mass,
                      fixed_pressure_boundaries_pa_abs=network.fixed,
                      demand_boundaries_kg_s=network.demands)
        write(ROOT/(scenario["id"]+"_report.json"), report)
        cases.append(dict(id=scenario["id"], label=scenario["label"], pipes=pipes,
                          clipName=clip_name, furnaces=[u["report"] for u in unit_results],
                          pressureResidual=max(r["momentum_residual_pa"] for r in network.reports),
                          massResidual=max(r["mass_residual_kg_s"] for r in network.reports)))
        print("SOLVED", scenario["id"], [(r["unit"], round(r["gas_feed_m3_s"], 4))
                                         for r in report["shaft"]], flush=True)
    result = dict(version=1, atmospherePa=cfg["atmosphere_pa"], scenarios=cases,
                  basis=cfg["basis"], coupling="Two-way steady pressure/flow to 3D Darcy shaft",
                  scope="Hearth VOF, pipe thermal transport and reaction-density feedback excluded")
    write(ROOT/"hydraulic_results.json", result)
    write(UNITY/"Source/hydraulic_results.json", result)
    with (ROOT/"pipe_pressure_flow.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["scenario"]+list(cases[0]["pipes"][0]))
        writer.writeheader()
        for case in cases:
            writer.writerows(dict(scenario=case["id"], **p) for p in case["pipes"])
    print("HYDRAULICS_COMPLETE", flush=True)


if __name__ == "__main__":
    build()
