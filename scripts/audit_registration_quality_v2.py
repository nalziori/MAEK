"""Audit frozen registration gate on TRAIN images only, before Colab training."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from maek.thermal_observation_eval import load_frames, sha, write_json
from maek.thermal_registration_quality import assess_registration


def audit(data, protocol, out):
    if out.exists():
        raise FileExistsError('Use fresh output')
    frozen=json.loads(protocol.read_text(encoding='utf-8'))
    for name,digest in frozen['data_hashes'].items():
        if sha(data/name)!=digest:
            raise ValueError('Data binding mismatch')
    repo=Path(__file__).resolve().parents[1]
    for name,digest in frozen['source_hashes'].items():
        if sha(repo/name)!=digest:
            raise ValueError('Source binding mismatch')
    frames=load_frames(data,'train')
    records=[]
    for frame in frames:
        decision=assess_registration(frame['reference'],frame['current'],frozen['registration_policy'])
        records.append({'sample_id':frame['sample_id'],'kind':'valid_pair',
                        'mechanism_audit_only':frame['mechanism'],**decision})
    for line in (data/'quality-index.jsonl').read_text(encoding='utf-8').splitlines():
        row=json.loads(line)
        if row['split']!='train':
            continue
        path=(data/row['relative_path']).resolve()
        if not path.is_relative_to(data.resolve()) or sha(path)!=row['sha256']:
            raise ValueError('Unsafe/mismatched sample')
        with np.load(path,allow_pickle=False) as a:
            decision=assess_registration(a['reference_c'],a['current_c'],frozen['registration_policy'])
        records.append({'sample_id':row['sample_id'],'kind':row['mechanism'],**decision})
    summary={kind:{'frames':sum(r['kind']==kind for r in records),
                   'accepted':sum(r['kind']==kind and r['can_infer'] for r in records),
                   'abstained':sum(r['kind']==kind and not r['can_infer'] for r in records)}
             for kind in ('valid_pair','misregistration','calibration_drift')}
    valid,shifted=summary['valid_pair'],summary['misregistration']
    result={'status':'completed','split':'train','image_only_gate':True,
        'policy_tuned_by_this_script':False,'summary':summary,
        'valid_pair_coverage':valid['accepted']/valid['frames'],
        'misregistration_rejection':shifted['abstained']/shifted['frames'],
        'calibration_drift_is_not_registration_ground_truth':True,
        'reasons':dict(Counter(r['reason'] for r in records)),
        'source_hashes':frozen['source_hashes'],'experiment_protocol_sha256':sha(protocol),
        'field_validated':False,'records':records}
    out.parent.mkdir(parents=True,exist_ok=True)
    write_json(out,result)
    print(json.dumps({k:v for k,v in result.items() if k not in ('records','source_hashes')}))
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('data','protocol','out'):
        parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    audit(args.data,args.protocol,args.out)
