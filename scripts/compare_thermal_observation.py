"""Compare a completed trained checkpoint and measured-input rules at a frozen dev FA gate."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from maek.thermal_observation_eval import run_comparison


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    parser.add_argument("--smoke", action="store_true", help="Allow fixture/untrained checkpoint; output is NOT a valid comparison")
    args = parser.parse_args()
    result = run_comparison(args.data, args.run, args.out, args.protocol, device=args.device, smoke=args.smoke)
    print(json.dumps({key: result[key] for key in ("status", "valid_comparison", "improvement_supported", "acceptance_checks")}))


if __name__ == "__main__":
    main()
