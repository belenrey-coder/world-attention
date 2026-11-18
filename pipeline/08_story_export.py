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
from kinds import LOCAL_MAX_REACH, MOMENT_KINDS, WAVE_MIN_MONTHS, topic_features  # noqa: E402
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
write("shocks.json", {"note": "Sport-free global moments (>= 15 countries within 60 min of the third country) that "
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
for k, rows in monthly.items():
    b = max(rows, key=lambda d: d["countries"])
    num("Waves", f"{k}: peak month and countries", f"{b['month']}: {b['countries']}", "waves.json", f"monthly.{k}")
for k, rows in daily.items():
    b = max(rows, key=lambda d: d[1])
    num("Waves", f"{k}: peak day Mar-Apr 2025 and countries", f"{b[0]}: {b[1]}", "waves.json", f"daily.{k}")

# ------------------------------------------------------------------ 5b appointments
print("appointments ...", flush=True)
# every global moment of kind appointment (Step 9 round 17; pipeline/appointments.py): category, event reach
# (main topic + accepted topics about the same event once docs/event_groups_review_appointments.csv is reviewed),
# within 60 min and minutes to half from the third country, and a 10-minute curve over 6 h
import appointments as AP  # noqa: E402
APPT_GROUPS = EV.load_groups(DOCS, EV.APPOINTMENT_REVIEW_FILES) if EV.reviewed(DOCS, EV.APPOINTMENT_REVIEW_FILES) else None
_ns_t = set(m[m.is_global & m.kind.eq("appointment") & ~m.is_sport.astype(bool)].topic_id)
_tr = pd.read_parquet(INTERIM / "topics.parquet", columns=["topic_id", "level", "start_time_utc", "query_raw", "related"],
                      filters=[("topic_id", "in", sorted(_ns_t))])
_tr = _tr[_tr.level == "country"]
_app_t = set(m[m.is_global & m.kind.eq("appointment")].topic_id) | {x for v in (APPT_GROUPS or {}).values() for x in v}
appt = AP.build(m, meta, t[t.topic_id.isin(_app_t)][["topic_id", "country_code", "start_time_utc"]], _tr,
                ROOT / "cache" / "claude" / "shocks" / "labels.jsonl", APPT_GROUPS)
appt = appt[~appt.topic_id.isin(hidden) & appt.topic_id.isin(set(_named)) & (appt.name.astype(str).str.len() > 2)]
appt["verified"] = appt.moment_id.map(m.set_index("moment_id").hand_scheduled).eq("scheduled")
appt = appt.sort_values(["event_reach", "event_reach_60", "moment_reach"], ascending=False)
APPT_CHART = pd.concat([appt[appt.category == "football"].head(10)] +
                       [appt[appt.category == c].head(5) for c in AP.CATEGORIES if c != "football"])


def _appt_item(r, curve=True):
    d = {"moment_id": int(r.moment_id), "topic_id": r.topic_id, "name": r.name, "date_utc": r.date_utc,
         "is_sport": bool(r.is_sport), "category": r.category, "event_reach": int(r.event_reach),
         "event_reach_60": int(r.event_reach_60), "event_minutes_to_half": r.event_minutes_to_half,
         "moment_reach": int(r.moment_reach), "verified": bool(r.verified),
         "event_topics": [name.get(x, x) for x in r.event_topics]}
    if curve:
        d["curve"] = r.curve
    return d


appt_files = []
for mo, g in appt.assign(month=appt.date_utc.str[:7]).groupby("month"):
    rel = f"appointments/{mo}.json"
    write(rel, {"month": mo, "fields": ["moment_id", "name", "date_utc", "is_sport", "category", "event_reach",
                                        "event_reach_60", "event_minutes_to_half", "moment_reach", "verified", "curve"],
                "rows": [[int(r.moment_id), r.name, r.date_utc, int(r.is_sport), r.category, int(r.event_reach),
                          int(r.event_reach_60), r.event_minutes_to_half, int(r.moment_reach), int(r.verified),
                          [c for _, c in r.curve]] for r in g.itertuples()]})
    appt_files.append(rel)
_g_all = int((m.is_global & ~m.topic_id.isin(hidden)).sum())
write("appointments.json", {
    "note": "Global moments of kind appointment (scheduled: sport, ceremonies, elections, launches, religious "
            "events). Event reach = countries where any topic about the same event trended from 2 h before to 24 h "
            "after the moment start; within 60 min, minutes to half and the curve count from the third country's "
            "first trend (curve = [minute, countries] every 10 min for 6 h). verified = hand-labelled scheduled. "
            "Per-moment rows with curves are in the monthly files.",
    "reach_basis": "event reach with reviewed event groups" if APPT_GROUPS is not None
                   else "event reach, main topic only (event groups not reviewed yet)",
    "categories": AP.CATEGORIES, "category_rule": AP.__doc__.split("Category rule, first match wins:")[1].strip(),
    "counts": {"appointments": len(appt), "global_moments": _g_all, "share_of_global": round(len(appt) / _g_all, 4),
               "sport": int(appt.is_sport.sum()), "non_sport": int((~appt.is_sport).sum()),
               "by_category": appt.category.value_counts().reindex(AP.CATEGORIES, fill_value=0).to_dict()},
    "chart": {"rule": "top 10 football + top 5 of each other category, by event reach",
              "verified": int(APPT_CHART.verified.sum()), "moments": [_appt_item(r) for r in APPT_CHART.itertuples()]},
    "top20_by_event_reach": [_appt_item(r, curve=False) for r in appt.head(20).itertuples()],
    "files": appt_files})
num("Appointments", "Global appointment moments (share of all global moments)",
    f"{len(appt):,} ({len(appt) / _g_all:.1%})", "appointments.json", "counts")
num("Appointments", "... sport / non-sport", f"{int(appt.is_sport.sum()):,} / {int((~appt.is_sport).sum()):,}",
    "appointments.json", "counts")
for c_, v_ in appt.category.value_counts().reindex(AP.CATEGORIES, fill_value=0).items():
    num("Appointments", f"... category {c_}", int(v_), "appointments.json", "counts.by_category")
for r in appt.head(5).itertuples():
    num("Appointments", f"{r.name} ({r.date_utc[:10]}): event reach / within 60 min / minutes to half",
        f"{r.event_reach} / {r.event_reach_60} / {r.event_minutes_to_half}", "appointments.json", "top20_by_event_reach")
num("Appointments", "Chart set (stratified), of which hand-verified", f"{int(APPT_CHART.verified.sum())} of {len(APPT_CHART)}",
    "appointments.json", "chart")

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
WHOLE = {"Ramadan": topics_where(r"\bramadan\b|ramazan|ramad[aã]n"),
         "Eid": topics_where(r"\beid\b|eid al|eid-al|bayram|lebaran|hari raya|aid el"),
         "Easter": topics_where(r"\beaster\b"),
         "Is it down": topics_where(r"outage|\bdown\b|not working", exclude=r"power|electric|blackout|apag")}
STRICT_RX = {k: (WHEN_RE, rx) for k, rx in FEST.items()} | {"Is it down": (DOWN_RE, None)}


def day_series(rows):
    g = rows.groupby("day").agg(countries=("country_code", "nunique"), trends=("country_code", "size"))
    return g


def summary(rows):
    g = day_series(rows)
    if g.empty:
        return {"trends": 0, "countries": 0, "peak_day": None, "peak_countries": 0}, []
    pk = g.countries.idxmax()
    return ({"trends": int(len(rows)), "countries": int(rows.country_code.nunique()), "peak_day": pk,
             "peak_countries": int(g.countries.max())}, [[d, int(x.countries), int(x.trends)] for d, x in g.iterrows()])


by_topic_counts = {}
for k in WHOLE:
    rx1, rx2 = STRICT_RX[k]
    strict = tv[ql.str.contains(rx1, regex=True, na=False) & (ql.str.contains(rx2, regex=True, na=False) if rx2 else True)]
    whole = tv[tv.topic_id.isin(WHOLE[k])]
    s_sum, s_days = summary(strict)
    w_sum, w_days = summary(whole)
    by_topic_counts[k] = {"strict": s_sum | {"rule": "searches phrased 'when is ...' / 'is ... down' only"},
                          "whole_topic": w_sum | {"topics": len(WHOLE[k]),
                                                  "rule": "every trend of topics whose Claude name matches (the article uses this)"},
                          "strict_by_day": s_days, "whole_topic_by_day": w_days}
rituals = {"note": "Weather topics (category weather) by local hour, weekday (Mon-Fri) vs weekend (Sat-Sun). US, CA and RU "
                   "use regional feeds in each region's zone; all others one zone per country. 'all_without_19utc_bump' "
                   "leaves out trends starting 19:00-19:59 UTC (CHECKS.md C4). Date series are UTC days: [day, countries, trends].",
           "weather_all_countries": split(w), "weather_tomorrow_all_countries": split(w[w.tomorrow]),
           "per_country": per_c,
           "weather_days": weather_days,
           "when_is": when, "is_x_down": [[d, int(x.countries), int(x.trends), x.top] for d, x in dg.iterrows()],
           "by_topic": by_topic_counts}
write("rituals.json", rituals)
allh = pd.Series(rituals["weather_all_countries"]["all"])
nob = pd.Series(rituals["weather_all_countries"]["all_without_19utc_bump"])
num("Rituals", "Weather: busiest local hour, all countries (with / without 19 UTC bump)", f"{allh.idxmax()} / {nob.idxmax()}",
    "rituals.json", "weather_all_countries")
num("Rituals", "Archive days (first to last data day) / of which full collection coverage",
    f"{weather_days['archive_days']} / {weather_days['full_coverage_days']}", "rituals.json", "weather_days.full_coverage_days")
num("Rituals", f"(a) Full-coverage days on which the topic 'Weather' ({len(wx_named)} topics named so) trended in 10+ countries",
    weather_days["topic_weather_days_10plus"], "rituals.json", "weather_days.topic_weather_days_10plus")
num("Rituals", "(a') ... the single topic with id 'Weather' only", weather_days["topic_weather_plain_id_days_10plus"],
    "rituals.json", "weather_days.topic_weather_plain_id_days_10plus")
num("Rituals", f"(b) Full-coverage days on which any weather topic ({len(weather_ids):,} topics) trended in 10+ countries",
    weather_days["any_weather_topic_days_10plus"], "rituals.json", "weather_days.any_weather_topic_days_10plus")
for k, v in by_topic_counts.items():
    w_, s_ = v["whole_topic"], v["strict"]
    num("Rituals", f"{k}, whole topic ({w_['topics']} topics): peak day and countries (ARTICLE)",
        f"{w_['peak_day']}: {w_['peak_countries']}", "rituals.json", f"by_topic.{k}.whole_topic")
    num("Rituals", f"{k}, whole topic: countries ever / trends", f"{w_['countries']} / {w_['trends']:,}", "rituals.json",
        f"by_topic.{k}.whole_topic")
    num("Rituals", f"{k}, strict phrasing: peak day and countries", f"{s_['peak_day']}: {s_['peak_countries']}",
        "rituals.json", f"by_topic.{k}.strict")
    num("Rituals", f"{k}, strict phrasing: countries ever / trends", f"{s_['countries']} / {s_['trends']:,}", "rituals.json",
        f"by_topic.{k}.strict")

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
print("wrapped ...", flush=True)
share = t.groupby(["country_code", "kind"]).size().unstack(fill_value=0)     # rows by their moment's kind
share = share.div(share.sum(1), axis=0).reindex(columns=KINDS, fill_value=0)
local_sh = (t.moment_reach < LOCAL_MAX_REACH).groupby(t.country_code).mean()   # reach, not a kind
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
            "kind_shares": {k: round(float(share.loc[c, k]), 4) if c in share.index else 0.0 for k in KINDS},
            "local_share": round(float(local_sh.get(c, 0.0)), 4)}
    write(f"wrapped/{c}.json", card)
    index.append({k: card[k] for k in ("country_code", "country_name", "low_data", "weather_hour")} |
                 {"twin": card["attention_twin"]["country_code"], "local_share": card["local_share"]})
write("wrapped/index.json", {"note": "Per-country cards; card choices (most local topic, biggest day) come from step 5 and "
                                     "respect the sensitive-topic decisions. kind_shares = share of the country's trends "
                                     "by the kind of the moment each trend belongs to; local_share = share of the country's trends whose moment "
                                     "reached < 15 countries. low_data = median covered day < 5 national trends.", "countries": index})
num("Wrapped", "Countries with a card", len(index), "wrapped/index.json", "countries")
num("Wrapped", "Cards flagged low_data", sum(x["low_data"] for x in index), "wrapped/index.json", "countries[].low_data")
ws = share.mean()
for k in KINDS:
    num("Wrapped", f"Mean share of trends that are {k}", float(ws[k]), "wrapped/<CC>.json", f"kind_shares.{k}")
num("Wrapped", "Mean share of trends whose moment reached < 15 countries", float(local_sh.mean()), "wrapped/<CC>.json",
    "local_share")

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
