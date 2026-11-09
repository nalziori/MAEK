"""Report v2 synthetic support and training-only previews; no model performance."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import ListedColormap


def report(root):
    validation = json.loads((root / 'validation.json').read_text(encoding='utf-8'))
    if validation['status'] != 'passed':
        raise ValueError('Independent validation must pass before reporting usable data')
    rows = [json.loads(s) for s in (root / 'index.jsonl').read_text().splitlines()]
    quality = [json.loads(s) for s in (root / 'quality-index.jsonl').read_text().splitlines()]
    stats, cross, examples = defaultdict(Counter), defaultdict(Counter), {}
    zero_drive_losses = 0
    for row in rows:
        with np.load(root / row['relative_path'], allow_pickle=False) as f:
            target = f['target']
            count = stats[row['split'], row['mechanism']]
            count['pairs'] += 1
            count['positive_frames'] += int(np.any(target == 1))
            count['positive_pixels'] += int(np.sum(target == 1))
            count['negative_pixels'] += int(np.sum(target == 0))
            count['ignored_pixels'] += int(np.sum(target == 255))
            if row['mechanism'] == 'wall_loss' and row['factors']['drive_bin'] == 'zero':
                zero_drive_losses += 1
            if row['mechanism'] == 'stable_repeat':
                cross[row['split'], row['factors']['insulated']][row['psf_sigma_px']] += 1
            # Deterministic first training examples, not strongest held-out examples.
            if (row['split'] == 'train' and row['factors']['drive_bin'] == 'high'
                    and row['mechanism'] not in examples):
                examples[row['mechanism']] = (row, {k:f[k] for k in f.files})
    for row in quality:
        if row['split'] == 'train' and row['mechanism'] not in examples:
            with np.load(root / row['relative_path'], allow_pickle=False) as f:
                examples[row['mechanism']] = (row, {k:f[k] for k in f.files})
    output_rows = [dict(split=s, mechanism=m, **counts) for (s,m),counts in stats.items()]
    with (root / 'support.csv').open('w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=list(output_rows[0]))
        writer.writeheader()
        writer.writerows(output_rows)
    with (root / 'blur-insulation-cross.csv').open('w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        writer.writerow(['split','insulated','psf_sigma_px','scene_count'])
        for (split, insulated), counts in cross.items():
            for blur,count in sorted(counts.items()):
                writer.writerow([split,insulated,blur,count])
    fig, axes = plt.subplots(len(examples), 4, figsize=(13, 2.5 * len(examples)))
    for axes_row, (name, (row, a)) in zip(axes, examples.items()):
        lo = min(float(a['reference_c'].min()), float(a['current_c'].min()))
        hi = max(float(a['reference_c'].max()), float(a['current_c'].max()))
        for ax, key in zip(axes_row[:2], ['reference_c', 'current_c']):
            im = ax.imshow(a[key], cmap='inferno', vmin=lo, vmax=hi)
            fig.colorbar(im, ax=ax, fraction=.04)
        delta = a['current_c'].astype(float) - a['reference_c']
        extent = max(.5, float(np.percentile(np.abs(delta), 99)))
        im = axes_row[2].imshow(delta, cmap='coolwarm', vmin=-extent, vmax=extent)
        fig.colorbar(im, ax=axes_row[2], fraction=.04)
        target = np.where(a['target'] == 255, 2, a['target'])
        axes_row[3].imshow(target, cmap=ListedColormap(['#263b50','#fa6c38','#cccccc']), vmin=0,vmax=2)
        for ax in axes_row:
            ax.set_xticks([])
            ax.set_yticks([])
        axes_row[0].set_ylabel(name + '\n' + row['sample_id'].split('_')[2], fontsize=9)
    for ax,title in zip(axes[0], ['Reference (degC)','Current (degC)',
                                 'Measured change (degC)','Target: blue0 / orange1 / gray ignore']):
        ax.set_title(title, fontsize=10)
    fig.suptitle('SYNTHETIC ONLY - generic LWIR model; not field validation or crack labels', fontsize=13)
    fig.tight_layout(rect=(0,0,1,.98))
    fig.savefig(root / 'preview.png', dpi=130)
    plt.close(fig)
    manifest = json.loads((root / 'manifest.json').read_text())
    config = json.loads((root / 'protocol.json').read_text())['config']
    split_text = '/'.join(f'{split}{count}쌍' for split, count in Counter(
        row['split'] for row in rows).items())
    lines = ['# 문헌 근거 합성 열화상 v2 데이터 카드', '',
        '**합성 데이터. 현장 검증 없음. 균열·감육 확정 정답이 아님.**', '',
        f"독립 장면 {manifest['group_count']}개, 관측 {len(rows)}쌍, 별도 품질 fixture {len(quality)}쌍.",
        f"{split_text}으로 분리했다. 각 쌍은 기준·현재{config['shape'][0]}×{config['shape'][1]} float32°C 영상이다.",
        '원인별 개수는 설계한 균형 실험이며 실제 결함 발생률을 뜻하지 않는다.', '',
        '## 검증과 근거', '',
        '- [독립 검증](validation.json): 데이터 해시·분할·물리 요인·측정/라벨 재계산을 확인한다.',
        '- [출처·가정 원장](evidence-ledger.json): 원자료 URL/절/판본/범위와 설정값의 근거 상태.',
        '- [고정 프로토콜](protocol.json), [manifest](manifest.json), [관측 인덱스](index.jsonl).',
        '- [생성 구조·한계·실행 안내](../../../MAEK/docs/thermal-evidence-synthesis.md).',
        '- [픽셀·프레임 지원 통계](support.csv), [흐림×보온 교차표](blur-insulation-cross.csv).', '',
        '## 생성된 관측의 지원 범위', '',
        '| 분할 | 물리/관측 개입 | 쌍 수 | 양성 픽셀이 있는 쌍 |', '|---|---|---:|---:|']
    for r in output_rows:
        lines.append(f"| {r['split']} | {r['mechanism']} | {r['pairs']} | {r['positive_frames']} |")
    lines += ['', '이 표는 정답에 양성 관측이 얼마나 포함됐는지 확인한 것이다. 모델 재현율·IoU·오경보 결과가 아니다.',
        f'온도 구동력0인 감육 대조군 {zero_drive_losses}쌍은 물리적으로 벽을 얇게 했지만 관측 양성으로 강제하지 않았다.',
        '반사·코팅 변화도 열적 관측 양성일 수 있다. 이를 균열 경보로 바로 바꾸면 제품 수준의 오경보가 된다.', '',
        '## 사용 경계', '',
        '모델 입력은 reference_c/current_c에서 만든3채널뿐이다. clean/true thickness/pipe mask/noise/원인/라벨 문턱은 감사 전용이다.',
        'quality-fixtures는 분할 학습에서 제외한다. 자동으로 정합·드리프트를 탐지하는 모델이 학습됐다는 의미도 아니다.',
        '정상상태 축약 셸·평탄한 분광 응답·회색 물체·가정한 센서 잡음이다. 실제 유동/재질/분광응답/BRDF/일사/균열 성장/가스누설은 검증하지 않았다.',
        '동일 생성기의 stress split은 새로운 현장 시험이 아니다. 문헌의 식을 쓴 것만으로 합성이 실측과 동등해지지는 않는다.', '',
        '기존 v1 Colab 패키지는 수정하지 않았다. v2로 학습하려면 별도 v2 프로토콜·번들을 만들어야 한다. 이번 산출물은 데이터이며 학습 모델이 아니다.', '',
        '## 미리보기', '', '![합성 관측과 품질 거절 예시](preview.png)', '',
        '미리보기는 train의 정해진 첫 사례를 사용했다. 시각화 범위는 행별 기준·현재에 동일하게 적용했고, 학습은 원래 온도 배열을 사용한다.']
    (root / 'DATA_CARD.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    summary = {'status':'written','synthetic_only':True,'field_validated':False,
               'model_evaluation_performed':False,'rows':output_rows,
               'zero_drive_wall_loss_pairs':zero_drive_losses,
               'artifact_hashes':{name:hashlib.sha256((root/name).read_bytes()).hexdigest()
                   for name in ['DATA_CARD.md','preview.png','support.csv','blur-insulation-cross.csv']}}
    (root / 'report-manifest.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps({k:v for k,v in summary.items() if k != 'rows'}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, required=True)
    report(parser.parse_args().dataset)
