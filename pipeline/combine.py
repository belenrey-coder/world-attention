"""Step 3(e) combine layers into topics, and 3(f) the hand-labelling validation sample.

Merge order (strongest evidence first), using union-find over distinct query_norm strings:
  1. same Wikidata QID            (exempt from the size cap)
  2. same Claude canonical_en      (confidence >= CANON_MIN_CONF, not "unknown"; exempt from the size cap)
  3. typo edges, best score first  (size-capped)
  4. semantic edges, best cosine first (size-capped)
Claude labels with confidence < MIN_CONF (0.5) may name a topic but never create or block a merge.
Typo edges are filtered first: strings of <= SHORT_TYPO_LEN (8) characters need ratio >= 96, and two
strings whose confident (>= 0.5) Claude names differ are never typo-merged.
Two groups with different QIDs are never merged (cannot-link). For the typo and semantic layers,
two groups whose confident Claude names (confidence >= CANON_BLOCK_CONF) are disjoint are not merged
either ('Atlético Madrid' vs 'Real Madrid vs Atlético Madrid'). Fuzzy/semantic unions that would
create a group larger than MAX_GROUP strings are refused, which stops chaining.

topic_id   = the group's QID if any, else its most common canonical_en, else its most common query_norm
topic_name = most common canonical_en in the group, else the Wikidata label, else the most common raw string
"""
import json
import random
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute  # noqa: F401  (pa.compute)
import pyarrow.parquet as pq

from common import DOCS, INTERIM, WORK, save_json

MAX_GROUP = 50
MIN_CONF = 0.5             # below this a Claude label only names a topic: it never creates or blocks merges
TYPO_NAME_BLOCK_CONF = 0.5  # typo edge dropped if both strings have Claude names this confident that differ
SHORT_TYPO_LEN = 8          # typo edges where either string has <= 8 characters ...
SHORT_TYPO_RATIO = 96       # ... need fuzz.ratio >= 96
CANON_MIN_CONF = 0.6
CLAUDE_QID_MIN_CONF = 0.7
CANON_BLOCK_CONF = 0.8
# Generic short strings ("real", "madrid", "mu", "cl", "liga"): a single-word string, or one with
# <= SHORT_GENERIC_LEN characters, may be in a multi-string topic only if Claude labelled that exact
# string with confidence >= SHORT_OWN_CONF and the topic's name, or its Wikidata ID is the topic's.
OVERRIDES = Path(__file__).parent / "overrides.csv"   # manual: string, action (detach|move), topic
SHORT_GENERIC_LEN = 4
SHORT_OWN_CONF = 0.8


def is_short_generic(q: str) -> bool:
    return len(q) <= SHORT_GENERIC_LEN or len(q.split()) == 1


class UF:
    def __init__(self, n):
        self.p = np.arange(n)
        self.size = np.ones(n, dtype=np.int64)
        self.label = [None] * n
        self.canon = [frozenset()] * n
        self.gated = np.zeros(n, dtype=bool)   # short/single-word strings
        self.own_name = [None] * n             # the string's own Claude name (conf >= SHORT_OWN_CONF), lowercased
        self.own_qid = [None] * n

    def gate_ok(self, x, other_root):
        """A gated string x may only join a group whose QID is x's QID or whose confident names include x's own name."""
        if not self.gated[x]:
            return True
        q, nm = self.own_qid[x], self.own_name[x]
        return (q is not None and q == self.label[other_root]) or (nm is not None and nm in self.canon[other_root])

    def find(self, x):
        p = self.p
        root = x
        while p[root] != root:
            root = p[root]
        while p[x] != root:
            p[x], x = root, p[x]
        return root

    def union(self, a, b, cap=None, use_canon=False, gate=False):
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return "same"
        la, lb = self.label[ra], self.label[rb]
        if la is not None and lb is not None and la != lb:
            return "cannot_link"
        ca, cb = self.canon[ra], self.canon[rb]
        if use_canon and ca and cb and not (ca & cb):
            return "claude_name_differs"
        if gate and not (self.gate_ok(a, rb) and self.gate_ok(b, ra)):
            return "short_generic"
        if cap is not None and self.size[ra] + self.size[rb] > cap:
            return "size_cap"
        if self.size[ra] < self.size[rb]:
            ra, rb = rb, ra
        self.p[rb] = ra
        self.size[ra] += self.size[rb]
        self.label[ra] = la if la is not None else lb
        self.canon[ra] = ca | cb
        return "merged"


def load_claude():
    from claude_label import load_labels
    lab = pd.DataFrame(load_labels().values())
    return lab.set_index("query_norm") if len(lab) else pd.DataFrame()


def string_qids(s, wd, lab):
    """Per-string QID from work/wikidata_qids.parquet: a Claude QID verified with wbgetentities
    (exists, not a disambiguation page, a label/alias matches Claude's name, confidence >= 0.7),
    else the strong English-name match from wbsearchentities. Claude QIDs that failed
    verification are kept as claude_qid_unverified and never used."""
    qid = pd.Series(None, index=s.query_norm, dtype=object)
    source = pd.Series(None, index=s.query_norm, dtype=object)
    if len(wd):
        wd = wd[wd.query_norm.isin(qid.index)]
        qid.loc[wd.query_norm] = wd.qid.values
        source.loc[wd.query_norm] = wd.qid_source.values
    unverified = {}
    if len(lab):
        for q, cq in lab.wikidata_qid.dropna().items():
            if qid.get(q) != cq and q in qid.index:
                unverified[q] = cq
    return qid, source, unverified


def filter_typo_edges(e, s, lab):
    """Drop typo edges between short strings (<= 8 chars) below ratio 96, and between two strings
    whose confident Claude names differ (compared after norm(): case, accents, punctuation)."""
    from textnorm import norm
    L = s.query_norm.str.len().to_numpy()
    short = (np.minimum(L[e.a.to_numpy()], L[e.b.to_numpy()]) <= SHORT_TYPO_LEN) & (e.score.to_numpy() < SHORT_TYPO_RATIO)
    name = np.array([None] * len(s), dtype=object)
    if len(lab):
        ok = lab[(lab.confidence >= TYPO_NAME_BLOCK_CONF) & (lab.canonical_en.str.lower() != "unknown")]
        sid_of = dict(zip(s.query_norm, s.sid))
        for q, n in ok.canonical_en.items():
            if q in sid_of:
                name[sid_of[q]] = norm(n)
    na, nb = name[e.a.to_numpy()], name[e.b.to_numpy()]
    differ = np.array([x is not None and y is not None and x != y for x, y in zip(na, nb)])
    keep = ~short & ~differ
    return e[keep], {"edges_in": int(len(e)), "dropped_short": int(short.sum()),
                     "dropped_claude_names_differ": int((differ & ~short).sum()), "edges_kept": int(keep.sum())}


def enforce_short_rule(s, root, qid, uf):
    """Final check of the short-string rule against each group's final topic: a gated string in a
    multi-string group stays only if its own confident Claude name equals the group's most common
    confident name, or its QID equals the group's most common QID. Others become their own topic."""
    root = root.copy()
    n_rows = s.n_rows.to_numpy()
    qv = qid.to_numpy()
    size = np.bincount(root, minlength=len(root))
    detached = 0
    for _ in range(3):   # removing a member can change a group's name; repeat until stable
        g = pd.DataFrame({"root": root, "w": n_rows, "qid": qv, "name": uf.own_name, "gated": uf.gated})
        size = np.bincount(root, minlength=len(root))
        g = g[size[root] > 1]
        nm = (g[g.name.notna() & ~g.gated].groupby(["root", "name"]).w.sum().reset_index()
              .sort_values("w", ascending=False).drop_duplicates("root").set_index("root").name)
        nm_all = (g[g.name.notna()].groupby(["root", "name"]).w.sum().reset_index()
                  .sort_values("w", ascending=False).drop_duplicates("root").set_index("root").name)
        nm = nm.reindex(nm_all.index).fillna(nm_all)
        qq = (g[g.qid.notna()].groupby(["root", "qid"]).w.sum().reset_index()
              .sort_values("w", ascending=False).drop_duplicates("root").set_index("root").qid)
        gg = g[g.gated].assign(own_qid=lambda d: [uf.own_qid[i] for i in d.index])
        ok = ((gg.own_qid.notna() & (gg.own_qid == gg.root.map(qq))) | (gg.name.notna() & (gg.name == gg.root.map(nm))))
        bad = gg.index[~ok.to_numpy()]
        if len(bad) == 0:
            break
        old = root.copy()
        bad = np.asarray(bad)
        root[bad] = bad
        detached += len(bad)
        # members whose root was a detached string: re-point them to the smallest remaining member
        orphan = np.isin(old, bad) & ~np.isin(np.arange(len(root)), bad)
        if orphan.any():
            idx = np.where(orphan)[0]
            new = pd.Series(idx).groupby(old[idx]).transform("min").to_numpy()
            root[idx] = new
    return root, int(detached)


def load_overrides():
    """pipeline/overrides.csv: one row per string (matched after norm()).
    detach: the string becomes its own topic, with no QID, named by its own most common raw form.
    move:   the string joins the topic whose QID or Claude name (case-insensitive) is `topic`."""
    from textnorm import norm
    if not OVERRIDES.exists():
        return pd.DataFrame(columns=["string", "action", "topic"])
    ov = pd.read_csv(OVERRIDES, dtype=str, comment="#").fillna("")
    ov["string"] = ov.string.map(norm)
    ov["action"] = ov.action.str.strip().str.lower()
    bad = ov[~ov.action.isin(["detach", "move"]) | ((ov.action == "move") & (ov.topic.str.strip() == ""))]
    if len(bad):
        raise SystemExit(f"bad rows in {OVERRIDES}: {bad.to_dict('records')}")
    return ov


def apply_overrides(ov, s, root, qid, lab):
    """Applied at the end of combine, after every merge layer and the short-string check."""
    root = root.copy()
    idx_of = dict(zip(s.query_norm, range(len(s))))
    w = s.n_rows.to_numpy()
    done = []
    for r in ov.itertuples():
        i = idx_of.get(r.string)
        if i is None:
            print(f"  override: string not found: {r.string!r}")
            continue
        old = root[i]
        others = np.where((root == old) & (np.arange(len(root)) != i))[0]
        if r.action == "detach":
            root[i] = i
            if len(others) and old == i:                 # it was the group's root: re-point the rest
                root[others] = others[0]
        else:
            key = r.topic.strip()
            cand = np.where(qid.to_numpy() == key)[0]
            if not len(cand) and len(lab):
                names = lab.canonical_en.str.lower().str.strip()
                cand = np.array([idx_of[q] for q in names.index[names == key.lower()] if q in idx_of])
            if not len(cand):
                print(f"  override: topic not found for move: {key!r}")
                continue
            target = root[cand[np.argmax(w[cand])]]
            if len(others) and old == i:
                root[others] = others[0]
            root[i] = target
        done.append((r.string, r.action, r.topic))
    return root, done


def run():
    s = pd.read_parquet(WORK / "strings.parquet")
    n = len(s)
    texts = s.query_norm.values
    sid_of = dict(zip(texts, s.sid))
    wdp = WORK / "wikidata_qids.parquet"
    wd = pd.read_parquet(wdp) if wdp.exists() else pd.DataFrame(columns=["query_norm", "qid", "wd_label", "qid_source"])
    lab = load_claude()
    qid, qsrc, unverified = string_qids(s, wd, lab)
    # short-string rule (b): a name-lookup QID is only a lookup of Claude's name, so for a short string it
    # counts only when that label is confident (>= SHORT_OWN_CONF). Otherwise the QID is dropped.
    if len(lab):
        conf_of = lab.confidence.reindex(qid.index)
        drop = (qsrc == "name_lookup").to_numpy() & qid.index.map(is_short_generic).to_numpy(dtype=bool) \
            & ~(conf_of.fillna(0) >= SHORT_OWN_CONF).to_numpy()
        qid[drop] = None
        qsrc[drop] = "dropped_short_low_conf"
        print(f"  name-lookup QIDs dropped from short low-confidence strings: {int(drop.sum()):,}")

    overrides = load_overrides()
    det = set(overrides.string[overrides.action == "detach"])
    det_mask = qid.index.isin(det)
    qid[det_mask] = None
    qsrc[det_mask] = "override_detach"

    uf = UF(n)
    for q, v in qid.items():
        if isinstance(v, str):
            uf.label[sid_of[q]] = v
    if len(lab):
        conf = lab[(lab.confidence >= CANON_BLOCK_CONF) & (lab.canonical_en.str.lower() != "unknown")]
        for q, name in conf.canonical_en.str.lower().str.strip().items():
            if q in sid_of:
                uf.canon[sid_of[q]] = frozenset([name])
    uf.gated = s.query_norm.map(is_short_generic).to_numpy()
    for q, v in qid.items():
        if isinstance(v, str):
            uf.own_qid[sid_of[q]] = v
    if len(lab):
        own = lab[(lab.confidence >= SHORT_OWN_CONF) & (lab.canonical_en.str.lower() != "unknown")]
        for q, nm in own.canonical_en.str.lower().str.strip().items():
            if q in sid_of:
                uf.own_name[sid_of[q]] = nm
    layer_of = np.array([None] * n, dtype=object)
    stats = {}

    def apply(name, pairs, cap, use_canon=False, gate=True):
        c = {"merged": 0, "same": 0, "cannot_link": 0, "claude_name_differs": 0, "short_generic": 0, "size_cap": 0}
        for a, b in pairs:
            r = uf.union(a, b, cap, use_canon, gate)
            c[r] += 1
            if r == "merged":
                for x in (a, b):
                    if layer_of[x] is None:
                        layer_of[x] = name
        stats[name] = c
        print(f"  {name:10s} {c}")

    # 1. same QID
    by_q = pd.Series(qid.values, index=s.sid.values).dropna()
    pairs = []
    for _, g in by_q.groupby(by_q):
        ids = g.index.to_numpy()
        pairs += [(ids[0], x) for x in ids[1:]]
    apply("wikidata", pairs, None, gate=False)  # same QID satisfies the short-string rule
    # 2. same canonical_en
    if len(lab):
        ok = lab[(lab.confidence >= CANON_MIN_CONF) & (lab.canonical_en.str.lower() != "unknown")]
        short = ok.index.map(is_short_generic).to_numpy(dtype=bool)
        ok = ok[~short | (ok.confidence >= SHORT_OWN_CONF).to_numpy()]
        key = ok.canonical_en.str.lower().str.strip()
        pairs = []
        for _, g in key.groupby(key):
            ids = [sid_of[q] for q in g.index if q in sid_of]
            pairs += [(ids[0], x) for x in ids[1:]]
        apply("claude", pairs, None, gate=False)   # gated strings filtered above
    # 3. typos, 4. semantic
    e = pd.read_parquet(WORK / "edges_typo.parquet").sort_values("score", ascending=False)
    e, typo_filter = filter_typo_edges(e, s, lab)
    stats["typo_filter"] = typo_filter
    print(f"  typo filter {typo_filter}")
    apply("typo", zip(e.a.to_numpy(), e.b.to_numpy()), MAX_GROUP, use_canon=True)
    e = pd.read_parquet(WORK / "edges_semantic.parquet").sort_values("cos", ascending=False)
    apply("semantic", zip(e.a.to_numpy(), e.b.to_numpy()), MAX_GROUP, use_canon=True)

    root = np.array([uf.find(i) for i in range(n)])
    root, detached = enforce_short_rule(s, root, qid, uf)
    stats["short_generic_detached"] = detached
    root, done = apply_overrides(overrides, s, root, qid, lab)
    stats["overrides_applied"] = [list(x) for x in done]
    print(f"  overrides applied: {done}")
    print(f"  short generic strings detached at the end: {detached}")
    s["group"] = root
    s["qid"] = qid.values
    s["qid_source"] = qsrc.values
    s["merge_layer"] = layer_of
    if len(lab):
        s = s.join(lab[["canonical_en", "type", "intent", "confidence", "wikidata_qid"]]
                   .rename(columns={"wikidata_qid": "claude_qid"}), on="query_norm")
    else:
        for c in ("canonical_en", "type", "intent", "confidence", "claude_qid"):
            s[c] = None
    s["claude_qid_unverified"] = s.query_norm.map(unverified)
    wd_label = dict(zip(wd.query_norm, wd.wd_label))

    # topic id / name per group (weights = number of rows)
    recs = {}
    for g, grp in s.groupby("group"):
        w = grp.n_rows
        q = grp.qid.dropna()
        canon = grp[(grp.canonical_en.notna()) & (grp.canonical_en.str.lower() != "unknown")]
        top_norm = grp.loc[w.idxmax(), "query_norm"]
        top_canon = canon.groupby("canonical_en").n_rows.sum().idxmax() if len(canon) else None
        if len(q):
            tid = grp.loc[q.index].groupby("qid").n_rows.sum().idxmax()
        else:
            tid = top_canon or top_norm
        if top_canon:
            name = top_canon
        elif len(q) and isinstance(wd_label.get(grp.loc[q.index[0], "query_norm"]), str):
            name = wd_label[grp.loc[q.index[0], "query_norm"]]
        else:
            name = grp.loc[w.idxmax(), "top_raw"]
        if len(grp) == 1 and grp.query_norm.iloc[0] in det:
            tid, name = grp.query_norm.iloc[0], grp.top_raw.iloc[0]
        recs[g] = (tid, name)
    # topic_id must be unique per group: groups without a QID take their Claude name as id, so two separate
    # groups with the same name (e.g. a low-confidence or short string kept apart) would silently merge.
    # The biggest group (by rows) keeps the plain id; the others get "<id> [<their most common string>]".
    rows_of = s.groupby("group").n_rows.sum()
    top_q = s.sort_values("n_rows", ascending=False).drop_duplicates("group").set_index("group").query_norm
    ids = pd.DataFrame({"tid": {g: v[0] for g, v in recs.items()}, "rows": rows_of})
    ids = ids.sort_values("rows", ascending=False)
    dup = ids.duplicated("tid")
    n_dup = int(dup.sum())
    for g in ids.index[dup]:
        recs[g] = (f"{recs[g][0]} [{top_q[g]}]", recs[g][1])
    stats["topic_id_collisions_resolved"] = n_dup
    print(f"  topic_id collisions resolved: {n_dup:,}")
    s["topic_id"] = s.group.map(lambda g: recs[g][0])
    s["topic_name"] = s.group.map(lambda g: recs[g][1])
    keep = ["sid", "query_norm", "top_raw", "n_rows", "vol_sum", "n_countries", "important", "group",
            "topic_id", "topic_name", "merge_layer", "qid", "qid_source", "canonical_en", "type", "intent",
            "confidence", "claude_qid", "claude_qid_unverified", "override"]
    s["override"] = s.query_norm.map(dict(zip(overrides.string, overrides.action)))
    s[keep].to_parquet(WORK / "string_topics.parquet", index=False)

    # map back to every row
    t = pq.read_table(INTERIM / "trends.parquet")
    qn = t.column("query_norm").to_pandas()
    m = s.set_index("query_norm")
    t = t.append_column("topic_id", pa.array(qn.map(m.topic_id).values, type=pa.string()))
    t = t.append_column("topic_name", pa.array(qn.map(m.topic_name).astype(str).values, type=pa.string()))
    # collection bump: flag (never drop) trends starting in the 19:00 UTC hour, see CHECKS.md C4
    hr = pa.compute.hour(t.column("start_time_utc"))
    t = t.append_column("utc19_bump", pa.compute.equal(hr, 19))
    pq.write_table(t, INTERIM / "topics.parquet", compression="zstd")

    n_raw = pq.read_table(INTERIM / "trends.parquet", columns=["query_raw"]).column("query_raw").to_pandas().nunique()
    summary = {"distinct_raw": int(n_raw), "distinct_norm": int(n), "groups": int(s.group.nunique()),
               "topics": int(s.topic_id.nunique()), "layers": stats,
               "max_group_size": int(s.group.value_counts().max()), "claude_labels": int(len(lab)),
               "strings_with_qid": int(s.qid.notna().sum()), "claude_qid_unverified": len(unverified)}
    save_json(WORK / "combine_summary.json", summary)
    print(json.dumps(summary, indent=1))
    print(f"wrote {INTERIM/'topics.parquet'} ({t.num_rows:,} rows)")


def validation_sample(n_pos=100, n_neg=100, seed=11, n_link=25):
    """200 string pairs for hand labelling. Positives: n_link pairs created by the link stage (a linked
    string + a string of the topic it joined), the rest random pairs from multi-string topics.
    Negatives: half 'hard' (embedding neighbours put in different topics), half random pairs
    of different topics that trended in the same 3-day window."""
    rng = random.Random(seed)
    s = pd.read_parquet(WORK / "string_topics.parquet")
    full = pd.read_parquet(WORK / "strings.parquet", columns=["sid", "first_day", "countries"])
    s = s.merge(full, on="sid")
    tid = dict(zip(s.sid, s.topic_id))
    multi = s.groupby("topic_id").filter(lambda g: len(g) >= 2)
    topics = multi.topic_id.unique().tolist()
    pos, linked_pairs = set(), set()
    if "linked" in s.columns and s.linked.any():
        lk = s[s.linked]
        not_lk = s[~s.linked.astype(bool)].groupby("topic_id").sid.apply(list).to_dict()
        lk = lk[lk.topic_id.isin(not_lk)]
        for a, t_ in lk.sample(min(n_link * 3, len(lk)), random_state=seed)[["sid", "topic_id"]].itertuples(index=False):
            b = rng.choice(not_lk[t_])
            linked_pairs.add((min(a, b), max(a, b)))
            if len(linked_pairs) == n_link:
                break
    while len(pos) < n_pos - len(linked_pairs):
        g = multi[multi.topic_id == rng.choice(topics)].sid.tolist()
        a, b = rng.sample(g, 2)
        pos.add((min(a, b), max(a, b)))
    cand = pd.read_parquet(WORK / "semantic_candidates.parquet", columns=["a", "b"])
    cand = cand[[tid[a] != tid[b] for a, b in zip(cand.a, cand.b)]]
    hard = set(map(tuple, cand.sample(n_neg // 2, random_state=seed)[["a", "b"]].to_numpy()))
    by_day = s.groupby("first_day").sid.apply(list).to_dict()
    days = sorted(by_day)
    rand = set()
    while len(rand) < n_neg - len(hard):
        d = rng.choice(days)
        pool = [x for k in range(d, d + 3) for x in by_day.get(k, [])]
        a, b = rng.sample(pool, 2)
        if tid[a] != tid[b]:
            rand.add((min(a, b), max(a, b)))
    rows = [(a, b, "same_topic") for a, b in pos] + [(a, b, "linked") for a, b in linked_pairs] + \
           [(a, b, "hard_negative") for a, b in hard] + \
           [(a, b, "random_negative") for a, b in rand]
    rng.shuffle(rows)
    info = s.set_index("sid")
    out, key = [], []
    for i, (a, b, kind) in enumerate(rows):
        ra, rb = info.loc[a], info.loc[b]
        out.append({"pair_id": i, "string_a": ra.top_raw, "string_b": rb.top_raw,
                    "countries_a": " ".join(ra.countries[:4]), "countries_b": " ".join(rb.countries[:4]),
                    "first_date_a": str(pd.Timestamp("1970-01-01") + pd.Timedelta(days=int(ra.first_day)))[:10],
                    "first_date_b": str(pd.Timestamp("1970-01-01") + pd.Timedelta(days=int(rb.first_day)))[:10],
                    "same_topic_label": ""})
        key.append({"pair_id": i, "sampled_as": kind, "predicted_same": tid[a] == tid[b],
                    "topic_a": ra.topic_id, "topic_b": rb.topic_id, "sid_a": a, "sid_b": b})
    pd.DataFrame(out).to_csv(DOCS / "validation_sample.csv", index=False)
    pd.DataFrame(key).to_csv(DOCS / "validation_key.csv", index=False)  # open only after labelling
    print(f"wrote {DOCS/'validation_sample.csv'} ({len(out)} pairs); answer key in {DOCS/'validation_key.csv'}")
