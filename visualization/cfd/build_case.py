"""Generate a reproducible OpenFOAM-14 3-D iron/slag/gas hearth case.

The coarse extraction patch is flux-coupled to the existing taphole model;
it does NOT geometrically resolve a 60 mm nozzle. Units are SI.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def header(name, cls="dictionary"):
    return f"FoamFile {{format ascii; class {cls}; object {name};}}\n"


def create(case, config, closed=False):
    for folder in ("0", "constant", "system"):
        (case/folder).mkdir(parents=True, exist_ok=True)

    def write(folder, name, body, cls="dictionary"):
        (case/folder/name).write_text(header(name, cls)+body+"\n", encoding="ascii")

    h = config["cell_m"]
    r = config["radius_m"]
    nz = round(config["height_m"]/h)
    nr = round(r/h)
    cells = [(i, j, k) for k in range(nz) for j in range(-nr, nr)
             for i in range(-nr, nr) if ((i+.5)*h)**2+((j+.5)*h)**2 < r*r]
    cell_set = set(cells)
    verts, lookup, blocks = [], {}, []
    boundaries = {p: [] for p in ("walls", "top", "tap")}
    offsets = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0),
               (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)]
    faces = [((-1, 0, 0), (0, 4, 7, 3)), ((1, 0, 0), (1, 2, 6, 5)),
             ((0, -1, 0), (0, 1, 5, 4)), ((0, 1, 0), (3, 7, 6, 2)),
             ((0, 0, -1), (0, 3, 2, 1)), ((0, 0, 1), (4, 5, 6, 7))]
    for i, j, k in cells:
        vi = []
        for di, dj, dk in offsets:
            point = (i+di, j+dj, k+dk)
            if point not in lookup:
                lookup[point] = len(verts)
                verts.append(point)
            vi.append(lookup[point])
        zone = " deadman" if ((i+.5)*h)**2+((j+.5)*h)**2 < 3**2 and k*h >= .5 else ""
        blocks.append("hex ("+" ".join(map(str, vi))+")"+zone+" (1 1 1) simpleGrading (1 1 1)")
        for delta, face in faces:
            neighbor = (i+delta[0], j+delta[1], k+delta[2])
            if neighbor in cell_set:
                continue
            patch = "walls"
            if k == nz-1 and delta == (0, 0, 1):
                patch = "top"
            elif delta == (0, 1, 0) and -.51 < (i+.5)*h < .51 and .5 <= k*h < 1:
                patch = "tap"
            boundaries[patch].append(tuple(vi[n] for n in face))
    body = "vertices\n(\n" + "\n".join(
        "("+" ".join(f"{x*h:g}" for x in p)+")" for p in verts)+"\n);\n"
    body += "blocks\n(\n"+"\n".join(blocks)+"\n);\nedges ();\nboundary\n(\n"
    for name, fs in boundaries.items():
        body += name+" { type "+("wall" if name == "walls" else "patch")+"; faces (\n"
        body += "\n".join("("+" ".join(map(str, f))+")" for f in fs)+"\n); }\n"
    body += ");\nmergePatchPairs ();"
    write("system", "blockMeshDict", body)
    centres = [[(i+.5)*h, (j+.5)*h, (k+.5)*h] for i, j, k in cells]
    (case/"mesh_manifest.json").write_text(json.dumps({"centres": centres, "cell_m": h,
        "cells": len(cells), "tap_area_m2": len(boundaries["tap"])*h*h,
        "scope": "Stair-step cylindrical hearth; coarse flux extraction patch"}))
    q = 0 if closed else config["tap_flow_m3_s"]
    uy = q/(len(boundaries["tap"])*h*h)
    write("0", "U", f"""dimensions [0 1 -1 0 0 0 0];
internalField uniform (0 0 0);
boundaryField {{
 walls {{type noSlip;}}
 top {{type pressureInletOutletVelocity; value uniform (0 0 0);}}
 tap {{type fixedValue; value uniform (0 {uy:.14g} 0);}}
}}""", "volVectorField")
    write("0", "p_rgh", """dimensions [1 -1 -2 0 0 0 0];
internalField uniform 0;
boundaryField {
 walls {type fixedFluxPressure; value uniform 0;}
 tap {type fixedFluxPressure; value uniform 0;}
 top {type prghTotalPressure; p0 uniform 150000; value uniform 150000;}
}""", "volScalarField")
    import math
    fractions = []
    for x, y, z in centres:
        interface = config["iron_height_m"] + config["interface_perturbation_m"] * (
            math.cos(x*.6)*math.sin(y*.4))
        iron = min(1, max(0, (interface-(z-h/2))/h))
        liquid = min(1, max(0, (config["iron_height_m"]+
                                config["slag_height_m"]-(z-h/2))/h))
        fractions.append((iron, liquid-iron, 1-liquid))
    for index, phase in enumerate(("iron", "slag", "gas")):
        vals = "\n".join(f"{v[index]:.14g}" for v in fractions)
        top = 1 if phase == "gas" else 0
        write("0", "alpha."+phase, f"""dimensions [0 0 0 0 0 0 0];
internalField nonuniform List<scalar> {len(cells)} (\n{vals}\n);
boundaryField {{
 walls {{type zeroGradient;}}
 tap {{type zeroGradient;}}
 top {{type inletOutlet; inletValue uniform {top}; value uniform {top};}}
}}""", "volScalarField")
        write("constant", "physicalProperties."+phase,
              f"viscosityModel constant;\nnu {config[phase+'_nu']};\n"
              f"rho {config[phase+'_density']};")
    write("constant", "phaseProperties", """phases (iron slag gas);
sigmas ((iron slag) 1.2 (iron gas) 1.6 (slag gas) 0.5);""")
    write("constant", "g", "dimensions [0 1 -2 0 0 0 0]; value (0 0 -9.81);",
          "uniformDimensionedVectorField")
    write("constant", "momentumTransport", "simulationType laminar;")
    d, f = config["deadman_darcy_m2_inv"], config["deadman_forchheimer_m_inv"]
    write("constant", "fvModels", f"""deadmanResistance {{
 type porosityForce;
 porosityForce {{
  cellZone deadman; type DarcyForchheimer;
  d ({d} {d} {d}); f ({f} {f} {f});
  coordinateSystem {{type cartesian; origin (0 0 0);
   coordinateRotation {{type axesRotation; e1 (1 0 0); e2 (0 1 0);}}
  }}
 }}
}}""")
    write("system", "controlDict", f"""application foamRun;
solver incompressibleMultiphaseVoF;
startFrom startTime; startTime 0; stopAt endTime; endTime {config['duration_s']};
deltaT 0.001; adjustTimeStep yes; maxCo 0.35; maxAlphaCo 0.25; maxDeltaT 0.05;
writeControl adjustableRunTime; writeInterval {config['write_interval_s']};
writeFormat ascii; writePrecision 12; writeCompression off;
timeFormat general; timePrecision 8; purgeWrite 0; runTimeModifiable true;
functions {{
 volumes {{type volFieldValue; libs ("libfieldFunctionObjects.so");
  writeFields false; writeControl timeStep; writeInterval 1; cellZone all; operation volIntegrate;
  fields (alpha.iron alpha.slag alpha.gas);}}
 tapFlux {{type surfaceFieldValue; libs ("libfieldFunctionObjects.so");
  writeFields false; writeControl timeStep; writeInterval 1; patch tap;
  operation sum; fields (phi);}}
}}""")
    write("system", "fvSchemes", """ddtSchemes {default Euler;}
gradSchemes {default Gauss linear;}
divSchemes {
 div(rhoPhi,U) Gauss upwind;
 div(phi,alpha) Gauss vanLeer;
 div(phirb,alpha) Gauss linear;
 div(((rho*nuEff)*dev2(T(grad(U))))) Gauss linear;
}
laplacianSchemes {default Gauss linear corrected;}
interpolationSchemes {default linear;}
snGradSchemes {default corrected;}""")
    write("system", "fvSolution", """solvers {
 "alpha.*" {nSubCycles polynomial (0 2); cAlpha 1;}
 "pcorr.*" {solver PCG; preconditioner DIC; tolerance 1e-9; relTol 0;}
 p_rgh {solver GAMG; tolerance 1e-8; relTol 0.01; smoother GaussSeidel;}
 p_rghFinal {solver GAMG; tolerance 1e-9; relTol 0; smoother GaussSeidel;}
 "U.*" {solver smoothSolver; smoother symGaussSeidel; tolerance 1e-8; relTol 0;}
}
PIMPLE {nOuterCorrectors 2; nCorrectors 2; nNonOrthogonalCorrectors 0;}
relaxationFactors {equations {".*" 1;}}""")
    print(json.dumps({"case": str(case), "cells": len(cells), "tap_m3_s": q}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", default="hearth")
    parser.add_argument("--cell", type=float)
    parser.add_argument("--duration", type=float)
    parser.add_argument("--closed", action="store_true")
    parser.add_argument("--flat", action="store_true")
    args = parser.parse_args()
    cfg = json.loads((ROOT/"config.json").read_text())["hearth"]
    if args.cell:
        cfg["cell_m"] = args.cell
    if args.duration:
        cfg["duration_s"] = args.duration
    if args.flat:
        cfg["interface_perturbation_m"] = 0
    create(ROOT/args.name, cfg, args.closed)
