"""Read-only census of saved thermal data and diagnostic annotation shortcuts.

No fitting of the product model, no archive mutation, and no new evaluation set.
Ground-truth geometry classifiers are oracle diagnostics, never deployment results.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import math
from collections import Counter
from pathlib import Path
from zipfile import ZipFile

import numpy as np
from PIL import Image

NAMES = ("normal", "wet_insulation", "insulation_damage", "steam_leak")


def describe(values):
    a = np.asarray(values, dtype=float)
    if not len(a):
        return {"n": 0}
    return {"n": len(a), "min": float(a.min()), "p10": float(np.quantile(a, .1)),
            "median": float(np.median(a)), "p90": float(np.quantile(a, .9)),
            "max": float(a.max()), "mean": float(a.mean())}


def histogram_summary(hist):
    n = int(hist.sum())
    if not n:
        return {"pixels": 0}
    occupied = np.flatnonzero(hist)
    cumulative = hist.cumsum()
    quantiles = {f"p{int(q * 100)}_c": float(np.searchsorted(cumulative, math.ceil(q * n)) / 100 - 50)
                 for q in (.01, .5, .99)}
    return {"pixels": n, "min_c": float(occupied[0] / 100 - 50),
            "max_c": float(occupied[-1] / 100 - 50), **quantiles,
            "png_floor_pixels": int(hist[0]), "png_ceiling_pixels": int(hist[-1]),
            "below_minus40_pixels": int(hist[:1000].sum()),
            "above_200_pixels": int(hist[25001:].sum()),
            "outside_model_window_fraction": float((hist[:1000].sum() + hist[25001:].sum()) / n)}


def geometry(binary, v, half_width):
    yy, xx = np.nonzero(binary)
    if not len(xx):
        return {}
    h, w = binary.shape
    width, height = int(xx.max() - xx.min() + 1), int(yy.max() - yy.min() + 1)
    return {"pixels": len(xx), "fraction": len(xx) / binary.size,
            "bbox_width": width, "bbox_height": height, "aspect": width / height,
            "cx_norm": float(xx.mean() / w), "cy_norm": float(yy.mean() / h),
            "pipe_v_norm": float(v[binary].mean() / half_width),
            "outside_pipe_fraction": float(np.mean(np.abs(v[binary]) >= half_width)),
            "above_axis_fraction": float(np.mean(v[binary] < 0)),
            "edge_touch": bool(xx.min() == 0 or yy.min() == 0 or xx.max() == w - 1 or yy.max() == h - 1)}


def summarize_rows(rows, instances, histogram):
    out = {"images": len(rows), "normal_images": sum(r["class_set"] == "normal" for r in rows),
           "mixed_class_images": sum("+" in r["class_set"] for r in rows),
           "class_sets": dict(Counter(r["class_set"] for r in rows)),
           "medium": dict(Counter(r["medium"] for r in rows)),
           "jacket": dict(Counter(r["jacket"] for r in rows)),
           "hard_factors": dict(Counter(h for r in rows for h in r["hard"].split("|") if h)),
           "images_with_hard_factor": sum(bool(r["hard"]) for r in rows),
           "metadata_defects": len(instances),
           "metadata_defect_kinds": dict(Counter(d["kind"] for d in instances)),
           "temperature_all_pixels": histogram_summary(histogram.sum(axis=0)),
           "classes": {}}
    for key in ("temp_c", "ambient_c", "wind_mps", "sun_k", "eps_jacket", "eps_set", "sky_offset_k", "tilt_deg", "hw_px", "blur_sigma"):
        out[key] = describe([r[key] for r in rows])
    for c, name in enumerate(NAMES):
        relevant = [r for r in rows if r[f"c{c}_pixels"] > 0] if c else [r for r in rows if r["class_set"] == "normal"]
        class_instances = [d for d in instances if d["class_id"] == c]
        item = {"image_support": len(relevant), "metadata_defect_count": len(class_instances),
                "medium_image_counts": dict(Counter(r["medium"] for r in relevant)),
                "jacket_image_counts": dict(Counter(r["jacket"] for r in relevant)),
                "image_min_c": describe([r["image_min_c"] for r in relevant]),
                "image_max_c": describe([r["image_max_c"] for r in relevant]),
                "process_temp_c": describe([r["temp_c"] for r in relevant]),
                "image_clipped_fraction": describe([r["clipped_fraction"] for r in relevant]),
                "images_with_any_clipped_pixel": sum(r["clip_low_pixels"] + r["clip_high_pixels"] > 0 for r in relevant),
                "gt_pixels_temperature": histogram_summary(histogram[c])}
        if c:
            for key in ("pixels", "fraction", "bbox_width", "bbox_height", "aspect", "cx_norm", "cy_norm", "pipe_v_norm", "outside_pipe_fraction", "above_axis_fraction"):
                item[f"gt_{key}"] = describe([r[f"c{c}_{key}"] for r in relevant])
            item["gt_centroid_below_pipe_axis_images"] = sum(r[f"c{c}_pipe_v_norm"] > 0 for r in relevant)
            item["gt_centroid_above_pipe_axis_images"] = sum(r[f"c{c}_pipe_v_norm"] < 0 for r in relevant)
            item["gt_pixels_under_100_images"] = sum(r[f"c{c}_pixels"] < 100 for r in relevant)
            item["gt_bbox_under_10px_both_axes_images"] = sum(r[f"c{c}_bbox_width"] < 10 and r[f"c{c}_bbox_height"] < 10 for r in relevant)
            item["gt_edge_touch_images"] = sum(r[f"c{c}_edge_touch"] for r in relevant)
            item["metadata_true_dt_k"] = describe([d["true_dt_k"] for d in class_instances])
            item["metadata_orifice_mm"] = describe([d["orifice_mm"] for d in class_instances])
            item["metadata_soft_values"] = dict(Counter(str(d.get("soft")) for d in class_instances))
        out["classes"][name] = item
    return out


def score(y, predictions, classes):
    confusion = np.zeros((len(classes), len(classes)), dtype=int)
    for actual, predicted in zip(y, predictions):
        confusion[classes.index(int(actual)), classes.index(int(predicted))] += 1
    recall = np.divide(np.diag(confusion), confusion.sum(axis=1), out=np.zeros(len(classes), dtype=float), where=confusion.sum(axis=1) != 0)
    return {"n": len(y), "correct": int(np.trace(confusion)),
            "accuracy": float(np.trace(confusion) / len(y)) if len(y) else None,
            "macro_recall_supported_classes": float(recall[confusion.sum(axis=1) > 0].mean()),
            "classes": [NAMES[c] for c in classes], "confusion_actual_rows": confusion.tolist()}


def classifier_diagnostics(rows):
    outcomes = {}
    definitions = {
        "oracle_gt_image_geometry_knn5": (["gt_fraction", "gt_bbox_width", "gt_bbox_height", "gt_aspect", "gt_cx_norm", "gt_cy_norm"], [1, 2, 3]),
        "oracle_gt_plus_pipe_geometry_knn5": (["gt_fraction", "gt_bbox_width", "gt_bbox_height", "gt_aspect", "gt_cx_norm", "gt_cy_norm", "gt_pipe_v_norm", "gt_outside_pipe_fraction"], [1, 2, 3]),
        "observable_global_temperature_knn5": (["image_min_c", "image_max_c", "image_mean_c", "image_p01_c", "image_median_c", "image_p99_c", "clipped_fraction"], [0, 1, 2, 3]),
    }
    for name, (features, classes) in definitions.items():
        eligible = [r for r in rows if r["target_class"] in classes]
        train = [r for r in eligible if r["partition"] == "train/train"]
        x = np.array([[r[k] for k in features] for r in train], dtype=float)
        y = np.array([r["target_class"] for r in train])
        scale = x.std(axis=0)
        scale[scale == 0] = 1
        center = x.mean(axis=0)
        x = (x - center) / scale
        majority = int(np.bincount(y, minlength=4).argmax())
        item = {"features": features, "fit_n": len(train), "fit_partition": "train/train",
                "selection": "Fixed k=5 Euclidean nearest neighbours, train-only z-score; lowest class ID breaks voting ties. No validation selection.",
                "training_majority_class": NAMES[majority], "evaluations": {}}
        for partition in ("train/val", "shifted/all"):
            test = [r for r in eligible if r["partition"] == partition or (partition == "shifted/all" and r["condition"] == "shifted")]
            query = (np.array([[r[k] for k in features] for r in test]) - center) / scale
            predictions = []
            for q in query:
                nearest = np.argsort(np.sum((x - q) ** 2, axis=1), kind="stable")[:5]
                predictions.append(int(np.bincount(y[nearest], minlength=4).argmax()))
            truth = [r["target_class"] for r in test]
            item["evaluations"][partition] = {**score(truth, predictions, classes),
                                              "majority_baseline": score(truth, [majority] * len(test), classes)}
        outcomes[name] = item
    return outcomes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows, defects = [], []
    histograms = {}
    with ZipFile(args.archive) as archive:
        for condition in ("train", "shifted"):
            prefix = f"thermal/{condition}"
            jobs = json.loads(archive.read(f"{prefix}/jobs.json"))
            split_by_id = {}
            for split in ("train", "val"):
                for line in archive.read(f"{prefix}/{split}.txt").decode().splitlines():
                    if line.strip():
                        job_id = Path(line.strip()).stem
                        assert job_id not in split_by_id
                        split_by_id[job_id] = split
            assert set(split_by_id) == {j["job_id"] for j in jobs}
            for job in jobs:
                job_id = job["job_id"]
                partition = f"{condition}/{split_by_id[job_id]}"
                with Image.open(io.BytesIO(archive.read(f"{prefix}/images/{job_id}.png"))) as im:
                    raw = np.array(im)
                with Image.open(io.BytesIO(archive.read(f"{prefix}/masks/{job_id}.png"))) as im:
                    mask = np.array(im)
                assert raw.dtype == np.uint16 and raw.shape == mask.shape == (256, 320)
                assert set(np.unique(mask)) <= {0, 1, 2, 3}
                present = sorted(set(np.unique(mask)) - {0})
                class_set = "+".join(NAMES[c] for c in present) or "normal"
                assert bool(present) != job["negative"]
                assert set(present) == {d["class_id"] for d in job["defects"]}
                temp = raw.astype(float) / 100 - 50
                scene, seg = job["scene"], job["seg"]
                yy, xx = np.indices(raw.shape)
                theta = math.radians(scene["tilt_deg"])
                v = -(xx - job["image_w"] / 2) * math.sin(theta) + (yy - scene["cy_px"]) * math.cos(theta)
                low, high = int(np.sum(raw < 1000)), int(np.sum(raw > 25000))
                row = {"condition": condition, "partition": partition, "job_id": job_id,
                       "class_set": class_set, "target_class": int(present[0]) if len(present) == 1 else (0 if not present else -1),
                       "metadata_defects": len(job["defects"]), "medium": seg["medium"], "jacket": seg["jacket"],
                       "temp_c": seg["temp_c"], "hard": "|".join(sorted(job["hard"])),
                       **{k: scene[k] for k in ("ambient_c", "wind_mps", "sun_k", "eps_jacket", "eps_set", "sky_offset_k", "tilt_deg", "hw_px", "blur_sigma")},
                       "image_min_c": float(temp.min()), "image_max_c": float(temp.max()), "image_mean_c": float(temp.mean()),
                       "image_p01_c": float(np.quantile(temp, .01)), "image_median_c": float(np.median(temp)), "image_p99_c": float(np.quantile(temp, .99)),
                       "clip_low_pixels": low, "clip_high_pixels": high, "clipped_fraction": (low + high) / raw.size,
                       "png_floor_pixels": int(np.sum(raw == 0)), "png_ceiling_pixels": int(np.sum(raw == 65535))}
                hist = histograms.setdefault(partition, np.zeros((4, 65536), dtype=np.int64))
                for c in range(4):
                    selected = mask == c
                    hist[c] += np.bincount(raw[selected], minlength=65536)
                    row[f"c{c}_pixels"] = int(selected.sum())
                    if c and selected.any():
                        g = geometry(selected, v, scene["hw_px"])
                        row.update({f"c{c}_{k}": value for k, value in g.items()})
                row.update({f"gt_{k}": value for k, value in geometry(mask > 0, v, scene["hw_px"]).items()})
                assert sum(row[f"c{c}_pixels"] for c in range(4)) == raw.size
                rows.append(row)
                defects.extend({**d, "condition": condition, "partition": partition, "job_id": job_id} for d in job["defects"])
            print(f"Read {condition}: {len(jobs)} images", flush=True)
    summaries = {}
    for name in ("train/train", "train/val", "train/all", "shifted/train", "shifted/val", "shifted/all", "all"):
        selected = [r for r in rows if name == "all" or r["partition"] == name or (name.endswith("/all") and r["condition"] == name.split("/")[0])]
        instances = [d for d in defects if name == "all" or d["partition"] == name or (name.endswith("/all") and d["condition"] == name.split("/")[0])]
        hist = sum((h for p, h in histograms.items() if name == "all" or p == name or (name.endswith("/all") and p.split("/")[0] == name.split("/")[0])), start=np.zeros((4, 65536), dtype=np.int64))
        summaries[name] = summarize_rows(selected, instances, hist)
        assert summaries[name]["temperature_all_pixels"]["pixels"] == len(selected) * 320 * 256
    assert len(rows) == 1300
    assert [summaries[n]["images"] for n in ("train/train", "train/val", "shifted/all")] == [812, 188, 300]
    diagnostics = classifier_diagnostics(rows)
    report = {"archive": str(args.archive.resolve()), "census_images": len(rows),
              "methods": {"temperature": "Saved uint16 / 100 - 50 degC; model-window clipping strictly < -40 or > 200. PNG endpoints counted separately; endpoint pixels suggest encoding saturation but do not establish pre-encoding values.",
                          "unit": "GT statistics are per image-class union; two same-class defects in one frame count once. Metadata defects count separately and are not mask-derived instances.",
                          "classifier": "Only single-class-positive images for GT geometry; observable temperature diagnostic adds normal images. Mixed-class images excluded. GT mask and pipe geometry are unavailable deployment truth and these scores are NOT detection performance.",
                          "causality": "Cross-sectional correlations in this archive do not prove model reliance or field generalization. Existing shifted data have already been inspected, so this is diagnostic, not a fresh holdout.",
                          "normal_histogram": "For class normal, image support means normal frames; gt_pixels_temperature is class-0 background pixels from ALL frames, not only normal frames."},
              "partitions": summaries, "diagnostics": diagnostics,
              "validation": {"all_image_mask_metadata_presence_matches": True, "all_pixel_count_sums_match": True,
                             "split_coverage_and_disjointness": True, "decoded_images": len(rows), "decoded_masks": len(rows)}}
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "thermal-bias.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    fields = list(dict.fromkeys(k for row in rows for k in row))
    with (args.output / "thermal-bias.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    lines = ["# 열화상 데이터 전수 분포·shortcut 진단", "", "1300장 원본 PNG, semantic GT, jobs.json을 모두 읽었다. 학습·데이터 수정은 하지 않았다.", "", "## 단위와 해석", "", "- 클래스 표의 n은 해당 클래스가 한 픽셀 이상 존재하는 **이미지 수**다. 한 이미지의 같은 클래스 결함 여러 개는 한 번 센다.", "- metadata 결함 수와 이미지 수는 다르다. GT geometry 통계는 이미지별 클래스 마스크 합집합이다.", "- GT geometry 분류기는 정답 마스크를 입력받는 oracle 진단이며 실제 탐지 성능이 아니다. 정상·복합 클래스 프레임을 제외한 3분류다.", "- 온도 분류기는 GT 없이 프레임 전체 온도 요약으로 정상 포함 4분류한다. 복합 클래스 프레임은 제외하므로 두 진단의 정확도를 직접 비교하면 안 된다.", "- 기존 shifted는 이미 검토한 진단 데이터이며 새로운 독립 평가가 아니다. 상관관계는 학습 모델의 shortcut 사용을 입증하지 않는다.", "", "## 전수 집계", "", "|집합|이미지|정상|복합 클래스|metadata 결함|전처리 범위 밖 픽셀|", "|---|---:|---:|---:|---:|---:|"]
    for name in ("train/train", "train/val", "shifted/all"):
        s = summaries[name]
        lines.append(f"|{name}|{s['images']}|{s['normal_images']}|{s['mixed_class_images']}|{s['metadata_defects']}|{s['temperature_all_pixels']['outside_model_window_fraction']:.3%}|")
    lines += ["", "클리핑은 학습 전처리 범위 −40~200°C를 벗어난 픽셀이다. PNG 저장 하한 −50°C·상한 605.35°C endpoint는 별도 집계했으며 실제 물리온도라는 뜻이 아니다.", "", "|조건|클래스|이미지 n|metadata 결함|GT 면적 중앙값 px|GT 온도 p01 / p50 / p99 °C|GT 클리핑|중심이 배관 아래|", "|---|---|---:|---:|---:|---|---:|---:|"]
    for condition in ("train/all", "shifted/all"):
        for name in NAMES[1:]:
            s = summaries[condition]["classes"][name]
            t = s["gt_pixels_temperature"]
            lines.append(f"|{condition}|{name}|{s['image_support']}|{s['metadata_defect_count']}|{s['gt_pixels']['median']:.0f}|{t['p1_c']:.2f} / {t['p50_c']:.2f} / {t['p99_c']:.2f}|{t['outside_model_window_fraction']:.3%}|{s['gt_centroid_below_pipe_axis_images']}/{s['image_support']}|")
    lines += ["", "## 고정 k=5 분류 진단", "", "train/train에서만 평균·표준편차와 이웃을 정했다. 검증 결과를 이용한 하이퍼파라미터 선택은 없다. GT geometry는 면적·bbox·aspect·중심좌표, +pipe는 배관 상대위치·바깥 픽셀 비율도 사용한다.", "", "|입력|평가 집합|n|맞힌 수|정확도|macro recall|학습 최빈 클래스 baseline|", "|---|---|---:|---:|---:|---:|---:|"]
    for name, item in diagnostics.items():
        for partition, s in item["evaluations"].items():
            lines.append(f"|{name}|{partition}|{s['n']}|{s['correct']}|{s['accuracy']:.2%}|{s['macro_recall_supported_classes']:.2%}|{s['majority_baseline']['accuracy']:.2%}|")
    lines += ["", "## 환경·재질·유체 분포", ""]
    for condition in ("train/all", "shifted/all"):
        s = summaries[condition]
        lines += [f"- {condition}: medium {s['medium']}; jacket {s['jacket']}; hard factor 포함 {s['images_with_hard_factor']}/{s['images']}.", f"- {condition}: 풍속 {s['wind_mps']['min']:.2f}~{s['wind_mps']['max']:.2f} m/s; sun_k {s['sun_k']['min']:.2f}~{s['sun_k']['max']:.2f}; eps_set {s['eps_set']['min']:.4f}~{s['eps_set']['max']:.4f}."]
    lines += ["", "## 발견한 편향과 해석 한계", "", "- wet_insulation GT 중심은 train 292/292, shifted 104/104 모두 배관 축 아래다. 두 조건에 같은 위치 단서가 남는다.", "- metadata의 경계 soft는 wet/tracer 0.35, insulation_damage 0.07로 각각 고정이다. 형태·경계 정보와 클래스가 함께 설계되어 있다.", "- insulation_damage GT 픽셀은 train 36.815%, shifted 51.949%가 전처리 범위 밖이다. 프레임 전체 평균 클리핑만 보면 작은 결함 영역의 정보 손실을 과소평가한다.", "- steam_leak 이미지의 medium은 train steam 97 / condensate 78 / traced 61, shifted steam 29 / condensate 22 / traced 21이다. 클래스명을 실제 가스 누출 검증으로 해석할 수 없다.", "- 클래스 GT 면적이 100 px 미만인 이미지-클래스는 train damage 1건, shifted damage 1건뿐이다. 이는 개별 결함 크기 분포가 아니며 같은 클래스 여러 결함은 합산된다.", "- 위치·형태 단서로 클래스를 구별할 수 있다는 진단은 현재 YOLO가 실제로 그 단서에 의존한다는 인과 증명이 아니다. 위치/형태를 균형화한 별도 조건에서 학습 모델을 재평가해야 그 의존성을 시험할 수 있다.", "", "전체 분포·클래스별 medium/jacket·GT 작은 영역/경계 접촉·endpoint·혼동행렬은 thermal-bias.json, 이미지별 원시 통계는 thermal-bias.csv에 있다.", "", "검증: 1300 image + 1300 mask decode, shape/dtype/class value, split coverage/disjointness, GT/metadata class presence, 각 프레임·집합의 pixel count 합계를 assert했다. CSV 1300행 및 JSON 산술 재검증은 별도 수행한다."]
    (args.output / "thermal-bias.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"images": len(rows), "metadata_defects": len(defects), "output": str(args.output)}))


if __name__ == "__main__":
    main()
