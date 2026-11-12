"""Adapter for the existing, frozen synthetic UT analyzers."""
import json

import numpy as np
from PIL import Image, ImageDraw

from maek import params, pit, ut


def analyse(raw):
    value = json.loads(raw)
    cfg = params.load_config()
    mode = value['mode']
    if mode not in ('straight', 'angle'):
        raise ValueError('mode는 straight 또는 angle이어야 합니다')
    signal = np.asarray(value['signal'], dtype=float)
    if signal.shape != (params.get(cfg, 'ut.n_samples'),) or not np.isfinite(signal).all() or not np.any(signal):
        raise ValueError('유한한 비영 A-scan 4096개가 필요합니다')
    for field in ('sampling_mhz', 'probe_freq_mhz', 'interface_delay_us'):
        if float(value[field]) != params.get(cfg, 'ut.' + field):
            raise ValueError(f'{field}: 교정 설정이 현재 모델과 다릅니다')
    wall, temp = float(value['wall_nominal_mm']), float(value['temp_c'])
    if not np.isfinite([wall, temp]).all() or not 2 <= wall <= 20 or not -20 <= temp <= 150:
        raise ValueError('지원 입력 범위: 공칭 두께2~20mm, 온도-20~150°C')
    output = {'model': 'UT baseline + frozen pit MLP', 'field_validated': False,
        'quality_status': '합성 학습 모델 · 실제 탐촉자 교정/검토 필요', 'regions': [], 'width': 640, 'height': 180}
    if mode == 'straight':
        n_avg = value['n_avg']
        model = pit.load_shipped().get('learned')
        if not model or model['fingerprint'] != pit._fingerprint(cfg):
            raise ValueError('피팅 모델과 설정의 해시가 다릅니다. 재학습 없이 판독 보류합니다')
        if n_avg not in model['n_avg_choices']:
            raise ValueError('평균 횟수가 학습 모델의 지원 범위와 다릅니다')
        thickness = ut.estimate_thickness(cfg, signal, temp)
        result = pit.detect_pit(cfg, signal, wall, temp, method='learned', model=model, n_avg=n_avg)
        if not np.isfinite(thickness) or not 0 < thickness <= 25:
            raise ValueError('유효한 저면 두께 에코를 확인하지 못했습니다')
        output.update(thickness_mm=thickness, pit_candidate=bool(result['found']),
            pit_depth_est_mm=float(result['depth_est_mm']) if result['found'] else None,
            pit_score=float(result['score']),
            analysis_summary=f'두께 추정 {thickness:.2f}mm · 피팅 후보 ' + ('관측' if result['found'] else '미검출'))
        found = result['found']
    else:
        angle = float(value['angle_deg'])
        if angle not in params.get(cfg, 'ut.angle_beam_angles_deg'):
            raise ValueError('지원 사각: 45/60/70도')
        result = ut.detect_crack(cfg, signal, wall, angle, temp)
        found = result['found']
        output.update(crack_candidate=bool(found), crack_score=float(result['score']),
            analysis_summary='균열 에코 후보 ' + ('관측' if found else '미검출'))
    output['assessment_status'] = 'candidate_observed' if found else 'no_candidate_observed'
    image = Image.new('RGB', (640, 180), '#f6f8f9')
    draw = ImageDraw.Draw(image)
    draw.line((30, 85, 630, 85), fill='#bac4cc')
    scale = max(float(np.max(np.abs(signal))), 1e-9)
    indices = np.linspace(0, len(signal)-1, 600).astype(int)
    draw.line([(30+i, 85-float(signal[j])/scale*65) for i,j in enumerate(indices)], fill='#126b8b', width=1)
    draw.text((30, 155), f'A-scan / {mode} / 0 - {len(signal)/value["sampling_mhz"]:.2f} us', fill='#263442')
    return output, np.array(image)
