"""Read-only, bounded v3 archive audit; write summaries, never extract or train.

Requires NumPy and Pillow. Input hashes exclude masks/labels so differing labels
cannot hide identical model inputs. ID overlap and actual sample overlap differ.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import itertools
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from zipfile import ZipFile

import numpy as np
from PIL import Image


def sha(data):
    return hashlib.sha256(data).hexdigest()


def file_sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def rows(archive, name):
    return list(csv.DictReader(io.StringIO(archive.read(name).decode("utf-8-sig"))))


def counts(values):
    return dict(sorted(Counter(values).items()))


def numeric_range(values):
    array = np.asarray(list(values), dtype=np.float64)
    return {"min": float(array.min()), "median": float(np.median(array)),
            "max": float(array.max())} if array.size else None


def overlap(first, second):
    shared = set(first) & set(second)
    return {"count": len(shared), "examples": sorted(shared)[:5]}


def image_audit(archive, modality, all_records):
    result = {}
    condition_jobs = {}
    for condition in ("train", "shifted"):
        prefix = f"{modality}/{condition}"
        raw = json.loads(archive.read(f"{prefix}/jobs.json"))
        jobs = raw["jobs"] if isinstance(raw, dict) else raw
        by_id = {job["job_id"]: job for job in jobs}
        condition_jobs[condition] = by_id
        assert len(by_id) == len(jobs), "Duplicate job IDs within condition"
        split_ids = {
            split: [Path(line).stem for line in archive.read(f"{prefix}/{split}.txt")
                    .decode().splitlines() if line.strip()]
            for split in ("train", "val")}
        assert not set(split_ids["train"]) & set(split_ids["val"])
        assert set(split_ids["train"]) | set(split_ids["val"]) == set(by_id)
        assert sum(map(len, split_ids.values())) == len(jobs)
        summary = {"jobs": len(jobs), "job_fields": sorted(jobs[0]),
                   "negative_metadata": sum(job["negative"] for job in jobs),
                   "defect_kinds": counts(d["kind"] for j in jobs for d in j["defects"]),
                   "class_ids_metadata": counts(str(d["class_id"]) for j in jobs for d in j["defects"]),
                   "defect_kind_class_mapping": {
                       kind: sorted({d["class_id"] for j in jobs for d in j["defects"] if d["kind"] == kind})
                       for kind in sorted({d["kind"] for j in jobs for d in j["defects"]})},
                   "dataset_yaml": archive.read(f"{prefix}/dataset.yaml").decode(),
                   "splits": {}}
        if modality == "thermal":
            summary.update({
                "media": counts(j["seg"]["medium"] for j in jobs),
                "physical_segment_temperature_c": numeric_range(j["seg"]["temp_c"] for j in jobs),
                "insulated": counts(str(j["seg"]["insulated"]) for j in jobs),
                "seg_fields": sorted(jobs[0]["seg"]),
                "defect_fields": sorted({k for j in jobs for d in j["defects"] for k in d}),
                "has_crack_or_wall_loss_labels": any(
                    d["kind"] in ("crack", "wall_loss", "internal_pitting", "external_corrosion", "cui")
                    for j in jobs for d in j["defects"]),
            })
        for split, ids in split_ids.items():
            recs, shapes, dtypes, labels, mask_counts = [], Counter(), Counter(), Counter(), Counter()
            normal_masks = 0
            lo, hi, clipped, pixels = float("inf"), float("-inf"), 0, 0
            for job_id in ids:
                job = by_id[job_id]
                extension = "png" if modality == "thermal" else "jpg"
                encoded = archive.read(f"{prefix}/images/{job_id}.{extension}")
                with Image.open(io.BytesIO(encoded)) as image:
                    array = np.asarray(image)
                    shapes[str(array.shape)] += 1
                    dtypes[str(array.dtype)] += 1
                    decoded_sha = sha(str((array.shape, array.dtype)).encode() + array.tobytes())
                    if modality == "thermal":
                        # Existing training conversion clips -40..200 C; original data are retained.
                        lo, hi = min(lo, int(array.min())), max(hi, int(array.max()))
                        clipped += int(((array < 1000) | (array > 25000)).sum())
                        pixels += array.size
                with Image.open(io.BytesIO(archive.read(f"{prefix}/masks/{job_id}.png"))) as mask:
                    mask_array = np.asarray(mask)
                    histogram = np.bincount(mask_array.ravel(), minlength=4)
                    unique = np.flatnonzero(histogram)
                    mask_counts.update({str(int(k)): int(histogram[k]) for k in unique})
                    normal_masks += int(not np.any(mask_array))
                    assert mask_array.shape == array.shape[:2]
                    assert set(unique) <= {0, 1, 2, 3}
                for line in archive.read(f"{prefix}/labels/{job_id}.txt").decode().splitlines():
                    tokens = line.split()
                    if not tokens:
                        continue
                    assert int(tokens[0]) in (0, 1, 2)
                    coords = np.asarray(tokens[1:], dtype=float)
                    assert coords.size >= 6 and coords.size % 2 == 0
                    assert np.isfinite(coords).all() and ((coords >= 0) & (coords <= 1)).all()
                    labels[tokens[0]] += 1
                recs.append({"id": job_id, "segment": job["segment_id"],
                             "defects": [d["defect_id"] for d in job["defects"] if "defect_id" in d],
                             "encoded_sha": sha(encoded), "decoded_sha": decoded_sha,
                             "metadata_sha": sha(json.dumps(job, sort_keys=True).encode())})
            key = f"{modality}/{condition}/{split}"
            all_records[key] = recs
            stat = {"n": len(recs), "image_shapes": dict(shapes), "image_dtypes": dict(dtypes),
                    "normal_masks": normal_masks, "yolo_instances_by_class": dict(labels),
                    "mask_pixels_by_class": dict(mask_counts),
                    "unique_segments": len({r["segment"] for r in recs}),
                    "duplicate_encoded_inputs": len(recs) - len({r["encoded_sha"] for r in recs}),
                    "duplicate_decoded_inputs": len(recs) - len({r["decoded_sha"] for r in recs})}
            if modality == "thermal":
                stat["apparent_temperature_c_range"] = [lo / 100 - 50, hi / 100 - 50]
                stat["pixels_outside_existing_training_range"] = clipped
                stat["total_pixels"] = pixels
            summary["splits"][split] = stat
        result[condition] = summary
    first, second = condition_jobs["train"], condition_jobs["shifted"]
    shared = set(first) & set(second)
    scene_key = "seg" if modality == "thermal" else "pipe"
    result["cross_condition_id_reuse"] = {
        "same_job_id_count": len(shared),
        "same_id_same_segment_string": sum(first[k]["segment_id"] == second[k]["segment_id"] for k in shared),
        "same_id_same_pipe_metadata": sum(first[k][scene_key] == second[k][scene_key] for k in shared),
        "same_id_same_defects": sum(first[k]["defects"] == second[k]["defects"] for k in shared),
        "interpretation": "IDs are local to each condition; matching bare IDs alone is not correspondence."}
    return result


def ut_audit(archive):
    result, hashes = {}, {}
    for condition in ("train", "shifted"):
        prefix = f"ut/{condition}"
        labels = rows(archive, f"{prefix}/ut_labels.csv")
        arrays, schemas = {}, {}
        for mode in ("angle", "straight"):
            with np.load(io.BytesIO(archive.read(f"{prefix}/ut_{mode}.npz")), allow_pickle=False) as data:
                assert data.files == ["signals"]
                array = data["signals"]
            assert array.shape == (len(labels), 4096)
            arrays[mode] = array
            schemas[mode] = {"shape": list(array.shape), "dtype": str(array.dtype),
                             "nonfinite_count": int((~np.isfinite(array)).sum())}
            hashes[f"{condition}/{mode}"] = [sha(row.tobytes()) for row in array]
        hashes[f"{condition}/pair"] = [
            sha(a.tobytes() + b.tobytes()) for a, b in zip(arrays["angle"], arrays["straight"])]
        result[condition] = {
            "rows": len(labels), "columns": list(labels[0]), "arrays": schemas,
            "crack_true": sum(r["crack"] == "True" for r in labels),
            "pit_depth_positive": sum(float(r["pit_depth_mm"]) > 0 for r in labels),
            "both_crack_and_pit": sum(r["crack"] == "True" and float(r["pit_depth_mm"]) > 0 for r in labels),
            "ranges": {k: numeric_range(float(r[k]) for r in labels)
                       for k in ("wall_mm", "t_min_mm", "crack_height_mm", "temp_c", "coupling")},
            "thickness_equation_max_abs_error": max(abs(float(r["wall_mm"]) - float(r["pit_depth_mm"]) - float(r["t_min_mm"])) for r in labels),
            "location_or_pairing_id_columns": [k for k in labels[0] if "id" in k or "time" in k],
            "duplicate_input_pairs": len(labels) - len(set(hashes[f"{condition}/pair"]))}
    result["cross_condition_input_overlap"] = {
        mode: overlap(hashes[f"train/{mode}"], hashes[f"shifted/{mode}"])
        for mode in ("angle", "straight", "pair")}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    root, out = args.data_root.resolve(), args.output_dir.resolve()
    assert root != out and root not in out.parents, "Output must be outside input dataset"
    report = {"schema_version": 1, "created_utc": datetime.now(UTC).isoformat(),
              "audit_script_sha256": file_sha(Path(__file__)), "data_root": str(root),
              "method": "All four ZIPs CRC checked; all 3700 input images decoded and encoded/decoded SHA256 compared; all 26000 UT signal rows hashed input-only; no extraction/training.",
              "archives": {}}
    all_records = {}
    for modality in ("network-strategy", "thermal", "camera", "ut"):
        path = root / f"maek-{modality}.zip"
        with ZipFile(path) as archive:
            members = archive.infolist()
            assert len(members) < 20000 and sum(m.file_size for m in members) < 2_000_000_000
            assert archive.testzip() is None, "ZIP CRC failure"
            report["archives"][modality] = {
                "filename": path.name, "bytes": path.stat().st_size, "sha256": file_sha(path),
                "crc": "passed", "files": sum(not m.is_dir() for m in members)}
            if modality in ("thermal", "camera"):
                report[modality] = image_audit(archive, modality, all_records)
            elif modality == "ut":
                report["ut"] = ut_audit(archive)
            else:
                tables = {n: rows(archive, n) for n in archive.namelist() if n.endswith(".csv")}
                segments = tables["network/segments.csv"]
                defects = tables["network/defects.csv"]
                report["network"] = {
                    "tables": {n: {"rows": len(r), "columns": list(r[0])} for n, r in tables.items()},
                    "media": counts(s["medium"] for s in segments),
                    "defect_kinds": counts(d["kind"] for d in defects),
                    "critical_defects": sum(d["critical"] == "True" for d in defects),
                    "manifest": json.loads(archive.read("manifest.json")),
                    "replacement_character_counts": {
                        n: archive.read(n).decode("utf-8-sig").count("\ufffd")
                        for n in ("DATA_CARD.md", "network/segments.csv")}}
        print(f"Audited {path.name}", flush=True)
    comparisons = {}
    for (ka, a), (kb, b) in itertools.combinations(all_records.items(), 2):
        if ka.split("/")[0] != kb.split("/")[0]:
            continue
        comparisons[f"{ka} vs {kb}"] = {
            "encoded_input": overlap((r["encoded_sha"] for r in a), (r["encoded_sha"] for r in b)),
            "decoded_input": overlap((r["decoded_sha"] for r in a), (r["decoded_sha"] for r in b)),
            "segment_id": overlap((r["segment"] for r in a), (r["segment"] for r in b)),
            "defect_id": overlap((d for r in a for d in r["defects"]), (d for r in b for d in r["defects"])),
        }
    report["image_split_overlap"] = comparisons
    camera = [r for k, rs in all_records.items() if k.startswith("camera/") for r in rs]
    thermal = [r for k, rs in all_records.items() if k.startswith("thermal/") for r in rs]
    report["cross_modality"] = {
        "camera_thermal_segment_overlap": overlap((r["segment"] for r in camera), (r["segment"] for r in thermal)),
        "camera_segments_missing_from_network": len({r["segment"] for r in camera} - {s["segment_id"] for s in segments}),
        "thermal_segments_matching_network": len({r["segment"] for r in thermal} & {s["segment_id"] for s in segments}),
        "ut_location_ids": "Absent: angle/straight/labels are row-paired only; no link to image/network physical locations.",
        "thermal_condition_ids": "IRS and ir identifiers restart in each condition. Same identifier is not the same physical scene.",
        "joint_four_case_defect_observation_dataset": "absent; cannot establish thermal-cue versus confirmed crack/wall-loss four-case coverage"}
    report["disposition"] = {
        "thermal": "Retain only as steam/insulation observation subtask; retire as gas-pipe crack/wall-loss training or validation evidence.",
        "camera": "Retain visible corrosion/CUI-sign/leak-stain simulation; shifted reuses underlying network segments/defects, so not independent asset holdout.",
        "ut": "Relevant synthetic crack/thickness waveform task, not thermal labels and not paired gas-pipe field evidence.",
        "network_strategy": "Retain assumptions-based simulation; no actual sensor-to-defect paired trial or measured cost/safety evidence.",
        "limitations": "Exact hashes do not detect all near-duplicates. Archive metadata cannot validate physical realism. No real inspection labels, temporal sequences, gas-specific sensor coverage or external site holdout established."}
    out.mkdir(parents=True, exist_ok=True)
    (out / "archive-audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# MAEK v3 archive audit", "", "All ZIPs were read without extraction or modification.", "",
             "| Modality | train condition | shifted condition | Labels |", "|---|---:|---:|---|",
             f"| Thermal | {report['thermal']['train']['jobs']} | {report['thermal']['shifted']['jobs']} | wet_insulation, insulation_damage, steam_leak |",
             f"| RGB | {report['camera']['train']['jobs']} | {report['camera']['shifted']['jobs']} | corrosion, cui_sign, leak_stain |",
             "| UT | 10000 | 3000 | crack/height, nominal/minimum thickness, pit depth |", "",
             "Thermal images are uint16 (256, 320), RGB uint8 (640, 640, 3); UT inputs are two float16 (N, 4096) arrays.", "",
             "Thermal media counts (train / shifted):", "",
             json.dumps({c: report['thermal'][c]['media'] for c in ('train', 'shifted')}, ensure_ascii=False), "",
             "## Split integrity", "", "| Pair | Exact input bytes | Decoded inputs | Segment IDs | Defect IDs |", "|---|---:|---:|---:|---:|"]
    for name, comp in comparisons.items():
        lines.append(f"| {name} | {comp['encoded_input']['count']} | {comp['decoded_input']['count']} | {comp['segment_id']['count']} | {comp['defect_id']['count']} |")
    lines += ["", "Thermal cross-condition ID reuse represents independently sampled scenes, not verified physical pairing. RGB cross-condition segment/defect overlap represents shared network assets; within-condition train/val segment grouping remains distinct.", "", "## Purpose fit and pairing", ""]
    lines += [f"- **{k}**: {v}" for k, v in report["disposition"].items()]
    lines += ["", "Thermal/network matching segments: " + str(report['cross_modality']['thermal_segments_matching_network']) + ". UT has no location ID. Consequently these modalities cannot be joined into corresponding thermal/RGB/UT crack-and-wall-loss examples by row index or recycled IDs.", "", "Full counts, schemas, ranges, clipping, hashes, overlaps and checks are in [archive-audit.json](archive-audit.json).", ""]
    (out / "archive-audit.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"status": "audit_complete", "output": str(out / 'archive-audit.json')}))


if __name__ == "__main__":
    main()
