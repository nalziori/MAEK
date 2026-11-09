import pytest

from maek.onboard_models import summarize


def test_summary_uses_wall_time_and_interpolated_percentile():
    result = summarize([1, 2, 3, 4], 0.01, 1500)
    assert result['p50_ms'] == 2.5
    assert result['p95_ms'] == pytest.approx(3.85)
    assert result['throughput_per_s'] == 400
    assert result['pass_p95_200ms']
    assert result['pass_memory_2gib']


@pytest.mark.parametrize('latencies,elapsed', [([], 1), ([0], 1), ([float('nan')], 1),
                                             ([1], 0), ([1], float('inf'))])
def test_invalid_timing_rejected(latencies, elapsed):
    with pytest.raises(ValueError):
        summarize(latencies, elapsed, None)


def test_missing_memory_is_not_zero():
    assert summarize([1], 1, None)['pass_memory_2gib'] is None
