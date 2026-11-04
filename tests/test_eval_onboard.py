import copy

import numpy as np
import pytest

from maek import evaluate, onboard, params
from maek.camera import segment


@pytest.fixture(scope="module")
def cfg():
    return copy.deepcopy(params.load_config())


def _in01(x):
    return 0.0 <= x <= 1.0 or np.isnan(x)


def test_segmenter_finds_orange_patch():
    img = np.full((64, 64, 3), 100, np.uint8)
    img[20:40, 20:40] = (200, 100, 32)
    m = segment.segment_rust(img)
    assert m[30, 30] and not m[2, 2]


def test_eval_camera_tiny_metrics_in_range(cfg):
    for cond in ("train", "shifted"):
        r = evaluate.eval_camera(cfg, cond, 12, seed=1, size=160)
        for k in ("pixel_iou", "detection_rate", "false_alarm_rate"):
            assert _in01(r[k])
        assert r["pod"]["status"] in ("ok", "all_hit", "all_miss", "too_few", "no_trend", "beyond_range")


def test_eval_ut_tiny_metrics_in_range(cfg):
    c = evaluate._with(cfg, "ut.n_samples", 2048)
    for cond in ("train", "shifted"):
        r = evaluate.eval_ut(c, cond, 40, seed=2)
        for k in ("crack_detection_rate", "crack_false_alarm_rate", "thickness_within_t1",
                  "thickness_within_t2", "pit_detection_rate", "pit_false_alarm_rate"):
            assert _in01(r[k]), k
        assert r["thickness_within_t1"] <= r["thickness_within_t2"]
        assert r["thickness_mae_mm"] >= 0


def test_pod_summary_degenerate_and_ok():
    s = np.linspace(0.5, 5, 40)
    assert evaluate.pod_summary(s, np.ones(40))["status"] == "all_hit"
    hits = (s > 2.0).astype(float)
    hits[[3, 30]] = 1 - hits[[3, 30]]
    p = evaluate.pod_summary(s, hits, n_boot=20)
    assert p["status"] == "ok" and 0 < p["a90"] < 10


def test_shifted_jobs_are_harder_and_train_unchanged(cfg):
    from maek import network
    from maek.camera import jobs

    seg, _, dfx = network.generate_network(cfg, 0, total_km=5)
    a = jobs.make_jobs(cfg, seg, dfx, 10, 0)
    b = jobs.make_jobs(cfg, seg, dfx, 10, 0, "shifted")
    assert np.mean([j["env"]["brightness"] for j in b]) < np.mean([j["env"]["brightness"]
                                                                   for j in a])


def test_onboard_measure_positive(cfg):
    r = onboard.measure(lambda x: x * 2, list(range(10)))
    assert r["median_ms"] > 0 and r["p95_ms"] >= r["median_ms"] and r["throughput_per_s"] > 0
    rows = onboard.run_benchmark(evaluate._with(cfg, "ut.n_samples", 2048), sizes=[96],
                                 n_images=4, n_ut=6)
    assert {r["function"] for r in rows} == {"corrosion_segment", "crack_detect", "thickness"}
    assert all(r["median_ms"] > 0 and r["tracemalloc_peak_mb"] >= 0 for r in rows)


def test_onboard_run_all_uses_callers_config_seed_and_sizes(cfg, tmp_path):
    c = evaluate._with(cfg, "ut.n_samples", 2048)
    c = evaluate._with(c, "onboard.bench_image_sizes", [80])
    df = onboard.run_all(c, tmp_path, threads=[1], seed=3, n_images=3, n_ut=4,
                         config_label="custom.yaml")
    seg = df[df["function"] == "corrosion_segment"]
    assert list(seg["input"]) == ["80x80px"]
    assert set(df["config"]) == {"custom.yaml"} and set(df["seed"]) == {3}
    assert (tmp_path / "onboard_config.yaml").exists()
    assert "custom.yaml" in (tmp_path / "onboard.csv").read_text()
    df2 = onboard.run_all(c, tmp_path, threads=[1], sizes=[64], n_images=3, n_ut=4)
    assert list(df2[df2["function"] == "corrosion_segment"]["input"]) == ["64x64px"]


def test_with_helper_is_single_source():
    assert not hasattr(onboard, "_with_size")
    assert onboard._with is evaluate._with
