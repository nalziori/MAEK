"""Procedural 2D renderer for camera jobs: pipe band + rust / stain patches + imaging effects.

`render_job` is deterministic for a given (job, rng state). Mask classes:
0 background/pipe, 1 corrosion, 2 cui_sign, 3 leak_stain (see maek.camera.CLASSES).
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from maek.camera import CLASSES

PIPE_RGB = {"carbon_steel": (100, 108, 112), "stainless": (175, 178, 182), "pvc": (205, 203, 196)}
CLAD_RGB = (188, 192, 198)
BG_RGB = (70, 72, 74)


def _interp_matrix(n, cell):
    """(n, g) smoothstep interpolation weights from a coarse grid of spacing `cell`."""
    g = int(n / cell) + 2
    pos = np.arange(n, dtype=np.float32) / cell
    i0 = pos.astype(int)
    f = pos - i0
    f = f * f * (3 - 2 * f)
    m = np.zeros((n, g), np.float32)
    r = np.arange(n)
    m[r, i0] = 1 - f
    m[r, i0 + 1] = f
    return m


def _noise(rng, h, w, cell, octaves=3):
    """Fractal value noise in [0, 1], shape (h, w) (separable interpolation via matmul)."""
    out = np.zeros((h, w), np.float32)
    amp, tot = 1.0, 0.0
    for o in range(octaves):
        c = max(cell / 2 ** o, 2.0)
        wy, wx = _interp_matrix(h, c), _interp_matrix(w, c)
        grid = rng.random((wy.shape[1], wx.shape[1]), dtype=np.float32)
        out += amp * (wy @ grid @ wx.T)
        tot += amp
        amp *= 0.5
    return out / tot


def _blur(img, sigma):
    if sigma < 0.3:
        return img
    r = math.ceil(3 * sigma)
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    k = (k / k.sum()).astype(np.float32)
    for axis in (0, 1):
        pad = [(0, 0)] * img.ndim
        pad[axis] = (r, r)
        p = np.pad(img, pad, mode="edge")
        n = img.shape[axis]
        out = np.zeros_like(img)
        for i, wgt in enumerate(k):
            out += wgt * (p[i:i + n] if axis == 0 else p[:, i:i + n])
        img = out
    return img


def _frame(job):
    S = job["image_size"]
    t = math.radians(job["pipe"]["tilt_deg"])
    return S, math.cos(t), math.sin(t), job["pipe"]["width_frac"] * S / 2


def _pipe_layers(job, rng):
    """Return (rgb float HxWx3 in 0-1, pipe_mask bool, u along-pipe px, v across px)."""
    S, ct, st, hw = _frame(job)
    yy, xx = np.mgrid[0:S, 0:S].astype(np.float32)
    dx, dy = xx - S / 2, yy - S / 2
    u = dx * ct + dy * st          # along pipe (px from centre)
    v = -dx * st + dy * ct         # across pipe
    inside = np.abs(v) < hw
    n = np.clip(v / hw, -1, 1)
    nz = np.sqrt(1 - n * n)
    shade = np.clip(0.35 * n * -1 + 0.9 * nz, 0, 1) * 0.75 + 0.25
    pipe = job["pipe"]
    base = np.array(CLAD_RGB if pipe["insulated"] else
                    PIPE_RGB.get(pipe["material"], PIPE_RGB["carbon_steel"]), np.float32) / 255
    tex = _noise(rng, S, S, 40, 3)
    streak = _noise(rng, S, S, 6, 2)
    surf = base[None, None, :] * (0.88 + 0.24 * tex[..., None])
    surf = surf * (0.96 + 0.08 * streak[..., None])
    if pipe["insulated"]:
        px_per_mm = hw * 2 / pipe["od_mm"]
        period = max(rng.uniform(250, 450) * px_per_mm, 24.0)
        ph = rng.uniform(0, period)
        seam = np.abs(((u + ph) % period) - period / 2) > period / 2 - 1.5
        surf = surf * np.where(seam, 0.7, 1.0)[..., None]
        rib = np.abs(((v + hw) % (hw * 0.5)) - hw * 0.25) > hw * 0.25 - 1.0
        surf = surf * np.where(rib, 0.9, 1.0)[..., None]
    bg_grad = 0.8 + 0.4 * (yy / S)
    bg = np.array(BG_RGB, np.float32)[None, None, :] / 255 * bg_grad[..., None]
    bg = bg * (0.8 + 0.4 * _noise(rng, S, S, 30, 3)[..., None])
    rgb = np.where(inside[..., None], surf * shade[..., None], bg)
    return rgb.astype(np.float32), inside, u, v


def defect_center(job, d):
    """Pixel centre (cx, cy) of a job defect; the single source of the renderer geometry."""
    S, ct, st, hw = _frame(job)
    cx = S / 2 + (d["u"] - 0.5) * S * ct - d["v"] * hw * st
    cy = S / 2 + (d["u"] - 0.5) * S * st + d["v"] * hw * ct
    return cx, cy


def _patch(job, d, rng):
    """Blob field for one defect: returns (y0, y1, x0, x1, field, color_field)."""
    S, ct, st, _hw = _frame(job)
    cx, cy = defect_center(job, d)
    a, b = d["w"] * S / 2, d["h"] * S / 2
    cls = d["class_id"]
    if cls == 3:                       # leak stain: drips mostly across/down the pipe
        a, b = a * 0.8, b * 1.5
    elif cls == 2:                     # cladding stain/dent streak
        a, b = a * 1.1, b * 1.2
    R = int(1.7 * max(a, b)) + 4
    x0, x1 = max(int(cx) - R, 0), min(int(cx) + R, S)
    y0, y1 = max(int(cy) - R, 0), min(int(cy) + R, S)
    if x1 <= x0 or y1 <= y0:
        return None
    h, w = y1 - y0, x1 - x0
    yy, xx = np.mgrid[y0:y1, x0:x1].astype(np.float32)
    dx, dy = xx - cx, yy - cy
    du = dx * ct + dy * st
    dv = -dx * st + dy * ct
    if cls == 3:                       # drips: elongate downward in image space
        r = np.sqrt((dx / a) ** 2 + (np.maximum(dy, 0) / b) ** 2
                    + (np.minimum(dy, 0) / (a * 0.9)) ** 2)
    else:
        r = np.sqrt((du / a) ** 2 + (dv / b) ** 2)
    cell = max(min(a, b) * 0.6, 3.0)
    nz = _noise(rng, h, w, cell, 3)
    field = 1.0 - r + 0.9 * (nz - 0.5)
    return y0, y1, x0, x1, field.astype(np.float32), nz


def _paint(rgb, mask, job, d, rng, inside):
    p = _patch(job, d, rng)
    if p is None:
        return
    y0, y1, x0, x1, field, nz = p
    cls = d["class_id"]
    region = field > 0
    ins = inside[y0:y1, x0:x1]
    region &= ins
    if not region.any():
        return
    alpha = np.clip(field * 4.0, 0, 1) * ins
    sub = rgb[y0:y1, x0:x1]
    h, w = field.shape
    var = _noise(rng, h, w, 5, 2)
    if cls == 1:       # rust: dark brown <-> orange, speckled
        t = np.clip(0.25 + 0.9 * var + 0.3 * (nz - 0.5), 0, 1)[..., None]
        dark = np.array([85, 38, 16], np.float32) / 255
        orange = np.array([200, 100, 32], np.float32) / 255
        shift = rng.uniform(-0.06, 0.06, 3).astype(np.float32)
        col = np.clip(dark * (1 - t) + orange * t + shift, 0, 1)
        speck = (rng.random((h, w), dtype=np.float32) > 0.93)[..., None] * 0.15
        col = np.clip(col - speck, 0, 1)
        a_ = alpha[..., None] * 0.92
    elif cls == 2:     # CUI sign: brownish-grey stain with streaks, plus slight dent shading
        base = np.array([120, 100, 78], np.float32) / 255
        col = base * (0.75 + 0.5 * var[..., None])
        a_ = alpha[..., None] * 0.6
    else:              # leak stain: wet dark or whitish deposit
        if d.get("_wet", True):
            base = np.array([45, 48, 50], np.float32) / 255
        else:
            base = np.array([215, 210, 190], np.float32) / 255
        col = base * (0.8 + 0.4 * var[..., None])
        a_ = alpha[..., None] * 0.7
    sub[...] = sub * (1 - a_) + col * a_
    mask[y0:y1, x0:x1][region] = cls


def render_job(cfg: dict, job: dict, rng) -> tuple[np.ndarray, np.ndarray]:
    """Render one job -> (rgb uint8 HxWx3, mask uint8 HxW)."""
    S = job["image_size"]
    rgb, inside, u, v = _pipe_layers(job, rng)
    mask = np.zeros((S, S), np.uint8)
    env = job["env"]
    hw = _frame(job)[3]
    for d in sorted(job["defects"], key=lambda q: q["class_id"]):
        d = dict(d)
        d["_wet"] = rng.random() < 0.5
        if d["class_id"] == 3:   # flange body at the leak position
            _flange(rgb, job, d, hw, u, v)
        _paint(rgb, mask, job, d, rng, inside)
    # lighting: global gain + soft gradient
    ang = rng.uniform(0, 2 * math.pi)
    yy, xx = np.mgrid[0:S, 0:S].astype(np.float32) / S - 0.5
    grad = 1.0 + 0.25 * (xx * math.cos(ang) + yy * math.sin(ang))
    rgb = rgb * (env["brightness"] * grad)[..., None]
    # dust: warm haze with texture
    if env["dust"] > 0:
        dn = _noise(rng, S, S, 60, 3)[..., None]
        al = env["dust"] * (0.5 + 0.7 * dn)
        rgb = rgb * (1 - al) + np.array([0.6, 0.55, 0.45], np.float32) * al
    # steam: white low-frequency clouds
    if env["steam"] > 0:
        sn = np.clip((_noise(rng, S, S, 120, 3) - 0.35) * 2.0, 0, 1)[..., None]
        al = env["steam"] * sn
        rgb = rgb * (1 - al) + np.float32(0.93) * al
    rgb = _blur(rgb.astype(np.float32), env["blur_sigma"])
    if env["noise_sigma"] > 0:
        rgb = rgb + np.float32(env["noise_sigma"]) * rng.standard_normal(rgb.shape, dtype=np.float32)
    return (np.clip(rgb, 0, 1) * 255 + 0.5).astype(np.uint8), mask


def _flange(rgb, job, d, hw, u, v):
    S = job["image_size"]
    pos = (d["u"] - 0.5) * S
    th = max(hw * 0.12, 3.0)
    band = (np.abs(u - pos) < th) & (np.abs(v) < hw * 1.12)
    rgb[band] = rgb[band] * 0.6 + 0.4 * np.array([0.35, 0.37, 0.4], np.float32)


# ---- contour tracing (numpy + small python loops) -------------------------------------

_DIRS = [(0, -1), (-1, -1), (-1, 0), (-1, 1), (0, 1), (1, 1), (1, 0), (1, -1)]  # (dy, dx) cw


def label_components(mask: np.ndarray):
    """8-connected labelling by row runs + union-find. Returns (labels int32, n)."""
    H, W = mask.shape
    labels = np.zeros((H, W), np.int32)
    parent = [0]

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    prev = []  # (start, end, label) runs of previous row
    for y in range(H):
        row = mask[y].astype(np.int8)
        d = np.diff(np.concatenate(([0], row, [0])))
        starts, ends = np.flatnonzero(d == 1), np.flatnonzero(d == -1)
        cur = []
        for s, e in zip(starts, ends):
            lab = 0
            for ps, pe, pl in prev:
                if ps < e + 1 and pe > s - 1:   # 8-connectivity overlap
                    if lab == 0:
                        lab = find(pl)
                    else:
                        parent[find(pl)] = lab
            if lab == 0:
                parent.append(len(parent))
                lab = len(parent) - 1
            labels[y, s:e] = lab
            cur.append((s, e, lab))
        prev = cur
    roots = np.array([find(i) for i in range(len(parent))], np.int32)
    labels = roots[labels]
    uniq = np.unique(labels[labels > 0])
    remap = np.zeros(len(parent), np.int32)
    remap[uniq] = np.arange(1, len(uniq) + 1)
    return remap[labels], len(uniq)


def trace_contour(comp: np.ndarray) -> list[tuple[int, int]]:
    """Moore-neighbour outer contour of one boolean component -> [(x, y), ...].

    Stops with Jacob's criterion: when the walk is back on the start pixel and would leave it
    the same way as the first move (stopping at the first return to the start pixel truncates
    the polygon when the start pixel is a cut vertex).
    """
    pad = np.pad(comp, 1)
    ys, xs = np.nonzero(pad)
    i = np.lexsort((xs, ys))[0]
    sy, sx = int(ys[i]), int(xs[i])
    pts = [(sx - 1, sy - 1)]
    by, bx = sy, sx
    d = 0  # backtrack direction (west of start is background)
    first_nd = None
    limit = 8 * int(comp.sum()) + 16
    for _ in range(limit):
        found = False
        for k in range(1, 9):
            nd = (d + k) % 8
            ny, nx = by + _DIRS[nd][0], bx + _DIRS[nd][1]
            if pad[ny, nx]:
                if first_nd is None:
                    first_nd = nd
                elif (by, bx) == (sy, sx) and nd == first_nd:
                    return pts
                py, px = by + _DIRS[(nd - 1) % 8][0], bx + _DIRS[(nd - 1) % 8][1]
                by, bx = ny, nx
                d = _DIRS.index((py - by, px - bx))
                found = True
                break
        if not found:
            break
        pts.append((bx - 1, by - 1))
    return pts


def _rdp(pts: np.ndarray, eps: float) -> np.ndarray:
    keep = np.zeros(len(pts), bool)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        if b <= a + 1:
            continue
        p, q = pts[a], pts[b]
        seg = q - p
        nrm = np.hypot(*seg)
        rel = pts[a + 1:b] - p
        dist = (np.hypot(*rel.T) if nrm == 0
                else np.abs(seg[0] * rel[:, 1] - seg[1] * rel[:, 0]) / nrm)
        j = int(np.argmax(dist))
        if dist[j] > eps:
            m = a + 1 + j
            keep[m] = True
            stack += [(a, m), (m, b)]
    return pts[keep]


def mask_polygons(mask: np.ndarray, min_area: int = 12, eps: float = 1.0, classes=None):
    """Yield (class_id, polygon Nx2 float pixel coords) for every component of every class.

    `classes` maps class id -> name (default: the camera CLASSES); id 0 is background.
    """
    for cls in (CLASSES if classes is None else classes):
        if cls == 0:
            continue
        labels, n = label_components(mask == cls)
        for k in range(1, n + 1):
            comp = labels == k
            if comp.sum() < min_area:
                continue
            pts = np.array(trace_contour(comp), float)
            if len(pts) > 4:
                pts = _rdp(pts, eps)
            if len(pts) >= 3:
                yield cls, pts


def yolo_lines(mask: np.ndarray, classes=None) -> list[str]:
    H, W = mask.shape
    lines = []
    for cls, pts in mask_polygons(mask, classes=classes):
        xy = np.clip((pts + 0.5) / np.array([W, H]), 0, 1)
        coords = " ".join(f"{c:.5f}" for c in xy.ravel())
        lines.append(f"{cls - 1} {coords}")
    return lines


def split_val(job_list: list[dict], frac: float = 0.2) -> set[str]:
    """Job ids of the validation split. Grouped by segment_id with a deterministic hash, so a
    segment (and hence any physical defect on it) is never in both train and val."""
    import hashlib

    val = set()
    for j in job_list:
        h = hashlib.md5(f"maek-split:{j['segment_id']}".encode()).digest()
        if int.from_bytes(h[:4], "big") / 2**32 < frac:
            val.add(j["job_id"])
    return val


_CFG = None


def _init_worker(cfg):
    global _CFG
    _CFG = cfg


def _render_one(task):
    from PIL import Image

    seed, i, job, out, fmt, quality = task
    out = Path(out)
    rgb, mask = render_job(_CFG, job, np.random.default_rng([seed, i]))
    jid = job["job_id"]
    img = Image.fromarray(rgb)
    if fmt == "jpg":
        img.save(out / "images" / f"{jid}.jpg", quality=quality)
    else:
        img.save(out / "images" / f"{jid}.png", compress_level=1)
    Image.fromarray(mask).save(out / "masks" / f"{jid}.png", compress_level=1)
    lines = yolo_lines(mask) if mask.any() else []
    (out / "labels" / f"{jid}.txt").write_text(
        "\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return jid


def render_all(cfg: dict, jobs: list[dict], out_dir, seed: int = 0, *,
               image_format: str = "png", jpg_quality: int = 92, workers: int = 1,
               relative_yaml: bool = False, val_frac: float = 0.2) -> Path:
    """Write images/, masks/, labels/ (YOLO-seg), train.txt, val.txt and dataset.yaml.

    image_format "png"|"jpg"; workers > 1 renders in parallel (output is identical for any
    worker count: image i uses rng [seed, i]). Train/val are split by segment_id.
    relative_yaml writes `path: .` (portable; train_yolo_seg.py resolves it at run time)
    instead of the absolute output folder. The list files always hold ./images/... paths.
    """
    if image_format not in ("png", "jpg"):
        raise ValueError(f"image_format must be 'png' or 'jpg', got {image_format!r}")
    out = Path(out_dir)
    for sub in ("images", "masks", "labels"):
        (out / sub).mkdir(parents=True, exist_ok=True)
    tasks = [(seed, i, job, str(out), image_format, jpg_quality) for i, job in enumerate(jobs)]
    if workers > 1:
        from concurrent.futures import ProcessPoolExecutor

        with ProcessPoolExecutor(workers, initializer=_init_worker, initargs=(cfg,)) as ex:
            names = list(ex.map(_render_one, tasks, chunksize=8))
    else:
        _init_worker(cfg)
        names = [_render_one(t) for t in tasks]
    val = split_val(jobs, val_frac)
    ext = image_format
    (out / "train.txt").write_text("".join(f"./images/{j}.{ext}\n" for j in names if j not in val))
    (out / "val.txt").write_text("".join(f"./images/{j}.{ext}\n" for j in names if j in val))
    cls_lines = "".join(f"  {c - 1}: {CLASSES[c]}\n" for c in CLASSES if c)
    root = "." if relative_yaml else str(out.resolve())
    (out / "dataset.yaml").write_text(
        f"path: {root}\ntrain: train.txt\nval: val.txt\nnames:\n{cls_lines}", encoding="utf-8")
    return out / "dataset.yaml"
