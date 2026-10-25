"""Verify all original rainfall cells/masks and cache native geodesic summaries.

Does not write to any source COG, snapshot, station record or saved EE script.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.rainfall import LocalRainfall


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=ROOT / 'data/rainfall')
    parser.add_argument('--cache-dir', type=Path, default=ROOT / 'data/cache')
    args = parser.parse_args()
    rainfall = LocalRainfall(args.data_dir, args.cache_dir)
    path = rainfall.write_cache()
    print(json.dumps({'cache': str(path), 'revision': rainfall.meta()['revision'],
                      'statistics': {name: p['summary'] for name, p in rainfall.meta()['products'].items()}}))
