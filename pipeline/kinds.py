"""Two layers (DECISIONS.md, Step 9 rounds 3-4):
  - MOMENT kind: shock | appointment | ritual | other (what each spike was). `moment_kinds` gives every moment its
    own kind in step 4 (moments.parquet `kind`); the timeline, shocks.json and every chart use it. A topic's kind
    is only a summary: the kind of its biggest moment (`topic_summary_kind`, topic_meta.parquet `kind`).
  - TOPIC patterns (topic_meta.parquet `wave_months`, `is_wave`, `is_constant`), independent of moment kinds:
      is_wave     = 15+ countries in at least WAVE_MIN_MONTHS separate calendar (UTC) months, and the topic is not
                    a sport topic, an athlete or a ritual (`wave_flags`);
      is_constant = 15+ countries in at least CONSTANT_MIN_MONTHS months (any topic). A topic can be both (ChatGPT).
`topic_kinds` is the older topic-level rule, kept for 09_validate_shocks.py (the timing-rule columns of sample 1).
Rules as in docs/STORY_CANDIDATES.md and DECISIONS.md (Steps 8 and 9).

SHOCK_MIN_REACH: a shock topic's biggest moment must reach this many countries. 15 since 2026-11-13, the
same number as the global-moment rule (it was 20 before; 09_validate_shocks.py reports 10 / 15 / 20).
"""
import json

import pandas as pd

SHOCK_MIN_REACH = 15
# Shock MOMENT rule (2026-11-16, DECISIONS.md Step 9, validated on hand sample 1): a global, non-sport moment that
# Claude (prompt shock-v2: the moment's own searches, forced scheduled/unscheduled) calls unscheduled with confidence
# >= SHOCK_MIN_CONF. No extra speed test: a global moment already has 15+ countries within an hour of the third.
SHOCK_MIN_CONF = 0.5
SHOCK_PROMPT = "shock-v2"


def load_shock_labels(path):
    """{moment key 'topic_id|YYYY-mm-ddTHH:MMZ': (scheduled, confidence)} from the step-9 label cache."""
    out = {}
    if path.exists():
        for line in path.read_text().splitlines():
            r = json.loads(line)
            if r.get("prompt_version") == SHOCK_PROMPT:
                out[r["key"]] = (r["scheduled"], float(r["confidence"]))
    return out


def moment_key(topic_id, start):
    return f"{topic_id}|{pd.Timestamp(start).strftime('%Y-%m-%dT%H:%MZ')}"


def shock_moments(m, labels, min_conf=SHOCK_MIN_CONF):
    """(is_shock, labelled, claude_scheduled) Series over moments m (needs is_global, is_sport, topic_id, start_utc);
    claude_scheduled is "scheduled" / "unscheduled" for labelled global non-sport moments, else None."""
    cand = m.is_global.astype(bool) & ~m.is_sport.astype(bool)
    keys = pd.Series([moment_key(a, b) if c else None for a, b, c in zip(m.topic_id, m.start_utc, cand)], index=m.index)
    lab = keys.map(lambda k: labels.get(k) if k else None)
    is_shock = lab.map(lambda x: bool(x) and x[0] == "unscheduled" and x[1] >= min_conf)
    return is_shock.astype(bool), lab.notna(), lab.map(lambda x: x[0] if x else None)


def topic_ritual(meta, m):
    """Ritual topics (recurring by nature): weather, holidays, lotteries / prayer times / horoscopes / rates
    (RITUAL_RE), and non-sport other/product/company/unlabeled topics with 15+ moments of 10+ countries.
    meta: indexed by topic_id with topic_name, type, category; m: moments with topic_id, reach. -> bool Series."""
    n10 = m[m.reach >= 10].groupby("topic_id").size().reindex(meta.index).fillna(0)
    nm = meta.topic_name.astype(str).str.lower()
    sport_t = meta.is_sport.fillna(False).astype(bool) if "is_sport" in meta else False
    return ((meta.category == "weather") | (meta["type"] == "holiday") | nm.str.contains(RITUAL_RE) |
            ((n10 >= 15) & ~sport_t & meta["type"].isin(["other", "product", "company", "unlabeled"])))


def moment_kinds(m, ritual_topics):
    """Kind of every moment (MOMENT_KINDS). m needs topic_id, topic_name, is_sport, is_shock, claude_scheduled.
    Later rules win:
      other        none of the below (most moments: small local spikes, or spread with no clear trigger)
      appointment  sport moment, a scheduled-event name (APPOINT_RE), or Claude says scheduled
      ritual       the topic is a ritual (topic_ritual)
      shock        is_shock (validated in step 9; wins even over ritual: a storm on a weather topic)
    Reach is not a kind: "local" (< 15 countries) is a property of the moment's reach, not of what happened."""
    rit = m.topic_id.isin(ritual_topics)
    tn = m.drop_duplicates("topic_id").set_index("topic_id").topic_name.astype(str).str.lower()
    appoint_t = set(tn.index[tn.str.contains(APPOINT_RE)])
    appoint = m.is_sport.astype(bool) | m.topic_id.isin(appoint_t) | m.claude_scheduled.eq("scheduled")
    kind = pd.Series("other", index=m.index)
    kind[appoint] = "appointment"
    kind[rit] = "ritual"
    kind[m.is_shock.astype(bool)] = "shock"
    return kind


def wave_months(t, min_countries=None):
    """Per topic: number of calendar (UTC) months in which 15+ countries' national feeds trended it.
    t: national rows with topic_id, country_code, start_time_utc."""
    min_countries = WAVE_MIN_COUNTRIES if min_countries is None else min_countries
    mo = t.start_time_utc.dt.strftime("%Y-%m")
    cm = t.assign(month=mo).groupby(["topic_id", "month"]).country_code.nunique()
    return (cm >= min_countries).groupby(level=0).sum().astype(int)


def wave_flags(meta, months, ritual, athlete):
    """(is_wave, is_constant) per topic. meta: indexed by topic_id with is_sport (topic rule); months: wave_months();
    ritual, athlete: bool Series by topic_id."""
    mo = months.reindex(meta.index).fillna(0)
    excl = meta.is_sport.fillna(False).astype(bool) | ritual.reindex(meta.index).fillna(False).astype(bool) | \
        athlete.reindex(meta.index).fillna(False).astype(bool)
    return (mo >= WAVE_MIN_MONTHS) & ~excl, mo >= CONSTANT_MIN_MONTHS


def topic_summary_kind(m):
    """Summary kind per topic = the kind of its biggest moment (reach, then countries within 60 min)."""
    best = m.sort_values(["reach", "reach_60"], ascending=False).drop_duplicates("topic_id")
    return best.set_index("topic_id").kind
LOCAL_MAX_REACH = 15          # old topic rule: biggest moment below this -> local (unless ritual)
MOMENT_KINDS = ["shock", "appointment", "ritual", "other"]
WAVE_MIN_MONTHS = 3           # proposed 2026-11-16: the lowest N that keeps DeepSeek and the Epstein files
WAVE_MIN_COUNTRIES = 15
CONSTANT_MIN_MONTHS = 12      # of the 18 full months (the data covers 19 calendar months)

RITUAL_RE = (r"lotto|lottery|loter|quina|mega ?sena|lotofacil|powerball|euromillion|xo so|kqxs|prayer|namaz|"
             r"salat|solat|sholat|adhan|horoscope|wordle|connections|strands|crossword|exchange rate|dollar rate|"
             r"gold (price|rate)|fuel price|petrol price|weather|forecast|tide|sunrise|sunset|tv guide")
APPOINT_RE = (r"final|award|awards|oscar|grammy|emmy|golden globe|eurovision|election|elecciones|debate|super bowl|"
              r"launch|release|premiere|estreno|draw|keynote|budget|summit|ceremony|festival|black friday|"
              r"cyber monday|world cup|olympic|marathon|grand prix|coronation|inauguration|met gala|wwdc|"
              r"apple event|state of the union|season \d|episode|trailer|draft|halftime|wrestlemania|"
              r"new year|countdown|eclipse|meteor shower|supermoon")
SHOCK_TYPES = ["event", "person", "company", "product", "place", "other", "unlabeled", "media"]


def topic_features(t, m, meta):
    """Per topic: biggest moment's reach and minutes to half, days in 10+ countries, moments of 10+ countries.
    t = national trend rows with topic_id, country_code and a UTC `day` column."""
    best = m.sort_values(["reach", "reach_60"], ascending=False).drop_duplicates("topic_id").set_index("topic_id")
    day_cc = t.groupby(["topic_id", "day"]).country_code.nunique()
    f = pd.DataFrame({"max_reach": best.reach, "best_min_to_half": best.minutes_to_half})
    f["persistence_days"] = (day_cc >= 10).groupby(level=0).sum().reindex(f.index).fillna(0).astype(int)
    f["moments_10plus"] = m[m.reach >= 10].groupby("topic_id").size().reindex(f.index).fillna(0).astype(int)
    f["type"] = meta["type"].reindex(f.index)
    f["category"] = meta["category"].reindex(f.index)
    f["is_sport"] = meta.is_sport.reindex(f.index).fillna(False).astype(bool)
    if "is_shock" in m:
        f["shock_moments"] = m[m.is_shock.astype(bool)].groupby("topic_id").size().reindex(f.index).fillna(0).astype(int)
    f["name"] = meta.topic_name.astype(str).reindex(f.index).fillna("")
    return f


def topic_kinds(f, shock_min_reach=SHOCK_MIN_REACH):
    """Kind per topic from topic_features(). Later rules win: shock < appointment < ritual; then local."""
    nm = f.name.str.lower()
    ritual = (f.category == "weather") | (f.type == "holiday") | nm.str.contains(RITUAL_RE) | \
             ((f.moments_10plus >= 15) & ~f.is_sport & f.type.isin(["other", "product", "company", "unlabeled"]))
    appoint = f.is_sport | nm.str.contains(APPOINT_RE) | ((f.type == "person") & (f.moments_10plus >= 10))
    if "shock_moments" in f:
        # since 2026-11-16: the topic has a shock moment (shock_moments above) and is not a long-running story
        shock = (f.shock_moments > 0) & (f.persistence_days <= 4) & f.type.isin(SHOCK_TYPES)
    else:   # old timing rule (before moments carry is_shock)
        shock = (f.best_min_to_half <= 180) & (f.max_reach >= shock_min_reach) & (f.persistence_days <= 4) & \
                f.type.isin(SHOCK_TYPES)
    kind = pd.Series("wave", index=f.index)
    kind[shock] = "shock"
    kind[appoint] = "appointment"
    kind[ritual] = "ritual"
    kind[(f.max_reach < LOCAL_MAX_REACH) & (kind != "ritual")] = "local"
    return kind
