"""Step 3g: link small local topics to the bigger topic they are about (cross-language phrasings).

Example: German "papst tot" was labelled "Pope dead" and stayed a Germany-only topic, but Google's own
related list for it contains "franziskus", "papst franziskus", "der papst ist gestorben": strings
that trend elsewhere and belong to the Pope Francis topics.

Rule (child topic C -> parent topic P):
  * C has national reach <= CHILD_MAX_REACH countries; P has reach >= PARENT_MIN_REACH and > C's.
  * Evidence = distinct strings linking C and P through Google's related lists, in either direction
    (C's string lists a P string, or a P string lists C's string), where the two strings trended
    within WINDOW_DAYS of each other.
  * Names: the English topic names (Claude's canonical_en) must have embedding cosine >= COS_MIN.
    Accept with >= MIN_EVIDENCE pieces of evidence and >= MIN_SHARE of C's evidence, or with
    any evidence and cosine >= COS_STRONG. This blocks co-trending but different things
    ("Claire Chazal" -> "Anne-Sophie Lapix").
  * Types must be compatible (see compatible()). Different confident QIDs never link.
  * The parent must have trended in another country (outside C's countries) within WINDOW_DAYS of
    one of C's trend days; otherwise C stays local ("Tsunami warning California" on 5 Dec 2024).
  * Chains are resolved to the final parent (reach strictly increases, so there are no cycles).
Manual overrides: docs/link_overrides.csv (child_topic_id, parent_topic_id; empty parent = never link).

Rewrites topic_id / topic_name in work/string_topics.parquet and data/interim/topics.parquet, keeping
the pre-link values in topic_id_combine / topic_name_combine (the stage always starts from those).
"""
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from unidecode import unidecode

sys.path.insert(0, str(Path(__file__).parent))
from common import DOCS, INTERIM, WINDOW_DAYS, WORK, save_json  # noqa: E402

CHILD_MAX_REACH = 3
PARENT_MIN_REACH = 3
MIN_EVIDENCE = 2
MIN_SHARE = 0.5
COS_MIN = 0.86        # English topic names (Claude) must be this similar (multilingual-e5-small, "query: ")
COS_STRONG = 0.92     # ... or this similar, with a single piece of evidence
SPORT = {"sports_match", "team"}
OVERRIDES = DOCS / "link_overrides.csv"


def compatible(ct: str, pt: str) -> bool:
    if ct == pt:
        return True
    if ct in SPORT or pt in SPORT:          # match <-> club, person <-> club: never
        return False
    if ct in ("event", "other", "unlabeled", "holiday"):
        return True                          # "death of X" -> X, "X news" -> X
    if ct == "person" and pt == "event":
        return False
    return ct in ("media", "product", "company") and pt in ("media", "product", "company", "event")


VS_RE = re.compile(r"\b(vs|v|x|contre|gegen|contra|against)\b|\s[-–]\s")


def _tokens(x: str) -> set:
    return set(re.findall(r"\w+", unidecode(x.lower())))


FILLER = {"the", "of", "in", "on", "a", "an", "and", "for", "to", "at", "today", "tonight", "live", "latest",
          "new", "news", "de", "la", "el", "le", "les", "del", "da", "do", "di", "en", "vivo", "online", "official"}
PLACE_OK_ADD = FILLER | {"city", "province", "state", "region", "county", "district", "map", "time", "population"}
WEATHER_WORDS = re.compile(r"weather|forecast|storm|rain|snow|typhoon|hurricane|cyclone|tornado|heat ?wave|"
                           r"cold front|clima|tiempo|wetter|meteo|hava durumu|pogoda|погода|cuaca|thoi tiet|"
                           r"天気|天氣|날씨|طقس|मौसम")
DIGITS = re.compile(r"\d+")


def _stem(w: str) -> str:
    return w[:-1] if len(w) > 3 and w.endswith("s") else w


def _content(x: str) -> set:
    return {_stem(w) for w in _tokens(x)} - FILLER


def guard(cn: str, pn: str, ct: str, pt: str) -> bool:
    """Name-level guards on top of compatible(). cn/pn are the topic names (Claude's English name if labelled)."""
    cl, pl = cn.lower(), pn.lower()
    a, b = _tokens(cn), _tokens(pn)
    if ct == "person" and pt == "person" and not (a <= b or b <= a):   # two different people
        return False
    if len(_content(pn)) == 0 or re.fullmatch(r"[\d\s]+|\w{1,2}", pl.strip()):   # junk parents ("8")
        return False
    if pt == "person" and re.search(r"arena|stadi|airport|aeroport|street|museum|school|universit|hospital|"
                                   r"bridge|\bpark\b|\bcenter\b|\bcentre\b", cl):   # a venue is not its namesake
        return False
    if VS_RE.search(cl) and pt != "sports_match":                      # a fixture only joins a fixture
        return False
    if bool(WEATHER_WORDS.search(cl)) != bool(WEATHER_WORDS.search(pl)):   # weather stays weather
        return False
    dc, dp = set(DIGITS.findall(cl)), set(DIGITS.findall(pl))
    if dc and dp and dc != dp:                                          # Channel 12 != Channel 13
        return False
    if pt == "place" and ct != "place" and not (_content(cn) - _content(pn)) <= PLACE_OK_ADD:
        return False                                                    # "maryland basketball" -> Maryland
    if ct != "unlabeled":                                               # both are English names
        ca, cb = _content(cn), _content(pn)
        if (ca - cb) and (cb - ca):                                     # Pittsburgh vs Philadelphia weather
            return False
    return True


def name_cos(a: list, b: list) -> np.ndarray:
    import torch
    from sentence_transformers import SentenceTransformer
    names = sorted(set(a) | set(b))
    dev = "mps" if torch.backends.mps.is_available() else "cpu"
    model = SentenceTransformer("intfloat/multilingual-e5-small", device=dev)
    v = model.encode([f"query: {n.lower()}" for n in names], batch_size=512, normalize_embeddings=True,
                     convert_to_numpy=True, show_progress_bar=False)
    ix = {n: i for i, n in enumerate(names)}
    ia, ib = np.array([ix[x] for x in a]), np.array([ix[x] for x in b])
    return (v[ia] * v[ib]).sum(1)


def shared_elsewhere(children: list, parents: list) -> list:
    """True if the parent trended (national feeds) in a country outside the child's countries,
    within WINDOW_DAYS of a day on which the child trended."""
    col = "topic_id_combine" if "topic_id_combine" in pq.read_schema(INTERIM / "topics.parquet").names else "topic_id"
    need = set(children) | set(parents)
    t = pq.read_table(INTERIM / "topics.parquet", columns=[col, "country_code", "level", "start_time_utc"]).to_pandas()
    t = t[(t.level == "country") & t[col].isin(need)]
    t["day"] = (t.start_time_utc.dt.floor("D").astype("int64") // 86_400_000_000_000).astype(int)
    by = t.groupby(col)
    days_cc = {k: g.groupby("day").country_code.agg(set).to_dict() for k, g in by}
    out = []
    for c, p in zip(children, parents):
        cd, pd_ = days_cc.get(c, {}), days_cc.get(p, {})
        c_cc = set().union(*cd.values()) if cd else set()
        hit = False
        for d in cd:
            for k in range(-WINDOW_DAYS, WINDOW_DAYS + 1):
                if pd_.get(d + k, set()) - c_cc:
                    hit = True
                    break
            if hit:
                break
        out.append(hit)
    return out


def topic_table(st: pd.DataFrame, s: pd.DataFrame) -> pd.DataFrame:
    cc = s.set_index("sid").countries
    st = st.assign(countries=st.sid.map(cc))
    nat = st.explode("countries")
    nat = nat[nat.countries.str.len() == 2] if nat.countries.notna().any() else nat
    reach = nat.groupby("topic_id").countries.nunique()

    def mode(col):
        d = st[st[col].notna()].groupby(["topic_id", col]).n_rows.sum().reset_index()
        return d.sort_values("n_rows", ascending=False).drop_duplicates("topic_id").set_index("topic_id")[col]

    tt = pd.DataFrame({"reach": reach})
    tt["type"] = mode("type")
    tt["qid"] = mode("qid")
    tt["name"] = st.drop_duplicates("topic_id").set_index("topic_id").topic_name
    tt["rows"] = st.groupby("topic_id").n_rows.sum()
    tt["type"] = tt["type"].fillna("unlabeled")
    tt["reach"] = tt.reach.fillna(0).astype(int)
    return tt


def short_rule(acc, st):
    """The combine short-string rule applied to links: if the child or the parent topic is a single
    short/single-word string, the link is kept only if that string's own Claude name (confidence
    >= SHORT_OWN_CONF) equals the other topic's name, or its QID equals the other topic's QID."""
    from combine import SHORT_OWN_CONF, is_short_generic
    cnt = st.topic_id.value_counts()
    single = st[st.topic_id.map(cnt) == 1].set_index("topic_id")
    single = single[single.query_norm.map(is_short_generic)]
    own_name = single.canonical_en.where(single.confidence >= SHORT_OWN_CONF).str.lower().str.strip()
    own_qid = single.qid

    def ok(t_short, other_name, other_qid):
        if t_short not in single.index:
            return True
        q, nm = own_qid.get(t_short), own_name.get(t_short)
        return (isinstance(q, str) and q == other_qid) or (isinstance(nm, str) and nm == str(other_name).lower().strip())

    keep = np.array([ok(c, pn, pq) and ok(p, cn, cq) for c, p, cn, pn, cq, pq in
                     zip(acc.child, acc.parent, acc.c_name, acc.p_name, acc.c_qid, acc.p_qid)], dtype=bool)
    print(f"links refused by the short-string rule: {int((~keep).sum()):,}")
    return acc[keep], int((~keep).sum())


def run():
    stp = WORK / "string_topics.parquet"
    st = pd.read_parquet(stp)
    if "topic_id_combine" in st.columns:        # always restart from combine's output
        st["topic_id"], st["topic_name"] = st.topic_id_combine, st.topic_name_combine
    else:
        st["topic_id_combine"], st["topic_name_combine"] = st.topic_id, st.topic_name
    s = pd.read_parquet(WORK / "strings.parquet", columns=["sid", "query_norm", "countries", "days", "related_ev"])
    tt = topic_table(st, s)
    sid2topic = st.set_index("sid").topic_id
    q2sid = dict(zip(s.query_norm, s.sid))
    days = dict(zip(s.sid, s.days))

    child_topics = set(tt.index[tt.reach <= CHILD_MAX_REACH])
    s["topic"] = s.sid.map(sid2topic)
    ex = s[["sid", "topic", "related_ev"]].explode("related_ev").dropna()
    ex["rs"] = ex.related_ev.map(q2sid)
    ex = ex[ex.rs.notna()].astype({"rs": "int64"})
    ex["rtopic"] = ex.rs.map(sid2topic)
    ex = ex[ex.rtopic.notna() & (ex.rtopic != ex.topic)]
    # forward: a child string lists a parent string; reverse: a parent string lists a child string
    fwd = ex[ex.topic.isin(child_topics)].assign(child=lambda d: d.topic, parent=lambda d: d.rtopic,
                                                  a=lambda d: d.sid, b=lambda d: d.rs)
    rev = ex[ex.rtopic.isin(child_topics)].assign(child=lambda d: d.rtopic, parent=lambda d: d.topic,
                                                   a=lambda d: d.rs, b=lambda d: d.sid)
    cand = pd.concat([fwd.assign(dir="fwd"), rev.assign(dir="rev")])[["child", "parent", "a", "b", "dir"]]
    keep = []
    for x, y in zip(cand.a, cand.b):
        cd, rd = np.sort(np.asarray(days[x])), np.sort(np.asarray(days[y]))
        j = np.searchsorted(rd, cd)
        near = np.minimum(np.abs(rd[np.clip(j, 0, len(rd) - 1)] - cd), np.abs(rd[np.clip(j - 1, 0, len(rd) - 1)] - cd))
        keep.append(near.min() <= WINDOW_DAYS)
    cand = cand[keep]
    qn = s.set_index("sid").query_norm
    cand["via"] = np.where(cand.dir == "fwd", cand.b.map(qn), cand.b.map(qn) + " (lists it)")
    ev = cand[["child", "parent", "via"]].drop_duplicates()
    print(f"child topics (reach <= {CHILD_MAX_REACH}): {len(child_topics):,}; evidence pairs: {len(ev):,} "
          f"(forward {int((cand.dir == 'fwd').sum()):,}, reverse {int((cand.dir == 'rev').sum()):,})")

    agg = ev.groupby(["child", "parent"]).agg(evidence=("via", "nunique"), via=("via", lambda x: "; ".join(sorted(x)[:6])))
    agg = agg.reset_index()
    agg["total"] = agg.child.map(ev.groupby("child").via.nunique())
    agg["share"] = agg.evidence / agg.total
    for c in ("reach", "type", "qid", "name"):
        agg[f"c_{c}"] = agg.child.map(tt[c])
        agg[f"p_{c}"] = agg.parent.map(tt[c])
    base = ((agg.p_reach >= PARENT_MIN_REACH) & (agg.p_reach > agg.c_reach)
            & ~(agg.c_qid.notna() & agg.p_qid.notna() & (agg.c_qid != agg.p_qid))
            & np.array([compatible(a, b) for a, b in zip(agg.c_type, agg.p_type)]))
    agg = agg[base].copy()
    agg["cos"] = name_cos(agg.c_name.astype(str).tolist(), agg.p_name.astype(str).tolist())
    agg["guard"] = [guard(a, b, ct, pt) for a, b, ct, pt in zip(agg.c_name.astype(str), agg.p_name.astype(str),
                                                                agg.c_type, agg.p_type)]
    ok = agg.guard & (agg.cos >= COS_MIN) & (((agg.evidence >= MIN_EVIDENCE) & (agg.share >= MIN_SHARE)) | (agg.cos >= COS_STRONG))
    # the parent must have trended in another country (not one of the child's) within the window:
    # linking is for "this is not only ours", not for filing a local event under a generic class
    cand_ok = agg[ok]
    shared = shared_elsewhere(cand_ok.child.tolist(), cand_ok.parent.tolist())
    ok.loc[cand_ok.index] = shared
    agg["shared_elsewhere"] = False
    agg.loc[cand_ok.index, "shared_elsewhere"] = shared
    agg["accepted"] = ok
    acc = agg[ok].sort_values(["child", "evidence", "cos"], ascending=[True, False, False]).drop_duplicates("child")
    acc, n_short = short_rule(acc, st)
    # manual overrides (pipeline/overrides.csv): a detached string's topic never links, in either direction
    if "override" in st.columns:
        frozen = set(st.topic_id[st.override.notna()])
        acc = acc[~acc.child.isin(frozen) & ~acc.parent.isin(frozen)]
    agg.loc[~agg.index.isin(acc.index), "accepted"] = False
    link = dict(zip(acc.child, acc.parent))

    # manual overrides
    n_over = 0
    if OVERRIDES.exists():
        ov = pd.read_csv(OVERRIDES, dtype=str, comment="#").fillna("")
        for c, p in zip(ov.child_topic_id, ov.parent_topic_id):
            n_over += 1
            if p:
                link[c] = p
            else:
                link.pop(c, None)

    def root(x):
        seen = 0
        while x in link and seen < 10:
            x, seen = link[x], seen + 1
        return x

    final = {c: root(c) for c in link}
    name = st.drop_duplicates("topic_id").set_index("topic_id").topic_name
    st["linked"] = st.topic_id.isin(final.keys())
    st["topic_id"] = st.topic_id.map(lambda x: final.get(x, x))
    st["topic_name"] = st.topic_id.map(name).fillna(st.topic_name)
    st.to_parquet(stp, index=False)

    t = pq.read_table(INTERIM / "topics.parquet")
    qn = t.column("query_norm").to_pandas()
    m = st.set_index("query_norm")
    for col, src in (("topic_id_combine", "topic_id_combine"), ("topic_name_combine", "topic_name_combine"),
                     ("topic_id", "topic_id"), ("topic_name", "topic_name")):
        arr = pa.array(qn.map(m[src]).astype(object).where(qn.map(m[src]).notna(), None).values, type=pa.string())
        if col in t.column_names:
            t = t.set_column(t.column_names.index(col), col, arr)
        else:
            t = t.append_column(col, arr)
    pq.write_table(t, INTERIM / "topics.parquet", compression="zstd")

    out = agg.sort_values(["accepted", "evidence"], ascending=False)
    out.to_parquet(WORK / "topic_links.parquet", index=False)
    rev = acc.assign(rows=acc.child.map(tt.rows)).sort_values("rows", ascending=False)
    rev[["child", "c_name", "c_type", "c_reach", "parent", "p_name", "p_type", "p_reach", "evidence", "share", "via"]] \
        .to_csv(DOCS / "link_review.csv", index=False)
    summary = {"child_topics": len(child_topics), "candidate_pairs": int(len(agg)), "accepted_links": int(len(acc)),
               "overrides": n_over, "refused_short_generic": n_short, "strings_relinked": int(st.linked.sum()),
               "topics_after": int(st.topic_id.nunique()), "rule": {
                   "child_max_reach": CHILD_MAX_REACH, "parent_min_reach": PARENT_MIN_REACH,
                   "min_evidence": MIN_EVIDENCE, "min_share": MIN_SHARE, "window_days": WINDOW_DAYS}}
    save_json(WORK / "link_summary.json", summary)
    print(json.dumps(summary, indent=1))
    print(f"wrote {DOCS / 'link_review.csv'} (accepted links, biggest children first)")


if __name__ == "__main__":
    run()
