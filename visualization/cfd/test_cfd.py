"""Numerical checks for the spatial reactive transport and case generator."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from build_case import create
from reactive_shaft import Shaft

ROOT = Path(__file__).resolve().parent


class TransportChecks(unittest.TestCase):
    def setUp(self):
        self.c = json.loads((ROOT/"config.json").read_text())["shaft"]

    def test_pressure_flux_balance(self):
        model = Shaft(self.c)
        self.assertLess(model.pressure_residual, 1e-9)
        self.assertAlmostEqual(model.qtop.sum(), model.qin.sum(), places=9)
        self.assertGreater(np.max(np.abs(model.velocity[:, :2])), .01)

    def test_full_transport_atoms_and_heat(self):
        model = Shaft(self.c)
        model.advance(12)
        report = model.report()
        self.assertLess(max(abs(v) for v in report["atom_residual_kmol"]), 1e-8)
        self.assertLess(abs(report["energy_residual_j"])/model.initial_energy, 1e-12)
        self.assertGreater(report["produced_iron_kg"], 0)
        self.assertGreaterEqual(report["minimum_species_kmol"], 0)
        expected = model.pore*self.c["gas_total_kmol_m3"]
        np.testing.assert_allclose(model.moles[:, :3].sum(axis=1), expected, rtol=1e-11)

    def test_inert_constant_scalar_is_preserved(self):
        self.c["reaction_rate_s_inv"] = 0
        self.c["inlet_co_fraction"] = .2
        model = Shaft(self.c)
        model.moles[:, :3] = model.pore*self.c["gas_total_kmol_m3"]*np.array([.2, 0, .8])
        before = model.moles.copy()
        model.advance(8)
        np.testing.assert_allclose(model.moles, before, atol=1e-12)

    def test_no_co_no_reduction(self):
        self.c["inlet_co_fraction"] = 0
        model = Shaft(self.c)
        model.moles[:, 0] = 0
        model.advance(2)
        self.assertEqual(model.produced_kmol, 0)

    def test_time_refinement(self):
        first = Shaft(self.c)
        first.advance(10)
        self.c["dt_s"] *= .5
        second = Shaft(self.c)
        second.advance(10)
        self.assertLess(abs(first.produced_kmol-second.produced_kmol)/second.produced_kmol, .02)

    def test_reject_invalid_step(self):
        model = Shaft(self.c)
        with self.assertRaises(ValueError):
            model.step(-1)
        with self.assertRaises(ValueError):
            model.step(10*model.max_dt)

    def test_case_has_real_3d_topology_and_distinct_phases(self):
        cfg = json.loads((ROOT/"config.json").read_text())["hearth"]
        with tempfile.TemporaryDirectory(prefix="maek-cfd-test-") as folder:
            target = Path(folder)
            create(target, cfg)
            mesh = json.loads((target/"mesh_manifest.json").read_text())
            xyz = np.array(mesh["centres"])
            self.assertTrue(all(len(np.unique(xyz[:, d])) > 2 for d in range(3)))
            self.assertEqual(mesh["cells"], 2528)
            for phase in ("iron", "slag", "gas"):
                self.assertTrue((target/"0"/("alpha."+phase)).exists())
            self.assertNotIn("empty", (target/"system/blockMeshDict").read_text())


if __name__ == "__main__":
    unittest.main(verbosity=2)
