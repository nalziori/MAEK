"""Stage 2: retrain with the judges' feedback applied, then train the two models to deploy.

    python run2.py arms --shard i/k     # ablation: tiles / 50:50 balance / rotation+flip / severity labels
    python run2.py final                # deployable corrosion and thermal models (+ synthetic replay)

Protocol fixed before running: conf 0.25, imgsz 640, last-epoch weights, no tuning on the test sets.
"""
import glob
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import yaml
from ultralytics import YOLO

import run as s1

ROOT = Path("/workspace/exp")
DS, DS2, W = ROOT / "ds", ROOT / "ds2", ROOT / "w"
CONF, IMGSZ, TILE, STRIDE = 0.25, 640, 640, 512
AUG = dict(degrees=20.0, flipud=0.5)  # pipes and steel members have no canonical orientation
E4_NAMES = {0: "corrosion", 1: "cui_sign", 2: "leak_stain"}


def starts(n):
    return [0] if n <= TILE else sorted(set(list(range(0, n - TILE, STRIDE)) + [n - TILE]))


def union_mask(result, shape):
    if result.masks is None or not len(result.masks):
        return np.zeros(shape, bool)
    m = result.masks.data.any(dim=0).cpu().numpy().astype(np.uint8)
    return cv2.resize(m, shape[::-1], interpolation=cv2.INTER_NEAREST) > 0


def predict_mask(model, im, tiled):
    if not tiled:
        return union_mask(model.predict(im, imgsz=IMGSZ, conf=CONF, retina_masks=True, verbose=False)[0], im.shape[:2])
    out = np.zeros(im.shape[:2], bool)
    pos = [(y, x) for y in starts(im.shape[0]) for x in starts(im.shape[1])]
    crops = [im[y:y + TILE, x:x + TILE] for y, x in pos]
    for (y, x), c, r in zip(pos, crops, model.predict(crops, imgsz=IMGSZ, conf=CONF, retina_masks=True, verbose=False)):
        out[y:y + c.shape[0], x:x + c.shape[1]] |= union_mask(r, c.shape[:2])
    return out


def gt_mask(img_path, shape):
    p = Path(img_path.replace("/images/", "/masks/")).with_suffix(".png")
    if "syn_corr" not in img_path and p.exists():
        return cv2.imread(str(p), cv2.IMREAD_GRAYSCALE) > 0
    m = np.zeros(shape, np.uint8)  # rasterise YOLO polygons (synthetic sets)
    lab = Path(img_path.replace("/images/", "/labels/")).with_suffix(".txt")
    for line in lab.read_text().splitlines() if lab.exists() else []:
        v = np.array(line.split()[1:], float).reshape(-1, 2) * [shape[1], shape[0]]
        cv2.fillPoly(m, [v.astype(np.int32)], 1)
    return m > 0


def seg_eval(model, files, tiled):
    inter = union = pp = gp = 0
    hit = pos = fa = neg = 0
    for f in files:
        im = cv2.imread(f)
        gt, pred = gt_mask(f, im.shape[:2]), predict_mask(model, im, tiled)
        a = int((pred & gt).sum())
        inter, union, pp, gp = inter + a, union + int((pred | gt).sum()), pp + int(pred.sum()), gp + int(gt.sum())
        if gt.any():
            pos += 1; hit += bool(a)
        else:
            neg += 1; fa += bool(pred.any())
    return {"n": len(files), "iou": inter / max(union, 1), "precision": inter / max(pp, 1), "recall": inter / max(gp, 1),
            "image_hit_rate": hit / max(pos, 1), "normal_images": neg, "normal_false_alarm_rate": fa / neg if neg else None}


def images(d):
    return sorted(f for f in glob.glob(str(d / "images" / "**" / "*.*"), recursive=True))


def corr_tests(model):
    out = {}
    for name in ("vt_test", "os_test"):
        fs = images(DS2 / "corr" / "full" / name)
        out[name] = {"full640": seg_eval(model, fs, False), "tiled": seg_eval(model, fs, True)}
    out["synthetic_test"] = {"full640": seg_eval(model, images(DS2 / "syn_corr" / "test" / "camera"), False)}
    return out


def tile_list(balance, seed):
    files, n_def, n_norm = [], 0, 0
    for name in ("vt_train", "os_train"):
        d = DS2 / "corr" / "tiles" / name
        meta = json.loads((d / "meta.json").read_text())
        de = [str(d / "images" / (t["tile"] + ".jpg")) for t in meta if t["defect"]]
        no = [str(d / "images" / (t["tile"] + ".jpg")) for t in meta if not t["defect"]]
        files += de + no; n_def += len(de); n_norm += len(no)
        if balance:  # 50:50 by repeating normal tiles (they get different online augmentation each epoch)
            rng = np.random.default_rng(seed)
            files += [no[i] for i in rng.integers(0, len(no), len(de) - len(no))]
    return files


def sev_eval(model):
    fs = images(DS2 / "corr" / "sev" / "test")
    inter, union = np.zeros(3), np.zeros(3)
    ai = au = 0
    for f in fs:
        gt = cv2.imread(f.replace("/images/", "/masks/").replace(".jpg", ".png"), cv2.IMREAD_GRAYSCALE)
        r = model.predict(f, imgsz=IMGSZ, conf=CONF, retina_masks=True, verbose=False)[0]
        pred = np.zeros_like(gt)
        if r.masks is not None and len(r.masks):
            for k in r.boxes.conf.argsort().tolist():  # higher confidence painted last
                m = cv2.resize(r.masks.data[k].cpu().numpy().astype(np.uint8), gt.shape[::-1], interpolation=cv2.INTER_NEAREST) > 0
                pred[m] = int(r.boxes.cls[k]) + 1
        for c in range(3):
            inter[c] += ((pred == c + 1) & (gt == c + 1)).sum(); union[c] += ((pred == c + 1) | (gt == c + 1)).sum()
        ai += ((pred > 0) & (gt > 0)).sum(); au += ((pred > 0) | (gt > 0)).sum()
    iou = (inter / np.maximum(union, 1)).tolist()
    return {"n": len(fs), "iou_fair": iou[0], "iou_poor": iou[1], "iou_severe": iou[2], "mean_iou": float(np.mean(iou)), "iou_any_corrosion": float(ai / max(au, 1))}


def train(key, init, files, names, epochs, seed, **extra):
    run = ROOT / "runs2" / key
    run.mkdir(parents=True, exist_ok=True)
    (run / "train.txt").write_text("\n".join(files) + "\n")
    (run / "data.yaml").write_text(yaml.safe_dump({"path": str(run), "train": "train.txt", "val": "train.txt", "names": names}))
    YOLO(init).train(data=str(run / "data.yaml"), epochs=epochs, imgsz=IMGSZ, batch=16, workers=8, seed=seed, val=False, plots=False,
                     project=str(run), name="t", exist_ok=True, verbose=False, patience=1000, **extra)
    return YOLO(str(run / "t" / "weights" / "last.pt"))


def arm_jobs():
    jobs = [dict(arm="E4_zero_shot", seed=0)]
    for s in (0, 1, 2):
        jobs += [dict(arm="T1_tiles", seed=s), dict(arm="T2_tiles_5050", seed=s),
                 dict(arm="T3_tiles_5050_rotflip", seed=s), dict(arm="S_severity_labels", seed=s)]
    return jobs + [dict(arm="T0_full_images", seed=s) for s in (0, 1, 2)]  # last: these wait for stage-1 weights


def run_arm(job):
    arm, seed = job["arm"], job["seed"]
    key = f"{arm}-s{seed}"
    if arm == "E4_zero_shot":
        return corr_tests(YOLO(str(W / "e4.pt"))), 0, 0
    if arm == "T0_full_images":  # stage-1 model trained on the same photos, not tiled
        w = ROOT / "runs" / f"corr-e4-vt+os-471-s{seed}" / "t" / "weights" / "last.pt"
        done = lambda: any(f'"corr-e4-vt+os-471-s{seed}"' in l for l in (ROOT / "results_corr.jsonl").read_text().splitlines())  # noqa: E731
        while not done():  # stage 1 may still be training this model
            time.sleep(30)
        return corr_tests(YOLO(str(w))), 471, 50
    if arm == "S_severity_labels":
        fs = images(DS2 / "corr" / "sev" / "train")
        ep = s1.epochs_for(len(fs))
        return sev_eval(train(key, str(W / "e4.pt"), fs, {0: "fair", 1: "poor", 2: "severe"}, ep, seed)), len(fs), ep
    fs = tile_list(arm != "T1_tiles", seed)
    extra = AUG if arm.endswith("rotflip") else {}
    return corr_tests(train(key, str(W / "e4.pt"), fs, E4_NAMES, 20, seed, **extra)), len(fs), 20


def th_tests(model):
    out = s1.th_evaluate(model, None)
    files = images(DS2 / "syn_th" / "test")
    tp = fp = n_gt = 0
    for i in range(0, len(files), 32):
        for f, r in zip(files[i:i + 32], model.predict(files[i:i + 32], imgsz=IMGSZ, conf=CONF, verbose=False)):
            gts = [[x - w / 2, y - h / 2, x + w / 2, y + h / 2] for _, x, y, w, h in (map(float, l.split()) for l in open(f.replace("/images/", "/labels/").replace(".jpg", ".txt")))]
            n_gt += len(gts); used = set()
            for k in r.boxes.conf.argsort(descending=True).tolist():
                p = r.boxes.xyxyn[k].tolist()
                best = max(((s1.iou(p, g), j) for j, g in enumerate(gts) if j not in used), default=(0, -1))
                if best[0] >= 0.5:
                    used.add(best[1]); tp += 1
                else:
                    fp += 1
    out["synthetic_test"] = {"n": len(files), "gt": n_gt, "recall": tp / max(n_gt, 1), "precision": tp / max(tp + fp, 1), "false_alarms_per_image": fp / len(files)}
    return out


def final():
    res = {}
    # corrosion: all feedback (tiles, 50:50, rotation/flip) + synthetic replay so the simulator images still work
    fs = tile_list(True, 0) + images(DS2 / "syn_corr" / "replay" / "camera")
    m = train("final_corrosion", str(W / "e4.pt"), fs, E4_NAMES, 20, 0, **AUG)
    res["corrosion_final"] = {"train_images": len(fs), "epochs": 20, "metrics": corr_tests(m)}
    # thermal: real leak photos (sessions other than the held-out one) + synthetic replay
    pool = json.loads((DS / "th" / "manifest.json").read_text())["pool"]
    fs = [str(DS / "th" / "pool" / "images" / (s + ".jpg")) for k in sorted(pool) for s in pool[k]] + images(DS2 / "syn_th" / "replay")
    ep = s1.epochs_for(len(fs))
    m = train("final_thermal", str(W / "sim_S.pt"), fs, {0: "hot_spot"}, ep, 0, **AUG)
    res["thermal_final"] = {"train_images": len(fs), "epochs": ep, "metrics": th_tests(m)}
    res["thermal_before(sim_S)"] = {"metrics": th_tests(YOLO(str(W / "sim_S.pt")))}
    (ROOT / "results_final.json").write_text(json.dumps(res, indent=2))
    print(json.dumps(res, indent=2), flush=True)


def main():
    if sys.argv[1] == "final":
        final()
        print("FINAL_FINISHED", flush=True)
        return
    i, k = (int(x) for x in sys.argv[sys.argv.index("--shard") + 1].split("/")) if "--shard" in sys.argv else (0, 1)
    res_path = ROOT / "results_arms.jsonl"
    for idx, job in enumerate(arm_jobs()):
        key = f"{job['arm']}-s{job['seed']}"
        if "--list" in sys.argv:
            print(key); continue
        if idx % k != i or (res_path.exists() and key in {json.loads(l)["key"] for l in res_path.read_text().splitlines()}):
            continue
        t0 = time.time()
        metrics, n, ep = run_arm(job)
        with res_path.open("a") as f:
            f.write(json.dumps(dict(job, key=key, train_images=n, epochs=ep, metrics=metrics, seconds=round(time.time() - t0))) + "\n")
        print("DONE", key, flush=True)
    print("SHARD_FINISHED", flush=True)


if __name__ == "__main__":
    main()
