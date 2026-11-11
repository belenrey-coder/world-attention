"""Recall rules for combine (added 2026-11-11). Each returns candidate pairs (sid_a, sid_b); combine
applies them as union-find layers with the usual guards (QID cannot-link, short-string gate,
size cap, and for rules 1-2 the confident-Claude-name block).

  1 word_set     same set of words, ignoring order, simple plurals and one-letter accent variants
  2 containment  B = all of A + only generic extra words (dates, years, today, live, results, ...)
  3 match_key    sports_match strings whose Claude names give the same two teams (sorted)
  4 claude_near  important strings whose Claude names are near-identical (ratio >= 95, conf >= 0.7)

Every pair must also have trended within WINDOW_DAYS of each other at least once (the 3-day window).
"""
import re
from collections import defaultdict

import numpy as np
import pandas as pd

from common import WINDOW_DAYS, digit_sig
from textnorm import norm

MAX_KEY_GROUP = 60          # keys shared by more strings than this are too generic to pair up
NEAR_RATIO = 95
NEAR_MIN_CONF = 0.7
MATCH_MIN_CONF = 0.5        # labels below 0.5 never create merges

# ------------------------------------------------------------------ tokens
_LATIN_WORD = re.compile(r"^[a-z]+$")


def stem(w: str) -> str:
    """Simple plural -> singular for Latin-script words (after norm: lowercase ASCII)."""
    w = w.replace("ё", "е")                       # one-letter accent variant in Cyrillic
    if not _LATIN_WORD.match(w) or len(w) < 5 or w.endswith(("ss", "us", "is")):
        return w
    if w.endswith("es") and w[:-2].endswith(("ch", "sh", "x", "z")):
        return w[:-2]                              # matches -> match, crashes -> crash
    if w.endswith("s"):
        return w[:-1]                              # games -> game, resultados -> resultado
    return w


def toks(q: str) -> list:
    return [stem(w) for w in q.split()]


# ------------------------------------------------------------------ window
def near_days(a, b) -> bool:
    a, b = np.asarray(a), np.sort(np.asarray(b))
    j = np.searchsorted(b, a)
    d = np.minimum(np.abs(b[np.clip(j, 0, len(b) - 1)] - a), np.abs(b[np.clip(j - 1, 0, len(b) - 1)] - a))
    return bool(d.min() <= WINDOW_DAYS)


def pairs_in_groups(groups, days, cond=None):
    """All pairs inside each group that trended within the window (and satisfy cond)."""
    out, skipped = [], 0
    for ids in groups:
        if len(ids) < 2:
            continue
        if len(ids) > MAX_KEY_GROUP:
            skipped += 1
            continue
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                a, b = ids[i], ids[j]
                if (cond is None or cond(a, b)) and near_days(days[a], days[b]):
                    out.append((a, b))
    return out, skipped


# ------------------------------------------------------------------ 1 word set
def rule_word_set(s):
    days = s.days.to_numpy()
    key = defaultdict(list)
    for sid, q in zip(s.sid, s.query_norm):
        t = toks(q)
        if t:
            key[tuple(sorted(set(t)))].append(sid)
    pairs, skipped = pairs_in_groups(key.values(), days)
    return pairs, {"keys_skipped_too_big": skipped}


# ------------------------------------------------------------------ 2 containment
MONTHS = set("""
january february march april may june july august september october november december
jan feb mar apr jun jul aug sep sept oct nov dec
enero febrero marzo abril mayo junio julio agosto septiembre setiembre octubre noviembre diciembre
janeiro fevereiro marco maio junho julho setembro outubro novembro dezembro
janvier fevrier mars avril mai juin juillet aout septembre octobre novembre decembre
januar februar marz juni juli oktober dezember
gennaio febbraio aprile maggio giugno luglio settembre ottobre dicembre
ocak subat nisan mayis haziran temmuz agustos eylul ekim kasim aralik
""".split())
GENERIC_EXTRA = set("""
today tonight live livestream stream streaming result score time news standing table update latest
hoy vivo directo resultado marcador hora noticia tabla posicione clasificacion
hoje resultado placar tabela classificacao
aujourd hui direct resultat heure actualite info classement
heute ergebni ergebnisse uhrzeit nachrichten tabelle
oggi diretta risultato risultati orario notizie classifica
bugun canli sonuc sonuclari skor haber puan durumu
hari ini langsung hasil berita klasemen
vandaag uitslag uitslagen stand
dzisiaj zywo wynik wyniki
hom nay truc tiep ket qua
сегодня прямая трансляция онлайн результат результаты счет новости таблица
اليوم مباشر بث نتيجة نتائج اخبار ترتيب
de en ao na do da del the in at
""".split())
GENERIC_EXTRA = {stem(norm(w)) for w in GENERIC_EXTRA} | {stem(norm(w)) for w in MONTHS}
_YEAR = re.compile(r"^20(2[3-7])$")
_DAYNUM = re.compile(r"^(?:[1-9]|[12]\d|3[01])(?:st|nd|rd|th)?$")


def generic_extra(extra: set) -> bool:
    """Extras are generic if each is a listed word or a year 2023-2027; day numbers count only
    next to a month word ("december 26"), so "iphone 16 pro" never reduces to "iphone pro"."""
    has_month = bool(extra & {stem(m) for m in MONTHS})
    for w in extra:
        if w in GENERIC_EXTRA or _YEAR.match(w) or (has_month and _DAYNUM.match(w)):
            continue
        return False
    return True


def rule_containment(s, is_short_generic, hubs):
    """A (not short, not a generic related term) and B: set(A) is a strict subset of set(B), and the
    extra words of B are all generic."""
    days = s.days.to_numpy()
    by_core = defaultdict(list)
    sets = {}
    for sid, q in zip(s.sid, s.query_norm):
        t = set(toks(q))
        core = frozenset(w for w in t if not (w in GENERIC_EXTRA or _YEAR.match(w) or _DAYNUM.match(w)))
        if core:
            sets[sid] = t
            by_core[core].append(sid)
    qn = s.query_norm.to_numpy()
    ok_a = {sid for sid in sets if not is_short_generic(qn[sid]) and qn[sid] not in hubs}
    pairs, skipped = [], 0
    for ids in by_core.values():
        if len(ids) < 2:
            continue
        if len(ids) > MAX_KEY_GROUP:
            skipped += 1
            continue
        for a in ids:
            if a not in ok_a:
                continue
            for b in ids:
                if a == b or not (sets[a] < sets[b]):
                    continue
                if generic_extra(sets[b] - sets[a]) and near_days(days[a], days[b]):
                    pairs.append((a, b))
    return pairs, {"keys_skipped_too_big": skipped}


# ------------------------------------------------------------------ 3 match key
VS_SPLIT = re.compile(r"\s+(?:vs\.?|v\.?|x|versus|contra|against|gegen|contre|mot|–|—|-)\s+", re.I)
TEAM_DROP = {"fc", "cf", "afc", "sc", "ac", "cd", "fk", "sk", "club", "cp", "the"}


def match_key(name: str):
    parts = VS_SPLIT.split(name)
    if len(parts) != 2:
        return None
    teams = []
    for p in parts:
        w = [x for x in norm(p).split() if x not in TEAM_DROP]
        if not w:
            return None
        teams.append(" ".join(w))
    if teams[0] == teams[1]:
        return None
    return tuple(sorted(teams))


def rule_match_key(s, lab):
    days = dict(zip(s.sid, s.days))
    sid_of = dict(zip(s.query_norm, s.sid))
    m = lab[(lab.type == "sports_match") & (lab.confidence >= MATCH_MIN_CONF)]
    key = defaultdict(list)
    for q, name in m.canonical_en.items():
        k = match_key(name)
        if k and q in sid_of:
            key[k].append(sid_of[q])
    pairs, skipped = pairs_in_groups(key.values(), days)
    return pairs, {"match_strings": int(len(m)), "keys": len(key), "keys_skipped_too_big": skipped}


# ------------------------------------------------------------------ 4 near-identical Claude names
def _similar_words(a: str, b: str) -> bool:
    """Same number of words, and every differing word has a close counterpart (no word swaps)."""
    from rapidfuzz import fuzz
    ta, tb = a.split(), b.split()
    if a.replace(" ", "") == b.replace(" ", ""):
        return True
    if len(ta) != len(tb):
        return False
    da, db = [w for w in ta if w not in tb], [w for w in tb if w not in ta]
    return all(any(fuzz.ratio(x, y) >= 75 for y in db) for x in da)


def rule_claude_near(s, lab):
    from rapidfuzz import fuzz, process
    imp = s[s.important]
    l = lab[(lab.confidence >= NEAR_MIN_CONF) & (lab.canonical_en.str.lower() != "unknown")]
    l = l[l.index.isin(set(imp.query_norm))]
    sid_of = dict(zip(s.query_norm, s.sid))
    name = {sid_of[q]: norm(n) for q, n in l.canonical_en.items()}
    days = dict(zip(s.sid, s.days))
    by_day = defaultdict(list)
    for sid in name:
        for d in days[sid]:
            by_day[int(d)].append(sid)
    pairs = set()
    for d in sorted(by_day):
        Q = by_day[d]
        C = sorted({x for k in range(d, d + WINDOW_DAYS + 1) for x in by_day.get(k, [])})
        qn, cn = [name[x] for x in Q], [name[x] for x in C]
        M = process.cdist(qn, cn, scorer=fuzz.ratio, score_cutoff=NEAR_RATIO, dtype=np.uint8, workers=-1)
        for i, j in zip(*np.nonzero(M)):
            a, b = Q[i], C[j]
            if a == b:
                continue
            na, nb = name[a], name[b]
            if digit_sig(na) == digit_sig(nb) and _similar_words(na, nb):
                pairs.add((min(a, b), max(a, b)))
    return sorted(pairs), {"names": len(name)}


def all_rules(s, lab, is_short_generic, hubs):
    out = {}
    for key, fn in (("claude_near", lambda: rule_claude_near(s, lab)),
                    ("match_key", lambda: rule_match_key(s, lab)),
                    ("raw_match_key", lambda: rule_raw_match_key(s, lab)),
                    ("word_set", lambda: rule_word_set(s)),
                    ("containment", lambda: rule_containment(s, is_short_generic, hubs))):
        pairs, info = fn()
        out[key] = (pairs, info)
        print(f"  recall rule {key}: {len(pairs):,} candidate pairs {info}", flush=True)
    return out


# ------------------------------------------------------------------ 5 raw match key (2026-11-11)
# Separators between two teams in the raw search string, in any language (matched as whole words; the
# dash forms only with spaces around them, so "al-hilal" or "saint-etienne" are never split).
RAW_SEPARATORS = ["vs", "vs.", "v", "v.", "x", "mot", "contra", "contro", "gegen", "contre", "versus", "against",
                  "lwn", "ضد", "مقابل", "против", "срещу", "проти", "proti", "protiv", "εναντιον", "εναντίον",
                  "dau voi", "đấu với", "พบ", "対", "對", "vs", "বনাম", "बनाम", "karsi", "karşı", "vastaan", "ellen",
                  "kontra", "naspram"]
_SEP_WORDS = sorted({s for s in RAW_SEPARATORS}, key=len, reverse=True)
RAW_SPLIT = re.compile(r"\s+[-–—]\s+|(?:^|\s)(?:" + "|".join(re.escape(s) for s in _SEP_WORDS) + r")(?:\s|$)", re.I)
MATCH_EXTRA = {stem(norm(w)) for w in """prediction predictions pronostico pronosticos prognose highlights lineup lineups
alineaciones alineacion escalacao escalacoes formazioni h2h tickets stats estadisticas where watch donde ver
onde assistir canal channel tv""".split()}
MAX_TEAM_WORDS = 4


def raw_match_key(raw: str):
    """(team_a, team_b) sorted, from a raw search string with exactly one separator; None otherwise."""
    if not isinstance(raw, str):
        return None
    parts = [p for p in RAW_SPLIT.split(raw.strip().lower()) if p is not None]
    if len(parts) != 2:
        return None
    teams = []
    for p in parts:
        w = [stem(x) for x in norm(p).split()]
        w = [x for x in w if x not in TEAM_DROP and x not in MATCH_EXTRA and x not in GENERIC_EXTRA
             and not _YEAR.match(x) and not _DAYNUM.match(x)]
        if not w or len(w) > MAX_TEAM_WORDS or all(x.isdigit() for x in w):
            return None
        teams.append(" ".join(w))
    if teams[0] == teams[1] or min(len(t) for t in teams) < 2:
        return None
    return tuple(sorted(teams))


def rule_raw_match_key(s, lab):
    """Merge strings whose raw text gives the same two teams, within the window. Skip a pair when both
    strings have confident Claude match names (conf >= 0.8) that give different teams."""
    days = s.days.to_numpy()
    raw = s.top_raw.to_numpy()
    ck = {}
    if len(lab):
        sid_of = dict(zip(s.query_norm, s.sid))
        conf = lab[(lab["type"] == "sports_match") & (lab.confidence >= 0.8)]
        ck = {sid_of[q]: match_key(n) for q, n in conf.canonical_en.items() if q in sid_of}
    key = defaultdict(list)
    for sid in s.sid:
        k = raw_match_key(raw[sid])
        if k:
            key[k].append(sid)

    def cond(a, b):
        ka, kb = ck.get(a), ck.get(b)
        return not (ka and kb and ka != kb)
    pairs, skipped = pairs_in_groups(key.values(), days, cond)
    return pairs, {"strings_with_key": int(sum(len(v) for v in key.values())), "keys": len(key),
                   "keys_skipped_too_big": skipped}
