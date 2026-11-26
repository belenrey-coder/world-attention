"""Step 8: data for the article -> data/export/story/ (one JSON per chapter, every file < 1 MB) and
docs/STORY_NUMBERS.md (every number the article quotes, with its source file and key).

Reads only earlier outputs: data/interim/{topics,moments,topic_meta}.parquet, work/string_topics.parquet,
data/export/coverage.json and data/export/wrapped/ (step 5). National feeds unless stated.

Sensitive topics follow step 5 (pipeline/05_export.py `visibility`): hidden topics never appear in lists,
examples or the time machine, and Wrapped keeps step 5's card choices (which also skip accident, crash,
shooting and death events). Example lists for local topics also leave out people, since small local
person-topics can be private individuals.

Two layers (DECISIONS.md, Step 9 rounds 3-4; rules in pipeline/kinds.py):
  - moment kind (shock / appointment / ritual / other) from step 4 (moments.parquet `kind`); every trend row takes
    the kind of the moment it belongs to (work/row_moments.parquet). The timeline, shocks.json, the time machine
    colours and the Wrapped kind shares use these. A topic's kind (topic_meta `kind`) is only a summary (its biggest
    moment's kind), used only in manifest.json counts.
  - topic pattern is_wave (topic_meta `is_wave`: 15+ countries in >= 3 separate months). waves.json lists every wave
    topic's monthly series regardless of moment kinds; the time machine and the timeline flag wave topics.
"Local" is no longer a kind: Wrapped's local_share is the share of trends whose moment reached < 15 countries.
"""
import importlib.util
import json
import warnings
import math
import random
import re
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", message="This pattern is interpreted as a regular expression")
sys.path.insert(0, str(Path(__file__).parent))
from common import DOCS, INTERIM, REGION_TZ, ROOT, WORK, load_json  # noqa: E402

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
# junk topics (step 4 `is_junk`) are left out of every chapter, including the denominators of the Wrapped shares
_junk = set(meta.index[meta.is_junk.astype(bool)])
print(f"junk topics left out: {len(_junk):,} ({int(t.topic_id.isin(_junk).sum()):,} national rows)", flush=True)
t = t[~t.topic_id.isin(_junk)]
m = m[~m.topic_id.isin(_junk)]
# each national row takes the kind of its moment (step 4)
_rm = pd.read_parquet(WORK / "row_moments.parquet")
t = t.merge(_rm, on=["topic_id", "country_code", "start_time_utc"], how="left")
t["kind"] = t.moment_id.map(m.set_index("moment_id").kind).fillna("other")
t["moment_reach"] = t.moment_id.map(m.set_index("moment_id").reach).fillna(1)
WAVE = set(meta.index[meta.is_wave.astype(bool)])
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


# ------------------------------------------------------------------ KIND RULES (pipeline/kinds.py)
print("kinds ...", flush=True)
from kinds import CONSTANT_MIN_MONTHS, LOCAL_MAX_REACH, MOMENT_KINDS, WAVE_MIN_MONTHS, topic_features  # noqa: E402
best = m.sort_values(["reach", "reach_60"], ascending=False).drop_duplicates("topic_id").set_index("topic_id")
f = topic_features(t, m, meta)
kind = meta.kind           # topic SUMMARY kind (its biggest moment's kind); charts use moment / row kinds
holiday = set(f.index[f.type == "holiday"])

OUT.exists() and shutil.rmtree(OUT)
OUT.mkdir(parents=True)


def top_phrasings(rows, k=8):
    return rows.query_raw.str.lower().value_counts().head(k).index.tolist()


# ------------------------------------------------------------------ 1 opening
print("opening ...", flush=True)
# Event reach (Step 9 round 12): once docs/event_groups_review.csv is fully reviewed, the opening counts the Pope's
# event group (main topic + accepted topics) from 2 h before the moment start to 24 h after; before that, the older
# name pattern and fixed window.
import events as EV  # noqa: E402
EVENT_GROUPS = EV.load_groups(DOCS) if EV.reviewed(DOCS) else None
OPENING_TOPIC, OPENING_DAY = "Q450675", "2025-04-21"
_pm = m[(m.topic_id == OPENING_TOPIC) & m.is_global & (m.start_utc.dt.strftime("%Y-%m-%d") == OPENING_DAY)]
if EVENT_GROUPS is not None and len(_pm):
    _pm = _pm.sort_values("reach", ascending=False).iloc[0]
    pope = {OPENING_TOPIC} | EVENT_GROUPS.get(int(_pm.moment_id), set())
    lo, hi = EV.window(_pm.start_utc)
    opening_basis = "event reach: event group from docs/event_groups_review.csv, moment start - 2 h to + 24 h"
else:
    pope = topics_where(r"pope francis|death of pope francis")
    lo = pd.Timestamp("2025-04-21 06:00", tz="UTC")
    hi = lo + pd.Timedelta(hours=24)
    opening_basis = "name pattern 'pope francis' and 21 Apr 06:00 - 22 Apr 06:00 UTC (event groups not reviewed yet)"
pr = t[t.topic_id.isin(pope) & (t.start_time_utc >= lo) & (t.start_time_utc < hi)]
first = pr.groupby("country_code").start_time_utc.min().sort_values()
t0 = _pm.start_utc if EVENT_GROUPS is not None and not isinstance(_pm, pd.DataFrame) else first.iloc[0]
phr = (pr.groupby(["country_code", "query_raw"]).size().reset_index(name="k")
       .sort_values(["country_code", "k"], ascending=[True, False]).drop_duplicates("country_code")
       .set_index("country_code").query_raw)
ctry = [{"country_code": c, "country_name": cname.get(c), "first_trend_utc": iso(ts),
         "minutes_from_first": max(0, int(round((ts - t0).total_seconds() / 60))), "top_phrasing": phr.get(c)}
        for c, ts in first.items()]
mins = np.array([c["minutes_from_first"] for c in ctry])
# "within 60 min" and "minutes to half" count from the third country's first trend (global-moment rule, Step 9
# round 15); minutes_from_first and the cumulative curve stay relative to the first trend
ref3, mins3 = EV.from_third(first)
half = EV.half_minutes(mins3)
opening = {"event": "Death of Pope Francis (announced 2025-04-21 07:47 UTC)", "basis": opening_basis,
           "topics": sorted(pope & set(pr.topic_id)), "window_utc": [iso(lo), iso(hi)],
           "first_trend_utc": iso(t0), "third_country_utc": iso(ref3), "countries": len(ctry),
           "minutes_to_half": half, "within_60_min": int((mins3 <= 60).sum()),
           "timing_basis": "within_60_min and minutes_to_half count from the third country's first trend",
           "by_country": ctry,
           "cumulative_by_10_min": [[k, int((mins <= k).sum())] for k in range(0, 24 * 60 + 1, 10)]}
write("opening.json", opening)
POPE_IDS, POPE_LO, POPE_HI = set(pope), lo, hi        # reused by two_clocks.json
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
LOW_DATA = {c for c, v in ex.low_data_countries(t).items() if v < ex.LOW_DATA_MEDIAN}
per_country = [{"country_code": c, "country_name": cname.get(c), "low_data": c in LOW_DATA, "topics": int(r.topics),
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
# outage needs evidence in the MOMENT's own phrasings or related searches (DECISIONS.md, Step 9 round 5)
OUTAGE_RE = (r"\b(outages?|down|not working|isn'?t working|stopped working|server status|status page|service status|"
             r"down ?detector|error|errors|problems?|issues?|"
             r"ca[ií]d[oa]|se cay[oó]|no funciona|no carga|falla|fallas|problemas?|"
             r"caiu|fora do ar|n[aã]o funciona|inst[aá]vel|"
             r"panne|en panne|ne fonctionne pas|"
             r"st[oö]rung|ausfall|geht nicht|funktioniert nicht|"
             r"non funziona|disservizio|"
             r"kesinti|[cç][oö]kt[uü]|eri[sş]im sorunu|"
             r"gangguan|tidak bisa|error|"
             r"не работает|сбой|упал|"
             r"storing|werkt niet|"
             r"awaria|nie działa)\b|障害|繋がらない|つながらない|ダウン|عطل|توقف|لا يعمل|خلل|故障|宕机|장애|오류")
gm = m[m.kind.eq("shock") & ~m.topic_id.isin(hidden)].sort_values("start_utc")   # moment kind (step 4)
# leave out unnamed strings ("c": 41 countries on 23 Jun 2025, Claude "unknown"): no story without a topic
_lab = pd.read_parquet(WORK / "string_topics.parquet", columns=["topic_id", "canonical_en", "n_rows"])
_named = _lab[_lab.canonical_en.notna() & (_lab.canonical_en.str.lower() != "unknown")].topic_id.unique()
_unnamed = gm[(gm.topic_name.astype(str).str.len() <= 2) | ~gm.topic_id.isin(set(_named))]
gm = gm.drop(_unnamed.index)
DISASTER_RE = (r"earthquake|quake|sismo|terremoto|gempa|tsunami|flood|inondation|wildfire|incendio|incendie|fire\b|"
               r"hurricane|typhoon|cyclone|tornado|storm|eruption|volcan|landslide|explosion|blast|collapse|derail|"
               r"crash|accident|plane|flight \d|shooting|tiroteo|stabbing|attack on|hostage|missing sub|sinking")
POLITICS_RE = (r"election|elecciones|president|presidente|prime minister|minister|government|parliament|congress|"
               r"senate|war\b|guerra|strike on|airstrike|missile|invasion|military|army|ceasefire|coup|protest|"
               r"sanction|tariff|arrest|captured|detenido|resign|impeach|nuclear|attack|bomb|iran|israel|gaza|ukraine|"
               r"russia|venezuela|maduro|trump|putin|khamenei|netanyahu|nato|united nations")
VIRAL_RE = (r"viral|video|meme|trend|kiss|kiss cam|wedding|engaged|pregnan|divorce|concert|tour|scandal|leak|"
            r"interview|award|red carpet|outfit|dating|girlfriend|boyfriend|instagram|tiktok|reality")
LAUNCH_RE = (r"launch|release|released|announce|unveil|new model|update|beta|preorder|pre-order|trailer|"
             r"iphone|pixel|galaxy|playstation|nintendo|switch 2|gpt|gemini|copilot|grok|model|app\b|version")


PERSON_ACCIDENT_RE = r"crash|accident|acidente|accidente|unfall|shooting|shot\b|stabb|attack"
POLITICS_STRONG_RE = (r"pardon|arrest|detenido|preso|election|elecciones|president|presidente|minister|resign|impeach|"
                      r"parliament|senate|congress|sanction|deport|indict|trial|court")
RELIGION_RE = r"\bpope\b|\bpapa\b|conclave|vatican|leo xiv|leone xiv"


def sub_kind(text, typ):
    """Claude type first, then keywords (first match wins)."""
    if re.search(RELIGION_RE, text):
        return "other"
    if typ == "product":
        return "launch"
    if typ == "company":
        return "launch" if re.search(LAUNCH_RE, text) else ("politics or conflict" if re.search(POLITICS_STRONG_RE, text)
                                                            else "other")
    if typ in ("person", "media"):
        if re.search(PERSON_ACCIDENT_RE, text):
            return "disaster or accident"
        if re.search(POLITICS_STRONG_RE, text):
            return "politics or conflict"
        if typ == "media" and re.search(r"trailer|release|premiere|estreno|season \d|teaser|announce", text):
            return "launch"
        return "viral or celebrity"
    if re.search(DISASTER_RE, text):
        return "disaster or accident"
    if re.search(POLITICS_RE, text) or typ == "place":
        return "politics or conflict"
    if re.search(LAUNCH_RE, text):
        return "launch"
    if re.search(VIRAL_RE, text):
        return "viral or celebrity"
    return "other"


shocks = []
by_topic = t[t.topic_id.isin(set(gm.topic_id))].groupby("topic_id")
# Google's related searches of the topic's strings ("hulk hogan death"): people mostly search just the name
_st = pd.read_parquet(WORK / "string_topics.parquet", columns=["sid", "topic_id"])
_rel = pd.read_parquet(WORK / "strings.parquet", columns=["sid", "related_top"]).merge(_st, on="sid")
_rel = _rel[_rel.topic_id.isin(set(gm.topic_id))]
related_text = _rel.groupby("topic_id").related_top.agg(lambda s: " ".join(" ".join(x) for x in s)).to_dict()
# the moment's own searches: national rows of the topic inside the moment (start .. end, at least 1 h), raw
# searches and Google's related searches of those rows (same window as the sport rule and Claude shock-v2)
_mrows = pd.read_parquet(INTERIM / "topics.parquet", columns=["topic_id", "level", "start_time_utc", "query_raw", "related"],
                         filters=[("topic_id", "in", sorted(set(gm.topic_id)))])
_mrows = _mrows[_mrows.level == "country"]
_mby = {k_: g_ for k_, g_ in _mrows.groupby("topic_id")}


# a search about planes, the military or markets is not outage evidence ("jets shot down", "aviao caiu",
# "why is gold down today", "caida criptomonedas", "trump backs down")
OUTAGE_NOT_RE = (r"\b(shot|shoots|shooting|back|backs|backed|step|steps|stepped|stand|stands|calm|slow|count|knock|"
                 r"knocked|let|bring|brought|hands|bear|bears|weigh|weighs) down\b|"
                 r"\b(avi[aã]o|avi[oó]n|plane|planes|jet|jets|aircraft|helic[oó]ptero|helicopter|drone|pilot|flight|"
                 r"f ?16|missile|market|markets|stock|stocks|bolsa|mercado|acciones|a[cç][oõ]es|cripto\w*|crypto|"
                 r"bitcoin|btc|price|prices|precio|pre[cç]o|d[oó]lar|dollar|gold|oro|ouro|oil|dow|jones|nasdaq|s&p)\b")


def outage_evidence(r):
    """First search of the moment that is outage evidence, or None."""
    for x in moment_own_terms(r):
        if re.search(OUTAGE_RE, x, re.I) and not re.search(OUTAGE_NOT_RE, x, re.I):
            return x
    return None


def moment_own_terms(r):
    g_ = _mby.get(r.topic_id)
    ph_ = [c["phrasing"].lower() for c in r.countries if c["phrasing"]]
    if g_ is None:
        return ph_
    hi_ = max(r.end_utc, r.start_utc + pd.Timedelta(hours=1))
    w_ = g_[(g_.start_time_utc >= r.start_utc) & (g_.start_time_utc <= hi_)]
    rel_ = [x.lower() for lst in w_.related for x in (lst if lst is not None else [])]
    return list(dict.fromkeys(ph_ + w_.query_raw.str.lower().tolist() + rel_))


n_outage_word_elsewhere = 0
HAND_SUB_KIND = {"disaster": "disaster or accident", "politics_conflict": "politics or conflict", "launch": "launch",
                 "viral_celebrity": "viral or celebrity", "markets": "markets", "other": "other"}
CHART_N = 60
for r in gm.itertuples():
    cs = r.countries
    ph = list(dict.fromkeys(c["phrasing"].lower() for c in cs if c["phrasing"]))[:10]
    # kind from the topic name, the moment's phrasings and every search of the topic in its first 48 h
    g_ = by_topic.get_group(r.topic_id)
    w_ = g_[(g_.start_time_utc >= r.start_utc) & (g_.start_time_utc < r.start_utc + pd.Timedelta(hours=48))]
    text = " ".join([str(r.topic_name)] + ph + w_.query_raw.str.lower().unique().tolist()
                    + [related_text.get(r.topic_id, "")]).lower()
    ev_out = outage_evidence(r)
    hand_t = getattr(r, "hand_event_type", None)
    if isinstance(hand_t, str):
        # hand label (validation samples / chart verification sheets) decides the split (Step 9 round 10)
        k = hand_t if hand_t in ("death", "outage") else "other"
        sk = HAND_SUB_KIND.get(hand_t, "other") if k == "other" else None
    else:
        if re.search(DEATH_RE, text):
            k = "death"
        elif ev_out:
            k = "outage"
        else:
            k = "other"
            n_outage_word_elsewhere += bool(re.search(OUTAGE_RE, text, re.I))
        sk = sub_kind(text, r.type) if k == "other" else None
    mm = np.array([c["min_from_start"] for c in cs])
    shocks.append({"moment_id": int(r.moment_id), "topic_id": r.topic_id, "name": r.topic_name, "kind": k,
                   "sub_kind": sk, "claude_type": r.type, "outage_evidence": ev_out if k == "outage" else None,
                   "verified": getattr(r, "hand_scheduled", None) == "unscheduled",
                   "kind_source": "hand label" if isinstance(hand_t, str) else "rule",
                   "date_utc": iso(r.start_utc), "reach": int(r.reach), "reach_60": int(r.reach_60),
                   "minutes_to_half": int(r.minutes_to_half), "phrasings": ph,
                   "curve_first_3h": [[x, int((mm <= x).sum())] for x in range(0, 181, 10)]})
shocks.sort(key=lambda d: (-d["reach"], -d["reach_60"]))
chart = shocks[:CHART_N]      # the chart set: the 60 widest shocks (verification sheets, Step 9 round 10)
# readers see EVENT reach for the chart shocks (Step 9 round 12): main topic + accepted topics about the same event.
# Since round 16 the chart's 60 are chosen BY event reach: among the hand-verified shocks in the CHART_POOL_N widest
# by moment reach (ranks 61-100 were checked: only 14 could reach the old 60th, and those were verified and grouped)
CHART_POOL_N = 100
if EVENT_GROUPS is not None:
    pool_ = [x for x in shocks[:CHART_POOL_N] if x["verified"]]
    for x in pool_:
        grp = {x["topic_id"]} | EVENT_GROUPS.get(x["moment_id"], set())
        em = EV.metrics(t, grp, pd.Timestamp(x["date_utc"].replace("Z", ""), tz="UTC"))
        x.update(event_reach=em["event_reach"], event_reach_60=em["event_reach_60"],
                 event_minutes_to_half=em["event_minutes_to_half"],
                 event_topics=sorted(name.get(g, g) for g in grp))
    chart = sorted(pool_, key=lambda d: (-d["event_reach"], -d["event_reach_60"], -d["reach"]))[:CHART_N]
chart_by_event = sorted(chart, key=lambda d: (-d.get("event_reach", d["reach"]), -d.get("event_reach_60", d["reach_60"])))
_est = load_json(WORK / "shock_estimate.json") if (WORK / "shock_estimate.json").exists() else None
# "Is it down": outage-driven searches (moved here from Rituals in Step 9 round 33)
DOWN_RE = r"^is \S+( \S+)? down|\bdown right now|not working|\bca[ií]do\b|\bcaiu\b|fora do ar|\bpanne\b|st[oö]rung|downdetector"
from kinds import OUTAGE_TOPIC_EXCLUDE_RE, OUTAGE_TOPIC_RE  # noqa: E402
_down_ids = topics_where(OUTAGE_TOPIC_RE, exclude=OUTAGE_TOPIC_EXCLUDE_RE)     # same rule as kinds.outage_topics
_dr = tv[tv.topic_id.isin(_down_ids)]
_dstrict = tv[tv.query_raw.str.lower().str.contains(DOWN_RE, regex=True, na=False)]
_out = [x for x in shocks if x["kind"] == "outage"]
_ow = [(pd.Timestamp(x["date_utc"].replace("Z", ""), tz="UTC"), x) for x in _out]
_in = np.zeros(len(_dr), bool)
_st = _dr.start_time_utc.astype("int64").to_numpy() // 10**9
for s0, _ in _ow:
    lo_, hi_ = int(s0.timestamp()) - 2 * 3600, int(s0.timestamp()) + 24 * 3600
    _in |= (_st >= lo_) & (_st < hi_)
_dday = _dr.groupby("day").agg(countries=("country_code", "nunique"), trends=("country_code", "size"))
_sday = _dstrict.groupby("day").agg(countries=("country_code", "nunique"), trends=("country_code", "size"),
                                    top=("query_raw", lambda s: s.str.lower().value_counts().index[0]))
_top10 = []
for d_, x_ in _dday.sort_values(["countries", "trends"], ascending=False).head(10).iterrows():
    dd = pd.Timestamp(d_, tz="UTC")
    match = [x["name"] for s0, x in _ow if s0 - pd.Timedelta(hours=2) < dd + pd.Timedelta(days=1)
             and s0 + pd.Timedelta(hours=24) > dd]
    _top10.append({"day": d_, "countries": int(x_.countries), "trends": int(x_.trends),
                   "outage_shocks": sorted(set(match))})
is_it_down = {"note": "Outage-named topics (Claude name with outage / down / not working; power cuts and blackouts left "
                      "out). Moved from Rituals: its peaks are outages. by_day = [UTC day, countries, trends]; "
                      "strict_by_day = searches phrased 'is ... down' / 'not working' / 'caído' ..., with the top phrasing.",
              "topics": len(_down_ids), "trends": int(len(_dr)), "countries": int(_dr.country_code.nunique()),
              "outage_shocks": len(_out), "trends_inside_outage_shocks": int(_in.sum()),
              "share_inside_outage_shocks": round(float(_in.mean()), 4) if len(_dr) else None,
              "window": "from 2 h before to 24 h after each outage shock's start (kind outage)",
              "top10_days": _top10,
              "by_day": [[d, int(x.countries), int(x.trends)] for d, x in _dday.iterrows()],
              "strict_by_day": [[d, int(x.countries), int(x.trends), x.top] for d, x in _sday.iterrows()]}
num("Shocks", f"'Is it down' ({len(_down_ids)} topics): trends inside outage shocks (share)",
    f"{is_it_down['trends_inside_outage_shocks']:,} of {is_it_down['trends']:,} ({is_it_down['share_inside_outage_shocks']:.0%})",
    "shocks.json", "is_it_down")
num("Shocks", "'Is it down': widest day (countries) / top 10 days with a matching outage shock",
    f"{_top10[0]['day']} ({_top10[0]['countries']}) / {sum(1 for x in _top10 if x['outage_shocks'])} of 10",
    "shocks.json", "is_it_down.top10_days")
write("shocks.json", {"is_it_down": is_it_down,"note": "Sport-free global moments (>= 15 countries within 60 min of the third country) that "
                               "Claude (shock-v2, the moment's own searches) calls unscheduled with confidence >= 0.5 "
                               "(DECISIONS.md, Step 9). curve_first_3h = [minutes from the moment's first trend, "
                               "countries started]. kind (death / outage / other) is a keyword rule: death on the topic name, "
                               "phrasings, the topic's searches in its first 48 h and Google's related searches; outage "
                               "only on the moment's own phrasings and related searches (status / down words in several "
                               "languages); some deaths stay 'other'. Unnamed topics (<= 2 characters or no Claude name) are left out.",
                     "left_out_unnamed": [{"name": r.topic_name, "date_utc": iso(r.start_utc), "reach": int(r.reach)}
                                          for r in _unnamed.itertuples()],
                     "sub_kind_rule": "for kind 'other' only. Papal topics -> other. Products -> launch; companies -> "
                                      "launch with launch words, politics with political words, else other. People and "
                                      "media -> disaster or accident with crash/accident/shooting words, politics with "
                                      "strong political words (arrest, pardon, election, ...), media with trailer/release "
                                      "words -> launch, else viral or celebrity. "
                                      "Other types: disaster, politics (or a place topic), launch, viral words, else other.",
                     "other_top40": [{k_: s_[k_] for k_ in ("name", "date_utc", "reach", "minutes_to_half", "claude_type",
                                                           "sub_kind", "phrasings")} | {"phrasings": s_["phrasings"][:5]}
                                     for s_ in [x for x in shocks if x["kind"] == "other"][:40]],
                     "chart_top60": {"note": (f"The {CHART_N} hand-verified shocks with the largest event reach, chosen "
                                              f"among the {CHART_POOL_N} widest by moment reach" if EVENT_GROUPS is not None
                                              else f"The {CHART_N} widest shocks (countries, then countries within 60 min)")
                                             + ". verified = hand-labelled unscheduled; hand-labelled scheduled moments "
                                               "are not shocks.",
                                     "moment_ids": [x["moment_id"] for x in chart],
                                     "verified": sum(x["verified"] for x in chart),
                                     "reach_basis": "event reach (main topic + accepted topics about the same event, "
                                                    "moment start - 2 h to + 24 h; within 60 min and minutes to half from the third "
                                                    "country's first trend)" if EVENT_GROUPS is not None
                                                    else "moment reach (event groups not reviewed yet)",
                                     "by_event_reach": [{"moment_id": x["moment_id"], "name": x["name"],
                                                         "date_utc": x["date_utc"],
                                                         "event_reach": x.get("event_reach"),
                                                         "event_reach_60": x.get("event_reach_60"),
                                                         "event_minutes_to_half": x.get("event_minutes_to_half"),
                                                         "moment_reach": x["reach"]} for x in chart_by_event]},
                     "estimate_true_shocks": _est,
                     "moments": shocks})
kc = pd.Series([s["kind"] for s in shocks]).value_counts().to_dict()
num("Shocks", f"Chart set: {CHART_N} shocks (by event reach once event groups are reviewed), of which hand-verified", f"{sum(x['verified'] for x in chart)} of {len(chart)}",
    "shocks.json", "chart_top60")
num("Shocks", "Shocks verified by hand label (all)", sum(x["verified"] for x in shocks), "shocks.json", "moments[].verified")
if _est:
    num("Shocks", "Estimated true number of shocks (flagged x precision / recall, 95% bootstrap interval)",
        f"{_est['estimate']:,.0f} [{_est['ci95'][0]:,.0f}, {_est['ci95'][1]:,.0f}]", "shocks.json", "estimate_true_shocks")
num("Shocks", "Sport-free global shock moments", len(shocks), "shocks.json", "moments")
for k_, v in kc.items():
    num("Shocks", f"... of kind {k_}", v, "shocks.json", "moments[].kind")
oth = [x for x in shocks if x["kind"] == "other"]
for k_, v in pd.Series([x["sub_kind"] for x in oth]).value_counts().items():
    num("Shocks", f"... 'other' shocks of sub-kind {k_} (all / in the top 40)",
        f"{v} / {sum(1 for x in oth[:40] if x['sub_kind'] == k_)}", "shocks.json", "moments[].sub_kind, other_top40")
if EVENT_GROUPS is not None:
    for s_ in chart_by_event[:5]:
        num("Shocks", f"{s_['name']} ({s_['date_utc'][:10]}): event reach / within 60 min / minutes to half",
            f"{s_['event_reach']} / {s_['event_reach_60']} / {s_['event_minutes_to_half']}", "shocks.json",
            "chart_top60.by_event_reach")
else:
    for s_ in shocks[:5]:
        num("Shocks", f"{s_['name']} ({s_['date_utc'][:10]}): countries / minutes to half",
            f"{s_['reach']} / {s_['minutes_to_half']}", "shocks.json", f"moments[{s_['name']}]")

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
# Selection rule for the chapter's series (DECISIONS.md, Step 9 round 5): every wave topic gets a theme (keyword
# groups first, then its Claude type); in each theme, the WAVE_SERIES_PER_THEME NON-constant wave topics with the most
# months in 15+ countries (ties: more countries overall) are the chapter's series. Constant wave topics (12+ months)
# are listed apart per theme (always there rather than rising and falling).
WAVE_SERIES_PER_THEME = 5
THEMES = [("AI tools", r"chatgpt|openai|gemini|claude|grok|deepseek|sora|copilot|perplexity|\bai\b|llm|midjourney"),
          ("markets and crypto", r"price|s&p|dow jones|nasdaq|stock|bitcoin|crypto|binance|ethereum|gold|oil|dollar|"
                                 r"tariff|inflation"),
          ("Epstein", r"epstein|maxwell|giuffre")]
TYPE_THEME = {"person": "people", "media": "media and entertainment", "product": "tech and brands",
              "company": "tech and brands", "event": "events", "place": "places and politics", "other": "other"}


def theme_of(tid):
    n_ = str(name.get(tid, tid)).lower()
    for th, rx in THEMES:
        if re.search(rx, n_):
            return th
    return TYPE_THEME.get(meta["type"].get(tid), "other")


_reach_all = tv.groupby("topic_id").country_code.nunique()
_wt = pd.DataFrame({"months": meta.wave_months.reindex(list(WAVE - hidden))})
_wt["countries"] = _reach_all.reindex(_wt.index).fillna(0).astype(int)
_wt["theme"] = [theme_of(x) for x in _wt.index]
_wt["constant"] = meta.is_constant.reindex(_wt.index).fillna(False).astype(bool)
_wt = _wt.sort_values(["months", "countries"], ascending=False)
_sel = _wt[~_wt.constant].groupby("theme", sort=False).head(WAVE_SERIES_PER_THEME)
_const = _wt[_wt.constant]


def _items(g):
    return [{"topic_id": tid, "name": name.get(tid), "months_15plus": int(r.months), "countries": int(r.countries)}
            for tid, r in g.iterrows()]


wave_series = {th: {"series": _items(g), "constant": _items(_const[_const.theme == th])}
               for th, g in _sel.groupby("theme", sort=False)}
picked = {k: sorted(ids & set(_sel.index)) for k, ids in {**SER, **DAILY}.items()}
hand_vs_rule = {k: {"selected_by_rule": bool(v), "via": [name.get(x) for x in v],
                    "constant_wave_topics": [name.get(x) for x in sorted(({**SER, **DAILY}[k]) & set(_const.index))],
                    "wave_topics_matched": [name.get(x) for x in sorted(({**SER, **DAILY}[k]) & WAVE)]}
                for k, v in picked.items()}

# every wave topic (topic pattern, independent of moment kinds): countries per month
wv = tv[tv.topic_id.isin(WAVE)]
wcc = wv.groupby(["topic_id", "month"]).country_code.nunique().unstack(fill_value=0).reindex(columns=months, fill_value=0)
wcc = wcc.loc[meta.wave_months.reindex(wcc.index).sort_values(ascending=False).index]
wave_topics = [[tid, name.get(tid), int(meta.wave_months.get(tid, 0)), meta["type"].get(tid), int(bool(meta.is_sport.get(tid))),
                [int(x) for x in row]] for tid, row in zip(wcc.index, wcc.values)]
write("waves.json", {"note": "Countries per UTC month whose national feed had the series trending; daily series for "
                             "25 Mar - 20 Apr 2025. gap_months = months with collection-gap days (counts lower there). "
                             f"wave_topics = every topic in 15+ countries in >= {WAVE_MIN_MONTHS} separate months "
                             "(is_wave, regardless of moment kinds), most months first.",
                     "months": months, "gap_months": gap_months, "monthly": monthly, "daily_2025_03_25_to_04_20": daily,
                     "wave_topic_fields": ["topic_id", "name", "months_15plus", "claude_type", "is_sport_topic",
                                           "countries_per_month"],
                     "wave_topics": wave_topics,
                     "wave_series_rule": f"Each wave topic gets a theme: keyword groups first ({', '.join(t_ for t_, _ in THEMES)}), "
                                         "otherwise its Claude type. In each theme, the "
                                         f"{WAVE_SERIES_PER_THEME} non-constant wave topics with the most months in 15+ "
                                         "countries (ties: more countries overall) are the chapter's series; constant "
                                         "wave topics (12+ months) are listed apart per theme.",
                     "wave_series": wave_series,
                     "hand_picked_vs_rule": hand_vs_rule,
                     "topics_matched": {k: len(v) for k, v in {**SER, **DAILY}.items()}})
num("Waves", f"Wave topics (15+ countries in >= {WAVE_MIN_MONTHS} months; not hidden)", len(wave_topics), "waves.json",
    "wave_topics")

# waves validation round (Step 9 round 27): one row per wave topic for review; category = one-line Claude
# classification (09_validate_shocks.py waves-label, cache/claude/waves/labels.jsonl)
WAVE_CATS = ["AI/tech", "politics/conflict", "finance/markets", "entertainment/culture", "people/celebrity",
             "science/health", "generic/always-on query", "other"]
_wl = {}
_wlp = ROOT / "cache" / "claude" / "waves" / "labels.jsonl"
if _wlp.exists():
    for line in _wlp.read_text().splitlines():
        x_ = json.loads(line)
        if x_.get("prompt_version") == "wave-v1":
            _wl[x_["key"]] = x_
_cov_days = t.groupby("month").day.nunique()           # days with any national row = days collected
_mcov = {mo: {"days_collected": int(_cov_days.get(mo, 0)), "days": int(pd.Period(mo).days_in_month),
              "coverage_share": round(int(_cov_days.get(mo, 0)) / pd.Period(mo).days_in_month, 3),
              "gap": mo in gap_months} for mo in months}
_ph = wv.assign(qn=wv.query_raw.astype(str).str.strip().str.lower()).groupby(["topic_id", "qn"]).agg(
    n=("country_code", "nunique"), rows=("query_raw", "size"),
    raw=("query_raw", lambda s: s.astype(str).str.strip().value_counts().index[0])).reset_index() \
    .sort_values(["topic_id", "n", "rows"], ascending=[True, False, False])
_ph = _ph.groupby("topic_id").raw.apply(lambda s: s.head(5).tolist()).to_dict()
_shk = m[m.kind.eq("shock") & m.topic_id.isin(WAVE)].sort_values("start_utc")
_shk = _shk.groupby("topic_id").start_utc.apply(lambda s: [f"{pd.Timestamp(x):%Y-%m-%d}" for x in s]).to_dict()
wr = []
for tid, row in zip(wcc.index, wcc.values):
    if tid in hidden:
        continue
    cpm = [int(x) for x in row]
    on = [mo for mo, c in zip(months, cpm) if c >= 15]
    pk = int(np.argmax(cpm))
    wr.append({"topic_id": tid, "name": name.get(tid), "category": _wl.get(tid, {}).get("category"),
               "category_why": _wl.get(tid, {}).get("why"), "phrasings": _ph.get(tid, []),
               "months_15plus": len(on), "months_15plus_list": on, "peak_month": months[pk], "peak_countries": cpm[pk],
               "distinct_countries": int(_reach_all.get(tid, 0)),
               "is_constant": bool(meta.is_constant.get(tid, False)),
               "shock_moments": len(_shk.get(tid, [])), "shock_dates": _shk.get(tid, []), "countries_per_month": cpm})
_wr = pd.DataFrame(wr)
_wr["country_months"] = _wr.countries_per_month.map(sum)
_wr["generic"] = _wr.category.eq("generic/always-on query")
write("waves_review.json", {
    "note": "One row per wave topic (15+ countries in 3+ separate UTC months; not hidden, not junk). category = "
            "one-line Claude classification (claude-haiku-5-5, prompt wave-v1, from the topic's name, type, searches, "
            "related searches and Wikidata description). months_15plus counts calendar months with 15+ countries "
            "(the wave rule; a month with collection gaps can fall below 15 from missing days). is_constant = 15+ "
            "countries in 12+ months. shock_moments = moments of the topic whose kind is shock. countries_per_month "
            "follows `months`; month_coverage gives days collected / days per month (gap months flagged).",
    "months": months, "gap_months": list(gap_months), "month_coverage": _mcov, "categories": WAVE_CATS,
    "labelled": int(_wr.category.notna().sum()), "topics": wr})


def _wtab(d, k=30):
    return {"by_months_15plus": [{"name": r.name, "category": r.category, "months_15plus": int(r.months_15plus),
                                  "distinct_countries": int(r.distinct_countries)}
                                 for r in d.sort_values(["months_15plus", "distinct_countries"], ascending=False)
                                 .head(k).itertuples()],
            "by_distinct_countries": [{"name": r.name, "category": r.category,
                                       "distinct_countries": int(r.distinct_countries),
                                       "months_15plus": int(r.months_15plus)}
                                      for r in d.sort_values(["distinct_countries", "months_15plus"], ascending=False)
                                      .head(k).itertuples()]}


def _wcat(d):
    return {"topics": d.category.value_counts().reindex(WAVE_CATS, fill_value=0).astype(int).to_dict(),
            "country_months": d.groupby("category").country_months.sum().reindex(WAVE_CATS, fill_value=0)
            .astype(int).to_dict()}


_wf = _wr[~_wr.is_constant & ~_wr.generic]
WAVE_BY_CATEGORY = {"all": {**_wcat(_wr), **_wtab(_wr)},
                    "without_constant_and_generic": {**_wcat(_wf), **_wtab(_wf)},
                    "without_constant": _wcat(_wr[~_wr.is_constant])}
_wj = json.load(open(OUT / "waves.json"))
_wj["by_category_note"] = ("Wave topics by one-line Claude category (waves_review.json). country_months = sum over the "
                           "months of countries trending the topic. without_constant_and_generic drops is_constant "
                           "topics (12+ months) and generic/always-on queries.")
_wj["by_category"] = WAVE_BY_CATEGORY
write("waves.json", _wj)
# checks: (a) largest category; (b) Tariffs / S&P 500 / Nasdaq / Dow Jones against the wave rule; (c) shock overlap
for k_, d_ in (("all wave topics", _wr), ("without constants", _wr[~_wr.is_constant]),
               ("without constants and generic", _wf)):
    c_ = _wcat(d_)
    tp = max(c_["topics"], key=c_["topics"].get)
    cm = max(c_["country_months"], key=c_["country_months"].get)
    print(f"  waves check (a) {k_}: largest by topics {tp} ({c_['topics'][tp]}; AI/tech {c_['topics']['AI/tech']}); "
          f"by country-months {cm} ({c_['country_months'][cm]:,}; AI/tech {c_['country_months']['AI/tech']:,})",
          flush=True)
    num("Waves", f"Largest category, {k_}: by topics / by country-months",
        f"{tp} ({c_['topics'][tp]}) / {cm} ({c_['country_months'][cm]:,})", "waves.json", "by_category")
    num("Waves", f"AI/tech, {k_}: topics / country-months",
        f"{c_['topics']['AI/tech']} / {c_['country_months']['AI/tech']:,}", "waves.json", "by_category")
WAVE_RULE_CHECK = {}
for k_ in ("Tariffs", "S&P 500", "Nasdaq", "Dow Jones"):
    ids_ = DAILY[k_]
    r_ = tv[tv.topic_id.isin(ids_)]
    mo15 = int((r_.groupby("month").country_code.nunique() >= 15).sum())
    per = meta.wave_months.reindex(list(ids_)).fillna(0)
    best = per.idxmax() if len(per) else None
    WAVE_RULE_CHECK[k_] = {"topics_matched": len(ids_), "wave_topics": int(len(ids_ & WAVE)),
                           "best_topic": name.get(best) if best else None,
                           "best_topic_months_15plus": int(per.max()) if len(per) else 0,
                           "series_months_15plus": mo15, "series_meets_rule": mo15 >= WAVE_MIN_MONTHS}
    print(f"  waves check (b) {k_}: {WAVE_RULE_CHECK[k_]}", flush=True)
    num("Waves", f"{k_}: wave topics among matched / best topic months at 15+ / all matched topics together, months at 15+",
        f"{WAVE_RULE_CHECK[k_]['wave_topics']} of {len(ids_)} / {WAVE_RULE_CHECK[k_]['best_topic_months_15plus']} / {mo15}",
        "waves_review.json", "topics")
_wsh = int((_wr.shock_moments > 0).sum())
print(f"  waves check (c): {_wsh} of {len(_wr)} wave topics have a shock moment "
      f"({int(_wr.shock_moments.sum())} shock moments)", flush=True)
num("Waves", "Wave topics with at least one shock moment (shock moments in them)",
    f"{_wsh} of {len(_wr)} ({int(_wr.shock_moments.sum())})", "waves_review.json", "topics[].shock_moments")
num("Waves", "Wave topics labelled by Claude (category)", f"{int(_wr.category.notna().sum())} of {len(_wr)}",
    "waves_review.json", "topics[].category")
num("Waves", "Constant wave topics (15+ countries in 12+ months)", int(_wr.is_constant.sum()), "waves_review.json",
    "topics[].is_constant")
for c_, v_ in _wcat(_wr)["topics"].items():
    num("Waves", f"... category {c_}: topics / country-months", f"{v_} / {_wcat(_wr)['country_months'][c_]:,}",
        "waves.json", "by_category.all")

# clean wave set (Step 9 round 28): the wave topics without constants (12+ months), without topics hand-labelled
# always-on / misgrouped / sport-or-ritual (docs/waves_review.csv, local; athletes and sport are already out of
# is_wave), and with obvious duplicates of one story merged (WAVE_MERGES, reviewed by hand from the clean topics that
# share a name word: same entity or same launch, most 15+ months shared; e.g. "Rockstar Games GTA 6" + "Rockstar
# Games"). Different people (Brigitte / Emmanuel Macron), different products of one maker (Sora / OpenAI), different
# phones (iPhone 16 / 17 / 18) and annual rituals of a service (Spotify Wrapped / Spotify) stay apart. Countries per
# month of a merged story = distinct countries over all its topics.
WAVE_DROP_LABELS = {"always-on query", "misgrouped topic", "should be sport or ritual"}
WAVE_MERGES_BY_NAME = {   # story name: its topics (the first is the story's main topic)
    "iPhone 17": ["iPhone 17", "iPhone 17 Pro", "iPhone 17 Pro Max"],
    "iPhone 18": ["iPhone 18", "iPhone 18 Pro", "iPhone 18 Pro Max"],
    "PlayStation 5": ["PlayStation 5", "PlayStation"],
    "YouTube": ["YouTube", "YouTube outage"],
    "Bitcoin price": ["Bitcoin price (BTC/USD)", "Bitcoin price USD"],
    "Jeffrey Epstein": ["Jeffrey Epstein", "Epstein files"],
    "Claude": ["Claude", "Claude AI"],
    "Pope Francis": ["Pope Francis", "Pope Francis Vatican"],
    "Rockstar Games GTA 6": ["Rockstar Games GTA 6", "Rockstar Games"],
    "Squid Game": ["Squid Game", "Squid Game season 3"],
    "Samsung": ["Samsung", "Samsung Galaxy S26 Ultra"],
    "Iran": ["Iran", "Iran–Israel war"],
    "Meta": ["Meta Platforms", "Meta stock"]}
_whl = {}
_wcsv = DOCS / "waves_review.csv"
if _wcsv.exists():
    _wh = pd.read_csv(_wcsv, dtype=str, keep_default_na=False)
    _whl = {a: b.strip() for a, b in zip(_wh.topic_id, _wh.label) if b.strip()}
_wr["hand_label"] = _wr.topic_id.map(_whl)
_cl = _wr[~_wr.is_constant & ~_wr.hand_label.isin(WAVE_DROP_LABELS)].copy()
_nm = dict(zip(_cl.topic_id, _cl["name"].astype(str)))
_by_name = {v: k for k, v in _nm.items()}
WAVE_MERGES, _story_name = {}, {}
for sname, tops in WAVE_MERGES_BY_NAME.items():
    have = [_by_name[x] for x in tops if x in _by_name]
    missing = [x for x in tops if x not in _by_name]
    if missing:
        print(f"  clean waves: merge '{sname}' topics not in the clean set: {missing}", flush=True)
    if len(have) >= 2:
        for x in have[1:]:
            WAVE_MERGES[x] = have[0]
        _story_name[have[0]] = sname
print("  clean waves, merges: " + "; ".join(f"{_nm[a_]} -> {_nm[b_]}" for a_, b_ in WAVE_MERGES.items()), flush=True)
_cl["story"] = _cl.topic_id.map(lambda x: WAVE_MERGES.get(x, x))
_wv_cl = wv[wv.topic_id.isin(set(_cl.topic_id))].assign(story=lambda d: d.topic_id.map(lambda x: WAVE_MERGES.get(x, x)))
_scpm = _wv_cl.groupby(["story", "month"]).country_code.nunique().unstack(fill_value=0).reindex(columns=months,
                                                                                                 fill_value=0)
_sdist = _wv_cl.groupby("story").country_code.nunique()
clean = []
for sid, g in _cl.groupby("story", sort=False):
    cpm = [int(x) for x in _scpm.loc[sid]]
    on = [mo for mo, c in zip(months, cpm) if c >= 15]
    pk = int(np.argmax(cpm))
    main = g[g.topic_id == sid].iloc[0] if (g.topic_id == sid).any() else g.iloc[0]
    clean.append({"story_id": sid, "name": _story_name.get(sid, main["name"]), "category": main.category, "topics": g["name"].tolist(),
                  "topic_ids": g.topic_id.tolist(),
                  "hand_label": main.hand_label if isinstance(main.hand_label, str) else None,
                  "months_15plus": len(on), "months_15plus_list": on, "peak_month": months[pk],
                  "peak_countries": cpm[pk], "distinct_countries": int(_sdist.get(sid, 0)),
                  "country_months": int(sum(cpm)), "shock_moments": int(g.shock_moments.sum()),
                  "countries_per_month": cpm})
_cs = pd.DataFrame(clean)
# after merging (Step 9 round 29): drop stories Claude calls generic/always-on (2 of 2 hand always-on in the sample)
# and merged stories at 12+ months at 15+ (the constant rule applied to the story, e.g. iPhone 17, PlayStation 5)
_cs["_generic"] = _cs.category.eq("generic/always-on query")
_cs["_constant"] = _cs.months_15plus >= CONSTANT_MIN_MONTHS
WAVE_STORIES_REMOVED = [{"name": r["name"], "category": r["category"], "topics": r["topics"],
                         "months_15plus": int(r["months_15plus"]), "distinct_countries": int(r["distinct_countries"]),
                         "removed_by": [x for x, f in (("generic/always-on category", r["_generic"]),
                                                       ("constant after merge (12+ months)", r["_constant"])) if f]}
                        for _, r in _cs[_cs._generic | _cs._constant].sort_values(
                            ["months_15plus", "distinct_countries"], ascending=False).iterrows()]
for x in WAVE_STORIES_REMOVED:
    print(f"  clean waves, removed: {x['name']} ({x['category']}; {x['months_15plus']} months; "
          f"{' + '.join(x['topics'])}): {', '.join(x['removed_by'])}", flush=True)
_cs = _cs[~_cs._generic & ~_cs._constant].drop(columns=["_generic", "_constant"]).reset_index(drop=True)


def _ctab(d, k=30):
    def it(r):
        return {"story_id": r["story_id"], "name": r["name"], "category": r["category"], "topics": r["topics"],
                "topic_ids": r["topic_ids"],
                "months_15plus": int(r["months_15plus"]), "distinct_countries": int(r["distinct_countries"]),
                "peak_month": r["peak_month"], "countries_per_month": r["countries_per_month"]}
    return {"by_months_15plus": [it(r) for _, r in d.sort_values(["months_15plus", "distinct_countries"],
                                                                   ascending=False).head(k).iterrows()],
            "by_distinct_countries": [it(r) for _, r in d.sort_values(["distinct_countries", "months_15plus"],
                                                                        ascending=False).head(k).iterrows()]}


_ccat = {"topics": _cs.category.value_counts().reindex(WAVE_CATS, fill_value=0).astype(int).to_dict(),
         "country_months": _cs.groupby("category").country_months.sum().reindex(WAVE_CATS, fill_value=0)
         .astype(int).to_dict()}
_wj["clean"] = {
    "note": "Clean wave set: wave topics without constants (15+ countries in 12+ months), without topics "
            "hand-labelled always-on query / misgrouped topic / should be sport or ritual (40-topic sample; the "
            "other topics are unlabelled and kept), athletes and sport already out of the wave rule, and duplicate "
            "topics of one story merged (merges). A merged story's countries per month = distinct countries over "
            "its topics. After merging, stories in Claude's generic/always-on category and stories at 12+ months "
            "at 15+ (the constant rule on the merged story) are dropped (removed_stories). countries_per_month "
            "follows months; gap_months have collection gaps (counts lower).",
    "months": months, "gap_months": list(gap_months),
    "dropped": {"constant": int(_wr.is_constant.sum()),
                "hand_label": int((~_wr.is_constant & _wr.hand_label.isin(WAVE_DROP_LABELS)).sum()),
                "generic_stories": sum("generic/always-on category" in x["removed_by"] for x in WAVE_STORIES_REMOVED),
                "constant_after_merge": sum("constant after merge (12+ months)" in x["removed_by"]
                                            for x in WAVE_STORIES_REMOVED),
                "stories_removed": len(WAVE_STORIES_REMOVED)},
    "removed_stories": WAVE_STORIES_REMOVED,
    "merges": [{"topic": _nm[a_], "into": _nm[b_]} for a_, b_ in WAVE_MERGES.items()],
    "stories": int(len(_cs)), "by_category": _ccat, **_ctab(_cs)}
write("waves.json", _wj)
_ct = max(_ccat["topics"], key=_ccat["topics"].get)
_cc = max(_ccat["country_months"], key=_ccat["country_months"].get)
print(f"  clean waves: {len(_cs)} stories from {len(_wr)} wave topics; largest by topics {_ct} "
      f"({_ccat['topics'][_ct]}), by country-months {_cc} ({_ccat['country_months'][_cc]:,})", flush=True)
_wval = load_json(WORK / "waves_validation.json", None) if (WORK / "waves_validation.json").exists() else None
if _wval:                                   # 09_validate_shocks.py waves-score (hand labels vs Claude categories)
    num("Waves", "Waves sample (hand labels): real recurring story / always-on / misgrouped / sport or ritual",
        " / ".join(str(_wval["labels"].get(k, 0)) for k in ("real recurring story", "always-on query",
                                                             "misgrouped topic", "should be sport or ritual"))
        + f" of {_wval['labelled']}", "waves_review.json", "hand labels (local)")
    num("Waves", "Waves sample: share of real recurring stories, weighted by category (95% CI)",
        f"{_wval['real_story_share_weighted']:.0%} ({_wval['real_story_share_ci95'][0]:.0%}-"
        f"{_wval['real_story_share_ci95'][1]:.0%})", "waves_review.json", "hand labels (local)")
    num("Waves", "Waves sample: Claude 'generic' that are hand always-on / hand always-on caught by 'generic'",
        f"{_wval['generic_category_precision_for_always_on'][0]} of {_wval['generic_category_precision_for_always_on'][1]}"
        f" / {_wval['always_on_labels_caught_by_generic'][0]} of {_wval['always_on_labels_caught_by_generic'][1]}",
        "waves_review.json", "hand labels (local)")
num("Waves", "Athletes and other sport topics kept out of the wave rule (3+ months at 15+, step-4 sporty check)",
    int((meta.is_athlete.astype(bool) & (meta.wave_months >= WAVE_MIN_MONTHS) & ~meta.is_junk.astype(bool)).sum()),
    "topic_meta", "is_athlete")
_dr = _wj["clean"]["dropped"]
num("Waves", "Clean wave set: stories (constants, hand-dropped topics, generic and merged-constant stories out; "
    "duplicates merged)", f"{len(_cs)} (from {len(_wr)} topics: {_dr['constant']} constant, {_dr['hand_label']} "
    f"hand-dropped, {len(WAVE_MERGES)} merged; then {_dr['stories_removed']} stories removed)", "waves.json", "clean")
num("Waves", "Clean waves: stories removed as generic/always-on / as constant after merge (12+ months)",
    f"{_dr['generic_stories']} / {_dr['constant_after_merge']}", "waves.json", "clean.removed_stories")
for x in WAVE_STORIES_REMOVED:
    num("Waves", f"Removed story: {x['name']} ({x['months_15plus']} months)", "; ".join(x["removed_by"]),
        "waves.json", "clean.removed_stories")
num("Waves", "Clean waves: largest category by stories / by country-months",
    f"{_ct} ({_ccat['topics'][_ct]}) / {_cc} ({_ccat['country_months'][_cc]:,})", "waves.json", "clean.by_category")
for c_ in WAVE_CATS:
    num("Waves", f"Clean waves, category {c_}: stories / country-months",
        f"{_ccat['topics'][c_]} / {_ccat['country_months'][c_]:,}", "waves.json", "clean.by_category")
for i_, x in enumerate(_wj["clean"]["by_months_15plus"][:10], 1):
    num("Waves", f"Clean waves top 10 by months at 15+: {i_}. {x['name']} ({x['category']}): months / countries",
        f"{x['months_15plus']} / {x['distinct_countries']}", "waves.json", "clean.by_months_15plus")
for i_, x in enumerate(_wj["clean"]["by_distinct_countries"][:5], 1):
    num("Waves", f"Clean waves top 5 by distinct countries: {i_}. {x['name']}: countries / months",
        f"{x['distinct_countries']} / {x['months_15plus']}", "waves.json", "clean.by_distinct_countries")
for k, rows in monthly.items():
    b = max(rows, key=lambda d: d["countries"])
    num("Waves", f"{k}: peak month and countries", f"{b['month']}: {b['countries']}", "waves.json", f"monthly.{k}")
for k, rows in daily.items():
    b = max(rows, key=lambda d: d[1])
    num("Waves", f"{k}: peak day Mar-Apr 2025 and countries", f"{b[0]}: {b[1]}", "waves.json", f"daily.{k}")

# ------------------------------------------------------------------ 5b appointments (event-based; the only writer of appointments.json)
print("appointments ...", flush=True)
# every global moment of kind appointment (Step 9 round 17; pipeline/appointments.py): category, event reach
# (main topic + accepted topics about the same event once docs/event_groups_review_appointments.csv is reviewed),
# within 60 min and minutes to half from the third country, and a 10-minute curve over 6 h
import appointments as AP  # noqa: E402
APPT_GROUPS = EV.load_groups(DOCS, EV.APPOINTMENT_REVIEW_FILES) if EV.reviewed(DOCS, EV.APPOINTMENT_REVIEW_FILES[:1]) else None
_ns_t = set(m[m.is_global & m.kind.eq("appointment") & ~m.is_sport.astype(bool)].topic_id)
_tr = pd.read_parquet(INTERIM / "topics.parquet", columns=["topic_id", "level", "start_time_utc", "query_raw", "related"],
                      filters=[("topic_id", "in", sorted(_ns_t))])
_tr = _tr[_tr.level == "country"]
_app_t = set(m[m.is_global & m.kind.eq("appointment")].topic_id) | {x for v in (APPT_GROUPS or {}).values() for x in v}
appt = AP.build(m, meta, t[t.topic_id.isin(_app_t)][["topic_id", "country_code", "start_time_utc"]], _tr,
                ROOT / "cache" / "claude" / "shocks" / "labels.jsonl")
appt = appt[~appt.topic_id.isin(hidden) & appt.topic_id.isin(set(_named)) & (appt.name.astype(str).str.len() > 2)].copy()
# the unit is the scheduled EVENT (Step 9 round 18): catalogue events group the moments of one ceremony, election,
# final or draw; other moments are their own unit; holidays (in Rituals) and unclear non-sport moments are left out
_hs = m[m.hand_scheduled.eq("scheduled")]
appt["event_id"] = AP.assign_events(appt, dict(zip(_hs.moment_id, _hs.hand_event_type))).values
_hand_sched = m.set_index("moment_id").hand_scheduled
# catalogue events also take non-global moments of their topics inside the window (Step 9 round 22)
_extra = AP.extra_members(m, meta, appt.moment_id, hidden)
appt = pd.concat([appt, _extra], ignore_index=True)
appt["is_sport"] = appt.is_sport.astype(bool)
_rbt = {k_: g_ for k_, g_ in t[t.topic_id.isin(set(appt.topic_id) | {x for v in (APPT_GROUPS or {}).values() for x in v})]
        [["topic_id", "country_code", "start_time_utc"]].groupby("topic_id")}
units = AP.event_units(appt, _rbt, APPT_GROUPS)
units["verified"] = [any(_hand_sched.get(x) == "scheduled" for x in mem) for mem in units.members]
APPT_REJECTED = AP.rejected_events(DOCS)      # events hand-labelled unscheduled on the verification sheet
units = units[(units.category != "holiday") & ~units.event_id.isin(APPT_REJECTED)].sort_values(
    ["event_reach", "rank_reach_60"], ascending=False)       # tie-break: third-country count (timing-independent)
APPT_CHART = pd.concat([units[units.category == "football"].head(10)] +
                       [units[units.category == c].head(5) for c in AP.CATEGORIES if c not in ("football", "holiday")])


def _int_or_none(x):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else int(x)


def _str_or_none(x):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else str(x)


def _fmt(x):
    return "—" if _int_or_none(x) is None else f"{int(x)}"


def _unit_item(r, curve=True):
    d = {"event_id": r.event_id, "event": r.event, "category": r.category, "is_sport": bool(r.is_sport),
         "first_utc": r.first_utc, "window_utc": r.window_utc, "event_reach": int(r.event_reach),
         "event_reach_60": _int_or_none(r.event_reach_60), "event_minutes_to_half": _int_or_none(r.event_minutes_to_half),
         "timing_basis": r.timing_basis, "start_utc": _str_or_none(getattr(r, "start_utc", None)),
         "start_note": _str_or_none(getattr(r, "start_note", None)),
         "start_source": _str_or_none(getattr(r, "start_source", None)),
         "anticipation": _int_or_none(getattr(r, "anticipation", None)),
         "new_in_first_hour": _int_or_none(getattr(r, "new_in_first_hour", None)),
         "verified": bool(r.verified), "multi_day": bool(r.multi_day),
         "event_reach_total": int(r.event_reach_total) if r.multi_day else None,
         "best_day": r.best_day if r.multi_day else None,
         "moments": [name.get(x, x) for x in r.member_names],
         "topics": [name.get(x, x) for x in r.topics]}
    if curve:
        d["curve"] = r.curve
    return d


appt_files = []
for mo, g in units.assign(month=units.first_utc.str[:7]).groupby("month"):
    rel = f"appointments/{mo}.json"
    write(rel, {"month": mo, "fields": ["event_id", "event", "first_utc", "is_sport", "category", "event_reach",
                                        "event_reach_60", "event_minutes_to_half", "moments", "verified", "multi_day",
                                        "event_reach_total", "curve"],
                "rows": [[r.event_id, r.event, r.first_utc, int(r.is_sport), r.category, int(r.event_reach),
                          _int_or_none(r.event_reach_60), _int_or_none(r.event_minutes_to_half), len(r.members), int(r.verified),
                          int(r.multi_day), int(r.event_reach_total) if r.multi_day else None,
                          [c for _, c in r.curve]] for r in g.itertuples()]})
    appt_files.append(rel)
# Appointments calendar day rule: each event counts once, on the UTC day of its cited scheduled start (start_utc),
# else of its first moment; the multi-day Winter Olympics counts on its opening-ceremony day.
_u = units.copy()
_u["day"] = [(st if isinstance(st, str) and st else fu)[:10] for st, fu in
             zip(_u.get("start_utc", pd.Series([None] * len(_u), index=_u.index)), _u.first_utc)]
_u = _u.sort_values(["event_reach", "rank_reach_60"], ascending=False)
NON_SPORT_CATS = [c for c in AP.CATEGORIES if c not in ("football", "other sport", "holiday")]
# league matches (reach comparison): football singles whose text (name + Claude's summary + phrasings) names a
# domestic league and no cup, European, international, friendly or final/knockout round; catalogue events (finals,
# draws) are never league matches
LEAGUE_RE = re.compile(r"\b(la ?liga|liga ea|premier league|serie a|bundesliga|ligue 1|eredivisie|primeira liga|"
                       r"liga espa[nñ]ola|liga santander|liga portugal|s[uü]per lig|saudi pro league|roshn|mls|major league soccer|liga mx|"
                       r"brasileir[aã]o|liga profesional|championship|league one|league two|"
                       r"scottish premiership|j1? league|k league|matchweek|jornada|giornata|spieltag)\b", re.I)
NOT_LEAGUE_RE = re.compile(r"champions league|\bucl\b|europa league|conference league|libertadores|sudamericana|"
                           r"concacaf|\bafc\b|copa del rey|\bcopa\b|\bcup\b|pokal|coppa|coupe|supercopa|super ?cup|"
                           r"supercoppa|club world cup|mundial de clubes|friendly|amistoso|pre-?season|\btour\b|"
                           r"trophy|troph[eé]e|semi-?final|quarter-?final|\bfinale?\b|play-?offs?|"
                           r"knockout|round of 16|last 16|octavos|nations league|world cup|qualif", re.I)
_ev_text = appt.assign(text=appt["text"].fillna("").astype(str) if "text" in appt else "") \
    .groupby("event_id").text.apply(" | ".join).to_dict()
# Claude's summaries cover few football moments, so the text also takes the searches and Google's related queries of
# the fixture's topics inside its window (they name "la liga", "copa del rey", "champions league" ...)
_fx = _u[(_u.category == "football") & ~_u.is_catalogue.astype(bool) & _u.event.astype(str).str.contains(r"\bvs\b")]
_fx_t = sorted({x for v in _fx.topics for x in v})
_fr = pd.read_parquet(INTERIM / "topics.parquet", columns=["topic_id", "level", "start_time_utc", "query_raw", "related"],
                      filters=[("topic_id", "in", _fx_t)]) if _fx_t else pd.DataFrame(
    columns=["topic_id", "level", "start_time_utc", "query_raw", "related"])
_fr = {k_: g_ for k_, g_ in _fr[_fr.level == "country"].groupby("topic_id")}
for r in _fx.itertuples():
    lo, hi = (pd.Timestamp(x.replace("Z", ""), tz="UTC") for x in r.window_utc)
    parts = []
    for x in r.topics:
        g_ = _fr.get(x)
        if g_ is None:
            continue
        g_ = g_[(g_.start_time_utc >= lo) & (g_.start_time_utc < hi)]
        parts += g_.query_raw.astype(str).tolist()
        parts += [str(q) for v in g_.related.dropna() for q in (v if not isinstance(v, str) else [v])]
    _ev_text[r.event_id] = _ev_text.get(r.event_id, "") + " | " + " | ".join(parts)
_u["league"] = [e in set(_fx.event_id) and bool(LEAGUE_RE.search(_ev_text.get(e, ""))) and
                not NOT_LEAGUE_RE.search(_ev_text.get(e, "")) and not NOT_LEAGUE_RE.search(str(n))
                for e, n in zip(_u.event_id, _u.event)]


def _cmp_item(r):
    return {"event_id": r.event_id, "event": r.event, "date": r.day, "category": r.category,
            "event_reach": int(r.event_reach)}


_fb = _u[_u.category == "football"]
REACH_COMPARISON = {
    "note": "Event reach of football matches vs other appointments (same events and day rule as appointments_daily."
            "json). League matches = football events outside the catalogue whose text (name, Claude's one-line "
            "summary, searches) names a domestic league and no cup, European, international, friendly, final or "
            "knockout round.",
    "football": {"events": int(len(_fb)), "median_event_reach": float(_fb.event_reach.median()),
                 "reached_50_plus": int((_fb.event_reach >= 50).sum()),
                 "reached_100_plus": int((_fb.event_reach >= 100).sum()),
                 "reached_120_plus": int((_fb.event_reach >= 120).sum()),
                 "league_matches": int(_u.league.sum()),
                 "widest_league_matches": [_cmp_item(r) for r in _u[_u.league].head(5).itertuples()]},
    "non_sport_40_plus": [_cmp_item(r) for r in _u[_u.category.isin(NON_SPORT_CATS) & (_u.event_reach >= 40)]
                          .sort_values(["event_reach", "day"], ascending=[False, True]).itertuples()],
    "other_sport_widest": [_cmp_item(r) for r in _u[_u.category == "other sport"].head(5).itertuples()]}
_g_all = int((m.is_global & ~m.topic_id.isin(hidden)).sum())
_in_all = appt[appt.event_id.notna()]
_in = _in_all[_in_all.moment_id.isin(set(m[m.is_global].moment_id))]     # global moments only, for the share
write("appointments.json", {
    "note": "Appointments counted by scheduled event: a catalogue event (a ceremony, election, final or draw) groups "
            "its moments; every other appointment moment (a match, a trailer) is its own unit. Holidays are in "
            "Rituals; unclear non-sport moments are left out. Event reach = countries where any topic of the event "
            "trended in its window (the catalogue window, or 2 h before to 24 h after a single moment); within 60 "
            "min, minutes to half and the curve count from the event's cited scheduled start for catalogue events "
            "(start_utc, start_source; anticipation = countries already trending before it; curve = [minutes after "
            "the start, countries] every 10 min for 6 h), are not given for football matches outside the catalogue "
            "(no kickoff times), and count from the third country's first trend for other single-moment units "
            "(timing_basis). Catalogue events take every trend of their topics inside the window, "
            "not only global moments. multi_day events (Winter Olympics 2026) are ranked by their best UTC day "
            "(event_reach, best_day), with event_reach_total over the whole window as a second number. verified = a "
            "member moment is hand-labelled scheduled.",
    "reach_basis": "event reach with reviewed event groups" if APPT_GROUPS is not None
                   else "event reach, event members only (event groups not reviewed yet)",
    "categories": [c for c in AP.CATEGORIES if c != "holiday"],
    "category_rule": AP.__doc__.split("Category rule, first match wins:")[1].strip(),
    "catalogue": [{"event_id": e[0], "event": e[1], "category": e[2],
                   "window_utc": [f"{e[3][0]:%Y-%m-%dT%H:%MZ}", f"{e[3][1]:%Y-%m-%dT%H:%MZ}"], "pattern": e[4]}
                  for e in AP.CATALOGUE],
    "counts": {"appointment_moments": len(_in), "global_moments": _g_all,
               "share_of_global": round(len(_in) / _g_all, 4), "sport_moments": int(_in.is_sport.sum()),
               "non_sport_moments": int((~_in.is_sport).sum()),
               "non_global_members_of_catalogue_events": int(len(_in_all) - len(_in)), "events": len(units),
               "catalogue_events": int(units.is_catalogue.sum()),
               "events_by_category": units.category.value_counts().reindex(
                   [c for c in AP.CATEGORIES if c != "holiday"], fill_value=0).to_dict(),
               "left_out": {"holiday": int((appt.category == "holiday").sum()),
                            "unclear_non_sport": int((appt.event_id.isna() & (appt.category != "holiday")).sum())}},
    "chart": {"rule": "top 10 football events + top 5 events of each other category, by event reach",
              "verified": int(APPT_CHART.verified.sum()), "events": [_unit_item(r) for r in APPT_CHART.itertuples()]},
    "top20_by_event_reach": [_unit_item(r, curve=False) for r in units.head(20).itertuples()],
    "catalogue_events": [_unit_item(r, curve=False) for r in units[units.is_catalogue.astype(bool)].itertuples()],
    "reach_comparison": REACH_COMPARISON,
    "files": appt_files})
# Appointments calendar: one row per archive day (day rule above)
_by_day = {d: g for d, g in _u.groupby("day")}
_days = pd.date_range(t.day.min(), t.day.max(), freq="D").strftime("%Y-%m-%d")
_gap = set(gap_days)
_cats = [c for c in AP.CATEGORIES if c != "holiday"]


def _searches(r, k=3):
    """Up to k real searches of the event, in their original language: the phrasings trended in the most countries
    in the event's window, over its topics (hidden sensitive topics excluded)."""
    lo, hi = (pd.Timestamp(x.replace("Z", ""), tz="UTC") for x in r.window_utc)
    w = tv[tv.topic_id.isin(set(r.topics) - hidden) & (tv.start_time_utc >= lo) & (tv.start_time_utc < hi)]
    if w.empty:
        return []
    q = w.assign(qn=w.query_raw.astype(str).str.strip().str.lower()).groupby("qn").agg(
        n=("country_code", "nunique"), raw=("query_raw", lambda s: s.astype(str).str.strip().value_counts().index[0]))
    return q.sort_values(["n", "raw"], ascending=[False, True]).raw.head(k).tolist()


def _widest(g):
    return None if g is None or g.empty else {"event": g.iloc[0].event, "category": g.iloc[0].category,
                                              "event_reach": int(g.iloc[0].event_reach)}


cal = []
for d in _days:
    g = _by_day.get(d)
    w = g.iloc[0] if g is not None else None
    nf = g[g.category != "football"] if g is not None else None
    cal.append([d, 0 if g is None else int(len(g)), None if w is None else w.event, None if w is None else w.category,
                None if w is None else int(w.event_reach), int(d in _gap),
                {c: (0 if g is None else int((g.category == c).sum())) for c in _cats},
                _widest(nf), [] if w is None else _searches(w)])
_fields = ["date", "events", "widest_event", "widest_category", "widest_event_reach", "gap", "events_by_category",
           "widest_non_football", "widest_searches"]
write("appointments_daily.json", {
    "note": "One row per day of the archive (UTC). events = appointment events that day (the event-based units of "
            "appointments.json; each event counts once, on the UTC day of its cited scheduled start, else of its first "
            "moment; the multi-day Winter Olympics on its opening-ceremony day). widest = the event with the largest "
            "event reach that day. events_by_category = the day's events per category. widest_non_football = the "
            "widest event that is not football (null if none). widest_searches = up to 3 real searches of the widest "
            "event in their original language (the phrasings trended in the most countries in the event's window; "
            "hidden sensitive topics excluded). gap = 1 if the day has a collection gap (counts are lower there).",
    "fields": _fields, "categories": _cats, "days": cal})
_cal = pd.DataFrame(cal, columns=_fields)
_full = _cal[_cal.gap == 0]
num("Appointments", "Calendar: archive days / days with at least one appointment event",
    f"{len(_cal)} / {int((_cal.events > 0).sum())}", "appointments_daily.json", "days")
num("Appointments", "Calendar: median appointment events per day (full-coverage days)", float(_full.events.median()),
    "appointments_daily.json", "days[].events")
_bd = _cal.sort_values("events", ascending=False).iloc[0]
num("Appointments", "Calendar: busiest day (most appointment events)", f"{_bd.date}: {int(_bd.events)}",
    "appointments_daily.json", "days")
# without football: full-coverage days that still have a 15+ country appointment event, and events per day
_nf_reach = _full.widest_non_football.map(lambda x: x["event_reach"] if x else 0)
_nf_events = _full.events - _full.events_by_category.map(lambda x: x["football"])
_share15 = float((_nf_reach >= 15).mean())
print(f"  check, full-coverage days: {_share15:.1%} still have an appointment event in 15+ countries without football;"
      f" median events per day without football {float(_nf_events.median()):g} (with football "
      f"{float(_full.events.median()):g})", flush=True)
num("Appointments", "Calendar: full-coverage days with a non-football appointment event in 15+ countries",
    f"{int((_nf_reach >= 15).sum())} of {len(_full)} ({_share15:.1%})", "appointments_daily.json",
    "days[].widest_non_football")
num("Appointments", "Calendar: median appointment events per day without football (full-coverage days)",
    float(_nf_events.median()), "appointments_daily.json", "days[].events_by_category")
_rc = REACH_COMPARISON["football"]
num("Appointments", "Reach comparison: football events / median event reach",
    f"{_rc['events']:,} / {_rc['median_event_reach']:g}", "appointments.json", "reach_comparison.football")
num("Appointments", "Reach comparison: football events reaching 50+ / 100+ / 120+ countries",
    f"{_rc['reached_50_plus']:,} / {_rc['reached_100_plus']:,} / {_rc['reached_120_plus']:,}", "appointments.json",
    "reach_comparison.football")
num("Appointments", "Reach comparison: league matches (domestic league named, no cup/European/friendly/final)",
    f"{_rc['league_matches']:,}", "appointments.json", "reach_comparison.football.league_matches")
for x in _rc["widest_league_matches"]:
    num("Appointments", f"Widest league match: {x['event']} ({x['date']}), event reach", x["event_reach"],
        "appointments.json", "reach_comparison.football.widest_league_matches")
num("Appointments", "Reach comparison: non-sport events with event reach 40+",
    len(REACH_COMPARISON["non_sport_40_plus"]), "appointments.json", "reach_comparison.non_sport_40_plus")
for x in REACH_COMPARISON["non_sport_40_plus"]:
    num("Appointments", f"Non-sport 40+: {x['event']} ({x['date']}, {x['category']}), event reach", x["event_reach"],
        "appointments.json", "reach_comparison.non_sport_40_plus")
for x in REACH_COMPARISON["other_sport_widest"]:
    num("Appointments", f"Widest other sport: {x['event']} ({x['date']}), event reach", x["event_reach"],
        "appointments.json", "reach_comparison.other_sport_widest")
for r in _u[(_u.category == "football") & ~_u.is_catalogue.astype(bool)].head(25).itertuples():   # league check
    print(f"  football {r.event_reach:>3} {r.day} league={int(r.league)} {r.event}", flush=True)
num("Appointments", "Global appointment moments in events (share of all global moments)",
    f"{len(_in):,} ({len(_in) / _g_all:.1%})", "appointments.json", "counts")
num("Appointments", "... sport / non-sport moments", f"{int(_in.is_sport.sum()):,} / {int((~_in.is_sport).sum()):,}",
    "appointments.json", "counts")
num("Appointments", "Scheduled events (catalogue events / single-moment units)",
    f"{len(units):,} ({int(units.is_catalogue.sum())} / {int((~units.is_catalogue).sum()):,})", "appointments.json", "counts")
for c_, v_ in units.category.value_counts().reindex([c for c in AP.CATEGORIES if c != "holiday"], fill_value=0).items():
    num("Appointments", f"... events in category {c_}", int(v_), "appointments.json", "counts.events_by_category")
for r in units.head(5).itertuples():
    num("Appointments", f"{r.event} ({r.first_utc[:10]}): event reach / by 60 min after start / minutes to half",
        f"{r.event_reach} / {_fmt(r.event_reach_60)} / {_fmt(r.event_minutes_to_half)}", "appointments.json",
        "top20_by_event_reach")
for r in APPT_CHART[APPT_CHART.timing_basis.eq("scheduled start")].itertuples():
    num("Appointments", f"{r.event}: anticipation / by 60 min after the start ({r.start_utc} UTC) / minutes to half "
        f"/ event reach", f"{_fmt(r.anticipation)} / {_fmt(r.event_reach_60)} / {_fmt(r.event_minutes_to_half)} / "
        f"{r.event_reach}", "appointments.json", "chart.events[]")
for r in units[units.multi_day.astype(bool)].itertuples():
    num("Appointments", f"{r.event}: best day ({r.best_day}) / total over the window",
        f"{r.event_reach} / {r.event_reach_total}", "appointments.json", "chart.events[].event_reach, event_reach_total")
for c_ in [c for c in AP.CATEGORIES if c not in ("football", "holiday", "other")]:
    for r in APPT_CHART[APPT_CHART.category == c_].head(5).itertuples():
        num("Appointments", f"Top 5 {c_}: {r.event} ({r.first_utc[:10]}), event reach", int(r.event_reach),
            "appointments.json", "chart.events")
num("Appointments", "Chart set (stratified by event), of which hand-verified",
    f"{int(APPT_CHART.verified.sum())} of {len(APPT_CHART)}", "appointments.json", "chart")

# ------------------------------------------------------------------ 5c wave chart (Step 9 round 30)
# the stories hand-labelled "real recurring story" on docs/wave_chart_verification.csv (local), Venezuela and Nicolás
# Maduro merged into one story. For each month at 15+: the story's biggest moment that month (most countries; any
# moment of its topics starting in the month) and whether it is a shock (shocks.json), an appointment (a member of an
# appointment event in appointments.json) or neither.
print("wave chart ...", flush=True)
WAVE_CHART_MERGES = {"Venezuela (Nicolás Maduro)": ["Q717", "Q58132"]}     # story ids on the verification sheet
WAVE_CHART_GROUPS = {   # story name -> group (reported by group)
    "pop stars": ["Dua Lipa", "Shakira", "Justin Bieber", "Sabrina Carpenter", "Ariana Grande", "BTS", "Demi Moore"],
    "crises/politics": ["Iran", "Venezuela (Nicolás Maduro)", "Jeffrey Epstein", "Emmanuel Macron", "Syria"],
    "tech/companies": ["Samsung", "Meta", "Nintendo Switch 2", "Grok", "OpenAI", "Nvidia stock"]}
_group_of = {s_: g_ for g_, v_ in WAVE_CHART_GROUPS.items() for s_ in v_}
_wvs = DOCS / "wave_chart_verification.csv"
WAVE_CHART = []
if _wvs.exists():
    _vs = pd.read_csv(_wvs, dtype=str, keep_default_na=False)
    _vs = _vs[_vs.label.str.strip().eq("real recurring story")]
    _cs_by = _cs.set_index("story_id")
    _shock_ids = {x["moment_id"] for x in shocks}
    _appt_ids = {int(x) for mem in units.members for x in mem}
    _merged_into = {sid: nm_ for nm_, ids_ in WAVE_CHART_MERGES.items() for sid in ids_}
    _stories = {}
    for r in _vs.itertuples():
        key = _merged_into.get(r.story_id, r.story)
        st_ = _stories.setdefault(key, {"name": key, "story_ids": [], "topic_ids": [], "topics": [], "notes": []})
        st_["story_ids"].append(r.story_id)
        if r.story_id in _cs_by.index:
            st_["topic_ids"] += list(_cs_by.loc[r.story_id, "topic_ids"])
            st_["topics"] += list(_cs_by.loc[r.story_id, "topics"])
        else:
            print(f"  wave chart: story {r.story_id} ({r.story}) is not in the clean set", flush=True)
        if r.notes.strip():
            st_["notes"].append(r.notes.strip())
    _mm = m[m.topic_id.isin({x for s_ in _stories.values() for x in s_["topic_ids"]})].copy()
    _mm["month"] = _mm.start_utc.dt.strftime("%Y-%m")
    for s_ in _stories.values():
        rows_ = wv[wv.topic_id.isin(s_["topic_ids"])]
        cpm = rows_.groupby("month").country_code.nunique().reindex(months, fill_value=0).astype(int).tolist()
        pk = int(np.argmax(cpm))
        mo_ = _mm[_mm.topic_id.isin(s_["topic_ids"])]
        returns = []
        for mo, c in zip(months, cpm):
            if c < 15:
                continue
            g_ = mo_[mo_.month == mo].sort_values(["reach", "reach_60"], ascending=False)
            if g_.empty:
                returns.append({"month": mo, "countries": c, "biggest_moment": None})
                continue
            b_ = g_.iloc[0]

            def _k(mid):
                return "shock" if int(mid) in _shock_ids else ("appointment" if int(mid) in _appt_ids else "neither")
            kinds_in = {_k(x) for x in g_.moment_id}
            returns.append({"month": mo, "countries": c, "gap": mo in gap_months,
                            "biggest_moment": {"date_utc": f"{b_.start_utc:%Y-%m-%d}", "topic": name.get(b_.topic_id),
                                               "moment_id": int(b_.moment_id),
                                               "start_utc": f"{b_.start_utc:%Y-%m-%dT%H:%MZ}",
                                               "countries": int(b_.reach), "countries_within_60_min": int(b_.reach_60),
                                               "is_global": bool(b_.is_global), "kind": _k(b_.moment_id)},
                            "month_has_shock": "shock" in kinds_in, "month_has_appointment": "appointment" in kinds_in})
        WAVE_CHART.append({"story": s_["name"], "group": _group_of.get(s_["name"]), "topics": s_["topics"],
                           "topic_ids": s_["topic_ids"],
                           "months_15plus": len(returns), "distinct_countries": int(rows_.country_code.nunique()),
                           "peak_month": months[pk], "peak_countries": cpm[pk], "countries_per_month": cpm,
                           "notes": " | ".join(s_["notes"]), "returns": returns})
    WAVE_CHART.sort(key=lambda d: (-d["months_15plus"], -d["distinct_countries"]))
    _ungrouped = [d["story"] for d in WAVE_CHART if d["group"] is None]
    if _ungrouped:
        print(f"  wave chart: stories without a group: {_ungrouped}", flush=True)
    _ret = pd.DataFrame([{"story": d["story"], "group": d["group"],
                          "kind": (x["biggest_moment"] or {}).get("kind", "no moment"),
                          "is_global": bool((x["biggest_moment"] or {}).get("is_global")),
                          "any": "shock" if x.get("month_has_shock") else (
                              "appointment" if x.get("month_has_appointment") else "neither")}
                         for d in WAVE_CHART for x in d["returns"]])
    _kinds = ["shock", "appointment", "neither"]
    _by_group = {g_: _ret[_ret.group == g_].kind.value_counts().reindex(_kinds, fill_value=0).astype(int).to_dict()
                 for g_ in WAVE_CHART_GROUPS}
    _by_group["all"] = _ret.kind.value_counts().reindex(_kinds, fill_value=0).astype(int).to_dict()
    _by_group_any = {g_: _ret[_ret.group == g_]["any"].value_counts().reindex(_kinds, fill_value=0).astype(int).to_dict()
                     for g_ in WAVE_CHART_GROUPS}
    _by_group_any["all"] = _ret["any"].value_counts().reindex(_kinds, fill_value=0).astype(int).to_dict()
    _glob = {g_: int(_ret[(_ret.group == g_) if g_ != "all" else _ret.group.notna()].is_global.sum())
             for g_ in list(WAVE_CHART_GROUPS) + ["all"]}
    write("waves_chart.json", {
        "note": "Wave chart: the clean-set stories hand-labelled real recurring stories on the wave verification "
                "sheet (Venezuela and Nicolás Maduro merged). countries_per_month follows months (gap months in "
                "month_coverage, with days collected / days). returns = every month at 15+, with the story's "
                "biggest moment that month (most countries; any moment of its topics starting that month) and its "
                "kind: shock (in shocks.json), appointment (a member of an appointment event in appointments.json) "
                "or neither. notes = the hand notes from the verification sheet.",
        "months": months, "month_coverage": _mcov, "groups": WAVE_CHART_GROUPS,
        "returns_by_group": _by_group,
        "returns_by_group_note": "returns_by_group = kind of each return's biggest moment (most countries). Shocks and "
                                 "appointments are global moments (15+ countries within 60 min), so a slow build that "
                                 "reaches many countries over hours or days counts as neither; biggest_moment_global "
                                 "counts the returns whose biggest moment is global. returns_by_group_any_moment = "
                                 "the month has any shock (else any appointment) moment of the story.",
        "biggest_moment_global": _glob, "returns_by_group_any_moment": _by_group_any, "stories": WAVE_CHART})
    print(f"  wave chart: {len(WAVE_CHART)} stories, {len(_ret)} returns; biggest moment by group {_by_group}; "
          f"global {_glob}; any moment in the month {_by_group_any}", flush=True)
    num("Waves", "Wave chart: stories (hand-verified real recurring stories) / returns (months at 15+)",
        f"{len(WAVE_CHART)} / {len(_ret)}", "waves_chart.json", "stories")
    for g_, v_ in _by_group.items():
        n_ = sum(v_.values())
        num("Waves", f"Wave chart returns, {g_}: biggest moment a shock / an appointment / neither",
            f"{v_['shock']} / {v_['appointment']} / {v_['neither']} of {n_}"
            + (f" ({v_['shock'] / n_:.0%} / {v_['appointment'] / n_:.0%} / {v_['neither'] / n_:.0%})" if n_ else ""),
            "waves_chart.json", "returns_by_group")
        num("Waves", f"Wave chart returns, {g_}: biggest moment global (15+ countries within 60 min)",
            f"{_glob[g_]} of {n_}", "waves_chart.json", "biggest_moment_global")
        va_ = _by_group_any[g_]
        num("Waves", f"Wave chart returns, {g_}: month has any shock / else any appointment / neither",
            f"{va_['shock']} / {va_['appointment']} / {va_['neither']} of {n_}", "waves_chart.json",
            "returns_by_group_any_moment")
    for d in WAVE_CHART:
        k_ = pd.Series([(x["biggest_moment"] or {}).get("kind") for x in d["returns"]]).value_counts()
        num("Waves", f"Wave chart: {d['story']} ({d['group']}): months at 15+ / countries / shock-appointment-neither",
            f"{d['months_15plus']} / {d['distinct_countries']} / {int(k_.get('shock', 0))}-"
            f"{int(k_.get('appointment', 0))}-{int(k_.get('neither', 0))}", "waves_chart.json", "stories")
else:
    print("  wave chart: docs/wave_chart_verification.csv not found (local hand labels); waves_chart.json not written",
          flush=True)


# ------------------------------------------------------------------ 5d wave speed (Step 9 round 31)
# "Waves spread slowly and come back." Daily series of the 18 chart stories; 72-hour curves of each story's biggest
# return (and Iran's June 2025 return from the US strikes) and of four shocks; and a baseline over every non-sport,
# non-hidden moment whose 72-hour total reaches 50+ (and 30+) countries.
# Counting (same for all): origin = the moment's start (its first country's trend). Countries where the topic set
# trended in the 24 h before the origin are "already trending" and left out. The clock starts at the third new
# country's first trend (as in the global-moment rule); the curve is cumulative distinct new countries (the first two
# count at 0), every 10 min for 6 h, then hourly to 72 h. hours_to_half = hours until half of the 72-hour total.
SPEED_THRESHOLDS = (50, 30)
CURVE_MIN = list(range(0, 361, 10)) + list(range(420, 72 * 60 + 1, 60))
print("wave speed ...", flush=True)
_cc_code = {c: i for i, c in enumerate(sorted(tv.country_code.unique()))}
_tsec = tv.start_time_utc.astype("int64").to_numpy() // 10**9
_tv_arr = pd.DataFrame({"topic_id": tv.topic_id.values, "cc": tv.country_code.map(_cc_code).values, "ts": _tsec})


def _arrays(topic_ids):
    d = _tv_arr[_tv_arr.topic_id.isin(set(topic_ids))].sort_values("ts")
    return d.ts.to_numpy(), d.cc.to_numpy()


def curve72(ts, cc, origin, curve=True):
    """ts, cc: sorted row start times (s) and country codes of a topic set; origin: Timestamp or seconds."""
    o = int(pd.Timestamp(origin).timestamp()) if not isinstance(origin, (int, np.integer)) else int(origin)
    a, b = np.searchsorted(ts, [o - 86400, o])
    already = set(cc[a:b].tolist())
    c_ = np.searchsorted(ts, o + 80 * 3600)
    pt, pc = ts[b:c_], cc[b:c_]
    if already:
        keep = ~np.isin(pc, list(already))
        pt, pc = pt[keep], pc[keep]
    _, first_idx = np.unique(pc, return_index=True)
    first = np.sort(pt[first_idx])
    if len(first) < 3:
        return None
    zero = first[2]
    mins = np.clip((first - zero) / 60.0, 0, None)
    mins = mins[mins <= 72 * 60]
    total = len(mins)
    half = float(np.sort(mins)[int(np.ceil(total / 2)) - 1] / 60)
    out = {"already_trending": len(already), "start_utc": f"{pd.Timestamp(zero, unit='s'):%Y-%m-%dT%H:%MZ}",
           "total_72h": int(total), "at_1h": int((mins <= 60).sum()), "at_24h": int((mins <= 1440).sum()),
           "at_72h": int(total), "share_1h": round(float((mins <= 60).sum() / total), 3),
           "hours_to_half": round(half, 2)}
    if curve:
        out["curve"] = [[mn, int((mins <= mn).sum())] for mn in CURVE_MIN]
    return out


WAVES_SPEED = {}
if WAVE_CHART:
    # 1 daily series
    _daily_days = pd.date_range(t.day.min(), t.day.max(), freq="D").strftime("%Y-%m-%d")
    _gapset = set(gap_days)
    daily_series = []
    for d in WAVE_CHART:
        r_ = tv[tv.topic_id.isin(set(d["topic_ids"]))]
        cnt = r_.groupby("day").country_code.nunique()
        daily_series.append({"story": d["story"], "group": d["group"],
                             "countries_per_day": [int(cnt.get(x, 0)) for x in _daily_days]})
    # 2 biggest return of each story (+ Iran from the US strikes)
    big_returns = []
    for d in WAVE_CHART:
        ts_, cc_ = _arrays(d["topic_ids"])
        rb = max((x for x in d["returns"] if x["biggest_moment"]), key=lambda x: x["countries"])
        bm = rb["biggest_moment"]
        cv = curve72(ts_, cc_, pd.Timestamp(bm["start_utc"].replace("Z", ""), tz="UTC"))
        big_returns.append({"story": d["story"], "group": d["group"], "month": rb["month"],
                            "month_countries": rb["countries"], "moment_start_utc": bm["start_utc"],
                            "moment_kind": bm["kind"], **(cv or {})})
        if d["story"] == "Iran":
            _us = m[m.topic_id.isin(set(d["topic_ids"])) & (m.start_utc.dt.strftime("%Y-%m-%d") == "2025-06-22")]
            _us = _us.sort_values(["reach", "reach_60"], ascending=False)
            if len(_us):
                u0 = _us.iloc[0]
                cv2 = curve72(ts_, cc_, u0.start_utc)
                big_returns.append({"story": "Iran (US strikes, 22 Jun 2025)", "group": d["group"],
                                    "month": "2025-06", "month_countries": rb["countries"] if rb["month"] == "2025-06"
                                    else None, "moment_start_utc": f"{u0.start_utc:%Y-%m-%dT%H:%MZ}",
                                    "moment_kind": "shock" if int(u0.moment_id) in _shock_ids else "other",
                                    "extra": True, **(cv2 or {})})
    # 3 four shocks
    SPEED_SHOCKS = [("Pope Francis", "2025-04-21"), ("ChatGPT", "2025-01-23"), ("Diogo Jota", "2025-07-03"),
                    ("Venezuela", "2026-01-03")]
    shock_curves = []
    for nm_, day_ in SPEED_SHOCKS:
        cand = [x for x in shocks if x["name"] == nm_ and x["date_utc"][:10] == day_]
        if not cand:
            print(f"  wave speed: shock {nm_} {day_} not found", flush=True)
            continue
        x = max(cand, key=lambda y: y["reach"])
        grp = {x["topic_id"]} | (EVENT_GROUPS or {}).get(x["moment_id"], set())
        ts_, cc_ = _arrays(grp)
        cv = curve72(ts_, cc_, pd.Timestamp(x["date_utc"].replace("Z", ""), tz="UTC"))
        shock_curves.append({"shock": nm_, "date_utc": x["date_utc"], "topics": sorted(name.get(g, g) for g in grp),
                             **(cv or {})})
    # 4 baseline: every non-sport, non-hidden moment (single topic); wave returns with the story's topics
    _bm = m[~m.is_sport.astype(bool) & ~m.topic_id.isin(hidden)]
    _nc = tv.groupby("topic_id").country_code.nunique()
    _bm = _bm[_bm.topic_id.isin(set(_nc[_nc >= min(SPEED_THRESHOLDS)].index))]
    _arr_by_topic = {k: (g.ts.to_numpy(), g.cc.to_numpy())
                     for k, g in _tv_arr[_tv_arr.topic_id.isin(set(_bm.topic_id))].sort_values("ts").groupby("topic_id")}
    _wave_moments = {x["biggest_moment"]["moment_id"] for d in WAVE_CHART for x in d["returns"] if x["biggest_moment"]}
    base = []
    _o = (_bm.start_utc.astype("int64") // 10**9).to_numpy()
    for tid, mid, o in zip(_bm.topic_id.values, _bm.moment_id.values, _o):
        ts_, cc_ = _arr_by_topic[tid]
        lo_, hi_ = np.searchsorted(ts_, [o, o + 80 * 3600])
        if hi_ - lo_ < min(SPEED_THRESHOLDS):        # fewer rows than the threshold: cannot reach it
            continue
        cv = curve72(ts_, cc_, int(o), curve=False)
        if cv and cv["total_72h"] >= min(SPEED_THRESHOLDS):
            mid = int(mid)
            grp_ = "shock" if mid in _shock_ids else ("appointment" if mid in _appt_ids else "other")
            base.append({"moment_id": mid, "group": grp_, "wave_moment": mid in _wave_moments,
                         "total_72h": cv["total_72h"], "share_1h": cv["share_1h"], "hours_to_half": cv["hours_to_half"]})
    base = pd.DataFrame(base)
    wret = []
    for d in WAVE_CHART:
        ts_, cc_ = _arrays(d["topic_ids"])
        for x in d["returns"]:
            if x["biggest_moment"]:
                cv = curve72(ts_, cc_, pd.Timestamp(x["biggest_moment"]["start_utc"].replace("Z", ""), tz="UTC"),
                             curve=False)
                if cv:
                    wret.append({"story": d["story"], "month": x["month"], "total_72h": cv["total_72h"],
                                 "share_1h": cv["share_1h"], "hours_to_half": cv["hours_to_half"]})
    wret = pd.DataFrame(wret)

    def _dist(d):
        if d.empty:
            return {"n": 0}
        q = d.share_1h.quantile([0.25, 0.5, 0.75])
        h = d.hours_to_half.quantile([0.25, 0.5, 0.75])
        hist = np.histogram(d.share_1h.clip(0, 1), bins=np.linspace(0, 1, 11))[0]
        return {"n": int(len(d)), "share_1h": {"q1": round(float(q[0.25]), 3), "median": round(float(q[0.5]), 3),
                                               "q3": round(float(q[0.75]), 3)},
                "hours_to_half": {"q1": round(float(h[0.25]), 2), "median": round(float(h[0.5]), 2),
                                  "q3": round(float(h[0.75]), 2)},
                "share_1h_histogram_10pct": [int(v) for v in hist]}

    baseline = {}
    for th in SPEED_THRESHOLDS:
        b_ = base[base.total_72h >= th]
        w_ = wret[wret.total_72h >= th] if len(wret) else wret
        baseline[f"{th}_plus"] = {"all": _dist(b_), "shocks": _dist(b_[b_.group == "shock"]),
                                  "appointments": _dist(b_[b_.group == "appointment"]), "wave_returns": _dist(w_),
                                  "everything_else": _dist(b_[(b_.group == "other") & ~b_.wave_moment])}
    WAVES_SPEED = {
        "note": "72-hour curves: origin = the moment's start (first country). Countries where the topic set trended "
                "in the 24 h before the origin are already_trending and left out. The clock starts at the third new "
                "country's first trend; curve = [minutes from the start, cumulative distinct new countries], every 10 "
                "min to 6 h then hourly to 72 h. hours_to_half = hours until half of the 72-hour total. Wave stories "
                "count any topic of the story; shocks count the shock's topic and its reviewed event group; the "
                "baseline counts each moment's own topic. Baseline = every non-sport, non-hidden moment whose 72-hour "
                "total reaches the threshold (global or not); groups: shocks (shocks.json), appointments (members of "
                "appointments.json events), wave_returns (the 18 stories' biggest moment in each month at 15+, with "
                "the story's topics), everything_else (the rest, without the wave stories' moments). "
                "share_1h_histogram_10pct: counts in bins [0-10%), [10-20%) ... [90-100%].",
        "days": list(_daily_days), "gap_days": sorted(_gapset & set(_daily_days)),
        "daily_series": daily_series, "biggest_returns": big_returns, "shocks": shock_curves,
        "baseline": baseline}
    write("waves_speed.json", WAVES_SPEED)
    for th in SPEED_THRESHOLDS:
        for g_, v_ in baseline[f"{th}_plus"].items():
            if v_.get("n"):
                print(f"  speed {th}+ {g_}: n={v_['n']} share_1h median {v_['share_1h']['median']:.0%} "
                      f"(IQR {v_['share_1h']['q1']:.0%}-{v_['share_1h']['q3']:.0%}); hours to half median "
                      f"{v_['hours_to_half']['median']:g}", flush=True)
                num("Waves", f"Speed baseline {th}+ countries in 72 h, {g_.replace('_', ' ')}: moments / median share "
                    f"within 1 h / median hours to half", f"{v_['n']:,} / {v_['share_1h']['median']:.0%} / "
                    f"{v_['hours_to_half']['median']:g}", "waves_speed.json", f"baseline.{th}_plus.{g_}")
    for x in big_returns + shock_curves:
        lab_ = x.get("story") or f"shock {x['shock']} ({x['date_utc'][:10]})"
        if "total_72h" in x:
            print(f"  curve {lab_}: start {x['start_utc']}, already {x['already_trending']}, 1h {x['at_1h']}, "
                  f"24h {x['at_24h']}, 72h {x['at_72h']}, hours to half {x['hours_to_half']}", flush=True)
            num("Waves", f"72-h curve, {lab_}" + (f" ({x['month']})" if x.get("month") else "")
                + ": already trending / 1 h / 24 h / 72 h / hours to half",
                f"{x['already_trending']} / {x['at_1h']} / {x['at_24h']} / {x['at_72h']} / {x['hours_to_half']:g}",
                "waves_speed.json", "biggest_returns" if x.get("story") else "shocks")

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
# weather days: only days with full collection coverage (not a gap day), from the first to the last data day
all_days = pd.date_range(t.day.min(), t.day.max(), freq="D").strftime("%Y-%m-%d")
full_days = [d for d in all_days if d not in set(gap_days)]
wx_named = set(meta.index[meta.topic_name == "Weather"]) - hidden        # every topic Claude named exactly "Weather"


def days_10plus(ids):
    cc = tv[tv.topic_id.isin(ids) & tv.day.isin(full_days)].groupby("day").country_code.nunique()
    return int((cc >= 10).sum())


weather_days = {"archive_days": len(all_days), "full_coverage_days": len(full_days),
                "topic_weather_days_10plus": days_10plus(wx_named), "topic_weather_n_topics": len(wx_named),
                "topic_weather_plain_id_days_10plus": days_10plus({"Weather"}),
                "any_weather_topic_days_10plus": days_10plus(weather_ids), "any_weather_n_topics": len(weather_ids),
                "note": "Days (UTC) with full collection coverage on which the topic trended in 10+ national feeds. "
                        "'topic Weather' = every topic Claude named exactly 'Weather' (one per language group, e.g. "
                        "'hava durumu', '天気'); plain_id = only the topic whose id is 'Weather' (English 'weather'); "
                        "any = every topic in the weather category (city forecasts, storms, ...)."}
allh = pd.Series(split(w)["all"])
nob = pd.Series(split(w)["all_without_19utc_bump"])
num("Rituals", "Weather: busiest local hour, all countries (with / without 19 UTC bump)", f"{allh.idxmax()} / {nob.idxmax()}",
    "rituals.json", "weather_clock.share_by_local_hour")
num("Rituals", "Archive days (first to last data day) / of which full collection coverage",
    f"{weather_days['archive_days']} / {weather_days['full_coverage_days']}", "rituals.json", "weather_days.full_coverage_days")
num("Rituals", f"(a) Full-coverage days on which the topic 'Weather' ({len(wx_named)} topics named so) trended in 10+ countries",
    weather_days["topic_weather_days_10plus"], "rituals.json", "weather_days.topic_weather_days_10plus")
num("Rituals", "(a') ... the single topic with id 'Weather' only", weather_days["topic_weather_plain_id_days_10plus"],
    "rituals.json", "weather_days.topic_weather_plain_id_days_10plus")
num("Rituals", f"(b) Full-coverage days on which any weather topic ({len(weather_ids):,} topics) trended in 10+ countries",
    weather_days["any_weather_topic_days_10plus"], "rituals.json", "weather_days.any_weather_topic_days_10plus")


# ------------------------------------------------------------------ 6b rituals validation (Step 9 round 32)
print("rituals review ...", flush=True)
import pytz  # noqa: E402
from kinds import RITUAL_RE, topic_ritual  # noqa: E402
RIT_RULE = ("A topic is ritual if any of: (1) Claude's category is weather; (2) Claude's type is holiday; (3) its name "
            "matches RITUAL_RE (lotteries, prayer times, horoscopes, daily puzzles, exchange / gold / fuel rates, "
            "weather words, TV guide ...); (4) it is not sport, its type is other / product / company / unlabeled, "
            "and it has 15+ moments of 10+ countries. Every moment of a ritual topic is a ritual moment, unless it is "
            "a shock (shocks win) (pipeline/kinds.py topic_ritual, moment_kinds).")
_rit = topic_ritual(meta, m)
# sport-like: topic sport rule, athlete (wave check), or most of the topic's moments sport (moment-level rule)
_msport = m.groupby("topic_id").is_sport.mean()
SPORT_LIKE = set(meta.index[meta.is_sport.fillna(False).astype(bool) | meta.is_athlete.fillna(False).astype(bool)]) | \
    set(_msport.index[_msport >= 0.5])
RIT_IDS = set(_rit.index[_rit]) - hidden - _down_ids    # "is it down" is with Shocks (round 33)
_nm_l = name.str.lower()
_rit_part = pd.DataFrame({"weather": meta.category.eq("weather"), "holiday": meta["type"].eq("holiday"),
                          "name_pattern": _nm_l.str.contains(RITUAL_RE, regex=True)}).reindex(list(RIT_IDS))
_rr = tv[tv.topic_id.isin(RIT_IDS)].copy()
_rr["wd"] = _rr.local_time.dt.dayofweek
_rr["qn"] = _rr.query_raw.astype(str).str.strip().str.lower()


def _top_phr(rows, k=3):
    return rows.groupby("topic_id").qn.agg(lambda s: s.value_counts().head(k).index.tolist()).to_dict()


_phr = _top_phr(_rr)
_dayc = _rr.groupby(["topic_id", "day"]).country_code.nunique()
_peak = _dayc.groupby(level=0).idxmax().map(lambda x: x[1])
_peakc = _dayc.groupby(level=0).max()
_agg = _rr.groupby("topic_id").agg(trends=("country_code", "size"), countries=("country_code", "nunique"),
                                    active_days=("ldate", "nunique"), first=("ldate", "min"), last=("ldate", "max"))
_agg["span"] = (pd.to_datetime(_agg["last"]) - pd.to_datetime(_agg["first"])).dt.days + 1
_wdshare = _rr.groupby(["topic_id", "wd"]).size().groupby(level=0).max() / _agg.trends
_weeks = _rr.assign(wk=pd.to_datetime(_rr.ldate).dt.to_period("W")).groupby("topic_id").wk.nunique()
# yearly concentration: share of trends within 10 days (day of year, circular) of the peak day
_pdoy = pd.to_datetime(_peak).dt.dayofyear
_rdoy = pd.to_datetime(_rr.ldate).dt.dayofyear.to_numpy()
_dist = np.abs(_rdoy - _rr.topic_id.map(_pdoy).to_numpy())
_dist = np.minimum(_dist, 365 - _dist)
_yshare = pd.Series(_dist <= 10, index=_rr.index).groupby(_rr.topic_id).mean()


def _cycle(tid):
    a_ = _agg.loc[tid]
    if a_.trends < 5:
        return "too few trends"
    if (meta["type"].get(tid) == "holiday" and _yshare.get(tid, 0) >= 0.5) or \
            (_yshare.get(tid, 0) >= 0.8 and a_.active_days <= 60):
        return "yearly"
    if a_.span >= 60 and a_.active_days / a_.span >= 0.3:
        return "daily"
    if _weeks.get(tid, 0) >= 6 and _wdshare.get(tid, 0) >= 0.5:
        return "weekly"
    return "unclear (sporadic)"


rit_topics = []
for tid in _agg.sort_values("trends", ascending=False).index:
    parts = [k for k in ("weather", "holiday", "name_pattern") if bool(_rit_part.loc[tid, k])] or ["15+ moments of 10+"]
    rit_topics.append({"topic_id": tid, "name": name.get(tid), "rule": parts, "phrasings": _phr.get(tid, []),
                       "countries": int(_agg.loc[tid, "countries"]), "trends": int(_agg.loc[tid, "trends"]),
                       "peak_day": _peak.get(tid), "peak_countries": int(_peakc.get(tid, 0)),
                       "active_local_days": int(_agg.loc[tid, "active_days"]), "proposed_cycle": _cycle(tid),
                       "sport_like": tid in SPORT_LIKE})
_cyc = pd.Series([x["proposed_cycle"] for x in rit_topics]).value_counts().to_dict()
print(f"  ritual topics {len(rit_topics):,}; proposed cycles {_cyc}", flush=True)

# weather clock
_mz = set()
for c in tv.country_code.unique():
    zs = pytz.country_timezones.get(c, [])
    offs = {pd.Timestamp(d_, tz=z).utcoffset() for z in zs for d_ in ("2025-01-15", "2025-07-15")}
    if len({pd.Timestamp("2025-01-15", tz=z).utcoffset() for z in zs}) > 1 or \
            len({pd.Timestamp("2025-07-15", tz=z).utcoffset() for z in zs}) > 1:
        _mz.add(c)


def _share(d):
    h = pd.Series(hours(d))
    return [round(float(x), 4) for x in (h / h.sum()).values] if h.sum() else [0] * 24


_wt = w[~w.tomorrow]
weather_clock = {
    "local_time_rule": "Local hour of each trend's start. US, CA and RU: regional feeds, each region in its own zone "
                       "(REGION_TZ). Every other country: its national feed in one zone (data/interim/"
                       "country_timezones.json, the capital's zone), including countries with several zones.",
    "today_share_by_local_hour": _share(_wt), "tomorrow_share_by_local_hour": _share(w[w.tomorrow]),
    "today_trends": int(len(_wt)), "tomorrow_trends": int(w.tomorrow.sum()),
    "robustness_without_multizone": {
        "countries_left_out": sorted(_mz),
        "rule": "countries whose time zones (pytz) have 2+ UTC offsets in January or July are left out",
        "today_share_by_local_hour": _share(_wt[~_wt.country_code.isin(_mz)]),
        "tomorrow_share_by_local_hour": _share(w[w.tomorrow & ~w.country_code.isin(_mz)])},
    "today_share_without_19utc_bump": _share(_wt[~_wt.utc19_bump.fillna(False).astype(bool)])}
# scrapes: the archive has a collection DATE per row (one cron run per day), not a scrape time. Proxy for each day's
# scrape hour: the latest national trend start in that day's collection.
_col = pd.read_parquet(INTERIM / "topics.parquet", columns=["level", "collection_date", "start_time_utc",
                                                             "duration_minutes", "duration_is_estimate"])
_col = _col[_col.level == "country"]
_last = _col.groupby("collection_date").start_time_utc.max()
_scr = _last.dt.hour.value_counts().reindex(range(24), fill_value=0).astype(int).tolist()
_col["h"] = _col.start_time_utc.dt.hour
_long = _col.assign(long=_col.duration_minutes >= 20 * 60).groupby("h").long.mean()
_est = _col.groupby("h").duration_is_estimate.mean()
_starts = _col.h.value_counts().reindex(range(24), fill_value=0)
scrape_check = {
    "note": "No scrape timestamps in the archive: rows carry a collection date, and the scraper runs once a day "
            "(data/raw/trendsscraper_public.py, cron; Trending Now pages of the last 24 h). latest_start_hour_per_"
            "collection_day = UTC hour of the latest national trend start in each day's collection (a proxy for the "
            "scrape time). trend_starts_by_utc_hour, share_20h_plus_by_utc_hour and duration_estimate_share_by_utc_"
            "hour test whether the 19:00 UTC excess is a cut-off at the edge of the 24-hour window.",
    "collection_days": int(len(_last)), "latest_start_hour_per_collection_day": _scr,
    "trend_starts_by_utc_hour": [int(x) for x in _starts.values],
    "share_20h_plus_by_utc_hour": [round(float(_long.get(h_, 0)), 4) for h_ in range(24)],
    "duration_estimate_share_by_utc_hour": [round(float(_est.get(h_, 0)), 4) for h_ in range(24)]}
_pk = pd.DataFrame([{"country": c, "country_name": v["country_name"], "trends": v["trends"], "peak_hour": v["peak_hour"],
                     "peak_hour_without_19utc": int(pd.Series(v["weather"]["all_without_19utc_bump"]).idxmax()),
                     "multizone": c in _mz} for c, v in per_c.items()]).sort_values("trends", ascending=False)
weather_clock["peak_local_hour_per_country"] = _pk.to_dict("records")
weather_clock["countries_per_peak_hour"] = _pk.peak_hour.value_counts().reindex(range(24), fill_value=0).astype(int).tolist()
weather_clock["countries_per_peak_hour_without_19utc"] = _pk.peak_hour_without_19utc.value_counts().reindex(
    range(24), fill_value=0).astype(int).tolist()

# weather days: topics named "Weather" and a random sample of the weather topics
_wx_rows = tv[tv.topic_id.isin(weather_ids)].assign(qn=lambda d: d.query_raw.astype(str).str.strip().str.lower())
_wxp = _wx_rows.groupby("topic_id").qn.agg(lambda s: s.value_counts().head(3).index.tolist()).to_dict()
_wxa = _wx_rows.groupby("topic_id").agg(trends=("country_code", "size"), countries=("country_code", "nunique"))


def _wx_item(tid):
    return {"topic_id": tid, "name": name.get(tid), "phrasings": _wxp.get(tid, []),
            "countries": int(_wxa.countries.get(tid, 0)), "trends": int(_wxa.trends.get(tid, 0))}


_rng = random.Random(41)
weather_topics = {"named_weather": [_wx_item(x) for x in sorted(wx_named, key=lambda x: -_wxa.trends.get(x, 0))],
                  "random_sample_40": [_wx_item(x) for x in _rng.sample(sorted(weather_ids), 40)],
                  "n_weather_topics": len(weather_ids), "days_10plus": weather_days}

# holidays (Step 9 round 33): a broad name rule per holiday (Claude topic name), then cleaned of name matches
# (people, places, clubs, brands) and of other days that share the word. Lunar New Year greetings belong to Lunar
# New Year, not New Year. Every list below is on topics with national trends (not hidden).
from wikidata import HUMAN_QID, get_p31  # noqa: E402
LNY_RX = (r"lunar new year|chinese new year|new year.*(chinese|lunar)|gong xi fa cai|gong hei fat choy|kung hei fat cho|"
          r"xin nian kuai le|capodanno cinese|nouvel an chinois|a[ñn]o nuevo chino|ano novo chin[eê]s|mondneujahr|"
          r"chinesisches neujahr|t[eế]t (nguy[eê]n [dđ][aá]n|[aâ]m l[iị]ch)|\btết\b|seollal|\bimlek\b|春节|春節|"
          r"spring festival gala|農曆新年|农历新年|설날")
HOLIDAYS = {"Ramadan": r"\bramadan\b|ramazan|ramad[aã]n|ramadhan",
            "Eid": r"\beid\b|eid al|eid-al|bayram|lebaran|hari raya|aidilfitri|idul fitri|idul adha|aid el|a[iï]d al",
            "Easter": r"\beaster\b|pascua|p[aá]scoa|ostern\b|p[aâ]ques|pasqua|semana santa",
            "Christmas": r"christmas|\bxmas\b|navidad|\bnatal\b|no[eë]l|weihnacht|\bnatale\b|рождеств|kerst",
            "New Year": r"new year|a[ñn]o nuevo|ano novo|nouvel an|neujahr|capodanno|новый год|nochevieja|silvester|"
                        r"r[ée]veillon|yılbaşı|yilbasi|t[eế]t d[uư][oơ]ng l[iị]ch",
            "Halloween": r"halloween",
            "Valentine's Day": r"valentin|dia dos namorados|情人節|情人节",
            "Diwali": r"diwali|deepavali|dipawali",
            "Lunar New Year": LNY_RX,
            "Mother's Day": r"mother'?s day|d[ií]a de (la|las) madres?|dia das m[ãa]es|f[eê]te des m[eè]res|muttertag|"
                            r"festa della mamma|anneler g[uü]n[uü]|moederdag",
            "Black Friday": r"black friday",
            "Women's Day": r"women'?s day|d[ií]a (internacional )?de la mujer|dia (internacional )?da mulher|"
                           r"journ[ée]e (internationale )?des (droits des )?femmes|frauentag|festa della donna|"
                           r"(?<!\d)8 (mart|марта|march|marzo|marca)|kad[ıi]nlar g[uü]n[uü]|международный женский|"
                           r"ng[aà]y qu[oố]c t[eế] ph[uụ] n[uữ]|hari perempuan|妇女节|婦女節|يوم المرأة|dzie[nń] kobiet"}
# holiday words used as names of people, places, clubs or brands
HOL_NAME_RE = {
    "Ramadan": r"ramazan (tetik|ar[ıi]kan|ba[sş]ak|bing[oö]l|can\b|kurto[gğ]lu|g[uü]lten|ka[sş]l[ıi]|demir|y[ıi]ld[ıi]z|"
               r"sar[ıi])|ramazani|mert ramazan|survivor ramazan|g[oö]n[uü]l da[gğ][ıi] ramazan|"
               r"ramadan (sobh|ahmeti|rouabah)|tariq ramadan|karar ramadan|nahla ramadan|mohamed ramadan|said ramadan",
    "Eid": r"\w+bayram|bayram(ov|o[gğ]lu)|serkan bayram|bayram ali|emin bayram|[oö]mer bayram|tuna bayram|"
           r"hac[ıi] bayram veli|bayrami[cç]|bayrampa[sş]a|(mahmoud|soliman|amir|said) eid\b",
    "Easter": r"pascual|pasquale|pascoal|pasqual\b|pasqualini|pasquali\b|pasquarosa|pasquantino|pasqualone|"
              r"easter island|klosterneuburg",
    "Christmas": r"noel o.callaghan|no[eë]l[ií]a|no[eë]lle|no[eë]line|noelvi|manoel|noel 格闘家|no[eë]l-baker|"
                 r"(jean|marie|mar[ií]a|cl[eé]ment|jules|fran[cç]ois|matthieu|tim|tova|brandon|gifton|david|kervon|"
                 r"nerlens|jaylin|geert)[- ]no[eë]ls?\b|"
                 r"no[eë]l (gallagher|fielding|edmonds|clarke|tata|robinson|johansen|ebenezer|stanton|barrionuevo|"
                 r"t[oö]rnqvist|leeming|mcgrath|radford|meade|fitzpatrick|leon|eichinger|rosal|nordh|van kleef|hunt|"
                 r"farrell|hoefenmayer|rodriguez|acciari|phillips|as[eé]ko|dempsey|gunler|futkeu|coward)|"
                 r"kerstin|kersti\b|kersting|bickerstaff|kerstrand|akkerstr|zuckerstreu|carnatal|baunatal|natal chart|"
                 r"natalee|kwazulu|santa cruz de natal|am[eé]rica de natal|am[eé]rica-rn|abc .*natal|"
                 r"aeroporto de natal|natal-rn|natal/rn|natal \(rn\)|em natal\b|(andrea|enzo|antonio di|tot[oò] di) natale\b|"
                 r"natale dalla|natal \w+ (x|vs)|(x|vs) .*natal\b|christmas island",
    "Valentine's Day": r"valentin[aoie]?\b|valentini\b",
    "Lunar New Year": r"\b(ap|assam|ctet|htet|reet|mahatet|kartet) (tet|result)|tet (result|certificate|e certificate|exam|"
                      r"admit|answer|response)|\bap tet\b|ille sur tet",
}
# always a name, even next to a holiday word
HOL_STRONG_RE = {"Valentine's Day": r"james valentine|carrington valentine|valentine (holmes|ozigbo|rosales|cadic)|"
                                    r"my bloody valentine|bullet for my valentine|blue valentine|bill martin valentine"}
# holiday context: a name word next to one of these phrases is the holiday (Père Noël, veglia pasquale, San Valentín)
HOL_CTX = {
    "Christmas": r"(papa|papá|p[eè]re|papai|pai|baba|ng[aà]y|nh[aạ]c|de|du|chant|joyeux|film|loto|march[eé]|parade|sapin|"
                 r"solde|soldes|vacances|cadeaux?|b[uû]che|cr[eè]che|repas|menu|apr[eè]s|veille|r[ée]veillon|ouvert|"
                 r"ferm[eé]|calendrier|lettre|chanson|musique|jeux|feu|night|panne|benediction|livreur|sciarada) no[eë]l\b|"
                 r"no[eë]l (20\d\d|baba|night|au |dans |\d|à|en |de |des |du |tree|market)|^no[eë]l$|joyeux noel",
    "Easter": r"(veglia|colomba|vigilia|domenica|luned[iì]) pas(quale|cual)|vigilia pascual",
    "Valentine's Day": r"valentine'?s|valentine (day|week|gift|card)|san valent|saint[- ]?valentin|st\.? valentin|"
                       r"sfantul valentin|valentin ?nap|valentinstag|valentino diena|valentinsdag|dia de s[aã]o valentim|"
                       r"情人|valentinovo|valentines|valentine\b(?!.*(holmes|ozigbo|rosales|cadic|museum))",
}
# other days that share the word (not this holiday); New Year's Lunar topics go to Lunar New Year
HOL_OTHER_RE = {
    "Eid": r"cumhuriyet bayram|zafer bayram|kabotaj|[cç]ocuk bayram|egemenlik|t[ıi]p bayram|gen[cç]lik ve spor|"
           r"23 nisan|29 ekim|30 a[gğ]ustos|19 may[ıi]s|1 temmuz|hari raya (natal|nyepi|waisak|galungan|kuningan|"
           r"imlek|pentakosta|paskah)|nevruz|dil bayram|paskalya|i[sş][cç]i bayram|nardugan|new year|رأس السنة",
    "New Year": r"chinese|lunar|cinese|chinois|chino\b|chin[eê]s|mondneujahr|chinesisch|gong xi|kung hei|xin nian",
    "Lunar New Year": r"t[eế]t [dđ]oan ng[oọ]|t[eế]t [dđ][oộ]c l[aậ]p|thanh minh|t[eế]t d[uư][oơ]ng l[iị]ch",
    # Women's Day: national women's days on other dates (Paraguay 24 Feb, Bolivia 11 Oct, Colombia 14 Oct, Honduras
    # 25 Jan, South Africa 9 Aug, UAE 28 Aug, Viet Nam 20 Oct), profession days, and searches that only share the date
    "Women's Day": r"20/10|20-10|vi[eệ]t nam|vietnamese women|paraguaya|boliviana|colombiana|hondure[ñn]a|"
                   r"mujer (ingeniera|medica|m[eé]dica|policia)|ni[ñn]a en la ciencia|"
                   r"mulher (negra|advogada)|(?<!inter)national women|south africa|emirati|الإماراتية|البحرينية|"
                   r"\b8 mart (ma[cç]|s[uü]per lig)|alt[ıi]n fiyat|loto|survivor|беспилотник|гороскоп|магнитн|лото|"
                   r"шоу маска|наша раша",
}
# 情人節 / 七夕 / Qixi: Chinese for Valentine's Day, but also Qixi (August), White Day (14 Mar) and other 14ths:
# kept only when the topic's widest day is within 7 days of 14 February
HOL_PEAK_RULE = {"Valentine's Day": (r"情人|七夕|qixi", 2, 14, 7)}
# the holiday's date per year in the archive (2024-11-27 to 2026-05-17); series pairs the same holiday across years.
# Mother's Day = second Sunday of May (US and most countries; the UK's Mothering Sunday in March is its own peak);
# Ramadan = first day of fasting (Saudi calendar); Eid al-Adha 2026 (27 May) is after the archive ends.
HOLIDAY_DATES = {
    "Ramadan": [("Ramadan", "2025-03-01"), ("Ramadan", "2026-02-18")],
    "Eid": [("Eid al-Fitr", "2025-03-30"), ("Eid al-Fitr", "2026-03-20"), ("Eid al-Adha", "2025-06-06")],
    "Easter": [("Easter", "2025-04-20"), ("Easter", "2026-04-05")],
    "Christmas": [("Christmas", "2024-12-25"), ("Christmas", "2025-12-25")],
    "New Year": [("New Year", "2025-01-01"), ("New Year", "2026-01-01")],
    "Halloween": [("Halloween", "2025-10-31")],
    "Valentine's Day": [("Valentine's Day", "2025-02-14"), ("Valentine's Day", "2026-02-14")],
    "Diwali": [("Diwali", "2025-10-20")],
    "Lunar New Year": [("Lunar New Year", "2025-01-29"), ("Lunar New Year", "2026-02-17")],
    "Mother's Day": [("Mother's Day", "2025-05-11"), ("Mother's Day", "2026-05-10")],
    "Black Friday": [("Black Friday", "2024-11-29"), ("Black Friday", "2025-11-28")],
    "Women's Day": [("Women's Day", "2025-03-08"), ("Women's Day", "2026-03-08")]}
HOL_BEFORE, HOL_AFTER = 10, 5
# round 32 rules, kept to show what the cleaning changed
HOLIDAYS_R32 = {"Eid": r"\beid\b|eid al|eid-al|bayram|lebaran|hari raya|aid el",
                "Lunar New Year": r"lunar new year|chinese new year|\bt[eế]t\b|spring festival|seollal|imlek|春节|春節",
                "Christmas": r"christmas|\bxmas\b|navidad|\bnatal\b|no[eë]l|weihnacht|\bnatale\b|рождеств|kerst"}
ODD_PEAKS = [("Eid", "2024-12-31"), ("Lunar New Year", "2024-12-31"), ("Christmas", "2026-03-26")]

_tv_ids = set(tv.topic_id.unique())
_day_cc = None
_arch_days = set(all_days)


def _hol_rows(ids):
    return tv[tv.topic_id.isin(ids)]


def _peak_day(rows):
    g = rows.groupby("day").agg(c=("country_code", "nunique"), n=("country_code", "size"))
    return g.sort_values(["c", "n"], ascending=False).index[0] if len(g) else None


_hol_cand = {h: (topics_where(rx) & _tv_ids) for h, rx in HOLIDAYS.items()}
_p31 = get_p31({q for ids in _hol_cand.values() for q in meta.qid.reindex(list(ids)).dropna()})
hol_clean, hol_removed = {}, {}
for hname, ids in _hol_cand.items():
    d = meta.loc[sorted(ids)]
    low = d.topic_name.astype(str).str.lower()
    ctx = low.str.contains(HOL_CTX.get(hname, "^$"), regex=True)
    strong = low.str.contains(HOL_STRONG_RE.get(hname, "^$"), regex=True)
    q = d.qid
    why = pd.Series("", index=d.index)
    why[q.map(lambda x: x in _p31 and _p31[x]["coords"] and HUMAN_QID not in _p31[x]["p31"]) & ~ctx] = "Wikidata place"
    why[d["type"].isin(["place"]) & ~ctx & why.eq("")] = "Claude type place"
    why[q.map(lambda x: x in _p31 and HUMAN_QID in _p31[x]["p31"]) & ~ctx & why.eq("")] = "Wikidata human"
    why[d["type"].isin(["person"]) & ~ctx & why.eq("")] = "Claude type person"
    why[(low.str.contains(HOL_NAME_RE.get(hname, "^$"), regex=True) & ~ctx | strong) & why.eq("")] = "holiday word used as a name"
    why[low.str.contains(HOL_OTHER_RE.get(hname, "^$"), regex=True) & why.eq("")] = (
        "moved to Lunar New Year" if hname == "New Year" else "another day sharing the word")
    if hname in HOL_PEAK_RULE:
        rx_, mo_, dy_, tol_ = HOL_PEAK_RULE[hname]
        for tid in d.index[low.str.contains(rx_, regex=True) & why.eq("")]:
            pk = pd.Timestamp(_peak_day(_hol_rows({tid})))
            off = abs((pk - pd.Timestamp(year=pk.year, month=mo_, day=dy_)).days)
            if off > tol_:
                why[tid] = f"Chinese 情人節 / 七夕 topic not within {tol_} days of {mo_:02d}-{dy_:02d}"
    hol_clean[hname] = set(why.index[why.eq("")])
    hol_removed[hname] = why[why.ne("")]
    print(f"  holiday {hname}: {len(ids)} matched, {len(hol_clean[hname])} clean; removed "
          f"{why[why.ne('')].value_counts().to_dict()}", flush=True)


def _hol_item(rows, tid, ph):
    r = rows[rows.topic_id == tid]
    return {"topic_id": tid, "name": name.get(tid), "phrasings": ph.get(tid, []),
            "countries": int(r.country_code.nunique()), "trends": int(len(r)), "peak_day": _peak_day(r)}


holidays, hol_chart = {}, {}
for hname, ids in hol_clean.items():
    rows = _hol_rows(ids)
    allr = _hol_rows(ids | set(hol_removed[hname].index))
    ph = allr.assign(qn=allr.query_raw.astype(str).str.strip().str.lower()).groupby("topic_id").qn.agg(
        lambda s: s.value_counts().head(3).index.tolist()).to_dict()
    tops = sorted([_hol_item(rows, x, ph) for x in ids], key=lambda x: -x["trends"])
    rem = sorted([_hol_item(allr, x, ph) | {"reason": hol_removed[hname][x]} for x in hol_removed[hname].index],
                 key=lambda x: -x["trends"])
    dcc = rows.groupby("day").country_code.agg(set)
    occ = []
    for series_, dt_ in HOLIDAY_DATES[hname]:
        d0 = pd.Timestamp(dt_)
        win = [(d0 + pd.Timedelta(days=k)).strftime("%Y-%m-%d") for k in range(-HOL_BEFORE, HOL_AFTER + 1)]
        ser = [[k - HOL_BEFORE, dd, (len(dcc[dd]) if dd in dcc.index else 0) if dd in _arch_days else None,
                dd in set(gap_days)] for k, dd in enumerate(win)]
        inw = [x for x in ser if x[2] is not None]
        pk = max(inw, key=lambda x: x[2]) if inw else None
        ccs = set().union(*[dcc[dd] for dd in win if dd in dcc.index]) if any(dd in dcc.index for dd in win) else set()
        occ.append({"series": series_, "year": d0.year, "date": dt_,
                    "days_in_archive": len(inw), "peak_day": pk[1] if pk else None,
                    "peak_countries": pk[2] if pk else None, "countries_in_window": len(ccs),
                    "countries_per_day": [x[:3] for x in ser],
                    "gap_days_in_window": [x[1] for x in ser if x[3]], "_cc": ccs})
    both = {}
    for series_ in dict.fromkeys(o_["series"] for o_ in occ):
        oo = [o_ for o_ in occ if o_["series"] == series_ and o_["days_in_archive"] > 0]
        if len(oo) >= 2:
            cc2 = oo[0]["_cc"] & oo[1]["_cc"]
            both[series_] = {"years": [oo[0]["year"], oo[1]["year"]], "countries": len(cc2),
                             "country_codes": sorted(cc2), "country_names": [cname.get(c, c) for c in sorted(cc2)]}
    for o_ in occ:
        o_.pop("_cc")
    dc_all = rows.groupby("day").country_code.nunique().sort_values(ascending=False)
    holidays[hname] = {"rule": HOLIDAYS[hname], "name_rule": HOL_NAME_RE.get(hname), "other_day_rule": HOL_OTHER_RE.get(hname),
                       "n_matched": len(ids) + len(hol_removed[hname]), "n_topics": len(tops),
                       "removed_by_reason": hol_removed[hname].value_counts().to_dict(),
                       "topics": tops, "removed": rem, "occurrences": occ, "countries_in_both_years": both,
                       "top_days_anywhere": [[d_, int(v_)] for d_, v_ in dc_all.head(5).items()]}
    hol_chart[hname] = {"topics": len(tops), "trends": int(len(rows)), "occurrences": occ,
                        "countries_in_both_years": both}
# odd peaks of round 32: countries that day with the round 32 group vs the clean group, and the widest topics before
odd_peaks = []
for hname, day_ in ODD_PEAKS:
    old_ids = topics_where(HOLIDAYS_R32[hname]) & _tv_ids
    r_old = tv[tv.topic_id.isin(old_ids) & (tv.day == day_)]
    r_new = tv[tv.topic_id.isin(hol_clean[hname]) & (tv.day == day_)]
    tt = r_old.groupby("topic_id").country_code.nunique().sort_values(ascending=False).head(5)
    odd_peaks.append({"holiday": hname, "day": day_, "countries_round32": int(r_old.country_code.nunique()),
                      "countries_clean": int(r_new.country_code.nunique()),
                      "top_topics_round32": [{"name": name.get(k), "countries": int(v),
                                              "in_clean_group": k in hol_clean[hname],
                                              "phrasings": r_old[r_old.topic_id == k].query_raw.str.lower()
                                              .value_counts().head(3).index.tolist()} for k, v in tt.items()]})
ODD_PEAK_NOTES = {
    ("Eid", "2024-12-31"): "Arabic 'عيد رأس السنة' (feast of the new year), a topic Claude named 'Eid al-Nahda (New Year's "
                           "Eve)', plus New Year greetings merged into an Eid greetings topic ('كل عام وانتم بخير' is said "
                           "for both). The New Year topic is now in New Year only; the greetings topic stays in Eid.",
    ("Lunar New Year", "2024-12-31"): "Real searches, not a matching error: at the Gregorian New Year people look up the "
                                      "coming Chinese New Year ('chinese new year 2025', 'chinese zodiac 2025', '除夕'). "
                                      "The same echo appears on 2025-12-31. Kept; the charts use the window around the "
                                      "Lunar New Year date.",
    ("Christmas", "2026-03-26"): "Name match: Noelia Castillo, a Spanish euthanasia case in the news (matched 'noel'). "
                                 "Removed by the name rule."}
for o_ in odd_peaks:
    o_["explanation"] = ODD_PEAK_NOTES[(o_["holiday"], o_["day"])]

# cycle scan (non-sport topics; national feeds, local dates and hours; per topic and country)
_ns = tv[~tv.topic_id.isin(SPORT_LIKE)]          # non-sport: no sport topics, athletes or mostly-sport topics
_pd = _ns.groupby(["topic_id", "country_code", "ldate"]).lhour.min().reset_index()
_pd["date"] = pd.to_datetime(_pd.ldate)
_g = _pd.groupby(["topic_id", "country_code"])
_pc = _g.agg(n_days=("ldate", "size"), first=("date", "min"), last=("date", "max")).reset_index()
_pc["span"] = (_pc["last"] - _pc["first"]).dt.days + 1
# daily: 50+ active days, 60%+ of them starting within the same local hour +-1 (Trending Now flags surges, so a daily
# ritual is active on at most a third of the days)
_dc = _pc[_pc.n_days >= 50]
_dh = _pd.merge(_dc[["topic_id", "country_code"]], on=["topic_id", "country_code"])
_hc = _dh.groupby(["topic_id", "country_code", "lhour"]).size().unstack(fill_value=0).reindex(columns=range(24),
                                                                                               fill_value=0)
_hv = _hc.to_numpy()
_win = _hv + np.roll(_hv, 1, axis=1) + np.roll(_hv, -1, axis=1)
_hs = pd.DataFrame({"hour_share": _win.max(axis=1) / _hv.sum(axis=1), "hour": _win.argmax(axis=1)}, index=_hc.index)
_daily = _dc.set_index(["topic_id", "country_code"]).join(_hs)
_daily = _daily[_daily.hour_share >= 0.6].reset_index()
# weekly: same local weekday on most active days, 8+ weeks, active in 40%+ of the weeks of its span
_pd["wd"] = _pd.date.dt.dayofweek
_pd["wk"] = _pd.date.dt.to_period("W")
_wk = _pd.groupby(["topic_id", "country_code"]).agg(weeks=("wk", "nunique"), n_days=("ldate", "size"))
_wdm = _pd.groupby(["topic_id", "country_code", "wd"]).size()
_wk["wd_share"] = _wdm.groupby(level=[0, 1]).max() / _wk.n_days
_wk["wd"] = _wdm.groupby(level=[0, 1]).idxmax().map(lambda x: x[2])
_wk = _wk.join(_pc.set_index(["topic_id", "country_code"])[["span"]])
_wk = _wk[(_wk.weeks >= 8) & (_wk.wd_share >= 0.7) & (_wk.weeks / (_wk.span / 7).clip(lower=1) >= 0.25)].reset_index()
# yearly: same local date (+-1 day) in both years, for topic-countries active on at most 30 days
_few = _pc[_pc.n_days <= 10][["topic_id", "country_code"]]
_yd = _pd.merge(_few, on=["topic_id", "country_code"])
_yd["md"] = _yd.date.dt.dayofyear
_yd["yr"] = _yd.date.dt.year
_y25 = _yd[_yd.yr == 2025]
_yo = _yd[_yd.yr != 2025]
_ym = _y25.merge(_yo, on=["topic_id", "country_code"], suffixes=("", "_o"))
_ym = _ym[(_ym.md - _ym.md_o).abs() <= 1]
_yearly = _ym.groupby(["topic_id", "country_code"]).agg(ldate=("ldate", "first"), ldate_o=("ldate_o", "first")).reset_index()
# the step-4 sport check (Wikidata, sport sites, competition names, related searches) on the scan's candidates:
# athletes and tournaments outside the wave candidates have no is_athlete flag
from sport import sport_fix  # noqa: E402
_scan_ids = set(_daily.topic_id) | set(_wk.topic_id) | set(_yearly.topic_id)
_sf = sport_fix(_scan_ids, meta)
_scan_sport = set(_sf.topic_id[_sf.sport_fix])
print(f"  cycle scan: {len(_scan_sport):,} of {len(_scan_ids):,} candidate topics dropped by the sport check", flush=True)
_daily = _daily[~_daily.topic_id.isin(_scan_sport)]
_wk = _wk[~_wk.topic_id.isin(_scan_sport)]
_yearly = _yearly[~_yearly.topic_id.isin(_scan_sport)]
_WD = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _cyc_top(d, by, ex, k=30):
    agg_ = d.groupby("topic_id").agg(countries=("country_code", "nunique"), **{by: (by, "sum")})
    out = []
    for tid, a_ in agg_.sort_values(["countries", by], ascending=False).head(k).iterrows():
        e_ = d[d.topic_id == tid].sort_values(by, ascending=False).iloc[0]
        out.append({"topic_id": tid, "name": name.get(tid), "countries": int(a_.countries), by: int(a_[by]),
                    "example": ex(e_), "is_ritual_topic": tid in RIT_IDS})
    return out


cycle_scan = {
    "rules": {"topics": "non-sport topics: not the topic sport rule, not athletes, not topics whose moments are "
                        "mostly sport, and not flagged by the step-4 sport check (sport.sport_fix) on the candidates",
              "daily": "per topic and country (national feed, local dates and hours): 50+ active days, and 60%+ of "
                       "them start within the same local hour +-1",
              "weekly": "8+ active weeks, 70%+ of its active days on one local weekday, active in 25%+ of the weeks "
                        "of its span",
              "yearly": "a topic-country with at most 10 active days that trended on the same local date (+-1 day) "
                        "in 2025 and in 2024 or 2026 (the archive overlaps itself from 27 Nov to 17 May)",
              "ranking": "topics by countries that meet the rule, then by days / weeks"},
    "daily": _cyc_top(_daily, "n_days", lambda e: f"{e.country_code}: {int(e.n_days)} days, around {int(e.hour):02d}:00 "
                                                  f"local ({e.hour_share:.0%} of days)"),
    "weekly": _cyc_top(_wk, "weeks", lambda e: f"{e.country_code}: {int(e.weeks)} weeks, {_WD[int(e.wd)]} "
                                               f"({e.wd_share:.0%} of days)"),
    "yearly": _cyc_top(_yearly.assign(pairs=1), "pairs", lambda e: f"{e.country_code}: {e.ldate_o} and {e.ldate}"),
    "counts": {"daily_topic_countries": int(len(_daily)), "daily_topics": int(_daily.topic_id.nunique()),
               "weekly_topic_countries": int(len(_wk)), "weekly_topics": int(_wk.topic_id.nunique()),
               "yearly_topic_countries": int(len(_yearly)), "yearly_topics": int(_yearly.topic_id.nunique())}}
print(f"  cycle scan: {cycle_scan['counts']}", flush=True)

# compact rows, split into files under 1 MB: rituals_review/ritual_topics_N.json and rituals_review/holidays.json
RIT_FIELDS = ["topic_id", "name", "rule", "phrasings", "countries", "trends", "peak_day", "peak_countries",
              "active_local_days", "proposed_cycle", "sport_like"]
_rit_rows = [[x[f] for f in RIT_FIELDS] for x in rit_topics]
RIT_CHUNK = 3000
_rit_files = []
for i_ in range(0, len(_rit_rows), RIT_CHUNK):
    rel_ = f"rituals_review/ritual_topics_{i_ // RIT_CHUNK + 1}.json"
    write(rel_, {"fields": RIT_FIELDS, "rows": _rit_rows[i_:i_ + RIT_CHUNK]})
    _rit_files.append(rel_)
HOL_FIELDS = ["topic_id", "name", "phrasings", "countries", "trends", "peak_day"]
write("rituals_review/holidays.json", {
    "fields": HOL_FIELDS, "removed_fields": HOL_FIELDS + ["reason"],
    "holidays": {k_: {"rule": v_["rule"], "rows": [[x[f] for f in HOL_FIELDS] for x in v_["topics"]],
                      "removed": [[x[f] for f in HOL_FIELDS + ["reason"]] for x in v_["removed"]]}
                 for k_, v_ in holidays.items()}})
_rv = WORK / "rituals_validation.json"
rituals_score = load_json(_rv) if _rv.exists() else None
write("rituals_review.json", {
    "note": "Rituals validation round. ritual_topics (in ritual_topic_files) = every topic of the ritual kind (not "
            "hidden; 'is it down' topics are with Shocks), most trends first; proposed_cycle is a rule on the topic's "
            "local dates: yearly (holiday type "
            "with half its trends within 10 days of the peak date, or 80%+ within 10 days and at most 60 active "
            "days), daily (active on 30%+ of the days of a 60+ day span: Trending Now flags surges, so even daily "
            "rituals miss most days), weekly (6+ weeks, 50%+ of trends on one weekday), else unclear; too few "
            "trends = under 5. Holidays are the clean groups (round 33): full topic lists and removed topics with "
            "the reason are in rituals_review/holidays.json; chart series are in rituals.json.",
    "rule": RIT_RULE, "n_ritual_topics": len(rit_topics), "proposed_cycles": _cyc,
    "ritual_topic_files": _rit_files, "ritual_topics_top100": rit_topics[:100],
    "weather_clock": weather_clock, "scrape_check": scrape_check, "weather_topics": weather_topics,
    "holiday_rules": {"order": "Wikidata place (has coordinates, not human) > Claude type place > Wikidata human > "
                               "Claude type person > holiday word used as a name > another day sharing the word; a "
                               "holiday phrase next to the word (Pere Noel, veglia pasquale, San Valentin) keeps the "
                               "topic. Valentine's Day: Chinese 情人節 / 七夕 topics kept only if their widest day is "
                               "within 7 days of 14 February.",
                      "dates": HOLIDAY_DATES, "window_days": [-HOL_BEFORE, HOL_AFTER]},
    "holiday_label_score": rituals_score,
    "holidays": {k_: {kk: vv for kk, vv in v_.items() if kk not in ("topics", "removed")}
                 | {"top10_topics": v_["topics"][:10], "removed_top20": v_["removed"][:20]}
                 for k_, v_ in holidays.items()},
    "odd_peaks": odd_peaks,
    "holiday_topics_file": "rituals_review/holidays.json",
    "cycle_scan": cycle_scan})
# rituals.json: chart data (weather clock, holiday windows)
_pk_c = []
for c, v in per_c.items():
    d_ = w[w.country_code == c]
    tdy, tmw = d_[~d_.tomorrow], d_[d_.tomorrow]
    _pk_c.append({"country": c, "country_name": v["country_name"], "trends": v["trends"], "peak_hour": v["peak_hour"],
                  "today_peak_hour": int(pd.Series(hours(tdy)).idxmax()) if len(tdy) >= 20 else None,
                  "tomorrow_peak_hour": int(pd.Series(hours(tmw)).idxmax()) if len(tmw) >= 20 else None,
                  "time_zone_source": v["time_zone_source"]})
_pk_c.sort(key=lambda x: -x["trends"])
rituals = {
    "note": "Chart data for Rituals. weather_clock: weather-category trends by local hour of their start (US, CA and RU "
            "regional feeds in each region's zone; every other country one zone), as shares of all trends; 'tomorrow' "
            "= phrasings with tomorrow / mañana / amanhã / demain / morgen / ... ; 'today' = every other weather "
            "phrasing. Per-country today / tomorrow peaks need 20+ trends. holidays: clean groups (round 33), "
            "countries per UTC day from 10 days before to 5 days after each holiday date, [offset, day, countries]; "
            "countries is null on days outside the archive (2024-11-27 to 2026-05-17).",
    "weather_clock": {"share_by_local_hour": _share(w), "today_share_by_local_hour": _share(_wt),
                      "tomorrow_share_by_local_hour": _share(w[w.tomorrow]),
                      "trends": int(len(w)), "today_trends": int(len(_wt)), "tomorrow_trends": int(w.tomorrow.sum()),
                      "peak_local_hour_per_country": _pk_c,
                      "countries_per_peak_hour": weather_clock["countries_per_peak_hour"]},
    "weather_days": weather_days,
    "holidays": hol_chart, "holiday_dates": HOLIDAY_DATES}
write("rituals.json", rituals)
# weather_day.json: countries per local hour for every local day, and the usual day (same rows and zones as the
# weather clock: national feeds in one zone, US/CA/RU regional feeds in each region's zone)
_wdn = tv[tv.topic_id.isin(weather_ids) & ~tv.country_code.isin(REG)]
_wdn = pd.DataFrame({"country_code": _wdn.country_code.values, "ld": _wdn.local_time.dt.strftime("%Y-%m-%d").values,
                     "lh": _wdn.local_time.dt.hour.values, "query_raw": _wdn.query_raw.values,
                     "uh": _wdn.start_time_utc.dt.hour.values})
rg["ld"] = ""
for z, idx in zone.groupby(zone).groups.items():
    rg.loc[idx, "ld"] = rg.loc[idx, "start_time_utc"].dt.tz_convert(z).dt.strftime("%Y-%m-%d").values
rg["uh"] = rg.start_time_utc.dt.hour
_wd = pd.concat([_wdn, rg[["country_code", "ld", "lh", "query_raw", "uh"]]], ignore_index=True)
# UTC offset of the trend's start, in hours (local hour - UTC hour, wrapped); UTC+1 = offset 1
_wd["off"] = ((_wd.lh - _wd.uh + 12) % 24) - 12
_wd["tomorrow"] = _wd.query_raw.str.lower().str.contains(TOMORROW_RE, regex=True, na=False)
_wd_days = pd.date_range(pd.Timestamp(all_days[0]) - pd.Timedelta(days=1), pd.Timestamp(all_days[-1]) + pd.Timedelta(days=1),
                         freq="D").strftime("%Y-%m-%d")
_gs, _in = set(gap_days), set(all_days)
_day_flag = {}
for d_ in _wd_days:
    nb = [(pd.Timestamp(d_) + pd.Timedelta(days=k)).strftime("%Y-%m-%d") for k in (-1, 1)]
    if d_ not in _in or d_ in _gs:
        _day_flag[d_] = "gap" if d_ in _gs else "outside archive"
    elif any(x in _gs or x not in _in for x in nb):
        _day_flag[d_] = "next to a gap or archive edge"
    else:
        _day_flag[d_] = None


def _wd_grid(d):
    g = d.groupby(["ld", "lh"]).country_code.nunique().unstack(fill_value=0)
    return g.reindex(index=_wd_days, columns=range(24), fill_value=0).astype(int)


_wdg = {"today": _wd_grid(_wd[~_wd.tomorrow]), "tomorrow": _wd_grid(_wd[_wd.tomorrow])}
_wd_full = [d_ for d_ in _wd_days if _day_flag[d_] is None]
_usual = {}
for k_, g_ in _wdg.items():
    f_ = g_.loc[_wd_full]
    av, md = f_.mean(), f_.median()
    _usual[k_] = {"mean_countries_by_local_hour": [round(float(x), 2) for x in av],
                  "median_countries_by_local_hour": [float(x) for x in md],
                  "peak_hour": int(av.idxmax()), "peak_mean_countries": round(float(av.max()), 2),
                  "peak_median_countries": float(md[av.idxmax()]),
                  "median_peak_hour": int(md.idxmax()), "median_peak_countries": float(md.max())}
# robustness (round 38): the 'tomorrow' usual day (a) without trends starting 19:00-19:59 UTC (the collection bump,
# CHECKS C4) and (b) without trends from countries at UTC+1 that day
_wtm = _wd[_wd.tomorrow]


def _usual_of(d):
    f_ = _wd_grid(d).loc[_wd_full]
    av, md = f_.mean(), f_.median()
    return {"mean_countries_by_local_hour": [round(float(x), 2) for x in av],
            "peak_hour": int(av.idxmax()), "peak_mean_countries": round(float(av.max()), 2),
            "peak_median_countries": float(md[av.idxmax()]), "hour_20_mean_countries": round(float(av[20]), 2),
            "hour_20_median_countries": float(md[20]), "trends": int(len(d))}


_tm_rob = {"all": _usual_of(_wtm), "without_19utc": _usual_of(_wtm[_wtm.uh != 19]),
           "without_utc_plus_1": _usual_of(_wtm[_wtm.off != 1]),
           "without_both": _usual_of(_wtm[(_wtm.uh != 19) & (_wtm.off != 1)]),
           "note": "'tomorrow' usual day over the full-coverage days: all trends; without trends starting 19:00-19:59 "
                   "UTC; without trends at UTC+1 (offset of that trend's start); without both."}
weather_day = {
    "note": "Weather category, 'today' / 'tomorrow' split as rituals.json (tomorrow = phrasings with a tomorrow word). "
            "Each trend sits on the local day and local hour of its start: national feeds in one zone per country "
            "(data/interim/country_timezones.json), US, CA and RU from their regional feeds, each in its region's "
            "zone (REGION_TZ); a country counts once per hour if any of its zones has a trend then. day = the local "
            "calendar date. by_day rows: [day, flag, today counts by local hour 0-23, tomorrow counts]. A local day "
            "overlaps the UTC day before or after it, so flag = 'gap' (the date is a collection gap day), 'next to a "
            "gap or archive edge' (the day before or after is a gap day or outside the archive) or 'outside archive'; "
            "null = full coverage. usual_day = mean and median over the full-coverage days.",
    "full_coverage_days": len(_wd_full), "days": len(_wd_days),
    "flag_counts": pd.Series([v for v in _day_flag.values() if v]).value_counts().to_dict(),
    "usual_day": _usual, "tomorrow_robustness": _tm_rob,
    "by_day": [[d_, _day_flag[d_], _wdg["today"].loc[d_].tolist(), _wdg["tomorrow"].loc[d_].tolist()] for d_ in _wd_days]}
write("weather_day.json", weather_day)
num("Rituals", "Weather usual day 'tomorrow', robustness: 20:00 mean countries all / without 19:00 UTC starts / "
               "without UTC+1 / without both (peak hour of each)",
    " / ".join(f"{v['hour_20_mean_countries']} ({v['peak_hour']}:00)" for k, v in _tm_rob.items() if k != "note"),
    "weather_day.json", "tomorrow_robustness")
for k_, u_ in _usual.items():
    num("Rituals", f"Weather usual day ('{k_}'): peak local hour / mean countries starting a trend then (median) / "
                   f"full-coverage days", f"{u_['peak_hour']}:00 / {u_['peak_mean_countries']} "
                   f"({u_['peak_median_countries']:g}) / {len(_wd_full)}", "weather_day.json", f"usual_day.{k_}")
num("Rituals", "Ritual topics (not hidden) / proposed cycle daily / weekly / yearly / unclear / too few trends",
    f"{len(rit_topics):,} / {_cyc.get('daily', 0):,} / {_cyc.get('weekly', 0):,} / {_cyc.get('yearly', 0):,} / "
    f"{_cyc.get('unclear (sporadic)', 0):,} / {_cyc.get('too few trends', 0):,}", "rituals_review.json", "ritual_topics")
_ts, _tm = pd.Series(weather_clock["today_share_by_local_hour"]), pd.Series(weather_clock["tomorrow_share_by_local_hour"])
_tr = pd.Series(weather_clock["robustness_without_multizone"]["today_share_by_local_hour"])
_tmr = pd.Series(weather_clock["robustness_without_multizone"]["tomorrow_share_by_local_hour"])
num("Rituals", "Ritual topics that look like sport (topic sport, athlete, or mostly sport moments)",
    f"{sum(x['sport_like'] for x in rit_topics):,} of {len(rit_topics):,} (of those with 5+ trends: "
    f"{sum(x['sport_like'] for x in rit_topics if x['trends'] >= 5):,} of {sum(x['trends'] >= 5 for x in rit_topics):,})",
    "rituals_review.json", "ritual_topics[].sport_like")
num("Rituals", "Weather clock: busiest local hour, 'today' / 'tomorrow' phrasings",
    f"{_ts.idxmax()}:00 ({_ts.max():.1%}) / {_tm.idxmax()}:00 ({_tm.max():.1%})", "rituals_review.json", "weather_clock")
num("Rituals", f"Weather clock without multi-zone countries ({len(_mz)} left out): busiest hour today / tomorrow",
    f"{_tr.idxmax()}:00 / {_tmr.idxmax()}:00", "rituals_review.json", "weather_clock.robustness_without_multizone")
num("Rituals", "Weather clock: 'today' share 05:00-09:59 local / 'tomorrow' share 18:00-23:59 local",
    f"{_ts[5:10].sum():.1%} / {_tm[18:24].sum():.1%}", "rituals_review.json", "weather_clock")
_scr_s = pd.Series(scrape_check["latest_start_hour_per_collection_day"])
num("Rituals", "Scrape proxy: UTC hour of the latest trend start per collection day (most common, share of days)",
    f"{_scr_s.idxmax()}:00 ({_scr_s.max() / _scr_s.sum():.0%} of {_scr_s.sum()} days)", "rituals_review.json",
    "scrape_check")
num("Rituals", "Trends starting 19:00-19:59 UTC: share lasting 20 h+ vs other hours (median)",
    f"{scrape_check['share_20h_plus_by_utc_hour'][19]:.1%} vs "
    f"{float(np.median([v for h_, v in enumerate(scrape_check['share_20h_plus_by_utc_hour']) if h_ != 19])):.1%}",
    "rituals_review.json", "scrape_check")
_pkh = pd.Series(weather_clock["countries_per_peak_hour"])
num("Rituals", "Weather: countries by peak local hour, most common hours",
    ", ".join(f"{h_}:00 {v_}" for h_, v_ in _pkh.sort_values(ascending=False).head(4).items()),
    "rituals_review.json", "weather_clock.countries_per_peak_hour")
for hname, v_ in holidays.items():
    rm_ = v_["removed_by_reason"]
    nm_ = sum(n_ for r_, n_ in rm_.items() if r_ in ("Wikidata place", "Claude type place", "Wikidata human",
                                                    "Claude type person", "holiday word used as a name"))
    num("Rituals", f"Holiday {hname}: topics matched / removed as names (people, places) / removed otherwise / clean",
        f"{v_['n_matched']} / {nm_} / {sum(rm_.values()) - nm_} / {v_['n_topics']}", "rituals_review.json",
        f"holidays.{hname}.removed_by_reason")
    oc = "; ".join(f"{o_['series']} {o_['year']}: {o_['peak_day']} ({o_['peak_countries']})"
                   for o_ in v_["occurrences"] if o_["days_in_archive"])
    bb = "; ".join(f"{k__} {b_['countries']}" for k__, b_ in v_["countries_in_both_years"].items()) or "-"
    num("Rituals", f"Holiday {hname} (clean): peak day (countries) per year, in the window -10 to +5 days / "
                   "countries in both years", f"{oc} / {bb}", "rituals.json", f"holidays.{hname}")
for o_ in odd_peaks:
    num("Rituals", f"Odd peak {o_['holiday']} {o_['day']}: countries with the round 32 group / clean group",
        f"{o_['countries_round32']} / {o_['countries_clean']}", "rituals_review.json", "odd_peaks")
if rituals_score:
    num("Rituals", "Holiday sample (hand labels): about the holiday, of all",
        f"{rituals_score['about']} of {rituals_score['n']} ({rituals_score['precision']:.0%})",
        "rituals_review.json", "holiday_label_score")
    num("Rituals", "Holiday sample: unrelated topics removed by the clean rule / holiday topics wrongly removed",
        f"{rituals_score['unrelated_removed']} of {rituals_score['unrelated']} / {rituals_score['about_removed']} of "
        f"{rituals_score['about']}", "rituals_review.json", "holiday_label_score")
_cc_ = cycle_scan["counts"]
num("Rituals", "Cycle scan: topics with a daily / weekly / yearly cycle in at least one country",
    f"{_cc_['daily_topics']:,} / {_cc_['weekly_topics']:,} / {_cc_['yearly_topics']:,}", "rituals_review.json",
    "cycle_scan.counts")
for k_ in ("daily", "weekly", "yearly"):
    num("Rituals", f"Cycle scan, top 5 {k_}", "; ".join(f"{x['name']} ({x['countries']})" for x in cycle_scan[k_][:5]),
        "rituals_review.json", f"cycle_scan.{k_}")

# ------------------------------------------------------------------ 6c two clocks (Step 9 round 35)
print("two clocks ...", flush=True)
# Rituals keep the local clock, shocks keep the UTC clock. Per country: the 10-minute step with the most trends of
# the case's topics (ties: earliest) in its national feed; local time = that UTC time in the country's zone
# (data/interim/country_timezones.json, DST-aware on that day). US, CA and RU have one national feed but several
# zones: the national peak uses the zone in country_timezones.json (US America/Chicago, CA America/Toronto,
# RU Europe/Moscow), and `zones` adds each zone's peak from the regional feeds (REGION_TZ), in that zone's own clock.
TC_MULTI = ("US", "CA", "RU")
_tc_reg = allrows[(allrows.level == "region") & allrows.country_code.isin(TC_MULTI)].copy()
_tc_reg["zone"] = [REGION_TZ.get(c, {}).get(z, cz[c]) for c, z in
                   zip(_tc_reg.country_code, _tc_reg.location.str.split("-").str[1])]


def _offset_h(ts, zone):
    return ts.tz_convert(zone).utcoffset().total_seconds() / 3600


def _loc(ts, zone):
    return ts.tz_convert(zone).strftime("%Y-%m-%dT%H:%M")


def _peak_step(rows):
    """(UTC timestamp of the 10-minute step with most trends, ties earliest; trends in it)."""
    s = rows.start_time_utc.dt.floor("10min").value_counts()
    s = s[s == s.max()].sort_index()
    _peak_step.tied = len(s) > 1
    return s.index[0], int(s.iloc[0])


def _top_phr(rows):
    return rows.query_raw.astype(str).str.strip().str.lower().value_counts().index[0]


def _row(code, label, zone, ts, rows, step_trends, ref_utc, ref_local_fn):
    off = _offset_h(ts, zone)
    loc = ts.tz_convert(zone)
    return {"country": code, "country_name": label, "zone": zone, "utc": iso(ts), "utc_offset_h": off,
            "local": _loc(ts, zone), "trends": int(len(rows)), "trends_in_peak_step": step_trends,
            "top_phrasing": _top_phr(rows),
            "utc_h_from_ref": round((ts - ref_utc).total_seconds() / 3600, 3),
            "local_h_from_ref": round((loc.tz_localize(None) - ref_local_fn(loc)).total_seconds() / 3600, 3)}


def _iqr(v):
    v = np.asarray([x for x in v if x is not None], float)
    if not len(v):
        return None
    q1, md, q3 = np.percentile(v, [25, 50, 75])
    return {"n": int(len(v)), "q1": round(q1, 2), "median": round(md, 2), "q3": round(q3, 2), "iqr_h": round(q3 - q1, 2),
            "p10_p90_h": round(float(np.percentile(v, 90) - np.percentile(v, 10)), 2),
            "within_1h_of_median": int((np.abs(v - md) <= 1).sum())}


def _circ(h):
    """Hours of day -> unwrapped around their circular mean, so a spread across midnight is not 24 h wide."""
    h = np.asarray(h, float)
    ang = h / 24 * 2 * np.pi
    c = (np.arctan2(np.sin(ang).mean(), np.cos(ang).mean()) / (2 * np.pi) * 24) % 24
    return ((h - c + 12) % 24) - 12 + c


def tc_event(ids, lo, hi, ref_utc, ref_local_fn, mode="peak"):
    """mode peak: busiest 10-minute step; mode first: first trend (as opening.json)."""
    r = t[t.topic_id.isin(ids) & (t.start_time_utc >= lo) & (t.start_time_utc < hi)]
    out = []
    for c, g in r.groupby("country_code"):
        ts, k = _peak_step(g) if mode == "peak" else (g.start_time_utc.min(), int((g.start_time_utc == g.start_time_utc.min()).sum()))
        it = _row(c, cname.get(c), cz[c], ts, g, k, ref_utc, ref_local_fn)
        if mode == "peak":
            it["peak_tied"] = bool(_peak_step.tied)
        if c in TC_MULTI:
            rr = _tc_reg[(_tc_reg.country_code == c) & _tc_reg.topic_id.isin(ids) & (_tc_reg.start_time_utc >= lo)
                         & (_tc_reg.start_time_utc < hi)]
            zs = []
            for z, gz in rr.groupby("zone"):
                tz_, kz = _peak_step(gz) if mode == "peak" else (gz.start_time_utc.min(), 1)
                zs.append(_row(c, f"{cname.get(c)} ({z})", z, tz_, gz, kz, ref_utc, ref_local_fn) |
                          {"regional_trends": int(len(gz)), "regions": int(gz.location.nunique())})
            it["zones"] = sorted(zs, key=lambda x: x["utc_offset_h"], reverse=True)
            it["multi_zone_note"] = "national feed; local time in " + cz[c] + "; see zones for each zone's own clock"
        out.append(it)
    out.sort(key=lambda x: x["utc"])
    return out


def tc_spread(rows, circular=False, near_ref=False):
    u = [x["utc_h_from_ref"] for x in rows]
    lcl = [x["local_h_from_ref"] for x in rows]
    if circular:
        u, lcl = _circ(u), _circ(lcl)
    out = {"utc": _iqr(u), "local": _iqr(lcl)}
    if near_ref:      # holidays: countries peaking near the reference (midnight), on each clock
        out["near_reference"] = {f"within_{h}h": {"utc": int(sum(abs(v) <= h for v in u)),
                                                  "local": int(sum(abs(v) <= h for v in lcl))} for h in (1, 3)}
        clear = [x for x in rows if x.get("trends_in_peak_step", 0) >= 2 and not x.get("peak_tied")]
        out["clear_peak"] = {"rule": "countries whose peak step has 2+ trends and no tie",
                             "utc": _iqr([x["utc_h_from_ref"] for x in clear]),
                             "local": _iqr([x["local_h_from_ref"] for x in clear])}
        if clear:
            out["clear_peak"]["near_reference_within_1h"] = {
                "utc": int(sum(abs(x["utc_h_from_ref"]) <= 1 for x in clear)),
                "local": int(sum(abs(x["local_h_from_ref"]) <= 1 for x in clear))}
    return out


two_clocks = {"note": "Two clocks: Rituals (local clock) vs Shocks (UTC clock). Each case lists every country with "
                      "trends in the window: utc = its peak 10-minute step (most trends of the case's topics; ties: "
                      "earliest) or, for Pope Francis, its first trend (as opening.json); utc_offset_h that day; local "
                      "= the same instant in the country's zone. utc_h_from_ref / local_h_from_ref = hours from the "
                      "case's reference (UTC, and the local wall clock) used for the spreads. Spread = quartiles and "
                      "IQR in hours over countries (national feeds; US/CA/RU in their country_timezones.json zone; "
                      "their zones lists are extra and not in the spreads). Hours of day (weather, Pope local "
                      "clock) are unwrapped around their circular mean.",
              "multi_zone_rule": "US, CA, RU: national feed, local time in " +
                                 ", ".join(f"{c} {cz[c]}" for c in TC_MULTI) + "; zones[] = each zone's peak from the "
                                 "regional feeds (REGION_TZ), in its own clock",
              "cases": {}}
for yr in (2024, 2025):
    lo = pd.Timestamp(f"{yr}-12-30 12:00", tz="UTC")
    rows = tc_event(hol_clean["New Year"], lo, lo + pd.Timedelta(hours=48), pd.Timestamp(f"{yr + 1}-01-01", tz="UTC"),
                    lambda loc, y=yr: pd.Timestamp(f"{y + 1}-01-01"))
    two_clocks["cases"][f"new_years_eve_{yr}_{yr + 1}"] = {
        "group": "clean New Year group (Rituals round 33)", "window_utc": [iso(lo), iso(lo + pd.Timedelta(hours=48))],
        "reference": f"{yr + 1}-01-01 00:00 (UTC for utc, local wall clock for local)", "measure": "peak",
        "countries": rows, "spread": tc_spread(rows, near_ref=True)}
    lo = pd.Timestamp(f"{yr}-12-23 12:00", tz="UTC")
    hi = pd.Timestamp(f"{yr}-12-26 00:00", tz="UTC")
    rows = tc_event(hol_clean["Christmas"], lo, hi, pd.Timestamp(f"{yr}-12-25", tz="UTC"),
                    lambda loc, y=yr: pd.Timestamp(f"{y}-12-25"))
    two_clocks["cases"][f"christmas_eve_{yr}"] = {
        "group": "clean Christmas group (Rituals round 33)", "window_utc": [iso(lo), iso(hi)],
        "reference": f"{yr}-12-25 00:00 (UTC / local wall clock)", "measure": "peak",
        "countries": rows, "spread": tc_spread(rows, near_ref=True)}
# weather "today": typical peak over all days, local hour and UTC hour separately (US/CA/RU regional, own zones,
# as the weather clock)
_wn = tv[tv.topic_id.isin(weather_ids) & ~tv.country_code.isin(REG)][["country_code", "start_time_utc", "local_time",
                                                                        "query_raw"]].copy()
_wn["lh"] = _wn.local_time.dt.hour
_wr = rg[["country_code", "start_time_utc", "lh", "query_raw"]].copy()
_ww = pd.concat([_wn[["country_code", "start_time_utc", "lh", "query_raw"]], _wr])
_ww = _ww[~_ww.query_raw.str.lower().str.contains(TOMORROW_RE, regex=True, na=False)]
_ww["uh"] = _ww.start_time_utc.dt.hour
_ww["off"] = ((_ww.lh - _ww.uh + 12) % 24) - 12
wx_rows = []
for c, g in _ww.groupby("country_code"):
    if len(g) < 20:
        continue
    lh_ = g.lh.value_counts().sort_index()
    uh_ = g.uh.value_counts().sort_index()
    wx_rows.append({"country": c, "country_name": cname.get(c), "trends": int(len(g)),
                    "local_peak_hour": int(lh_.idxmax()), "utc_peak_hour": int(uh_.idxmax()),
                    "typical_utc_offset_h": float(g["off"].median()), "top_phrasing": _top_phr(g),
                    "time_zone_source": "regional feeds, own zones" if c in REG else "national feed, one zone",
                    "utc_h_from_ref": int(uh_.idxmax()), "local_h_from_ref": int(lh_.idxmax())})
wx_rows.sort(key=lambda x: -x["trends"])
two_clocks["cases"]["weather_today"] = {
    "group": "weather category, 'today' phrasings (every weather phrasing without a tomorrow word), all days",
    "measure": "typical peak: the local hour with most trends, and separately the UTC hour with most trends "
               "(countries with 20+ trends; US/CA/RU from their regional feeds, each in its own zone)",
    "reference": "hour of day", "countries": wx_rows, "spread": tc_spread(wx_rows, circular=True)}
# Pope Francis: each country's first trend, same topics and window as opening.json
_pope_ids, _pope_lo, _pope_hi = POPE_IDS, POPE_LO, POPE_HI
rows = tc_event(_pope_ids, _pope_lo, _pope_hi, pd.Timestamp("2025-04-21", tz="UTC"),
                lambda loc: pd.Timestamp("2025-04-21"), mode="first")
_ploc = [int(x["local"][11:13]) + int(x["local"][14:16]) / 60 for x in rows]
for x, v in zip(rows, _ploc):
    x["local_clock_h"] = round(v, 3)
_sp = tc_spread(rows)
_sp["local_clock_hour"] = _iqr(_circ(_ploc))
two_clocks["cases"]["pope_francis_2025_04_21"] = {
    "group": "opening.json topics and window", "window_utc": [iso(_pope_lo), iso(_pope_hi)], "measure": "first trend",
    "reference": "2025-04-21 00:00 (UTC / local wall clock); local_clock_hour = local hour of day, unwrapped",
    "countries": rows, "spread": _sp}
write("two_clocks.json", two_clocks)
for k_, v_ in two_clocks["cases"].items():
    su, sl = v_["spread"]["utc"], v_["spread"].get("local_clock_hour") or v_["spread"]["local"]
    num("Rituals", f"Two clocks, {k_}: countries / IQR of peak times UTC vs local (hours) / within 1 h of the median "
                   f"UTC vs local", f"{su['n']} / {su['iqr_h']} vs {sl['iqr_h']} / {su['within_1h_of_median']} vs "
                   f"{sl['within_1h_of_median']}", "two_clocks.json", f"cases.{k_}.spread")
    if "near_reference" in v_["spread"]:
        nr, cp = v_["spread"]["near_reference"], v_["spread"]["clear_peak"]
        num("Rituals", f"Two clocks, {k_}: countries peaking within 1 h / 3 h of midnight, UTC vs local; clear peaks "
                       f"({cp['utc']['n'] if cp['utc'] else 0}): IQR UTC vs local, within 1 h of midnight UTC vs local",
            f"{nr['within_1h']['utc']} vs {nr['within_1h']['local']} / {nr['within_3h']['utc']} vs "
            f"{nr['within_3h']['local']}; {cp['utc']['iqr_h'] if cp['utc'] else '-'} vs "
            f"{cp['local']['iqr_h'] if cp['local'] else '-'}, {cp.get('near_reference_within_1h', {}).get('utc', '-')} vs "
            f"{cp.get('near_reference_within_1h', {}).get('local', '-')}", "two_clocks.json",
            f"cases.{k_}.spread.near_reference")

# ------------------------------------------------------------------ 7 time machine
print("time machine ...", flush=True)
dur = pd.to_timedelta(tv.duration_minutes.fillna(0).clip(upper=24 * 60), unit="m")
end = tv.end_time_utc.fillna(tv.start_time_utc + dur)
end = end.where(end > tv.start_time_utc, tv.start_time_utc + pd.Timedelta(minutes=1))
h0 = tv.start_time_utc.dt.floor("h").astype("int64") // 3_600_000_000_000
h1 = (end - pd.Timedelta(microseconds=1)).dt.floor("h").astype("int64") // 3_600_000_000_000
n = np.clip(h1 - h0 + 1, 1, 25).values
# one entry per (topic, moment kind): the same topic can show in a month with different kinds
tid_codes, tid_uni = pd.factorize(tv.topic_id + "|" + tv.kind)
cc_codes, cc_uni = pd.factorize(tv.country_code, sort=True)
idx = np.repeat(np.arange(len(tv)), n)
offs = np.arange(len(idx)) - np.repeat(np.cumsum(n) - n, n)
e = pd.DataFrame({"hour": h0.values[idx] + offs, "cc": cc_codes[idx], "tid": tid_codes[idx],
                  "vol": tv.vol.values[idx], "start": tv.start_time_utc.astype("int64").values[idx]})
e = e.sort_values(["hour", "cc", "vol", "start"], ascending=[True, True, False, False]).drop_duplicates(["hour", "cc"])
e["month"] = pd.to_datetime(e.hour * 3_600_000_000_000, utc=True).dt.strftime("%Y-%m")
countries = list(cc_uni)
KINDS = MOMENT_KINDS
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
                "topics": [[tid_uni[x].rsplit("|", 1)[0], name.get(tid_uni[x].rsplit("|", 1)[0]),
                            KINDS.index(tid_uni[x].rsplit("|", 1)[1]), int(tid_uni[x].rsplit("|", 1)[0] in WAVE)]
                           for x in tids],
                "top": [[pos[d[(h, c)]] if (h, c) in d else -1 for c in range(len(countries))] for h in hi_],
                "note": "top[i][j] = index into topics of country j's top active trend in hour i (-1 = none); "
                        "topics = [topic_id, name, kind index into kinds, is_wave 0/1] (kind = the kind of the "
                        "moment the trend belongs to, so a topic can appear twice with different kinds; is_wave = "
                        "the topic is a wave topic, a flag, not a kind)"}
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
write("timemachine/peaks.json", {"note": "Global moments for the timeline (>= 15 countries within 60 min of the third). name is null when it equals topic_id; is_sport 0/1; kind = index into kinds (the moment's own kind); is_wave 0/1 = the topic is a wave topic.",
                                 "files": tm_files,
                                 "fields": ["date_utc", "topic_id", "name", "reach", "is_sport", "kind", "is_wave"], "kinds": KINDS,
                                 "peaks": [[iso(r.start_utc), r.topic_id, r.topic_name if r.topic_name != r.topic_id else None,
                                            int(r.reach), int(bool(r.is_sport)), KINDS.index(r.kind), int(r.topic_id in WAVE)]
                                           for r in peaks_.itertuples()]})
num("Time machine", "Global moments on the timeline", len(peaks_), "timemachine/peaks.json", "peaks")

# ------------------------------------------------------------------ 8 wrapped
# Country Wrapped, "your turn" round (Step 9 round 39): every card is rebuilt here on the current pipeline, aligned
# with the article. Step 5's cards give only the biggest day; everything else is computed from this step's data.
print("wrapped ...", flush=True)
from scipy import sparse  # noqa: E402
share = t.groupby(["country_code", "kind"]).size().unstack(fill_value=0)     # rows by their moment's kind
share = share.div(share.sum(1), axis=0).reindex(columns=KINDS, fill_value=0)
small_sh = (t.moment_reach < LOCAL_MAX_REACH).groupby(t.country_code).mean()   # reach, not a kind
W_CC = sorted(t.country_code.unique())
_med_day = ex.low_data_countries(t)
# local share (the Local chapter, local.json): share of the country's topics found in no other national feed
_lsh = pd.Series({d["country_code"]: d["single_country_topic_share"] for d in local["per_country"]})
_lrank = _lsh.rank(ascending=False, method="min").astype(int)
_lrank_full = _lsh[[c for c in _lsh.index if c not in LOW_DATA]].rank(ascending=False, method="min").astype(int)
# top uniquely local topics: one-country topics, without hidden and Wrapped-skip topics, by volume then trends
_tcw = t.groupby(["topic_id", "country_code"]).agg(vol=("vol", "sum"), n=("vol", "size")).reset_index()
_tcw = _tcw[_tcw.topic_id.isin(single) & ~_tcw.topic_id.isin(hidden | wrapped_skip)].sort_values(
    ["n", "vol"], ascending=False)        # by trends, then volume (volume alone picks one-off 1M draws)
_loc_top = {c: g.head(5) for c, g in _tcw.groupby("country_code")}
_rows_by_tid = {k_: g_ for k_, g_ in t[t.topic_id.isin(set(_tcw.groupby("country_code").head(5).topic_id))]
                .groupby("topic_id")}
# attention twin: Jaccard on the sets of topics each national feed had; second version without sports matches,
# clubs (category sports_match / team) and athletes (is_athlete)
_sport_t = set(meta.index[meta.category.isin(["sports_match", "team"]) | meta.is_athlete.astype(bool)])


def _twins(rows):
    pairs = rows[["country_code", "topic_id"]].drop_duplicates()
    ti_ = {x: i for i, x in enumerate(pairs.topic_id.unique())}
    ci_ = {c: i for i, c in enumerate(W_CC)}
    X_ = sparse.csr_matrix((np.ones(len(pairs)), (pairs.country_code.map(ci_), pairs.topic_id.map(ti_))),
                           shape=(len(W_CC), len(ti_)))
    inter = (X_ @ X_.T).toarray()
    sz = np.asarray(X_.sum(1)).ravel()
    jac_ = inter / np.maximum(sz[:, None] + sz[None, :] - inter, 1)
    np.fill_diagonal(jac_, -1)
    out_ = {}
    for c in W_CC:
        o_ = np.argsort(-jac_[ci_[c]])[:3]
        out_[c] = {"country_code": W_CC[o_[0]], "country_name": cname.get(W_CC[o_[0]]),
                   "jaccard": round(float(jac_[ci_[c], o_[0]]), 4),
                   "runners_up": [{"country_code": W_CC[j], "jaccard": round(float(jac_[ci_[c], j]), 4)} for j in o_[1:]]}
    return out_


TWIN_ALL = _twins(t)
TWIN_NOSPORT = _twins(t[~t.topic_id.isin(_sport_t)])
# shocks: the 60 chart shocks (event reach: main topic + accepted topics, start - 2 h to + 24 h, as shocks.json)
_chart_cc = {}
for x in chart_by_event:
    grp = {x["topic_id"]} | (EVENT_GROUPS or {}).get(x["moment_id"], set())
    em = EV.metrics(t, grp, pd.Timestamp(x["date_utc"].replace("Z", ""), tz="UTC"))
    _chart_cc[x["moment_id"]] = (x, set(em["first"].index))
# global moments (not hidden): joined, and among the first 3 countries (ties with the third included)
_gmw = m[m.is_global & ~m.topic_id.isin(hidden)]
_g_join, _g_first3 = {}, {}
for cs in _gmw.countries:
    cs = sorted(cs, key=lambda c_: c_["min_from_start"])
    third_ = cs[2]["min_from_start"] if len(cs) >= 3 else None
    for c_ in cs:
        _g_join[c_["country_code"]] = _g_join.get(c_["country_code"], 0) + 1
        if third_ is not None and c_["min_from_start"] <= third_:
            _g_first3[c_["country_code"]] = _g_first3.get(c_["country_code"], 0) + 1
# appointments: event units (appointments.json), countries trending any of the event's topics in its window
_ap_cc = {}
for u in units.itertuples():
    lo_, hi_ = (pd.Timestamp(v_) for v_ in u.window_utc)
    parts_ = [_rbt[x] for x in u.topics if x in _rbt]
    if not parts_:
        continue
    w_ = pd.concat(parts_)
    _ap_cc[u.event_id] = (u, set(w_[(w_.start_time_utc >= lo_) & (w_.start_time_utc < hi_)].country_code))
_ap_order = list(units.event_id)
# waves: the 18 verified wave stories (waves_chart.json); a country joins a story in a month at 15+ if it trended
# any of the story's topics that month
_wave_cc = []
for st_ in WAVE_CHART:
    r_ = wv[wv.topic_id.isin(st_["topic_ids"])]
    m15 = [mo for mo, n_ in zip(months, st_["countries_per_month"]) if n_ >= 15]
    per_ = r_[r_.month.isin(m15)].groupby("country_code").month.agg(lambda s_: sorted(set(s_)))
    _wave_cc.append((st_, m15, per_.to_dict()))
# rituals: weather hours from the weather clock (rituals.json), holidays from the clean groups (both years)
_wx_pk = {x["country"]: x for x in _pk_c}
_hol_both = {}
for hname, v_ in holidays.items():
    for series_, b_ in v_["countries_in_both_years"].items():
        for c in b_["country_codes"]:
            _hol_both.setdefault(c, []).append(series_)
_bd = {}
for p in sorted((EXPORT / "wrapped").glob("[A-Z][A-Z].json")):
    c5 = json.load(open(p))
    _bd[c5["country_code"]] = c5["busiest_day"]
index = []
WRAPPED_CARDS = {}
for c in W_CC:
    lt_ = _loc_top.get(c, pd.DataFrame(columns=["topic_id", "vol", "n"]))
    loc_items = [{"topic_id": r.topic_id, "name": name.get(r.topic_id), "type": meta["type"].get(r.topic_id),
                  "trends": int(r.n), "volume_sum": int(r.vol),
                  "top_phrasings": top_phrasings(_rows_by_tid[r.topic_id], 3)} for r in lt_.itertuples()]
    shocks_j = [{"moment_id": mid, "name": x["name"], "date_utc": x["date_utc"], "event_reach": x.get("event_reach")}
                for mid, (x, ccs) in _chart_cc.items() if c in ccs]
    ap_j = [eid for eid in _ap_order if eid in _ap_cc and c in _ap_cc[eid][1]][:3]
    waves_j = [{"story": st_["story"], "group": st_["group"], "months_15plus_joined": per_[c],
                "months_15plus": len(m15)} for st_, m15, per_ in _wave_cc if c in per_]
    wx_ = _wx_pk.get(c, {})
    bd = _bd.get(c)
    card = {"country_code": c, "country_name": cname.get(c), "low_data": c in LOW_DATA,
            "median_trends_per_day": round(float(_med_day.get(c, 0)), 1),
            "local_share": round(float(_lsh.get(c, 0.0)), 4),
            "local_share_rank": int(_lrank.get(c)), "local_share_rank_of": int(len(_lrank)),
            "local_share_rank_without_low_data": int(_lrank_full[c]) if c in _lrank_full.index else None,
            "local_share_rank_without_low_data_of": int(len(_lrank_full)),
            "uniquely_local_top5": loc_items,
            "shocks": {"chart_shocks_joined": shocks_j, "chart_shocks_joined_n": len(shocks_j),
                       "chart_shocks": len(_chart_cc),
                       "global_moments_joined": _g_join.get(c, 0), "global_moments": int(len(_gmw)),
                       "global_moments_among_first_3": _g_first3.get(c, 0)},
            "appointments": {"widest_3": [{"event_id": eid, "event": _ap_cc[eid][0].event,
                                           "category": _ap_cc[eid][0].category, "first_utc": _ap_cc[eid][0].first_utc,
                                           "event_reach": int(_ap_cc[eid][0].event_reach)} for eid in ap_j]},
            "waves": {"joined": waves_j, "joined_n": len(waves_j), "stories": len(_wave_cc)},
            "rituals": {"weather_today_hour": wx_.get("today_peak_hour"),
                        "weather_tomorrow_hour": wx_.get("tomorrow_peak_hour"),
                        "weather_trends": wx_.get("trends", 0),
                        "top_weather_phrasing": per_c.get(c, {}).get("top_phrasing"),
                        "time_zone_source": wx_.get("time_zone_source"),
                        "holidays_both_years": sorted(_hol_both.get(c, []))},
            "attention_twin": TWIN_ALL[c], "attention_twin_without_sport": TWIN_NOSPORT[c],
            "biggest_day": bd and {"date": bd["date"], "trends": bd["trends"],
                                   "top_topic": (bd["top_topics"] or [{}])[0].get("name")},
            "kind_shares": {k: round(float(share.loc[c, k]), 4) if c in share.index else 0.0 for k in KINDS},
            "small_moment_share": round(float(small_sh.get(c, 0.0)), 4)}
    WRAPPED_CARDS[c] = card
    write(f"wrapped/{c}.json", card)
    index.append({"country_code": c, "country_name": card["country_name"], "low_data": card["low_data"],
                  "local_share": card["local_share"], "local_share_rank": card["local_share_rank"],
                  "twin": TWIN_ALL[c]["country_code"], "twin_without_sport": TWIN_NOSPORT[c]["country_code"],
                  "weather_today_hour": card["rituals"]["weather_today_hour"],
                  "chart_shocks_joined": len(shocks_j), "waves_joined": len(waves_j)})
write("wrapped/index.json", {
    "note": "Country Wrapped cards (Step 9 round 39). local_share = share of the country's topics found in no other "
            "national feed (local.json), rank 1 = most local, also ranked without low_data countries. "
            "uniquely_local_top5 = its one-country topics by trends, then search volume, without hidden and Wrapped-skip topics. "
            "shocks = which of the 60 chart shocks (shocks.json chart_top60, event reach) it joined, and how many "
            "global moments (not hidden) it joined / was among the first 3 countries in (ties with the third "
            "included). appointments.widest_3 = its 3 widest appointment events (appointments.json units, by event "
            "reach). waves = which of the 18 verified wave stories (waves_chart.json) it joined, with the story's "
            "months at 15+ countries in which it took part. rituals: weather today / tomorrow peak local hour (20+ "
            "trends, as rituals.json), top weather phrasing, holidays it searched in both years (clean groups, -10..+5 "
            "days). attention_twin = highest Jaccard on topic sets; attention_twin_without_sport drops sports matches, "
            "clubs (category sports_match / team) and athletes. biggest_day from step 5. kind_shares = share of its "
            "trends by moment kind; small_moment_share = share of its trends whose moment reached < 15 countries "
            "(was local_share before round 39). low_data = median covered day < 5 national trends.",
    "countries": index})
num("Wrapped", "Countries with a card", len(index), "wrapped/index.json", "countries")
num("Wrapped", "Cards flagged low_data", sum(x["low_data"] for x in index), "wrapped/index.json", "countries[].low_data")
ws = share.mean()
for k in KINDS:
    num("Wrapped", f"Mean share of trends that are {k}", float(ws[k]), "wrapped/<CC>.json", f"kind_shares.{k}")
num("Wrapped", "Mean share of trends whose moment reached < 15 countries", float(small_sh.mean()), "wrapped/<CC>.json",
    "small_moment_share")
_tw_same = sum(TWIN_ALL[c]["country_code"] == TWIN_NOSPORT[c]["country_code"] for c in W_CC)
num("Wrapped", "Attention twin: same twin on all topics and without sport (countries)",
    f"{_tw_same} of {len(W_CC)}", "wrapped/<CC>.json", "attention_twin, attention_twin_without_sport")
_mut = sum(TWIN_ALL[TWIN_ALL[c]["country_code"]]["country_code"] == c for c in W_CC)
_mutn = sum(TWIN_NOSPORT[TWIN_NOSPORT[c]["country_code"]]["country_code"] == c for c in W_CC)
num("Wrapped", "Attention twin: countries whose twin has them as twin too, all topics / without sport",
    f"{_mut} / {_mutn}", "wrapped/<CC>.json", "attention_twin")
_ws = pd.Series([len(WRAPPED_CARDS[c]["shocks"]["chart_shocks_joined"]) for c in W_CC], index=W_CC)
num("Wrapped", "Chart shocks joined per country: median / min / max (of 60)",
    f"{_ws.median():g} / {_ws.min()} / {_ws.max()}", "wrapped/<CC>.json", "shocks.chart_shocks_joined")
_wf3 = pd.Series({c: WRAPPED_CARDS[c]["shocks"]["global_moments_among_first_3"] for c in W_CC}).sort_values(ascending=False)
num("Wrapped", "Most often among the first 3 countries of a global moment (top 3)",
    ", ".join(f"{cname.get(c)} {v}" for c, v in _wf3.head(3).items()), "wrapped/<CC>.json",
    "shocks.global_moments_among_first_3")
_wwv = pd.Series([WRAPPED_CARDS[c]["waves"]["joined_n"] for c in W_CC], index=W_CC)
num("Wrapped", "Verified waves joined per country: median / countries in all 18",
    f"{_wwv.median():g} / {int((_wwv == len(_wave_cc)).sum())}", "wrapped/<CC>.json", "waves.joined")
_wtl = sum(1 for c in W_CC if WRAPPED_CARDS[c]["rituals"]["weather_today_hour"] is not None)
_w6 = sum(1 for c in W_CC if WRAPPED_CARDS[c]["rituals"]["weather_today_hour"] == 6)
num("Wrapped", "Cards with a weather 'today' hour / of which 6:00", f"{_wtl} / {_w6}", "wrapped/<CC>.json",
    "rituals.weather_today_hour")
_top_local = [c for c in _lrank_full.sort_values().index[:3]]
num("Wrapped", "Most local countries (not low_data), share of topics found nowhere else",
    ", ".join(f"{cname.get(c)} {_lsh[c]:.1%}" for c in _top_local), "wrapped/<CC>.json", "local_share")
# review data for step 9 `wrapped-review` (local report and label sheet)
write("wrapped_review.json", {"note": "Input for 09_validate_shocks.py wrapped-review (local).",
                              "cards": {c: {k: v for k, v in WRAPPED_CARDS[c].items()
                                            if k in ("country_name", "low_data", "uniquely_local_top5", "attention_twin",
                                                     "attention_twin_without_sport")} for c in W_CC}})

# ------------------------------------------------------------------ 8b days (simplified time machine)
_gd = m[m.is_global & ~m.topic_id.isin(hidden)].copy()
_gd["day"] = _gd.start_utc.dt.strftime("%Y-%m-%d")
_gd = _gd.sort_values(["day", "reach", "reach_60"], ascending=[True, False, False])
_days_all = pd.date_range(t.day.min(), t.day.max(), freq="D").strftime("%Y-%m-%d")
_gby = {d_: g_.head(5) for d_, g_ in _gd.groupby("day")}
days_out = []
for d_ in _days_all:
    g_ = _gby.get(d_)
    days_out.append({"day": d_, "gap": d_ in set(gap_days),
                     "global_moments": int((_gd.day == d_).sum()),
                     "top5": [] if g_ is None else
                     [{"moment_id": int(r.moment_id), "topic_id": r.topic_id,
                       "name": r.topic_name if isinstance(r.topic_name, str) else r.topic_id, "kind": r.kind,
                       "is_sport": bool(r.is_sport), "start_utc": iso(r.start_utc), "countries": int(r.reach),
                       "countries_within_60_min": int(r.reach_60)} for r in g_.itertuples()]})
write("days.json", {"note": "Simplified time machine (Step 9 round 39): for every UTC day of the archive, its 5 widest "
                            "global moments (>= 15 countries within 60 min of the third; not hidden), by countries then "
                            "countries within 60 min. A moment sits on the UTC day it starts. gap = collection gap day. "
                            "The hourly map frames stay in data/export/hours/ (step 5) and timemachine/.",
                    "days": days_out})
_dn = pd.Series([len(x["top5"]) for x in days_out])
num("Time machine", "Days in days.json / days with at least one global moment / gap days",
    f"{len(days_out)} / {int((_dn > 0).sum())} / {sum(x['gap'] for x in days_out)}", "days.json", "days")

# ------------------------------------------------------------------ manifest + numbers
(OUT / "manifest.json").write_text(json.dumps({"generated_by": "pipeline/08_story_export.py", "max_bytes": MAX_BYTES,
                                               "files": [{"file": r, "bytes": b} for r, b in WRITTEN],
                                               "visibility": vis,
                                               "kind_counts": {"moments": m.kind.value_counts().to_dict(),
                                                               "global_moments": m[m.is_global].kind.value_counts().to_dict(),
                                                               "topics_summary": kind.value_counts().to_dict()}},
                                              indent=1))
L = ["# Story numbers", "",
     "_Generated by `pipeline/08_story_export.py` (`make story`). Every number the article quotes, with the file in "
     "`data/export/story/` and the key it comes from. Re-run after any pipeline change; do not edit by hand._", "",
     "Conventions: national feeds; UTC unless a local hour is named; a moment is one topic in one burst of attention "
     "(DECISIONS.md, Step 4); kinds (shock, appointment, ritual, other) are rule-based and belong to moments: each trend takes the kind of its moment; waves are a topic pattern (15+ countries in 3+ months), not a kind (DECISIONS.md, Step 9); hidden sensitive topics are "
     f"excluded ({len(hidden):,} topics). Collection-gap months: {', '.join(f'{k} ({v} days)' for k, v in gap_months.items())}.", ""]
for ch in dict.fromkeys(x[0] for x in NUMBERS):
    L += [f"## {ch}", "", "| number | value | file | key |", "|---|---|---|---|"]
    for c_, label, v, fl, key in NUMBERS:
        if c_ == ch:
            L.append(f"| {label.replace('|', '/')} | {fmt(v).replace('|', '/')} | `{fl}` | `{key}` |")
    L.append("")
L += ["## Shocks tagged 'other': the 40 biggest by reach", "",
      "From `shocks.json` → `other_top40`. Sub-kinds are keyword rules (see `sub_kind_rule` in the file); check them.", "",
      "| # | topic | date (UTC) | countries | min to half | Claude type | sub-kind | top phrasings |",
      "|---|---|---|---|---|---|---|---|"]
for i, s_ in enumerate([x for x in shocks if x["kind"] == "other"][:40], 1):
    L.append(f"| {i} | {s_['name']} | {s_['date_utc'][:10]} | {s_['reach']} | {s_['minutes_to_half']} | {s_['claude_type']} | "
             f"{s_['sub_kind']} | {'; '.join(s_['phrasings'][:3]).replace('|', '/')} |")
L.append("")
(DOCS / "STORY_NUMBERS.md").write_text("\n".join(L) + "\n")
big = max(WRITTEN, key=lambda x: x[1])
print(f"{len(WRITTEN)} files, {sum(b for _, b in WRITTEN) / 1e6:.1f} MB; largest {big[0]} {big[1] / 1e6:.2f} MB")
print(f"wrote {DOCS / 'STORY_NUMBERS.md'} ({len(NUMBERS)} numbers)")
