"""Proposed fix for the is_sport leak (2026-11-13; not yet used by 04_moments.py, see DECISIONS.md Step 9).

The current rule (04_moments.add_sport) marks sport by Claude type (sports_match, team) and league /
competition names, so athletes (typed "person"), sport sites and sport channels leak into "non-sport".
A topic is sport under the fix if any of:
  1. wikidata:  its Wikidata description names a sport role or body (tennis player, footballer, cricketer,
                racing driver, football club, sports competition, ...);
  2. site:      its name is a sport site, app or channel (Yalla Shoot, Livescore, Flashscore, ESPN, beIN Sports, ...);
     competition name: its name ends like a tournament ("Cincinnati Open", "... Masters", "... Trophy", "... Cup");
  3. related:   >= RELATED_MIN (people: RELATED_MIN_PERSON) of its top 10 Google related searches are fixtures
                ("x vs y", any language) or sport terms (live score, atp, wta, highlights, ...); never for places.
"""
import re

import pandas as pd

from common import WORK

SPORT_DESC_RE = re.compile(
    r"tennis player|footballer|football player|association football|soccer player|cricketer|racing driver|"
    r"formula one driver|basketball player|baseball player|ice hockey player|american football player|"
    r"\bboxer\b|mixed martial artist|cyclist|golfer|swimmer|athlete|sprinter|runner\b|rugby|volleyball|handball|"
    r"figure skater|skier|\bwrestler\b|darts player|snooker player|motorcycle racer|jockey|weightlifter|gymnast|"
    r"fencer|rower|referee|ice dancer|speed skater|ski jumper|snowboarder|biathlete|luger|bobsledder|curler|football manager|football coach|head coach|sports team|football club|sports club|"
    r"basketball team|cricket team|sports competition|sports season|sports league|tournament|olympic", re.I)
SPORT_SITE_RE = re.compile(
    r"yalla ?shoot|yalla ?kora|kora ?live|\blivescore|live ?score|flashscore|sofascore|fotmob|\bespn|cricbuzz|"
    r"totalsportek|\bmarca\b|gazzetta dello sport|bein sports|\bdazn\b|sky sports|tnt sports|365scores|onefootball|"
    r"goal\.com|\btudn\b|tyc sports|\bole\b|kooora|^sports?$|sport tv|sportv|eurosport|fubo|streameast|vipleague|"
    r"tarjeta roja|roja directa|rojadirecta|pirlo ?tv|futbol libre|fútbol libre|marca ?tv",
    re.I)
SPORT_TERM_RE = re.compile(
    r"\b(live score|livescore|atp|wta|grand slam|highlights|lineups?|standings|fixtures|"
    r"goals?|match|partido|jogo|maç|مباراة|матч|ipl|odi|t20|test match|f1|grand prix|qualifying|"
    r"cup|copa|league|liga|serie a|bundesliga|ligue 1|premier league|champions league|nba|nfl|ufc)\b", re.I)
COMPETITION_NAME_RE = re.compile(r"\b(open|masters|trophy|championships?|grand prix|cup)( \d{4})?$|\btour de\b|"
                                 r"^(coppa|copa|coupe|taça|taca|pokal|supercopa|supercoppa|supercup)\b|"
                                 r"\bpokal\b|^major league\b|\b(league|liga|ligue|lig|serie [ab]|bundesliga)$|primera divisi[oó]n|"
                                 r"\bfriendl(y|ies)\b", re.I)
RELATED_MIN = 3
RELATED_MIN_PERSON = 2       # people: 2 sport related searches are enough (an athlete's are mostly fixtures)
NO_RELATED_TYPES = {"place"}  # a country's related searches can be full of its team's fixtures: never by "related"
PLACE_RELATED_MIN = 3         # ... but a place with >= 3 sport related searches is a candidate "club place" (Paris,
                              # Monaco); its moments then need a fixture of a club named after the place (sport_moments)
NGRAM_MAX = 4


def sport_entities(term, ath, own_qid=None, own_tok=()):
    """QIDs of athletes / clubs / competitions named in a search (any 1-4 word n-gram that is itself a search whose
    Wikidata item has a sport description), leaving out the topic's own item and n-grams sharing its name tokens."""
    w = term.split()
    out = {}
    for n in range(1, min(NGRAM_MAX, len(w)) + 1):
        for i in range(len(w) - n + 1):
            g = " ".join(w[i:i + n])
            q = ath.get(g)
            if q and q != own_qid and len(g) >= 4 and not ({x[:5] for x in _tokens(g)} & set(own_tok)):
                out.setdefault(q, g)
    return out


def _tokens(x):
    return [y for y in re.findall(r"[a-z]+", unidecode(str(x)).lower()) if len(y) >= 4]


def sport_fix(topic_ids, meta):
    """-> DataFrame(topic_id, sport_fix, reason) for the given topics."""
    from recall import raw_match_key
    ids = set(topic_ids)
    wd = pd.read_parquet(WORK / "wikidata_qids.parquet").drop_duplicates("qid").set_index("qid")
    st = pd.read_parquet(WORK / "string_topics.parquet", columns=["sid", "topic_id", "n_rows"])
    st = st[st.topic_id.isin(ids)]
    rel = pd.read_parquet(WORK / "strings.parquet", columns=["sid", "related_top"]).merge(st, on="sid")
    top_rel = {}
    for tid, g in rel.groupby("topic_id"):
        w = {}
        for terms, n in zip(g.related_top, g.n_rows):
            for r in terms:
                w[r] = w.get(r, 0) + n
        top_rel[tid] = [x for x, _ in sorted(w.items(), key=lambda kv: -kv[1])[:10]]
    ath = athlete_strings()
    rows = []
    for tid in ids:
        name = str(meta.topic_name.get(tid, tid))
        q = meta.qid.get(tid)
        desc = wd.wd_desc.get(q) if isinstance(q, str) and q in wd.index else None
        rl = top_rel.get(tid, [])
        # a place's own name is part of its clubs' names ("paris saint germain"): keep those n-grams for places
        own_tok = set() if meta["type"].get(tid) in NO_RELATED_TYPES else {x[:5] for x in _tokens(name)}
        ents = [sport_entities(r.lower(), ath, q, own_tok) for r in rl]
        rel_ents = {k: v for e in ents for k, v in e.items()}
        # a related search counts if it is a fixture, has a sport term, or names another athlete / club / competition
        n_rel = sum(1 for r, e in zip(rl, ents) if raw_match_key(r) is not None or SPORT_TERM_RE.search(r) or e)
        if isinstance(desc, str) and SPORT_DESC_RE.search(desc):
            reason = "wikidata"
        elif SPORT_SITE_RE.search(name):
            reason = "site"
        elif COMPETITION_NAME_RE.search(name):
            reason = "competition name"
        elif meta["type"].get(tid) not in NO_RELATED_TYPES and \
                n_rel >= (RELATED_MIN_PERSON if meta["type"].get(tid) == "person" else RELATED_MIN):
            reason = "related"
        elif meta["type"].get(tid) in NO_RELATED_TYPES and n_rel >= PLACE_RELATED_MIN:
            reason = "club place"
        else:
            reason = None
        rows.append({"topic_id": tid, "sport_fix": reason is not None, "reason": reason, "wikidata_desc": desc,
                     "related_sport_terms": n_rel,
                     "related_entities": rel_ents})
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ moment-level rule (2026-11-13, v2)
# Sport must describe the MOMENT, not the person. A moment is sport if its topic has an entity signal (sport_fix
# above), the moment looks like a sporting event, and no applicable override fires. "Moment-level" = the topic's
# national trend rows inside the moment (start_utc .. end_utc): their raw searches ("phrasings", together with the
# moment's per-country phrasings) and their own Google related searches ("related").
#
# Overrides (DECISIONS.md, Step 9):
#  - ALWAYS: death; health emergencies (collapse, cardiac, hospital, coma); accidents outside play (car/plane/road
#    words); crime (arrest, police, charged, sentenced); outage; announcements (fired, transfer, departure, contract):
#    these make the moment non-sport even on a match day.
#  - IN_PLAY: injury, doping / suspension / ban, an accident/crash with no vehicle word, and "retired/retirement"
#    (in tennis, a player retiring hurt mid-match). A surprise DURING a scheduled sporting event is sport, so these
#    are lifted when the moment has fixture or competition evidence; otherwise they still make it non-sport.
#  - An override word counts only if it is in the moment's phrasings or in >= 2 of its related searches.
from unidecode import unidecode

from sport_calendar import event_on, sport_of

EVENT_RE = re.compile(
    r"\b(vs\.?|contra|contro|gegen|mot|lwn|score|scores|livescore|result|results|resultado|resultados|"
    r"marcador|placar|live|en vivo|en directo|ao vivo|diretta|canli|stream|streaming|highlights|resumen|melhores momentos|"
    r"gol|goal|goals|golazo|lineup|lineups|alineacion|alineaciones|escalacao|formazione|prediction|pronostico|h2h|"
    r"standings|tabla|classifica|final|finale|semifinal|semi final|quarterfinal|cuartos|round|ronda|set|tiebreak|"
    r"match|partido|jogo|partita|spiel|maç|مباراة|ضد|مقابل|матч|против|срещу|game \d|race|qualifying|clasificacion|"
    r"podium|wins|won|beat|beats|defeat|draw|debut|hat-?trick|record)\b", re.I)
ALWAYS_RE = re.compile(
    r"\b(died|dies|dead|death|rip|r\.i\.p|passed away|obituary|funeral|cause of death|murio|murió|muere|fallece|"
    r"fallecio|falleció|morre|morreu|faleceu|falecimento|est mort|décès|deces|meurt|gestorben|stirbt|è morto|morto|"
    r"muore|öldü|vefat|wafat|meninggal|умер|скончался|погиб|توفي|وفاة|"
    r"collapse|collapsed|colapso|desmaio|desmayo|malore|cardiac|heart attack|infarto|paro cardiaco|hospital|"
    r"hospitalized|hospitalizado|internado|coma|illness|cancer|câncer|"
    r"car crash|car accident|plane crash|road accident|traffic accident|accidente de transito|accidente de tráfico|"
    r"acidente de carro|accident de voiture|autounfall|"
    r"arrest|arrested|detenido|detido|preso|prison|jail|police|policia|charged|sentenced|abuse|assault|"
    r"outage|caido|caído|fora do ar|not working|"
    r"fired|sacked|despedido|destituido|leaves|leaving|departure|farewell|despedida|"
    r"transfer|traspaso|fichaje|signs|signing|contract|contrato|renewal|renueva|"
    r"appointed|new coach|nuevo entrenador|novo treinador|announce|announces|anuncia|going|next club|new club|"
    r"joins|joining|unveiled|presentacion|presentación|apresentacao|apresentação)\b", re.I)
IN_PLAY_RE = re.compile(
    r"\b(injury|injured|lesion|lesión|lesao|lesão|verletzung|infortunio|blessure|doping|suspended|suspension|banned|"
    r"ban|accident|accidente|acidente|crash|crashed|chute|caduta|sturz|"
    r"retire|retires|retired|retirement|se retira|abandona|ritiro|aposentadoria)\b", re.I)
# competition named in the moment's own searches (counts as competition evidence, like a fixture)
COMP_TERM_RE = re.compile(
    r"\b(atp|wta|grand slam|wimbledon|roland garros|\w+ open|masters|olympi\w*|olimpiad\w*|world cup|mundial|"
    r"champions league|europa league|conference league|premier league|la ?liga|serie a|bundesliga|ligue 1|"
    r"copa del rey|copa america|libertadores|nba|nfl|nhl|mlb|ipl|t20|grand prix|formula 1|\bf1\b|motogp|"
    r"tour de france|giro|vuelta|ufc|nations league|super bowl|playoffs?|euro 20\d\d|club world cup|"
    r"copa|coupe|coppa|pokal|campeonato|torneo|torneio|mundial de clubes|copa do mundo|"
    r"كاس|كأس|دوري|بطولة|مونديال|кубок|чемпионат|лига|турнир|олимпиад\w*|olimpiyat|şampiyonlar|jo 20\d\d|jeux olympiques|"
    r"giochi olimpici|milano cortina)\b", re.I)
SUPPORT_MIN_RELATED = 2
FIXTURE_BEFORE_H = 12      # a fixture counts as "that day" if it started up to 12 h before the athlete's moment ...
FIXTURE_AFTER_H = 3        # ... or up to 3 h after it (pre-match lineups)
TEAMMATES_MIN = 2          # >= 2 other athletes named in the moment's searches, during a fixture window
WOMEN_RE = re.compile(r"\b(women|womens|femenino|feminino|femminile|frauen|feminine|féminine|ladies|wsl|nwsl|w)\b", re.I)
TEAM_DROP_WORDS = {"fc", "cf", "afc", "sc", "ac", "cd", "fk", "sk", "club", "cp", "the", "de", "national", "football",
                   "team", "men", "s", "under", "u21", "u23", "u20", "u19", "u17", "association", "calcio", "sv", "bk",
                   "if", "sk", "rc", "us", "as", "ss", "ssc", "afc", "basketball", "baseball", "hockey"}


def _hit(rx, phrasings, related):
    """First override word found in the phrasings, or in >= SUPPORT_MIN_RELATED distinct related searches."""
    for x in phrasings:
        mm = rx.search(x)
        if mm:
            return mm.group(0)
    hits = [rx.search(x).group(0) for x in related if rx.search(x)]
    return hits[0] if len(set(r for r in related if rx.search(r))) >= SUPPORT_MIN_RELATED else None


def _translit_words(terms):
    """Words of the moment's searches, plus their Latin transliteration (Cyrillic, Arabic, Greek ...)."""
    out = set()
    for term in terms:
        for w in term.split():
            if len(w) >= 4 and not w.isdigit():
                out.add(w)
                lat = unidecode(w).lower().replace("'", "")
                if len(lat) >= 4:
                    out.add(lat)
    return out


KEY_STOP = {"live", "news", "today", "women", "womens", "final", "finals", "league", "match", "game", "games", "open",
            "round", "stage", "group", "world", "championship", "championships", "season", "2024", "2025", "2026",
            "results", "result", "score", "highlights", "semifinal", "quarterfinal", "qualifying", "race", "grand", "prix",
            "real", "united", "city", "sporting", "athletic", "atletico", "inter", "olympic", "olympics", "winter",
            "summer", "national", "under", "south", "north", "east", "west", "central", "saint", "port", "new",
            "royal", "nova", "nuevo", "nueva", "santa", "santo", "sao",
            # generic words in club names ("Sport Club Internacional", "Società Sportiva", "Racing Club")
            "sport", "sports", "sportiva", "sportivo", "sportclub", "societa", "sociedad", "deportivo", "deportiva",
            "club", "clube", "racing", "union", "unione", "associazione", "olympique", "futbol", "futebol",
            "koninklijke", "vereniging", "football", "soccer", "basket"}


def _team_keys(names):
    """Distinctive tokens of team names ('FC Bayern Munich' -> {'bayern', 'munich'})."""
    keys = set()
    for n in names:
        for w in re.findall(r"[a-z0-9]+", unidecode(str(n)).lower()):
            if len(w) >= 4 and w not in TEAM_DROP_WORDS and w not in KEY_STOP:
                keys.add(w)
    return keys


def athlete_strings():
    """{search (query_norm): QID} for searches whose Wikidata item has a sport-role description."""
    wd = pd.read_parquet(WORK / "wikidata_qids.parquet")
    wd = wd[wd.wd_desc.fillna("").str.contains(SPORT_DESC_RE)]
    return dict(zip(wd.query_norm, wd.qid))


def athlete_teams(topic_ids, meta):
    """({topic_id: team keys}, {topic_id: plays for a women's team}) from Wikidata P54 (member of sports team)."""
    from wikidata import get_entities, get_p54
    q_of = {tid: meta.qid.get(tid) for tid in topic_ids if isinstance(meta.qid.get(tid), str)}
    p54 = get_p54(set(q_of.values()))
    teams = sorted({x for v in p54.values() for x in v})
    ents = get_entities(teams) if teams else {}
    names = {q: [v["value"] for v in (e.get("labels") or {}).values()] for q, e in ents.items() if not e.get("missing")}
    keys = {tid: _team_keys([n for tq in p54.get(q, []) for n in names.get(tq, [])]) for tid, q in q_of.items()}
    women = {tid: any(WOMEN_RE.search(n) for tq in p54.get(q, []) for n in names.get(tq, [])[:3]) for tid, q in q_of.items()}
    return keys, women


NON_SPORT_ROLE_RE = re.compile(
    r"\b(actor|actress|singer|model|influencer|presenter|television host|tv host|youtuber|rapper|musician|"
    r"politician|journalist|businessperson|businessman|businesswoman|socialite|television personality|"
    r"tv personality|comedian|writer|film director)\b", re.I)
CLUB_DESC_RE = re.compile(r"football club|sports club|sports team|basketball team|national .*team|club\b", re.I)


def related_clubs(rel_ents, wdd, labels, p54):
    """Club keys from the topic's related entities: clubs named directly (their Wikidata label), plus clubs that
    >= TEAMMATES_MIN of the co-trending athletes have played for (Wikidata P54), for a topic with no own item."""
    keys = _team_keys(labels.get(q, g) for q, g in rel_ents.items() if CLUB_DESC_RE.search(str(wdd.get(q) or "")))
    from collections import Counter
    c = Counter(t for q in rel_ents for t in set(p54.get(q, [])))
    shared = [t for t, n in c.items() if n >= TEAMMATES_MIN]
    return keys | _team_keys(labels.get(t, "") for t in shared)


def _mates_sport(mates, wdd):
    """Sport of the co-trending athletes (most common calendar sport among their descriptions), for an athlete
    whose own Wikidata description is missing or wrong (Medvedev matched to no item)."""
    from collections import Counter
    c = Counter(x for x in (sport_of(wdd.get(q)) for q in mates) if x)
    return c.most_common(1)[0][0] if c and c.most_common(1)[0][1] >= TEAMMATES_MIN else None


def sport_moments(cand, meta, entity, moments=None):
    """cand: candidate moments (topic_id, key, start_utc, end_utc, countries); entity: sport_fix() output;
    moments: all moments with the topic-level is_sport flag (the fixtures list); read from disk if None.
    -> DataFrame(key, entity_reason, event_evidence, override, override_kind, sport_moment, moment_text_sample)."""
    from recall import raw_match_key
    ent = entity.set_index("topic_id")
    c = cand[cand.topic_id.map(ent.sport_fix).fillna(False).astype(bool)]
    rows = pd.read_parquet(WORK.parent / "topics.parquet", columns=["topic_id", "level", "start_time_utc", "query_raw", "related"],
                           filters=[("topic_id", "in", sorted(set(c.topic_id)))])
    rows = rows[rows.level == "country"]
    by_t = {k: g for k, g in rows.groupby("topic_id")}
    m_all = moments if moments is not None else \
        pd.read_parquet(WORK.parent / "moments.parquet", columns=["topic_name", "start_utc", "is_sport", "reach"])
    flag = m_all["is_sport_topic"] if "is_sport_topic" in m_all else m_all["is_sport"]
    sm = m_all[flag.astype(bool) & (m_all.reach >= 3)]
    # every sport moment counts as a competition (fixtures, and events such as an Olympic downhill), indexed by day
    fixtures_by_day = {}
    for n_, s_ in zip(sm.topic_name.astype(str), sm.start_utc):
        fixtures_by_day.setdefault(s_.floor("D"), []).append((n_, _team_keys([n_]), s_, bool(WOMEN_RE.search(n_))))
    athletes = athlete_strings()
    wdd = pd.read_parquet(WORK / "wikidata_qids.parquet").drop_duplicates("qid").set_index("qid").wd_desc
    teams, women_team = athlete_teams(set(c[c.topic_id.map(meta["type"]).eq("person")].topic_id), meta)
    # related-entity identity: labels of the entities and P54 clubs of the related athletes
    from wikidata import get_entities, get_p54
    rq = sorted({q for tid in set(c.topic_id) for q in (ent.related_entities.get(tid) or {})})
    rp54 = get_p54(set(rq)) if rq else {}
    lq = sorted(set(rq) | {t for v in rp54.values() for t in v})
    le = get_entities(lq) if lq else {}
    labels = {q: ((e.get("labels") or {}).get("en") or {}).get("value", "") for q, e in le.items() if not e.get("missing")}
    out = []
    for r in c.itertuples():
        g = by_t.get(r.topic_id)
        lo, hi = r.start_utc, max(r.end_utc, r.start_utc + pd.Timedelta(hours=1))
        w = g[(g.start_time_utc >= lo) & (g.start_time_utc <= hi)] if g is not None else None
        phr = [cc["phrasing"].lower() for cc in r.countries if cc["phrasing"]]
        rel = []
        if w is not None and len(w):
            phr += list(w.query_raw.str.lower())
            rel = [x.lower() for lst in w.related for x in (lst if lst is not None else [])]
        phr, rel = list(dict.fromkeys(phr)), [x for x in dict.fromkeys(rel) if x not in set(phr)]
        terms = phr + rel
        # sporting-event evidence
        ev, competition = None, False
        fixture = next((x for x in terms if raw_match_key(x) is not None), None)
        own_tok = {x[:5] for x in _tokens(r.topic_name)}
        own_q = meta.qid.get(r.topic_id)
        mates = list(dict.fromkeys(q_ for x in terms for q_ in sport_entities(x, athletes, own_q, own_tok)))
        # topic-level identity (like Wikidata P54): athletes / clubs named in the topic's related searches give the
        # sport (for the calendar) and the clubs (for the fixture date check) when Wikidata has no or a wrong item
        rel_ents = ent.related_entities.get(r.topic_id) or {}
        if NON_SPORT_ROLE_RE.search(str(ent.wikidata_desc.get(r.topic_id) or "")):
            rel_ents = {}       # an actress whose related searches name her partner's teammates is not an athlete
        if ent.reason.get(r.topic_id) == "club place":
            # a place (Paris, Monaco) is sport only on the day of a fixture of a club named after it
            place = set(_tokens(r.topic_name))
            d0 = r.start_utc.floor("D")
            lo_f, hi_f = r.start_utc - pd.Timedelta(hours=FIXTURE_BEFORE_H), r.start_utc + pd.Timedelta(hours=FIXTURE_AFTER_H)
            near = [fx for k in (-1, 0, 1) for fx in fixtures_by_day.get(d0 + pd.Timedelta(days=k), [])
                    if lo_f <= fx[2] <= hi_f and place & fx[1]]
            fx_t = next((x for x in terms if raw_match_key(x) is not None and place & set(_tokens(x))), None)
            if fx_t:
                ev, competition = f"fixture: {fx_t}", True
            elif near:
                ev, competition = f"competition date (club named after the place): {near[0][0]}", True
        elif fixture:
            ev, competition = f"fixture: {fixture}", True
        elif ent.reason.get(r.topic_id) in ("site", "competition name"):
            ev, competition = "competition/site topic", True
        elif (meta["type"].get(r.topic_id) == "person" and (cal := event_on(
                sport_of(ent.wikidata_desc.get(r.topic_id)) or _mates_sport(list(rel_ents), wdd), r.start_utc.date()))):
            # individual sports: inside a major event window of the athlete's sport (pipeline/sport_calendar.py)
            ev, competition = f"calendar: {cal}", True
        elif any(COMP_TERM_RE.search(x) for x in terms):
            ev, competition = f"competition in searches: {next(COMP_TERM_RE.search(x).group(0) for x in terms if COMP_TERM_RE.search(x))}", True
        else:
            d0 = r.start_utc.floor("D")
            lo_f, hi_f = r.start_utc - pd.Timedelta(hours=FIXTURE_BEFORE_H), r.start_utc + pd.Timedelta(hours=FIXTURE_AFTER_H)
            near = [fx for k in (-1, 0, 1) for fx in fixtures_by_day.get(d0 + pd.Timedelta(days=k), [])
                    if lo_f <= fx[2] <= hi_f and (not fx[3] or women_team.get(r.topic_id, False))]
            words = _translit_words(terms) - set(str(r.topic_name).lower().split())
            sur = [x for x in re.findall(r"[a-z]+", unidecode(str(r.topic_name)).lower()) if len(x) >= 4]
            club = teams.get(r.topic_id, set()) | related_clubs(rel_ents, wdd, labels, rp54)
            hit = None
            for name_, keys, _s, _w in near:
                if club & keys:
                    hit = f"competition date (club, Wikidata P54): {name_}"
                elif sur and sur[-1] in keys:
                    hit = f"competition date (surname): {name_}"
                elif keys & {x for x in words if x.isascii()} or any(k_[:5] == x[:5] for k_ in keys if len(k_) >= 5
                                                                     for x in words if x.isascii() and len(x) >= 5):
                    hit = f"competition date (team in searches): {name_}"
                if hit:
                    break
            if not hit and near and len(mates) >= TEAMMATES_MIN:
                hit = f"competition date (co-trending athletes: {len(mates)} others): {near[0][0]}"
            if hit:
                ev, competition = hit, True
            elif EVENT_RE.search(" | ".join(terms)):
                ev = f"event word: {EVENT_RE.search(' | '.join(terms)).group(0)}"
        # overrides
        ov_always = _hit(ALWAYS_RE, phr, rel)
        ov_play = _hit(IN_PLAY_RE, phr, rel)
        if ov_always:
            ov, kind = ov_always, "always"
        elif ov_play and not competition:
            ov, kind = ov_play, "in-play word without competition evidence"
        else:
            ov, kind = None, ("in-play word lifted (competition day)" if ov_play else None)
        out.append({"key": r.key, "entity_reason": ent.reason.get(r.topic_id), "event_evidence": ev,
                    "override": ov, "override_kind": kind, "sport_moment": bool(ev) and not ov,
                    "moment_text_sample": " | ".join(terms)[:300]})
    return pd.DataFrame(out)
