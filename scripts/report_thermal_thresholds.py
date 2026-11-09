"""Render frozen threshold-loop evidence without importing or running inference."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

CLASSES = ('wet_insulation', 'insulation_damage', 'steam_leak')
SPLITS = ('diagnostic_val', 'diagnostic_shifted', 'selection_shifted',
          'selection_train', 'confirmation_shifted', 'confirmation_train')
OUTPUTS = ('report.md', 'threshold-comparison.csv', 'errors.csv',
           'transition-ledger.csv', 'feature-bins.csv', 'normal-error-groups.csv')
CATEGORIES = {
    'baseline_hit': '기준 성공',
    'matching_coverage_below_baseline_confidence': '기준 점수 미만의 같은 클래스 마스크',
    'cross_class_overlap_ownership': '타 클래스의 픽셀 소유권',
    'other_class_overlap_at_cache_floor': '타 클래스의 충분한 겹침',
    'insufficient_same_class_mask_coverage': '같은 클래스 마스크 겹침 부족',
    'no_same_class_overlap_at_cache_floor': '캐시 바닥에서 같은 클래스 겹침 없음',
}


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def pct(value):
    return 'NA' if value is None else f'{value * 100:.2f}%'


def number(value):
    return 'NA' if value is None else f'{value:.4f}'


def macro(row):
    values = [row['classes'][c]['image_recall'] for c in CLASSES]
    return sum(values) / 3 if all(v is not None for v in values) else None


def mean_iou(row):
    values = [row['classes'][c]['iou'] for c in CLASSES]
    return sum(values) / 3 if all(v is not None for v in values) else None


def first_table(text):
    lines, found = [], False
    for line in text.splitlines():
        if line.startswith('|'):
            found = True
            lines.append(line)
        elif found:
            break
    if len(lines) < 8:
        raise ValueError('Judge leaderboard must contain all six proposals')
    return '\n'.join(lines)


def borrowed_footer(text):
    marker = '## 가져온 부분 장부'
    if marker not in text:
        raise ValueError('Judge borrowed-parts ledger missing')
    return text[text.index(marker):].strip()


def write_csv(path, rows, minimum_fields):
    fields = list(minimum_fields)
    for row in rows:
        fields.extend(k for k in row if k not in fields)
    with Path(path).open('x', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: compact(v) if isinstance(v, (dict, list)) else v
                             for k, v in row.items()})


def transition_counts(data, name, base):
    value = data['transitions'].get(name, {}) if name != base else {}
    return (len(value.get('new_normal_alarms', [])),
            sum(map(len, value.get('lost_hits', {}).values())),
            sum(map(len, value.get('gained_hits', {}).values())))


def comparison_rows(protocol, splits):
    rows = []
    base = protocol['baseline']
    for split, data in splits.items():
        for name, metric in data['results'].items():
            new, lost, gained = transition_counts(data, name, base)
            change = data['changes'].get(name, {})
            row = {'split': split, 'configuration': name,
                   'wet_threshold': protocol['grid'][name][0],
                   'damage_threshold': protocol['grid'][name][1],
                   'steam_threshold': protocol['grid'][name][2],
                   'image_count': metric['image_count'], 'macro_recall': macro(metric),
                   'macro_pooled_iou': mean_iou(metric),
                   'normal_false_alarms': metric['normal_false_alarms'],
                   'normal_images': metric['normal_images'],
                   'normal_fa_rate': metric['normal_image_false_alarm_rate'],
                   'normal_fa_wilson95': metric['normal_image_false_alarm_ci95'],
                   'new_normal_alarms': new, 'lost_class_hits': lost, 'gained_class_hits': gained,
                   'macro_recall_paired_change': change.get('macro_recall_change'),
                   'normal_fa_paired_reduction': change.get('fa_reduction')}
            for cls in CLASSES:
                row.update({f'{cls}_{k}': v for k, v in metric['classes'][cls].items()})
                row[f'{cls}_fp_per_image'] = metric['class_fp_per_image'][cls]
                row[f'{cls}_paired_recall_change'] = change.get('per_class_recall_change', {}).get(cls)
            rows.append(row)
    return rows


def detail_rows(splits):
    errors, ledger, bins = [], [], []
    for split, data in splits.items():
        for item in data['error_rows']:
            row = {'split': split}
            for key, value in item.items():
                if key in ('features', 'scene'):
                    row.update({f'{key}_{k}': v for k, v in value.items()})
                else:
                    row[key] = value
            errors.append(row)
        for name, values in data['transitions'].items():
            for kind in ('new_normal_alarms', 'resolved_normal_alarms'):
                ledger.extend({'split': split, 'configuration': name, 'transition': kind,
                               'class': '', 'sample_id': sample_id} for sample_id in values[kind])
            for kind in ('gained_hits', 'lost_hits'):
                for cls, ids in values[kind].items():
                    ledger.extend({'split': split, 'configuration': name, 'transition': kind,
                                   'class': cls, 'sample_id': sample_id} for sample_id in ids)
        bins.extend({'split': split, **item} for item in data['error_summary']['groups'])
        # Report-only descriptive contrast strata, never used by selection.
        groups = defaultdict(list)
        for row in data['error_rows']:
            contrast = row['features'].get('local_contrast_c')
            label = ('unknown' if contrast is None else '<2' if abs(contrast) < 2 else
                     '[2,5)' if abs(contrast) < 5 else '>=5')
            groups[('absolute_local_contrast_c', label)].append(row)
            groups[(f'class_{row["class_id"]}_absolute_local_contrast_c', label)].append(row)
        scopes = ['absolute_local_contrast_c', *[f'class_{c}_absolute_local_contrast_c' for c in (1, 2, 3)]]
        for scope in scopes:
            for label in ('<2', '[2,5)', '>=5', 'unknown'):
                items = groups[(scope, label)]
                bins.append({'split': split, 'scope': scope, 'bin': label, 'n': len(items),
                             'baseline_hits': sum(r['baseline_hit'] for r in items),
                             'baseline_denominator': len(items),
                             'any_grid_hits': sum(r['any_grid_hit'] for r in items),
                             'any_grid_denominator': len(items),
                             'categories': dict(Counter(r['category'] for r in items)),
                             'low_denominator': len(items) < 20,
                             'note': 'report-only descriptive bins; no selection use'})
    return errors, ledger, bins


def rank(protocol, result, name):
    metric = result['results'][name]
    return (-(macro(metric) if macro(metric) is not None else -math.inf),
            metric['normal_image_false_alarm_rate'] if metric['normal_images'] else math.inf,
            -(mean_iou(metric) if mean_iou(metric) is not None else -math.inf),
            sum(abs(t - .25) for t in protocol['grid'][name]), name)


def normal_groups(splits, base):
    """Join aligned image metadata/outcomes; overlapping hard tags are non-additive."""
    rows = []
    for split, data in splits.items():
        images, ids = data['image_rows'], data['ids']
        if len(images) != len(ids) or any(r['sample_id'] != sid for r, sid in zip(images, ids, strict=True)):
            raise ValueError(f'Image feature/sample ID alignment differs: {split}')
        baseline = data['results'][base]['sample_outcomes']
        for name, metric in data['results'].items():
            outcomes = metric['sample_outcomes']
            if len(outcomes) != len(images) or len(baseline) != len(images):
                raise ValueError(f'Outcome count differs: {split}/{name}')
            groups = {('all', 'all'): []}
            for image, outcome, old in zip(images, outcomes, baseline, strict=True):
                if bool(image['normal']) != bool(outcome['normal']) or bool(old['normal']) != bool(outcome['normal']):
                    raise ValueError(f'Normal labels disagree: {split}/{name}')
                if not image['normal']:
                    continue
                feature = image['features']
                tags = sorted(set(feature['hard'])) or ['none']
                clip = feature['input_clip_fraction']
                clip_bin = '0' if clip == 0 else '(0,.1]' if clip <= .1 else '>.1'
                keys = [('all', 'all'), *[('hard', tag) for tag in tags],
                        ('jacket', feature.get('jacket') or 'unknown'), ('input_clip_fraction', clip_bin)]
                value = (image['sample_id'], bool(outcome['alarm']), bool(old['alarm']), clip)
                for key in keys:
                    groups.setdefault(key, []).append(value)
            all_normal = groups[('all', 'all')]
            if len(all_normal) != metric['normal_images'] or sum(v[1] for v in all_normal) != metric['normal_false_alarms']:
                raise ValueError(f'Normal outcomes/metrics disagree: {split}/{name}')
            for (scope, label), values in sorted(groups.items()):
                alarms = [sid for sid, alarm, _, _ in values if alarm]
                new = [sid for sid, alarm, old, _ in values if alarm and not old]
                resolved = [sid for sid, alarm, old, _ in values if old and not alarm]
                rows.append({'split': split, 'configuration': name, 'scope': scope, 'bin': label,
                             'normal_images': len(values), 'alarms': len(alarms),
                             'alarm_rate': len(alarms) / len(values) if values else None,
                             'new_normal_alarms': len(new), 'resolved_normal_alarms': len(resolved),
                             'input_clip_fraction_median': statistics.median(v[3] for v in values) if values else None,
                             'low_denominator': len(values) < 20,
                             'alarm_ids': alarms, 'new_normal_alarm_ids': new,
                             'resolved_normal_alarm_ids': resolved})
    return rows


def ps_quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def render(out, p, splits, selection, decision, judge, bins, normal):
    base, selected = p['baseline'], selection['selected']
    compare = selected if selected != base else selection['challenger']
    lines = ['# MAEK 고정 30epoch 열화상 임계값 개선 실험', '',
             first_table(judge), '',
             '점수는 정확성/완결성/설계 판단(각 10점)이며 성능 측정 점수가 아니다.', '',
             '## 통합 실험 결과', '',
             (f"선택 단계 결정: **{selected}**. 확인 단계 비교 대상: **{compare}**. "
             f"최종 권고: **{decision['recommended']}**. "
             f"새 합성 확인셋의 개선 확인: **{'통과' if decision['confirmed_improvement'] else '미확인·기준 유지'}**."), '',
             '기본 탐지기 설정과 학습 가중치는 변경하지 않았다. 선택에서 탈락한 최상위 challenger의 확인 결과는 설명용이며 재선택에 사용하지 않는다.', '',
             ('`(wet, damage, steam) ∈ {0.10, 0.25, 0.40}³`: 정확히 27조합. 기준은 `(0.25, 0.25, 0.25)`. '
             'strict `score > threshold`, 클래스별 필터 후 의미 마스크 재합성, confidence 우선·동점 원순서를 유지했다.'), '',
             '| 분할 | 역할 | seed | 이미지 | 정상 | 클래스 양성 wet/damage/steam | 평가 조합 |',
             '|---|---|---:|---:|---:|---|---:|']
    for split, data in splits.items():
        metric = data['results'][base]
        role = '기존·이미 본 진단' if split.startswith('diagnostic') else '새 seed 선택' if split.startswith('selection') else '새 seed 확인'
        den = '/'.join(str(metric['classes'][c]['image_denominator']) for c in CLASSES)
        lines.append(f"| {split} | {role} | {p['splits'][split][0]} | {len(data['ids'])} | {metric['normal_images']} | {den} | {len(data['results'])} |")
    lines += ['', ('기존 진단 488장, 새 선택 360장(shifted240+train분포120), 새 확인 600장(shifted400+train분포200)이다. '
              'train분포는 새로 생성한 표본이며 학습에 다시 사용하지 않았다. 같은 생성기의 새 seed 확인으로, 외부 현장 검증은 아니다.'), '',
              ('유효한 입력은 전부 점수에 포함했다. clipping 때문에 제외하거나 abstention을 추가하지 않았다. '
              '각 분할의 저장된 이미지 수와 프로토콜 수를 대조했다. 필수 분모가 없으면 판단할 수 없다.'), '',
              ('선택/확인 점추정 게이트: 두 분포 모두 기존 개별 클래스 hit 손실 0, 신규 정상 경보 0, 클래스별 FP/이미지 비증가; '
              'shifted macro recall 증가 ≥1%p. 확인은 여기에 shifted paired macro recall 95% CI 하한>0을 요구한다. '
              '순위는 shifted macro recall↓, 정상 FA↑, pooled 평균 IoU↓, 기준과 임계값 거리↑, 이름 순이다. '
              '여기서 ↓는 큰 값 우선, ↑는 작은 값 우선이다.'), '',
              '## 선택 순위 상위 10개와 기준', '',
              '| 순위 | 조합 | macro recall | 기준 대비 %p | 정상 FA | 신규 FA | 잃은/얻은 hit | 평균 pooled IoU | 선택 게이트 |',
              '|---:|---|---:|---:|---|---:|---|---:|---|']
    data = splits['selection_shifted']
    ranked = sorted((n for n in data['results'] if n != base), key=lambda n: rank(p, data, n))
    base_macro = macro(data['results'][base])
    for index, name in [('기준', base), *list(enumerate(ranked[:10], 1))]:
        metric = data['results'][name]
        new, lost, gained = transition_counts(data, name, base)
        gain = None if macro(metric) is None or base_macro is None else (macro(metric) - base_macro) * 100
        status = '기준' if name == base else '통과' if name in selection['eligible'] else '탈락'
        lines.append(f"| {index} | {name} | {pct(macro(metric))} | {number(gain)} | {metric['normal_false_alarms']}/{metric['normal_images']} | {new} | {lost}/{gained} | {pct(mean_iou(metric))} | {status} |")
    lines += ['', ('표의 수치는 selection_shifted이며 게이트는 selection_train도 함께 적용한다. '
              '모든 27×4 진단·선택 결과와 확인 결과는 `threshold-comparison.csv`에 보존했다. '
              '선택 집합의 다중 비교 CI는 탐색적이며 확증적 유의성으로 해석하지 않는다.'), '',
              '## 기준과 확인 비교', '',
              '| 분할 | 조합 | macro recall | wet hit/양성 | damage hit/양성 | steam hit/양성 | 정상 FA/정상 | FA Wilson 95% 상한 |',
              '|---|---|---:|---|---|---|---|---:|']
    for split, data in splits.items():
        names = [base] if compare == base else [base, compare]
        for name in names:
            metric = data['results'][name]
            hit = [f"{metric['classes'][c]['image_hits']}/{metric['classes'][c]['image_denominator']}" for c in CLASSES]
            ci = metric['normal_image_false_alarm_ci95']
            lines.append(f"| {split} | {name} | {pct(macro(metric))} | {' | '.join(hit)} | {metric['normal_false_alarms']}/{metric['normal_images']} | {pct(ci[1] if ci else None)} |")
    lines += ['', ('class-image hit은 해당 정답 클래스 픽셀의 ≥30%를 정확히 분류한 경우다. '
              'FP/이미지는 기존 dilation·연결요소 정의를 유지한다. IoU는 이미지 IoU 평균이 아닌 합산 TP/union으로 계산했다. '
              '정상 FA가 0이어도 위험 0이라는 뜻은 아니며 위 Wilson 상한으로 표본 불확실성을 표시한다.'), '',
              '| 확인 분할 | macro recall 변화 %p | paired 95% CI (%p) | 유효 bootstrap | 신규 정상 경보 | 잃은/얻은 hit |',
              '|---|---:|---|---:|---:|---|']
    for split in SPLITS[-2:]:
        data = splits[split]
        change = data['changes'].get(compare, {}).get('macro_recall_change')
        new, lost, gained = transition_counts(data, compare, base)
        ci = change['ci95'] if change else None
        lines.append(f"| {split} | {number(change['change'] * 100) if change and change['change'] is not None else 'NA'} | "
                     f"{', '.join(number(v * 100) for v in ci) if ci else 'NA'} | {change['bootstrap_valid'] if change else 'NA'} | {new} | {lost}/{gained} |")
    lines += ['', ('동일 이미지의 전후를 묶어 bootstrap 2000회(seed=19) 계산했다. '
              '클래스별 CI와 정상 FA 변화 CI는 비교 CSV에 포함한다. 개별 정상 경보 신규/해소 및 클래스 hit의 획득/손실 ID는 '
              '`transition-ledger.csv`에 기록했다. 이 장부는 이미지 결과 전환이며 인스턴스별 픽셀 소유권 전체 추적을 구현했다고 주장하지 않는다.'), '',
              '## 정상 이미지의 오경보 오류', '',
              '| 선택·확인 분할 | 조합 | 정상 경보/정상 | 신규 정상 경보 | 해소 정상 경보 |',
              '|---|---|---|---:|---:|']
    for row in normal:
        if row['split'] in SPLITS[2:] and row['configuration'] in (base, compare) and row['scope'] == 'all':
            lines.append(f"| {row['split']} | {row['configuration']} | {row['alarms']}/{row['normal_images']} | {row['new_normal_alarms']} | {row['resolved_normal_alarms']} |")
    lines += ['', '| 분할 | 조합 | 정상 hard tag | 경보/정상 | n<20 |',
              '|---|---|---|---|---|']
    for row in normal:
        if row['configuration'] in (base, compare) and row['scope'] == 'hard':
            lines.append(f"| {row['split']} | {row['configuration']} | {row['bin']} | {row['alarms']}/{row['normal_images']} | {'주의' if row['low_denominator'] else ''} |")
    lines += ['', ('정상 이미지의 hard tag·jacket·입력 clipping 특징과 각 조합의 alarm을 저장된 동일 이미지 인덱스로 연결했다. '
              '태그가 없으면 none이며 한 이미지의 여러 hard tag는 중복 집계된다. 태그별 분모를 더해 전체 정상 수로 해석하면 안 된다. '
              '전체 조합의 정상 경보·신규·해소 수와 ID, jacket·clipping 구간은 `normal-error-groups.csv`에 있다. '
              '선택·확인 네 분할의 0건도 위 표와 CSV에 기록했다. 이 역시 관측 연관이며 물리적 원인 판정은 아니다.'), '',
              '## 오류 분류와 임계값으로 가능한 범위', '',
              '| 진단 분할 | 클래스 | 분모 | 기준 hit | 어느 조합이든 hit (oracle) | 오류별 수 |',
              '|---|---|---:|---:|---:|---|']
    for split in SPLITS[:2]:
        for class_id, cls in enumerate(CLASSES, 1):
            rows = [r for r in splits[split]['error_rows'] if r['class_id'] == class_id]
            counts = Counter(r['category'] for r in rows if not r['baseline_hit'])
            errors = '; '.join(f'{CATEGORIES.get(k, k)}={v}' for k, v in sorted(counts.items())) or '없음'
            lines.append(f"| {split} | {cls} | {len(rows)} | {sum(r['baseline_hit'] for r in rows)} | {sum(r['any_grid_hit'] for r in rows)} | {errors} |")
    lines += ['', ('`any_grid_hit`은 이미지×클래스마다 다른 설정을 골랐을 때의 정답 의존 가상 상한이다. '
              '하나의 배포 가능한 탐지기 성능도, 안전 게이트를 동시에 통과한 성능도 아니다. 확인 집합에서는 평가한 두 설정 안에서만 계산했다. '
              '‘캐시 바닥에서 겹침 없음’은 conf>0.10의 NMS 이후 관측이며 원시 제안 부재를 증명하지 않는다. '
              '정답·pipe geometry·환경 정보는 오프라인 오류 설명에만 사용했다.'), '',
              '### 기존 shifted300: 성공·실패의 관측 특징', '',
              '| 클래스 | 기준 결과 | n | signed local contrast 중앙값 °C | 대비 유효 n | GT 면적 중앙값 px | GT clipping 있음 n/N |',
              '|---|---|---:|---:|---:|---:|---|']
    for class_id, cls in enumerate(CLASSES, 1):
        for hit in (True, False):
            rows = [r for r in splits['diagnostic_shifted']['error_rows']
                    if r['class_id'] == class_id and bool(r['baseline_hit']) == hit]
            contrasts = [r['features']['local_contrast_c'] for r in rows
                         if r['features'].get('local_contrast_c') is not None]
            areas = [r['features']['gt_pixels'] for r in rows]
            clipped = sum(r['features']['gt_clip_fraction'] > 0 for r in rows)
            lines.append(f"| {cls} | {'성공' if hit else '실패'} | {len(rows)} | "
                         f"{number(statistics.median(contrasts)) if contrasts else 'NA'} | {len(contrasts)} | "
                         f"{number(statistics.median(areas)) if areas else 'NA'} | {clipped}/{len(rows)} |")
    old = splits['diagnostic_shifted']
    old_best = min(old['results'], key=lambda n: rank(p, old, n))
    old_metric = old['results'][old_best]
    old_gain = macro(old_metric) - macro(old['results'][base])
    lines += ['', (f"이미 본 shifted300의 설명용 최고 순위는 `{old_best}`: macro recall {pct(macro(old_metric))}, "
              f"기준 대비 {old_gain * 100:.4f}%p, 정상 FA {old_metric['normal_false_alarms']}/{old_metric['normal_images']}이다. "
              '이는 기존 진단 데이터의 결과이며 새 독립 성과로 해석하지 않는다.'), '',
              ('성공·실패의 대비, 면적, clipping 차이는 다음 전처리·약한 대비·작은 steam 표본 점검의 가설을 만드는 관측 자료다. '
              '특정 특징이 실패를 일으켰다거나 전처리/재학습으로 개선될 것이라고 확정하지 않는다.'), '',
              '## clipping·대비와 오류의 관측 연관', '',
              '| 진단 분할 | 특징 | 구간 | 이미지×클래스 n | 기준 hit/n | 가상 상한 hit/n | n<20 |',
              '|---|---|---|---:|---|---|---|']
    for row in bins:
        if row['split'] in SPLITS[:2] and row['scope'] in ('clip', 'absolute_local_contrast_c'):
            lines.append(f"| {row['split']} | {row['scope']} | {row['bin']} | {row['n']} | {row['baseline_hits']}/{row['n']} | {row['any_grid_hits']}/{row['n']} | {'주의' if row['low_denominator'] else ''} |")
    lines += ['', ('clip은 정답 클래스 온도가 입력 변환 범위 [-40,200]°C 밖에 있는 픽셀 비율이다. '
              '대비는 정답 영역 중앙 온도와 같은 물리 영역의 주변 ring 중앙 온도 차이의 절댓값이며 °C 단위다. '
              '대비 구간은 보고용 설명이며 선택에 쓰지 않았다. n은 고유 이미지가 아닌 이미지×클래스 수이고 환경 태그는 중복될 수 있다. '
              'n<20 구간은 작은 표본이다. 크기·클래스별·clipping·대비·바람·일사·방사율 등 전체 층화는 `feature-bins.csv`에 있다. '
              '이 표는 관측 연관이며 인과 효과가 아니다.'), '',
              '## 재현성과 검증', '',
              f"가중치 SHA256: `{p['weights_sha256']}`. 아카이브 SHA256: `{p['archive_sha256']}`.", '',
              f"프로토콜 SHA256: `{sha(out / 'protocol.json')}`. 라이브러리 버전: `{compact(p['runtime'])}`.", '',
              '| 분할 | native .25/cache 일치 | .40·mixed sentinel | 이전 검증 기준 일치 |',
              '|---|---:|---:|---:|']
    for split, data in splits.items():
        v = data['parity']
        lines.append(f"| {split} | {v['native025_all']} | {v['native040_and_mixed_sentinels']} | {v['old_verified_baseline']} |")
    lines += ['', ('NMS cap·timeout 경로의 guard와 캐시 SHA256은 각 split JSON에, 원본·소스·설치 라이브러리 해시는 protocol.json에 기록했다. '
              'native/cache 일치는 픽셀 단위이며 sentinel은 추가 경로 검증 표본 수다. 저장된 parity 수치를 보고한 것이며 보고서 생성기가 모델 추론을 다시 실행하지는 않았다.'), '']
    validation = out / 'validation.json'
    if validation.exists():
        lines += ['실행자가 남긴 저장예측·지표·해시 독립 검증 기록(`validation.json`):', '', '```json',
                  json.dumps(read(validation), ensure_ascii=False, indent=2), '```', '']
    else:
        lines += ['저장예측·지표·해시 독립 검증 기록 `validation.json`은 보고서 생성 시점에 없었다.', '']
    test_results = out / 'test-results.json'
    if test_results.exists():
        lines += ['별도 pytest·Ruff 실행 기록(`test-results.json`):', '', '```json',
                  json.dumps(read(test_results), ensure_ascii=False, indent=2), '```', '']
    else:
        lines += ['`test-results.json`은 보고서 생성 시점에 없었다. 자동 테스트 통과를 주장하지 않는다.', '']
    executable = ps_quote(sys.executable)
    script = ps_quote(Path(__file__).resolve().parent / 'evaluate_thermal_thresholds.py')
    report_script = ps_quote(Path(__file__).resolve())
    validate_script = ps_quote(Path(__file__).resolve().parent / 'validate_thermal_thresholds.py')
    replay = out.parent / (out.name + '-replay')
    lines += ['아래 PowerShell 명령은 **새 비어 있는 재현 디렉터리**에서 같은 프로토콜을 재실행한다. 원본 결과에 재실행하면 exclusive 쓰기가 거부된다.', '', '```powershell',
              f'$replay = {ps_quote(replay)}',
              f'& {executable} {script} freeze --out $replay --archive {ps_quote(p["archive"])} --weights {ps_quote(p["weights"])} --reference {ps_quote(p["old_reference"])}',
              *[f'& {executable} {script} {stage} --out $replay' for stage in ('diagnose', 'select', 'confirm')],
              f'& {executable} {validate_script} --out $replay',
              '# 보고서 심사 자료는 동일한 원본을 복사한다.',
              "New-Item -ItemType Directory -Path (Join-Path $replay 'review67') -Force | Out-Null",
              f"Copy-Item -LiteralPath {ps_quote(out / 'review67' / '07-judge.md')} -Destination (Join-Path $replay 'review67/07-judge.md')",
              f'& {executable} {report_script} --out $replay', '```', '',
              ('추론은 직렬로 실행했으며 이번 단계에는 재학습과 Colab이 필요 없다. '
              '이번 임계값 실험의 CPU 지연·메모리·Jetson 성능은 측정하지 않았으므로 개선이나 실시간 탑재 안정성을 주장하지 않는다. '
              '기존 CPU 측정 결과를 이번 설정의 실측으로 대체하지 않는다.'), '',
              ('미해결 범위는 실제 현장 데이터 검증, 배포 장치 성능, 합성 생성기 밖의 일반화다. '
              '선택·확인 실패는 고정 모델과 이번 27개 격자에서 기준 유지라는 결과이며 추가학습 필요성을 자동으로 확정하지 않는다.'), '',
              borrowed_footer(judge), '',
              ('실제 반영 범위: 02의 단계 골격과 이미지 결과 전환 장부, 03의 기존 지표·복구 진단, '
              '05의 신규 경보/개별 hit 회귀 게이트, 01의 캐시·원본 보존, 06의 oracle 상한, 04의 버전·분할 동결. '
              'raw 재처리와 인스턴스→픽셀 상세 장부는 이번 구현에 포함하지 않았으며 guard 이상에서는 중단한다.'), '']
    return '\n'.join(lines)


def generate(out):
    out = Path(out).resolve()
    for name in OUTPUTS:
        if (out / name).exists():
            raise FileExistsError(out / name)
    protocol = read(out / 'protocol.json')
    splits = {name: read(out / f'{name}.json') for name in SPLITS}
    selection, decision = read(out / 'selection.json'), read(out / 'decision.json')
    judge = (out / 'review67' / '07-judge.md').read_text(encoding='utf-8')
    if len(protocol['grid']) != 27:
        raise ValueError('Expected exactly 27 frozen configurations')
    all_hashes = set()
    compare = selection['selected'] if selection['selected'] != protocol['baseline'] else selection['challenger']
    for split, data in splits.items():
        expected = protocol['splits'][split][1]
        if (len(data['ids']) != expected or len(set(data['ids'])) != expected or
                len(data['input_hashes']) != expected or len(set(data['input_hashes'])) != expected):
            raise ValueError(f'Invalid sample count/uniqueness: {split}')
        if all_hashes.intersection(data['input_hashes']):
            raise ValueError('Input hash leakage between splits')
        all_hashes.update(data['input_hashes'])
        names = set(protocol['grid']) if not split.startswith('confirmation') else {protocol['baseline'], compare}
        if set(data['results']) != names or data['grid_count'] != len(names):
            raise ValueError(f'Unexpected evaluated configurations: {split}')
        if any(v['image_count'] != expected for v in data['results'].values()):
            raise ValueError(f'Incomplete metric coverage: {split}')
    for filename, digest in selection['evidence_hashes'].items():
        if sha(out / filename) != digest:
            raise ValueError(f'Selection evidence changed: {filename}')
    if decision['selected_on_selection'] != selection['selected']:
        raise ValueError('Selection and decision disagree')
    errors, ledger, bins = detail_rows(splits)
    normal = normal_groups(splits, protocol['baseline'])
    comparison = comparison_rows(protocol, splits)
    report = render(out, protocol, splits, selection, decision, judge, bins, normal)
    write_csv(out / 'threshold-comparison.csv', comparison, ['split', 'configuration'])
    write_csv(out / 'errors.csv', errors, ['split', 'sample_id', 'class_id', 'category'])
    write_csv(out / 'transition-ledger.csv', ledger, ['split', 'configuration', 'transition', 'class', 'sample_id'])
    write_csv(out / 'feature-bins.csv', bins, ['split', 'scope', 'bin', 'n'])
    write_csv(out / 'normal-error-groups.csv', normal, ['split', 'configuration', 'scope', 'bin'])
    with (out / 'report.md').open('x', encoding='utf-8') as stream:
        stream.write(report)
    return {'comparison_rows': len(comparison), 'error_rows': len(errors),
            'transition_rows': len(ledger), 'feature_bins': len(bins),
            'normal_error_groups': len(normal), 'report': str(out / 'report.md')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(generate(args.out), ensure_ascii=False))


if __name__ == '__main__':
    main()
