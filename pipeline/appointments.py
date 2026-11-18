"""Appointments chapter (DECISIONS.md, Step 9 round 17): every global moment of kind appointment, its category and
its event-level figures (pipeline/events.py: event reach over -2 h .. +24 h, within 60 min and minutes to half from
the third country's first trend, plus a 10-minute curve over 6 h from that same reference).

Category rule, first match wins:
  sport moments (is_sport):
    other sport  the name, sport evidence or a Wikidata description points to a sport other than football
                 (NBA, NFL, cricket, tennis, F1, golf, UFC, Olympics, a basketball / cricket / ice hockey team, ...)
    football     every other sport moment (football dominates the sport moments)
  non-sport moments, on the name + Claude's one-line "what happened" (shock-v2) + the moment's own searches:
    religious        conclave, pope, Vatican, Ramadan, Eid, Easter, Diwali, Hajj, ...
    award/ceremony   Oscars, Grammys, Golden Globes, Emmys, Nobel, Eurovision, Ballon d'Or, The Game Awards, awards
    election/politics elections, votes, referendums, inaugurations, scheduled speeches and debates, summits, budgets
    holiday          Christmas, New Year, Halloween, Valentine's Day, Mother's Day, Black Friday, carnival, ...
    launch/release   product events, film / series / game / album releases, trailers, premieres
    other            the rest
"""
import json
import re

import numpy as np
import pandas as pd

import events as EV

CATEGORIES = ["football", "other sport", "holiday", "award/ceremony", "election/politics", "launch/release",
              "religious", "other"]
CURVE_MIN = 360
CURVE_STEP = 10

OTHER_SPORT_RE = re.compile(
    r"\b(nba|wnba|nfl|super bowl|nhl|stanley cup|mlb|world series|ufc|boxing|boxer|wwe|wrestlemania|cricket|ipl|"
    r"t20|odi|test match|tennis|atp|wta|wimbledon|roland garros|french open|us open|australian open|grand slam|"
    r"f1|formula 1|formula one|grand prix|gp|motogp|golf|masters|pga|ryder cup|olympics?|olympic games|"
    r"winter olympics|juegos ol[ií]mpicos|olimpiadas?|jeux olympiques|giochi olimpici|rugby|"
    r"six nations|cycling|tour de france|giro|vuelta|nascar|indycar|darts|snooker|volleyball|handball|basketball|"
    r"euroleague|baseball|hockey|figure skating|skating|skiing|biathlon|athletics|marathon|chess|esports|"
    r"calendar: (tennis|f1|golf|cricket|winter))\b", re.I)
NON_FOOTBALL_DESC_RE = re.compile(
    r"basketball|american football|baseball|ice hockey|cricket|tennis|racing|golf|rugby|boxer|mixed martial|"
    r"wrestl|cyclist|volleyball|handball|skater|skier|athlete|sprinter|swimmer|formula", re.I)
RELIGIOUS_RE = re.compile(r"\b(conclave|pope|papa|pontiff|white smoke|habemus|vatican|vaticano|ramadan|ramadhan|"
                          r"eid|easter|pascua|p[aá]scoa|diwali|hajj|yom kippur|hanukkah|passover|holy week|"
                          r"semana santa|lent)\b", re.I)
AWARD_RE = re.compile(r"\b(oscars?|academy awards?|grammys?|golden globes?|emmys?|bafta|nobel|eurovision|"
                      r"ballon d'?or|game awards|mtv|vmas?|brit awards?|billboard music|tony awards?|cannes|"
                      r"met gala|sag awards?|critics'? choice|goya|c[eé]sar|awards?|ceremony|nominations?|"
                      r"nominees?|red carpet|wins? best|best (picture|actor|actress|director|album))\b", re.I)
ELECTION_RE = re.compile(r"\b(elections?|elecciones|elei[cç][oõ]es|elezioni|[ée]lections?|wahl\w*|bundestag|vote|"
                         r"votes|voting|referendum|ballot|inaugurat\w*|sworn in|swearing-in|state of the union|"
                         r"debate|speech|address to the nation|parliament|budget|summit|primar(y|ies)|polls?|"
                         r"exit poll|coalition|chancellor|president-elect|white house|oval office|press conference|"
                         r"meeting with|state visit|official visit)\b", re.I)
HOLIDAY_RE = re.compile(r"\b(christmas|navidad|natal|new year'?s?|a[ñn]o nuevo|halloween|valentine'?s?|"
                        r"mother'?s day|father'?s day|thanksgiving|black friday|cyber monday|independence day|"
                        r"national day|carnival|carnaval|lunar new year|chinese new year|holiday|feriado|festivo)\b",
                        re.I)
LAUNCH_RE = re.compile(r"\b(launch\w*|releas\w*|trailer|teaser|premiere\w*|estreno|keynote|wwdc|unveil\w*|"
                       r"announc\w*|reveal\w*|pre-?sale|pre-?orders?|album|single|season \d+|episode|debut\w*|"
                       r"new model|iphone|galaxy|pixel|console|video game|game|film|movie|series|show|wrapped|"
                       r"tickets?|tour dates|showcase|direct|state of play)\b", re.I)
NON_SPORT_ORDER = [("religious", RELIGIOUS_RE), ("award/ceremony", AWARD_RE), ("election/politics", ELECTION_RE),
                   ("holiday", HOLIDAY_RE), ("launch/release", LAUNCH_RE)]


def team_descs(name, wd_by_query):
    """Wikidata descriptions of the two sides of a fixture name ('A vs B'), when the sides are known searches."""
    parts = re.split(r"\s+(?:vs\.?|v|x|-)\s+", str(name).lower())
    return [wd_by_query.get(p.strip(), "") for p in parts if p.strip()]


def category(r, text, wd_by_query, wd_desc):
    """Category of one appointment moment. r: moment row; text: name + Claude summary + the moment's searches."""
    if r.is_sport:
        descs = [wd_desc or ""] + team_descs(r.topic_name, wd_by_query)
        if OTHER_SPORT_RE.search(f"{r.topic_name} | {r.sport_evidence or ''}") or \
                any(NON_FOOTBALL_DESC_RE.search(d or "") for d in descs):
            return "other sport"
        return "football"
    for cat, rx in NON_SPORT_ORDER:
        if rx.search(text):
            return cat
    return "other"


def moment_terms(rows_by_topic, r, k=20):
    g = rows_by_topic.get(r.topic_id)
    ph = [c["phrasing"].lower() for c in r.countries if c["phrasing"]]
    if g is None:
        return ph
    hi = max(r.end_utc, r.start_utc + pd.Timedelta(hours=1))
    w = g[(g.start_time_utc >= r.start_utc) & (g.start_time_utc <= hi)]
    rel = [x.lower() for lst in w.related for x in (lst if lst is not None else [])]
    return list(dict.fromkeys(ph + w.query_raw.str.lower().tolist() + rel))[:k]


def event_figures(rows_by_topic, topic_ids, start):
    """Event reach, within 60 min, minutes to half and the 10-minute curve over 6 h (from the third country)."""
    lo, hi = EV.window(start)
    parts = [rows_by_topic[x] for x in topic_ids if x in rows_by_topic]
    if not parts:
        return {"event_reach": 0, "event_reach_60": 0, "event_minutes_to_half": None, "curve": []}
    w = pd.concat(parts)
    w = w[(w.start_time_utc >= lo) & (w.start_time_utc < hi)]
    first = w.groupby("country_code").start_time_utc.min().sort_values()
    if first.empty:
        return {"event_reach": 0, "event_reach_60": 0, "event_minutes_to_half": None, "curve": []}
    ref, mins = EV.from_third(first)
    return {"event_reach": int(len(first)), "event_reach_60": int((mins <= 60).sum()),
            "event_minutes_to_half": EV.half_minutes(mins), "reference_utc": ref,
            "curve": [[k, int((mins <= k).sum())] for k in range(0, CURVE_MIN + 1, CURVE_STEP)]}


def build(m, meta, rows, terms_rows, labels_path, groups=None):
    """All global appointment moments with category and event figures. m: moments; meta: topic_meta indexed by
    topic_id; rows: national rows (topic_id, country_code, start_time_utc) of every topic that can be in a group;
    terms_rows: national rows with query_raw and related, for the non-sport appointment topics; groups:
    {moment_id: accepted topic_ids} or None (main topic only)."""
    from common import WORK
    a = m[m.is_global & m.kind.eq("appointment")].copy()
    summ = {}
    if labels_path.exists():
        for line in labels_path.read_text().splitlines():
            x = json.loads(line)
            if x.get("prompt_version") == "shock-v2":
                summ[x["key"]] = x["what_happened"]
    wd = pd.read_parquet(WORK / "wikidata_qids.parquet", columns=["query_norm", "qid", "wd_desc"])
    wd_by_query = dict(zip(wd.query_norm, wd.wd_desc.fillna("")))
    wd_by_qid = wd.drop_duplicates("qid").set_index("qid").wd_desc
    groups = groups or {}
    rows_by_topic = {k: g for k, g in rows.groupby("topic_id")}
    terms_by_topic = {k: g for k, g in terms_rows.groupby("topic_id")}
    out = []
    for r in a.itertuples():
        key = f"{r.topic_id}|{pd.Timestamp(r.start_utc):%Y-%m-%dT%H:%MZ}"
        terms = [] if r.is_sport else moment_terms(terms_by_topic, r)
        text = " | ".join([str(r.topic_name), summ.get(key, "")] + terms)
        q = meta.qid.get(r.topic_id)
        cat = category(r, text, wd_by_query, wd_by_qid.get(q) if isinstance(q, str) else None)
        grp = {r.topic_id} | groups.get(int(r.moment_id), set())
        ef = event_figures(rows_by_topic, grp, r.start_utc)
        out.append({"moment_id": int(r.moment_id), "key": key, "topic_id": r.topic_id, "name": r.topic_name,
                    "date_utc": f"{pd.Timestamp(r.start_utc):%Y-%m-%dT%H:%MZ}", "is_sport": bool(r.is_sport),
                    "category": cat, "claude_summary": summ.get(key), "moment_reach": int(r.reach),
                    "reach_60": int(r.reach_60), "event_topics": sorted(grp), **{k: v for k, v in ef.items()
                                                                                 if k != "reference_utc"}})
    return pd.DataFrame(out)
