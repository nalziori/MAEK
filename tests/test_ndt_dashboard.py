import json

import numpy as np
import pytest

from maek import params, ut
from maek.ndt_dashboard import analyse


def sample(mode='straight'):
    cfg = params.load_config()
    signal = (ut.simulate_straight(cfg, np.random.default_rng(19), 8, n_avg=16)
              if mode == 'straight' else ut.simulate_angle(cfg, np.random.default_rng(19), 8, 1))
    return {'mode': mode, 'signal': signal.tolist(), 'wall_nominal_mm': 8, 'temp_c': 20,
                'sampling_mhz': 100, 'probe_freq_mhz': 5, 'interface_delay_us': 1, 'n_avg': 16, 'angle_deg': 60}


def test_frozen_ut_prediction():
    result, image = analyse(json.dumps(sample()).encode())
    assert abs(result['thickness_mm']-8) < .2
    assert result['pit_candidate'] is False
    assert image.shape == (180,640,3)
    result, _ = analyse(json.dumps(sample('angle')).encode())
    assert result['crack_candidate'] is True


def test_unknown_or_mismatched_waveforms_are_not_normal():
    value = sample()
    value['sampling_mhz'] = 50
    with pytest.raises(ValueError): analyse(json.dumps(value).encode())
    value = sample()
    value['signal'] = [0]*4096
    with pytest.raises(ValueError): analyse(json.dumps(value).encode())
