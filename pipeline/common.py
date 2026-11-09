"""Shared paths, constants and small helpers for steps 3-4."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INTERIM = ROOT / "data" / "interim"
WORK = INTERIM / "work"
CACHE = ROOT / "cache"
DOCS = ROOT / "docs"
for p in (WORK, CACHE / "wikidata", CACHE / "claude", CACHE / "embeddings", DOCS):
    p.mkdir(parents=True, exist_ok=True)

# ---- thresholds (all logged in docs/DECISIONS.md) ----
WINDOW_DAYS = 2            # "3-day window": strings whose trend days are <= 2 days apart (days d, d+1, d+2)
TYPO_RATIO = 92            # rapidfuzz fuzz.ratio >= 92 (normalized Indel similarity >= 0.92)
TYPO_MIN_LEN = 6           # both strings at least this many characters
GENERIC_DEGREE = 25        # a related search seen with >= 25 distinct trends is "generic" and never counts as evidence
MANUAL_GENERIC = {"news", "live", "cnn", "bbc", "today", "hoy", "en vivo", "ao vivo", "live score",
                  "results", "score", "weather", "google", "youtube", "facebook", "wikipedia"}
SEM_HIGH = 0.96            # cosine >= this + same numbers + word-swap guard -> merge without related evidence
SEM_LOW = 0.93             # cosine >= this + same numbers + one string in the other's related list -> merge
IMPORTANT_TOP_PCT = 0.01   # each country's top 1% of strings by summed search volume
CLAUDE_MODEL = "claude-haiku-5-5"
CLAUDE_CHUNK = 150         # strings per request
# Message Batches pricing for claude-haiku-5-5 (50% of $0.10 / $0.50 per MTok; prompts <= 100K tokens)
PRICE_IN_PER_MTOK = 0.05
PRICE_OUT_PER_MTOK = 0.25
SPEND_LIMIT_USD = 10.0
SPEND_ALERT_USD = 5.0      # stop and warn if a planned run would exceed this

DIGITS = re.compile(r"\d+")


def digit_sig(s: str) -> tuple:
    return tuple(sorted(DIGITS.findall(s)))


def save_json(path, obj):
    Path(path).write_text(json.dumps(obj, indent=2, ensure_ascii=False, default=str))


def load_json(path, default=None):
    p = Path(path)
    return json.loads(p.read_text()) if p.exists() else default


class UnionFind:
    """Union-find with optional cannot-link on a per-component label (e.g. Wikidata QID)."""

    def __init__(self, n):
        self.parent = list(range(n))
        self.label = [None] * n

    def find(self, x):
        p = self.parent
        while p[x] != x:
            p[x] = p[p[x]]
            x = p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return False
        la, lb = self.label[ra], self.label[rb]
        if la is not None and lb is not None and la != lb:
            return None  # blocked: would merge two different labels
        self.parent[rb] = ra
        self.label[ra] = la if la is not None else lb
        return True


# Sub-national region -> IANA time zone for multi-zone countries (location codes XX-YYY).
# Regions not listed use the country's zone (data/interim/country_timezones.json).
REGION_TZ = {
    "US": {**{s: "America/New_York" for s in "CT DC DE FL GA IN KY MA MD ME MI NC NH NJ NY OH PA RI SC VA VT WV".split()},
           **{s: "America/Chicago" for s in "AL AR IA IL KS LA MN MO MS ND NE OK SD TN TX WI".split()},
           **{s: "America/Denver" for s in "CO MT NM UT WY ID".split()},
           **{s: "America/Los_Angeles" for s in "CA NV OR WA".split()},
           "AZ": "America/Phoenix", "AK": "America/Anchorage", "HI": "Pacific/Honolulu"},
    "CA": {"AB": "America/Edmonton", "BC": "America/Vancouver", "MB": "America/Winnipeg", "NB": "America/Moncton",
           "NL": "America/St_Johns", "NS": "America/Halifax", "NT": "America/Yellowknife", "NU": "America/Iqaluit",
           "ON": "America/Toronto", "PE": "America/Halifax", "QC": "America/Toronto", "SK": "America/Regina",
           "YT": "America/Whitehorse"},
    "AU": {"ACT": "Australia/Sydney", "NSW": "Australia/Sydney", "NT": "Australia/Darwin", "QLD": "Australia/Brisbane",
           "SA": "Australia/Adelaide", "TAS": "Australia/Hobart", "VIC": "Australia/Melbourne", "WA": "Australia/Perth"},
    "BR": {**{s: "America/Sao_Paulo" for s in "AL AP BA CE DF ES GO MA MG PA PB PE PI PR RJ RN RS SC SE SP TO".split()},
           "AM": "America/Manaus", "RO": "America/Porto_Velho", "RR": "America/Boa_Vista", "MT": "America/Cuiaba",
           "MS": "America/Campo_Grande", "AC": "America/Rio_Branco"},
    "MX": {"BCN": "America/Tijuana", "BCS": "America/Mazatlan", "SON": "America/Hermosillo", "SIN": "America/Mazatlan",
           "NAY": "America/Mazatlan", "CHH": "America/Chihuahua", "ROO": "America/Cancun"},
    "RU": {"KGD": "Europe/Kaliningrad",
           **{s: "Europe/Samara" for s in "SAM UD".split()}, "AST": "Europe/Astrakhan", "SAR": "Europe/Saratov",
           "ULY": "Europe/Ulyanovsk", "VGG": "Europe/Volgograd",
           **{s: "Asia/Yekaterinburg" for s in "SVE CHE KGN TYU KHM YAN ORE PER BA".split()},
           "OMS": "Asia/Omsk", **{s: "Asia/Novosibirsk" for s in "NVS".split()}, "ALT": "Asia/Barnaul",
           "AL": "Asia/Barnaul", "TOM": "Asia/Tomsk", "KEM": "Asia/Novokuznetsk",
           **{s: "Asia/Krasnoyarsk" for s in "KYA KK TY".split()}, **{s: "Asia/Irkutsk" for s in "IRK BU".split()},
           **{s: "Asia/Yakutsk" for s in "SA AMU".split()}, "ZAB": "Asia/Chita",
           **{s: "Asia/Vladivostok" for s in "PRI KHA YEV".split()}, "MAG": "Asia/Magadan", "SAK": "Asia/Sakhalin",
           **{s: "Asia/Kamchatka" for s in "KAM CHU".split()}},
    "ID": {**{s: "Asia/Makassar" for s in "BA NB NT KI KS KU SA SG SN ST SR GO".split()},
           **{s: "Asia/Jayapura" for s in "MA MU PA PB".split()},
           **{s: "Asia/Pontianak" for s in "KB KT".split()}},
}
