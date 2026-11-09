"""Score the hand-labelled validation sample.

1. Open docs/validation_sample.csv and fill `same_topic_label` with 1 (same topic) or 0 (different).
   Leave a row blank to skip it. Don't open docs/validation_key.csv until you're done.
2. Run:  python pipeline/score_validation.py

Precision = labelled-same among pairs the pipeline merged.
Recall    = pipeline-merged among pairs you labelled same.
The sample is half predicted-same and half predicted-different (with hard negatives
over-sampled), so recall here is an estimate on hard cases, not the population recall.
"""
from pathlib import Path

import pandas as pd

DOCS = Path(__file__).resolve().parents[1] / "docs"


def main():
    lab = pd.read_csv(DOCS / "validation_sample.csv")
    key = pd.read_csv(DOCS / "validation_key.csv")
    df = lab.merge(key, on="pair_id")
    df["same_topic_label"] = pd.to_numeric(df.same_topic_label, errors="coerce")
    df = df[df.same_topic_label.isin([0, 1])]
    if df.empty:
        print("No labelled rows yet: fill same_topic_label with 1 or 0 in docs/validation_sample.csv")
        return
    y, p = df.same_topic_label.astype(bool), df.predicted_same.astype(bool)
    tp, fp, fn, tn = (y & p).sum(), (~y & p).sum(), (y & ~p).sum(), (~y & ~p).sum()
    prec = tp / (tp + fp) if tp + fp else float("nan")
    rec = tp / (tp + fn) if tp + fn else float("nan")
    print(f"labelled pairs: {len(df)}  (TP {tp}, FP {fp}, FN {fn}, TN {tn})")
    print(f"precision: {prec:.3f}")
    print(f"recall:    {rec:.3f}")
    print("\nby sampling stratum:")
    print(df.groupby("sampled_as").apply(lambda g: pd.Series({
        "n": len(g), "labelled_same": int(g.same_topic_label.sum()), "predicted_same": int(g.predicted_same.sum())})))
    bad = df[y != p][["pair_id", "string_a", "string_b", "same_topic_label", "predicted_same", "sampled_as"]]
    if len(bad):
        print("\ndisagreements:")
        print(bad.to_string(index=False))


if __name__ == "__main__":
    main()
