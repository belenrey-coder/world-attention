"""Step 3(b): link name-like strings to Wikidata with wbsearchentities.

- Only strings that look like a name (person / team / place / thing), see `looks_like_name`.
- Languages: those of the countries where the string trended (most rows first), max 3,
  stopping at the first strong match.
- Strong match only: the matched label or alias, normalized with the same `norm()`,
  equals the string's query_norm. Disambiguation/category/list items are skipped.
- Every response is cached in cache/wikidata/<lang>/<xx>/<sha1>.json; reruns are free.
- Polite: descriptive User-Agent (no personal contact), maxlag=5, 2 connections capped at
  3 requests/s overall (Wikimedia's documented limit for identified bots is 200/min); on a
  429 or maxlag reply every worker pauses for Retry-After.
"""
import hashlib
import json
import random
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
import requests

from common import CACHE, WORK
from textnorm import norm

API = "https://www.wikidata.org/w/api.php"
# User-Agent: generic project name + the project's GitHub URL (no personal email). The URL is read from
# the environment (WD_CONTACT_URL) so it is never hard-coded; nothing is sent without it.
UA_BASE = "world-attention-research/0.1"


def user_agent():
    url = __import__("os").environ.get("WD_CONTACT_URL", "").strip()
    if not url.startswith("https://github.com/"):
        raise SystemExit("Set WD_CONTACT_URL to the project's GitHub repo URL before calling Wikidata.")
    return f"{UA_BASE} ({url})"

MAX_LANGS = 2
WORKERS = 1
MAX_RPS = float(__import__("os").environ.get("WD_RPS", 0.15))  # 0.15 req/s = 9/min (unidentified tier is 10/min)

COUNTRY_LANG = {
    "US": "en", "GB": "en", "CA": "en", "AU": "en", "NZ": "en", "IE": "en", "ZA": "en", "NG": "en",
    "KE": "en", "GH": "en", "UG": "en", "ZM": "en", "ZW": "en", "JM": "en", "TT": "en", "SG": "en",
    "PH": "en", "IN": "en", "PK": "en", "LK": "en", "NP": "ne", "BD": "bn", "MM": "my", "KH": "km",
    "JP": "ja", "KR": "ko", "TW": "zh", "HK": "zh", "VN": "vi", "TH": "th", "ID": "id", "MY": "ms",
    "BR": "pt", "PT": "pt", "AO": "pt", "MZ": "pt",
    "ES": "es", "MX": "es", "AR": "es", "CO": "es", "CL": "es", "PE": "es", "VE": "es", "EC": "es",
    "UY": "es", "PY": "es", "BO": "es", "DO": "es", "GT": "es", "CR": "es", "PA": "es", "HN": "es",
    "SV": "es", "NI": "es", "CU": "es", "PR": "es",
    "FR": "fr", "BE": "fr", "CH": "de", "CI": "fr", "SN": "fr", "CM": "fr", "CD": "fr", "BJ": "fr",
    "BF": "fr", "ML": "fr", "HT": "fr", "MA": "ar", "DZ": "ar", "TN": "ar",
    "DE": "de", "AT": "de", "IT": "it", "NL": "nl", "SE": "sv", "NO": "nb", "DK": "da", "FI": "fi",
    "PL": "pl", "CZ": "cs", "SK": "sk", "HU": "hu", "RO": "ro", "MD": "ro", "BG": "bg", "GR": "el",
    "CY": "el", "HR": "hr", "RS": "sr", "BA": "bs", "SI": "sl", "MK": "mk", "AL": "sq", "LT": "lt",
    "LV": "lv", "EE": "et", "UA": "uk", "BY": "ru", "RU": "ru", "KZ": "ru", "KG": "ru", "UZ": "uz",
    "TM": "tk", "AZ": "az", "AM": "hy", "GE": "ka", "TR": "tr", "IL": "he", "IR": "fa",
    "SA": "ar", "AE": "ar", "EG": "ar", "IQ": "ar", "JO": "ar", "KW": "ar", "QA": "ar", "OM": "ar",
    "BH": "ar", "LB": "ar", "SY": "ar", "LY": "ar", "YE": "ar", "PS": "ar",
    "ET": "am", "TZ": "sw",
}

NON_NAME_WORDS = set("""
how what when where why who whom which is are does do did can will should near me today tonight tomorrow
yesterday hoy hoje manana amanha heute morgen aujourd hui oggi domani live en vivo ao vivo directo score
scores result results resultado resultados news noticias noticia nachrichten weather clima tiempo meteo
prediction predictions pronostico highlights schedule horario tickets stock price precio preco update
vs v x como que quando onde cuando donde quien wie was wer wann quand comment pourquoi perche come cosa
game partido jogo match spiel juego ver watch stream online free gratis login app download near
ضد مباراة مباشر พบ против матч прямая
""".split())
_HAS_DIGIT = re.compile(r"\d")
_CJK = re.compile(r"[぀-ヿ㐀-鿿가-힯]")


def looks_like_name(q: str) -> bool:
    if not q or _HAS_DIGIT.search(q) or len(q) < 3 or len(q) > 40:
        return False
    toks = q.split()
    if _CJK.search(q):
        return len(q) <= 12 and len(toks) <= 3
    if not 1 <= len(toks) <= 4:
        return False
    return not any(t in NON_NAME_WORDS for t in toks)


def langs_for(countries):
    out = []
    for cc in countries:
        lang = COUNTRY_LANG.get(cc, "en")
        if lang not in out:
            out.append(lang)
        if len(out) == MAX_LANGS:
            break
    return out or ["en"]


def cache_path(lang, query):
    h = hashlib.sha1(query.encode()).hexdigest()
    return CACHE / "wikidata" / lang / h[:2] / f"{h}.json"


_lock = threading.Lock()
_next_slot = [0.0]
_session = threading.local()
_stats = {"429": 0}


def _throttle():
    with _lock:
        now = time.time()
        wait = _next_slot[0] - now
        _next_slot[0] = max(now, _next_slot[0]) + 1.0 / MAX_RPS
    if wait > 0:
        time.sleep(wait)


def search(lang, query):
    p = cache_path(lang, query)
    if p.exists():
        return json.loads(p.read_text())
    params = {"action": "wbsearchentities", "search": query, "language": lang, "uselang": lang,
              "type": "item", "limit": 7, "format": "json", "maxlag": 5}
    data = _get(params)
    if data is not None:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, ensure_ascii=False))
    return data


def _get(params):
    """One polite API GET: global throttle, global pause on 429/maxlag, backoff on 5xx.
    Returns the JSON (API errors as {"search": [], "error": code}) or None after 6 attempts."""
    if not hasattr(_session, "s"):
        _session.s = requests.Session()
        _session.s.headers["User-Agent"] = user_agent()
    for attempt in range(6):
        _throttle()
        try:
            r = _session.s.get(API, params=params, timeout=30)
        except requests.RequestException:
            time.sleep(2 ** attempt)
            continue
        if r.status_code == 429 or (r.ok and '"maxlag"' in r.text[:200]):
            pause = float(r.headers.get("Retry-After", 5)) + random.random()
            with _lock:  # global pause: push everyone's next slot past the Retry-After
                _next_slot[0] = max(_next_slot[0], time.time() + pause)
            _stats["429"] += 1
            continue
        if r.status_code >= 500:
            time.sleep(2 ** attempt)
            continue
        data = r.json()
        if "error" in data:  # e.g. unsupported language code: cache so we do not retry forever
            data = {"search": [], "error": data["error"].get("code")}
        return data
    return None  # give up for now (not cached; will be retried on the next run)


BAD_DESC = ("disambiguation page", "wikimedia category", "wikimedia list", "wikimedia template",
            "wikinews article", "scholarly article", "wikimedia project page")


def best_match(qnorm, data):
    """Return (qid, label, description, n_strong, candidates)."""
    cands, strong = [], []
    for r in (data or {}).get("search", []):
        desc = (r.get("description") or "")
        if any(b in desc.lower() for b in BAD_DESC):
            continue
        cands.append({"id": r["id"], "label": r.get("label"), "description": desc})
        m = r.get("match", {})
        if m.get("type") in ("label", "alias") and norm(m.get("text", "")) == qnorm:
            strong.append(r)
    if not strong:
        return None, None, None, 0, cands
    r = strong[0]
    return r["id"], r.get("label"), r.get("description"), len(strong), cands


def lookup(row):
    q, countries = row
    for lang in langs_for(countries):
        data = search(lang, q)
        if data is None:
            return {"query_norm": q, "status": "failed"}
        qid, label, desc, n_strong, cands = best_match(q, data)
        if qid:
            return {"query_norm": q, "status": "ok", "wd_qid": qid, "wd_label": label, "wd_desc": desc,
                    "wd_lang": lang, "wd_n_strong": n_strong, "wd_candidates": json.dumps(cands, ensure_ascii=False)}
        last = cands
    return {"query_norm": q, "status": "no_match", "wd_candidates": json.dumps(last, ensure_ascii=False)}


def run(s: pd.DataFrame, scope="important"):
    """scope: 'test' (Claude test sample only), 'important', or 'all' name-like strings."""
    from claude_label import test_sample_ids
    s = s.copy()
    s["name_like"] = s.query_norm.map(looks_like_name)
    test_ids = set(test_sample_ids(s))
    s["prio"] = 2
    s.loc[s.important, "prio"] = 1
    s.loc[s.sid.isin(test_ids), "prio"] = 0
    todo = s[s.name_like].sort_values(["prio", "vol_sum"], ascending=[True, False])
    todo = todo[todo.prio <= {"test": 0, "important": 1, "all": 2}[scope]]
    print(f"name-like strings: {s.name_like.sum():,} "
          f"(important: {(s.name_like & s.important).sum():,}); looking up {len(todo):,}")
    rows, t0 = [], time.time()
    with ThreadPoolExecutor(WORKERS) as ex:
        for i, res in enumerate(ex.map(lookup, zip(todo.query_norm, todo.countries))):
            rows.append(res)
            if i % 5000 == 0:
                ok = sum(r["status"] == "ok" for r in rows)
                print(f"  {i:,}/{len(todo):,}  matched {ok:,}  429s {_stats['429']}  ({time.time()-t0:.0f}s)", flush=True)
    out = pd.DataFrame(rows)
    out["scope"] = scope
    out.to_parquet(WORK / "wikidata_links.parquet", index=False)
    print(out.status.value_counts().to_string())


# ============================================================================================
# Verification of Claude's QIDs (wbgetentities, 50 ids per request) and English-name lookup.
# ============================================================================================
ENT_DIR = CACHE / "wikidata" / "entities"
# API limit is 50 languages: all trending-country languages + "mul" (Wikidata's multilingual label,
# where many person names now live), minus Turkmen and Uzbek (rare in this data)
ALL_LANGS = sorted({"en", "mul", *COUNTRY_LANG.values()} - {"tk", "uz"})
assert len(ALL_LANGS) <= 50
LOOKUP_TYPES = ("person", "team", "place", "company")
MIN_CONF = 0.5            # labels below this never create or block merges (so are never looked up)
CLAUDE_QID_MIN_CONF = 0.7  # a Claude QID is used only at this confidence and only if verified
NAME_RATIO = 90            # fuzz.ratio between Claude's name and a label/alias to count as a name match
_PAREN = re.compile(r"\s*\(([^)]*)\)\s*")


def _ent_path(qid):
    return ENT_DIR / qid[-2:] / f"{qid}.json"


def get_entities(qids):
    """{requested_qid: entity or {"missing": True}}. Redirects are followed. Cached per QID."""
    qids = sorted(set(qids))
    todo = [q for q in qids if not _ent_path(q).exists()]
    for k in range(0, len(todo), 50):
        chunk = todo[k:k + 50]
        data = _get({"action": "wbgetentities", "ids": "|".join(chunk), "props": "labels|aliases|descriptions",
                     "languages": "|".join(ALL_LANGS), "redirects": "yes", "format": "json", "maxlag": 5})
        if data is None or "entities" not in data:
            print(f"  wbgetentities failed for {chunk[0]}..; will retry on the next run")
            continue
        ents = data["entities"]
        by_from = {}
        for key, e in ents.items():
            red = e.get("redirects")
            if red:
                by_from[red["from"]] = e
        for q in chunk:
            e = ents.get(q) or by_from.get(q) or {"missing": True}
            if "missing" in e:
                e = {"id": q, "missing": True}
            p = _ent_path(q)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(e, ensure_ascii=False))
        if (k // 50) % 20 == 0:
            print(f"  wbgetentities {k + len(chunk):,}/{len(todo):,}", flush=True)
    return {q: json.loads(_ent_path(q).read_text()) for q in qids if _ent_path(q).exists()}


def _names(e):
    out = {norm(v["value"]) for v in (e.get("labels") or {}).values()}
    for vals in (e.get("aliases") or {}).values():
        out |= {norm(v["value"]) for v in vals}
    return out - {""}


def _en(e, field):
    d = e.get(field) or {}
    v = d.get("en") or d.get("mul") or next(iter(d.values()), None)
    return v["value"] if v else None


def verify_claude_qids(lab):
    """Check every QID Claude gave. status: verified | low_conf | missing | bad_item | name_mismatch."""
    from rapidfuzz import fuzz
    c = lab[lab.wikidata_qid.notna()].copy()
    print(f"Claude QIDs to verify: {len(c):,} strings, {c.wikidata_qid.nunique():,} distinct ids "
          f"({-(-c.wikidata_qid.nunique() // 50)} requests)")
    ents = get_entities(c.wikidata_qid.unique())
    rows = []
    for q, r in c.iterrows():
        e = ents.get(r.wikidata_qid)
        if e is None:
            st = "failed"
        elif e.get("missing"):
            st = "missing"
        elif any(b in (_en(e, "descriptions") or "").lower() for b in BAD_DESC):
            st = "bad_item"
        else:
            names = _names(e)
            cn = norm(_PAREN.sub(" ", r.canonical_en))
            ok = q in names or cn in names or any(fuzz.ratio(cn, n) >= NAME_RATIO for n in names)
            st = "name_mismatch" if not ok else ("verified" if r.confidence >= CLAUDE_QID_MIN_CONF else "low_conf")
        rows.append({"query_norm": q, "claude_qid": r.wikidata_qid, "status": st,
                     "qid": (e or {}).get("id") if st == "verified" else None,   # redirect target
                     "wd_label": _en(e, "labels") if e and not e.get("missing") else None,
                     "wd_desc": _en(e, "descriptions") if e and not e.get("missing") else None})
    out = pd.DataFrame(rows)
    out.to_parquet(WORK / "wikidata_claude_check.parquet", index=False)
    print(out.status.value_counts().to_string())
    return out


def name_lookup_todo(s, lab, checked):
    """Deduplicated English names to search: important strings typed person/team/place/company,
    confidence >= MIN_CONF, not 'unknown', without a verified QID."""
    imp = set(s.query_norm[s.important])
    verified = set(checked.query_norm[checked.status == "verified"]) if len(checked) else set()
    l = lab[lab.index.isin(imp) & lab.type.isin(LOOKUP_TYPES) & (lab.confidence >= MIN_CONF)
            & (lab.canonical_en.str.lower() != "unknown") & ~lab.index.isin(verified)]
    return l, sorted(set(l.canonical_en.str.strip()))


def _match_name(name, data):
    """First strong (exact label/alias) English match. A parenthetical in Claude's name, e.g.
    'Georgia (country)', must appear in the item's description."""
    base = _PAREN.sub(" ", name).strip()
    paren = [norm(x) for x in _PAREN.findall(name)]
    target = norm(base)
    for r in (data or {}).get("search", []):
        desc = r.get("description") or ""
        if any(b in desc.lower() for b in BAD_DESC):
            continue
        m = r.get("match", {})
        if m.get("type") in ("label", "alias") and norm(m.get("text", "")) == target:
            if paren and not all(p and p in norm(desc) for p in paren):
                continue
            return r["id"], r.get("label"), desc
    return None, None, None


def lookup_names(s, lab, checked, estimate_only=False):
    l, names = name_lookup_todo(s, lab, checked)
    # names that failed from rate limiting in the 2026-11 run are final "no ID": never retried
    prev_p = WORK / "wikidata_name_lookup.parquet"
    frozen = set()
    if prev_p.exists():
        prev = pd.read_parquet(prev_p)
        frozen = set(prev.name[prev.status == "no_id_rate_limited"])
    todo = [n for n in names if n not in frozen and not cache_path("en", _PAREN.sub(" ", n).strip()).exists()]
    hrs = len(todo) / MAX_RPS / 3600
    print(f"name lookup: {len(l):,} strings -> {len(names):,} distinct English names; "
          f"{len(todo):,} not cached; at {MAX_RPS:g} req/s about {hrs:.1f} h")
    if estimate_only:
        return None
    t0, res = time.time(), {}
    for i, n in enumerate(names):
        if n in frozen:
            res[n] = "frozen"
            continue
        data = search("en", _PAREN.sub(" ", n).strip())
        res[n] = _match_name(n, data) if data is not None else None
        if i % 2000 == 0:
            print(f"  {i:,}/{len(names):,}  matched {sum(1 for v in res.values() if v and v[0]):,}  "
                  f"429s {_stats['429']}  ({time.time()-t0:.0f}s)", flush=True)
    rows = []
    for q, r in l.iterrows():
        m = res.get(r.canonical_en.strip())
        if m == "frozen":
            rows.append({"query_norm": q, "name": r.canonical_en.strip(), "status": "no_id_rate_limited",
                         "qid": None, "wd_label": None, "wd_desc": None})
            continue
        rows.append({"query_norm": q, "name": r.canonical_en.strip(),
                     "status": "failed" if m is None else ("ok" if m[0] else "no_match"),
                     "qid": m[0] if m else None, "wd_label": m[1] if m else None, "wd_desc": m[2] if m else None})
    out = pd.DataFrame(rows)
    out.to_parquet(WORK / "wikidata_name_lookup.parquet", index=False)
    print(out.status.value_counts().to_string())
    return out


def run_v2(s, step, estimate_only=False):
    """step: 'verify' (Claude QIDs) or 'names' (English-name lookup). Writes work/wikidata_qids.parquet,
    the per-string QIDs used by combine."""
    from claude_label import load_labels
    lab = pd.DataFrame(load_labels().values()).set_index("query_norm")
    chk_p = WORK / "wikidata_claude_check.parquet"
    if step == "verify":
        checked = verify_claude_qids(lab)
    else:
        checked = pd.read_parquet(chk_p) if chk_p.exists() else pd.DataFrame(columns=["query_norm", "status"])
        if lookup_names(s, lab, checked, estimate_only) is None:
            return
    parts = []
    if chk_p.exists():
        c = pd.read_parquet(chk_p)
        parts.append(c[c.status == "verified"].assign(qid_source="claude_verified"))
    nl_p = WORK / "wikidata_name_lookup.parquet"
    if nl_p.exists():
        n = pd.read_parquet(nl_p)
        parts.append(n[n.status == "ok"].assign(qid_source="name_lookup"))
    q = pd.concat(parts)[["query_norm", "qid", "wd_label", "wd_desc", "qid_source"]].drop_duplicates("query_norm")
    q.to_parquet(WORK / "wikidata_qids.parquet", index=False)
    print(f"wrote {WORK/'wikidata_qids.parquet'}: {len(q):,} strings with a QID "
          f"({q.qid_source.value_counts().to_dict()})")
