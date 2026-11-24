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
                                               "countries": int(b_.reach), "countries_within_60_min": int(b_.reach_60),
                                               "is_global": bool(b_.is_global), "kind": _k(b_.moment_id)},
                            "month_has_shock": "shock" in kinds_in, "month_has_appointment": "appointment" in kinds_in})
        WAVE_CHART.append({"story": s_["name"], "group": _group_of.get(s_["name"]), "topics": s_["topics"],
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
