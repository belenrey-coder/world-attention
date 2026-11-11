"""Step 3: merge every way of searching for the same thing -> data/interim/topics.parquet

Runs in stages so expensive work is cached and the Claude step can pause for approval:

Usage:
  python pipeline/03_topics.py strings      # distinct-string table + importance flags
  python pipeline/03_topics.py typos        # (a) exact + fuzzy (rapidfuzz) merges in 3-day windows
  python pipeline/03_topics.py embed        # (c) e5 embeddings, computed once -> cache/embeddings/
  python pipeline/03_topics.py semantic     # (c) embedding merges with related-search evidence
  python pipeline/03_topics.py wikidata-verify  # (b) after Claude: check Claude's QIDs (wbgetentities)
  python pipeline/03_topics.py wikidata-names [--estimate]  # (b) look up English names of entities
  python pipeline/03_topics.py claude-test  # (d) 500-string test batch, then STOP
  python pipeline/03_topics.py claude-full  # (d) the rest (only after approval)
  python pipeline/03_topics.py combine      # (e) topic_id/topic_name -> topics.parquet
  python pipeline/03_topics.py validation   # (f) docs/validation_sample.csv (never overwrites hand labels)
  python pipeline/03_topics.py validation-v3  # (f) fresh docs/validation_sample_v3.csv (key git-ignored)
"""
import sys
import time
import warnings
from collections import Counter
from pathlib import Path

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import pyarrow.compute as pc
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).parent))
from common import (  # noqa: E402
    CACHE,
    DOCS,
    GENERIC_DEGREE,
    IMPORTANT_TOP_PCT,
    INTERIM,
    MANUAL_GENERIC,
    SEM_HIGH,
    SEM_LOW,
    TYPO_MIN_LEN,
    TYPO_RATIO,
    WINDOW_DAYS,
    WORK,
    UnionFind,
    digit_sig,
    load_json,
    save_json,
)

STR_PATH = WORK / "strings.parquet"
EMB_PATH = CACHE / "embeddings" / "e5_small_f16.npy"
EMB_KEYS = CACHE / "embeddings" / "e5_small_keys.txt"


# ---------------------------------------------------------------- strings
def stage_strings():
    t = pq.read_table(
        INTERIM / "trends.parquet",
        columns=[
            "query_raw",
            "query_norm",
            "country_code",
            "start_time_utc",
            "search_volume_lower",
            "related",
        ],
    )
    df = t.select(
        ["query_raw", "query_norm", "country_code", "start_time_utc", "search_volume_lower"]
    ).to_pandas()
    df["day"] = (
        df.start_time_utc.dt.tz_convert("UTC").dt.tz_localize(None) - pd.Timestamp("1970-01-01")
    ).dt.days
    g = df.groupby("query_norm", sort=True)
    s = pd.DataFrame(
        {
            "n_rows": g.size(),
            "vol_sum": g.search_volume_lower.sum(),
            "n_countries": g.country_code.nunique(),
            "first_day": g.day.min(),
            "last_day": g.day.max(),
        }
    )
    s["top_raw"] = (
        df.groupby(["query_norm", "query_raw"])
        .size()
        .reset_index()
        .sort_values(0)
        .drop_duplicates("query_norm", keep="last")
        .set_index("query_norm")["query_raw"]
    )
    cc = (
        df.groupby(["query_norm", "country_code"])
        .size()
        .rename("n")
        .reset_index()
        .sort_values(["query_norm", "n"], ascending=[True, False])
    )
    s["countries"] = cc.groupby("query_norm").country_code.agg(list)
    s["days"] = df.groupby("query_norm").day.agg(lambda x: sorted(set(x)))

    # importance: >=2 countries OR in a country's top 1% by summed volume
    cv = (
        df.groupby(["country_code", "query_norm"])
        .search_volume_lower.sum()
        .rename("v")
        .reset_index()
    )
    cv["rank_pct"] = cv.groupby("country_code").v.rank(
        ascending=False, pct=True, method="first"
    )
    top = set(cv.loc[cv.rank_pct <= IMPORTANT_TOP_PCT, "query_norm"])
    s["top1pct"] = s.index.isin(top)
    s["important"] = (s.n_countries >= 2) | s.top1pct

    # related searches: frequency per (string, term) over rows; generic = seen with many distinct trends
    r = t.column("related")
    idx = pc.list_parent_indices(r).to_numpy()
    e = pd.DataFrame(
        {
            "q": t.column("query_norm").take(idx).to_numpy(zero_copy_only=False),
            "term": pc.list_flatten(r).to_numpy(zero_copy_only=False),
        }
    )
    e = e[e.q != e.term]
    e = e.groupby(["q", "term"]).size().rename("n").reset_index()
    deg = e.groupby("term").q.size()
    generic = set(deg[deg >= GENERIC_DEGREE].index) | MANUAL_GENERIC
    pd.Series(sorted(generic)).to_csv(
        WORK / "generic_related.csv", index=False, header=["term"]
    )
    e = e.sort_values(["q", "n"], ascending=[True, False])
    s["related_top"] = e.groupby("q").head(10).groupby("q").term.agg(list)
    ev = e[~e.term.isin(generic)]
    s["related_ev"] = ev.groupby("q").head(30).groupby("q").term.agg(list)
    for c in ("related_top", "related_ev"):
        s[c] = s[c].apply(lambda x: x if isinstance(x, list) else [])
    s["is_generic_term"] = s.index.isin(generic)
    s = s.reset_index().rename(columns={"index": "query_norm"})
    s["sid"] = np.arange(len(s))
    s.to_parquet(STR_PATH, index=False)
    print(
        f"distinct strings {len(s):,}; important {s.important.sum():,} "
        f"(>=2 countries {(s.n_countries >= 2).sum():,}, top1% {s.top1pct.sum():,}); "
        f"generic related terms blocked: {len(generic):,}"
    )


def load_strings():
    return pd.read_parquet(STR_PATH)


def day_index(s):
    """day -> np.array of sids active that day."""
    ex = s[["sid", "days"]].explode("days")
    ex["days"] = ex["days"].astype(int)
    return {d: g.sid.to_numpy() for d, g in ex.groupby("days")}


def windows(dmap):
    """Yield (Q, C): strings on day d vs strings on days d..d+WINDOW_DAYS."""
    for d in sorted(dmap):
        Q = dmap[d]
        C = np.unique(
            np.concatenate([dmap[x] for x in range(d, d + WINDOW_DAYS + 1) if x in dmap])
        )
        yield d, Q, C


# ---------------------------------------------------------------- (a) typos
CONNECTORS = {
    "vs",
    "v",
    "x",
    "versus",
    "contra",
    "mot",
    "gegen",
    "contre",
    "vs.",
    "-",
    "y",
    "e",
    "and",
}
MATCH_WORDS = {
    "vs",
    "v",
    "x",
    "versus",
    "contra",
    "mot",
    "gegen",
    "contre",
    "lwn",
    "voi",
    "ضد",
    "พบ",
    "против",
    "対",
}


def is_match(q: str) -> bool:
    return any(t in MATCH_WORDS for t in q.split())


def typo_ok(a: str, b: str) -> str:
    """Token-level guard on a fuzzy pair. Returns reason accepted, or '' if rejected.

    Accept: identical once spaces/connector words are removed; single token changed slightly;
    or tokens added with <= 3 extra characters. Reject short-token swaps.
    """
    from rapidfuzz import fuzz

    ta = [t for t in a.split() if t not in CONNECTORS]
    tb = [t for t in b.split() if t not in CONNECTORS]
    if "".join(ta) == "".join(tb):
        return "spacing_or_connector"
    ca, cb = Counter(ta), Counter(tb)
    only_a, only_b = list((ca - cb).elements()), list((cb - ca).elements())
    if len(only_a) == 1 and len(only_b) == 1:
        x, y = only_a[0], only_b[0]
        if min(len(x), len(y)) >= 4 and fuzz.ratio(x, y) >= 80:
            return "one_token_spelling"
        return ""
    if not only_a or not only_b:
        extra = only_a or only_b
        if sum(len(t) for t in extra) <= 3:
            return "short_token_added"
    return ""


def stage_typos():
    from rapidfuzz import fuzz, process

    raw_path = WORK / "edges_typo_raw.parquet"
    s = load_strings()
    if raw_path.exists():
        out = pd.read_parquet(raw_path)
        print(f"reusing {raw_path.name}: {len(out):,} raw fuzzy pairs")
    else:
        out = _typo_pairs(s, fuzz, process)
        out.to_parquet(raw_path, index=False)
    texts = s.query_norm.values
    out["reason"] = [typo_ok(texts[a], texts[b]) for a, b in zip(out.a, out.b)]
    kept = out[out.reason != ""]
    kept.to_parquet(WORK / "edges_typo.parquet", index=False)
    print(f"fuzzy pairs {len(out):,}; kept after token guard {len(kept):,}")
    print(kept.reason.value_counts().to_string())


def _typo_pairs(s, fuzz, process):
    texts = s.query_norm.tolist()
    sig = [digit_sig(x) for x in texts]
    dmap = day_index(s)
    pairs = {}
    t0 = time.time()
    for i, (d, Q, C) in enumerate(windows(dmap)):
        Q = Q[[len(texts[q]) >= TYPO_MIN_LEN for q in Q]]
        C = C[[len(texts[c]) >= TYPO_MIN_LEN for c in C]]
        if len(Q) == 0 or len(C) == 0:
            continue
        m = process.cdist(
            [texts[q] for q in Q],
            [texts[c] for c in C],
            scorer=fuzz.ratio,
            score_cutoff=TYPO_RATIO,
            dtype=np.uint8,
            workers=-1,
        )
        for qi, ci in zip(*np.nonzero(m)):
            a, b = int(Q[qi]), int(C[ci])
            if a == b or sig[a] != sig[b]:
                continue
            key = (min(a, b), max(a, b))
            pairs[key] = max(pairs.get(key, 0), int(m[qi, ci]))
        if i % 50 == 0:
            print(
                f"  day {i}/{len(dmap)}  pairs so far {len(pairs):,}  ({time.time()-t0:.0f}s)"
            )
    return pd.DataFrame(
        [(a, b, sc) for (a, b), sc in pairs.items()], columns=["a", "b", "score"]
    )


# ---------------------------------------------------------------- (c) embeddings
def stage_embed():
    import torch
    from sentence_transformers import SentenceTransformer

    s = load_strings()
    keys = s.query_norm.tolist()
    if EMB_PATH.exists() and EMB_KEYS.read_text().split("\n") == keys:
        print("embeddings already computed; skipping")
        return
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    model = SentenceTransformer("intfloat/multilingual-e5-small", device=device)
    order = np.argsort([len(k) for k in keys])
    emb = np.zeros((len(keys), 384), dtype=np.float16)
    bs, t0 = 1024, time.time()
    for i in range(0, len(order), bs):
        ids = order[i : i + bs]
        v = model.encode(
            [f"query: {keys[j]}" for j in ids],
            batch_size=bs,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        emb[ids] = v.astype(np.float16)
        if (i // bs) % 100 == 0:
            print(f"  {i:,}/{len(keys):,} ({time.time()-t0:.0f}s)")
    np.save(EMB_PATH, emb)
    EMB_KEYS.write_text("\n".join(keys))
    print(f"saved {EMB_PATH} {emb.shape} on {device} in {time.time()-t0:.0f}s")


def evidence(a, b, texts, rel_top, rel_ev, generic):
    """Related-search evidence between strings a and b (generic terms never count)."""
    direct = (texts[b] not in generic and texts[b] in rel_top[a]) or (
        texts[a] not in generic and texts[a] in rel_top[b]
    )
    shared = len(rel_ev[a] & rel_ev[b])
    return direct, shared


def semantic_candidates(cos_min):
    s = load_strings()
    emb = np.load(EMB_PATH).astype(np.float32)
    dmap = day_index(s)
    seen = {}
    for d, Q, C in windows(dmap):
        sims = emb[Q] @ emb[C].T
        qi, ci = np.nonzero(sims >= cos_min)
        for x, y in zip(qi, ci):
            a, b = int(Q[x]), int(C[y])
            if a == b:
                continue
            k = (min(a, b), max(a, b))
            seen[k] = max(seen.get(k, 0.0), float(sims[x, y]))
    return s, seen


def swap_guard(a: str, b: str) -> str:
    """Classify how a and b differ at the word level."""
    from rapidfuzz import fuzz

    ta = Counter(t for t in a.split() if t not in CONNECTORS)
    tb = Counter(t for t in b.split() if t not in CONNECTORS)
    only_a, only_b = list((ta - tb).elements()), list((tb - ta).elements())
    if not only_a and not only_b:
        return "same_words"
    if not only_a or not only_b:
        if is_match(a) != is_match(b):
            return ""
        if len(only_a) + len(only_b) > 1:
            return ""
        return "added_words"
    ok = all(max(fuzz.ratio(x, y) for y in only_b) >= 75 for x in only_a) and all(
        max(fuzz.ratio(y, x) for x in only_a) >= 75 for y in only_b
    )
    return "similar_words" if ok else ""


def is_hub(q: str, generic: set) -> bool:
    """Strings too short or generic to anchor a meaning merge."""
    return len(q) < 4 or q.replace(" ", "").isdigit() or q in generic


def stage_semantic():
    s, cand = semantic_candidates(SEM_LOW)
    texts = s.query_norm.tolist()
    sig = [digit_sig(x) for x in texts]
    rel_top = [set(x) for x in s.related_top]
    rel_ev = [set(x) for x in s.related_ev]
    generic = set(pd.read_csv(WORK / "generic_related.csv").term)
    rows = []
    for (a, b), cos in cand.items():
        direct, shared = evidence(a, b, texts, rel_top, rel_ev, generic)
        same_num = sig[a] == sig[b]
        guard = swap_guard(texts[a], texts[b])
        hub = is_hub(texts[a], generic) or is_hub(texts[b], generic)
        rule = None
        if not same_num or hub:
            rule = None
        elif cos >= SEM_HIGH and guard in ("same_words", "similar_words"):
            rule = "high_cos+guard"
        elif cos >= SEM_HIGH and guard == "added_words" and (direct or shared >= 2):
            rule = "high_cos+added_words+related"
        elif direct and (guard in ("same_words", "similar_words") or shared >= 2):
            rule = "cos+related_link"
        rows.append((a, b, cos, direct, shared, same_num, guard, hub, rule))
    out = pd.DataFrame(
        rows,
        columns=[
            "a",
            "b",
            "cos",
            "direct",
            "shared",
            "same_num",
            "guard",
            "hub",
            "rule",
        ],
    )
    out.to_parquet(WORK / "semantic_candidates.parquet", index=False)
    acc = out[out.rule.notna()]
    acc.to_parquet(WORK / "edges_semantic.parquet", index=False)
    print(f"semantic candidates (cos>={SEM_LOW}): {len(out):,}; accepted: {len(acc):,}")
    print(acc.rule.value_counts().to_string())


# ---------------------------------------------------------------- dispatch
if __name__ == "__main__":
    stage = sys.argv[1] if len(sys.argv) > 1 else ""
    if stage == "strings":
        stage_strings()
    elif stage == "typos":
        stage_typos()
    elif stage == "embed":
        stage_embed()
    elif stage == "semantic":
        stage_semantic()
    elif stage == "wikidata":
        from wikidata import run as wd_run

        wd_run(load_strings(), scope=sys.argv[2] if len(sys.argv) > 2 else "important")
    elif stage in ("wikidata-verify", "wikidata-names"):
        from wikidata import run_v2

        run_v2(
            load_strings(), stage.split("-")[1], estimate_only="--estimate" in sys.argv
        )
    elif stage in ("claude-test", "claude-full", "claude-retry"):
        from claude_label import run as cl_run

        cl_run(load_strings(), mode=stage.split("-")[1])
    elif stage == "combine":
        from combine import run as cb_run

        cb_run()
    elif stage == "link":
        from link import run as link_run

        link_run()
    elif stage == "validation":
        from combine import validation_sample

        validation_sample()
    elif stage == "validation-v3":
        from combine import validation_sample_v3

        validation_sample_v3()
    else:
        print(__doc__)