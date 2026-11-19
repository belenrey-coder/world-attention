"""Event reach (DECISIONS.md, Step 9 round 12; METHODOLOGY.md, "Moment reach and event reach").

Moment reach (step 4) counts the countries whose session of ONE topic starts in ONE burst. Readers see event reach
instead, for the opening and the chart shocks: the countries where ANY topic about the same event trended from
EVENT_BEFORE_H before the moment start to EVENT_AFTER_H after it. Two things make the counts differ:
  - split topics: "murió el papa" became its own topic ("Death of Pope Francis"), so Argentina never trended the
    main "Pope Francis" topic in that window;
  - running sessions: countries already trending the topic (Pope Francis at Easter, 19-20 Apr 2025) continue a
    session from an earlier moment, so they do not count as joining the new burst.

"Within 60 min" and "minutes to half" are counted from the third country's first trend in the window, as in the
global-moment rule (one or two early countries would otherwise make a spike look slow).

Each event's topic group = the main topic + the candidates accepted by hand in docs/event_groups_review.csv
(git-ignored). Name matching only proposes candidates; nothing is accepted automatically, except that a candidate
which can never change a shown number is marked accept = "no-effect": all its countries already trended the main
topic, and never earlier than the main topic did (minutes clipped at the moment start). Since the main topic is
always in the group, such a row cannot lower any country's first time, whatever else is accepted.
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
        main_first = _first_minutes(w[w.topic_id == e.topic_id], e.start_utc)
        mname, mtype = meta.topic_name.get(e.topic_id, e.topic_id), meta["type"].get(e.topic_id)
        found = []
        for tid, g in w[(w.topic_id != e.topic_id) & ~w.topic_id.isin(junk)].groupby("topic_id"):
            mk = match_kind(mname, mtype, meta.topic_name.get(tid, tid))
            if mk:
                cc = set(g.country_code)
                cf = _first_minutes(g, e.start_utc)
                earlier = [c for c, mn in cf.items() if c in main_first and mn < main_first[c]]
                can = bool(cc - main_cc) or bool(earlier)
                found.append({"event": f"{mname} ({pd.Timestamp(e.start_utc):%Y-%m-%d})", "event_moment_id": int(e.moment_id),
                              "event_topic_id": e.topic_id, "event_countries_main_topic": len(main_cc),
                              "candidate_topic_id": tid, "candidate_topic": meta.topic_name.get(tid, tid),
                              "match": mk, "phrasings": "; ".join(g.query_raw.str.lower().value_counts().head(3).index),
                              "countries_in_window": len(cc), "countries_added": len(cc - main_cc),
                              "added_countries": ", ".join(sorted(cc - main_cc)),
                              "earlier_countries": ", ".join(sorted(earlier)),
                              "can_change": can, "accept": "" if can else "no-effect"})
        note = f"generic: {len(found)} candidates, review each" if len(found) > MANY_CANDIDATES else ""
        for f in found:
            f["note"] = "; ".join(x for x in (note, "surname only: check it is the same person" if f["match"] == "surname only" else "") if x)
            rows.append(f)
    d = pd.DataFrame(rows)
    if d.empty:
        return d
    # rows that could change a number first, grouped by event in chart order; then the no-effect rows
    order = {mid: i for i, mid in enumerate(dict.fromkeys(events.moment_id))}
    d["_ev"] = d.event_moment_id.map(order)
    d = d.sort_values(["can_change", "_ev", "countries_added", "countries_in_window"],
                      ascending=[False, True, False, False]).drop(columns=["_ev"])
    return d.reset_index(drop=True)


def _first_minutes(rows, start):
    """{country: minutes from the moment start to its first row, clipped at 0} (minute 0 = at or before start)."""
    if rows.empty:
        return {}
    f = rows.groupby("country_code").start_time_utc.min()
    return {c: max(0, int(round((v - pd.Timestamp(start)).total_seconds() / 60))) for c, v in f.items()}


# review files per chapter: the shocks' (main + extra) and the appointments' are decided and switched on separately
SHOCK_REVIEW_FILES = ["event_groups_review.csv", "event_groups_review_extra.csv"]
APPOINTMENT_REVIEW_FILES = ["event_groups_review_appointments.csv"]


def review_files(docs, names=None):
    return [docs / n for n in (names or SHOCK_REVIEW_FILES) if (docs / n).exists()]


def load_groups(docs, names=None):
    """{event moment_id: set of accepted candidate topic_ids} from the chapter's review files; None if none exist."""
    files = review_files(docs, names)
    if not files:
        return None
    d = pd.concat([pd.read_csv(p, dtype=str, keep_default_na=False) for p in files], ignore_index=True)
    ok = d.accept.str.strip().str.lower().isin(ACCEPT_VALUES)
    out = {}
    if "event_id" in d.columns:          # appointments: one group per scheduled event (event_id)
        for eid, tid in zip(d.event_id[ok], d.candidate_topic_id[ok]):
            out.setdefault(str(eid), set()).add(tid)
        return out
    for mid, tid in zip(d.event_moment_id[ok], d.candidate_topic_id[ok]):
        out.setdefault(int(mid), set()).add(tid)
    return out


def reviewed(docs, names=None):
    """True once every candidate row in the chapter's review files has an accept decision (any non-empty value)."""
    files = review_files(docs, names)
    if not files:
        return False
    d = pd.concat([pd.read_csv(p, dtype=str, keep_default_na=False) for p in files], ignore_index=True)
    return bool(len(d)) and (d.accept.str.strip() != "").all()


def from_third(first):
    """Reference time and minutes for 'within 60 min' and 'minutes to half': counted from the THIRD country's first
    trend, as in the global-moment rule (2026-11-17), so one or two early countries don't make a spike look slow.
    first: Series of per-country first times, sorted. -> (reference time, minutes clipped at 0)."""
    ref = first.iloc[min(2, len(first) - 1)]
    return ref, np.clip(((first - ref).dt.total_seconds() / 60).round().astype(int).values, 0, None)


def half_minutes(mins):
    return int(np.sort(mins)[int(np.ceil(len(mins) / 2)) - 1]) if len(mins) else None


def metrics(t, topic_ids, start):
    """Event reach (countries in the window), countries within 60 min and minutes to half, both counted from the
    third country's first trend in the window (from_third). -> dict with the per-country first times."""
    lo, hi = window(start)
    w = t[t.topic_id.isin(topic_ids) & (t.start_time_utc >= lo) & (t.start_time_utc < hi)]
    first = w.groupby("country_code").start_time_utc.min().sort_values()
    if first.empty:
        return {"event_reach": 0, "event_reach_60": 0, "event_minutes_to_half": None, "first": first,
                "minutes": np.array([]), "reference_utc": None}
    ref, mins = from_third(first)
    return {"event_reach": int(len(first)), "event_reach_60": int((mins <= 60).sum()),
            "event_minutes_to_half": half_minutes(mins), "first": first, "minutes": mins, "reference_utc": ref}
