"""Steady mass/pressure network with a Schur response of the existing 3-D Darcy grid.

SciPy solves signed mass flow and absolute node pressure simultaneously. This is
not a water-hammer, choked-flow, reacting pipe or temperature transport solver.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import root, least_squares

G = 9.80665
RU = 8314.462618


def friction(reynolds, relative_roughness):
    """64/Re laminar; Haaland turbulent; continuous transitional interpolation."""
    re = np.maximum(np.asarray(reynolds), 1e-15)
    laminar = 64 / re
    turbulent = (-1.8 * np.log10((relative_roughness / 3.7)**1.11 + 6.9/re))**-2
    weight = np.clip((re-2300)/1700, 0, 1)
    return (1-weight)*laminar + weight*turbulent


@dataclass
class Edge:
    id: str
    a: str
    b: str
    diameter: float
    length: float
    k: float
    fluid: tuple  # molecular mass, temperature, dynamic viscosity, liquid density
    dz: float = 0
    rise: float = 0
    ratio: float = 1
    closed: bool = False
    service: str = ""
    furnace: str = ""
    sector: int = -1


class Network:
    def __init__(self, elevations, edges, fixed, demands=None, roughness=4.5e-5,
                 shaft_response=None, shaft_temperature=1900, trapped_pressure=201325,
                 mass_tolerance=1e-6, pressure_tolerance=.05):
        if any(p <= 0 for p in fixed.values()) or trapped_pressure <= 0:
            raise ValueError("Absolute boundary/reference pressures must be positive")
        if any(e.diameter <= 0 or e.length < 0 or e.k < 0 or
               e.fluid[1] <= 0 or e.fluid[2] <= 0 for e in edges):
            raise ValueError("Invalid hydraulic dimensions or fluid properties")
        self.elevations = elevations
        self.edges = edges
        self.fixed = dict(fixed)
        self.demands = demands or {}
        self.roughness = roughness
        self.shaft_response = shaft_response
        self.shaft_temperature = shaft_temperature
        self.trapped_pressure = trapped_pressure
        self.mass_tolerance = mass_tolerance
        self.pressure_tolerance = pressure_tolerance
        self.pressure = {}
        self.mass = {e.id: 0.0 for e in edges}
        self.reports = []
        self.assumed_anchors = []

    def solve(self):
        active = [e for e in self.edges if not e.closed]
        adjacency = {n: set() for n in self.elevations}
        for e in active:
            adjacency[e.a].add(e.b)
            adjacency[e.b].add(e.a)
        pending = set(adjacency)
        while pending:
            first = min(pending)
            component, stack = set(), [first]
            while stack:
                n = stack.pop()
                if n not in component:
                    component.add(n)
                    stack.extend(adjacency[n]-component)
            pending -= component
            selected = [e for e in active if e.a in component]
            anchors = {n: p for n, p in self.fixed.items() if n in component}
            if not anchors:
                if any(abs(self.demands.get(n, 0)) > 0 for n in component):
                    raise ValueError("Demand in unanchored closed component")
                anchors[first] = self.trapped_pressure
                self.assumed_anchors.append(first)
            self._solve_component(sorted(component), selected, anchors)
        return self

    def _solve_component(self, names, edges, anchors):
        index = {n: k for k, n in enumerate(names)}
        free = [n for n in names if n not in anchors]
        nf, ne = len(free), len(edges)
        fi = np.array([index[n] for n in free], dtype=int)
        pa = np.array([index[e.a] for e in edges], dtype=int)
        pb = np.array([index[e.b] for e in edges], dtype=int)
        pressure = np.full(len(names), np.mean(list(anchors.values())))
        for n, p in anchors.items():
            pressure[index[n]] = p
        if not edges:
            self.pressure.update(zip(names, pressure))
            return
        d = np.array([e.diameter for e in edges])
        area = np.pi*d*d/4
        length = np.array([e.length for e in edges])
        minor = np.array([e.k for e in edges])
        molecular, temp, mu, liquid = np.array([e.fluid for e in edges]).T
        dz = np.array([e.dz for e in edges])
        rise = np.array([e.rise for e in edges])
        ratio = np.array([e.ratio for e in edges])
        demand = np.array([self.demands.get(n, 0) for n in names], dtype=float)
        groups = {}
        for k, e in enumerate(edges):
            if e.furnace:
                groups.setdefault(e.furnace, []).append(k)
        pscale = 10000.0
        mscale = 10.0 if np.any(liquid) else 1.0

        def equations(x):
            p = pressure.copy()
            p[fi] = x[:nf]*pscale
            mass = x[nf:]*mscale
            rho = np.where(liquid > 0, liquid,
                           np.maximum((p[pa]+p[pb])*.5, 1)*molecular/(RU*temp))
            re = np.abs(mass)*d/(mu*area)
            # Laminar limit remains linear at zero; avoid 0 * infinite friction.
            loss = (friction(np.maximum(re, 1e-8), self.roughness/d)*length/d+minor)
            loss = loss*mass*np.abs(mass)/(2*rho*area*area)
            near = re < 1e-6
            loss[near] = 128*mu[near]*length[near]*mass[near]/(
                np.pi*rho[near]*d[near]**4)
            momentum = p[pa]-p[pb]+rise-rho*G*dz-loss
            for ids_list in groups.values():
                ids = np.asarray(ids_list)
                sectors = np.array([edges[k].sector for k in ids])
                top_p = p[pb[ids[0]]]
                gas_rho = max(top_p, 1)*28.01/(RU*self.shaft_temperature)
                gas_q = ratio[ids]*mass[ids]/gas_rho
                q8 = np.bincount(sectors, weights=gas_q, minlength=8)
                dp8 = self.shaft_response @ q8
                # Vertical hydrostatic contribution, plus the resolved Darcy response.
                momentum[ids] -= dp8[sectors] + (gas_rho-rho[ids])*G*dz[ids]
            balance = demand.copy()
            np.add.at(balance, pa, mass)
            np.add.at(balance, pb, -ratio*mass)
            return np.r_[balance[fi]/mscale, momentum/pscale]

        guess = np.r_[pressure[fi]/pscale, np.ones(ne)*.1]
        solved = root(equations, guess, method="hybr", options={"xtol": 1e-9,
                                                              "maxfev": 20000})
        if np.max(np.abs(equations(solved.x))) > 1e-7:
            solved = least_squares(equations, solved.x, xtol=1e-12, ftol=1e-12,
                                   gtol=1e-12, max_nfev=600, x_scale="jac")
        residual = equations(solved.x)
        if not np.isfinite(solved.x).all() or not np.isfinite(residual).all():
            raise RuntimeError("Non-finite hydraulic solution")
        mass_error = float(np.max(np.abs(residual[:nf]), initial=0)*mscale)
        pressure_error = float(np.max(np.abs(residual[nf:]), initial=0)*pscale)
        pressure[fi] = solved.x[:nf]*pscale
        if (mass_error > self.mass_tolerance or pressure_error > self.pressure_tolerance
                or np.min(pressure) <= 0):
            raise RuntimeError((names[0], "nonphysical or unconverged", mass_error,
                                pressure_error, float(np.min(pressure))))
        self.pressure.update(zip(names, map(float, pressure)))
        self.mass.update({e.id: float(m) for e, m in zip(edges, solved.x[nf:]*mscale)})
        self.reports.append(dict(first_node=names[0], nodes=len(names), edges=ne,
                                 mass_residual_kg_s=mass_error,
                                 momentum_residual_pa=pressure_error))

    def values(self, edge):
        p1, p2 = self.pressure[edge.a], self.pressure[edge.b]
        molecular, temperature, viscosity, liquid = edge.fluid
        rho1 = liquid or p1*molecular/(RU*temperature)
        rho2 = liquid or p2*molecular/(RU*temperature)
        mass = self.mass[edge.id]
        area = np.pi*edge.diameter**2/4
        # Signed values use the source geometry's a -> b direction.
        rho = rho1 if mass >= 0 else rho2
        velocity = mass/rho/area
        sound = (1.4*RU*temperature/max(molecular, 1))**.5
        return dict(id=edge.id, pressureFromPa=p1, pressureToPa=p2, massKgS=mass,
                    volumeM3S=mass/rho, velocityMS=velocity,
                    volumeFromM3S=mass/rho1, volumeToM3S=mass/rho2,
                    reynolds=abs(mass)*edge.diameter/(viscosity*area),
                    mach=max(abs(mass/rho1/area), abs(mass/rho2/area))/sound if not liquid else 0,
                    insideDiameterM=edge.diameter, temperatureK=temperature,
                    state="closed" if edge.closed else
                    "stagnant" if abs(mass) < 1e-7 else "flowing")
