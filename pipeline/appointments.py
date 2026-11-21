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
    r"calendar: (tennis|f1|golf|cricket|winter)|"
    # NBA, NFL and IPL sides (fixture names rarely say the league)
    r"lakers|celtics|warriors|knicks|pacers|thunder|(?<!red )bulls|magic|nets|heat|bucks|cavaliers|nuggets|timberwolves|"
    r"mavericks|rockets|suns|clippers|spurs vs|vs spurs|grizzlies|pelicans|hawks|hornets|pistons|raptors|76ers|"
    r"sixers|wizards|jazz|trail blazers|chiefs|eagles|ravens|49ers|cowboys|packers|bengals|steelers|broncos|"
    r"seahawks|patriots|commanders|vikings|texans|jaguars|dolphins|buccaneers|saints|falcons|rams|chargers|raiders|"
    r"mumbai indians|chennai super kings|royal challengers|kolkata knight riders|delhi capitals|punjab kings|"
    r"rajasthan royals|sunrisers|lucknow super giants|gujarat titans)\b", re.I)
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
        terms = ([c["phrasing"].lower() for c in r.countries if c["phrasing"]][:20] if r.is_sport
                 else moment_terms(terms_by_topic, r))
        text = " | ".join([str(r.topic_name), summ.get(key, "")] + terms)
        q = meta.qid.get(r.topic_id)
        cat = category(r, text, wd_by_query, wd_by_qid.get(q) if isinstance(q, str) else None)
        grp = {r.topic_id} | groups.get(int(r.moment_id), set())
        ef = event_figures(rows_by_topic, grp, r.start_utc)
        out.append({"moment_id": int(r.moment_id), "key": key, "topic_id": r.topic_id, "name": r.topic_name,
                    "date_utc": f"{pd.Timestamp(r.start_utc):%Y-%m-%dT%H:%MZ}", "is_sport": bool(r.is_sport),
                    "category": cat, "claude_summary": summ.get(key), "moment_reach": int(r.reach),
                    "reach_60": int(r.reach_60), "event_topics": sorted(grp), "text": text,
                    **{k: v for k, v in ef.items()
                                                                                 if k != "reference_utc"}})
    return pd.DataFrame(out)


# ------------------------------------------------------------------ scheduled events (Step 9 round 18)
# Non-sport appointments are counted by SCHEDULED EVENT, not by topic: an awards night appears as many people and
# films, an election as several parties. A moment joins an event when it starts inside the event's window AND its
# text (name + Claude's one-line summary + the moment's own searches; for sport moments name + phrasings) matches
# the event's pattern. Finals and draws split across topics (players, the competition, the half-time act) are
# grouped the same way. Moments matching no event stay their own unit (a match, a trailer); unclear non-sport
# moments (category "other") are left unassigned. Ceremony, election, launch and religious events take only non-sport
# moments (an "Olympique Lyonnais" match is not the Olympics closing ceremony); finals, draws and the Super Bowl take
# both. Windows are UTC: the event day, or the night of a ceremony
# across midnight UTC.
def _w(a, b):
    return pd.Timestamp(a, tz="UTC"), pd.Timestamp(b, tz="UTC")


CATALOGUE = [
    # id, name, category, window, pattern
    ("game-awards-2024", "The Game Awards 2024", "award/ceremony", _w("2024-12-12 20:00", "2024-12-13 08:00"),
     r"game awards|astro bot|elden ring|troy baker|indiana jones|harrison ford"),
    ("inauguration-2025", "Trump inauguration 2025", "election/politics", _w("2025-01-20 06:00", "2025-01-21 06:00"),
     r"inaugurat|capital one arena|swearing|sworn"),
    ("oscar-nominations-2025", "Oscar nominations 2025", "award/ceremony", _w("2025-01-23 10:00", "2025-01-24 10:00"),
     r"oscar|academy award"),
    ("grammys-2025", "Grammys 2025", "award/ceremony", _w("2025-02-02 18:00", "2025-02-03 08:00"), r"grammy"),
    ("super-bowl-lix", "Super Bowl LIX", "other sport", _w("2025-02-09 18:00", "2025-02-10 06:00"),
     r"super bowl|halftime|half-time|\bnfl\b|chiefs|eagles|kendrick"),
    ("apple-2025-02", "Apple event, Feb 2025 (iPhone 16e)", "launch/release", _w("2025-02-19 06:00", "2025-02-20 06:00"),
     r"iphone|apple"),
    ("german-election-2025", "German federal election 2025", "election/politics", _w("2025-02-23 06:00", "2025-02-24 06:00"),
     r"bundestagswahl|german|election|wahl|\bafd\b|cdu|csu|linke|greens|gr[uü]ne|\bbsw\b|\bspd\b|merz"),
    ("oscars-2025", "Oscars 2025", "award/ceremony", _w("2025-03-02 18:00", "2025-03-03 08:00"),
     r"oscar|academy award|best (picture|actor|actress|director|documentary|animated)"),
    ("conclave-2025", "Conclave 2025 (Pope Leo XIV)", "religious", _w("2025-05-08 12:00", "2025-05-09 06:00"),
     r"pope|papa|conclave|c[oó]nclave|habemus|humo blanco|white smoke|fumata|prevost|leo xiv|le[oó]n xiv"),
    ("esc-2025-sf1", "Eurovision 2025, semi-final 1", "award/ceremony", _w("2025-05-13 12:00", "2025-05-14 03:00"),
     r"eurovision|\besc\b|eurovisi[oó]n"),
    ("esc-2025-sf2", "Eurovision 2025, semi-final 2", "award/ceremony", _w("2025-05-15 12:00", "2025-05-16 03:00"),
     r"eurovision|\besc\b|eurovisi[oó]n"),
    ("esc-2025-final", "Eurovision 2025 final", "award/ceremony", _w("2025-05-17 12:00", "2025-05-18 03:00"),
     r"eurovision|\besc\b|eurovisi[oó]n|k[aä][aä]rij[aä]"),
    ("polish-election-2025", "Polish presidential election 2025", "election/politics",
     _w("2025-05-18 06:00", "2025-05-19 06:00"), r"election|wybory|presidential"),
    ("europa-final-2025", "Europa League final 2025", "football", _w("2025-05-21 12:00", "2025-05-22 06:00"),
     r"europa league|tottenham|manchester united|\bspurs\b"),
    ("ucl-final-2025", "Champions League final 2025 (PSG vs Inter)", "football", _w("2025-05-31 15:00", "2025-06-01 06:00"),
     r"champions league|paris saint-germain|\bpsg\b|inter milan|internazionale|dou[eé]|hakimi|"
     r"kvaratskhelia|mayulu|donnarumma|linkin park|vitinha|demb[eé]l[eé]|lautaro"),
    ("roland-garros-final-2025", "Roland Garros men's final 2025", "other sport", _w("2025-06-08 08:00", "2025-06-09 06:00"),
     r"alcaraz|sinner|roland garros|french open"),
    ("g7-2025", "G7 summit 2025", "election/politics", _w("2025-06-16 06:00", "2025-06-17 06:00"), r"\bg7\b|summit"),
    ("wimbledon-final-2025", "Wimbledon men's final 2025", "other sport", _w("2025-07-13 12:00", "2025-07-14 03:00"),
     r"sinner|alcaraz|wimbledon|mcconaughey"),
    ("cwc-final-2025", "Club World Cup final 2025 (Chelsea vs PSG)", "football", _w("2025-07-13 15:00", "2025-07-14 06:00"),
     r"club world cup|mundial de clubes|paris saint-germain|\bpsg\b|chelsea|metlife|jo[aã]o pedro|gusto|delap|"
     r"palmer|coldplay"),
    ("nobel-literature-2025", "Nobel Prize in Literature 2025", "award/ceremony", _w("2025-10-09 06:00", "2025-10-10 03:00"),
     r"nobel"),
    ("nobel-peace-2025", "Nobel Peace Prize 2025", "award/ceremony", _w("2025-10-10 03:00", "2025-10-11 03:00"), r"nobel"),
    ("vs-show-2025", "Victoria's Secret Fashion Show 2025", "award/ceremony", _w("2025-10-15 18:00", "2025-10-16 08:00"),
     r"victoria'?s secret"),
    ("grammy-nominations-2026", "Grammy nominations 2026", "award/ceremony", _w("2025-11-07 10:00", "2025-11-08 06:00"),
     r"grammy"),
    ("st5-release", "Stranger Things 5 release", "launch/release", _w("2025-11-26 18:00", "2025-11-27 18:00"),
     r"stranger things"),
    ("spotify-wrapped-2024", "Spotify Wrapped and year-end recaps 2024", "launch/release", _w("2024-12-04 06:00", "2024-12-05 06:00"),
     r"spotify|wrapped"),
    ("spotify-wrapped-2025", "Spotify Wrapped and year-end recaps 2025", "launch/release", _w("2025-12-03 06:00", "2025-12-04 06:00"),
     r"spotify|wrapped"),
    ("wc-2026-draw", "World Cup 2026 draw", "football", _w("2025-12-05 12:00", "2025-12-06 06:00"),
     r"world cup draw|\bdraw\b|sorteo|sorteio|tirage|auslosung|sorteggio|kennedy center|world cup 2026|mundial 2026|"
     r"copa do mundo 2026|heidi klum|scherzinger|rio ferdinand"),
    ("game-awards-2025", "The Game Awards 2025", "award/ceremony", _w("2025-12-11 20:00", "2025-12-12 08:00"),
     r"game awards|gang of dragon|forest 3|arc raiders"),
    ("st5-finale", "Stranger Things 5 finale", "launch/release", _w("2025-12-31 18:00", "2026-01-01 18:00"),
     r"stranger things"),
    ("grammys-2026", "Grammys 2026", "award/ceremony", _w("2026-02-01 18:00", "2026-02-02 08:00"), r"grammy"),
    ("olympics-2026-opening", "Winter Olympics 2026 opening ceremony", "award/ceremony",
     _w("2026-02-06 15:00", "2026-02-07 06:00"),
     r"olymp|olimp|opening ceremony|cerimonia|ceremonia|mameli|san siro|pausini|impacciatore|theron"),
    ("super-bowl-lx", "Super Bowl LX", "other sport", _w("2026-02-08 16:00", "2026-02-09 06:00"),
     r"super bowl|halftime|half-time|\bnfl\b|seahawks|patriots|green day|puth|ricky martin|bad bunny|national anthem"),
    ("olympics-2026-closing", "Winter Olympics 2026 closing ceremony", "award/ceremony",
     _w("2026-02-22 15:00", "2026-02-23 03:00"), r"olymp|olimp|closing ceremony|verona"),
    ("apple-2026-03", "Apple event, Mar 2026 (iPhone 17e)", "launch/release", _w("2026-03-02 06:00", "2026-03-03 06:00"),
     r"iphone|apple"),
    ("oscars-2026", "Oscars 2026", "award/ceremony", _w("2026-03-15 18:00", "2026-03-16 08:00"),
     r"oscar|academy award|in memoriam|best (picture|actor|actress|director|supporting)"),
    ("esc-2026-sf1", "Eurovision 2026, semi-final 1", "award/ceremony", _w("2026-05-12 12:00", "2026-05-13 03:00"),
     r"eurovision|\besc\b|eurovisi[oó]n"),
    ("esc-2026-sf2", "Eurovision 2026, semi-final 2", "award/ceremony", _w("2026-05-14 12:00", "2026-05-15 03:00"),
     r"eurovision|\besc\b|eurovisi[oó]n"),
    ("esc-2026-final", "Eurovision 2026 final", "award/ceremony", _w("2026-05-16 12:00", "2026-05-17 03:00"),
     r"eurovision|\besc\b|eurovisi[oó]n"),
]


# a hand-labelled scheduled moment joins a catalogue window only if its hand event type fits the event's category
HAND_TYPE_FITS = {"other": {"award/ceremony", "religious", "election/politics"},
                  "viral_celebrity": {"award/ceremony", "religious", "election/politics"},
                  "politics_conflict": {"election/politics"}, "launch": {"launch/release"},
                  "markets": set(), "sport": {"football", "other sport"}}


def assign_events(a, hand_scheduled_types=None):
    """a: build() output (with `text`). -> Series event_id per moment (catalogue id, 'm<moment_id>' for a moment
    that is its own unit, None for unassigned: holiday, or a non-sport moment of category 'other').
    hand_scheduled_types: {moment_id: hand event type} for moments hand-labelled scheduled. After the pattern pass,
    such a moment that starts inside a catalogue window joins that event even without the event's name in its text,
    if its hand type fits the event's category (HAND_TYPE_FITS; a sport moment only joins an event of its own sport
    category) and the sport / non-sport restriction allows it. First fitting window in catalogue order."""
    start = pd.to_datetime(a.date_utc, utc=True)
    ev = pd.Series(None, index=a.index, dtype=object)
    for eid, _n, cat, (lo, hi), rx in CATALOGUE:
        hit = ev.isna() & (start >= lo) & (start < hi) & a.text.str.contains(rx, case=False, regex=True)
        if cat not in ("football", "other sport"):     # ceremonies, elections, launches, religious: no sport moments
            hit &= ~a.is_sport.astype(bool)
        ev[hit] = eid
    ht = a.moment_id.map(hand_scheduled_types or {})
    for eid, _n, cat, (lo, hi), _rx in CATALOGUE:
        fits = ht.map(lambda x: isinstance(x, str) and cat in HAND_TYPE_FITS.get(x, set()))
        if cat in ("football", "other sport"):
            fits &= a.category.eq(cat)
        hit = ev.isna() & fits & (start >= lo) & (start < hi)
        if cat not in ("football", "other sport"):
            hit &= ~a.is_sport.astype(bool)
        ev[hit] = eid
    own = ev.isna() & ~a.category.isin(["holiday"]) & (a.is_sport | ~a.category.eq("other"))
    ev[own] = "m" + a.moment_id[own].astype(str)
    return ev


def event_units(a, rows_by_topic, groups=None):
    """One row per scheduled event (catalogue event or single-moment unit): members, category, window, event reach,
    within 60 min, minutes to half and the 10-minute curve (from the third country). groups: {event_id: accepted
    candidate topic_ids} from the appointments review, or None."""
    cat_of = {e[0]: e for e in CATALOGUE}
    out = []
    for eid, g in a[a.event_id.notna()].groupby("event_id", sort=False):
        g = g.sort_values("moment_reach", ascending=False)
        if eid in cat_of:
            _, name_, cat, (lo, hi), _ = cat_of[eid]
        else:
            r0 = g.iloc[0]
            name_, cat = r0["name"], r0["category"]
            lo, hi = EV.window(pd.Timestamp(r0["date_utc"].replace("Z", ""), tz="UTC"))
        topics = set(g.topic_id) | (groups or {}).get(eid, set())
        f = figures_window(rows_by_topic, topics, lo, hi)
        out.append({"event_id": eid, "event": name_, "category": cat, "is_catalogue": eid in cat_of,
                    "window_utc": [f"{lo:%Y-%m-%dT%H:%MZ}", f"{hi:%Y-%m-%dT%H:%MZ}"],
                    "members": g.moment_id.tolist(), "member_names": g["name"].tolist(), "topics": sorted(topics),
                    "is_sport": bool(g.is_sport.any()), "first_utc": g.date_utc.min(),
                    "largest_member": int(g.moment_id.iloc[0]), **f})
    return pd.DataFrame(out)


def figures_window(rows_by_topic, topic_ids, lo, hi):
    parts = [rows_by_topic[x] for x in topic_ids if x in rows_by_topic]
    first = pd.concat(parts) if parts else pd.DataFrame(columns=["country_code", "start_time_utc"])
    first = first[(first.start_time_utc >= lo) & (first.start_time_utc < hi)]
    first = first.groupby("country_code").start_time_utc.min().sort_values()
    if first.empty:
        return {"event_reach": 0, "event_reach_60": 0, "event_minutes_to_half": None, "curve": []}
    ref, mins = EV.from_third(first)
    return {"event_reach": int(len(first)), "event_reach_60": int((mins <= 60).sum()),
            "event_minutes_to_half": EV.half_minutes(mins), "reference_utc": f"{ref:%Y-%m-%dT%H:%MZ}",
            "curve": [[k, int((mins <= k).sum())] for k in range(0, CURVE_MIN + 1, CURVE_STEP)]}


def event_candidates(units, t, meta):
    """Event-group candidates for the chart events (same format and no-effect rule as events.candidates): topics
    trending in the event window whose name matches any member topic's name and that are not members."""
    junk = set(meta.index[meta.is_junk.astype(bool)]) if "is_junk" in meta else set()
    rows = []
    for u in units.itertuples():
        lo, hi = (pd.Timestamp(x) for x in u.window_utc)
        w = t[(t.start_time_utc >= lo) & (t.start_time_utc < hi)]
        mem = w[w.topic_id.isin(u.topics)]
        mem_cc = set(mem.country_code)
        ref = mem.start_time_utc.min() if len(mem) else lo
        mfirst = EV._first_minutes(mem, ref)
        seen = set()
        for tid, g in w[~w.topic_id.isin(u.topics) & ~w.topic_id.isin(junk)].groupby("topic_id"):
            mks = [EV.match_kind(meta.topic_name.get(x, x), meta["type"].get(x), meta.topic_name.get(tid, tid))
                   for x in u.topics]
            mk = next((x for x in mks if x), None)
            if not mk or tid in seen:
                continue
            seen.add(tid)
            cc = set(g.country_code)
            cf = EV._first_minutes(g, ref)
            earlier = [c for c, mn in cf.items() if c in mfirst and mn < mfirst[c]]
            can = bool(cc - mem_cc) or bool(earlier)
            rows.append({"event": u.event, "event_id": u.event_id, "event_category": u.category,
                         "event_countries_members": len(mem_cc), "candidate_topic_id": tid,
                         "candidate_topic": meta.topic_name.get(tid, tid), "match": mk,
                         "phrasings": "; ".join(g.query_raw.str.lower().value_counts().head(3).index),
                         "countries_in_window": len(cc), "countries_added": len(cc - mem_cc),
                         "added_countries": ", ".join(sorted(cc - mem_cc)), "earlier_countries": ", ".join(sorted(earlier)),
                         "can_change": can, "accept": "" if can else "no-effect",
                         "note": "surname only: check it is the same person" if mk == "surname only" else ""})
    d = pd.DataFrame(rows)
    if d.empty:
        return d
    order = {e: i for i, e in enumerate(units.event_id)}
    d["_o"] = d.event_id.map(order)
    return d.sort_values(["can_change", "_o", "countries_added"], ascending=[False, True, False]).drop(columns="_o")


def rejected_events(docs):
    """Event ids whose row in docs/appointment_chart_verification.csv is hand-labelled unscheduled: the whole event
    leaves Appointments (its labelled moment becomes a shock in step 4; its other members go with it)."""
    out = set()
    for stem in ("appointment_chart_verification", "appointment_chart_verification_2"):
        sp, kp = docs / f"{stem}.csv", docs / f"{stem}_key.csv"
        if not (sp.exists() and kp.exists()):
            continue
        d = pd.read_csv(sp, dtype=str, keep_default_na=False).merge(
            pd.read_csv(kp, dtype=str, keep_default_na=False)[["sample_id", "event_id"]], on="sample_id")
        out |= set(d.event_id[d.scheduled_label.str.strip().str.lower().eq("unscheduled")])
    return out
