"""Conservative 3-D porous Darcy / CO reduction / effective-energy demonstration.

Frozen total gas molar concentration; fixed porous solid. Not compressible CFD-DEM.
CO-rich tuyere input represents an upstream raceway, NOT resolved coke combustion.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.linalg import spsolve

ROOT = Path(__file__).resolve().parent


class Shaft:
    def __init__(self, config):
        self.c = config
        h = config["cell_m"]
        r = config["radius_m"]
        height = config["height_m"]
        indices = []
        for k in range(round(height / h)):
            for j in range(-round(r / h), round(r / h)):
                for i in range(-round(r / h), round(r / h)):
                    x, y, z = (i + .5) * h, (j + .5) * h, (k + .5) * h
                    radius = r * (1 - .28 * z / height)
                    if x*x + y*y < radius*radius:
                        indices.append((i, j, k))
        self.ijk = np.array(indices)
        self.xyz = (self.ijk + .5) * h
        self.n = len(indices)
        lookup = {v: i for i, v in enumerate(indices)}
        pairs = []
        for i, v in enumerate(indices):
            for axis in range(3):
                w = list(v)
                w[axis] += 1
                if tuple(w) in lookup:
                    pairs.append((i, lookup[tuple(w)], axis))
        self.pairs = np.array(pairs)
        a, b, axis = self.pairs.T
        self.a, self.b = a, b
        self.top = np.where(self.ijk[:, 2] == self.ijk[:, 2].max())[0]
        bottom = np.where(self.ijk[:, 2] == 0)[0]
        # Eight tuyere sectors; uneven feed exposes genuinely three-dimensional response.
        chosen = []
        for theta in np.arange(8) * np.pi / 4:
            target = np.array([.8*r*np.cos(theta), .8*r*np.sin(theta), h*.5])
            chosen.append(bottom[np.argmin(np.linalg.norm(self.xyz[bottom]-target, axis=1))])
        self.inlet = np.array(chosen)
        weights = 1 + .25 * np.cos(np.arange(8)*np.pi/4)
        self.qin = config["gas_feed_m3_s"] * weights / weights.sum()
        if "inlet_flows_m3_s" in config:
            self.qin = np.asarray(config["inlet_flows_m3_s"], dtype=float)
            if self.qin.shape != (8,) or np.any(self.qin < 0):
                raise ValueError("Eight non-negative inlet volume flows required")
        conductance = config["permeability_m2"] / config["gas_viscosity_pa_s"] * h
        # A layered resistance field and a radially varying solid packing fraction.
        z = self.xyz[:, 2]
        self.mobility = 1 / (1 + .8 * (np.sin(z*np.pi/3)**2))
        g = conductance * 2*self.mobility[a]*self.mobility[b]/(
            self.mobility[a]+self.mobility[b])
        gt = 2*conductance*self.mobility[self.top]
        rows = np.r_[a, b, a, b, self.top]
        cols = np.r_[a, b, b, a, self.top]
        vals = np.r_[g, g, -g, -g, gt]
        matrix = coo_matrix((vals, (rows, cols)), shape=(self.n, self.n)).tocsr()
        rhs = np.zeros(self.n)
        np.add.at(rhs, self.inlet, self.qin)
        self.pressure = spsolve(matrix, rhs)
        self.q = g*(self.pressure[a]-self.pressure[b])
        self.qtop = gt*self.pressure[self.top]
        self.pressure_residual = float(np.max(np.abs(matrix@self.pressure-rhs)))
        self.velocity = np.zeros((self.n, 3))
        count = np.zeros((self.n, 3))
        for ids in (a, b):
            np.add.at(self.velocity, (ids, axis), self.q / h**2)
            np.add.at(count, (ids, axis), 1)
        self.velocity /= np.maximum(count, 1)
        self.vol = h**3
        self.pore = self.vol*config["void_fraction"]
        total = self.pore*config["gas_total_kmol_m3"]
        # CO, CO2, N2, Fe2O3, Fe; extensive kmol per cell.
        self.moles = np.zeros((self.n, 5))
        self.moles[:, :3] = total*np.array([.2, .05, .75])
        self.moles[:, 3] = config["ore_kmol_m3"]*self.vol
        self.temperature = config["initial_bottom_k"] + (
            config["initial_top_k"]-config["initial_bottom_k"])*z/height
        self.capacity = config["bulk_heat_capacity_j_m3_k"]*self.vol
        self.energy = self.temperature*self.capacity
        self.initial_atoms = self.atoms()
        self.boundary_atoms = np.zeros(4)
        self.initial_energy = float(self.energy.sum())
        self.boundary_energy = 0.0
        self.reaction_energy = 0.0
        self.time = 0.0
        self.produced_kmol = 0.0
        self.last_rate = 0.0
        self.donor = np.where(self.q >= 0, a, b)
        self.receiver = np.where(self.q >= 0, b, a)
        outward = np.zeros(self.n)
        np.add.at(outward, self.donor, np.abs(self.q))
        np.add.at(outward, self.top, self.qtop)
        self.max_dt = float(.7*self.pore / max(outward.max(), 1e-12))

    @staticmethod
    def atom_map():
        # Fe, C, O, N atoms per molecule.
        return np.array([[0, 1, 1, 0], [0, 1, 2, 0], [0, 0, 0, 2],
                         [2, 0, 3, 0], [1, 0, 0, 0]], dtype=float)

    def atoms(self):
        return self.moles.sum(axis=0) @ self.atom_map()

    def step(self, dt):
        if dt <= 0 or dt > self.max_dt * (1+1e-12):
            raise ValueError("Step must be positive and obey the donor-volume CFL bound")
        c = self.c
        amount = np.abs(self.q)*dt
        transfer = self.moles[self.donor, :3]/self.pore * amount[:, None]
        delta = np.zeros_like(self.moles)
        for species in range(3):
            np.add.at(delta[:, species], self.donor, -transfer[:, species])
            np.add.at(delta[:, species], self.receiver, transfer[:, species])
        inlet = self.qin[:, None]*dt*c["gas_total_kmol_m3"] * np.array([
            c["inlet_co_fraction"], 0, 1-c["inlet_co_fraction"]])
        outlet = self.moles[self.top, :3]/self.pore * (self.qtop*dt)[:, None]
        for species in range(3):
            np.add.at(delta[:, species], self.inlet, inlet[:, species])
            np.add.at(delta[:, species], self.top, -outlet[:, species])
        self.boundary_atoms += (inlet.sum(axis=0)-outlet.sum(axis=0)) @ self.atom_map()[:3]
        cpvol = c["gas_heat_capacity_j_kmol_k"]*c["gas_total_kmol_m3"]
        heat = cpvol*self.temperature[self.donor]*amount
        de = np.zeros(self.n)
        np.add.at(de, self.donor, -heat)
        np.add.at(de, self.receiver, heat)
        ein = self.qin*dt*cpvol*c["inlet_temperature_k"]
        eout = self.qtop*dt*cpvol*self.temperature[self.top]
        np.add.at(de, self.inlet, ein)
        np.add.at(de, self.top, -eout)
        conduction = c["effective_conductivity_w_m_k"]*c["cell_m"]*dt * (
            self.temperature[self.b]-self.temperature[self.a])
        np.add.at(de, self.a, conduction)
        np.add.at(de, self.b, -conduction)
        self.boundary_energy += float(ein.sum()-eout.sum())
        self.moles += delta
        rate = c["reaction_rate_s_inv"]*np.exp(-c["activation_k"]*(
            1/self.temperature-1/1500))
        # Phenomenological net CO reduction; exact stoichiometry and reactant cap.
        extent = np.minimum(self.moles[:, 3], self.moles[:, 0]/3) * (1-np.exp(-rate*dt))
        self.moles[:, 0] -= 3*extent
        self.moles[:, 1] += 3*extent
        self.moles[:, 3] -= extent
        self.moles[:, 4] += 2*extent
        self.produced_kmol += float(2*extent.sum())
        self.last_rate = float(2*extent.sum()*55.845/dt)
        reaction_heat = extent*c["reaction_heat_j_kmol"]
        self.energy += de+reaction_heat
        self.reaction_energy += float(reaction_heat.sum())
        self.temperature = self.energy/self.capacity
        self.time += dt

    def advance(self, duration):
        target = self.time+duration
        while self.time < target-1e-10:
            self.step(min(self.c["dt_s"], self.max_dt, target-self.time))

    def report(self):
        return {
            "time_s": self.time, "cells": self.n,
            "pressure_residual_m3_s": self.pressure_residual,
            "atom_residual_kmol": (self.atoms()-self.initial_atoms-self.boundary_atoms).tolist(),
            "energy_residual_j": float(self.energy.sum()-self.initial_energy-
                                       self.boundary_energy-self.reaction_energy),
            "produced_iron_kg": self.produced_kmol*55.845,
            "iron_generation_kg_s": self.last_rate,
            "temperature_range_k": [float(self.temperature.min()), float(self.temperature.max())],
            "co_fraction_range": [float(self.moles[:, 0].min()/self.pore/
                                        self.c["gas_total_kmol_m3"]),
                                  float(self.moles[:, 0].max()/self.pore/
                                        self.c["gas_total_kmol_m3"])],
            "minimum_species_kmol": float(self.moles.min()),
        }


def run():
    c = json.loads((ROOT/"config.json").read_text())["shaft"]
    model = Shaft(c)
    frames = []
    for time in np.arange(0, c["duration_s"]+.001, 5):
        model.advance(time-model.time)
        frames.append({"time": float(time), "temperature": model.temperature.tolist(),
                       "co": (model.moles[:, 0]/model.pore/
                              c["gas_total_kmol_m3"]).tolist(),
                       "reduction": (model.moles[:, 4]/(2*c["ore_kmol_m3"]*
                                     model.vol)).tolist()})
    result = {"positions": model.xyz.tolist(), "velocity": model.velocity.tolist(),
              "pressure": model.pressure.tolist(), "cell_m": c["cell_m"],
              "frames": frames, "report": model.report(),
              "scope": "3D Darcy CO-reduction and effective thermal transport; fixed solid; "
                       "frozen gas molarity; no resolved raceway or DEM; no hearth feedback"}
    (ROOT/"shaft_result.json").write_text(json.dumps(result), encoding="utf-8")
    print(json.dumps(model.report(), indent=2))


if __name__ == "__main__":
    run()
