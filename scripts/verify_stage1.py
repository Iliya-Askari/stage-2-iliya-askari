"""Automatic acceptance check for Challenge 1 outputs.

Usage (after `nyc311 run`):  python scripts/verify_stage1.py
Prints PASS / WARN / FAIL per criterion; exit code 1 if anything FAILs.
"""

import argparse
import csv
import json
import re
import subprocess
import sys
from pathlib import Path

from nyc311_factory.contract import CASE_COLUMN_NAMES
from nyc311_factory.io_utils import sha256_file

MIN_COMMITS = 10
MIN_WORDS, MAX_WORDS = 800, 1500
EXPECTED_MONTHS = 18
RESULTS = []


def check(status, name, detail=""):
    RESULTS.append(status)
    print(f"[{status}] {name}" + (f" - {detail}" if detail else ""))


def run_git(*args):
    try:
        out = subprocess.run(["git", *args], capture_output=True, text=True, timeout=30)
        return out.stdout if out.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--curated", default="data/curated")
    parser.add_argument("--notebook", default="solution.ipynb")
    parser.add_argument("--report", default="report.md")
    parser.add_argument("--min-raw", type=int, default=300000)
    args = parser.parse_args()
    curated = Path(args.curated)

    manifest_path = curated / "run_manifest.json"
    if not manifest_path.exists():
        check("FAIL", "run_manifest.json exists", f"not found in {curated}")
        return 1
    m = json.loads(manifest_path.read_text(encoding="utf-8"))
    rec = m["records"]

    check("PASS" if rec["raw"] >= args.min_raw else "FAIL", "raw records >= minimum", f"{rec['raw']} (min {args.min_raw})")
    check("PASS" if rec["raw"] == rec["valid"] + rec["quarantined"] else "FAIL",
          "raw = valid + quarantined", f"{rec['raw']} = {rec['valid']} + {rec['quarantined']}")
    check("PASS" if sum(rec["quarantine_by_reason"].values()) == rec["quarantined"] else "FAIL",
          "quarantine counts per reason add up", str(rec["quarantine_by_reason"]))
    j = m["join"]
    check("PASS" if j["rows_before_join"] == j["rows_after_join"] == rec["valid"] else "FAIL",
          "join keeps row count", f"{j['rows_before_join']} -> {j['rows_after_join']}, unmatched {j['unmatched_population']}")
    http = m["http"]
    if m["config"]["source"]["kind"] == "file":
        check("WARN", "HTTP request budget", "file source (demo): no HTTP requests expected")
    else:
        check("PASS" if http["total_http_requests"] >= http["minimum_possible_requests"] else "FAIL",
              "HTTP request budget reported", f"{http['total_http_requests']} used / {http['minimum_possible_requests']} minimum")
    ratio = rec["quarantined"] / rec["raw"] if rec["raw"] else 0
    limit = m["config"]["quarantine_max_ratio"]
    check("PASS" if ratio <= limit else "FAIL", "quarantine ratio under threshold", f"{ratio:.4%} <= {limit:.2%}")
    if limit > 10 * max(ratio, 1e-9) and ratio > 0:
        check("WARN", "threshold is loose", f"limit is {limit / ratio:.0f}x the observed ratio; justify or tighten in report")
    check("PASS" if m["window"].get("scope_complaint_types") is not None else "WARN", "scope recorded in manifest",
          str(m["window"].get("scope_complaint_types")))
    commit = m["code_version"]["git_commit"]
    check("PASS" if commit != "unknown" else "WARN", "git commit recorded in manifest", commit)

    for name, expected in m["output_hashes_sha256"].items():
        path = curated / name
        ok = path.exists() and sha256_file(path) == expected
        check("PASS" if ok else "FAIL", f"hash matches manifest: {name}", expected[:12])

    case_path = curated / "case_level.csv"
    if case_path.exists():
        seen, dupes, negative, rows = set(), 0, 0, 0
        with open(case_path, encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            check("PASS" if tuple(reader.fieldnames) == CASE_COLUMN_NAMES else "FAIL", "case_level columns match contract")
            for row in reader:
                rows += 1
                if row["unique_key"] in seen:
                    dupes += 1
                seen.add(row["unique_key"])
                if row["resolution_hours"] and float(row["resolution_hours"]) < 0:
                    negative += 1
        check("PASS" if dupes == 0 else "FAIL", "no duplicate unique_key", f"{rows} rows, {dupes} duplicates")
        check("PASS" if negative == 0 else "FAIL", "no negative durations", str(negative))
        check("PASS" if rows == rec["valid"] else "FAIL", "case_level rows == valid count", f"{rows} vs {rec['valid']}")

    quarantine = curated / "quarantine.jsonl"
    if quarantine.exists():
        lines = [json.loads(l) for l in quarantine.read_text(encoding="utf-8").splitlines() if l.strip()]
        check("PASS" if len(lines) == rec["quarantined"] and all("reason_code" in l for l in lines) else "FAIL",
              "quarantine file has reason codes", f"{len(lines)} lines")

    wide = curated / "wide_borough_type_month.csv"
    if wide.exists():
        header = wide.read_text(encoding="utf-8").splitlines()[0].split(",")
        counts = [c for c in header if c.startswith("count_")]
        rates = [c for c in header if c.startswith("rate_per_")]
        check("PASS" if len(counts) == len(rates) == EXPECTED_MONTHS else "WARN", "wide table has count+rate per month",
              f"{len(counts)} count cols, {len(rates)} rate cols (expected {EXPECTED_MONTHS})")

    req = Path("requirements.txt")
    if req.exists():
        loose = [l for l in req.read_text().splitlines() if l.strip() and "==" not in l]
        check("PASS" if not loose else "FAIL", "requirements pinned with ==", str(loose))
    gi = Path(".gitignore")
    check("PASS" if gi.exists() and "data/raw" in gi.read_text() else "FAIL", ".gitignore excludes data/raw")

    nb = Path(args.notebook)
    if nb.exists():
        data = json.loads(nb.read_text(encoding="utf-8"))
        code = [c for c in data["cells"] if c["cell_type"] == "code"]
        counts = [c.get("execution_count") for c in code]
        check("PASS" if counts == list(range(1, len(code) + 1)) else "FAIL", "notebook execution counts 1..N", str(counts[:6]) + "...")
        check("PASS" if all(c.get("outputs") is not None for c in code) and any(c.get("outputs") for c in code) else "FAIL",
              "notebook outputs are saved")
        errors = [o for c in code for o in c.get("outputs", []) if o.get("output_type") == "error"]
        check("PASS" if not errors else "FAIL", "notebook has no error outputs")
        text = nb.read_text(encoding="utf-8")
        check("FAIL" if re.search(r"[A-Za-z]:\\\\|/Users/|/home/", text) else "PASS", "no absolute paths in notebook")
        plots = sum(1 for c in code for o in c.get("outputs", []) if "image/png" in o.get("data", {}))
        check("PASS" if plots >= 4 else "FAIL", ">= 4 charts in notebook", str(plots))
    else:
        check("FAIL", "solution.ipynb exists")

    rp = Path(args.report)
    if rp.exists():
        text = rp.read_text(encoding="utf-8")
        words = len(text.split())
        check("PASS" if MIN_WORDS <= words <= MAX_WORDS else "WARN", "report length", f"{words} words (target {MIN_WORDS}-{MAX_WORDS})")
        check("PASS" if "‹" not in text else "FAIL", "report has no unfilled placeholders", f"{text.count('‹')} left")
        check("PASS" if "AI usage" in text else "FAIL", "report has 'AI usage' section")
    else:
        check("FAIL", "report.md exists")

    commits = run_git("rev-list", "--count", "HEAD")
    if commits is None:
        check("WARN", "git history", "not a git repository yet")
    else:
        n = int(commits.strip())
        check("PASS" if n >= MIN_COMMITS else "FAIL", f"at least {MIN_COMMITS} commits", str(n))
        branches = (run_git("branch", "--all") or "").split()
        check("PASS" if len([b for b in branches if b != "*"]) >= 2 else "WARN", "more than one branch exists (feature branch + PR)")
        tracked = (run_git("ls-files", "data") or "").splitlines()
        bad = [t for t in tracked if "raw" in t and not t.endswith(".gitkeep")]
        check("PASS" if not bad else "FAIL", "no raw data tracked by git", str(bad[:3]))
        history = run_git("log", "--all", "--name-only", "--pretty=format:") or ""
        leaked = [l for l in history.splitlines() if re.search(r"data/raw/.*\.jsonl", l)]
        check("PASS" if not leaked else "FAIL", "no raw data anywhere in git history", str(leaked[:3]))

    fails = RESULTS.count("FAIL")
    print(f"\nSummary: {RESULTS.count('PASS')} PASS, {RESULTS.count('WARN')} WARN, {fails} FAIL")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
