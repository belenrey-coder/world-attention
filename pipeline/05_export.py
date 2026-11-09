"""Step 5: export compact JSON for the site -> data/export/ (every file < 2 MB, split where needed).

  days/YYYY-MM.json        per local day and country, the top 10 topics (split into parts if > 2 MB)
  moments_global.json      global moments with spread timelines (split by month if > 2 MB)
  topics_index.json        searchable topics: months, countries, reach (sharded if > 2 MB)
  wrapped/<CC>.json        Country Wrapped card data, plus wrapped/index.json
  hours/YYYY-MM.json       per UTC hour and country, the top active trend (map frames for the time machine)
  similarity.json          125 x 125 Jaccard similarity of topic sets (all topics, and without football)
  routine.json             trends by local hour x category, per country and worldwide
  coverage.json            trends per UTC day and country, with collection-gap flags
  manifest.json            every file written, with its size

National feeds only. Volumes are Google's lower-bound buckets (search_volume_lower).
"""
import json
import math
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import sparse

sys.path.insert(0, str(Path(__file__).parent))
from common import INTERIM, REGION_TZ, ROOT  # noqa: E402

EXPORT = ROOT / "data" / "export"
MAX_BYTES = 2_000_000
TOP_N_DAY = 10
LOCAL_TOP_N = 10
WEATHER_MIN_TRENDS = 20            # weather hour only if the country has this many weather trends
SPORT_CATS = {"sports_match", "team"}
NBA_RE = (r"\bnba\b|lakers|celtics|warriors|knicks|thunder|nuggets|bucks|76ers|sixers|heat vs|vs heat|mavericks|"
          r"timberwolves|cavaliers|pacers|rockets|spurs|clippers|grizzlies|pelicans|kings vs|suns|hawks|raptors|"
          r"magic vs|vs magic|bulls vs|vs bulls|pistons|hornets|wizards|blazers|jazz vs|vs jazz|nets vs|vs nets")
NIGHT_HOURS = range(0, 5)          # 00:00-04:59 local
LOW_DATA_MEDIAN = 5                # Wrapped stats are low_data if the median covered day has < 5 national trends
REGIONAL_TOD = ("US", "CA", "RU")  # time-of-day stats from regional feeds, each region in its own zone
INDEX_MIN_REACH = 2                # topics_index: topics in >= 2 countries, or in any daily top 10
MANIFEST = []


def dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=str)


def write(rel: str, obj) -> int:
    s = dumps(obj).encode("utf-8")
    if len(s) > MAX_BYTES:
        raise ValueError(f"{rel} is {len(s):,} bytes")
    p = EXPORT / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(s)
    MANIFEST.append({"file": rel, "bytes": len(s)})
    return len(s)


def write_parts(base: str, keys: list, build) -> list:
    """build(list_of_keys) -> obj. Write one file if it fits, else split keys into k equal parts."""
    for k in range(1, len(keys) + 1):
        chunks = [list(c) for c in np.array_split(np.array(keys, dtype=object), k) if len(c)]
        objs = [build(c) for c in chunks]
        if all(len(dumps(o).encode()) <= MAX_BYTES for o in objs):
            if k == 1:
                write(f"{base}.json", objs[0])
                return [f"{base}.json"]
            names = [f"{base}-{i + 1}.json" for i in range(k)]
            for n, o in zip(names, objs):
                write(n, o)
            return names
    raise ValueError(f"cannot fit {base} under {MAX_BYTES} bytes")


def load():
    t = pd.read_parquet(INTERIM / "topics.parquet",
                        columns=["topic_id", "country_code", "country_name", "level", "start_time_utc", "end_time_utc",
                                 "duration_minutes", "local_time", "search_volume_lower"])
    t = t[(t.level == "country") & t.topic_id.notna()].drop(columns="level")
    t["vol"] = t.search_volume_lower.fillna(0)
    t["ldate"] = t.local_time.dt.strftime("%Y-%m-%d")
    t["lmonth"] = t.ldate.str[:7]
    t["lhour"] = t.local_time.dt.hour
    meta = pd.read_parquet(INTERIM / "topic_meta.parquet").set_index("topic_id")
    t["category"] = t.topic_id.map(meta.category).fillna("unlabeled")
    m = pd.read_parquet(INTERIM / "moments.parquet")
    return t, meta, m


def export_days(t, meta):
    d = (t.groupby(["lmonth", "ldate", "country_code", "topic_id"])
         .agg(vol=("vol", "sum"), n=("vol", "size"), first=("start_time_utc", "min")).reset_index())
    d = d.sort_values(["ldate", "country_code", "vol", "n", "first"], ascending=[True, True, False, False, True])
    d = d.groupby(["ldate", "country_code"]).head(TOP_N_DAY)
    files = {}
    for month, g in d.groupby("lmonth"):
        def build(dates, g=g, month=month):
            gg = g[g.ldate.isin(dates)]
            tids = list(dict.fromkeys(gg.topic_id))
            pos = {tid: i for i, tid in enumerate(tids)}
            days = {}
            for (ld, cc), h in gg.groupby(["ldate", "country_code"], sort=True):
                days.setdefault(ld, {})[cc] = [[pos[a], int(v), int(n)] for a, v, n in zip(h.topic_id, h.vol, h.n)]
            return {"month": month, "fields": ["topic", "volume_sum", "trends"],
                    "topics": [[tid, meta.topic_name.get(tid), meta.type.get(tid)] for tid in tids],
                    "days": days}
        files[month] = write_parts(f"days/{month}", sorted(g.ldate.unique()), build)
    return d, files


def export_global(m):
    g = m[m.is_global].sort_values("start_utc")
    recs = [{"id": int(r.moment_id), "topic_id": r.topic_id, "name": r.topic_name, "type": r.type,
             "is_sport": bool(r.is_sport),
             "start_utc": r.start_utc.isoformat(), "reach": int(r.reach), "reach_60": int(r.reach_60),
             "minutes_to_half": int(r.minutes_to_half), "peak_volume": int(r.peak_volume),
             "timeline": [[c["country_code"], c["min_from_start"], c["phrasing"]] for c in r.countries]}
            for r in g.itertuples()]
    obj = {"fields_timeline": ["country", "minutes_from_start", "phrasing"], "moments": recs}
    if len(dumps(obj).encode()) <= MAX_BYTES:
        write("moments_global.json", obj)
        return ["moments_global.json"]
    names = []
    for month in sorted({r["start_utc"][:7] for r in recs}):
        names.append(f"moments_global/{month}.json")
        write(names[-1], {**obj, "moments": [r for r in recs if r["start_utc"][:7] == month]})
    write("moments_global.json", {"split_by_month": names, "count": len(recs)})
    return names


def export_index(t, meta, day_top, m):
    agg = t.groupby("topic_id").agg(trends=("vol", "size"), vol=("vol", "sum"))
    cc = t.groupby("topic_id").country_code.unique()
    months = t.groupby("topic_id").lmonth.unique()
    agg["reach"] = cc.map(len)
    keep = agg[(agg.reach >= INDEX_MIN_REACH) | agg.index.isin(day_top.topic_id.unique())]
    keep = keep.sort_values(["trends", "vol"], ascending=False)
    all_months = sorted(t.lmonth.unique())
    mpos = {mo: i for i, mo in enumerate(all_months)}
    n_mom = m.groupby("topic_id").size()
    rows = [[tid, meta.topic_name.get(tid), meta.type.get(tid), meta.qid.get(tid) if pd.notna(meta.qid.get(tid)) else None,
             int(r.reach), int(r.trends), int(n_mom.get(tid, 0)),
             sorted(mpos[x] for x in months[tid]), sorted(cc[tid].tolist())]
            for tid, r in keep.iterrows()]
    head = {"fields": ["topic_id", "name", "type", "qid", "reach", "trends", "moments", "months", "countries"],
            "months": all_months}
    obj = {**head, "topics": rows}
    if len(dumps(obj).encode()) <= MAX_BYTES:
        write("topics_index.json", obj)
        return 1, len(rows)
    # shard: most-trended first, so shard 0 alone covers the most popular searches
    shards, cur, size = [], [], 0
    for r in rows:
        b = len(dumps(r).encode()) + 1
        if size + b > MAX_BYTES - 5000:
            shards.append(cur)
            cur, size = [], 0
        cur.append(r)
        size += b
    shards.append(cur)
    names = [f"topics_index/{i:03d}.json" for i in range(len(shards))]
    for n, s in zip(names, shards):
        write(n, {**head, "topics": s})
    write("topics_index.json", {**head, "shards": names, "count": len(rows),
                                "note": "shards ordered by number of trends, most first"})
    return len(names), len(rows)


def gap_days(t):
    """UTC days whose total trends are < 25% of the median day (collection gaps; same rule as coverage.json)."""
    day = t.start_time_utc.dt.strftime("%Y-%m-%d")
    tot = day.value_counts()
    full = pd.date_range(tot.index.min(), tot.index.max(), freq="D").strftime("%Y-%m-%d")
    tot = tot.reindex(full, fill_value=0)
    return set(tot.index[tot < 0.25 * tot.median()]), day


def low_data_countries(t):
    """Median national trends per covered day (monthly averages over non-gap days, median over months;
    the same measure as CHECKS.md C4 'thin feeds')."""
    gaps, day = gap_days(t)
    d = pd.DataFrame({"cc": t.country_code.values, "day": day.values})
    d = d[~d.day.isin(gaps)]
    d["month"] = d.day.str[:7]
    per = d.groupby(["cc", "month"]).size().unstack(fill_value=0) / d.groupby("month").day.nunique()
    return per.median(axis=1)


def regional_hours(meta, cz):
    """Local hour of every regional-feed trend in REGIONAL_TOD countries, using each region's own zone."""
    r = pd.read_parquet(INTERIM / "topics.parquet", columns=["topic_id", "country_code", "location", "level", "start_time_utc"],
                        filters=[("level", "==", "region"), ("country_code", "in", list(REGIONAL_TOD))])
    r = r[r.topic_id.notna()]
    zone = r.location.str.split("-").str[1]
    zone = pd.Series([REGION_TZ.get(c, {}).get(z, cz[c]) for c, z in zip(r.country_code, zone)], index=r.index)
    r["lhour"] = -1
    for z, idx in zone.groupby(zone).groups.items():
        r.loc[idx, "lhour"] = r.loc[idx, "start_time_utc"].dt.tz_convert(z).dt.hour
    r["category"] = r.topic_id.map(meta.category).fillna("unlabeled")
    return r


def export_wrapped(t, meta, m):
    countries = t.groupby("country_code").agg(country_name=("country_name", "first"), trends=("vol", "size"),
                                              first=("ldate", "min"), last=("ldate", "max"),
                                              days=("ldate", "nunique"))
    ccs = countries.index.tolist()
    name = lambda tid: meta.topic_name.get(tid)  # noqa: E731
    typ = lambda tid: meta.type.get(tid)  # noqa: E731

    # uniquely local: topics that trended in this country's national feed and no other
    tc = t.groupby(["topic_id", "country_code"]).agg(vol=("vol", "sum"), n=("vol", "size")).reset_index()
    tot = tc.groupby("topic_id").agg(vol_all=("vol", "sum"), reach=("country_code", "size"))
    tc = tc.join(tot, on="topic_id")
    tc["share"] = tc.vol / tc.vol_all.replace(0, np.nan)
    tc["score"] = tc.vol * tc.share
    local = (tc[tc.reach == 1].sort_values(["vol", "n"], ascending=False)
             .groupby("country_code").head(LOCAL_TOP_N))

    # attention twin: Jaccard on topic sets
    ti = {tid: i for i, tid in enumerate(tc.topic_id.unique())}
    ci = {c: i for i, c in enumerate(ccs)}
    X = sparse.csr_matrix((np.ones(len(tc)), (tc.country_code.map(ci), tc.topic_id.map(ti))),
                          shape=(len(ccs), len(ti)))
    inter = (X @ X.T).toarray()
    sizes = np.asarray(X.sum(1)).ravel()
    jac = inter / (sizes[:, None] + sizes[None, :] - inter)
    np.fill_diagonal(jac, -1)

    # global moments per country
    gm = m[m.is_global]
    n_global = len(gm)
    part, early = {}, {}
    for cs in gm.countries:
        for i, c in enumerate(cs):
            part[c["country_code"]] = part.get(c["country_code"], 0) + 1
            if i < 3:
                early[c["country_code"]] = early.get(c["country_code"], 0) + 1

    # time of day: national feed in the country's zone, except REGIONAL_TOD countries (regional feeds, own zones)
    cz = json.load(open(INTERIM / "country_timezones.json"))
    reg = regional_hours(meta, cz)
    tod = pd.concat([t[~t.country_code.isin(REGIONAL_TOD)][["country_code", "lhour", "category"]],
                     reg[["country_code", "lhour", "category"]]])
    hours = (tod.groupby(["country_code", "lhour"]).size().unstack(fill_value=0)
             .reindex(index=ccs, columns=range(24), fill_value=0))
    wt = tod[tod.category == "weather"]
    whours = (wt.groupby(["country_code", "lhour"]).size().unstack(fill_value=0)
              .reindex(index=ccs, columns=range(24), fill_value=0))
    med_day = low_data_countries(t)
    per_day = t.groupby(["country_code", "ldate"]).size()
    day_topic = t.groupby(["country_code", "ldate", "topic_id"]).vol.sum()
    month_top = (t.groupby(["country_code", "lmonth", "topic_id"]).agg(vol=("vol", "sum"), n=("vol", "size"))
                 .reset_index().sort_values(["vol", "n"], ascending=False)
                 .drop_duplicates(["country_code", "lmonth"]).sort_values("lmonth"))

    index = []
    for c in ccs:
        info = countries.loc[c]
        h = hours.loc[c]
        busiest = per_day.loc[c].idxmax()
        bt = day_topic.loc[(c, busiest)].sort_values(ascending=False).head(5)
        twins = np.argsort(-jac[ci[c]])[:3]
        card = {
            "country_code": c, "country_name": info.country_name,
            "coverage": {"first_day": info["first"], "last_day": info["last"], "days": int(info.days),
                         "trends": int(info.trends)},
            "uniquely_local": [{"topic_id": r.topic_id, "name": name(r.topic_id), "type": typ(r.topic_id),
                                "volume_sum": int(r.vol), "trends": int(r.n), "share_here": round(float(r.share), 3),
                                "reach": int(r.reach)}
                               for r in local[local.country_code == c].itertuples()],
            "busiest_day": {"date": busiest, "trends": int(per_day.loc[(c, busiest)]),
                            "top_topics": [{"topic_id": k, "name": name(k)} for k in bt.index]},
            "attention_twin": {"country_code": ccs[twins[0]], "country_name": countries.country_name.iloc[twins[0]],
                               "jaccard": round(float(jac[ci[c], twins[0]]), 4),
                               "runners_up": [{"country_code": ccs[j], "jaccard": round(float(jac[ci[c], j]), 4)}
                                              for j in twins[1:]]},
            "low_data": bool(med_day.get(c, 0) < LOW_DATA_MEDIAN),
            "median_trends_per_day": round(float(med_day.get(c, 0)), 1),
            "time_of_day_source": ("regional feeds, each region's own time zone" if c in REGIONAL_TOD
                                   else "national feed, one time zone"),
            # no busiest_hour: CHECKS.md C4 shows it is mostly the 19:00 UTC collection bump
            "weather_hour": (int(whours.loc[c].idxmax()) if whours.loc[c].sum() >= WEATHER_MIN_TRENDS else None),
            "weather_trends": int(whours.loc[c].sum()),
            "weather_hour_histogram": [int(x) for x in whours.loc[c].values],
            "hour_histogram": [int(x) for x in h.values],
            "night_share": round(float(h.loc[list(NIGHT_HOURS)].sum() / h.sum()), 4),
            "global_moments": {"joined": part.get(c, 0), "total": n_global,
                               "share": round(part.get(c, 0) / n_global, 4) if n_global else None,
                               "among_first_3": early.get(c, 0)},
            "top_topic_per_month": [{"month": r.lmonth, "topic_id": r.topic_id, "name": name(r.topic_id),
                                     "volume_sum": int(r.vol), "trends": int(r.n)}
                                    for r in month_top[month_top.country_code == c].itertuples()],
        }
        write(f"wrapped/{c}.json", card)
        index.append({"country_code": c, "country_name": info.country_name, "twin": card["attention_twin"]["country_code"],
                      "weather_hour": card["weather_hour"],
                      "night_share": card["night_share"], "low_data": card["low_data"]})
    write("wrapped/index.json", index)
    return len(ccs), jac, ccs, X, tc, ti


def export_hours(t, meta):
    """Each trend counts as active in every UTC hour from its start to its end (max 24 h)."""
    dur = pd.to_timedelta(t.duration_minutes.fillna(0).clip(upper=24 * 60), unit="m")
    end = t.end_time_utc.fillna(t.start_time_utc + dur)
    end = end.where(end > t.start_time_utc, t.start_time_utc + pd.Timedelta(minutes=1))
    h0 = t.start_time_utc.dt.floor("h").astype("int64") // 3_600_000_000_000
    h1 = (end - pd.Timedelta(microseconds=1)).dt.floor("h").astype("int64") // 3_600_000_000_000
    n = np.clip(h1 - h0 + 1, 1, 25).values
    tid_codes, tid_uni = pd.factorize(t.topic_id)
    cc_codes, cc_uni = pd.factorize(t.country_code, sort=True)
    idx = np.repeat(np.arange(len(t)), n)
    offs = np.arange(len(idx)) - np.repeat(np.cumsum(n) - n, n)
    e = pd.DataFrame({"hour": h0.values[idx] + offs, "cc": cc_codes[idx], "tid": tid_codes[idx],
                      "vol": t.vol.values[idx], "start": t.start_time_utc.astype("int64").values[idx]})
    e = e.sort_values(["hour", "cc", "vol", "start"], ascending=[True, True, False, False])
    e = e.drop_duplicates(["hour", "cc"])
    e["ts"] = pd.to_datetime(e.hour * 3_600_000_000_000, utc=True)
    e["month"] = e.ts.dt.strftime("%Y-%m")
    countries = list(cc_uni)
    n_files = 0
    for month, g in e.groupby("month"):
        start = pd.Timestamp(month + "-01", tz="UTC")
        all_hours = pd.date_range(start, start + pd.offsets.MonthBegin(1), freq="h", inclusive="left")
        key = g.set_index(["hour", "cc"])

        def build(hrs, key=key, month=month):
            hrs_i = [int(h.value // 3_600_000_000_000) for h in hrs]
            sub = key[key.index.get_level_values(0).isin(hrs_i)]
            tids = list(dict.fromkeys(sub.tid))
            pos = {x: i for i, x in enumerate(tids)}
            top, vol = [], []
            for hi in hrs_i:
                row_t, row_v = [-1] * len(countries), [0] * len(countries)
                if hi in sub.index.get_level_values(0):
                    s = sub.loc[hi]
                    for c, a, v in zip(s.index, s.tid, s.vol):
                        row_t[c], row_v[c] = pos[a], int(v)
                top.append(row_t)
                vol.append(row_v)
            return {"month": month, "countries": countries,
                    "hours": [h.strftime("%Y-%m-%dT%H") for h in hrs],
                    "note": "top[i][j] = index into topics of the highest-volume trend active in hour i in country j; -1 = none",
                    "topics": [[tid_uni[x], meta.topic_name.get(tid_uni[x]), meta.category.get(tid_uni[x])] for x in tids],
                    "top": top, "volume": vol}
        n_files += len(write_parts(f"hours/{month}", list(all_hours), build))
    return n_files


def export_similarity(jac, ccs, X, tc, ti, meta, countries_df):
    from scipy.cluster.hierarchy import leaves_list, linkage
    from scipy.spatial.distance import squareform
    J = jac.copy()
    np.fill_diagonal(J, 1.0)
    # without football (matches and clubs), to see blocs beyond shared fixtures
    cat = pd.Series(list(ti.keys())).map(meta.category).fillna("unlabeled").values
    keep = ~np.isin(cat, list(SPORT_CATS))
    Xn = X[:, np.where(keep)[0]]
    inter = (Xn @ Xn.T).toarray()
    sz = np.asarray(Xn.sum(1)).ravel()
    Jn = inter / np.maximum(sz[:, None] + sz[None, :] - inter, 1)
    np.fill_diagonal(Jn, 1.0)
    order = leaves_list(linkage(squareform(1 - J, checks=False), method="average")).tolist()
    order_n = leaves_list(linkage(squareform(1 - Jn, checks=False), method="average")).tolist()
    write("similarity.json", {
        "countries": ccs, "names": [countries_df.country_name.loc[c] for c in ccs],
        "topics_per_country": [int(x) for x in np.asarray(X.sum(1)).ravel()],
        "jaccard": np.round(J, 4).tolist(), "jaccard_no_football": np.round(Jn, 4).tolist(),
        "cluster_order": order, "cluster_order_no_football": order_n,
        "note": "Jaccard on sets of topics that trended in each national feed; cluster order = average-linkage leaves"})


def export_routine(t, meta):
    cats = sorted(t.category.unique())
    names = t.topic_id.map(meta.topic_name).fillna("")
    t = t.assign(series=t.category)
    nba = t[names.str.contains(NBA_RE, case=False, regex=True)].assign(series="nba")
    both = pd.concat([t[["country_code", "series", "lhour"]], nba[["country_code", "series", "lhour"]]])
    series = cats + ["nba"]
    cube = (both.groupby(["country_code", "series", "lhour"]).size()
            .unstack(fill_value=0).reindex(columns=range(24), fill_value=0))
    out = {}
    for c in sorted(t.country_code.unique()):
        sub = cube.loc[c].reindex(series, fill_value=0)
        out[c] = sub.values.astype(int).tolist()
    world = both.groupby(["series", "lhour"]).size().unstack(fill_value=0).reindex(
        index=series, columns=range(24), fill_value=0)
    write("routine.json", {"series": series, "hours": list(range(24)),
                           "note": "trend starts by LOCAL hour (one zone per country); rows follow 'series'; "
                                   "'nba' = NBA team/league topics (also counted in their category)",
                           "world": world.values.astype(int).tolist(), "countries": out})


def export_coverage(t):
    day = t.start_time_utc.dt.strftime("%Y-%m-%d")
    per = t.groupby([day, "country_code"]).size().unstack(fill_value=0)
    full = pd.date_range(per.index.min(), per.index.max(), freq="D").strftime("%Y-%m-%d")
    per = per.reindex(full, fill_value=0)
    tot = per.sum(1)
    med = float(tot.median())
    gap = (tot < 0.25 * med).tolist()
    runs, cur = [], None
    for d, gflag in zip(per.index, gap):
        if gflag and cur is None:
            cur = [d, d]
        elif gflag:
            cur[1] = d
        elif cur is not None:
            runs.append(cur)
            cur = None
    if cur:
        runs.append(cur)
    write("coverage.json", {"days": per.index.tolist(), "countries": per.columns.tolist(),
                            "total": [int(x) for x in tot], "countries_reporting": [int(x) for x in (per > 0).sum(1)],
                            "is_gap": gap, "gap_rule": "day total < 25% of the median day", "gaps": runs,
                            "median_day": med, "per_country": per.T.values.tolist()})
    return runs


def main():
    if EXPORT.exists():
        shutil.rmtree(EXPORT)
    EXPORT.mkdir(parents=True)
    t, meta, m = load()
    print(f"national rows {len(t):,}; topics {t.topic_id.nunique():,}; moments {len(m):,}")
    day_top, day_files = export_days(t, meta)
    print(f"days: {sum(len(v) for v in day_files.values())} files for {len(day_files)} months")
    g = export_global(m)
    print(f"global moments: {len(g)} file(s)")
    ns, nt = export_index(t, meta, day_top, m)
    print(f"topics_index: {nt:,} topics in {ns} shard(s)")
    nc, jac, ccs, X, tc, ti = export_wrapped(t, meta, m)
    print(f"wrapped: {nc} countries")
    cdf = t.groupby("country_code").agg(country_name=("country_name", "first"))
    export_similarity(jac, ccs, X, tc, ti, meta, cdf)
    print("similarity: done")
    export_routine(t, meta)
    print("routine: done")
    print("coverage gaps:", export_coverage(t))
    print(f"hours: {export_hours(t, meta)} files")
    total = sum(f["bytes"] for f in MANIFEST)
    biggest = max(MANIFEST, key=lambda f: f["bytes"])
    (EXPORT / "manifest.json").write_text(json.dumps(
        {"generated_by": "pipeline/05_export.py", "max_bytes": MAX_BYTES, "total_bytes": total, "files": MANIFEST},
        indent=1))
    print(f"{len(MANIFEST)} files, {total / 1e6:.1f} MB total; largest {biggest['file']} {biggest['bytes'] / 1e6:.2f} MB")


if __name__ == "__main__":
    main()
