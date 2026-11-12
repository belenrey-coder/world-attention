"""Step 8: data for the article -> data/export/story/ (one JSON per chapter, every file < 1 MB) and
docs/STORY_NUMBERS.md (every number the article quotes, with its source file and key).

Reads only earlier outputs: data/interim/{topics,moments,topic_meta}.parquet, work/string_topics.parquet,
data/export/coverage.json and data/export/wrapped/ (step 5). National feeds unless stated.

Sensitive topics follow step 5 (pipeline/05_export.py `visibility`): hidden topics never appear in lists,
examples or the time machine, and Wrapped keeps step 5's card choices (which also skip accident, crash,
shooting and death events). Example lists for local topics also leave out people, since small local
person-topics can be private individuals.

Kinds (shock / appointment / wave / ritual / local) are rule-based, from the Claude type plus timing; the
rules are the ones in docs/STORY_CANDIDATES.md (see KIND RULES below). A topic whose biggest moment reached
< 15 countries is "local" unless it is a ritual.
"""
import importlib.util
import json
import warnings
import math
import re
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", message="This pattern is interpreted as a regular expression")
sys.path.insert(0, str(Path(__file__).parent))
from common import DOCS, INTERIM, REGION_TZ, ROOT, WORK  # noqa: E402

EXPORT = ROOT / "data" / "export"
OUT = EXPORT / "story"
MAX_BYTES = 1_000_000
NUMBERS = []          # (chapter, label, value, file, key)
WRITTEN = []


def load_export_module():
    spec = importlib.util.spec_from_file_location("export05", Path(__file__).parent / "05_export.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def dumps(o):
    return json.dumps(o, ensure_ascii=False, separators=(",", ":"), default=str)


def write(rel, obj):
    b = dumps(obj).encode()
    if len(b) > MAX_BYTES:
        raise ValueError(f"{rel}: {len(b):,} bytes > {MAX_BYTES:,}")
    p = OUT / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b)
    WRITTEN.append((rel, len(b)))


def num(chapter, label, value, file, key):
    NUMBERS.append((chapter, label, value, file, key))
    return value


def fmt(v):
    if isinstance(v, float):
        return f"{v:.1%}" if 0 <= v <= 1 else f"{v:,.1f}"
    if isinstance(v, (int, np.integer)):
        return f"{int(v):,}"
    return str(v)


def iso(ts):
    return None if ts is None or pd.isna(ts) else pd.Timestamp(ts).strftime("%Y-%m-%dT%H:%MZ")


# ------------------------------------------------------------------ load
print("loading ...", flush=True)
ex = load_export_module()
cols = ["topic_id", "country_code", "country_name", "level", "location", "start_time_utc", "end_time_utc",
        "duration_minutes", "local_time", "query_raw", "search_volume_lower", "utc19_bump"]
allrows = pd.read_parquet(INTERIM / "topics.parquet", columns=cols)
allrows = allrows[allrows.topic_id.notna()]
t = allrows[allrows.level == "country"].copy()
t["vol"] = t.search_volume_lower.fillna(0)
t["day"] = t.start_time_utc.dt.strftime("%Y-%m-%d")
t["month"] = t.start_time_utc.dt.strftime("%Y-%m")
t["ldate"] = t.local_time.dt.strftime("%Y-%m-%d")
t["lmonth"] = t.ldate.str[:7]
t["lhour"] = t.local_time.dt.hour
meta = pd.read_parquet(INTERIM / "topic_meta.parquet").set_index("topic_id")
t["category"] = t.topic_id.map(meta.category).fillna("unlabeled")
m = pd.read_parquet(INTERIM / "moments.parquet")
cov = json.load(open(EXPORT / "coverage.json"))
cname = t.groupby("country_code").country_name.first().to_dict()
name = meta.topic_name.astype(str)
hidden, wrapped_skip, vis = ex.visibility(t, meta)
tv = t[~t.topic_id.isin(hidden)]
print(f"national rows {len(t):,}; hidden topics {len(hidden):,}", flush=True)

# collection gaps -> months
gap_days = sorted({d.strftime("%Y-%m-%d") for a, b in cov["gaps"] for d in pd.date_range(a, b)})
gap_months = pd.Series(gap_days).str[:7].value_counts().sort_index().to_dict()


def topics_where(rx, types=None, exclude=None):
    s = name.str.lower()
    ok = s.str.contains(rx, regex=True)
    if types is not None:
        ok &= meta["type"].isin(types)
    if exclude:
        ok &= ~s.str.contains(exclude, regex=True)
    return set(meta.index[ok]) - hidden


# ------------------------------------------------------------------ KIND RULES (as in STORY_CANDIDATES.md)
print("kinds ...", flush=True)
best = m.sort_values(["reach", "reach_60"], ascending=False).drop_duplicates("topic_id").set_index("topic_id")
day_cc = t.groupby(["topic_id", "day"]).country_code.nunique()
f = pd.DataFrame({"max_reach": best.reach, "best_min_to_half": best.minutes_to_half})
f["persistence_days"] = (day_cc >= 10).groupby(level=0).sum().reindex(f.index).fillna(0).astype(int)
f["moments_10plus"] = m[m.reach >= 10].groupby("topic_id").size().reindex(f.index).fillna(0).astype(int)
f["type"] = meta["type"].reindex(f.index)
f["category"] = meta["category"].reindex(f.index)
f["is_sport"] = meta.is_sport.reindex(f.index).fillna(False).astype(bool)
nm = name.reindex(f.index).fillna("").str.lower()
RITUAL_RE = (r"lotto|lottery|loter|quina|mega ?sena|lotofacil|powerball|euromillion|xo so|kqxs|prayer|namaz|"
             r"salat|solat|sholat|adhan|horoscope|wordle|connections|strands|crossword|exchange rate|dollar rate|"
             r"gold (price|rate)|fuel price|petrol price|weather|forecast|tide|sunrise|sunset|tv guide")
APPOINT_RE = (r"final|award|awards|oscar|grammy|emmy|golden globe|eurovision|election|elecciones|debate|super bowl|"
              r"launch|release|premiere|estreno|draw|keynote|budget|summit|ceremony|festival|black friday|"
              r"cyber monday|world cup|olympic|marathon|grand prix|coronation|inauguration|met gala|wwdc|"
              r"apple event|state of the union|season \d|episode|trailer|draft|halftime|wrestlemania|"
              r"new year|countdown|eclipse|meteor shower|supermoon")
ritual = (f.category == "weather") | (f.type == "holiday") | nm.str.contains(RITUAL_RE) | \
         ((f.moments_10plus >= 15) & ~f.is_sport & f.type.isin(["other", "product", "company", "unlabeled"]))
appoint = f.is_sport | nm.str.contains(APPOINT_RE) | ((f.type == "person") & (f.moments_10plus >= 10))
shock = (f.best_min_to_half <= 180) & (f.max_reach >= 20) & (f.persistence_days <= 4) & \
        f.type.isin(["event", "person", "company", "product", "place", "other", "unlabeled", "media"])
kind = pd.Series("wave", index=f.index)
kind[shock] = "shock"
kind[appoint] = "appointment"
kind[ritual] = "ritual"
kind[(f.max_reach < 15) & (kind != "ritual")] = "local"
KIND = kind.to_dict()
kind_of = lambda tid: KIND.get(tid, "local")  # noqa: E731
holiday = set(f.index[f.type == "holiday"])

OUT.exists() and shutil.rmtree(OUT)
OUT.mkdir(parents=True)


def top_phrasings(rows, k=8):
    return rows.query_raw.str.lower().value_counts().head(k).index.tolist()


# ------------------------------------------------------------------ 1 opening
print("opening ...", flush=True)
pope = topics_where(r"pope francis|death of pope francis")
lo = pd.Timestamp("2025-04-21 06:00", tz="UTC")
hi = lo + pd.Timedelta(hours=24)
pr = t[t.topic_id.isin(pope) & (t.start_time_utc >= lo) & (t.start_time_utc < hi)]
first = pr.groupby("country_code").start_time_utc.min().sort_values()
t0 = first.iloc[0]
phr = (pr.groupby(["country_code", "query_raw"]).size().reset_index(name="k")
       .sort_values(["country_code", "k"], ascending=[True, False]).drop_duplicates("country_code")
       .set_index("country_code").query_raw)
ctry = [{"country_code": c, "country_name": cname.get(c), "first_trend_utc": iso(ts),
         "minutes_from_first": int(round((ts - t0).total_seconds() / 60)), "top_phrasing": phr.get(c)}
        for c, ts in first.items()]
mins = np.array([c["minutes_from_first"] for c in ctry])
half = int(np.sort(mins)[math.ceil(len(mins) / 2) - 1])
opening = {"event": "Death of Pope Francis (announced 2025-04-21 07:47 UTC)",
           "topics": sorted(pope & set(pr.topic_id)), "window_utc": [iso(lo), iso(hi)],
           "first_trend_utc": iso(t0), "countries": len(ctry), "minutes_to_half": half,
           "within_60_min": int((mins <= 60).sum()), "by_country": ctry,
           "cumulative_by_10_min": [[k, int((mins <= k).sum())] for k in range(0, 24 * 60 + 1, 10)]}
write("opening.json", opening)
num("Opening", "First Pope Francis trend (UTC)", opening["first_trend_utc"], "opening.json", "first_trend_utc")
num("Opening", "Countries in 24 h", len(ctry), "opening.json", "countries")
num("Opening", "Minutes until half of them", half, "opening.json", "minutes_to_half")
num("Opening", "Countries within 60 min", opening["within_60_min"], "opening.json", "within_60_min")
opening_first = int((mins == 0).sum())
num("Opening", "Countries already trending at the first scrape (07:50 UTC; the scraper's 10-min grid makes them a tie)",
    opening_first, "opening.json", "cumulative_by_10_min[0]")

# ------------------------------------------------------------------ 2 local
print("local ...", flush=True)
reach = t.groupby("topic_id").country_code.nunique()
grp = pd.cut(reach, [0, 1, 14, 10_000], labels=["1", "2-14", "15+"])
rows_per = t.groupby("topic_id").size()
canon = pd.read_parquet(WORK / "string_topics.parquet", columns=["topic_id", "canonical_en", "n_rows", "query_norm"])
groups = []
for g in ["1", "2-14", "15+"]:
    ids = grp.index[grp == g]
    ok = [x for x in ids if x not in hidden and meta["type"].get(x) not in ("person", "unlabeled")
          and isinstance(meta.topic_name.get(x), str)]
    ex_ids = rows_per.reindex(ok).sort_values(ascending=False).head(5).index
    exs = []
    for x in ex_ids:
        r = tv[tv.topic_id == x]
        exs.append({"topic_id": x, "english_name": meta.topic_name.get(x), "type": meta["type"].get(x),
                    "countries": sorted(r.country_code.unique().tolist()), "trends": int(len(r)),
                    "top_phrasings": top_phrasings(r, 3)})
    groups.append({"group": g, "topics": int(len(ids)), "topic_share": round(len(ids) / len(reach), 4),
                   "trends": int(rows_per.reindex(ids).sum()), "trend_share": round(rows_per.reindex(ids).sum() / len(t), 4),
                   "examples": exs})
single = set(grp.index[grp == "1"])
pc = t.assign(single=t.topic_id.isin(single)).groupby("country_code").agg(
    trends=("single", "size"), single_trends=("single", "sum"))
pt = t.drop_duplicates(["country_code", "topic_id"]).assign(single=lambda d: d.topic_id.isin(single)) \
    .groupby("country_code").agg(topics=("single", "size"), single_topics=("single", "sum"))
pcs = pc.join(pt)
low = {c for c, v in ex.low_data_countries(t).items() if v < ex.LOW_DATA_MEDIAN}
per_country = [{"country_code": c, "country_name": cname.get(c), "low_data": c in low, "topics": int(r.topics),
                "single_country_topic_share": round(r.single_topics / r.topics, 4),
                "single_country_trend_share": round(r.single_trends / r.trends, 4)}
               for c, r in pcs.sort_values("single_topics", ascending=False).iterrows()]
local = {"note": "Topics by the number of countries whose national feed ever had them trending. Examples are the "
                 "most-trended topics per group, without hidden topics or people; english_name is Claude's English "
                 "name, top_phrasings the searches as typed.",
         "groups": groups, "per_country": sorted(per_country, key=lambda d: -d["single_country_topic_share"])}
write("local.json", local)
for g in groups:
    num("Local", f"Topics reaching {g['group']} countries", g["topics"], "local.json", f"groups[{g['group']}].topics")
    num("Local", f"Share of topics reaching {g['group']} countries", g["topic_share"], "local.json",
        f"groups[{g['group']}].topic_share")
    num("Local", f"Share of trends from topics reaching {g['group']} countries", g["trend_share"], "local.json",
        f"groups[{g['group']}].trend_share")
full = [d for d in local["per_country"] if not d["low_data"]]
hi_c, lo_c = full[0], full[-1]
num("Local", f"Most local country (not low_data): {hi_c['country_name']} (share of its topics found nowhere else)",
    hi_c["single_country_topic_share"], "local.json", "per_country (low_data false), first")
num("Local", f"Least local country (not low_data): {lo_c['country_name']}", lo_c["single_country_topic_share"],
    "local.json", "per_country (low_data false), last")
num("Local", "Median country: share of its topics found nowhere else",
    float(np.median([d["single_country_topic_share"] for d in full])), "local.json", "per_country[].single_country_topic_share")

# ------------------------------------------------------------------ 3 shocks
print("shocks ...", flush=True)
DEATH_RE = (r"\b(death|dies|died|dead|rip|obituary|funeral|muere|muri[oó]|fallece|falleci[oó]|morre|morreu|"
            r"faleceu|d[ée]c[eè]s|est mort|meurt|gestorben|stirbt|tot\b|morto|muore|[oö]ld[uü]|wafat|meninggal|"
            r"qua đời|умер|скончал|توفي|وفاة)")
OUTAGE_RE = r"\b(outage|down|not working|ca[ií]do|caiu|fora do ar|panne|st[oö]rung|error|no funciona)\b"
gm = m[m.is_global & ~m.is_sport.astype(bool) & m.topic_id.map(lambda x: kind_of(x) == "shock")
       & ~m.topic_id.isin(hidden)].sort_values("start_utc")
# leave out unnamed strings ("c": 41 countries on 23 Jun 2025, Claude "unknown"): no story without a topic
_lab = pd.read_parquet(WORK / "string_topics.parquet", columns=["topic_id", "canonical_en", "n_rows"])
_named = _lab[_lab.canonical_en.notna() & (_lab.canonical_en.str.lower() != "unknown")].topic_id.unique()
_unnamed = gm[(gm.topic_name.astype(str).str.len() <= 2) | ~gm.topic_id.isin(set(_named))]
gm = gm.drop(_unnamed.index)
shocks = []
by_topic = t[t.topic_id.isin(set(gm.topic_id))].groupby("topic_id")
# Google's related searches of the topic's strings ("hulk hogan death"): people mostly search just the name
_st = pd.read_parquet(WORK / "string_topics.parquet", columns=["sid", "topic_id"])
_rel = pd.read_parquet(WORK / "strings.parquet", columns=["sid", "related_top"]).merge(_st, on="sid")
_rel = _rel[_rel.topic_id.isin(set(gm.topic_id))]
related_text = _rel.groupby("topic_id").related_top.agg(lambda s: " ".join(" ".join(x) for x in s)).to_dict()
for r in gm.itertuples():
    cs = r.countries
    ph = list(dict.fromkeys(c["phrasing"].lower() for c in cs if c["phrasing"]))[:10]
    # kind from the topic name, the moment's phrasings and every search of the topic in its first 48 h
    g_ = by_topic.get_group(r.topic_id)
    w_ = g_[(g_.start_time_utc >= r.start_utc) & (g_.start_time_utc < r.start_utc + pd.Timedelta(hours=48))]
    text = " ".join([str(r.topic_name)] + ph + w_.query_raw.str.lower().unique().tolist()
                    + [related_text.get(r.topic_id, "")]).lower()
    k = "death" if re.search(DEATH_RE, text) else ("outage" if re.search(OUTAGE_RE, text) else "other")
    mm = np.array([c["min_from_start"] for c in cs])
    shocks.append({"moment_id": int(r.moment_id), "topic_id": r.topic_id, "name": r.topic_name, "kind": k,
                   "date_utc": iso(r.start_utc), "reach": int(r.reach), "reach_60": int(r.reach_60),
                   "minutes_to_half": int(r.minutes_to_half), "phrasings": ph,
                   "curve_first_3h": [[x, int((mm <= x).sum())] for x in range(0, 181, 10)]})
shocks.sort(key=lambda d: -d["reach"])
write("shocks.json", {"note": "Sport-free global moments (>= 15 countries within 60 min of the third country) of "
                               "topics tagged shock. curve_first_3h = [minutes from the moment's first trend, "
                               "countries started]. kind (death / outage / other) is a keyword rule on the topic name, "
                               "phrasings, the topic's searches in its first 48 h and Google's related searches; some "
                               "deaths stay 'other'. Unnamed topics (<= 2 characters or no Claude name) are left out.",
                     "left_out_unnamed": [{"name": r.topic_name, "date_utc": iso(r.start_utc), "reach": int(r.reach)}
                                          for r in _unnamed.itertuples()],
                     "moments": shocks})
kc = pd.Series([s["kind"] for s in shocks]).value_counts().to_dict()
num("Shocks", "Sport-free global shock moments", len(shocks), "shocks.json", "moments")
for k_, v in kc.items():
    num("Shocks", f"... of kind {k_}", v, "shocks.json", "moments[].kind")
for s_ in shocks[:5]:
    num("Shocks", f"{s_['name']} ({s_['date_utc'][:10]}): countries / minutes to half",
        f"{s_['reach']} / {s_['minutes_to_half']}", "shocks.json", f"moments[{s_['name']}]")

# ------------------------------------------------------------------ 4 appointments
print("appointments ...", flush=True)


def appointment(label, tids, lo_, hi_, pick="max"):
    lo_, hi_ = pd.Timestamp(lo_, tz="UTC"), pd.Timestamp(hi_, tz="UTC") + pd.Timedelta(days=1)
    mm = m[m.topic_id.isin(tids) & (m.start_utc >= lo_) & (m.start_utc < hi_)]
    if mm.empty:
        return {"event": label, "found": False}
    pk = mm.sort_values("reach", ascending=False).iloc[0]
    d0 = pk.start_utc.floor("D")
    days = pd.date_range(d0 - pd.Timedelta(days=7), d0 + pd.Timedelta(days=2), freq="D")
    rr = tv[tv.topic_id.isin(tids)]
    per = rr[(rr.start_time_utc >= days[0]) & (rr.start_time_utc < days[-1] + pd.Timedelta(days=1))] \
        .groupby("day").country_code.nunique()
    cs = pk.countries
    return {"event": label, "found": True, "topic_id": pk.topic_id, "name": pk.topic_name, "date_utc": iso(pk.start_utc),
            "reach": int(pk.reach), "minutes_to_half": int(pk.minutes_to_half),
            "countries": [c["country_code"] for c in cs],
            "phrasings": list(dict.fromkeys(c["phrasing"].lower() for c in cs if c["phrasing"]))[:10],
            "build_up": [[d.strftime("%Y-%m-%d"), int(per.get(d.strftime("%Y-%m-%d"), 0)), (d - d0).days] for d in days]}


clasico = topics_where(r"real madrid.*barcelona|barcelona.*real madrid|el cl[aá]sico", exclude=r"women|femen|\bb\b|basket")
cm = m[m.topic_id.isin(clasico) & (m.reach >= 60)].sort_values("reach", ascending=False)
peaks, used = [], []
for r in cm.itertuples():
    if all(abs((r.start_utc - u).total_seconds()) > 3 * 86400 for u in used):
        used.append(r.start_utc)
        peaks.append(r.start_utc)
apps = [appointment(f"El Clásico {p:%Y-%m-%d}", clasico, (p - pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
                    (p + pd.Timedelta(days=1)).strftime("%Y-%m-%d")) for p in sorted(peaks)]
apps += [
    appointment("Winter Olympics 2026", topics_where(r"winter olympic|milano cortina|olimpiadi invernali"), "2026-01-25", "2026-02-25"),
    appointment("Club World Cup 2025 start", topics_where(r"club world cup|mundial de clubes|copa do mundo de clubes"), "2025-06-10", "2025-06-20"),
    appointment("PSG vs Bayern (Club World Cup QF, 4 Jul 2025)", topics_where(r"(paris saint|psg).*bayern|bayern.*(paris saint|psg)"), "2025-07-03", "2025-07-06"),
    appointment("Champions League final 2025 (PSG vs Inter)", topics_where(r"(paris saint|psg).*inter|inter.*(paris saint|psg)|champions league final"), "2025-05-29", "2025-06-02"),
    appointment("Super Bowl LIX (9 Feb 2025)", topics_where(r"super bowl"), "2025-02-05", "2025-02-12"),
    appointment("Super Bowl LX (8 Feb 2026)", topics_where(r"super bowl"), "2026-02-04", "2026-02-11"),
    appointment("World Cup 2026 draw (5 Dec 2025)", topics_where(r"(world cup|mundial|copa do mundo).*(draw|sorteo|sorteio)|(draw|sorteo|sorteio).*(world cup|mundial)"), "2025-12-01", "2025-12-08"),
    appointment("London Marathon 2025", topics_where(r"london.*marathon|marathon.*london"), "2025-04-24", "2025-04-30"),
]
hol = f[f.index.isin(holiday) & ~f.index.isin(hidden)].sort_values("max_reach", ascending=False).head(3)
for tid in hol.index:
    b = best.loc[tid]
    apps.append(appointment(f"Holiday: {name[tid]}", {tid}, (b.start_utc - pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
                            (b.start_utc + pd.Timedelta(days=1)).strftime("%Y-%m-%d")) | {"holiday": True})
write("appointments.json", {"note": "Each event's peak moment (biggest reach in its window). build_up = [UTC day, countries "
                                    "trending the event's topics that day, days from the peak]. Holidays are non-sport "
                                    "appointments for comparison.", "events": apps})
for a in apps:
    if a.get("found"):
        num("Appointments", f"{a['event']}: countries at peak ({a['date_utc'][:10]})", a["reach"], "appointments.json",
            f"events[{a['event']}].reach")

# ------------------------------------------------------------------ 5 waves
print("waves ...", flush=True)
SER = {"ChatGPT": topics_where(r"chatgpt|chat gpt|openai"),
       "Gemini": topics_where(r"google gemini|gemini ai|gemini \d|gemini app|nano banana") | topics_where(r"^gemini$", types=["product", "company"]),
       "Claude": topics_where(r"claude (ai|\d|code|sonnet|opus)|anthropic") | topics_where(r"^claude$", types=["product", "company"]),
       "DeepSeek": topics_where(r"deepseek"), "Grok": topics_where(r"\bgrok\b"),
       "Epstein files": topics_where(r"epstein"), "Bitcoin": topics_where(r"bitcoin|\bbtc\b"),
       "Gold price": topics_where(r"gold (price|rate)|price of gold|gold prices")}
months = sorted(t.month.unique())
monthly = {}
for k, ids in SER.items():
    r = tv[tv.topic_id.isin(ids)]
    cc = r.groupby("month").country_code.nunique()
    ph = r.groupby("month").query_raw.agg(lambda s: s.str.lower().value_counts().head(3).index.tolist())
    monthly[k] = [{"month": mo, "countries": int(cc.get(mo, 0)), "top_phrasings": ph.get(mo, [])} for mo in months]
DAILY = {"Tariffs": topics_where(r"tariff|aranceles|tarifas de trump|zölle|dazi|droits de douane"),
         "S&P 500": topics_where(r"s&p|s and p 500|sp500"), "Dow Jones": topics_where(r"dow jones|\bdow\b"),
         "Nasdaq": topics_where(r"nasdaq")}
ddays = pd.date_range("2025-03-25", "2025-04-20", freq="D").strftime("%Y-%m-%d")
daily = {k: [[d, int(tv[tv.topic_id.isin(ids) & (tv.day == d)].country_code.nunique())] for d in ddays]
         for k, ids in DAILY.items()}
write("waves.json", {"note": "Countries per UTC month whose national feed had the series trending; daily series for "
                             "25 Mar - 20 Apr 2025. gap_months = months with collection-gap days (counts lower there).",
                     "months": months, "gap_months": gap_months, "monthly": monthly, "daily_2025_03_25_to_04_20": daily,
                     "topics_matched": {k: len(v) for k, v in {**SER, **DAILY}.items()}})
for k, rows in monthly.items():
    b = max(rows, key=lambda d: d["countries"])
    num("Waves", f"{k}: peak month and countries", f"{b['month']}: {b['countries']}", "waves.json", f"monthly.{k}")
for k, rows in daily.items():
    b = max(rows, key=lambda d: d[1])
    num("Waves", f"{k}: peak day Mar-Apr 2025 and countries", f"{b[0]}: {b[1]}", "waves.json", f"daily.{k}")

# ------------------------------------------------------------------ 6 rituals
print("rituals ...", flush=True)
cz = json.load(open(INTERIM / "country_timezones.json"))
weather_ids = set(meta.index[meta.category == "weather"]) - hidden
TOMORROW_RE = r"tomorrow|ma[ñn]ana|amanh[ãa]|demain|morgen|domani|yar[ıi]n|besok|завтра|غدا|明天|明日|내일|ngày mai|jutro|zítra|holnap|imorgon|i morgen"
# national rows in one zone per country, except US/CA/RU: regional feeds in each region's own zone (CHECKS C3)
REG = ("US", "CA", "RU")
w_nat = tv[tv.topic_id.isin(weather_ids) & ~tv.country_code.isin(REG)][["country_code", "local_time", "query_raw", "utc19_bump"]]
w_nat = w_nat.assign(lh=w_nat.local_time.dt.hour, wd=w_nat.local_time.dt.dayofweek)
rg = allrows[(allrows.level == "region") & allrows.country_code.isin(REG) & allrows.topic_id.isin(weather_ids)].copy()
zone = pd.Series([REGION_TZ.get(c, {}).get(z, cz[c]) for c, z in zip(rg.country_code, rg.location.str.split("-").str[1])],
                 index=rg.index)
rg["lh"], rg["wd"] = -1, -1
for z, idx in zone.groupby(zone).groups.items():
    lt = rg.loc[idx, "start_time_utc"].dt.tz_convert(z)
    rg.loc[idx, "lh"], rg.loc[idx, "wd"] = lt.dt.hour.values, lt.dt.dayofweek.values
w = pd.concat([w_nat[["country_code", "lh", "wd", "query_raw", "utc19_bump"]],
               rg[["country_code", "lh", "wd", "query_raw", "utc19_bump"]]])
w["weekend"] = w.wd >= 5
w["tomorrow"] = w.query_raw.str.lower().str.contains(TOMORROW_RE, regex=True, na=False)


def hours(d):
    return [int(x) for x in d.lh.value_counts().reindex(range(24), fill_value=0).values]


def split(d):
    return {"weekday": hours(d[~d.weekend]), "weekend": hours(d[d.weekend]), "all": hours(d),
            "all_without_19utc_bump": hours(d[~d.utc19_bump.fillna(False).astype(bool)])}


per_c = {}
for c, d in w.groupby("country_code"):
    h = pd.Series(hours(d))
    per_c[c] = {"country_name": cname.get(c), "trends": int(len(d)), "peak_hour": int(h.idxmax()),
                "top_phrasing": d.query_raw.str.lower().value_counts().index[0],
                "weather": split(d), "weather_tomorrow": split(d[d.tomorrow]),
                "time_zone_source": "regional feeds, own zones" if c in REG else "national feed, one zone"}
wd_cc = tv[tv.topic_id.isin(weather_ids)].groupby("day").country_code.nunique()
WHEN_RE = r"^(when is|when does|cu[aá]ndo es|cu[aá]ndo empieza|quando [eé]|quando come[cç]a|wann ist|wann beginnt|quand est|quand commence|kapan|ne zaman)\b"
FEST = {"Ramadan": r"ramadan|ramad[aã]n|ramazan|puasa", "Eid": r"\beid\b|bayram|lebaran|aid el|a[iï]d al", "Easter": r"easter|pascua|p[aá]scoa|ostern|p[aâ]ques|pasqua"}
DOWN_RE = r"^is \S+( \S+)? down|\bdown right now|not working|\bca[ií]do\b|\bcaiu\b|fora do ar|\bpanne\b|st[oö]rung|downdetector"
ql = tv.query_raw.str.lower()
when = {}
for k, rx in FEST.items():
    r = tv[ql.str.contains(WHEN_RE, regex=True, na=False) & ql.str.contains(rx, regex=True, na=False)]
    g = r.groupby("day").agg(countries=("country_code", "nunique"), trends=("country_code", "size"))
    when[k] = [[d, int(x.countries), int(x.trends)] for d, x in g.iterrows()]
dn = tv[ql.str.contains(DOWN_RE, regex=True, na=False)]
dg = dn.groupby("day").agg(countries=("country_code", "nunique"), trends=("country_code", "size"),
                          top=("query_raw", lambda s: s.str.lower().value_counts().index[0]))
rituals = {"note": "Weather topics (category weather) by local hour, weekday (Mon-Fri) vs weekend (Sat-Sun). US, CA and RU "
                   "use regional feeds in each region's zone; all others one zone per country. 'all_without_19utc_bump' "
                   "leaves out trends starting 19:00-19:59 UTC (CHECKS.md C4). Date series are UTC days: [day, countries, trends].",
           "weather_all_countries": split(w), "weather_tomorrow_all_countries": split(w[w.tomorrow]),
           "per_country": per_c,
           "weather_days_in_10plus_countries": int((wd_cc >= 10).sum()), "weather_days_total": int(len(wd_cc)),
           "when_is": when, "is_x_down": [[d, int(x.countries), int(x.trends), x.top] for d, x in dg.iterrows()]}
write("rituals.json", rituals)
allh = pd.Series(rituals["weather_all_countries"]["all"])
nob = pd.Series(rituals["weather_all_countries"]["all_without_19utc_bump"])
num("Rituals", "Weather: busiest local hour, all countries (with / without 19 UTC bump)", f"{allh.idxmax()} / {nob.idxmax()}",
    "rituals.json", "weather_all_countries")
num("Rituals", "Weather: days trending in 10+ countries", rituals["weather_days_in_10plus_countries"], "rituals.json",
    "weather_days_in_10plus_countries")
for k, s_ in when.items():
    if s_:
        b = max(s_, key=lambda x: x[1])
        num("Rituals", f"'When is {k}': peak day and countries", f"{b[0]}: {b[1]}", "rituals.json", f"when_is.{k}")
if len(dg):
    b = dg.countries.idxmax()
    num("Rituals", "'Is X down': peak day, countries, top search", f"{b}: {dg.countries.max()} ({dg.loc[b, 'top']})",
        "rituals.json", "is_x_down")

# ------------------------------------------------------------------ 7 time machine
print("time machine ...", flush=True)
dur = pd.to_timedelta(tv.duration_minutes.fillna(0).clip(upper=24 * 60), unit="m")
end = tv.end_time_utc.fillna(tv.start_time_utc + dur)
end = end.where(end > tv.start_time_utc, tv.start_time_utc + pd.Timedelta(minutes=1))
h0 = tv.start_time_utc.dt.floor("h").astype("int64") // 3_600_000_000_000
h1 = (end - pd.Timedelta(microseconds=1)).dt.floor("h").astype("int64") // 3_600_000_000_000
n = np.clip(h1 - h0 + 1, 1, 25).values
tid_codes, tid_uni = pd.factorize(tv.topic_id)
cc_codes, cc_uni = pd.factorize(tv.country_code, sort=True)
idx = np.repeat(np.arange(len(tv)), n)
offs = np.arange(len(idx)) - np.repeat(np.cumsum(n) - n, n)
e = pd.DataFrame({"hour": h0.values[idx] + offs, "cc": cc_codes[idx], "tid": tid_codes[idx],
                  "vol": tv.vol.values[idx], "start": tv.start_time_utc.astype("int64").values[idx]})
e = e.sort_values(["hour", "cc", "vol", "start"], ascending=[True, True, False, False]).drop_duplicates(["hour", "cc"])
e["month"] = pd.to_datetime(e.hour * 3_600_000_000_000, utc=True).dt.strftime("%Y-%m")
countries = list(cc_uni)
KINDS = ["shock", "appointment", "wave", "ritual", "local"]
tm_files = []
for month, g in e.groupby("month"):
    start = pd.Timestamp(month + "-01", tz="UTC")
    hrs = pd.date_range(start, start + pd.offsets.MonthBegin(1), freq="h", inclusive="left")
    key = g.set_index(["hour", "cc"]).tid

    def build(hh):
        hi_ = [int(h.value // 3_600_000_000_000) for h in hh]
        sub = key[key.index.get_level_values(0).isin(hi_)]
        tids = list(dict.fromkeys(sub.values))
        pos = {x: i for i, x in enumerate(tids)}
        d = sub.to_dict()
        return {"month": month, "countries": countries, "hours": [h.strftime("%Y-%m-%dT%H") for h in hh],
                "kinds": KINDS,
                "topics": [[tid_uni[x], name.get(tid_uni[x]), KINDS.index(kind_of(tid_uni[x]))] for x in tids],
                "top": [[pos[d[(h, c)]] if (h, c) in d else -1 for c in range(len(countries))] for h in hi_],
                "note": "top[i][j] = index into topics of country j's top active trend in hour i (-1 = none); "
                        "topics = [topic_id, name, kind index into kinds]"}
    for k in range(1, 9):
        parts = [list(p) for p in np.array_split(np.array(hrs, dtype=object), k)]
        objs = [build(p) for p in parts]
        if all(len(dumps(o).encode()) <= MAX_BYTES for o in objs):
            for i, o in enumerate(objs):
                rel = f"timemachine/{month}.json" if k == 1 else f"timemachine/{month}-{i + 1}.json"
                write(rel, o)
                tm_files.append(rel)
            break
    else:
        raise ValueError(f"time machine {month} does not fit")
peaks_ = m[m.is_global & ~m.topic_id.isin(hidden)].sort_values("start_utc")
write("timemachine/peaks.json", {"note": "Global moments for the timeline (>= 15 countries within 60 min of the third). name is null when it equals topic_id; is_sport 0/1; kind = index into kinds.",
                                 "files": tm_files,
                                 "fields": ["date_utc", "topic_id", "name", "reach", "is_sport", "kind"], "kinds": KINDS,
                                 "peaks": [[iso(r.start_utc), r.topic_id, r.topic_name if r.topic_name != r.topic_id else None,
                                            int(r.reach), int(bool(r.is_sport)), KINDS.index(kind_of(r.topic_id))]
                                           for r in peaks_.itertuples()]})
num("Time machine", "Global moments on the timeline", len(peaks_), "timemachine/peaks.json", "peaks")

# ------------------------------------------------------------------ 8 wrapped
print("wrapped ...", flush=True)
tk = t.assign(kind=t.topic_id.map(kind_of))
share = tk.groupby(["country_code", "kind"]).size().unstack(fill_value=0)
share = share.div(share.sum(1), axis=0).reindex(columns=KINDS, fill_value=0)
index = []
for p in sorted((EXPORT / "wrapped").glob("[A-Z][A-Z].json")):
    c5 = json.load(open(p))
    c = c5["country_code"]
    ml = c5["uniquely_local"][0] if c5["uniquely_local"] else None
    card = {"country_code": c, "country_name": c5["country_name"], "low_data": c5["low_data"],
            "median_trends_per_day": c5["median_trends_per_day"],
            "most_local_topic": ml and {"topic_id": ml["topic_id"], "name": ml["name"], "trends": ml["trends"]},
            "biggest_day": {"date": c5["busiest_day"]["date"], "trends": c5["busiest_day"]["trends"],
                            "top_topic": (c5["busiest_day"]["top_topics"] or [{}])[0].get("name")},
            "attention_twin": {"country_code": c5["attention_twin"]["country_code"],
                               "country_name": c5["attention_twin"]["country_name"],
                               "jaccard": c5["attention_twin"]["jaccard"]},
            "weather_hour": c5["weather_hour"], "time_of_day_source": c5["time_of_day_source"],
            "kind_shares": {k: round(float(share.loc[c, k]), 4) if c in share.index else 0.0 for k in KINDS}}
    write(f"wrapped/{c}.json", card)
    index.append({k: card[k] for k in ("country_code", "country_name", "low_data", "weather_hour")} |
                 {"twin": card["attention_twin"]["country_code"], "local_share": card["kind_shares"]["local"]})
write("wrapped/index.json", {"note": "Per-country cards; card choices (most local topic, biggest day) come from step 5 and "
                                     "respect the sensitive-topic decisions. kind_shares = share of the country's trends "
                                     "by topic kind. low_data = median covered day < 5 national trends.", "countries": index})
num("Wrapped", "Countries with a card", len(index), "wrapped/index.json", "countries")
num("Wrapped", "Cards flagged low_data", sum(x["low_data"] for x in index), "wrapped/index.json", "countries[].low_data")
ws = share.mean()
for k in KINDS:
    num("Wrapped", f"Mean share of trends that are {k}", float(ws[k]), "wrapped/<CC>.json", f"kind_shares.{k}")

# ------------------------------------------------------------------ manifest + numbers
(OUT / "manifest.json").write_text(json.dumps({"generated_by": "pipeline/08_story_export.py", "max_bytes": MAX_BYTES,
                                               "files": [{"file": r, "bytes": b} for r, b in WRITTEN],
                                               "visibility": vis, "kind_counts": kind.value_counts().to_dict()}, indent=1))
L = ["# Story numbers", "",
     "_Generated by `pipeline/08_story_export.py` (`make story`). Every number the article quotes, with the file in "
     "`data/export/story/` and the key it comes from. Re-run after any pipeline change; do not edit by hand._", "",
     "Conventions: national feeds; UTC unless a local hour is named; a moment is one topic in one burst of attention "
     "(DECISIONS.md, Step 4); kinds are rule-based (shock, appointment, wave, ritual, local); hidden sensitive topics are "
     f"excluded ({len(hidden):,} topics). Collection-gap months: {', '.join(f'{k} ({v} days)' for k, v in gap_months.items())}.", ""]
for ch in dict.fromkeys(x[0] for x in NUMBERS):
    L += [f"## {ch}", "", "| number | value | file | key |", "|---|---|---|---|"]
    for c_, label, v, fl, key in NUMBERS:
        if c_ == ch:
            L.append(f"| {label.replace('|', '/')} | {fmt(v).replace('|', '/')} | `{fl}` | `{key}` |")
    L.append("")
(DOCS / "STORY_NUMBERS.md").write_text("\n".join(L) + "\n")
big = max(WRITTEN, key=lambda x: x[1])
print(f"{len(WRITTEN)} files, {sum(b for _, b in WRITTEN) / 1e6:.1f} MB; largest {big[0]} {big[1] / 1e6:.2f} MB")
print(f"wrote {DOCS / 'STORY_NUMBERS.md'} ({len(NUMBERS)} numbers)")
