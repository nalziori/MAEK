"""Compare baseline/finetune/scratch under the frozen v2 experiment."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from maek.thermal_v2_comparison import run_comparison

if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('data','baseline','training-root','out','protocol'):
        parser.add_argument('--'+key,type=Path,required=True)
    parser.add_argument('--device',choices=['cuda','cpu'],default='cuda')
    parser.add_argument('--smoke',action='store_true')
    args=parser.parse_args()
    result=run_comparison(args.data,args.baseline,args.training_root,args.out,args.protocol,
                          device=args.device,smoke=args.smoke)
    print(json.dumps({k:result[k] for k in ('status','valid_comparison','improvement_supported')}))
