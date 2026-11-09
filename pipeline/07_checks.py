"""Step 7: data checks before building the site -> docs/CHECKS.md (+ data/interim/work/checks.json).

Each check reports PASS / WARN / FAIL with its key numbers:
  C2  known events: are real events detected as moments, at the right time?
  C3  time zones: does one zone per country distort local-hour findings? (regional feeds, own zones)
  C4  collection artifacts: fixed-UTC spikes, feeds that change size, thin feeds
  C6  sensitivity of the headline numbers to thresholds
  C7  collection gaps: which countries miss days, and does it move the attention twins?
  C8  volume comparability across countries
  C9  cultural-bloc stability (similarity measures, bootstrap)
  C11 export integrity (the site's data contract)
It also writes two hand-review lists: docs/review_sensitive.csv (item 5) and docs/review_types.csv (item 10).
"""
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import sparse
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import squareform
from sklearn.metrics import adjusted_rand_score

sys.path.insert(0, str(Path(__file__).parent))
from common import DOCS, INTERIM, ROOT, WORK, save_json  # noqa: E402

EXPORT = ROOT / "data" / "export"
RESULTS = []          # (id, name, status, summary)
SENS_TIERS = {}
DETAIL = []           # markdown lines


def report(cid, name, status, summary, lines=()):
    RESULTS.append({"id": cid, "check": name, "status": status, "summary": summary})
    DETAIL.append(f"\n## {cid} {name}: **{status}**\n")
    DETAIL.append(summary + "\n")
    DETAIL.extend(lines)
    print(f"[{status}] {cid} {name}: {summary}")


def md_table(df):
    cols = list(df.columns)
    out = ["| " + " | ".join(map(str, cols)) + " |", "|" + "---|" * len(cols)]
    for r in df.itertuples(index=False):
        out.append("| " + " | ".join(str(v).replace("|", "/") for v in r) + " |")
    return out


# ------------------------------------------------------------------ data
def load():
    t = pd.read_parquet(INTERIM / "topics.parquet",
                        columns=["topic_id", "topic_id_combine", "query_norm", "country_code", "location", "level",
                                 "start_time_utc", "local_time", "search_volume_lower", "utc19_bump"])
    meta = pd.read_parquet(INTERIM / "topic_meta.parquet").set_index("topic_id")
    t["category"] = t.topic_id.map(meta.category).fillna("unlabeled")
    nat = t[t.level == "country"].copy()
    nat["lhour"] = nat.local_time.dt.hour
    nat["uhour"] = nat.start_time_utc.dt.hour
    nat["day"] = nat.start_time_utc.dt.strftime("%Y-%m-%d")
    nat["ldate"] = nat.local_time.dt.strftime("%Y-%m-%d")
    nat["vol"] = nat.search_volume_lower.fillna(0)
    reg = t[t.level == "region"]
    m = pd.read_parquet(INTERIM / "moments.parquet")
    cov = json.load(open(EXPORT / "coverage.json"))
    return nat, reg, meta, m, cov


# ------------------------------------------------------------------ C2 known events
# UTC times from public reporting, approximate. tol = minutes allowed between the real time and the
# moment's first trend. Verify each time before quoting it in the article.
EVENTS = [
    ("Meta outage (Facebook, Instagram, WhatsApp)", "2024-12-11 17:50", r"facebook|instagram|whatsapp|messenger", 45),
    ("ChatGPT outage", "2024-12-11 23:10", r"chatgpt|chat gpt|openai", 45),
    ("Jimmy Carter dies (announced)", "2024-12-29 20:50", r"jimmy carter|carter", 45),
    ("Super Bowl LIX (kickoff 23:30; searched all day)", "2025-02-09 23:30", r"super bowl", 900),
    ("Myanmar earthquake", "2025-03-28 06:20", r"myanmar|earthquake|bangkok|sismo|terremoto|gempa", 90),
    ("Pope Francis dies (announced)", "2025-04-21 07:47", r"pope francis|papa francesco|papa francisco|papst|francis|francisco|franciszek", 30),
    ("Iberian blackout (local: ES, PT)", "2025-04-28 10:33", r"apagon|apagao|apagão|apagón|blackout|corte de luz", 60),
    ("White smoke, Pope Leo XIV", "2025-05-08 16:07", r"leo xiv|pope leo|leone xiv|papa leon|fumata|white smoke|conclave|habemus|prevost", 45),
    ("Champions League final PSG-Inter (kickoff 19:00)", "2025-05-31 19:00", r"psg|paris saint|inter|champions league", 900),
    ("Diogo Jota dies (news in the morning)", "2025-07-03 07:00", r"diogo jota|jota", 120),
    ("Ozzy Osbourne dies (announced)", "2025-07-22 17:40", r"ozzy|osbourne", 60),
    ("Hulk Hogan dies (reported)", "2025-07-24 14:50", r"hulk hogan|hogan", 120),
    ("Kamchatka M8.8 earthquake / tsunami", "2025-07-29 23:24", r"tsunami|kamchatka|earthquake|sismo|terremoto|gempa", 90),
    ("Charlie Kirk shot (inside a collection gap)", "2025-09-10 18:20", r"charlie kirk|kirk", 60),
    ("AWS outage", "2025-10-20 07:11", r"aws|amazon web services|amazon down|alexa|snapchat|fortnite|roblox", 90),
    ("Cloudflare outage", "2025-11-18 11:20", r"cloudflare", 30),
]


def check_events(m, cov):
    gaps = [(pd.Timestamp(a, tz="UTC"), pd.Timestamp(b, tz="UTC") + pd.Timedelta(days=1)) for a, b in cov["gaps"]]
    win = m[(m.reach >= 2)]
    rows, n_fail, n_warn = [], 0, 0
    for name, ts, pat, tol in EVENTS:
        t0 = pd.Timestamp(ts, tz="UTC")
        in_gap = any(a <= t0 < b for a, b in gaps)
        c = win[(win.start_utc >= t0 - pd.Timedelta(hours=18)) & (win.start_utc <= t0 + pd.Timedelta(hours=18))]
        phr = c.countries.map(lambda cs: " ".join(str(x["phrasing"]) for x in cs[:10]))
        txt = (c.topic_name.astype(str) + " " + phr).str.lower()
        c = c[txt.str.contains(pat, regex=True)]
        if len(c) == 0:
            status = "WARN" if in_gap else "FAIL"
            rows.append({"event": name, "true_utc": ts, "found": "no" + (" (in gap)" if in_gap else ""),
                         "moment": "", "first_trend_utc": "", "diff_min": "", "reach": "", "min_to_half": "",
                         "status": status})
        else:
            # the moment that starts closest to the true time (reach >= 3), not the biggest one in the window:
            # a person or brand is often already trending before the event
            c3 = c[c.reach >= 3] if (c.reach >= 3).any() else c
            best = c3.iloc[(c3.start_utc - t0).abs().argsort().iloc[0]]
            biggest = c.sort_values("reach", ascending=False).iloc[0]
            diff = (best.start_utc - t0).total_seconds() / 60
            status = "PASS" if abs(diff) <= tol else ("WARN" if abs(diff) <= 3 * tol else "FAIL")
            if in_gap:
                status = "WARN"
            rows.append({"event": name, "true_utc": ts, "found": "yes" + (" (in gap)" if in_gap else ""),
                         "moment": best.topic_name, "first_trend_utc": best.start_utc.strftime("%Y-%m-%d %H:%M"),
                         "diff_min": int(round(diff)), "reach": int(best.reach),
                         "min_to_half": int(best.minutes_to_half),
                         "related_moments": int(((c.start_utc - t0).abs() <= pd.Timedelta(minutes=max(tol, 60))).sum()),
                         "biggest_nearby": f"{biggest.topic_name} ({int(biggest.reach)})", "status": status})
        n_fail += status == "FAIL"
        n_warn += status == "WARN"
    df = pd.DataFrame(rows)
    status = "FAIL" if n_fail > 2 else ("WARN" if n_fail or n_warn else "PASS")
    n_pass = int((df.status == "PASS").sum())
    report("C2", "Known events", status,
           f"{n_pass}/{len(df)} events found within tolerance; {n_warn} warn, {n_fail} fail. The best match is the "
           "moment (reach ≥ 3) starting closest to the true time, among those within ±18 h whose name or phrasings match. True times are approximate "
           "(public reporting): verify them before quoting.",
           md_table(df) + ["", "`diff_min` = first trend − true time. Negative = the topic was already "
                           "trending (e.g. a person in the news before the event). `related_moments` = matching "
                           "moments starting near the true time: a large number means one event is split across "
                           "several topics (\"Pope\", \"New pope\", \"Habemus Papam\"…), so a replay should "
                           "group topics by time window, not show one topic."])
    return df


# ------------------------------------------------------------------ C3 time zones
from common import REGION_TZ  # noqa: E402  (region -> time zone, shared with 05_export)


def check_timezones(reg, cz, meta):
    out, flags = [], 0
    for cc, zones in REGION_TZ.items():
        r = reg[reg.country_code == cc]
        if r.empty:
            continue
        sub = r.location.str.split("-").str[1]
        tz_reg = sub.map(zones).fillna(cz[cc])
        lh_country = r.start_time_utc.dt.tz_convert(cz[cc]).dt.hour
        lh_region = pd.Series(index=r.index, dtype=float)
        for z, idx in tz_reg.groupby(tz_reg).groups.items():
            lh_region.loc[idx] = r.loc[idx, "start_time_utc"].dt.tz_convert(z).dt.hour
        lh_region = lh_region.astype(int)
        moved = float((tz_reg != cz[cc]).mean())
        w = r.category == "weather"

        def stats(h):
            hw = h[w]
            return (float(h.isin(range(0, 5)).mean()), int(hw.value_counts().idxmax()) if len(hw) >= 20 else None,
                    int(h.value_counts().idxmax()))
        n1, wh1, bh1 = stats(lh_country)
        n2, wh2, bh2 = stats(lh_region)
        bad = (abs(n1 - n2) > 0.02) or (wh1 != wh2)
        flags += bad
        out.append({"country": cc, "country_zone": cz[cc], "region_rows": len(r), "rows_in_other_zones": f"{moved:.0%}",
                    "night_share (country zone)": f"{n1:.1%}", "night_share (region zones)": f"{n2:.1%}",
                    "weather_hour (country zone)": wh1, "weather_hour (region zones)": wh2,
                    "busiest_hour": f"{bh1} → {bh2}", "status": "WARN" if bad else "PASS"})
    df = pd.DataFrame(out)
    status = "WARN" if flags else "PASS"
    report("C3", "One time zone per country", status,
           f"{flags} of {len(df)} multi-zone countries change their night share by > 2 points or their weather hour "
           "when regional feeds use their own zones. Kazakhstan has no regional feeds, but the zone database is "
           "current (Asia/Almaty = UTC+5 since March 2024).",
           md_table(df) + ["", "Computed on the regional feeds (national feeds have no location). Countries with "
                           "PASS can quote national-feed local-hour figures; WARN countries need a caveat or "
                           "region-based numbers."])
    return df


# ------------------------------------------------------------------ C4 collection artifacts
def check_artifacts(nat, cov):
    lines, warn = [], []
    # minute grid
    mins = nat.start_time_utc.dt.minute
    grid10 = float((mins % 10 == 0).mean())
    lines.append(f"- Start minutes on a 10-minute grid: {grid10:.1%} (the scraper's resolution, so ties of "
                 "a few minutes are not meaningful).")
    # peaks at local night: is it the same UTC hour across countries?
    pk = nat.groupby(["country_code", "lhour"]).size().unstack(fill_value=0)
    peak_local = pk.idxmax(axis=1)
    pku = nat.groupby(["country_code", "uhour"]).size().unstack(fill_value=0)
    peak_utc = pku.idxmax(axis=1)
    share_peak = (pku.max(axis=1) / pku.sum(axis=1))
    night = peak_local[peak_local.isin(range(0, 5))]
    tab = pd.DataFrame({"country": night.index, "peak_local_hour": night.values,
                        "peak_utc_hour": peak_utc.loc[night.index].values,
                        "share_in_peak_utc_hour": share_peak.loc[night.index].map("{:.1%}".format).values})
    lines.append(f"- Countries whose busiest local hour is 00–04: {len(night)}.")
    if len(night):
        lines += [""] + md_table(tab) + [""]
        same_utc = tab.peak_utc_hour.value_counts()
        if len(night) >= 3 and same_utc.iloc[0] >= 3:
            lines.append(f"  {same_utc.iloc[0]} of them peak at the same UTC hour ({same_utc.index[0]}:00), which "
                         "suggests a collection batch rather than behaviour. Treat their night share with care.")
            warn.append("night peaks share a UTC hour")
    # the 19:00 UTC excess: one UTC hour with far more trend starts than its neighbours
    sh = pku.div(pku.sum(axis=1), axis=0)
    excess = sh - (sh.shift(1, axis=1) + sh.shift(-1, axis=1)) / 2
    at19 = excess[19]
    hit = at19[at19 > 0.03]
    lines.append(f"- Countries with an excess of > 3 points of all trends starting in the 19:00 UTC hour (vs. "
                 f"the mean of 18:00 and 20:00): **{len(hit)}** of {len(sh)} (median excess {at19.median():.1%}). "
                 "19:00 UTC is 21:00 in Berlin, the collector's clock; the excess is steady every month, which "
                 "points to a daily collection pass rather than behaviour.")
    corr = pku.copy().astype(float)
    corr[19] = (pku[18] + pku[20]) / 2
    rows = []
    for cc in sorted(pk.index):
        off = nat[nat.country_code == cc]
        if off.empty:
            continue
        shift = int(round((off.local_time - off.start_time_utc.dt.tz_localize(None)).dt.total_seconds().median() / 3600))
        # both histograms go through the same UTC -> local shift (median offset), so only the 19:00 fix differs
        lh_s = pd.Series({(u + shift) % 24: corr.loc[cc, u] for u in range(24)}).sort_index()
        lh_r = pd.Series({(u + shift) % 24: pku.loc[cc, u] for u in range(24)}).sort_index()
        night_c = lh_s.loc[[0, 1, 2, 3, 4]].sum() / lh_s.sum()
        night_raw = lh_r.loc[[0, 1, 2, 3, 4]].sum() / lh_r.sum()
        rows.append({"country": cc, "busiest_hour": int(lh_r.idxmax()), "busiest_hour_corrected": int(lh_s.idxmax()),
                     "night_share": f"{night_raw:.1%}", "night_share_corrected": f"{night_c:.1%}"})
    cdf = pd.DataFrame(rows)
    moved = cdf[cdf.busiest_hour != cdf.busiest_hour_corrected]
    lines.append(f"- With the 19:00 UTC hour replaced by the mean of its neighbours, {len(moved)} countries change "
                 "their busiest local hour; night shares move by at most "
                 f"{(cdf.night_share.str.rstrip('%').astype(float) - cdf.night_share_corrected.str.rstrip('%').astype(float)).abs().max():.1f} "
                 "points. Busiest hour is fragile; night share is not. Countries that change:")
    lines += [""] + md_table(moved) + [""]
    # the utc19_bump flag (trends starting 19:00-19:59 UTC): busiest hour with and without them
    nb = nat[~nat.utc19_bump]
    w_all, w_no = nat.uhour.value_counts(), nb.uhour.value_counts()
    l_all, l_no = nat.lhour.value_counts(), nb.lhour.value_counts()
    lines.append(f"- Flag `utc19_bump` (in `topics.parquet`; data unchanged): {int(nat.utc19_bump.sum()):,} national "
                 f"trends ({nat.utc19_bump.mean():.1%}) start in the 19:00 UTC hour (1/24 = 4.2% if even).")
    lines.append(f"- Busiest hour worldwide, all trends: **{w_all.idxmax()}:00 UTC** ({w_all.max() / len(nat):.1%}); "
                 f"without flagged trends: **{w_no.idxmax()}:00 UTC** ({w_no.max() / len(nb):.1%}). "
                 f"By local time: {l_all.idxmax()}:00 with all trends, {l_no.idxmax()}:00 without.")
    pa_ = nat.groupby(["country_code", "lhour"]).size().unstack(fill_value=0).idxmax(axis=1)
    pn_ = nb.groupby(["country_code", "lhour"]).size().unstack(fill_value=0).idxmax(axis=1)
    ch = pd.DataFrame({"country": pa_.index, "busiest_local_hour_all": pa_.values,
                       "busiest_local_hour_without_19utc": pn_.reindex(pa_.index).values})
    ch = ch[ch.busiest_local_hour_all != ch.busiest_local_hour_without_19utc]
    lines.append(f"- Countries whose busiest local hour changes when flagged trends are left out: **{len(ch)}** "
                 f"of {len(pa_)}.")
    if len(ch):
        lines += [""] + md_table(ch) + [""]
    if len(hit) >= 5:
        warn.append(f"19:00 UTC collection excess in {len(hit)} feeds")
    # spiky UTC hours: any country with > 25% of trends in one UTC hour
    spiky = share_peak[share_peak > 0.25]
    lines.append(f"- Countries with > 25% of all trends in a single UTC hour: {len(spiky)} "
                 f"{', '.join(f'{c} ({v:.0%})' for c, v in spiky.items())}")
    if len(spiky):
        warn.append("spiky UTC hours")
    # feed size over time
    gapdays = {d for d, g in zip(cov["days"], cov["is_gap"]) if g}
    n2 = nat[~nat.day.isin(gapdays)]
    n2 = n2.assign(month=n2.day.str[:7])
    mon = n2.groupby(["country_code", "month"]).size().unstack(fill_value=0)
    ndays = n2.groupby("month").day.nunique()
    per_day = mon / ndays
    med = per_day.median(axis=1)
    low = (per_day.lt(0.3 * med, axis=0)).sum(axis=1)
    trend = (per_day.iloc[:, -4:-1].mean(axis=1) / per_day.iloc[:, 1:4].mean(axis=1)).replace([np.inf], np.nan)
    unstable = pd.DataFrame({"country": med.index, "median_trends_per_day": med.round(1).values,
                             "months_below_30pct": low.values, "last3_vs_first3": trend.round(2).values})
    flag = unstable[(unstable.months_below_30pct >= 2) | (unstable.last3_vs_first3 < 0.5) | (unstable.last3_vs_first3 > 2)]
    lines.append(f"- Feeds whose size changes over time (≥ 2 months below 30% of their median, or the last 3 "
                 f"months < 0.5× or > 2× the first 3): {len(flag)}")
    if len(flag):
        lines += [""] + md_table(flag) + [""]
        warn.append("unstable feeds")
    thin = unstable[unstable.median_trends_per_day < 5].sort_values("median_trends_per_day")
    lines.append(f"- Thin feeds (median < 5 trends per covered day): {len(thin)} "
                 f"{', '.join(f'{c} ({v})' for c, v in zip(thin.country, thin.median_trends_per_day))}. Wrapped "
                 "stats for these rest on few trends; show them with a caveat or hide percentage stats.")
    if len(thin):
        warn.append("thin feeds")
    status = "WARN" if warn else "PASS"
    report("C4", "Collection artifacts", status, "; ".join(warn) if warn else "no artifacts found", lines)
    return {"thin": thin.country.tolist(), "unstable": flag.country.tolist(), "night_peaks": tab}


# ------------------------------------------------------------------ C6 sensitivity
def global_count(m, n_min, win, non_sport=False):
    c = m[m.reach >= n_min]
    if non_sport:
        c = c[~c.is_sport] if "is_sport" in c.columns else c[~c.type.isin(["sports_match", "team"])]
    def ok(cs):
        third = cs[2]["min_from_start"]
        return sum(1 for x in cs if x["min_from_start"] <= third + win) >= n_min
    return c[c.countries.map(ok)]


def check_sensitivity(nat, m, meta):
    lines, notes = [], []
    # (a) share of single-country topics
    def share(col, d=nat):
        r = d.groupby(col).country_code.nunique()
        return (r == 1).mean()
    trends = nat.groupby("topic_id").size()
    multi_trend = nat[nat.topic_id.map(trends) >= 3]
    r_t = nat.groupby("topic_id").country_code.nunique()
    variants = {
        "topics (current)": share("topic_id"),
        "topics before linking": share("topic_id_combine"),
        "no merging (query_norm)": share("query_norm"),
        "topics with ≥ 3 trends only": share("topic_id", multi_trend),
        "share of trends in single-country topics": float((nat.topic_id.map(r_t) == 1).mean()),
    }
    vals = list(variants.values())[:4]
    lines.append("**Single-country topics** (headline: ~85%)\n")
    lines += md_table(pd.DataFrame({"definition": variants.keys(), "share": [f"{v:.1%}" for v in variants.values()]}))
    spread = max(vals) - min(vals)
    lines.append(f"\nRange across topic definitions: {min(vals):.1%}–{max(vals):.1%}. Weighted by trends instead "
                 f"of topics it is {variants['share of trends in single-country topics']:.1%}: say which one you mean.\n")
    if spread > 0.10:
        notes.append("single-country share depends on the definition")

    # (b) global moment rule grid
    grid = []
    for n_min in (10, 15, 20, 25):
        for win in (30, 60, 120):
            g = global_count(m, n_min, win)
            grid.append({"min_countries": n_min, "window_min": win, "global": len(g),
                         "non_sport": int((~g.type.isin(["sports_match", "team"])).sum())})
    gdf = pd.DataFrame(grid)
    lines.append("**Global-moment rule** (current: 15 countries within 60 min of the third)\n")
    lines += md_table(gdf.pivot(index="min_countries", columns="window_min", values="global").reset_index()
                      .rename(columns=lambda c: f"{c} min" if isinstance(c, (int, np.integer)) else c))
    lines.append("\nNon-sport global moments under the same grid:\n")
    lines += md_table(gdf.pivot(index="min_countries", columns="window_min", values="non_sport").reset_index()
                      .rename(columns=lambda c: f"{c} min" if isinstance(c, (int, np.integer)) else c))
    base = gdf[(gdf.min_countries == 15) & (gdf.window_min == 60)].iloc[0]
    lines.append(f"\nThe count is threshold-dependent by construction (e.g. {gdf.non_sport.min():,}–"
                 f"{gdf.non_sport.max():,} non-sport moments across the grid). Quote it with the rule "
                 f"(\"{base.non_sport:,} non-sport moments reached 15+ countries within an hour\").\n")

    # (c) rank of 11 Dec 2024
    rk = []
    for n_min, win in ((10, 60), (15, 60), (20, 120), (15, 30)):
        g = global_count(m, n_min, win, non_sport=True).copy()
        g["day"] = g.start_utc.dt.strftime("%Y-%m-%d")
        g["r60"] = g.countries.map(lambda cs: sum(1 for x in cs if x["min_from_start"] <= cs[2]["min_from_start"] + win))
        by = g.groupby("day").agg(sum_reach=("r60", "sum"), moments=("r60", "size"),
                                  countries=("countries", lambda s: len({x["country_code"] for cs in s for x in cs})))
        for metric in ("sum_reach", "moments", "countries"):
            order = by[metric].sort_values(ascending=False)
            rank = list(order.index).index("2024-12-11") + 1 if "2024-12-11" in order.index else None
            rk.append({"rule": f"{n_min}/{win} min", "metric": metric, "rank of 2024-12-11": rank,
                       "top day": order.index[0]})
    rdf = pd.DataFrame(rk)
    lines.append("**Rank of 11 Dec 2024 among days of non-sport global moments**\n")
    lines += md_table(rdf)
    ranks = rdf["rank of 2024-12-11"].dropna()
    lines.append(f"\nRank range: {int(ranks.min())}–{int(ranks.max())}. Players count as non-sport here "
                 "(Claude type `person`), which is why tennis and football finals still top the list.\n")
    if ranks.min() > 1:
        notes.append("11 Dec is never #1, even outside sport")

    # (d) weather hour
    w = nat[nat.category == "weather"]
    clear = w[w.topic_id.map(meta.topic_name).fillna("").str.lower().str.contains(
        r"weather|forecast|clima|meteo|tiempo|tempo|wetter|pogoda|погод|hava|cuaca|thoi tiet|天気|天氣|날씨|طقس|मौसम")]
    wv = []
    for label, d, mn in (("all weather, ≥ 20 trends", w, 20), ("all weather, ≥ 50 trends", w, 50),
                         ("forecast-type names only, ≥ 20", clear, 20)):
        h = d.groupby(["country_code", "lhour"]).size().unstack(fill_value=0)
        h = h[h.sum(axis=1) >= mn]
        pk = h.idxmax(axis=1)
        wv.append({"definition": label, "countries": len(h), "peak at 6": int((pk == 6).sum()),
                   "peak 5–7": int(pk.isin([5, 6, 7]).sum()), "peak 19–21": int(pk.isin([19, 20, 21]).sum())})
    lines.append("**Weather hour** (headline: most countries at 6 a.m.)\n")
    lines += md_table(pd.DataFrame(wv))

    # (e) night share definitions
    nd = []
    for label, hrs in (("00–04", range(0, 5)), ("23–03", [23, 0, 1, 2, 3]), ("01–05", range(1, 6))):
        s = nat.groupby("country_code").lhour.apply(lambda x: x.isin(list(hrs)).mean()).sort_values(ascending=False)
        nd.append({"night": label, "top 5 night owls": ", ".join(f"{c} {v:.0%}" for c, v in s.head(5).items()),
                   "bottom 3": ", ".join(f"{c} {v:.0%}" for c, v in s.tail(3).items())})
    lines.append("\n**Night-owl ranking under three definitions of night**\n")
    lines += md_table(pd.DataFrame(nd))

    status = "WARN" if notes else "PASS"
    report("C6", "Sensitivity of headline numbers", status,
           "; ".join(notes) if notes else "headline numbers are stable", lines)


# ------------------------------------------------------------------ C7 gaps
def jaccard_twins(d):
    tc = d[["country_code", "topic_id"]].drop_duplicates()
    ccs = sorted(tc.country_code.unique())
    ci = {c: i for i, c in enumerate(ccs)}
    ti = {t: i for i, t in enumerate(tc.topic_id.unique())}
    X = sparse.csr_matrix((np.ones(len(tc)), (tc.country_code.map(ci), tc.topic_id.map(ti))), shape=(len(ccs), len(ti)))
    inter = (X @ X.T).toarray()
    sz = np.asarray(X.sum(1)).ravel()
    J = inter / np.maximum(sz[:, None] + sz[None, :] - inter, 1)
    np.fill_diagonal(J, -1)
    return {c: ccs[int(np.argmax(J[i]))] for c, i in ci.items()}, X, ccs


def check_gaps(nat, cov):
    per = pd.DataFrame(cov["per_country"], index=cov["countries"], columns=cov["days"]).T
    reporting = (per > 0).mean(axis=1)
    normal = per[reporting >= 0.8]
    miss = (normal == 0).mean().sort_values(ascending=False)
    bad = miss[miss > 0.10]
    lines = [f"- Days where ≥ 80% of countries report: {len(normal)} of {len(per)}.",
             f"- Countries missing > 10% of those days: {len(bad)} "
             f"{', '.join(f'{c} ({v:.0%})' for c, v in bad.items())}"]
    clean_days = set(per.index[reporting >= 0.95])
    t_all, _, _ = jaccard_twins(nat)
    t_clean, _, _ = jaccard_twins(nat[nat.day.isin(clean_days)])
    agree = np.mean([t_all[c] == t_clean.get(c) for c in t_all])
    lines.append(f"- Attention twins recomputed on the {len(clean_days)} days where ≥ 95% of countries report: "
                 f"{agree:.0%} of countries keep the same twin.")
    changed = [f"{c}: {t_all[c]}→{t_clean.get(c)}" for c in t_all if t_all[c] != t_clean.get(c)]
    if changed:
        lines.append(f"  Changed: {', '.join(changed[:30])}{' …' if len(changed) > 30 else ''}")
    status = "PASS" if agree >= 0.8 and len(bad) <= 5 else "WARN"
    report("C7", "Collection gaps", status,
           f"{len(bad)} countries miss > 10% of normal days; {agree:.0%} of attention twins survive using only "
           "full-coverage days.", lines)
    return t_all


# ------------------------------------------------------------------ C8 volume
def check_volume(nat):
    med = nat.groupby("country_code").vol.median().sort_values()
    lines = [f"- Median volume bucket per country ranges from {med.iloc[0]:,.0f} ({med.index[0]}) to "
             f"{med.iloc[-1]:,.0f} ({med.index[-1]}): {med.iloc[-1] / max(med.iloc[0], 1):.0f}× apart. "
             "Buckets are lower bounds of Google's ranges and scale with country size."]
    d = nat.groupby(["ldate", "country_code", "topic_id"]).agg(vol=("vol", "sum"), n=("vol", "size")).reset_index()
    a = d.sort_values(["vol", "n"], ascending=False).drop_duplicates(["ldate", "country_code"])
    b = d.sort_values(["n", "vol"], ascending=False).drop_duplicates(["ldate", "country_code"])
    a_s = a.set_index(["ldate", "country_code"]).topic_id.sort_index()
    b_s = b.set_index(["ldate", "country_code"]).topic_id.reindex(a_s.index)
    agree = float((a_s == b_s).mean())
    lines.append(f"- Within a country, the day's #1 topic by summed volume equals the #1 by number of trends on "
                 f"{agree:.0%} of country-days.")
    lines.append("- Exports that rank across countries use reach (country counts), not volume: global moments, "
                 "topics_index (`reach`, `trends`). `peak_volume` in moments is a max over countries: don't "
                 "compare it across moments as 'size'. Daily and hourly top topics rank within a country only.")
    report("C8", "Volume comparability", "PASS" if agree >= 0.6 else "WARN",
           "volume is only compared within a country; cross-country exports use reach", lines)


# ------------------------------------------------------------------ C9 blocs
def check_blocs(nat, meta, k=15, boots=20, seed=7):
    tc = nat[["country_code", "topic_id"]].drop_duplicates()
    ccs = sorted(tc.country_code.unique())
    ci = {c: i for i, c in enumerate(ccs)}
    tids = tc.topic_id.unique()
    ti = {t: i for i, t in enumerate(tids)}
    X = sparse.csr_matrix((np.ones(len(tc)), (tc.country_code.map(ci), tc.topic_id.map(ti))),
                          shape=(len(ccs), len(ti))).tocsc()
    # only topics shared by >= 2 countries carry similarity signal
    df_ = np.asarray(X.sum(0)).ravel()
    X = X[:, np.where(df_ >= 2)[0]].tocsr()
    df_ = df_[df_ >= 2]

    def sims(M, dfv):
        inter = (M @ M.T).toarray()
        sz = np.asarray(M.sum(1)).ravel()
        jac = inter / np.maximum(sz[:, None] + sz[None, :] - inter, 1)
        ovl = inter / np.maximum(np.minimum(sz[:, None], sz[None, :]), 1)
        idf = np.log(len(ccs) / dfv)
        W = M.multiply(idf).tocsr()
        nrm = np.sqrt(np.asarray(W.multiply(W).sum(1)).ravel())
        cos = (W @ W.T).toarray() / np.maximum(np.outer(nrm, nrm), 1e-9)
        return {"jaccard": jac, "overlap": ovl, "tfidf_cosine": cos}

    def clusters(S):
        D = 1 - S.copy()
        np.fill_diagonal(D, 0)
        D = np.clip((D + D.T) / 2, 0, None)
        return fcluster(linkage(squareform(D, checks=False), method="average"), k, criterion="maxclust")

    def twins(S):
        S = S.copy()
        np.fill_diagonal(S, -1)
        return np.argmax(S, axis=1)

    S = sims(X, df_)
    base_c, base_t = clusters(S["jaccard"]), twins(S["jaccard"])
    rows = []
    for name, M in S.items():
        rows.append({"similarity": name, "twin agreement vs Jaccard": f"{np.mean(twins(M) == base_t):.0%}",
                     f"ARI of {k} clusters vs Jaccard": f"{adjusted_rand_score(base_c, clusters(M)):.2f}"})
    rng = np.random.default_rng(seed)
    aris, tw = [], []
    for _ in range(boots):
        cols = rng.integers(0, X.shape[1], X.shape[1])
        Mb = X[:, cols]
        Sb = sims(Mb, df_[cols])["jaccard"]
        aris.append(adjusted_rand_score(base_c, clusters(Sb)))
        tw.append(np.mean(twins(Sb) == base_t))
    # football-free
    cat = pd.Series(tids).map(meta.category).fillna("unlabeled").values
    keep_cols = np.where(np.isin(cat, ["sports_match", "team"]) == False)[0]  # noqa: E712
    Xn = sparse.csr_matrix((np.ones(len(tc)), (tc.country_code.map(ci), tc.topic_id.map(ti))),
                           shape=(len(ccs), len(ti))).tocsc()[:, keep_cols]
    dn = np.asarray(Xn.sum(0)).ravel()
    Xn = Xn[:, np.where(dn >= 2)[0]].tocsr()
    Sn = sims(Xn, dn[dn >= 2])["jaccard"]
    rows.append({"similarity": "jaccard without football", "twin agreement vs Jaccard": f"{np.mean(twins(Sn) == base_t):.0%}",
                 f"ARI of {k} clusters vs Jaccard": f"{adjusted_rand_score(base_c, clusters(Sn)):.2f}"})
    ari_m, tw_m = float(np.mean(aris)), float(np.mean(tw))
    lines = md_table(pd.DataFrame(rows)) + [
        "", f"- Bootstrap ({boots}× resampled topics): mean ARI of clusters {ari_m:.2f} "
            f"(min {min(aris):.2f}); twins kept {tw_m:.0%}.",
        f"- Clusters ({k}, Jaccard, average linkage):"]
    for cl in sorted(set(base_c)):
        members = [ccs[i] for i in np.where(base_c == cl)[0]]
        lines.append(f"  - {' '.join(members)}")
    lines.append("\nOnly blocs that survive both the bootstrap and a second measure belong in the story. "
                 "Singleton clusters are countries that resemble no bloc.")
    status = "PASS" if ari_m >= 0.7 else ("WARN" if ari_m >= 0.5 else "FAIL")
    report("C9", "Cultural-bloc stability", status,
           f"bootstrap ARI {ari_m:.2f}, twins kept {tw_m:.0%}; see the table for other similarity measures", lines)


# ------------------------------------------------------------------ C11 exports
def _strict_load(p):
    def bad(x):
        raise ValueError(f"invalid JSON constant {x}")
    return json.loads(p.read_text(), parse_constant=bad)


def check_exports():
    errs, n = [], 0
    files = sorted(EXPORT.rglob("*.json"))
    objs = {}
    for p in files:
        n += 1
        rel = str(p.relative_to(EXPORT))
        if p.stat().st_size > 2_000_000:
            errs.append(f"{rel}: {p.stat().st_size:,} bytes > 2 MB")
        try:
            objs[rel] = _strict_load(p)
        except Exception as e:  # noqa: BLE001
            errs.append(f"{rel}: {e}")
    wrapped = [k for k in objs if k.startswith("wrapped/") and k != "wrapped/index.json"]
    countries = set(objs.get("similarity.json", {}).get("countries", []))
    if len(wrapped) != len(countries):
        errs.append(f"wrapped cards {len(wrapped)} != countries {len(countries)}")
    need = ["uniquely_local", "busiest_day", "attention_twin", "weather_hour", "night_share", "global_moments",
            "top_topic_per_month", "hour_histogram"]
    for k in wrapped:
        miss = [f for f in need if f not in objs[k]]
        if miss:
            errs.append(f"{k}: missing {miss}")
        tw = objs[k].get("attention_twin", {}).get("country_code")
        if tw not in countries:
            errs.append(f"{k}: twin {tw} not a country")
    for k, o in objs.items():
        if k.startswith("days/"):
            nt = len(o["topics"])
            for d, by in o["days"].items():
                for cc, lst in by.items():
                    if cc not in countries:
                        errs.append(f"{k} {d}: unknown country {cc}")
                    if any(not (0 <= x[0] < nt) for x in lst):
                        errs.append(f"{k} {d} {cc}: topic index out of range")
                    if len(lst) > 10:
                        errs.append(f"{k} {d} {cc}: {len(lst)} > 10 topics")
        if k.startswith("hours/"):
            nc, nt = len(o["countries"]), len(o["topics"])
            if len(o["top"]) != len(o["hours"]):
                errs.append(f"{k}: top rows {len(o['top'])} != hours {len(o['hours'])}")
            for row in o["top"]:
                if len(row) != nc or any(not (-1 <= x < nt) for x in row):
                    errs.append(f"{k}: malformed hour row")
                    break
        if k.startswith("moments_global/") or (k == "moments_global.json" and "moments" in o):
            for mo in o["moments"]:
                if any(c[0] not in countries for c in mo["timeline"]):
                    errs.append(f"{k}: moment {mo['id']} has unknown country")
                    break
                if not isinstance(mo.get("is_sport"), bool):
                    errs.append(f"{k}: moment {mo['id']} has no boolean is_sport")
                    break
                if mo["reach_60"] < 15:
                    errs.append(f"{k}: moment {mo['id']} reach_60 < 15")
                    break
        if k.startswith("topics_index/") or (k == "topics_index.json" and "topics" in o):
            nf = len(o["fields"])
            if any(len(r) != nf for r in o["topics"]):
                errs.append(f"{k}: row length != fields")
    sim = objs.get("similarity.json")
    if sim:
        J = np.array(sim["jaccard"])
        if J.shape != (len(countries), len(countries)) or not np.allclose(J, J.T) or not np.allclose(np.diag(J), 1):
            errs.append("similarity.json: matrix not square/symmetric/unit-diagonal")
    rt = objs.get("routine.json")
    if rt:
        for c, rows in rt["countries"].items():
            if len(rows) != len(rt["series"]) or any(len(r) != 24 for r in rows):
                errs.append(f"routine.json {c}: wrong shape")
                break
    cv = objs.get("coverage.json")
    if cv and (len(cv["total"]) != len(cv["days"]) or len(cv["per_country"]) != len(cv["countries"])):
        errs.append("coverage.json: length mismatch")
    report("C11", "Export integrity", "FAIL" if errs else "PASS",
           f"{n} files checked; {len(errs)} problems", [f"- {e}" for e in errs[:50]] or ["- none"])


# ------------------------------------------------------------------ hand-review lists (items 5, 10)
SENSITIVE_RE = (r"murder|\bkill(?:ed|ing|s)?\b|shooting|\bshot\b|stabb|\barrest|\brape\b|\braped\b|sexual|assault|"
                r"suicide|dead body|found dead|\bdied\b|\bdeath\b|obituary|\bmissing\b|kidnap|\babuse|victim|"
                r"accident|\bcrash|\bleak(?:ed|s)?\b|\bnude|naked|\bporn|onlyfans|\bsex\b|\bxxx\b|scandal|"
                r"viral video|video viral|asesinato|asesinad|\bmuerto|\bmuere\b|falleci|homicid|feminicid|"
                r"desaparecid|violad|vazad|\bmorte\b|\bmorre\b|assassin|\bmord\b|getötet|"
                r"قتل|مقتل|وفاة|فضيحة|اغتصاب|убийств|погиб|умер")


def review_lists(nat, meta):
    t = nat.groupby("topic_id").agg(trends=("vol", "size"), reach=("country_code", "nunique"),
                                    countries=("country_code", lambda s: " ".join(sorted(set(s))[:5])))
    t = t.join(meta[["topic_name", "type", "category"]])
    shown, on_card = set(), set()
    for p in (EXPORT / "wrapped").glob("*.json"):
        if p.name == "index.json":
            continue
        o = json.load(open(p))
        shown |= {u["topic_id"] for u in o["uniquely_local"]}
        shown |= {u["topic_id"] for u in o["busiest_day"]["top_topics"]}
        shown |= {u["topic_id"] for u in o["top_topic_per_month"]}
        on_card |= {u["topic_id"] for u in o["uniquely_local"]} | {u["topic_id"] for u in o["busiest_day"]["top_topics"]} \
            | {u["topic_id"] for u in o["top_topic_per_month"]}
    for p in (EXPORT / "days").glob("*.json"):
        o = json.load(open(p))
        used = {x[0] for by in o["days"].values() for lst in by.values() for x in lst[:3]}
        shown |= {o["topics"][i][0] for i in used}
    top_q = nat.groupby(["topic_id", "query_norm"]).size().reset_index(name="k") \
        .sort_values("k", ascending=False).drop_duplicates("topic_id").set_index("topic_id").query_norm
    t["top_string"] = t.index.map(top_q)
    txt = (t.topic_name.fillna("") + " | " + t.top_string.fillna("")).str.lower()
    t["flag_keywords"] = txt.str.contains(SENSITIVE_RE, regex=True)
    t["flag_private_person"] = (t.type == "person") & (t.reach <= 2) & (t.trends <= 3)
    t["shown_on_site"] = t.index.isin(shown)
    sens = t[t.shown_on_site & (t.flag_keywords | t.flag_private_person)].copy()
    sens["reason"] = np.where(sens.flag_keywords & sens.flag_private_person, "keywords + low-reach person",
                              np.where(sens.flag_keywords, "keywords", "low-reach person"))
    sens["where"] = np.where(sens.index.isin(on_card), "wrapped card", "daily top 3")
    sens["priority"] = np.select(
        [sens.flag_keywords & (sens["where"] == "wrapped card"),
         sens.flag_keywords | (sens["where"] == "wrapped card")], [1, 2], 3)
    sens = sens.sort_values(["priority", "trends"], ascending=[True, False])
    sens["decision"] = ""
    sens.reset_index()[["priority", "topic_id", "topic_name", "top_string", "type", "reach", "trends", "countries",
                        "where", "reason", "decision"]].to_csv(DOCS / "review_sensitive.csv", index=False)
    global SENS_TIERS
    SENS_TIERS = sens.priority.value_counts().sort_index().to_dict()
    # 100 type checks: 10 per type, among topics shown on the site, weighted toward bigger ones
    rng = np.random.default_rng(3)
    pool = t[t.shown_on_site & t.type.notna()]
    picks = []
    for ty, g in pool.groupby("type"):
        w = np.sqrt(g.trends.values.astype(float))
        n = min(10, len(g))
        idx = rng.choice(len(g), n, replace=False, p=w / w.sum())
        picks.append(g.iloc[idx])
    tp = pd.concat(picks).reset_index()
    tp["correct_type"] = ""
    tp[["topic_id", "topic_name", "top_string", "type", "category", "reach", "trends", "countries", "correct_type"]] \
        .to_csv(DOCS / "review_types.csv", index=False)
    return len(sens), int(sens.reason.str.contains("person").sum()), len(tp)


# ------------------------------------------------------------------ main
def main():
    nat, reg, meta, m, cov = load()
    cz = json.load(open(INTERIM / "country_timezones.json"))
    print(f"national rows {len(nat):,}; region rows {len(reg):,}; moments {len(m):,}")
    check_events(m, cov)
    check_timezones(reg, cz, meta)
    check_artifacts(nat, cov)
    check_sensitivity(nat, m, meta)
    check_gaps(nat, cov)
    check_volume(nat)
    check_blocs(nat, meta)
    check_exports()
    n_sens, n_priv, n_types = review_lists(nat, meta)

    head = ["# Data checks", "",
            "_Generated by `pipeline/07_checks.py`. Re-run after any pipeline change (`make checks`)._", "",
            "| check | status | summary |", "|---|---|---|"]
    for r in RESULTS:
        head.append(f"| {r['id']} {r['check']} | **{r['status']}** | {r['summary']} |")
    head += ["", "## Hand-review lists", "",
             f"- `docs/review_sensitive.csv`: {n_sens} topics shown on the site (Wrapped cards, daily top 3) "
             f"that match crime/death/sexual keywords or look like private people ({n_priv} low-reach persons). "
             f"Fill `decision` with keep or hide. Priority 1 = crime/death/sexual keywords on a Wrapped card "
             f"({SENS_TIERS.get(1, 0)}); 2 = keywords in a daily top 3, or a low-reach person on a Wrapped card "
             f"({SENS_TIERS.get(2, 0)}); 3 = low-reach persons only in daily top 3 ({SENS_TIERS.get(3, 0)}, mostly "
             "athletes and local public figures: reviewing these is optional).",
             f"- `docs/review_types.csv`: {n_types} topics (up to 10 per Claude type, bigger topics more likely). "
             "Fill `correct_type`; leave it blank if the type is right.",
             "- `docs/validation_sample.csv`: 200 string pairs (75 merged, 25 linked, 100 different). Fill "
             "`same_topic_label` with 1/0, then `make score`."]
    (DOCS / "CHECKS.md").write_text("\n".join(head + DETAIL) + "\n")
    save_json(WORK / "checks.json", RESULTS)
    print(f"wrote {DOCS / 'CHECKS.md'}")


if __name__ == "__main__":
    main()
