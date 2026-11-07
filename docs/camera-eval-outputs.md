# Camera eval output files (for the dashboard / report)

`scripts/eval_camera_seg.py --out DIR` writes the files below. Every model run (HSV, E0, E2, E3 ...) has
the same columns, so the dashboard only needs to read one folder per run.

## summary.csv: one row per class (corrosion, cui_sign, leak_stain)

| column | meaning |
|---|---|
| n_defects | number of visible defects of this class (fewer than 4 visible pixels are skipped) |
| hit_rate | **headline number**: fraction of defects whose own pixels are at least 30 % (`eval.seg_hit_recall`) predicted as the **same class** |
| hit_rate_any_class | same, but any defect class counts (found it, possibly mislabelled) |
| image_detect | fraction of images containing the class where at least 30 px (`eval.seg_min_pred_px`) are predicted as it |
| false_alarm | fraction of images **without** the class where at least 30 px are predicted as it |
| pixel_iou | pixel IoU of the class over the whole set |
| a90_cm2, pod_status | area at 90 % POD from the logistic POD fit, and whether the fit is usable (`ok`, `no_trend`, ...) |

## defects.csv: one row per defect

`job_id, k, class, area_cm2, n_px, recall, recall_any_class, hit, contrast, brightness, dust, steam,
blur_sigma, noise_sigma`. `contrast` is the colour distance between the defect and a 6 px ring around
it, in units of ring noise; below about 0.3, a defect is hard to see even for a person.

## The other outputs

- `images.csv`: one row per image, with the environment values, `gt_<class>` flags, and `pred_px_<class>` counts.
- `by_condition.csv`: hit rate per class, broken down by quartile of each environment factor (`factor`, `bin`, `hit_rate`, `n`).
- `summary.json`: the run arguments plus the summary rows.
- `pred/<job_id>.png` (written only with `--save-pred`): the predicted mask, using classes 0–3 like `masks/`. This is the input to `scripts/failure_grid.py`.

Seeds: data-v3 train 1, data-v3 shifted 101 (final test, used once), DR train 11, DR val 12 (model selection).
