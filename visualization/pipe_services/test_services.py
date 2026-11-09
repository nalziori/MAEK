"""Validate service semantics and new utility ports without Blender or Unity."""
import json
import math
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent


class ServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads((ROOT / "pipe_services.json").read_text(encoding="utf-8"))
        cls.net = json.loads((ROOT / "services_network.json").read_text(encoding="utf-8"))
        cls.old = json.loads((ROOT.parent / "drone_verified_network.json").read_text())
        cls.pipes = {p["id"]: p for p in cls.data["pipes"]}

    def test_all_original_geometry_and_states_preserved(self):
        new = {p["id"]: p for p in self.net["lines"]}
        self.assertEqual(len(self.old["lines"]), 240)
        for old in self.old["lines"]:
            for key, value in old.items():
                self.assertEqual(new[old["id"]][key], value, (old["id"], key))

    def test_categories_and_ports_have_consistent_media(self):
        definitions = {s["code"]: s for s in self.data["services"]}
        self.assertEqual(len(self.pipes), 247)
        self.assertEqual(len(self.data["pipes"]), 247)
        self.assertEqual(len(definitions), 14)
        self.assertEqual(set(definitions), {p["serviceCode"] for p in self.pipes.values()})
        for p in self.pipes.values():
            self.assertEqual(definitions[p["serviceCode"]]["medium"], p["medium"])
            for key in ("fromNode", "toNode"):
                self.assertEqual(self.net["nodes"][p[key]]["medium"], p["medium"])
            self.assertFalse(p["directionResolved"])

    def test_process_stages_are_distinguished(self):
        expected = {"G001": "BFG_RAW", "G004": "BFG_DEDUST", "G005": "BFG_CLEAN",
                    "W001": "CW_SUPPLY", "W003": "CW_RETURN"}
        for unit in ("BF1", "BF2"):
            for suffix, code in expected.items():
                self.assertEqual(self.pipes[unit + "-" + suffix]["serviceCode"], code)
        cold = [p for p in self.pipes.values() if p["serviceCode"] == "COLD_BLAST"]
        hot = [p for p in self.pipes.values() if p["serviceCode"] == "HOT_BLAST"]
        self.assertEqual(len(cold), 12)
        self.assertEqual(len(hot), 60)
        self.assertTrue(all(p["id"].split("-")[-1].startswith("C") for p in cold))
        self.assertTrue(all(not p["id"].split("-")[-1].startswith("C") for p in hot))

    def reachable(self, start, valve_open=False):
        graph = {}
        edges = [(l["from"], l["to"]) for l in self.net["lines"]
                 if l["id"].startswith("UTIL-")]
        edges += [(e["from"], e["to"]) for e in self.net["internal_connections"]
                  if e["from"].startswith("UTIL.") and
                  (e["active"] or valve_open and e["from"] == "UTIL.N2.VALVE.IN")]
        for a, b in edges:
            graph.setdefault(a, set()).add(b)
            graph.setdefault(b, set()).add(a)
        seen, pending = set(), [start]
        while pending:
            node = pending.pop()
            if node not in seen:
                seen.add(node)
                pending.extend(graph.get(node, ()) - seen)
        return seen

    def test_closed_valve_blocks_nitrogen_and_opening_only_joins_nitrogen(self):
        start = "UTIL.N2.SOURCE.OUT"
        self.assertNotIn("UTIL.N2.CHAMBER.IN", self.reachable(start))
        connected = self.reachable(start, valve_open=True)
        self.assertIn("UTIL.N2.RECOVERY.IN", connected)
        self.assertTrue(all(self.net["nodes"][n]["medium"] == "N2" for n in connected))
        self.assertEqual(self.pipes["UTIL-N002"]["state"], "closed")

    def test_actuator_air_is_separate_from_nitrogen(self):
        air = self.reachable("UTIL.IA.SOURCE.OUT", valve_open=True)
        self.assertIn("UTIL.N2.ACT.AIR", air)
        self.assertTrue(all(self.net["nodes"][n]["medium"] == "INSTR_AIR" for n in air))
        self.assertEqual(self.net["control_relationships"][0]["to"], "UTIL.N2.VALVE")
        self.assertFalse(any(e["from"] == "UTIL.N2.ACT.AIR" or
                             e["to"] == "UTIL.N2.ACT.AIR"
                             for e in self.net["internal_connections"]))

    def test_new_endpoints_touch_actual_equipment_surfaces(self):
        shapes = {a["id"]: a for a in self.data["utilityAssets"]}
        for p in self.pipes.values():
            if not p["newGeometry"]:
                continue
            for key, point in (("fromNode", p["points"][0]),
                               ("toNode", p["points"][-1])):
                node = self.net["nodes"][p[key]]
                self.assertEqual(point["position"], node["position"])
                asset = shapes[node["device"]]
                v = [x-c for x, c in zip(node["position"], asset["position"])]
                half = [s/2 for s in asset["size"]]
                if asset["shape"] == "box":
                    self.assertTrue(all(abs(x) <= h+1e-8 for x, h in zip(v, half)))
                    self.assertTrue(any(abs(abs(x)-h) < 1e-8 for x, h in zip(v, half)))
                else:
                    radial = math.hypot(v[0], v[1])
                    self.assertLessEqual(radial, half[0]+1e-8)
                    self.assertLessEqual(abs(v[2]), half[2]+1e-8)
                    self.assertTrue(abs(radial-half[0]) < 1e-8 or
                                    abs(abs(v[2])-half[2]) < 1e-8)


if __name__ == "__main__":
    unittest.main(verbosity=2)
