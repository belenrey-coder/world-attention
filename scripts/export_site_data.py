"""Build the site's aggregated data (site/public/data/*.json) from the pipeline outputs.

    .venv/bin/python scripts/export_site_data.py            # every chapter built so far
    .venv/bin/python scripts/export_site_data.py opening    # one file

Reads data/export/ (steps 5 and 8) and data/interim/country_timezones.json. Writes only small, aggregated JSON:
no API keys, samples, verification or review files, shocks.json, CSV or parquet (docs/SPEC.md, "Data"). Every file
carries `source` and `as_of`.
"""
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pycountry

ROOT = Path(__file__).resolve().parents[1]
EXPORT = ROOT / "data" / "export"
STORY = EXPORT / "story"
INTERIM = ROOT / "data" / "interim"
OUT = ROOT / "site" / "public" / "data"

SOURCE = ("GoogleTrendArchive: Google Trends 'Trending Now' national feeds for 125 countries, collected every "
          "10 minutes, Nov. 27, 2024 to May 17, 2026. Topics merged by the world-attention pipeline.")
# files the site must never publish, whatever a builder below asks for
FORBIDDEN = ("shocks.json", "_review", "verification", "validation", "sample", ".csv", ".parquet")


def load(p):
    return json.loads(Path(p).read_text())


def as_of():
    cov = load(EXPORT / "coverage.json")
    return cov["days"][-1]


def write(name, obj):
    if any(f in name for f in FORBIDDEN):
        raise SystemExit(f"refusing to write {name}: not publishable")
    obj = {"source": obj.pop("source", SOURCE), "as_of": as_of(), **obj}
    p = OUT / name
    p.parent.mkdir(parents=True, exist_ok=True)
    b = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode()
    p.write_bytes(b)
    print(f"  {name}: {len(b) / 1024:.1f} kB")


# ---------------------------------------------------------------- countries (shared lookup)
def countries():
    """125 countries: ISO alpha-2, ISO numeric (the world-atlas feature id), name, time zone, a city for that zone."""
    cz = load(INTERIM / "country_timezones.json")
    names = {c["country_code"]: c["country_name"] for c in load(STORY / "wrapped" / "index.json")["countries"]}
    rows = []
    for c, tz in sorted(cz.items()):
        p = pycountry.countries.get(alpha_2=c)
        rows.append({"iso2": c, "id": p.numeric, "name": names.get(c, p.name), "tz": tz,
                     "city": tz.split("/")[-1].replace("_", " ")})
    return rows


def build_countries():
    write("countries.json", {"note": "The 125 countries in the archive. id = ISO 3166 numeric, the feature id in "
                                     "world-atlas countries-50m. tz = the one time zone used for each national feed "
                                     "(United States: America/Chicago, Canada: America/Toronto, Russia: "
                                     "Europe/Moscow); city = that zone's city.",
                             "countries": countries()})


# ---------------------------------------------------------------- Chapter 0: opening
OPEN_BINS = ["07:50", "08:00", "08:10", "08:20", "08:30", "08:40", "08:50"]


def _clock(dt):
    """'5:00 a.m.' / '5 p.m.' style, as the article writes times."""
    h, mnt = dt.hour, dt.minute
    ap = "a.m." if h < 12 else "p.m."
    h12 = h % 12 or 12
    return f"{h12}:{mnt:02d} {ap}"


# Local time in the Opening = the capital's time zone on that date (docs/SPEC.md, Chapter 0, check 2). Google's feeds
# are national, so the data has no city; every country gets its capital. Same zone as the feed's for every country
# except the United States (feed: America/Chicago; capital: Washington, America/New_York) and Ukraine (feed zone
# Europe/Simferopol, same offset on Apr. 21, 2025; capital: Kyiv).
CAPITALS = {
    "AE": ("Abu Dhabi", "Asia/Dubai"), "AL": ("Tirana", "Europe/Tirane"), "AM": ("Yerevan", "Asia/Yerevan"),
    "AO": ("Luanda", "Africa/Luanda"), "AR": ("Buenos Aires", "America/Argentina/Buenos_Aires"),
    "AT": ("Vienna", "Europe/Vienna"), "AU": ("Canberra", "Australia/Sydney"), "AZ": ("Baku", "Asia/Baku"),
    "BA": ("Sarajevo", "Europe/Sarajevo"), "BD": ("Dhaka", "Asia/Dhaka"), "BE": ("Brussels", "Europe/Brussels"),
    "BF": ("Ouagadougou", "Africa/Ouagadougou"), "BG": ("Sofia", "Europe/Sofia"), "BH": ("Manama", "Asia/Bahrain"),
    "BJ": ("Porto-Novo", "Africa/Porto-Novo"), "BO": ("La Paz", "America/La_Paz"), "BR": ("Brasília", "America/Sao_Paulo"),
    "BY": ("Minsk", "Europe/Minsk"), "CA": ("Ottawa", "America/Toronto"), "CD": ("Kinshasa", "Africa/Kinshasa"),
    "CH": ("Bern", "Europe/Zurich"), "CI": ("Yamoussoukro", "Africa/Abidjan"), "CL": ("Santiago", "America/Santiago"),
    "CM": ("Yaoundé", "Africa/Douala"), "CO": ("Bogotá", "America/Bogota"), "CR": ("San José", "America/Costa_Rica"),
    "CU": ("Havana", "America/Havana"), "CY": ("Nicosia", "Asia/Nicosia"), "CZ": ("Prague", "Europe/Prague"),
    "DE": ("Berlin", "Europe/Berlin"), "DK": ("Copenhagen", "Europe/Copenhagen"),
    "DO": ("Santo Domingo", "America/Santo_Domingo"), "DZ": ("Algiers", "Africa/Algiers"),
    "EC": ("Quito", "America/Guayaquil"), "EE": ("Tallinn", "Europe/Tallinn"), "EG": ("Cairo", "Africa/Cairo"),
    "ES": ("Madrid", "Europe/Madrid"), "ET": ("Addis Ababa", "Africa/Addis_Ababa"), "FI": ("Helsinki", "Europe/Helsinki"),
    "FR": ("Paris", "Europe/Paris"), "GB": ("London", "Europe/London"), "GE": ("Tbilisi", "Asia/Tbilisi"),
    "GH": ("Accra", "Africa/Accra"), "GR": ("Athens", "Europe/Athens"), "GT": ("Guatemala City", "America/Guatemala"),
    "HK": ("Hong Kong", "Asia/Hong_Kong"), "HN": ("Tegucigalpa", "America/Tegucigalpa"), "HR": ("Zagreb", "Europe/Zagreb"),
    "HT": ("Port-au-Prince", "America/Port-au-Prince"), "HU": ("Budapest", "Europe/Budapest"),
    "ID": ("Jakarta", "Asia/Jakarta"), "IE": ("Dublin", "Europe/Dublin"), "IL": ("Jerusalem", "Asia/Jerusalem"),
    "IN": ("New Delhi", "Asia/Kolkata"), "IQ": ("Baghdad", "Asia/Baghdad"), "IR": ("Tehran", "Asia/Tehran"),
    "IT": ("Rome", "Europe/Rome"), "JM": ("Kingston", "America/Jamaica"), "JO": ("Amman", "Asia/Amman"),
    "JP": ("Tokyo", "Asia/Tokyo"), "KE": ("Nairobi", "Africa/Nairobi"), "KG": ("Bishkek", "Asia/Bishkek"),
    "KH": ("Phnom Penh", "Asia/Phnom_Penh"), "KR": ("Seoul", "Asia/Seoul"), "KW": ("Kuwait City", "Asia/Kuwait"),
    "KZ": ("Astana", "Asia/Almaty"), "LB": ("Beirut", "Asia/Beirut"), "LK": ("Colombo", "Asia/Colombo"),
    "LT": ("Vilnius", "Europe/Vilnius"), "LV": ("Riga", "Europe/Riga"), "LY": ("Tripoli", "Africa/Tripoli"),
    "MA": ("Rabat", "Africa/Casablanca"), "MD": ("Chișinău", "Europe/Chisinau"), "MK": ("Skopje", "Europe/Skopje"),
    "ML": ("Bamako", "Africa/Bamako"), "MM": ("Naypyidaw", "Asia/Yangon"), "MX": ("Mexico City", "America/Mexico_City"),
    "MY": ("Kuala Lumpur", "Asia/Kuala_Lumpur"), "MZ": ("Maputo", "Africa/Maputo"), "NG": ("Abuja", "Africa/Lagos"),
    "NI": ("Managua", "America/Managua"), "NL": ("Amsterdam", "Europe/Amsterdam"), "NO": ("Oslo", "Europe/Oslo"),
    "NP": ("Kathmandu", "Asia/Kathmandu"), "NZ": ("Wellington", "Pacific/Auckland"), "OM": ("Muscat", "Asia/Muscat"),
    "PA": ("Panama City", "America/Panama"), "PE": ("Lima", "America/Lima"), "PH": ("Manila", "Asia/Manila"),
    "PK": ("Islamabad", "Asia/Karachi"), "PL": ("Warsaw", "Europe/Warsaw"), "PR": ("San Juan", "America/Puerto_Rico"),
    "PS": ("Ramallah", "Asia/Hebron"), "PT": ("Lisbon", "Europe/Lisbon"), "PY": ("Asunción", "America/Asuncion"),
    "QA": ("Doha", "Asia/Qatar"), "RO": ("Bucharest", "Europe/Bucharest"), "RS": ("Belgrade", "Europe/Belgrade"),
    "RU": ("Moscow", "Europe/Moscow"), "SA": ("Riyadh", "Asia/Riyadh"), "SE": ("Stockholm", "Europe/Stockholm"),
    "SG": ("Singapore", "Asia/Singapore"), "SI": ("Ljubljana", "Europe/Ljubljana"), "SK": ("Bratislava", "Europe/Bratislava"),
    "SN": ("Dakar", "Africa/Dakar"), "SV": ("San Salvador", "America/El_Salvador"), "SY": ("Damascus", "Asia/Damascus"),
    "TH": ("Bangkok", "Asia/Bangkok"), "TM": ("Ashgabat", "Asia/Ashgabat"), "TN": ("Tunis", "Africa/Tunis"),
    "TR": ("Ankara", "Europe/Istanbul"), "TT": ("Port of Spain", "America/Port_of_Spain"), "TW": ("Taipei", "Asia/Taipei"),
    "TZ": ("Dodoma", "Africa/Dar_es_Salaam"), "UA": ("Kyiv", "Europe/Kyiv"), "UG": ("Kampala", "Africa/Kampala"),
    "US": ("Washington", "America/New_York"), "UY": ("Montevideo", "America/Montevideo"), "UZ": ("Tashkent", "Asia/Tashkent"),
    "VE": ("Caracas", "America/Caracas"), "VN": ("Hanoi", "Asia/Ho_Chi_Minh"), "YE": ("Sanaa", "Asia/Aden"),
    "ZA": ("Pretoria", "Africa/Johannesburg"), "ZM": ("Lusaka", "Africa/Lusaka"), "ZW": ("Harare", "Africa/Harare"),
}

# "Searched as" = a trend title exactly as it appeared in the country's own feed at its first-trending refresh
# (docs/SPEC.md, Chapter 0, check 1). Candidates: the merged topic's titles at that refresh, plus these titles from
# the same refresh that name him or "the pope" but were not merged into the topic (checked by hand, Nov. 26, 2026).
# Left out on purpose: "vaticano", "vatican news", "pap" (a Polish news agency), other popes (ratzinger, wojtyla),
# "jd vance pope" and "pope easter sunday" (the day before). The archive stores titles in lower case.
OPEN_EXTRA_TITLES = {
    "SE": ["påve franciskus"], "RU": ["папа римский"], "PT": ["papa"], "NL": ["paus", "paus overleden"],
    "KR": ["교황"], "BE": ["pape", "paus"], "HR": ["papa"], "VN": ["giáo hoàng francis"],
    "IT": ["papa francesco pasqua"], "AT": ["papst"], "JP": ["ローマ教皇"], "PL": ["papiez", "папа римский"],
    "CH": ["papst"], "CZ": ["papež"], "LV": ["папа римский"], "BA": ["papa"], "IL": ["папа римский"],
    "MD": ["papa de la roma"],
}


# Languages, for ordering "Searched as": local-language titles first (docs/SPEC.md, Chapter 0, decided Nov. 26).
# TITLE_LANGS = the languages a title can be written in (ISO 639-1); COUNTRY_LANGS = official languages (plus French
# in Algeria and Tunisia and English in Sri Lanka, where they are the working languages of the press).
TITLE_LANGS = {
    "ferenc pápa": "hu", "frases del papa francisco": "es", "giáo hoàng francis": "vi", "mort du pape": "fr",
    "murio el papa": "es", "papa morreu": "pt", "papa": "es pt it hr bs sr ro sq tr", "papa de la roma": "ro", "papa francesco": "it",
    "papa francesco pasqua": "it", "papa francis": "tr", "papa francisc": "ro", "papa francisco": "es pt",
    "pape": "fr", "pape françois": "fr", "papež": "cs sl", "papež františek": "cs", "papež frančišek": "sl",
    "papiez": "pl", "papież franciszek": "pl", "papst": "de", "papst franziskus": "de", "papst tot": "de",
    "papá francisco": "es", "paus": "nl id", "paus fransiskus": "id", "paus overleden": "nl", "pave frans": "da no",
    "pope died": "en", "pope francis": "en", "pope francis death": "en", "påve franciskus": "sv",
    "vaticano papa francisco": "es", "παπασ φραγκισκοσ": "el", "папа римский": "ru", "папа римский умер": "ru",
    "папа римский франциск": "ru", "папа франциск": "ru bg", "البابا فرنسيس": "ar", "پاپ فرانسیس": "fa",
    "ローマ教皇": "ja", "교황": "ko", "папа римський": "uk", "pope": "en", "教宗": "zh",
}
COUNTRY_LANGS = {
    "AE": "ar", "AL": "sq", "AM": "hy", "AO": "pt", "AR": "es", "AT": "de", "AU": "en", "AZ": "az", "BA": "bs hr sr",
    "BD": "bn", "BE": "nl fr de", "BF": "fr", "BG": "bg", "BH": "ar", "BJ": "fr", "BO": "es", "BR": "pt", "BY": "be ru",
    "CA": "en fr", "CD": "fr", "CH": "de fr it", "CI": "fr", "CL": "es", "CM": "fr en", "CO": "es", "CR": "es",
    "CU": "es", "CY": "el tr", "CZ": "cs", "DE": "de", "DK": "da", "DO": "es", "DZ": "ar fr", "EC": "es", "EE": "et",
    "EG": "ar", "ES": "es", "ET": "am", "FI": "fi sv", "FR": "fr", "GB": "en", "GE": "ka", "GH": "en", "GR": "el",
    "GT": "es", "HK": "zh en", "HN": "es", "HR": "hr", "HT": "fr", "HU": "hu", "ID": "id", "IE": "en", "IL": "he ar",
    "IN": "hi en", "IQ": "ar", "IR": "fa", "IT": "it", "JM": "en", "JO": "ar", "JP": "ja", "KE": "en sw", "KG": "ky ru",
    "KH": "km", "KR": "ko", "KW": "ar", "KZ": "kk ru", "LB": "ar", "LK": "si ta en", "LT": "lt", "LV": "lv", "LY": "ar",
    "MA": "ar", "MD": "ro", "MK": "mk sq", "ML": "fr", "MM": "my", "MX": "es", "MY": "ms", "MZ": "pt", "NG": "en",
    "NI": "es", "NL": "nl", "NO": "no", "NP": "ne", "NZ": "en", "OM": "ar", "PA": "es", "PE": "es", "PH": "fil en",
    "PK": "ur en", "PL": "pl", "PR": "es en", "PS": "ar", "PT": "pt", "PY": "es", "QA": "ar", "RO": "ro", "RS": "sr",
    "RU": "ru", "SA": "ar", "SE": "sv", "SG": "en ms zh ta", "SI": "sl", "SK": "sk", "SN": "fr", "SV": "es", "SY": "ar",
    "TH": "th", "TM": "tk", "TN": "ar fr", "TR": "tr", "TT": "en", "TW": "zh", "TZ": "sw en", "UA": "uk", "UG": "en sw",
    "US": "en", "UY": "es", "UZ": "uz", "VE": "es", "VN": "vi", "YE": "ar", "ZA": "en", "ZM": "en", "ZW": "en",
}


def _is_local(title, country):
    return bool(set(TITLE_LANGS.get(title, "").split()) & set(COUNTRY_LANGS.get(country, "").split()))


def _pope_titles(o, first_utc):
    """Per country: every candidate title at its first-trending refresh, ranked: local-language titles first, then by
    search volume (ties: longer on the list, then alphabetical). The archive keeps no feed order."""
    import pandas as pd
    lo, hi = (pd.Timestamp(x.replace("Z", ""), tz="UTC") for x in o["window_utc"])
    t = pd.read_parquet(INTERIM / "topics.parquet", columns=["topic_id", "country_code", "level", "start_time_utc",
                                                             "query_raw", "search_volume_lower", "duration_minutes"],
                        filters=[("level", "==", "country"), ("start_time_utc", ">=", lo), ("start_time_utc", "<", hi)])
    t["q"] = t.query_raw.astype(str).str.strip()
    out = {}
    for c, ts in first_utc.items():
        g = t[(t.country_code == c) & (t.start_time_utc == pd.Timestamp(ts.replace("Z", ""), tz="UTC"))]
        g = g[g.topic_id.isin(o["topics"]) | g.q.isin(OPEN_EXTRA_TITLES.get(c, []))]
        g = g.assign(merged=g.topic_id.isin(o["topics"]), vol=g.search_volume_lower.fillna(0),
                     dur=g.duration_minutes.fillna(0))
        g = g.assign(local=[_is_local(q, c) for q in g.q])
        g = g.sort_values(["local", "vol", "dur", "q"], ascending=[False, False, False, True]).drop_duplicates("q")
        out[c] = [{"title": q, "volume": int(v), "minutes_listed": int(d), "merged": bool(m), "local": bool(lc)}
                  for q, v, d, m, lc in zip(g.q, g.vol, g.dur, g.merged, g.local)]
    return out


def build_opening():
    o = load(STORY / "opening.json")
    first = {r["country_code"]: r for r in o["by_country"]}
    titles = _pope_titles(o, {c: r["first_trend_utc"] for c, r in first.items()})
    t0 = datetime.fromisoformat(o["first_trend_utc"].replace("Z", "+00:00"))
    rows = []
    for c in countries():
        r = first.get(c["iso2"])
        city, tz = CAPITALS[c["iso2"]]
        row = {"iso2": c["iso2"], "name": c["name"], "trending": r is not None, "city": city}
        if r:
            ts = datetime.fromisoformat(r["first_trend_utc"].replace("Z", "+00:00"))
            hm = ts.strftime("%H:%M")
            loc = ts.astimezone(ZoneInfo(tz))
            label = hm if ts.date() == t0.date() else f"{ts:%b} {ts.day}, {hm}"
            tl = titles.get(c["iso2"], [])
            row.update({"first_utc": r["first_trend_utc"], "refresh": label,
                        "bin": OPEN_BINS.index(hm) if hm in OPEN_BINS else len(OPEN_BINS),
                        "minutes_after_first": int((ts - t0).total_seconds() // 60),
                        "local_time": loc.strftime("%Y-%m-%dT%H:%M%z"), "local_clock": _clock(loc),
                        "local_day_offset": (loc.date() - ts.date()).days,
                        "searched_as": [x["title"] for x in tl[:3]]})
        rows.append(row)
    rows.sort(key=lambda x: (not x["trending"], x.get("minutes_after_first", 0), x["name"]))
    bins = OPEN_BINS + ["Later"]
    per_bin = [sum(1 for x in rows if x.get("bin") == i) for i in range(len(bins))]
    cum = [sum(per_bin[:i + 1]) for i in range(len(OPEN_BINS))]
    write("opening.json", {
        "note": "Death of Pope Francis, Apr. 21, 2025 (announced just before the 07:50 UTC refresh). One row per country (125): the 10-minute "
                "refresh in which the merged topic first appeared on its national trending list, minutes after the "
                "first refresh (07:50 UTC), local time in the capital's time zone on that date (city = the capital), "
                "and searched_as = up to 3 Pope titles as they trended in that country's feed at that refresh (lower "
                "case in the archive), local-language titles first, then by searches. bin = index into "
                "bins (07:50 ... 08:50, then 'Later' for 09:00 to 24 h after). Countries in the same refresh tie "
                "(10-minute collection).",
        "event": "Death of Pope Francis", "date": "2025-04-21",
        "first_refresh_utc": o["first_trend_utc"], "bins": bins, "per_bin": per_bin,
        "cumulative_by_bin": cum, "countries_24h": o["countries"], "within_60_min": o["within_60_min"],
        "minutes_to_half": o["minutes_to_half"],
        "takeaway": "Within 10 minutes, more than half of the countries were searching for Pope Francis.",
        "rows": rows})
    return titles


# ---------------------------------------------------------------- Chapter 1: most searches never leave home
LOCAL_SAMPLE = {"1": 300, "2-14": 70, "15+": 16}        # words per pile (phones show the first 150 / 40 / 16)
LOCAL_NAMED = {"1": ["clima mendoza", "journal de quebec"], "2-14": ["Viaplay", "Fajr (dawn prayer)"],
               "15+": ["Q450675", "Real Madrid CF"]}
LOCAL_SEED = 7
LOCAL_NAMED_NOTE = {"clima mendoza": "weather in one Argentine city", "journal de quebec": "a Canadian newspaper",
                    "Viaplay": "a streaming service", "Fajr (dawn prayer)": "the time of the dawn prayer",
                    "Q450675": "the Pope, over 18 months", "Real Madrid CF": "the football club"}


def _pipeline_visibility(t, meta):
    """Hidden and Wrapped-skip topics, by the pipeline's own rule (05_export.visibility)."""
    import importlib.util
    sys.path.insert(0, str(ROOT / "pipeline"))
    spec = importlib.util.spec_from_file_location("export05", ROOT / "pipeline" / "05_export.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    hidden, skip, _ = mod.visibility(t, meta)
    return hidden, skip


def build_local():
    import random
    import pandas as pd
    import unicodedata
    loc = load(STORY / "local.json")
    groups = {g["group"]: g for g in loc["groups"]}
    meta = pd.read_parquet(INTERIM / "topic_meta.parquet").set_index("topic_id")
    t = pd.read_parquet(INTERIM / "topics.parquet", columns=["topic_id", "country_code", "level", "query_raw"])
    t = t[(t.level == "country") & t.topic_id.notna()]
    hidden, skip = _pipeline_visibility(t, meta)
    junk = set(meta.index[meta.is_junk.astype(bool)])
    t = t[~t.topic_id.isin(junk)]
    reach = t.groupby("topic_id").country_code.nunique()
    n_tr = t.groupby("topic_id").size()
    names = {c["iso2"]: c["name"] for c in countries()}
    grp = pd.cut(reach, [0, 1, 14, 10_000], labels=["1", "2-14", "15+"]).astype(str)
    fold = lambda x: "".join(ch for ch in unicodedata.normalize("NFKD", str(x).lower())
                             if not unicodedata.combining(ch)).strip()
    nm = meta.topic_name
    ok = (~reach.index.isin(hidden | skip)) & nm.reindex(reach.index).notna().values & (n_tr.reindex(reach.index) >= 3).values
    typ = meta["type"].reindex(reach.index).fillna("unlabeled")
    # no people in the 1 and 2-14 piles: low-reach names may be private individuals
    ok &= ~((typ == "person") & (grp != "15+")).values
    cand = reach.index[ok]
    rng = random.Random(LOCAL_SEED)
    words = []
    by_name = {str(v).lower(): k_ for k_, v in nm.items() if k_ in reach.index}
    for g_, k in LOCAL_SAMPLE.items():
        pool = sorted(cand[(grp.reindex(cand) == g_).values])
        # named examples by topic id or by Claude's name
        named = [x if x in reach.index else by_name.get(x.lower()) for x in LOCAL_NAMED[g_]]
        named = [x for x in named if x is not None]
        note_of = dict(zip(named, [LOCAL_NAMED_NOTE[k_] for k_ in LOCAL_NAMED[g_]
                                   if (k_ if k_ in reach.index else by_name.get(k_.lower())) is not None]))
        pick = named + rng.sample([x for x in pool if x not in named], k - len(named))
        sub = t[t.topic_id.isin(pick)]
        top_q = sub.assign(q=sub.query_raw.astype(str).str.strip().str.lower()).groupby("topic_id").q \
            .agg(lambda s: s.value_counts().index[0])
        ccs = sub.groupby("topic_id").country_code.agg(lambda s: sorted(set(s)))
        for x in pick:
            q = top_q[x]
            if len(q) > 30:
                q = q[:29] + "…"
            en = nm.get(x)
            words.append({"text": q, "translation": en if fold(en) != fold(top_q[x]) else None, "pile": g_,
                          "countries": int(reach[x]),
                          "country_names": [names.get(c, c) for c in ccs[x]][:12],
                          "named": x in named, "note": note_of.get(x)})
    piles = [{"group": g_, "label": {"1": "never left one country", "2-14": "reached 2 to 14 countries",
                                     "15+": "reached 15 or more"}[g_],
              "topics": groups[g_]["topics"], "share": groups[g_]["topic_share"]} for g_ in ("1", "2-14", "15+")]
    write("local.json", {
        "note": "Topics by the number of countries whose national feed ever had them trending (Nov. 2024 to May "
                "2026). words = a fixed random sample of real searches per pile (the most common phrasing of each "
                "topic, with Claude's English name as translation when it differs), plus two named examples per "
                "pile. Hidden topics, junk topics and people reaching fewer than 15 countries are left out; each "
                "sampled topic trended at least 3 times. Not one word per topic: piles are scaled by share.",
        "total_topics": int(sum(p_["topics"] for p_ in piles)), "piles": piles,
        "takeaway": f"{piles[0]['share']:.1%} of trending topics never left one country.",
        "words": words})


# ---------------------------------------------------------------- Chapter 2: shocks
SHOCK_TYPES = ["death", "outage", "politics or conflict", "other"]


def build_shocks():
    """The 60 chart shocks (shocks.json chart_top60, hand-verified), aggregated: name, type, date, event reach, within
    1 hour, minutes to half, a 10-minute curve for 3 hours timed from the third country, and each country's minutes
    from the first trend (for the replay on the opening map). Reads shocks.json locally; does not publish it."""
    import re
    import pandas as pd
    sys.path.insert(0, str(ROOT / "pipeline"))
    import events as EV
    from common import DOCS
    s = load(STORY / "shocks.json")
    byid = {m["moment_id"]: m for m in s["moments"]}
    chart = [byid[i] for i in s["chart_top60"]["moment_ids"]]
    groups = EV.load_groups(DOCS) or {}
    meta = pd.read_parquet(INTERIM / "topic_meta.parquet").set_index("topic_id")
    junk = set(meta.index[meta.is_junk.astype(bool)])
    t = pd.read_parquet(INTERIM / "topics.parquet", columns=["topic_id", "country_code", "level", "start_time_utc"])
    t = t[(t.level == "country") & t.topic_id.notna() & ~t.topic_id.isin(junk)]
    rows = []
    for m in chart:
        grp = {m["topic_id"]} | groups.get(m["moment_id"], set())
        start = pd.Timestamp(m["date_utc"].replace("Z", ""), tz="UTC")
        em = EV.metrics(t, grp, start)
        first = em["first"]
        mins = em["minutes"]
        typ = m["kind"] if m["kind"] in ("death", "outage") else (
            "politics or conflict" if m.get("sub_kind") == "politics or conflict" else "other")
        name = m["name"]
        label = f"{name} down" if typ == "outage" and not re.search(r"down|outage", name, re.I) else name
        t0 = first.iloc[0]
        rows.append({
            "id": m["moment_id"], "name": name, "label": label, "type": typ,
            "date": f"{t0:%Y-%m-%d}", "first_utc": f"{t0:%Y-%m-%dT%H:%MZ}",
            "third_utc": f"{em['reference_utc']:%Y-%m-%dT%H:%MZ}",
            "countries_24h": em["event_reach"], "within_1h": em["event_reach_60"],
            "minutes_to_half": em["event_minutes_to_half"],
            "curve": [int((mins <= k).sum()) for k in range(0, 181, 10)],
            "map": [[c, int((ts - t0).total_seconds() // 60)] for c, ts in first.items()],
        })
    rows.sort(key=lambda r: (-r["countries_24h"], -r["within_1h"]))
    counts = {k: sum(r["type"] == k for r in rows) for k in SHOCK_TYPES}
    write("shocks_chart.json", {
        "note": "The 60 widest shocks (unscheduled global moments, each checked by hand), at event level: the main "
                "topic plus topics accepted as the same event, from 2 hours before the moment to 24 hours after. "
                "curve = countries trending every 10 minutes for 3 hours (0, 10, ... 180), timed from the third "
                "country's first trend; countries_24h = all countries in the window. map = [country, minutes after "
                "the first country]. type: death and outage from the pipeline's keyword rule and hand labels; "
                "politics or conflict and other from the sub-kind rule.",
        "types": SHOCK_TYPES, "counts": counts, "curve_minutes": list(range(0, 181, 10)),
        "takeaway": "Most shocks reach half their countries within an hour.",
        "shocks": rows})


# ---------------------------------------------------------------- Chapter 3: appointments
SHORT_EVENT = {"Winter Olympics 2026 (4-22 Feb, multi-day)": "Winter Olympics (best day)",
               "Roland Garros men's final 2025": "Roland Garros men's final", "Wimbledon men's final 2025": "Wimbledon men's final",
               "NBA": "NBA Finals, Game 7", "Conclave 2025 (Pope Leo XIV)": "Conclave (Pope Leo XIV)",
               "Apple event, Feb 2025 (iPhone 16e)": "Apple event (iPhone 16e)", "Trump inauguration 2025": "Trump inauguration",
               "German federal election 2025": "German election", "Eurovision 2025 final": "Eurovision final 2025",
               "Eurovision 2026 final": "Eurovision final 2026", "Nobel Peace Prize 2025": "Nobel Peace Prize"}


def build_appointments():
    """appointments_daily.json: one row per UTC day (count of scheduled events in 15+ countries, widest event, the
    same without football and without any sport, gap flag, real searches of the widest event).
    appointments_compare.json: event reach of the widest league matches, other sport and non-sport events."""
    import glob
    from datetime import date
    d = load(STORY / "appointments_daily.json")
    f = d["fields"]
    days = [dict(zip(f, r)) for r in d["days"]]
    # widest non-sport event per day, from the event units (UTC day of the first moment)
    ns = {}
    for p_ in sorted(glob.glob(str(STORY / "appointments" / "*.json"))):
        m = load(p_)
        for r in m["rows"]:
            e = dict(zip(m["fields"], r))
            if e["is_sport"]:
                continue
            day = e["first_utc"][:10]
            if day not in ns or e["event_reach"] > ns[day]["reach"]:
                ns[day] = {"event": e["event"], "category": e["category"], "reach": e["event_reach"]}
    out = []
    for r in days:
        c = r["events_by_category"]
        nf = r["events"] - c["football"]
        nsp = nf - c["other sport"]
        w = {"event": r["widest_event"], "category": r["widest_category"], "reach": r["widest_event_reach"]} \
            if r["widest_event"] else None
        wnf = r["widest_non_football"]
        wnf = {"event": wnf["event"], "category": wnf["category"], "reach": wnf["event_reach"]} if wnf else None
        wns = wnf if wnf and wnf["category"] not in ("football", "other sport") else ns.get(r["date"]) if nsp else None
        out.append({"date": r["date"], "weekday": date.fromisoformat(r["date"]).weekday(), "gap": bool(r["gap"]),
                    "events": r["events"], "events_no_football": nf, "events_no_sport": nsp,
                    "widest": w, "widest_no_football": wnf, "widest_no_sport": wns,
                    "searches": r["widest_searches"]})
    full = [x for x in out if not x["gap"]]
    import statistics
    med = lambda k: statistics.median(x[k] for x in full)  # noqa: E731
    by_wd = {wd: round(statistics.mean(x["events"] for x in full if x["weekday"] == wd), 1) for wd in range(7)}
    by_wd_reach = {wd: round(statistics.mean((x["widest"] or {"reach": 0})["reach"] for x in full if x["weekday"] == wd))
                   for wd in range(7)}
    summary = {
        "full_days": len(full), "days": len(out),
        "days_with_event": {"all": sum(x["events"] > 0 for x in full), "no_football": sum(x["events_no_football"] > 0 for x in full),
                            "no_sport": sum(x["events_no_sport"] > 0 for x in full)},
        "median_events": {"all": med("events"), "no_football": med("events_no_football"), "no_sport": med("events_no_sport")},
        "mean_events_by_weekday": by_wd, "mean_widest_reach_by_weekday": by_wd_reach,
        "days_100_plus": sum((x["widest"] or {"reach": 0})["reach"] >= 100 for x in full),
        "days_100_plus_football": sum((x["widest"] or {"reach": 0})["reach"] >= 100 and x["widest"]["category"] == "football" for x in full),
    }
    write("appointments_daily.json", {
        "note": "One row per UTC day of the archive. events = scheduled events (appointments) that trended in 15+ "
                "countries within an hour that day; each event counts once, on the day of its scheduled start (else "
                "of its first moment). widest = the event with the largest event reach (countries where any topic "
                "about it trended in its window). no_football / no_sport = the same without football, without any "
                "sport. searches = up to 3 real searches of the widest event, as typed. gap = collection gap day "
                "(lower counts). weekday: 0 = Monday. Summary statistics use the full-coverage days only.",
        "summary": summary, "categories": d["categories"],
        "takeaway": f"On {summary['days_with_event']['all']} of {summary['full_days']} days, at least one scheduled event trended in 15 or more countries.",
        "days": out})

    a = load(STORY / "appointments.json")["reach_comparison"]
    item = lambda x: {"event": SHORT_EVENT.get(x["event"], x["event"]), "date": x["date"], "category": x["category"],  # noqa: E731
                      "reach": x["event_reach"]}
    league = [item(x) for x in a["football"]["widest_league_matches"][:5]]
    other = [item(x) for x in a["other_sport_widest"][:5]]
    # non-sport: catalogue and hand-verified events only (single-topic units such as "Samsung" or "BTS" left out)
    nonsport = [item(x) for x in a["non_sport_40_plus"] if not x["event_id"].startswith("m")][:15]
    write("appointments_compare.json", {
        "note": "Event reach (countries where any topic about the event trended in its window). League matches: "
                "domestic league games identified from their searches (a lower bound). Non-sport: catalogue and "
                "hand-verified events only; single-topic units left out. typical_match = median event reach of "
                "football events.",
        "anchor": league[0], "question": next(x for x in nonsport if x["event"] == "Oscars 2026"),
        "typical_match": a["football"]["median_event_reach"],
        "groups": [{"label": "Spanish league matches (the five widest)", "items": league},
                   {"label": "Other sport (the five widest)", "items": other},
                   {"label": "Not sport: ceremonies, elections, launches, religion", "items": nonsport}]})


# ---------------------------------------------------------------- Chapter 4: waves
MON = {m: i + 1 for i, m in enumerate(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])}
GROUP_KEY = {"crises/politics": "crises", "pop stars": "stars", "tech/companies": "tech"}


def _note_months(notes, months):
    """Parse a story's hand-written notes ('Fall of Assad (Dec 2024, 90) → coastal violence (Mar 2025) → …') into
    {month: what brought it back}. Notes that are review comments (no arrows) give nothing."""
    import re
    out = {}
    if "→" not in notes:
        return out
    year = None
    for seg in [x.strip() for x in notes.split("|")[0].split("→")]:
        m = re.search(r"\(([A-Z][a-z]{2})(?: (\d{4}))?(?:[–-]([A-Z][a-z]{2})(?: (\d{4}))?)?(?:, (\d+))?\)", seg)
        if not m or m.group(1) not in MON:
            continue
        y1 = int(m.group(2) or m.group(4) or (year or 2025))
        year = int(m.group(4) or y1)
        text = seg[:m.start()].strip().rstrip(".,;")        # what came before the "(month, countries)" only
        if "review" in text:                                  # a review comment before the first reason
            text = text.split(". ")[-1]
        text = text[0].upper() + text[1:] if text else text
        a = f"{y1}-{MON[m.group(1)]:02d}"
        b = f"{year}-{MON[m.group(3)]:02d}" if m.group(3) in MON else a
        for mo in months:
            if a <= mo <= b and mo not in out:
                out[mo] = text
    return out


def build_waves():
    import pandas as pd
    sp = load(STORY / "waves_speed.json")
    ch = load(STORY / "waves_chart.json")
    days = sp["days"]
    gap = set(sp["gap_days"])
    series = {x["story"]: x["countries_per_day"] for x in sp["daily_series"]}
    months = ch["months"]

    # ---- Iran, day by day, with its top searches
    iran = next(x for x in ch["stories"] if x["story"] == "Iran")
    t = pd.read_parquet(INTERIM / "topics.parquet", columns=["topic_id", "country_code", "level", "start_time_utc", "query_raw"],
                        filters=[("topic_id", "in", iran["topic_ids"])])
    t = t[t.level == "country"]
    t["day"] = t.start_time_utc.dt.strftime("%Y-%m-%d")
    t["q"] = t.query_raw.astype(str).str.strip().str.lower()
    top = (t.groupby(["day", "q"]).country_code.nunique().reset_index().sort_values(["day", "country_code"], ascending=[True, False])
           .groupby("day").head(3).groupby("day").q.apply(list).to_dict())
    write("waves_daily.json", {
        "note": "Iran: countries whose national feed had any Iran topic trending (Iran and Iran–Israel war merged), "
                "per UTC day, with the day's top 3 searches (by countries). gap = collection gap day (a lower bound).",
        "story": "Iran", "topics": iran["topics"],
        "takeaway": "Iran kept coming back: its widest day reached " + str(max(series["Iran"])) + " countries.",
        "days": [{"date": d_, "countries": c, "gap": d_ in gap, "searches": top.get(d_, [])}
                 for d_, c in zip(days, series["Iran"])]})

    # ---- two returns on one clock
    br = sp["biggest_returns"]
    pick = {"Syria": next(x for x in br if x["story"] == "Syria"),
            "Iran": next(x for x in br if x["story"].startswith("Iran (US strikes"))}
    lab = {"Syria": "Syria, the fall of Assad (Dec. 7, 2024)", "Iran": "Iran, the US strikes (June 22, 2025)"}
    b50 = sp["baseline"]["50_plus"]
    write("waves_speed.json", {
        "note": "Two returns on one clock: cumulative new countries from the third new country's first trend "
                "(minutes; every 10 min to 6 h, then hourly), up to 24 hours. Countries already searching the story in "
                "the 24 hours before are left out (already_trending). Baseline: every non-sport moment reaching 50+ "
                "countries within 72 hours.",
        "returns": [{"key": k, "label": lab[k], "start_utc": v["start_utc"], "already_trending": v["already_trending"],
                     "total_72h": v["total_72h"], "at_1h": v["at_1h"], "at_24h": v["at_24h"], "hours_to_half": v["hours_to_half"],
                     "curve": [c for c in v["curve"] if c[0] <= 24 * 60]} for k, v in pick.items()],
        "baseline": {"moments_50_plus": b50["all"]["n"], "shocks": b50["shocks"]["n"],
                     "shock_share": round(b50["shocks"]["n"] / b50["all"]["n"], 3),
                     "median_hours_to_half": b50["all"]["hours_to_half"]["median"]},
        "takeaway": "When Damascus fell, searches spread over half a day; when the United States struck Iran, 50 countries were searching within the hour."})

    # ---- the ridgeline: 18 stories
    cov = {m: [c["days_collected"], c["days"]] for m, c in ch["month_coverage"].items()}
    stories = []
    for x in ch["stories"]:
        mn = _note_months(x["notes"], months)
        ret = {r["month"]: r for r in x["returns"]}
        drivers = {}
        for mo in months:
            if mo in mn:
                drivers[mo] = mn[mo]
            elif mo in ret and ret[mo].get("biggest_moment"):
                drivers[mo] = f"biggest moment: {ret[mo]['biggest_moment']['topic']}"
        best = max((r for r in br if r["story"] == x["story"] or r["story"].startswith(x["story"] + " (")),
                   key=lambda r: r["total_72h"], default=None)
        peak_label = mn.get(x["peak_month"]) or x["story"]
        stories.append({
            "story": x["story"], "group": GROUP_KEY[x["group"]], "topics": x["topics"],
            "countries_per_month": x["countries_per_month"], "months_15plus": x["months_15plus"],
            "distinct_countries": x["distinct_countries"], "peak_month": x["peak_month"],
            "peak_countries": x["peak_countries"], "peak_label": peak_label, "drivers": drivers,
            "daily": series.get(x["story"]),
            "biggest_return": best and {"start_utc": best["start_utc"], "month_countries": best["month_countries"],
                                        "total_72h": best["total_72h"], "at_1h": best["at_1h"],
                                        "hours_to_half": best["hours_to_half"], "kind": best["moment_kind"]}})
    write("waves_chart.json", {
        "note": "18 stories hand-checked as recurring (Venezuela and Nicolás Maduro merged), from the top of a list "
                "ranked by months with 15+ countries. countries_per_month = countries where any of the story's topics "
                "trended at least once that month (follows months). coverage = [days collected, days in month]; "
                "partial months are lower bounds. drivers = what brought it back that month (hand-written notes, else "
                "the month's biggest moment). daily = countries per UTC day (follows days).",
        "months": months, "coverage": cov, "days": days, "gap_days": sorted(gap),
        "groups": {"crises": "crises and politics", "stars": "stars", "tech": "tech and companies"},
        "takeaway": "Eighteen stories the world kept returning to: wars and crises came back with unscheduled news; stars returned together in awards season.",
        "stories": stories})


# ---------------------------------------------------------------- Chapter 5: rituals
TOMORROW_RE = (r"tomorrow|ma[ñn]ana|amanh[ãa]|demain|morgen|domani|yar[ıi]n|besok|завтра|غدا|明天|明日|내일|ngày mai|jutro|"
               r"zítra|holnap|imorgon|i morgen")
FIXED_MAX_SHIFT = 3        # a holiday whose date moved by more days than this between its two years is "moving"


def _weather_six(names):
    """Per local date: the countries where a 'today' weather trend started at 6 a.m. local, with the same zones as
    step 8's weather_day.json (national feeds in one zone; US, CA, RU from their regional feeds in each region's zone)."""
    import pandas as pd
    sys.path.insert(0, str(ROOT / "pipeline"))
    from common import REGION_TZ
    meta = pd.read_parquet(INTERIM / "topic_meta.parquet").set_index("topic_id")
    wid = set(meta.index[(meta.category == "weather") & ~meta.is_junk.astype(bool)])
    cz = load(INTERIM / "country_timezones.json")
    t = pd.read_parquet(INTERIM / "topics.parquet", columns=["topic_id", "country_code", "level", "location", "start_time_utc", "query_raw"],
                        filters=[("topic_id", "in", sorted(wid))])
    t = t[~t.query_raw.astype(str).str.lower().str.contains(TOMORROW_RE, regex=True, na=False)]
    reg = ("US", "CA", "RU")
    nat = t[(t.level == "country") & ~t.country_code.isin(reg)].copy()
    rg = t[(t.level == "region") & t.country_code.isin(reg)].copy()
    nat["zone"] = nat.country_code.map(cz)
    rg["zone"] = [REGION_TZ.get(c, {}).get(str(z).split("-")[-1], cz[c]) for c, z in zip(rg.country_code, rg.location)]
    rows = []
    for d in (nat, rg):
        for z, g in d.groupby("zone"):
            lt = g.start_time_utc.dt.tz_convert(z)
            k = g[lt.dt.hour.values == 6]
            rows.append(pd.DataFrame({"ld": lt[lt.dt.hour == 6].dt.strftime("%Y-%m-%d").values, "c": k.country_code.values}))
    six = pd.concat(rows).drop_duplicates()
    return six.groupby("ld").c.apply(lambda s: sorted(s)).to_dict()


def build_rituals():
    from datetime import date
    names = {c["iso2"]: c["name"] for c in countries()}
    # ---- weather: each country's usual peak (two_clocks.json weather_today), the usual day, every day × hour
    wt = load(STORY / "two_clocks.json")["cases"]["weather_today"]["countries"]
    wd = load(STORY / "weather_day.json")
    six = _weather_six(names)
    rows = [{"iso2": r["country"], "name": names.get(r["country"], r["country_name"]), "local_peak_hour": r["local_peak_hour"],
             "utc_peak_hour": r["utc_peak_hour"], "utc_offset_h": r["typical_utc_offset_h"], "phrasing": r["top_phrasing"]}
            for r in wt]
    by_day = [{"date": d_, "flag": f, "today": today, "six": six.get(d_, [])} for d_, f, today, _tomorrow in wd["by_day"]]
    u = wd["usual_day"]["today"]
    write("weather_day.json", {
        "note": "Weather ('today' phrasings only; 'weather tomorrow' is left out). countries: each country's usual peak, "
                "the local hour and the UTC hour with the most weather trends over the archive (20+ trends; US, CA "
                "and RU from their regional feeds, each in its zone), its typical UTC offset and its most common "
                "phrasing. usual_day = mean countries where a weather trend started in each local hour (0-23), over "
                "the full-coverage days. days = every local day: flag (null = full coverage; 'gap' or next to one), "
                "countries starting a weather trend in each local hour, and the countries that did at 6 a.m.",
        "full_coverage_days": wd["full_coverage_days"],
        "usual_day": {"mean": u["mean_countries_by_local_hour"], "peak_hour": u["peak_hour"],
                      "peak_mean": u["peak_mean_countries"]},
        "takeaway": f"On a usual day, weather starts trending in about {round(u['peak_mean_countries'])} countries at {u['peak_hour']} a.m. local time.",
        "countries": rows, "days": by_day})

    # ---- holidays that came twice
    r = load(STORY / "rituals.json")
    hols = []
    for name_, h in r["holidays"].items():
        for series_, both in h["countries_in_both_years"].items():
            occ = sorted([o for o in h["occurrences"] if o["series"] == series_ and o["days_in_archive"]], key=lambda o: o["date"])
            if len(occ) < 2:
                continue
            d1, d2 = (date.fromisoformat(o["date"]) for o in occ[:2])
            shift = (d2 - d1).days - 365 if d2.year - d1.year == 1 else (d2 - d1).days - 366
            # day of year of each holiday date, same year basis
            hols.append({
                "name": series_, "moving": abs(shift) > FIXED_MAX_SHIFT, "shift_days": shift,
                "occurrences": [{"year": o["year"], "date": o["date"], "peak_day": o["peak_day"], "peak_countries": o["peak_countries"],
                                 "days": [[x[1], x[2]] for x in o["countries_per_day"] if x[2] is not None]} for o in occ[:2]],
                "both_years": both["country_codes"], "both_years_n": both["countries"]})
    hols.sort(key=lambda h_: h_["occurrences"][0]["date"])
    write("rituals.json", {
        "note": "Holidays that appear twice in the archive (Halloween, Diwali and Eid al-Adha appear once and are left "
                "out). Clean holiday groups (hand-checked, 90% precise); countries per UTC day from 10 days before to 5 "
                "days after each holiday date. moving = its date moved by more than 3 days between the two years "
                "(shift_days: + later, - earlier). both_years = countries where it trended in both windows.",
        "takeaway": "Every year the world returns to the same holidays, even when their dates move.",
        "holidays": hols})


# ---------------------------------------------------------------- Closing: two clocks
def build_clocks():
    from datetime import datetime
    tc = load(STORY / "two_clocks.json")["cases"]
    cl = {c["iso2"]: c for c in countries()}
    ref = datetime(2025, 4, 21, 12)
    # rows by the capital's UTC offset that day (United States = Washington), as in the Opening
    off = {c: ZoneInfo(CAPITALS[c][1]).utcoffset(ref).total_seconds() / 3600 for c in cl}
    wrap = lambda h: h - 24 if h >= 15 else h      # weather hours on a day from 15:00 (previous) to 15:00 UTC  # noqa: E731
    weather = {r["country"]: {"world": wrap(r["utc_peak_hour"]), "local": r["local_peak_hour"], "phrasing": r["top_phrasing"]}
               for r in tc["weather_today"]["countries"]}
    # Pope Francis dots = the Opening's rows: first refresh (UTC), the capital's clock, the "searched as" titles
    op = load(OUT / "opening.json")

    def _h(stamp):
        d = datetime.strptime(stamp[:16], "%Y-%m-%dT%H:%M")
        return round((d - datetime(2025, 4, 21)).total_seconds() / 3600, 3)
    pope = {r["iso2"]: {"world": _h(r["first_utc"]), "local": _h(r["local_time"]), "phrasing": " · ".join(r["searched_as"])}
            for r in op["rows"] if r["trending"]}
    nye_case = tc["new_years_eve_2025_2026"]
    nye = {r["country"]: {"world": r["utc_h_from_ref"], "local": r["local_h_from_ref"], "phrasing": r["top_phrasing"]}
           for r in nye_case["countries"] if r["trends_in_peak_step"] >= 2 and not r["peak_tied"]}
    iso = sorted(set(weather) | set(pope), key=lambda c: (-off[c], cl[c]["name"]))
    ws, ps = tc["weather_today"]["spread"], tc["pope_francis_2025_04_21"]["spread"]
    write("two_clocks.json", {
        "note": "One row per country, east (top) to west (UTC offset on Apr. 21, 2025; United States, Canada and Russia "
                "by the capital's zone). weather = the hour its 'weather' searches usually peak (world = UTC hour, on a day "
                "from 15:00 to 15:00 UTC; local = local hour). pope = its first Pope Francis trend on Apr. 21, 2025, in "
                "hours after midnight (UTC, and on the local wall clock). nye = New Year's Eve 2025/26: hours from "
                "midnight (UTC, and local), for the countries with a clear peak (2+ trends in the peak 10 minutes, no tie).",
        "rows": [{"iso2": c, "name": cl[c]["name"], "offset": off[c]} for c in iso],
        "events": {
            "weather": {"label": "Weather", "domain": [-9, 15], "values": weather,
                        "stat": {"local_within_1h": ws["local"]["within_1h_of_median"], "n": ws["local"]["n"]}},
            "pope": {"label": "Pope Francis", "domain": [-2, 22], "values": pope,
                     "stat": {"world_within_1h": ps["utc"]["within_1h_of_median"], "n": ps["utc"]["n"]}},
            "nye": {"label": "New Year's Eve", "domain": [-12, 12], "values": nye,
                    "stat": {"n": len(nye), "local_within_1h": sum(abs(v["local"]) <= 1 for v in nye.values())}}},
        "takeaway": f"On local clocks {ws['local']['within_1h_of_median']} of {ws['local']['n']} countries search the weather at 6 a.m., while {ps['utc']['within_1h_of_median']} of {ps['utc']['n']} searched for Pope Francis within the same world hour."})


# ---------------------------------------------------------------- Your turn: frames, days, Country Wrapped
def build_frames():
    """frames/YYYY-MM.json from data/export/hours (step 8): per UTC hour, each country's top active search and the
    top 5 shared topics (topic, countries, kind, member countries, how many started it in the last 3 hours)."""
    import glob
    import gzip
    for p_ in sorted(glob.glob(str(EXPORT / "hours" / "*.json"))):
        h = load(p_)
        obj = {"source": SOURCE, "month": h["month"], "countries": h["countries"], "hours": h["hours"],
               "gap_hours": h["gap_hours"], "kinds": h["kinds"],
               "note": "top[i][j] = index into topics of country j's top active trend in hour i (-1 = none). shared[i] "
                       "= the hour's top 5 shared topics: [topic index, countries, kind index, member country indices, "
                       "countries that started it in the last 3 hours]. topics = [name, category]. Hidden topics never "
                       "appear. gap_hours = hours of collection-gap days.",
               "topics": [[t[1] or t[0], t[2]] for t in h["topics"]], "top": h["top"], "shared": h["shared"]}
        write(f"frames/{h['month']}.json", obj)
        b = (OUT / "frames" / f"{h['month']}.json").read_bytes()
        print(f"    gzip {len(gzip.compress(b)) / 1024:.0f} kB")


def build_days():
    d = load(STORY / "days.json")
    write("days.json", {
        "note": "Per UTC day: its widest global moments (up to 5: name, kind, countries, start) and the gap flag. "
                "countries = event reach for verified shock and appointment events, else the moment's reach.",
        "days": [{"date": x["day"], "gap": x["gap"],
                  "top": [{"name": t["event"] or t["name"], "kind": t["kind"], "countries": t["countries"],
                           "start_utc": t["start_utc"]} for t in x["top5"]]} for x in d["days"]]})


def build_wrapped():
    import glob
    import statistics
    cards = {json.loads(Path(p_).read_text())["country_code"]: json.loads(Path(p_).read_text())
             for p_ in glob.glob(str(STORY / "wrapped" / "[A-Z][A-Z].json"))}
    full = [c for c in cards.values() if not c["low_data"]]
    typ_sched = statistics.median(c["appointments"]["appointment_share"] for c in full)
    best_local = max(full, key=lambda c: c["local_share"])
    # weather "today" phrasing only ("weather tomorrow" is cut from the article)
    today_phr = {r["country"]: r["top_phrasing"] for r in load(STORY / "two_clocks.json")["cases"]["weather_today"]["countries"]}
    for cc, c in cards.items():
        sh = c["shocks"]
        top_shocks = sorted(sh["chart_shocks_joined"], key=lambda x: -(x["event_reach"] or 0))[:3]
        out = {
            "iso2": cc, "name": c["country_name"], "low_data": c["low_data"],
            "local_share": c["local_share"], "local_rank": c["local_share_rank"], "local_rank_of": c["local_share_rank_of"],
            "local_top5": [x["name"] for x in c["uniquely_local_top5"]],
            "global_joined": sh["global_moments_joined"], "global_total": sh["global_moments"],
            "shocks_joined": sh["chart_shocks_joined_n"], "shocks_total": sh["chart_shocks"],
            "biggest_shocks": [{"name": x["name"], "date": x["date_utc"][:10], "countries": x["event_reach"]} for x in top_shocks],
            "first3_share": sh["first3_share"], "first3_rank": sh["first3_share_rank_without_low_data"],
            "first3_rank_of": sh["first3_share_rank_of"], "feed_minutes": sh["feed_median_minutes_between_starts"],
            "waves_joined": c["waves"]["joined_n"], "waves_total": c["waves"]["stories"],
            "waves": [w["story"] for w in c["waves"]["joined"]],
            "scheduled_share": c["appointments"]["appointment_share"], "scheduled_typical": round(typ_sched, 4),
            "weather_hour": c["rituals"]["weather_today_hour"], "weather_phrasings": [today_phr[cc]] if cc in today_phr else [],
            "holidays_both": c["rituals"]["holidays_both_years"], "holidays_total": 10,
            "twin": {"iso2": c["attention_twin"]["country_code"], "name": c["attention_twin"]["country_name"]},
            "twin_no_sport": {"iso2": c["attention_twin_without_sport"]["country_code"], "name": c["attention_twin_without_sport"]["country_name"]},
            "surprising_twin": c.get("surprising_twin") and {"iso2": c["surprising_twin"]["country_code"], "name": c["surprising_twin"]["country_name"]},
            "biggest_day": c["biggest_day"],
            "most_local": {"name": best_local["country_name"], "share": best_local["local_share"]},
        }
        write(f"wrapped/{cc}.json", {"note": "Country Wrapped: what this country kept to itself and what it shared. "
                                             "Ranks exclude low_data countries unless stated.", **out})
    write("wrapped/index.json", {"countries": sorted([{"iso2": k, "name": v["country_name"], "low_data": v["low_data"]}
                                                       for k, v in cards.items()], key=lambda x: x["name"])})


BUILDERS = {"countries": build_countries, "opening": build_opening, "local": build_local, "shocks": build_shocks, "appointments": build_appointments, "waves": build_waves, "rituals": build_rituals, "clocks": build_clocks, "frames": build_frames, "days": build_days, "wrapped": build_wrapped}

if __name__ == "__main__":
    todo = sys.argv[1:] or list(BUILDERS)
    print(f"writing to {OUT.relative_to(ROOT)}")
    for k in todo:
        BUILDERS[k]()
