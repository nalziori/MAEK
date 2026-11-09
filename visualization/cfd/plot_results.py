"""Export scientific diagnostic plots from the saved numerical fields."""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from export_results import load

ROOT = Path(__file__).resolve().parent
shaft = json.loads((ROOT/"shaft_result.json").read_text())
report = json.loads((ROOT/"verification.json").read_text())
xyz = np.array(shaft["positions"])
sel = abs(xyz[:, 1]-.5) < .01
frame = shaft["frames"][-1]
fig, axes = plt.subplots(2, 3, figsize=(15, 9), constrained_layout=True)
for ax, name, values, cmap, limits in [
    (axes[0, 0], "Shaft temperature [K]", frame["temperature"], "inferno", (750, 1900)),
    (axes[0, 1], "Shaft CO molar fraction", frame["co"], "viridis", (0, .4)),
    (axes[0, 2], "Darcy gauge pressure [Pa]", shaft["pressure"], "magma", (0, None)),
]:
    im = ax.scatter(xyz[sel, 0], xyz[sel, 2], c=np.array(values)[sel], marker="s", s=45,
                    cmap=cmap, vmin=limits[0], vmax=limits[1])
    fig.colorbar(im, ax=ax, shrink=.8)
    ax.set(title=name+"\ny=0.5 m; 120 s", xlabel="x [m]", ylabel="height [m]")
    ax.set_aspect("equal")
meta, points, data = load(ROOT/"hearth_fine")
time, alpha, vel, pressure = data[-1]
cut = abs(points[:, 1]-.125) < .01
ax = axes[1, 0]
im = ax.scatter(points[cut, 0], points[cut, 2], c=alpha[cut, 0], marker="s", s=22,
                cmap="hot", vmin=0, vmax=1)
fig.colorbar(im, ax=ax, shrink=.8)
sample = np.where(cut)[0][::3]
q = ax.quiver(points[sample, 0], points[sample, 2], vel[sample, 0], vel[sample, 2],
              angles="xy", scale_units="xy", scale=.5, color="cyan", width=.004)
ax.quiverkey(q, .75, 1.06, .1, "0.1 m/s", labelpos="E")
ax.set(title="Hearth iron fraction and velocity\ny=0.125 m; 12 s", xlabel="x [m]",
       ylabel="height [m]")
ax.set_aspect("equal")
ax = axes[1, 1]
ax.plot(report["time"], report["declared_tap_m3"], label="imposed extraction", lw=2)
ax.plot(report["time"], report["iron_out_m3"], "o", label="VOF iron removed", ms=4)
ax.set(title="Hearth volume balance", xlabel="time [s]", ylabel="extracted volume [m3]")
ax.legend()
ax.grid(alpha=.25)
ax = axes[1, 2]
sensitivity = report["mesh_sensitivity"]
ax.bar(["Fine liquid\nvelocity RMS", "Coarse/fine\nRMS difference"],
       [sensitivity["fine_liquid_velocity_rms_m_s"],
        sensitivity["liquid_velocity_rms_difference_m_s"]], color=["#177a8a", "#b24b31"])
ax.set(title="Mesh sensitivity: NOT grid independent", ylabel="velocity [m/s]")
fig.suptitle("MAEK | 3D VOF hearth + independent reactive porous shaft\n"
             "Numerical prototype; isothermal hearth; no full-furnace coupling or plant validation",
             fontsize=14)
fig.savefig(ROOT/"cfd_verification.png", dpi=160, bbox_inches="tight")
plt.close(fig)
print(ROOT/"cfd_verification.png")
