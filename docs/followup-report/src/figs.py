"""Figures for the MAEK real-photo adaptation report.

    python figs.py <results dir> <out dir with weights + testsets> <figure dir> <dir with e4.pt, sim_S.pt>
"""
import collections
import glob
import json
import statistics as st
import sys
from pathlib import Path

import cv2
import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams.update({"font.family": "Malgun Gothic", "axes.unicode_minus": False, "font.size": 12,
                     "axes.spines.top": False, "axes.spines.right": False})
R, OUT, FIG, W = (Path(a) for a in sys.argv[1:5])
BLUE, LIGHT, GREY, RED, GOLD = "#1f7fa8", "#7fb8d0", "#9aa3ad", "#d6453d", "#c9b458"
PURPLE = (214, 69, 61)[::-1]  # BGR of RED


def rows(f):
    return [json.loads(line) for line in (R / f).read_text().splitlines()]


def agg(rs, key, val):
    g = collections.defaultdict(list)
    for r in rs:
        g[key(r)].append(val(r))
    return {k: (st.mean(v), st.pstdev(v) if len(v) > 1 else 0) for k, v in g.items()}


def save(fig, name):
    fig.tight_layout()
    fig.savefig(FIG / name)
    plt.close(fig)


# 1. corrosion: IoU on the bridge test set vs number of real photos
c = rows("results_corr.jsonl")
vt = agg([r for r in c if r["train"] in ("vt", "none")], lambda r: (r["init"], r["n"]), lambda r: r["metrics"]["vt_test"]["iou"])
ns = [0, 25, 50, 100, 200, 396]
fig, ax = plt.subplots(figsize=(7.2, 4.2), dpi=200)
for init, col, lab in (("e4", BLUE, "합성 사전학습에서 시작"), ("coco", GREY, "일반 사전학습에서 시작")):
    xs = [n for n in ns if (init, n) in vt]
    ax.errorbar([ns.index(n) for n in xs], [vt[(init, n)][0] for n in xs], yerr=[vt[(init, n)][1] for n in xs],
                color=col, marker="o", lw=2.2, capsize=3, label=lab)
ax.annotate(f"{vt[('e4', 0)][0]:.2f}", (0, vt[("e4", 0)][0]), textcoords="offset points", xytext=(8, 6), color=BLUE, weight="bold")
ax.annotate(f"{vt[('e4', 396)][0]:.2f}", (5, vt[("e4", 396)][0]), textcoords="offset points", xytext=(-10, -22), color=BLUE, weight="bold")
ax.set_xticks(range(len(ns)))
ax.set_xticklabels([f"{n}장" for n in ns])
ax.set_ylim(0, 0.8)
ax.set_xlabel("추가 학습에 쓴 실사진 수")
ax.set_ylabel("부식 영역 일치도 (IoU)")
ax.legend(frameon=False, loc="lower right")
save(fig, "corrosion_curve.png")

# 2. site-specific data: IoU on the Ostrava test set
o = agg([r for r in c if r["init"] == "e4"], lambda r: (r["train"], r["n"]), lambda r: r["metrics"]["os_test"]["iou"])
keys = [("none", 0), ("vt", 396), ("os", 75), ("vt+os", 471)]
labels = ["합성만\n(실사진 0장)", "다른 현장 사진\n(교량 396장)", "그 현장 사진\n(산업단지 75장)", "둘 다\n(471장)"]
fig, ax = plt.subplots(figsize=(7.2, 4.2), dpi=200)
vals = [o[k][0] for k in keys]
bars = ax.bar(labels, vals, yerr=[o[k][1] for k in keys], color=[GREY, GREY, BLUE, BLUE], capsize=4, width=0.6)
for b, v in zip(bars, vals):
    ax.text(b.get_x() + b.get_width() / 2, v + o[keys[vals.index(v)]][1] + 0.025, f"{v:.2f}", ha="center", weight="bold")
ax.set_ylim(0, 0.9)
ax.set_ylabel("산업단지 시험 사진 30장의 IoU")
save(fig, "site_specific.png")

# 3. thermal: recall on the held-out session vs number of real images
t = rows("results_th.jsonl")
rc = agg(t, lambda r: (r["init"], r["n"]), lambda r: r["metrics"]["test_A_session"]["recall"])
ns = [0, 10, 25, 50, 100, 156]
fig, ax = plt.subplots(figsize=(7.2, 4.2), dpi=200)
for init, col, lab in (("sim_S", BLUE, "합성 배관 사전학습에서 시작"), ("coco", GREY, "일반 사전학습에서 시작"),
                       ("pv_A", GOLD, "태양광 열화상 사전학습에서 시작")):
    xs = [n for n in ns if (init, n) in rc]
    ax.errorbar([ns.index(n) for n in xs], [rc[(init, n)][0] * 100 for n in xs], yerr=[rc[(init, n)][1] * 100 for n in xs],
                color=col, marker="o", lw=2.2, capsize=3, label=lab)
fin = json.loads((R / "results_final.json").read_text())["thermal_final"]["metrics"]["test_A_session"]["recall"] * 100
ax.scatter([5], [fin], color=RED, s=90, zorder=5, marker="D", label="탑재 모델 (합성 이미지 병행, 회전·뒤집기)")
ax.annotate(f"{fin:.0f}%", (5, fin), textcoords="offset points", xytext=(-36, 2), color=RED, weight="bold")
ax.set_xticks(range(len(ns)))
ax.set_xticklabels([f"{n}장" for n in ns])
ax.set_ylim(0, 82)
ax.set_xlabel("추가 학습에 쓴 실제 열화상 수 (원본 기준)")
ax.set_ylabel("열점 검출률 (%)")
ax.legend(frameon=False, loc="upper left", fontsize=10)
save(fig, "thermal_curve.png")

# 4. feedback conditions
a = [r for r in rows("results_arms.jsonl") if r["arm"].startswith("T")]
arms = [("T0_full_images", "사진 통째로\n(기준)"), ("T1_tiles", "타일 분할"), ("T2_tiles_5050", "타일\n+ 50:50"),
        ("T3_tiles_5050_rotflip", "타일 + 50:50\n+ 회전·뒤집기")]
fig, ax = plt.subplots(figsize=(7.2, 4.2), dpi=200)
for j, (ds, col, lab) in enumerate((("vt_test", BLUE, "교량 시험 44장"), ("os_test", LIGHT, "산업단지 시험 30장"))):
    g = agg(a, lambda r: r["arm"], lambda r, ds=ds: r["metrics"][ds]["full640"]["iou"])
    xs = np.arange(len(arms)) + (j - 0.5) * 0.36
    ax.bar(xs, [g[k][0] for k, _ in arms], 0.36, yerr=[g[k][1] for k, _ in arms], color=col, capsize=3, label=lab)
    for x, (k, _) in zip(xs, arms):
        ax.text(x, g[k][0] + 0.04, f"{g[k][0]:.2f}", ha="center", fontsize=10)
ax.set_xticks(range(len(arms)))
ax.set_xticklabels([lab for _, lab in arms])
ax.set_ylim(0, 0.92)
ax.set_ylabel("IoU")
ax.legend(frameon=False, loc="upper right", ncol=2, fontsize=10)
save(fig, "feedback_arms.png")

# 5. before / after examples on held-out real images
from ultralytics import YOLO


def contours(mask):
    return cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]


def seg_overlay(model, im):
    r = model.predict(im, imgsz=640, conf=0.25, retina_masks=True, verbose=False)[0]
    out = im.copy()
    if r.masks is not None and len(r.masks):
        m = cv2.resize(r.masks.data.any(dim=0).cpu().numpy().astype(np.uint8), im.shape[1::-1], interpolation=cv2.INTER_NEAREST) > 0
        out[m] = (out[m] * 0.45 + np.array(PURPLE) * 0.55).astype(np.uint8)
        cv2.drawContours(out, contours(m), -1, PURPLE, 4)
    return out


def box_overlay(model, im):
    out = im.copy()
    for b in model.predict(im, imgsz=640, conf=0.25, verbose=False)[0].boxes.xyxy.tolist():
        cv2.rectangle(out, (int(b[0]), int(b[1])), (int(b[2]), int(b[3])), (255, 255, 0), 3)
    return out


def sheet(grid, heads, name):
    fig, axes = plt.subplots(len(grid), len(heads), figsize=(3.1 * len(heads), 2.45 * len(grid)), dpi=200)
    for i, row in enumerate(grid):
        for j, im in enumerate(row):
            axes[i][j].imshow(cv2.cvtColor(cv2.resize(im, (420, 315), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB))
            axes[i][j].axis("off")
            if i == 0:
                axes[i][j].set_title(heads[j], fontsize=12)
    fig.tight_layout(pad=0.4)
    fig.savefig(FIG / name)
    plt.close(fig)


T = OUT / "testsets"
before, after = YOLO(str(W / "e4.pt")), YOLO(str(OUT / "maek_corrosion_real_v1.pt"))
grid = []
for d, k in (("ds2/corr/full/vt_test", 30), ("ds2/corr/full/os_test", 10), ("ds2/corr/full/os_test", 0)):
    f = sorted(glob.glob(str(T / d / "images" / "*.jpg")))[k]
    im = cv2.imread(f)
    s = 960 / max(im.shape[:2])
    im = cv2.resize(im, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    gt = cv2.resize(cv2.imread(f.replace("images", "masks").replace(".jpg", ".png"), 0), im.shape[1::-1], interpolation=cv2.INTER_NEAREST) > 0
    truth = im.copy()
    cv2.drawContours(truth, contours(gt), -1, (255, 255, 255), 5)
    grid.append([im, seg_overlay(before, im), seg_overlay(after, im), truth])
sheet(grid, ["실사진", "추가 학습 전", "추가 학습 후", "정답 (흰 선)"], "examples_corrosion.png")

before, after = YOLO(str(W / "sim_S.pt")), YOLO(str(OUT / "maek_thermal_real_v1.pt"))
grid = []
for k in (0, 25, 50):
    f = sorted(glob.glob(str(T / "ds/th/test/images/*.jpg")))[k]
    im = cv2.imread(f)
    truth = im.copy()
    H, Wd = im.shape[:2]
    for line in Path(f.replace("images", "labels").replace(".jpg", ".txt")).read_text().splitlines():
        _, x, y, w, h = map(float, line.split())
        cv2.rectangle(truth, (int((x - w / 2) * Wd), int((y - h / 2) * H)), (int((x + w / 2) * Wd), int((y + h / 2) * H)), (255, 255, 255), 3)
    grid.append([im, box_overlay(before, im), box_overlay(after, im), truth])
sheet(grid, ["실제 열화상", "추가 학습 전", "추가 학습 후", "정답 (흰 상자)"], "examples_thermal.png")
print("figures:", sorted(p.name for p in FIG.glob("*.png")))
