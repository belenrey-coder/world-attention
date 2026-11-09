"""Step 2: clean the raw table -> data/interim/trends.parquet (all rows).

- keep national feeds (two-letter codes) and sub-national regions (CC-XXX); drop numeric US metro codes
- timestamps: stored with a 'Z' but really Central European wall-clock -> localize Europe/Berlin -> UTC
- validate against three known events (abort if any is off by > 15 minutes)
- add local_time, country_name, region, query_raw, query_norm, related
"""
import json
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytz

sys.path.insert(0, str(Path(__file__).parent))
from textnorm import norm  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "interim"
OUT.mkdir(parents=True, exist_ok=True)

# One zone per country. Explicit choices for multi-zone countries named in the brief;
# everything else falls back to pytz's first (primary) zone for the country.
TZ_OVERRIDES = {
    "US": "America/Chicago", "BR": "America/Sao_Paulo", "RU": "Europe/Moscow",
    "AU": "Australia/Sydney", "CA": "America/Toronto", "MX": "America/Mexico_City",
    "ID": "Asia/Jakarta", "KZ": "Asia/Almaty",
}

# Validation events: (query_norm, UTC date of the event, expected first-start UTC)
CHECKS = [
    ("pope francis", "2025-04-21", "2025-04-21 07:50"),
    ("cloudflare", "2025-11-18", "2025-11-18 11:20"),
    ("jimmy carter", "2024-12-29", "2024-12-29 20:50"),
]
TOL_MIN = 15


def berlin_to_utc(s: pd.Series):
    """'2025-04-21T09:50:00Z' (really Berlin wall-clock) -> tz-aware UTC timestamps."""
    naive = pd.to_datetime(s.str.replace("Z", "", regex=False), errors="coerce", format="%Y-%m-%dT%H:%M:%S")
    berlin = pytz.timezone("Europe/Berlin")
    # Ambiguous hour on the autumn DST change: assume summer time (first occurrence).
    loc = naive.dt.tz_localize(berlin, ambiguous=np.ones(len(naive), dtype=bool), nonexistent="shift_forward")
    amb = naive.notna() & (naive.dt.tz_localize(berlin, ambiguous="NaT", nonexistent="NaT").isna())
    return loc.dt.tz_convert("UTC"), int(amb.sum())


def main():
    df = pd.read_parquet(RAW / "trending_queries.parquet")
    n_raw = len(df)
    locs = pd.read_csv(RAW / "Trends_LocationList.csv", dtype=str, keep_default_na=False)
    loc_name = dict(zip(locs.tag, locs.location))

    code = df["location"]
    is_metro = code.str.fullmatch(r"\d+")
    is_country = code.str.fullmatch(r"[A-Z]{2}")
    is_region = code.str.fullmatch(r"[A-Z]{2}-[A-Z0-9]+")
    other = ~(is_metro | is_country | is_region)
    print(f"raw rows {n_raw:,}: country {is_country.sum():,}, region {is_region.sum():,}, "
          f"metro (dropped) {is_metro.sum():,}, other (dropped) {other.sum():,}")
    if other.any():
        print("  unrecognised codes:", sorted(code[other].unique())[:20])
    df = df[is_country | is_region].reset_index(drop=True)
    stats = {"rows_raw": n_raw, "rows_metro_dropped": int(is_metro.sum()), "rows_other_dropped": int(other.sum())}

    df["level"] = np.where(df["location"].str.len() == 2, "country", "region")
    df["country_code"] = df["location"].str[:2]
    df["country_name"] = df["country_code"].map(loc_name)
    df["region"] = np.where(df["level"] == "region", df["location"].map(loc_name), None)
    missing_names = sorted(df.loc[df.country_name.isna(), "country_code"].unique())
    if missing_names:
        print("  country codes without a name in the location list:", missing_names)

    # --- timestamps -------------------------------------------------------
    df["start_time_utc"], amb_s = berlin_to_utc(df["start_time"])
    df["end_time_utc"], amb_e = berlin_to_utc(df["end_time"])
    stats["dst_ambiguous_start_rows"] = amb_s
    print(f"timestamps: {df.start_time_utc.isna().sum():,} missing start, {df.end_time_utc.isna().sum():,} missing end; "
          f"{amb_s:,} start times fell in the ambiguous autumn DST hour (assumed CEST)")

    # --- text -------------------------------------------------------------
    df["query_raw"] = df["trends"]
    uq = pd.unique(df["query_raw"])
    qmap = {q: norm(q) for q in uq}
    df["query_norm"] = df["query_raw"].map(qmap)
    print(f"distinct query_raw {len(uq):,} -> distinct query_norm {df.query_norm.nunique():,}; "
          f"empty after normalization: {(df.query_norm == '').sum():,} rows")

    # --- validation -------------------------------------------------------
    results, failed = [], False
    for q, day, expected in CHECKS:
        exp = pd.Timestamp(expected, tz="UTC")
        sub = df[(df.query_norm == q) & (df.start_time_utc.dt.strftime("%Y-%m-%d") == day)]
        got = sub.start_time_utc.min()
        diff = abs((got - exp).total_seconds()) / 60 if pd.notna(got) else float("inf")
        ok = diff <= TOL_MIN
        failed |= not ok
        first_loc = sub.sort_values("start_time_utc").location.iloc[0] if len(sub) else None
        results.append({"query": q, "expected_utc": expected, "observed_utc": str(got)[:16],
                        "diff_min": diff, "first_location": first_loc, "pass": ok})
        print(f"  CHECK {q!r}: expected {expected} UTC, observed {str(got)[:16]} UTC "
              f"(first in {first_loc}), off by {diff:.0f} min -> {'PASS' if ok else 'FAIL'}")
    (OUT / "timestamp_checks.json").write_text(json.dumps({"checks": results, **stats}, indent=2, default=str))
    if failed:
        sys.exit("Timestamp validation failed (>15 min). Stopping before writing trends.parquet.")

    # --- local time -------------------------------------------------------
    tzmap = {}
    for cc in df.country_code.unique():
        tzmap[cc] = TZ_OVERRIDES.get(cc) or (pytz.country_timezones.get(cc) or ["UTC"])[0]
    df["local_tz"] = df["country_code"].map(tzmap)
    local = pd.Series(pd.NaT, index=df.index, dtype="datetime64[ns]")
    for tz, idx in df.groupby("local_tz").groups.items():
        local.loc[idx] = df.loc[idx, "start_time_utc"].dt.tz_convert(tz).dt.tz_localize(None)
    df["local_time"] = local
    (OUT / "country_timezones.json").write_text(json.dumps(dict(sorted(tzmap.items())), indent=1))

    # --- related list (computed on distinct breakdown strings, then broadcast) --
    codes, uniq_bd = pd.factorize(df["trend_breakdown"])
    tok_cache = {}

    def norm_list(bd):
        out, seen = [], set()
        for t in bd.split(","):
            n = tok_cache.get(t)
            if n is None:
                n = tok_cache[t] = norm(t)
            if n and n not in seen:
                seen.add(n)
                out.append(n)
        return out

    lists = pa.array([norm_list(b) for b in uniq_bd], type=pa.list_(pa.string()))
    related = lists.take(pa.array(codes))
    print(f"related: {len(uniq_bd):,} distinct breakdown strings, {len(tok_cache):,} distinct related terms")

    # --- write -------------------------------------------------------------
    num = ["search_volume_lower", "duration_minutes", "n_queries", "total_occurrences", "n_days_observed"]
    for c in num:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    for c in ["times_were_swapped", "duration_is_estimate"]:
        df[c] = df[c].map({"TRUE": True, "FALSE": False})
    keep = ["query_raw", "query_norm", "location", "level", "country_code", "country_name", "region",
            "start_time_utc", "end_time_utc", "local_time", "local_tz", "search_volume_lower",
            "duration_minutes", "duration_is_estimate", "times_were_swapped", "n_queries",
            "total_occurrences", "n_days_observed", "episode_id", "collection_date", "trend_breakdown"]
    table = pa.Table.from_pandas(df[keep], preserve_index=False).append_column("related", related)
    pq.write_table(table, OUT / "trends.parquet", compression="zstd")
    print(f"Wrote {OUT/'trends.parquet'}: {table.num_rows:,} rows, {table.num_columns} columns")


if __name__ == "__main__":
    main()
