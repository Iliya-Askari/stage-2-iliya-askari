"""Helpers used by solution.ipynb (kept here so the notebook only narrates)."""

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .curate import CASE_FILE, WIDE_FILE
from .manifest import MANIFEST_FILE

IQR_FACTOR = 1.5
WEEKEND_DOW = (5, 6)
EDGE_MONTHS = 3
LOG_OFFSET = 1.0
UNKNOWN_BOROUGH = "UNSPECIFIED"


def load_cases(curated_dir):
    return pd.read_csv(Path(curated_dir) / CASE_FILE, parse_dates=["created_date", "closed_date"],
                       dtype={"unique_key": str, "incident_zip": str})


def load_wide(curated_dir):
    return pd.read_csv(Path(curated_dir) / WIDE_FILE)


def load_manifest(curated_dir):
    return json.loads((Path(curated_dir) / MANIFEST_FILE).read_text(encoding="utf-8"))


def iqr_fences(series, factor=IQR_FACTOR):
    """Tukey fences on log1p(hours): durations are right-skewed, so fences on the raw scale are useless."""
    logged = np.log1p(series.dropna())
    q1, q3 = logged.quantile([0.25, 0.75])
    spread = q3 - q1
    return float(np.expm1(q1 - factor * spread)), float(np.expm1(q3 + factor * spread))


def outlier_summary(df):
    closed = df.loc[df["is_closed"] == 1, "resolution_hours"]
    low, high = iqr_fences(closed)
    flagged = (closed > high) | (closed < low)
    return pd.DataFrame({
        "metric": ["fence_low_h", "fence_high_h", "n_flagged", "pct_flagged",
                   "mean_all_h", "mean_without_outliers_h", "median_all_h", "median_without_outliers_h"],
        "value": [low, high, int(flagged.sum()), 100 * flagged.mean(),
                  closed.mean(), closed[~flagged].mean(), closed.median(), closed[~flagged].median()],
    })


def monthly_trend(df):
    grouped = df.groupby("created_month")
    return pd.DataFrame({
        "cases": grouped.size(),
        "median_hours_closed": grouped.apply(lambda g: g.loc[g["is_closed"] == 1, "resolution_hours"].median(),
                                              include_groups=False),
        "open_share_pct": 100 * grouped["is_closed"].apply(lambda s: 1 - s.mean()),
    })


def correlation_frame(df):
    closed = df[df["is_closed"] == 1]
    frame = pd.DataFrame({
        "log_resolution_hours": np.log1p(closed["resolution_hours"]),
        "created_hour": closed["created_hour"], "created_dow": closed["created_dow"],
        "population_zip": closed["population_zip"],
    })
    return frame.corr(method="spearman")


def findings(df):
    """Data-driven sentences for the 'non-obvious findings' section (numbers computed, not typed)."""
    closed = df[df["is_closed"] == 1]
    out = []
    known = closed[closed["borough"] != UNKNOWN_BOROUGH]
    med = known.groupby("borough")["resolution_hours"].median().sort_values()
    out.append(f"Borough gap: median closing time is {med.iloc[0]:.1f} h in {med.index[0]} but "
               f"{med.iloc[-1]:.1f} h in {med.index[-1]} ({med.iloc[-1] / med.iloc[0]:.1f}x).")
    weekend = closed["created_dow"].isin(WEEKEND_DOW)
    out.append(f"Weekend effect: complaints created on weekends have median {closed.loc[weekend, 'resolution_hours'].median():.1f} h "
               f"vs {closed.loc[~weekend, 'resolution_hours'].median():.1f} h on weekdays.")
    trend = monthly_trend(df)
    first, last = trend.iloc[:EDGE_MONTHS], trend.iloc[-EDGE_MONTHS:]
    first_med, last_med = first["median_hours_closed"].mean(), last["median_hours_closed"].mean()
    first_open, last_open = first["open_share_pct"].mean(), last["open_share_pct"].mean()
    direction = "lower" if last_med < first_med else "higher"
    caveat = ("; recent months may look faster only because slow cases are not closed yet (right-censoring)"
              if last_med < first_med and last_open > first_open else "")
    out.append(f"Trend vs censoring: median closing time of the last {EDGE_MONTHS} months is {last_med:.1f} h "
               f"({direction} than {first_med:.1f} h in the first {EDGE_MONTHS}), while {last_open:.1f}% of recent cases "
               f"are still open (vs {first_open:.1f}%){caveat}.")
    both = df[df["zip_borough"].notna() & (df["borough"] != "UNSPECIFIED")]
    if len(both):
        out.append(f"Data quality: {100 * both['borough_mismatch'].mean():.2f}% of cases with a usable ZIP report a borough "
                   "different from the one implied by the ZIP prefix.")
    return out
