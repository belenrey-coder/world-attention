"""Step 4: split each topic's trends into moments -> data/interim/moments.parquet.

A moment is one topic within one burst of attention (national feeds only), found in two passes:
  1. Sessions: per (topic, country), consecutive trends are one session unless the country went
     SESSION_GAP_HOURS without the topic trending. A country that trends a topic every day
     (ChatGPT, weather) therefore has one long session, which is its baseline.
  2. Bursts: per topic, session *starts* are sorted in time, and a new moment begins when the next
     session start is more than BURST_GAP_HOURS after the previous one. Countries whose session is
     already running are baseline, so they neither join nor chain the burst.
This catches spikes in always-on topics: on 11 Dec 2024 dozens of countries start a new "ChatGPT"
session within an hour, even though a few countries were already trending it.

Per moment: start (UTC), each country's first time, reach, minutes to half reach, peak volume bucket,
most common phrasing per country, and a global flag (>= GLOBAL_MIN_COUNTRIES countries had started
by GLOBAL_WINDOW_MIN minutes after the third country). The top 300 global moments go to
docs/GLOBAL_MOMENTS.md for review.

Also writes data/interim/topic_meta.parquet (one row per topic: name, type, qid), used by step 5.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from common import CACHE, DOCS, INTERIM, WORK, save_json  # noqa: E402
from kinds import (CONSTANT_MIN_MONTHS, SHOCK_MIN_CONF, SHOCK_PROMPT, WAVE_MIN_MONTHS, load_hand_labels,  # noqa: E402
                   load_shock_labels, moment_key, moment_kinds, shock_moments, topic_ritual, topic_summary_kind, wave_flags, wave_months)

SESSION_GAP_HOURS = 24
BURST_GAP_HOURS = 6
GLOBAL_MIN_COUNTRIES = 15
GLOBAL_WINDOW_MIN = 60
GLOBAL_REVIEW_N = 300


# Meteorological weather (not earthquakes, tsunamis or space weather). Matched as whole words in the topic
# name and the topic's most common normalized string (query_norm has no accents). Hand-reviewed: every
# topic matched only by an ambiguous word was read (Nov 2026) and the false-positive families became
# NOT_WEATHER_RE; one-off corrections go in docs/weather_overrides.csv.
WEATHER_EN = (r"weather|forecast|rain|rainfall|storm|thunderstorm|typhoon|hurricane|cyclone|tornado|cold front|"
              r"heat ?wave|heatwave|snow|snowfall|blizzard|hail|monsoon|tropical depression|tropical storm|"
              r"temperature|frost|fog|wind warning|weather warning|weather alert|met office|pagasa|imd|"
              r"meteorolog\w*|climate today")
WEATHER_LOCAL = (r"clima|pronostico del tiempo|tiempo en|previsao do tempo|tempo em|chuva|frente frio|lluvia|tormenta|"
                 r"wetter|unwetter|meteo|hava durumu|yagmur|pogoda|погода|cuaca|hujan|thoi tiet|"
                 r"mua da|co mua|mua lon|mua to|mua bao|mua mua|troi mua|gio mua|"
                 r"天気|天氣|天气|台風|颱風|날씨|태풍|طقس|الطقس|الأرصاد|آب و هوا|मौसम|बारिश|อากาศ|ฝน|"
                 r"vremea|vreme|pocasi|idojaras|καιρος|vejret|vaer|vader|saa|weer")
WEATHER_RE = rf"(?:^|\W)(?:{WEATHER_EN}|{WEATHER_LOCAL})(?:\W|$)"
_NOT = [
    # not meteorological
    r"earthquake|tsunami|volcano|climate change|geomagnetic|geomagnetica|магнитн|solar storm|tormenta solar|aurora",
    r"snow moon|full moon|bulan purnama|lluvia de estrellas|lluvia estrellas|chuva de estrelas|meteor|sao bang|"
    r"geminid|perseid|lirid|leonid|solar term|grain rain|frost's descent|霜降|穀雨|lluvia de aranas|lluvia de sapos",
    r"rain delay|fog of war|mental fog|^the fog$|hail to the chief|hail mary|rain man|purple rain|desert storm|"
    r"amazon rain ?forest|bolinho de chuva|chuva acida|mua do|aku tak membenci hujan|idgitaf",
    # people, teams, brands, titles
    r"(?:emma|adam|morgan|scott|maxwell|sadie|deshae|bryony|jenny|jo|kirk|ky|martin|phyllis) frost|frost bank|"
    r"arctic frost|frost game|frost relic|vaterchen frost|first frost",
    r"snow man|(?:dan|eric|david|gavin|mark|luna) snow|snow leopard|snow patrol|snow white|snowden|snow ice cream|"
    r"snow canyon|snow geese|snow sculpture|meitu ai snow|black snow|let it snow|snow gear|snow check|snow game",
    r"(?:toni|sue|johnny|hannah|tallia|martinho|yfke|nikola|kane bradley|zac lomax|dexter|kina) storm|storm reid|"
    r"(?:melbourne|guelph|seattle|manchester|red|nordic|goblin|onyx|cannibal|infinite|atlantean) storm|"
    r"storm (?:chasers|shadow|distillery|lake|ingebrigtsen|huntley|de beul)|into the storm|heroes of the storm|"
    r"dark storm team|stormloop|storm loop|fever storm|stormzy|storm(?:s|ers)? (?:vs|v|x) ",
    r"rain or shine|rain rave|(?:lizzy|sophie|bi) rain|rain (?:hannah|newton|epler|lohmus|laane)|rain 演唱會",
    r"tornado fc|toninho tornado|tony tornado|aeronautica militare tornado|kipas tornado",
    r"activision|turtle wow|diablo|blizzard beach|tyler blizzard",
    r"thea hail|tormenta de pasiones",
    r"survivor yagmur|yagmur (?:atacan|banda|taktas|sarnic|un)|ayni yagmur altinda|efecan",
    r"darth vader|wordt vader|vader noa|janssens vader|rigters vader|travis vader|daar gaan ze weer|weer verliefd",
    r"radno vreme|vreme smrti|saa (?:strike|pilots|ceo)|vs saa|lamola|salima saa|kuolema saa|imd vs",
    # forecasts of things other than weather
    r"^(?=.*(?:forecast|prognose|прогноз|預測))(?=.*(?:bitcoin|gold|dollar|currenc|exchange|gbp|\beur\b|property|"
    r"housing|dividend|inflation|petrol|fuel|diesel|stock|pension|election|wahl|курс|northern lights|air quality|"
    r"smoke|預測))",
    r"northern lights",
]
NOT_WEATHER_RE = "|".join(f"(?:{x})" for x in _NOT)
VS_ONLY_RE = r"\bvs\b"                       # fixtures, unless the string is about weather terms themselves
VS_WEATHER_OK = r"watch vs warning|sleet vs snow|weather"
WEATHER_OVERRIDES = DOCS / "weather_overrides.csv"

# Sport: Claude types sports_match / team, plus league and competition topics (whatever their type,
# except people, companies, products and places), matched on the topic name. Athletes are not sport here.
SPORT_TYPES = {"sports_match", "team"}
LEAGUE_RE = (r"\b(?:premier league|la ?liga|serie a|bundesliga|ligue 1|eredivisie|primeira liga|super lig|"
             r"liga mx|liga profesional|brasileirao|saudi pro league|mls|champions league|europa league|"
             r"conference league|nations league|copa (?:america|libertadores|sudamericana|del rey|do brasil|"
             r"del mundo)|fa cup|carabao cup|efl cup|club world cup|world cup|afcon|africa cup of nations|"
             r"euro 20\d\d|nba|wnba|nfl|nhl|mlb|ipl|big bash|super bowl|stanley cup|world series|"
             r"grand prix|formula 1|formula one|\bf1\b|motogp|wimbledon|roland garros|french open|us open|"
             r"australian open|tour de france|olympics?|six nations|ufc|wwe|ryder cup|march madness|"
             r"cricket|playoffs?|derby)\b")
NOT_SPORT_TYPES = {"person", "company", "product", "place"}


def add_sport(meta: pd.DataFrame) -> pd.DataFrame:
    league = meta.topic_name.fillna("").str.lower().str.contains(LEAGUE_RE, regex=True)
    meta["is_sport"] = meta["type"].isin(SPORT_TYPES) | (league & ~meta["type"].isin(NOT_SPORT_TYPES))
    return meta


def add_category(meta: pd.DataFrame, st: pd.DataFrame) -> pd.DataFrame:
    top_q = st.sort_values("n_rows", ascending=False).drop_duplicates("topic_id").set_index("topic_id").query_norm
    text = (meta.topic_name.fillna("") + " | " + meta.topic_id.map(top_q).fillna("")).str.lower()
    is_w = text.str.contains(WEATHER_RE, regex=True) & ~text.str.contains(NOT_WEATHER_RE, regex=True)
    is_w &= ~(text.str.contains(VS_ONLY_RE, regex=True) & ~text.str.contains(VS_WEATHER_OK, regex=True))
    is_w &= ~meta["type"].isin(["sports_match", "team", "person", "media", "company", "product"])
    if WEATHER_OVERRIDES.exists():
        ov = pd.read_csv(WEATHER_OVERRIDES, comment="#", dtype={"topic_id": str, "is_weather": int})
        for tid, flag in zip(ov.topic_id, ov.is_weather):
            is_w[meta.topic_id == tid] = bool(flag)
    meta["category"] = np.where(is_w, "weather", meta["type"])
    return meta


def add_moment_sport(m: pd.DataFrame, meta: pd.DataFrame) -> pd.DataFrame:
    """Moment-level sport (2026-11-16, DECISIONS.md Step 9): a global moment of a non-sport topic is sport when
    pipeline/sport.py finds an entity signal, sporting-event evidence in that moment and no override. is_sport_topic
    keeps the topic rule (it is also the fixtures list the moment rule checks dates against)."""
    from sport import sport_fix, sport_moments
    m["is_sport_topic"] = m.is_sport
    m["sport_evidence"] = None
    cand = m[m.is_global & ~m.is_sport].copy()
    cand["key"] = cand.index
    mi = meta.set_index("topic_id")
    ent = sport_fix(set(cand.topic_id), mi)
    mom = sport_moments(cand, mi, ent, moments=m[["topic_name", "start_utc", "is_sport_topic", "reach"]]).set_index("key")
    hit = mom.index[mom.sport_moment]
    m.loc[hit, "is_sport"] = True
    m.loc[hit, "sport_evidence"] = mom.loc[hit, "event_evidence"]
    print(f"moment-level sport: {len(hit):,} of {len(cand):,} global non-sport moments moved to sport")
    return m


# Junk topics (DECISIONS.md, Step 9 round 6): generic or empty-meaning names, left out everywhere downstream.
JUNK_WORDS = {
    # generic nouns people type into the search box
    "test", "video", "videos", "live", "live tv", "tv", "news", "noticias", "notícias", "nachrichten", "sport", "sports",
    "deportes", "esportes", "football", "futbol", "fútbol", "futebol", "radio", "time", "hora", "email", "mail", "film",
    "films", "movie", "movies", "game", "games", "juegos", "jogos", "music", "musica", "música", "score", "photos",
    "images", "online", "free", "download", "login", "home", "app", "apps", "today", "hoy", "hoje", "weather", "clima",
    "tiempo", "wetter", "meteo", "météo", "pogoda", "погода", "translate", "calculator", "calendar", "lyrics",
    # stopwords and question words
    "a", "an", "the", "of", "in", "on", "at", "to", "for", "and", "or", "is", "it", "what", "how", "why", "when",
    "where", "which", "ok", "yes", "we", "you", "me", "my", "de", "la", "el", "los", "las", "que", "y", "en", "un",
    "una", "do", "da", "na", "se", "por", "para", "com", "le", "les", "des", "du", "et", "der", "die", "das", "und"}


# real topics the junk rule would remove (topic_id). Rule: allow only topics that name one specific thing (a person,
# product, site or place), not generic tools or ambiguous words (DECISIONS.md, Step 9 rounds 7-8):
# BTS's V, Google Translate, Seek (job site), 444.hu (Hungarian news site), Åre (Swedish ski resort)
JUNK_ALLOW = {"V", "Translate", "seek", "444", "are"}


def junk_topics(mi: pd.DataFrame, ritual: pd.Series) -> pd.Series:
    """Reason a topic is junk, else None. Rules, in order:
      single character   the name is one character ("A", "e", "f")
      bare number        only digits ("2026", "0", "7")
      unknown            Claude named it "unknown" (and never anything else) and there is no Wikidata match
                         ("test", "live", "working", "what"); topics Claude was never asked to name are not junk
      generic word       the name (without a "[...]" language suffix) is in JUNK_WORDS, unless the topic is a ritual
                         (the generic "Weather" topics are rituals and stay)
    Real short topics are unaffected: "Iran", "Gemini", "X (Twitter)", "NBA", "CNN"."""
    st = pd.read_parquet(WORK / "string_topics.parquet", columns=["topic_id", "canonical_en"])
    named = set(st[st.canonical_en.notna() & (st.canonical_en.str.lower() != "unknown")].topic_id)
    unknown = set(st[st.canonical_en.str.lower().eq("unknown")].topic_id) - named
    n = mi.topic_name.astype(str).str.replace(r"\s*\[.*\]\s*$", "", regex=True).str.strip().str.lower()
    rit = ritual.reindex(mi.index).fillna(False).astype(bool)
    reason = pd.Series(None, index=mi.index, dtype=object)
    reason[n.isin(JUNK_WORDS) & ~rit] = "generic word"
    reason[mi.index.isin(unknown) & mi.qid.isna()] = "unknown"
    reason[n.str.fullmatch(r"\d+")] = "bare number"
    reason[n.str.len() <= 1] = "single character"
    reason[reason.index.isin(JUNK_ALLOW)] = None
    return reason


def sporty(mi: pd.DataFrame, m: pd.DataFrame, ids: set) -> pd.Series:
    """Athletes and other sport topics the topic rule misses (left out of is_wave), among `ids`: an entity signal
    of the sport rule (sport.sport_fix: Wikidata sport description, sport site or channel, competition name; for
    people and "other"-typed topics also sport related searches (Teams, Valencia, Madrid; not products or companies
    such as Max or Stake); for places, 3+ sport related searches: club cities and countries whose
    national team drives the searches, such as Valencia or Georgia), or most of the topic's global moments are sport
    (moment-level rule; Paris, Monaco)."""
    from sport import sport_fix
    ent = sport_fix(ids, mi).set_index("topic_id")
    sig = ent.reason.isin(["wikidata", "site", "competition name", "club place"]) | \
        (ent.reason.eq("related") & ent.index.to_series().map(mi["type"]).isin(["person", "other", "unlabeled"]))
    g = m[m.is_global]
    share = g.groupby("topic_id").is_sport.mean()
    by_moments = share[share >= 0.5].index
    out = pd.Series(False, index=mi.index)
    out[out.index.isin(set(sig.index[sig]) | set(by_moments))] = True
    return out


def add_shock(m: pd.DataFrame) -> pd.DataFrame:
    """is_shock: kinds.shock_moments with the cached step-9 Claude labels (cache/claude/shocks/labels.jsonl).
    Moments without a label are not shocks; run `make shocks-label2` for them (the count is in moments_summary)."""
    labels = load_shock_labels(CACHE / "claude" / "shocks" / "labels.jsonl")
    # the rule alone (Claude label, rule-based sport): kept as is_shock_rule for the step-9 estimate
    m["is_shock_rule"], m["shock_labelled"], m["claude_scheduled"] = shock_moments(m, labels)
    m["is_shock"] = m.is_shock_rule
    m["scheduled_final"] = m.claude_scheduled
    # hand labels (validation samples, chart verification sheets) override Claude and the sport rule
    hand = load_hand_labels(DOCS)
    # hand labels are recorded on every labelled moment (chart sheets can label a non-global member of a catalogue
    # event); the sport and shock overrides apply to global moments only
    hand_topics = {k.split("|")[0] for k in hand}
    keys = pd.Series([moment_key(a, b) if a in hand_topics else None for a, b in zip(m.topic_id, m.start_utc)],
                     index=m.index)
    hl = keys.map(lambda k: hand.get(k) if k else None)
    m["hand_scheduled"] = hl.map(lambda x: x[0] if x else None)
    m["hand_event_type"] = hl.map(lambda x: x[1] if x else None)
    hit = hl.notna() & m.is_global.astype(bool)
    m.loc[hit, "is_sport"] = m.loc[hit, "hand_event_type"].eq("sport")
    m.loc[hit, "is_shock"] = m.loc[hit, "hand_scheduled"].eq("unscheduled") & ~m.loc[hit, "is_sport"]
    m.loc[hit, "scheduled_final"] = m.loc[hit, "hand_scheduled"]
    m["is_shock"] = m.is_shock.astype(bool)
    print(f"hand-labelled moments: {int(hl.notna().sum())}, of which global {int(hit.sum())} (of {len(hand)} hand labels); shock moments: "
          f"{int(m.is_shock.sum()):,} (rule alone {int(m.is_shock_rule.sum()):,}); global non-sport moments without "
          f"a Claude label: {int((m.is_global & ~m.is_sport & ~m.shock_labelled & ~hit).sum()):,}")
    return m


def topic_meta() -> pd.DataFrame:
    """Topic name / type / intent / qid, each the row-weighted most common value among the topic's strings."""
    st = pd.read_parquet(WORK / "string_topics.parquet",
                         columns=["topic_id", "topic_name", "query_norm", "n_rows", "type", "intent", "qid", "confidence"])

    def mode(col):
        d = st[st[col].notna()].groupby(["topic_id", col]).n_rows.sum().reset_index()
        d = d.sort_values("n_rows", ascending=False).drop_duplicates("topic_id")
        return d.set_index("topic_id")[col]

    meta = st.groupby("topic_id").agg(topic_name=("topic_name", "first"), n_strings=("n_rows", "size"))
    for c in ("type", "intent", "qid"):
        meta[c] = mode(c)
    meta["type"] = meta["type"].fillna("unlabeled")
    return add_sport(add_category(meta.reset_index(), st))


def main():
    cols = ["topic_id", "topic_name", "country_code", "query_raw", "start_time_utc", "end_time_utc",
            "duration_minutes", "search_volume_lower", "level"]
    t = pd.read_parquet(INTERIM / "topics.parquet", columns=cols)
    t = t[t.level == "country"].drop(columns="level")
    t = t[t.topic_id.notna()]
    print(f"national rows: {len(t):,}; topics: {t.topic_id.nunique():,}")

    # end = end time, else start + duration (capped at 24 h), else start
    dur = pd.to_timedelta(t.duration_minutes.fillna(0).clip(upper=24 * 60), unit="m")
    end = t.end_time_utc.fillna(t.start_time_utc + dur)
    t["end"] = end.where(end >= t.start_time_utc, t.start_time_utc)

    # pass 1: sessions per (topic, country)
    t = t.sort_values(["topic_id", "country_code", "start_time_utc"], kind="stable").reset_index(drop=True)
    new_tc = t.topic_id.ne(t.topic_id.shift()) | t.country_code.ne(t.country_code.shift())
    tc_key = np.cumsum(new_tc.values)
    run_end = t["end"].astype("int64").groupby(tc_key).cummax()
    gap = t.start_time_utc.astype("int64") - run_end.shift()
    new_sess = new_tc | (gap > SESSION_GAP_HOURS * 3600 * 1e9)
    t["session"] = np.cumsum(new_sess.values) - 1
    ss = t.groupby("session").agg(topic_id=("topic_id", "first"), s_start=("start_time_utc", "min"))

    # pass 2: bursts of session starts per topic
    ss = ss.sort_values(["topic_id", "s_start"], kind="stable")
    new_topic = ss.topic_id.ne(ss.topic_id.shift())
    sgap = ss.s_start.astype("int64").diff()
    new_moment = new_topic | (sgap > BURST_GAP_HOURS * 3600 * 1e9)
    ss["moment_id"] = np.cumsum(new_moment.values) - 1
    t["moment_id"] = t.session.map(ss.moment_id)
    t = t.sort_values(["moment_id", "start_time_utc"], kind="stable").reset_index(drop=True)
    print(f"sessions: {len(ss):,}; moments: {t.moment_id.max() + 1:,}")

    # per (moment, country)
    mc = (t.groupby(["moment_id", "country_code"])
          .agg(first_utc=("start_time_utc", "min"), vol=("search_volume_lower", "max"), n=("query_raw", "size"))
          .reset_index())
    ph = (t.groupby(["moment_id", "country_code", "query_raw"]).size().reset_index(name="k")
          .sort_values(["moment_id", "country_code", "k"], ascending=[True, True, False])
          .drop_duplicates(["moment_id", "country_code"]))
    mc = mc.merge(ph[["moment_id", "country_code", "query_raw"]], on=["moment_id", "country_code"], how="left")
    mc = mc.sort_values(["moment_id", "first_utc"]).reset_index(drop=True)
    mc["rank"] = mc.groupby("moment_id").cumcount()

    m = (t.groupby("moment_id")
         .agg(topic_id=("topic_id", "first"), topic_name=("topic_name", "first"),
              start_utc=("start_time_utc", "min"), end_utc=("end", "max"),
              peak_volume=("search_volume_lower", "max"), n_trends=("query_raw", "size")))
    m["reach"] = mc.groupby("moment_id").size()

    start_ns = m.start_utc.astype("int64")
    mins = (mc.first_utc.astype("int64").values - start_ns.loc[mc.moment_id].values) / 6e10
    mc["min_from_start"] = np.round(mins).astype(int)

    # minutes to half reach: time at which ceil(reach/2) countries had started
    half_k = np.ceil(m.reach / 2).astype(int) - 1
    key = mc.set_index(["moment_id", "rank"]).min_from_start
    m["minutes_to_half"] = key.reindex(list(zip(m.index, half_k))).values

    # global: countries started by (third country's first time + window)
    third = mc[mc["rank"] == 2].set_index("moment_id").min_from_start
    mc["third"] = mc.moment_id.map(third)
    in_win = mc[mc.third.notna() & (mc.min_from_start <= mc.third + GLOBAL_WINDOW_MIN)]
    m["reach_60"] = in_win.groupby("moment_id").size().reindex(m.index).fillna(0).astype(int)
    m["is_global"] = m.reach_60 >= GLOBAL_MIN_COUNTRIES

    # nested per-country list: country, first_utc, minutes from start, peak volume, phrasing
    # mc is sorted by moment_id, so each moment is one contiguous slice
    recs = [{"country_code": c, "first_utc": f, "min_from_start": int(x), "peak_volume": float(v), "phrasing": p}
            for c, f, x, v, p in zip(mc.country_code, mc.first_utc, mc.min_from_start, mc.vol, mc.query_raw)]
    bounds = np.cumsum(m.reach.values)
    m["countries"] = [recs[a:b] for a, b in zip(np.r_[0, bounds[:-1]], bounds)]

    meta = topic_meta()
    m = m.reset_index().merge(meta[["topic_id", "type", "category", "intent", "qid", "is_sport"]], on="topic_id", how="left")
    m["is_sport"] = m.is_sport.fillna(False).astype(bool)
    m = add_moment_sport(m, meta)
    m = add_shock(m)
    mi = meta.set_index("topic_id")
    rit = topic_ritual(mi, m)
    m["kind"] = moment_kinds(m, set(rit.index[rit]))
    meta["kind"] = meta.topic_id.map(topic_summary_kind(m)).fillna("other")
    months = wave_months(t)
    meta["wave_months"] = meta.topic_id.map(months).fillna(0).astype(int)
    ath = sporty(mi, m, set(months.index[months >= WAVE_MIN_MONTHS]))
    meta["is_athlete"] = meta.topic_id.map(ath).fillna(False).astype(bool)
    junk = junk_topics(mi, rit)
    meta["junk_reason"] = meta.topic_id.map(junk)
    meta["is_junk"] = meta.junk_reason.notna()
    is_wave, is_const = wave_flags(mi, months, rit, ath)
    is_wave &= junk.reindex(is_wave.index).isna()
    is_const &= junk.reindex(is_const.index).isna()
    meta["is_wave"] = meta.topic_id.map(is_wave).fillna(False).astype(bool)
    meta["is_constant"] = meta.topic_id.map(is_const).fillna(False).astype(bool)
    m["is_wave"] = m.topic_id.map(meta.set_index("topic_id").is_wave).fillna(False).astype(bool)
    # which moment each national trend row belongs to (step 8 gives rows their moment's kind)
    t[["topic_id", "country_code", "start_time_utc", "moment_id"]].drop_duplicates(
        ["topic_id", "country_code", "start_time_utc"]).to_parquet(WORK / "row_moments.parquet", index=False)
    m["duration_h"] = ((m.end_utc - m.start_utc).dt.total_seconds() / 3600).round(1)
    m.to_parquet(INTERIM / "moments.parquet", index=False)
    meta.to_parquet(INTERIM / "topic_meta.parquet", index=False)

    g = m[m.is_global].sort_values(["reach_60", "reach"], ascending=False)
    summary = {
        "national_rows": int(len(t)), "topics": int(t.topic_id.nunique()), "moments": int(len(m)),
        "moments_reach_ge_2": int((m.reach >= 2).sum()), "moments_reach_ge_10": int((m.reach >= 10).sum()),
        "global_moments": int(len(g)), "session_gap_hours": SESSION_GAP_HOURS, "burst_gap_hours": BURST_GAP_HOURS,
        "sessions": int(len(ss)),
        "global_moments_sport": int(g.is_sport.sum()),
        "global_moments_non_sport": int((~g.is_sport).sum()),
        "sport_rule": "topic: Claude type sports_match/team, or a league/competition name (LEAGUE_RE); "
                      "global moments: also the moment-level rule in pipeline/sport.py",
        "global_moments_sport_topic_rule": int(g.is_sport_topic.sum()),
        "global_moments_sport_moment_rule_added": int((g.is_sport & ~g.is_sport_topic).sum()),
        "shock_rule": f"global non-sport moment, Claude {SHOCK_PROMPT} unscheduled with confidence >= {SHOCK_MIN_CONF}",
        "shock_moments": int(g.is_shock.sum()),
        "shock_moments_rule_alone": int(g.is_shock_rule.sum()),
        "hand_labelled_global_moments": int(g.hand_scheduled.notna().sum()),
        "moment_kinds": m.kind.value_counts().to_dict(),
        "global_moment_kinds": g.kind.value_counts().to_dict(),
        "topic_summary_kinds": meta.kind.value_counts().to_dict(),
        "wave_rule": f"topic in 15+ countries in >= {WAVE_MIN_MONTHS} separate UTC months; not a sport topic, "
                     "athlete or ritual",
        "wave_topics": int(meta.is_wave.sum()),
        "constant_rule": f"topic in 15+ countries in >= {CONSTANT_MIN_MONTHS} UTC months (any topic)",
        "constant_topics": int(meta.is_constant.sum()),
        "wave_and_constant_topics": int((meta.is_wave & meta.is_constant).sum()),
        "junk_topics": meta.junk_reason.value_counts().to_dict(),
        "global_non_sport_without_claude_label": int((~g.is_sport & ~g.shock_labelled).sum()),
        "reach_100_in_60min": {"all": int((m.reach_60 >= 100).sum()), "sport": int(((m.reach_60 >= 100) & m.is_sport).sum()),
                               "non_sport": int(((m.reach_60 >= 100) & ~m.is_sport).sum())},
        "moments_longer_than_7d": int(((m.end_utc - m.start_utc).dt.days >= 7).sum()),
        "global_rule": f">= {GLOBAL_MIN_COUNTRIES} countries started by {GLOBAL_WINDOW_MIN} min after the 3rd",
        "topics_with_multiple_moments": int((m.groupby("topic_id").size() > 1).sum()),
    }
    save_json(WORK / "moments_summary.json", summary)
    print(summary)

    write_review(g, "GLOBAL_MOMENTS.md", "Global moments (top 300 for review)", "")
    write_review(g[~g.is_sport], "GLOBAL_MOMENTS_NO_SPORT.md", "Global moments without sport (top 300 for review)",
                 "Sport excluded (`is_sport`: Claude type sports_match or team, or a league/competition topic; for "
                 "global moments also the moment-level rule in `pipeline/sport.py`: athletes on match days). ")



def write_review(g, fname, title, note):
    L = [f"# {title}\n",
         f"_Generated by `pipeline/04_moments.py`. A moment is global if ≥ {GLOBAL_MIN_COUNTRIES} national feeds "
         f"had it trending within {GLOBAL_WINDOW_MIN} min after the third country started. {note}Sorted by countries in "
         f"that window, then total reach. {len(g):,} moments in this list "
         f"({int((g.reach_60 >= 100).sum())} reach 100+ countries within 60 min)._\n",
         "Review: is it one real event? is the name right? are unrelated things merged in?\n",
         "| # | topic | type | sport | start (UTC) | reach in 60 min | total reach | min to half | first 3 countries | phrasings |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for i, r in enumerate(g.head(GLOBAL_REVIEW_N).itertuples(), 1):
        cs = r.countries
        first3 = ", ".join(f"{c['country_code']} +{c['min_from_start']}m" for c in cs[:3])
        phr = []
        for c in cs:
            if c["phrasing"] and c["phrasing"].lower() not in [p.lower() for p in phr]:
                phr.append(c["phrasing"])
            if len(phr) == 4:
                break
        name = str(r.topic_name).replace("|", "/")
        L.append(f"| {i} | {name} | {r.type} | {'yes' if r.is_sport else ''} | {r.start_utc:%Y-%m-%d %H:%M} | "
                 f"{r.reach_60} | {r.reach} | {int(r.minutes_to_half)} | {first3} | {'; '.join(phr).replace('|', '/')} |")
    (DOCS / fname).write_text("\n".join(L) + "\n")
    print(f"wrote {DOCS / fname}")


if __name__ == "__main__":
    main()
