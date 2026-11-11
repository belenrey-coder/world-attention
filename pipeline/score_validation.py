"""Score the hand-labelled validation sample.

1. Open docs/validation_sample.csv and fill `same_topic_label` with 1 (same topic) or 0 (different).
   Leave a row blank to skip it. Don't open docs/validation_key.csv until you're done.
2. Run:  python pipeline/score_validation.py        (docs/validation_sample.csv)
         python pipeline/score_validation.py v3     (docs/validation_sample_v3.csv + validation_key_v3.csv)

Predictions are recomputed from the CURRENT topics (data/interim/work/string_topics.parquet, by the
pair's string ids), so the score follows the pipeline; the predictions frozen in the key when the
sample was drawn are scored too, for comparison.

Precision = labelled-same among pairs the pipeline merged.
Recall    = pipeline-merged among pairs you labelled same.
The sample is half predicted-same and half predicted-different (with hard negatives
over-sampled), so the raw (unweighted) recall is an estimate on hard cases, not the population recall.

POPULATION ESTIMATE: each sampling group ("stratum") is weighted by how many pairs of that kind exist
in the full set of pairs the pipeline could merge (string pairs that trended within the 3-day window),
counted from the current topics under the same restrictions the sampler used (v3: Latin script, plus the
Arabic/Cyrillic match strata). Weighted precision = sum_h N_h * TP_h/n_h / sum_h N_h * PP_h/n_h, weighted
recall = sum_h N_h * TP_h/n_h / sum_h N_h * S_h/n_h (PP = predicted same, S = labelled same).
Caveats: stratum sizes come from today's topics, not the topics at draw time; within a stratum the
sampler was not uniform (same-topic pairs were drawn topic-first); and a few dozen random negatives
cannot see rare missed pairs among billions, so the recall estimate is an upper bound.
"""
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
TOPICS = ROOT / "data" / "interim" / "work" / "string_topics.parquet"


def score(df, col, title):
    y, p = df.same_topic_label.astype(bool), df[col].astype(bool)
    tp, fp, fn, tn = (y & p).sum(), (~y & p).sum(), (y & ~p).sum(), (~y & ~p).sum()
    prec = tp / (tp + fp) if tp + fp else float("nan")
    rec = tp / (tp + fn) if tp + fn else float("nan")
    print(f"{title}: labelled pairs {len(df)}  (TP {tp}, FP {fp}, FN {fn}, TN {tn})  "
          f"precision {prec:.3f}  recall {rec:.3f}")
    return y, p


def stratum_sizes(version):
    """N_h: pairs of each sampling kind in the full set of pairs (see module docstring)."""
    import numpy as np
    W = ROOT / "data" / "interim" / "work"
    st = pd.read_parquet(TOPICS, columns=["sid", "topic_id", "top_raw", "type", "linked"])
    s = pd.read_parquet(W / "strings.parquet", columns=["sid", "first_day"])
    st = st.merge(s, on="sid")
    st["linked"] = st.linked.fillna(False).astype(bool)
    cand = pd.read_parquet(W / "semantic_candidates.parquet", columns=["a", "b"])
    tid = st.set_index("sid").topic_id

    def sizes(pool, cand_mask):
        n_t = pool.groupby("topic_id").size()
        lk = pool[pool.linked].groupby("topic_id").size()
        nl = pool[~pool.linked].groupby("topic_id").size()
        linked = float((lk * nl.reindex(lk.index).fillna(0)).sum())
        same = float((n_t * (n_t - 1) / 2).sum()) - linked
        c = cand[cand_mask(cand)]
        hard = float((c.a.map(tid).values != c.b.map(tid).values).sum())
        d = pool.first_day.value_counts()
        win = float(sum(n * (n - 1) / 2 + n * (d.get(k + 1, 0) + d.get(k + 2, 0)) for k, n in d.items()))
        return {"same_topic": same, "linked": linked, "hard_negative": hard,
                "random_negative": max(win - same - linked - hard, 0.0)}
    if version != "v3":
        return sizes(st, lambda c: np.ones(len(c), dtype=bool))
    latin = st.top_raw.fillna("").str.match(r"^[\u0000-\u024F\u1E00-\u1EFF\u2000-\u206F]+$")
    lat = st[latin]
    ls = set(lat.sid)
    out = sizes(lat, lambda c: c.a.isin(ls).to_numpy() & c.b.isin(ls).to_numpy())
    sm = st[st["type"] == "sports_match"]
    ac = sm[sm.top_raw.fillna("").str.contains(r"[\u0600-\u06FF\u0400-\u04FF]")]
    sm_n = sm.groupby("topic_id").size()
    ac_n = ac.groupby("topic_id").size()
    out["arabic_cyrillic_match_same"] = float((ac_n * (sm_n.reindex(ac_n.index) - 1)).clip(lower=0).sum())
    acs, sms = set(ac.sid), set(sm.sid)
    c = cand[(cand.a.isin(acs) | cand.b.isin(acs)) & cand.a.isin(sms) & cand.b.isin(sms)]
    out["arabic_cyrillic_match_hard_negative"] = float((c.a.map(tid).values != c.b.map(tid).values).sum())
    return out


def weighted(df, version):
    N = stratum_sizes(version)
    g = df.assign(y=df.same_topic_label.astype(bool), p=df.predicted_same.astype(bool))
    g = g.assign(tp=g.y & g.p).groupby("sampled_as").agg(n=("y", "size"), S=("y", "sum"), PP=("p", "sum"),
                                                            TP=("tp", "sum"))
    g["N_population"] = g.index.map(lambda h: N.get(h, 0.0))
    w = g.N_population / g.n
    prec = (w * g.TP).sum() / (w * g.PP).sum() if (w * g.PP).sum() else float("nan")
    rec = (w * g.TP).sum() / (w * g.S).sum() if (w * g.S).sum() else float("nan")
    print("\nPOPULATION ESTIMATE (strata weighted by their size in the full set of pairs):")
    print(g.assign(N_population=g.N_population.map("{:,.0f}".format)).to_string())
    print(f"  weighted precision {prec:.3f}   weighted recall {rec:.3f}   <- population estimate"
          + ("" if version == "v3" else " (not the final score: use v3)"))
    return prec, rec


def main():
    v = f"_{sys.argv[1]}" if len(sys.argv) > 1 else ""
    lab = pd.read_csv(DOCS / f"validation_sample{v}.csv")
    key = pd.read_csv(DOCS / f"validation_key{v}.csv")
    df = lab.merge(key, on="pair_id")
    df["same_topic_label"] = pd.to_numeric(df.same_topic_label, errors="coerce")
    df = df[df.same_topic_label.isin([0, 1])]
    if df.empty:
        print(f"No labelled rows yet: fill same_topic_label with 1 or 0 in docs/validation_sample{v}.csv")
        return
    score(df, "predicted_same", "frozen predictions (when drawn)")
    if TOPICS.exists() and {"sid_a", "sid_b"} <= set(df.columns):
        tid = pd.read_parquet(TOPICS, columns=["sid", "topic_id"]).set_index("sid").topic_id
        df["predicted_now"] = df.sid_a.map(tid).values == df.sid_b.map(tid).values
        y, p = score(df, "predicted_now", "current topics           ")
        df["predicted_same"] = df.predicted_now
    else:
        y, p = df.same_topic_label.astype(bool), df.predicted_same.astype(bool)
    print("\nby sampling stratum:")
    print(df.groupby("sampled_as").agg(n=("pair_id", "size"), labelled_same=("same_topic_label", "sum"),
                                       predicted_same=("predicted_same", "sum")).astype(int))
    bad = df[y != p][["pair_id", "string_a", "string_b", "same_topic_label", "predicted_same", "sampled_as"]]
    weighted(df, sys.argv[1] if len(sys.argv) > 1 else "")
    if len(bad):
        print("\ndisagreements:")
        print(bad.to_string(index=False))


if __name__ == "__main__":
    main()
