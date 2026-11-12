"""Real-photo adaptation runs: fine-tune on N real images, evaluate on held-out real images.

    python run.py corr|th --shard i/k

Fixed protocol (decided before any run): conf 0.25, imgsz 640, last-epoch weights (no validation-based
selection, so the test sets are never used for tuning), epochs = clip(16000 / n_train_images, 50, 150).
Results append to results_<exp>.jsonl; finished jobs are skipped on restart.
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

ROOT = Path("/workspace/exp")
DS = ROOT / "ds"
W = ROOT / "w"
CONF, IMGSZ = 0.25, 640
SEEDS = (0, 1, 2)


def epochs_for(n_images):
    return int(min(150, max(50, round(16000 / n_images))))


def imgs(d):
    return sorted(glob.glob(str(d / "images" / "*.jpg")))


# ---------------- corrosion (segmentation) ----------------
def corr_jobs():
    jobs = [dict(exp="corr", init="e4", train="none", n=0, seed=0)]
    for init in ("e4", "coco"):
        for n in (25, 50, 100, 200, 396):
            jobs += [dict(exp="corr", init=init, train="vt", n=n, seed=s) for s in SEEDS]
        jobs += [dict(exp="corr", init=init, train="os", n=75, seed=s) for s in SEEDS]
        jobs += [dict(exp="corr", init=init, train="vt+os", n=471, seed=s) for s in SEEDS]
    return jobs


def corr_train_list(job):
    vt, os_ = imgs(DS / "corr" / "vt_train"), imgs(DS / "corr" / "os_train")
    rng = np.random.default_rng(job["seed"])
    if job["train"] == "vt":
        return [vt[i] for i in rng.permutation(len(vt))[: job["n"]]]
    return {"os": os_, "vt+os": vt + os_}[job["train"]]


def corr_eval(model, name):
    files = imgs(DS / "corr" / name)
    inter = union = pred_px = gt_px = 0
    ious, detected = [], 0
    for i in range(0, len(files), 16):
        for f, r in zip(files[i:i + 16], model.predict(files[i:i + 16], imgsz=IMGSZ, conf=CONF, retina_masks=True, verbose=False)):
            gt = cv2.imread(f.replace("/images/", "/masks/").replace(".jpg", ".png"), cv2.IMREAD_GRAYSCALE) > 0
            pred = np.zeros_like(gt)
            if r.masks is not None and len(r.masks):
                m = r.masks.data.any(dim=0).cpu().numpy().astype(np.uint8)
                pred = cv2.resize(m, gt.shape[::-1], interpolation=cv2.INTER_NEAREST) > 0
            a, b = int((pred & gt).sum()), int((pred | gt).sum())
            inter, union, pred_px, gt_px = inter + a, union + b, pred_px + int(pred.sum()), gt_px + int(gt.sum())
            ious.append(a / b if b else 1.0)
            detected += bool(a)
    return {"n": len(files), "iou": inter / max(union, 1), "precision": inter / max(pred_px, 1), "recall": inter / max(gt_px, 1),
            "mean_image_iou": float(np.mean(ious)), "image_hit_rate": detected / len(files)}


def corr_init(job):
    return str(W / "e4.pt") if job["init"] == "e4" else "yolov8n-seg.pt"


def corr_names(job):
    return YOLO(str(W / "e4.pt")).names if job["init"] == "e4" else {0: "corrosion"}


def corr_evaluate(model, job):
    out = {"vt_test": corr_eval(model, "vt_test"), "os_test": corr_eval(model, "os_test")}
    if "os" not in job["train"]:  # Ostrava train split is unseen too, so it can be scored as well
        out["os_train_unseen"] = corr_eval(model, "os_train")
    return out


# ---------------- thermal (detection) ----------------
def th_jobs():
    n_all = len(json.loads((DS / "th" / "manifest.json").read_text())["pool"])
    jobs = [dict(exp="th", init=i, train="none", n=0, seed=0) for i in ("sim_S", "pv_A")]
    for init in ("sim_S", "coco", "pv_A"):
        for n in (10, 25, 50, 100, n_all):
            jobs += [dict(exp="th", init=init, train="rf", n=n, seed=s) for s in SEEDS]
    return jobs


def th_train_list(job):
    pool = json.loads((DS / "th" / "manifest.json").read_text())["pool"]
    keys = sorted(pool)
    pick = [keys[i] for i in np.random.default_rng(job["seed"]).permutation(len(keys))[: job["n"]]]
    return [str(DS / "th" / "pool" / "images" / (s + ".jpg")) for k in pick for s in pool[k]]


def iou(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
    return ix / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - ix + 1e-9)


def th_evaluate(model, job):
    files = imgs(DS / "th" / "test")
    tp = fp = n_gt = 0
    for i in range(0, len(files), 32):
        for f, r in zip(files[i:i + 32], model.predict(files[i:i + 32], imgsz=IMGSZ, conf=CONF, verbose=False)):
            gts = []
            for line in open(f.replace("/images/", "/labels/").replace(".jpg", ".txt")):
                _, x, y, w, h = map(float, line.split())
                gts.append([x - w / 2, y - h / 2, x + w / 2, y + h / 2])
            n_gt += len(gts)
            used = set()
            order = r.boxes.conf.argsort(descending=True).tolist()
            for k in order:
                p = r.boxes.xyxyn[k].tolist()
                best = max(((iou(p, g), j) for j, g in enumerate(gts) if j not in used), default=(0, -1))
                if best[0] >= 0.5:
                    used.add(best[1]); tp += 1
                else:
                    fp += 1
    return {"test_A_session": {"n": len(files), "gt": n_gt, "recall": tp / max(n_gt, 1), "precision": tp / max(tp + fp, 1),
                               "false_alarms_per_image": fp / len(files)}}


def th_init(job):
    return {"sim_S": str(W / "sim_S.pt"), "pv_A": str(W / "pv_A.pt"), "coco": "yolov8s.pt"}[job["init"]]


SPEC = {"corr": (corr_jobs, corr_train_list, corr_init, corr_names, corr_evaluate),
        "th": (th_jobs, th_train_list, th_init, lambda job: {0: "hot_spot"}, th_evaluate)}


def main():
    exp = sys.argv[1]
    i, k = (int(x) for x in sys.argv[sys.argv.index("--shard") + 1].split("/")) if "--shard" in sys.argv else (0, 1)
    jobs_fn, train_list, init, names, evaluate = SPEC[exp]
    res_path = ROOT / f"results_{exp}.jsonl"
    key = lambda j: f"{j['exp']}-{j['init']}-{j['train']}-{j['n']}-s{j['seed']}"  # noqa: E731
    for idx, job in enumerate(jobs_fn()):
        if idx % k != i:
            continue
        done = {json.loads(l)["key"] for l in res_path.read_text().splitlines()} if res_path.exists() else set()
        if key(job) in done:
            continue
        t0 = time.time()
        run = ROOT / "runs" / key(job)
        if job["n"] == 0:
            model, n_img, ep = YOLO(init(job)), 0, 0
        else:
            files = train_list(job)
            run.mkdir(parents=True, exist_ok=True)
            (run / "train.txt").write_text("\n".join(files) + "\n")
            (run / "data.yaml").write_text(yaml.safe_dump({"path": str(run), "train": "train.txt", "val": "train.txt", "names": dict(names(job))}))
            n_img, ep = len(files), epochs_for(len(files))
            YOLO(init(job)).train(data=str(run / "data.yaml"), epochs=ep, imgsz=IMGSZ, batch=16, workers=8, seed=job["seed"],
                                  val=False, plots=False, project=str(run), name="t", exist_ok=True, verbose=False, patience=1000)
            model = YOLO(str(run / "t" / "weights" / "last.pt"))
        row = dict(job, key=key(job), train_images=n_img, epochs=ep, metrics=evaluate(model, job), seconds=round(time.time() - t0))
        with res_path.open("a") as f:
            f.write(json.dumps(row) + "\n")
        print("DONE", row["key"], json.dumps(row["metrics"])[:300], flush=True)
    print("SHARD_FINISHED", flush=True)


if __name__ == "__main__":
    main()
