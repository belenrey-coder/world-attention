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
over-sampled), so recall here is an estimate on hard cases, not the population recall.
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
    if len(bad):
        print("\ndisagreements:")
        print(bad.to_string(index=False))


if __name__ == "__main__":
    main()
