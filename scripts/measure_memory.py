"""Show that peak Python memory during curation stays far below the raw data size.

Usage: python scripts/measure_memory.py [config path]   (run after 'nyc311 fetch')
"""

import sys
import tracemalloc
from pathlib import Path

from nyc311_factory.config import load_config
from nyc311_factory.pipeline import run_curate

BYTES_PER_MB = 1024 * 1024

if __name__ == "__main__":
    cfg = load_config(sys.argv[1] if len(sys.argv) > 1 else "config/default.json")
    raw_bytes = sum(p.stat().st_size for p in Path(cfg.paths.raw).rglob("batch_*.jsonl"))
    tracemalloc.start()
    run_curate(cfg)
    _, peak = tracemalloc.get_traced_memory()
    print(f"raw on disk: {raw_bytes / BYTES_PER_MB:.1f} MB | peak traced Python memory: {peak / BYTES_PER_MB:.1f} MB")
