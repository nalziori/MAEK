"""Cut the blast-furnace-1 gas-cleaning area out of the Unity geometry for the three.js simulation.

Reads MAEKCOL1 (unity/.../Source/maek_geometry.bytes, written by visualization/export_unity_geometry.py)
and writes site/sim/data/bf1.bin (int16 xyz in centimetres, non-indexed triangles, three.js right-handed: z negated,
winding reversed) and bf1.json (per-asset draw ranges + material colours).

    python scripts/export_bf1_scene.py
"""
from __future__ import annotations

import json
import struct
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "unity" / "MAEKInspection" / "Assets" / "MAEK" / "Source"
OUT = ROOT / "site" / "sim" / "data"
CENTER = np.array([-80.0, 12.0, 34.0])  # BF1.DC (dust catcher), Unity coordinates
RADIUS = 40.0
SKIP = ("DECOR.Label",)


def read_assets(path, wanted):
    data = path.read_bytes()
    assert data[:8] == b"MAEKCOL1", "not a MAEKCOL1 file"
    (n,), off = struct.unpack_from("<i", data, 8), 12
    for _ in range(n):
        (ln,) = struct.unpack_from("<i", data, off); off += 4
        aid = data[off:off + ln].decode("utf-8"); off += ln
        nv, ns = struct.unpack_from("<ii", data, off); off += 8
        verts = np.frombuffer(data, "<f4", nv * 6, off).reshape(nv, 6); off += nv * 24
        subs = []
        for _ in range(ns):
            mi, ni = struct.unpack_from("<ii", data, off); off += 8
            subs.append((mi, np.frombuffer(data, "<i4", ni, off))); off += ni * 4
        if aid in wanted:
            yield aid, verts[:, :3], subs
    assert off == len(data), "trailing bytes: format mismatch"


def main():
    manifest = json.loads((SRC / "maek_manifest.json").read_text(encoding="utf-8"))
    pos = {a["id"]: np.array(a["position"]) for a in manifest["assets"]}
    wanted = {aid for aid, p in pos.items()
              if not aid.startswith(SKIP) and aid.startswith(("BF1", "DECOR."))
              and np.linalg.norm((p - CENTER)[[0, 2]]) < RADIUS}
    chunks, meshes, count = [], [], 0
    for aid, xyz, subs in read_assets(SRC / "maek_geometry.bytes", wanted):
        world = xyz + pos[aid] - CENTER          # recentre on the dust catcher
        world[:, 2] *= -1                        # Unity left-handed -> three.js right-handed
        for mi, idx in subs:
            tri = world[idx].reshape(-1, 3, 3)[:, ::-1].reshape(-1, 3)  # reverse winding after mirror
            cm = np.round(tri * 100)
            assert np.abs(cm).max() < 32767, aid  # int16 centimetres cover +-327 m
            chunks.append(cm.astype("<i2"))
            meshes.append({"id": aid, "material": int(mi), "start": count, "count": len(tri)})
            count += len(tri)
    OUT.mkdir(parents=True, exist_ok=True)
    np.concatenate(chunks).tofile(OUT / "bf1.bin")
    mats = [{"name": m["name"], "color": m["color"][:3], "metallic": m["metallic"]} for m in manifest["materials"]]
    (OUT / "bf1.json").write_text(json.dumps({"origin_unity": CENTER.tolist(), "vertices": count, "units": "cm",
                                              "materials": mats, "meshes": meshes}), encoding="utf-8")
    print(f"{len({m['id'] for m in meshes})} assets, {count} vertices, {(OUT / 'bf1.bin').stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
