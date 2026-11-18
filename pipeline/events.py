"""Event reach (DECISIONS.md, Step 9 round 12; METHODOLOGY.md, "Moment reach and event reach").

Moment reach (step 4) counts the countries whose session of ONE topic starts in ONE burst. Readers see event reach
instead, for the opening and the chart shocks: the countries where ANY topic about the same event trended from
EVENT_BEFORE_H before the moment start to EVENT_AFTER_H after it. Two things make the counts differ:
  - split topics: "murió el papa" became its own topic ("Death of Pope Francis"), so Argentina never trended the
    main "Pope Francis" topic in that window;
  - running sessions: countries already trending the topic (Pope Francis at Easter, 19-20 Apr 2025) continue a
    session from an earlier moment, so they do not count as joining the new burst.

Each event's topic group = the main topic + the candidates accepted by hand in docs/event_groups_review.csv
(git-ignored). Name matching only proposes candidates; nothing is accepted automatically.
"""
import re

import numpy as np
import pandas as pd

EVENT_BEFORE_H = 2
EVENT_AFTER_H = 24
REVIEW_FILE = "event_groups_review.csv"
MANY_CANDIDATES = 25      # events with more candidates than this are flagged as generic matches
ACCEPT_VALUES = {"yes", "y", "1", "true", "accept", "accepted", "x"}


def window(start):
    s = pd.Timestamp(start)
    return s - pd.Timedelta(hours=EVENT_BEFORE_H), s + pd.Timedelta(hours=EVENT_AFTER_H)


def _clean(name):
    return re.sub(r"\s*\[.*\]\s*$", "", str(name)).strip().lower()


def match_kind(main_name, main_type, cand_name):
    """How a candidate topic's name matches the event's main topic, or None."""
    n, c = _clean(main_name), _clean(cand_name)
    if not n or not c or n == c:
        return "same name" if n and n == c else None
    if re.search(rf"\b{re.escape(n)}\b", c):
        return "contains the event name"
    if len(c.split()) >= 2 and re.search(rf"\b{re.escape(c)}\b", n):
        return "inside the event name"
    if main_type == "person":
        toks = [x for x in re.findall(r"\w+", n) if len(x) >= 4]
        if toks and re.search(rf"\b{re.escape(toks[-1])}\b", c):
            return "surname only"
    return None


def candidates(events, t, meta):
    """events: DataFrame(event, moment_id, topic_id, start_utc); t: national rows (topic_id, country_code,
    start_time_utc, query_raw); meta: topic_meta indexed by topic_id (topic_name, type, is_junk).
    -> review rows, one per (event, candidate topic)."""
    junk = set(meta.index[meta.is_junk.astype(bool)]) if "is_junk" in meta else set()
    rows = []
    for e in events.itertuples():
        lo, hi = window(e.start_utc)
        w = t[(t.start_time_utc >= lo) & (t.start_time_utc < hi)]
        main_cc = set(w[w.topic_id == e.topic_id].country_code)
        mname, mtype = meta.topic_name.get(e.topic_id, e.topic_id), meta["type"].get(e.topic_id)
        found = []
        for tid, g in w[(w.topic_id != e.topic_id) & ~w.topic_id.isin(junk)].groupby("topic_id"):
            mk = match_kind(mname, mtype, meta.topic_name.get(tid, tid))
            if mk:
                cc = set(g.country_code)
                found.append({"event": f"{mname} ({pd.Timestamp(e.start_utc):%Y-%m-%d})", "event_moment_id": int(e.moment_id),
                              "event_topic_id": e.topic_id, "event_countries_main_topic": len(main_cc),
                              "candidate_topic_id": tid, "candidate_topic": meta.topic_name.get(tid, tid),
                              "match": mk, "phrasings": "; ".join(g.query_raw.str.lower().value_counts().head(3).index),
                              "countries_in_window": len(cc), "countries_added": len(cc - main_cc),
                              "added_countries": ", ".join(sorted(cc - main_cc)), "accept": ""})
        note = f"generic: {len(found)} candidates, review each" if len(found) > MANY_CANDIDATES else ""
        for f in sorted(found, key=lambda x: (-x["countries_added"], -x["countries_in_window"])):
            f["note"] = "; ".join(x for x in (note, "surname only: check it is the same person" if f["match"] == "surname only" else "") if x)
            rows.append(f)
    return pd.DataFrame(rows)


def load_groups(docs):
    """{event moment_id: set of accepted candidate topic_ids} from the reviewed file; None if there is no file."""
    p = docs / REVIEW_FILE
    if not p.exists():
        return None
    d = pd.read_csv(p, dtype=str, keep_default_na=False)
    ok = d.accept.str.strip().str.lower().isin(ACCEPT_VALUES)
    out = {}
    for mid, tid in zip(d.event_moment_id[ok], d.candidate_topic_id[ok]):
        out.setdefault(int(mid), set()).add(tid)
    return out


def reviewed(docs):
    """True once every candidate row has an accept decision (any non-empty value)."""
    p = docs / REVIEW_FILE
    if not p.exists():
        return False
    d = pd.read_csv(p, dtype=str, keep_default_na=False)
    return bool(len(d)) and (d.accept.str.strip() != "").all()


def metrics(t, topic_ids, start):
    """Event reach, countries within 60 min and minutes to half, counted from the moment start (rows before the
    start, up to EVENT_BEFORE_H earlier, count as minute 0). -> dict with the per-country first times."""
    lo, hi = window(start)
    s = pd.Timestamp(start)
    w = t[t.topic_id.isin(topic_ids) & (t.start_time_utc >= lo) & (t.start_time_utc < hi)]
    first = w.groupby("country_code").start_time_utc.min().sort_values()
    mins = np.clip(((first - s).dt.total_seconds() / 60).round().astype(int).values, 0, None)
    half = int(np.sort(mins)[int(np.ceil(len(mins) / 2)) - 1]) if len(mins) else None
    return {"event_reach": int(len(first)), "event_reach_60": int((mins <= 60).sum()),
            "event_minutes_to_half": half, "first": first, "minutes": mins}
