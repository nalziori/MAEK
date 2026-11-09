"""Independent analytic limits and coupling checks for the hydraulic solver."""
from __future__ import annotations

import json
import math
import unittest

import numpy as np

from solver import Edge, Network, G, RU
from build_results import ROOT, VIS, Shaft, response_matrix

WATER = (0, 293, .001, 1000)


class HydraulicTests(unittest.TestCase):
    def test_laminar_poiseuille_limit(self):
        edge = Edge("p", "a", "b", .01, 1, 0, WATER)
        net = Network({"a": 0, "b": 0}, [edge], {"a": 101335, "b": 101325}).solve()
        expected = math.pi*.01**4*10/(128*.001)*1000
        self.assertAlmostEqual(net.mass["p"], expected, places=9)

    def test_reversing_pressure_reverses_flow(self):
        edge = Edge("p", "a", "b", .1, 20, 2, WATER)
        forward = Network({"a": 0, "b": 0}, [edge], {"a": 201325, "b": 101325}).solve()
        reverse = Network({"a": 0, "b": 0}, [edge], {"b": 201325, "a": 101325}).solve()
        self.assertAlmostEqual(forward.mass["p"], -reverse.mass["p"], places=7)

    def test_isothermal_gas_pressure_squared_laminar_limit(self):
        fluid = (28.014, 293, .0000176, 0)
        edge = Edge("g", "a", "b", .001, 1000, 0, fluid)
        net = Network({"a": 0, "b": 0}, [edge], {"a": 401325, "b": 101325}).solve()
        expected = math.pi*.001**4*(401325**2-101325**2)/(
            256*.0000176*(RU/28.014)*293*1000)
        self.assertAlmostEqual(net.mass["g"], expected, places=11)
        values = net.values(edge)
        self.assertGreater(abs(values["volumeToM3S"]), abs(values["volumeFromM3S"]))

    def test_hydrostatic_column_without_demand(self):
        edge = Edge("p", "a", "b", .1, 10, 0, WATER, dz=10)
        net = Network({"a": 0, "b": 10}, [edge], {"a": 201325}).solve()
        self.assertAlmostEqual(net.mass["p"], 0, places=8)
        self.assertAlmostEqual(net.pressure["b"], 201325-1000*G*10, places=3)

    def test_parallel_branches_conserve_mass(self):
        edges = [Edge("in", "a", "j", .1, 20, 1, WATER),
                 Edge("left", "j", "b", .1, 10, 1, WATER),
                 Edge("right", "j", "c", .1, 10, 1, WATER)]
        net = Network(dict.fromkeys("ajbc", 0), edges,
                      {"a": 201325, "b": 101325, "c": 101325}).solve()
        self.assertAlmostEqual(net.mass["left"], net.mass["right"], places=7)
        self.assertAlmostEqual(net.mass["in"], net.mass["left"]+net.mass["right"], places=7)

    def test_closed_valve_sustains_pressure_jump_without_flow(self):
        edge = Edge("p", "a", "b", .1, 10, 0, WATER, closed=True)
        net = Network({"a": 0, "b": 0}, [edge], {"a": 201325, "b": 101325}).solve()
        self.assertEqual(net.mass["p"], 0)
        self.assertEqual(net.values(edge)["pressureFromPa"]-net.values(edge)["pressureToPa"], 100000)

    def test_shaft_response_matches_fresh_spatial_solve(self):
        config = json.loads((VIS/"cfd/config.json").read_text())["shaft"]
        matrix = response_matrix(config)
        feed = np.array([1, 2, 1.5, .7, .5, 1.2, 1.8, 2.2])
        model = Shaft(dict(config, inlet_flows_m3_s=feed.tolist()))
        np.testing.assert_allclose(matrix@feed, model.pressure[model.inlet], atol=1e-9)
        np.testing.assert_allclose(matrix, matrix.T, atol=1e-10)
        self.assertAlmostEqual(model.qtop.sum(), feed.sum(), places=8)

    def test_saved_cases_and_reaction_conservation(self):
        if not (ROOT/"hydraulic_results.json").exists():
            self.skipTest("Run build_results.py for the integration test")
        data = json.loads((ROOT/"hydraulic_results.json").read_text(encoding="utf-8"))
        cases = data["scenarios"]
        self.assertEqual(len(cases), 3)
        for case in cases:
            self.assertEqual(len({p["id"] for p in case["pipes"]}), 247)
            self.assertLess(case["massResidual"], 1e-6)
            self.assertLess(case["pressureResidual"], .05)
            for p in case["pipes"]:
                self.assertGreater(min(p["pressureFromPa"], p["pressureToPa"]), 0)
                self.assertLess(p["mach"], .3)
                if p["state"] == "closed":
                    self.assertEqual(p["massKgS"], 0)
            for f in case["furnaces"]:
                self.assertLess(f["coupling_pressure_residual_pa"], .05)
                self.assertLess(max(abs(x) for x in f["atom_residual_kmol"]), 1e-7)
                self.assertLess(abs(f["energy_residual_j"]), .1)
        self.assertLess(cases[1]["furnaces"][0]["blast_mass_kg_s"],
                        cases[0]["furnaces"][0]["blast_mass_kg_s"])
        self.assertAlmostEqual(cases[1]["furnaces"][1]["blast_mass_kg_s"],
                               cases[0]["furnaces"][1]["blast_mass_kg_s"], places=5)
        base = {p["id"]: p for p in cases[0]["pipes"]}
        opened = {p["id"]: p for p in cases[2]["pipes"]}
        self.assertEqual(base["UTIL-N002"]["massKgS"], 0)
        self.assertGreater(opened["UTIL-N002"]["massKgS"], 0)
        self.assertLess(abs(base["UTIL-I003"]["massKgS"]), 1e-7)
        self.assertAlmostEqual(opened["UTIL-I003"]["massKgS"], .0005, places=8)


if __name__ == "__main__":
    unittest.main(verbosity=2)
