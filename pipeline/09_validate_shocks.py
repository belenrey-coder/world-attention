"""Step 9: validate the "shock" kind (scheduled vs unscheduled) before it is final.

    python pipeline/09_validate_shocks.py thresholds   # shock counts at 10 / 15 / 20 countries (no API call)
    python pipeline/09_validate_shocks.py label        # Claude labels every non-sport global moment (Batches API, cached)
    python pipeline/09_validate_shocks.py sample       # blind stratified sample of 100 -> docs/shock_validation_sample.csv
    python pipeline/09_validate_shocks.py helpers      # add search links / moment details to the sample (no labels)
    python pipeline/09_validate_shocks.py score        # after hand labelling: agreement, kappa, precision/recall
    python pipeline/09_validate_shocks.py label2       # Claude v2 labels: per-moment evidence, forced choice
    python pipeline/09_validate_shocks.py sample2      # test sample 2 (80 new moments) -> docs/shock_validation_sample2.csv
    python pipeline/09_validate_shocks.py score2       # after hand labelling sample 2 -> docs/SHOCK_VALIDATION_2.md
    python pipeline/09_validate_shocks.py verify-sheet # next chart verification sheet (60 widest shocks, unlabelled ones)
    python pipeline/09_validate_shocks.py estimate     # true number of shocks = flagged x precision / recall (+ 95% CI)
    python pipeline/09_validate_shocks.py event-groups # candidate topics per chart event -> docs/event_groups_review.csv
    python pipeline/09_validate_shocks.py sport-check  # proposed is_sport fix (pipeline/sport.py) on all candidates
    python pipeline/09_validate_shocks.py waves-label  # one-line Claude category per wave topic (Batches API, cached)
    python pipeline/09_validate_shocks.py waves-sample # after make story: local hand-label sheet docs/waves_review.csv
    python pipeline/09_validate_shocks.py waves-score  # hand labels vs Claude categories -> docs/WAVES_VALIDATION.md
    python pipeline/09_validate_shocks.py waves-verify-sheet # top 30 clean waves -> docs/wave_chart_verification.csv

Candidates: every non-sport global moment (is_global, is_sport false, topic not hidden). "Current shocks" are the
moments in data/export/story/shocks.json as last exported (built with the old 20-country rule).
The timing rule is pipeline/kinds.py (shock = biggest moment reaches >= N countries, half of its countries within
3 h, at most 4 days in 10+ countries); N = 15 now, 10 and 20 are robustness variants.

Claude: claude-haiku-5-5 via the Message Batches API, same key handling as step 3 (python-dotenv, never printed),
batch pricing logged, every answer validated against a JSON schema, malformed answers retried once, everything
cached in cache/claude/shocks/. Total Claude spend across all runs must stay under SPEND_ALERT_USD.
Nothing here changes shocks.json or STORY_NUMBERS.md.
"""
import json
import random
import re
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from common import (CACHE, CLAUDE_MODEL, DOCS, INTERIM, PRICE_IN_PER_MTOK, PRICE_OUT_PER_MTOK, ROOT,  # noqa: E402
                    SPEND_ALERT_USD, SPEND_LIMIT_USD, WORK, load_json, save_json)
from kinds import topic_features, topic_kinds  # noqa: E402

PROMPT_VERSION = "shock-v1"
CHUNK = 40
THRESHOLDS = (10, 15, 20)
SAMPLE_N = 100
SEED = 13
SDIR = CACHE / "claude" / "shocks"
SDIR.mkdir(parents=True, exist_ok=True)
LABELS = SDIR / "labels.jsonl"
BATCH_LOG = SDIR / "batches.json"
SAMPLE = DOCS / "shock_validation_sample.csv"
KEY = DOCS / "shock_validation_key.csv"          # git-ignored
SAMPLE2 = DOCS / "shock_validation_sample2.csv"  # test sample for the final rule (git-ignored, like the key)
KEY2 = DOCS / "shock_validation_key2.csv"        # git-ignored
SAMPLE2_N = 80
SEED2 = 29
EXPORT = ROOT / "data" / "export"
SCHEDULED = ["scheduled", "unscheduled", "unsure"]
EVENT_TYPES = ["death", "outage", "disaster", "politics_conflict", "launch", "viral_celebrity", "other"]
# hand labels may also say "sport": the moment is really sport (athlete, competition, club, sport site), i.e. the
# is_sport rule leaked it into the non-sport candidates. Claude was not offered this label.
# "markets": stocks, indices, crypto, gold, currencies (Claude was not offered this label either)
HUMAN_EVENT_TYPES = EVENT_TYPES + ["sport", "markets"]

SYSTEM = """You classify global moments of Google search attention: a topic that started trending in many countries within an hour.

Each input line is one JSON object:
  i: id to echo back
  name: the topic's name (English, from an earlier labelling step; may be imperfect)
  date, start_utc: when the first country started trending it (UTC)
  phrasings: the searches people typed, in several languages
  related: other searches Google grouped with the topic's searches
  countries: countries reached; countries_60min: countries within 60 minutes; minutes_to_half: minutes until half of them
  wikidata: a matching Wikidata item (id, label, description), if one was found

For every object return one item:
  scheduled: "scheduled" if the date of what caused the searches was publicly known in advance (a match or
    tournament, an award show, a product launch event, an election, a holiday, a scheduled release or broadcast);
    "unscheduled" if nobody could have known the day in advance (a death, an outage, a disaster, an accident,
    an arrest, a surprise announcement, a viral moment); "unsure" if the evidence does not show which.
  what_happened: one short sentence on what most likely drove the searches, based only on the evidence.
    If it is not clear, write "Unclear from the evidence."
  event_type: death | outage | disaster | politics_conflict | launch | viral_celebrity | other
  confidence: 0 to 1, how sure you are about "scheduled"

Rules:
- Rely only on the evidence given. You may recognise what kind of thing a name refers to (a football club, an
  actor, an app), but do not add facts that are not in the evidence: no dates, causes, numbers or outcomes you
  cannot see in the phrasings, related searches or Wikidata description.
- Many of these events happened after your training data. Do not assume you know about them.
- If the evidence does not show whether the date was known in advance, answer "unsure". Do not guess.
- A person trending is not by itself a death: say "death" only if the phrasings or related searches point to
  one (e.g. "died", "muere", "rip", "cause of death").

Return exactly one item per input id."""

SCHEMA = {"type": "object", "properties": {"items": {"type": "array", "items": {
    "type": "object",
    "properties": {"i": {"type": "integer"}, "scheduled": {"type": "string", "enum": SCHEDULED},
                   "what_happened": {"type": "string"}, "event_type": {"type": "string", "enum": EVENT_TYPES},
                   "confidence": {"type": "number"}},
    "required": ["i", "scheduled", "what_happened", "event_type", "confidence"], "additionalProperties": False}}},
    "required": ["items"], "additionalProperties": False}


# ---- v2 (2026-11-16): per-moment evidence, forced choice (no "unsure"), confidence 0-1
PROMPT_VERSION_V2 = "shock-v2"
SCHEDULED_V2 = ["scheduled", "unscheduled"]
SYSTEM_V2 = SYSTEM.split("For every object return one item:")[0].replace(
    "  phrasings: the searches people typed, in several languages\n"
    "  related: other searches Google grouped with the topic's searches\n",
    "  phrasings: the searches people typed during THIS moment (in several languages), most frequent first\n"
    "  related: the searches Google grouped with them during THIS moment only, most frequent first\n") + """For every object return one item:
  scheduled: "scheduled" if the date of what caused the searches was publicly known in advance (a match or
    tournament, an award show, a product launch event, an election, a holiday, a scheduled release or broadcast);
    "unscheduled" if nobody could have known the day in advance (a death, an outage, a disaster, an accident,
    an arrest, a surprise announcement, a viral moment). You must choose one of the two.
  confidence: 0 to 1, how likely your choice is correct (0.5 = a coin flip, 1 = certain)
  what_happened: one short sentence on what most likely drove the searches, based only on the evidence.
    If it is not clear, write "Unclear from the evidence."
  event_type: death | outage | disaster | politics_conflict | launch | viral_celebrity | other

Rules:
- Rely only on the evidence given. You may recognise what kind of thing a name refers to (a football club, an
  actor, an app), but do not add facts that are not in the evidence: no dates, causes, numbers or outcomes you
  cannot see in the phrasings, related searches or Wikidata description.
- Many of these events happened after your training data. Do not assume you know about them.
- Always choose scheduled or unscheduled. When the evidence is weak, choose the more likely one and give a
  confidence near 0.5.
- A person trending is not by itself a death: say "death" only if the phrasings or related searches point to
  one (e.g. "died", "muere", "rip", "cause of death").

Return exactly one item per input id."""
SCHEMA_V2 = json.loads(json.dumps(SCHEMA))
SCHEMA_V2["properties"]["items"]["items"]["properties"]["scheduled"]["enum"] = SCHEDULED_V2


def iso(ts):
    return pd.Timestamp(ts).strftime("%Y-%m-%dT%H:%MZ")


def mkey(topic_id, start):
    """Stable moment key (moment ids change when moments are rebuilt)."""
    return f"{topic_id}|{iso(start)}"


# ------------------------------------------------------------------ data
def load():
    import importlib.util
    spec = importlib.util.spec_from_file_location("export05", Path(__file__).parent / "05_export.py")
    ex = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ex)
    t, meta, m = ex.load()                                # national rows, topic meta, moments
    t["day"] = t.start_time_utc.dt.strftime("%Y-%m-%d")
    hidden, _, _ = ex.visibility(t, meta)
    f = topic_features(t, m, meta)
    cand = m[m.is_global & ~m.is_sport.astype(bool) & ~m.topic_id.isin(hidden)].copy()
    cand["key"] = [mkey(a, b) for a, b in zip(cand.topic_id, cand.start_utc)]
    for n in THRESHOLDS:
        k = topic_kinds(f, n)
        cand[f"rule_shock_{n}"] = cand.topic_id.map(k).eq("shock")
    lab = pd.read_parquet(WORK / "string_topics.parquet", columns=["topic_id", "canonical_en"])
    named = set(lab[lab.canonical_en.notna() & (lab.canonical_en.str.lower() != "unknown")].topic_id)
    cand["named"] = (cand.topic_name.astype(str).str.len() > 2) & cand.topic_id.isin(named)
    cur = json.load(open(EXPORT / "story" / "shocks.json"))
    cur_keys = {mkey(x["topic_id"], pd.Timestamp(x["date_utc"])) for x in cur["moments"]}
    cand["current_shock"] = cand.key.isin(cur_keys)
    return t, meta, m, cand, len(cur["moments"])


def related_for(topic_ids):
    st = pd.read_parquet(WORK / "string_topics.parquet", columns=["sid", "topic_id", "n_rows"])
    st = st[st.topic_id.isin(topic_ids)]
    rel = pd.read_parquet(WORK / "strings.parquet", columns=["sid", "related_top"]).merge(st, on="sid")
    out = {}
    for tid, g in rel.groupby("topic_id"):
        w = {}
        for terms, n in zip(g.related_top, g.n_rows):
            for r in terms:
                w[r] = w.get(r, 0) + n
        out[tid] = [x for x, _ in sorted(w.items(), key=lambda kv: -kv[1])[:10]]
    return out


def wikidata_for(meta):
    wd = pd.read_parquet(WORK / "wikidata_qids.parquet")
    info = wd.drop_duplicates("qid").set_index("qid")
    out = {}
    for tid, q in meta.qid.dropna().items():
        if q in info.index:
            out[tid] = {"id": q, "label": info.wd_label.get(q), "desc": (info.wd_desc.get(q) or "")[:100]}
    return out


def records(cand, meta):
    rel = related_for(set(cand.topic_id))
    wd = wikidata_for(meta)
    recs = {}
    for r in cand.itertuples():
        ph = list(dict.fromkeys(c["phrasing"].lower() for c in r.countries if c["phrasing"]))[:8]
        rec = {"name": str(r.topic_name), "date": iso(r.start_utc)[:10], "start_utc": iso(r.start_utc)[11:16],
               "phrasings": ph, "related": rel.get(r.topic_id, [])[:10], "countries": int(r.reach),
               "countries_60min": int(r.reach_60), "minutes_to_half": int(r.minutes_to_half)}
        if r.topic_id in wd:
            rec["wikidata"] = wd[r.topic_id]
        recs[r.key] = rec
    return recs


def moment_evidence(cand):
    """{key: (phrasings, related)} from the topic's national rows inside the moment only (start_utc .. end_utc, at
    least 1 h): phrasings = the moment's per-country phrasings and raw searches, related = those rows' Google related
    searches; both ranked by how many rows have them. Same window as the moment-level sport rule (sport.py)."""
    from collections import Counter
    rows = pd.read_parquet(INTERIM / "topics.parquet", columns=["topic_id", "level", "start_time_utc", "query_raw", "related"],
                           filters=[("topic_id", "in", sorted(set(cand.topic_id)))])
    rows = rows[rows.level == "country"]
    by_t = {k: g for k, g in rows.groupby("topic_id")}
    out = {}
    for r in cand.itertuples():
        g = by_t.get(r.topic_id)
        lo, hi = r.start_utc, max(r.end_utc, r.start_utc + pd.Timedelta(hours=1))
        ph = Counter(c["phrasing"].lower() for c in r.countries if c["phrasing"])
        rel = Counter()
        if g is not None:
            w = g[(g.start_time_utc >= lo) & (g.start_time_utc <= hi)]
            ph.update(w.query_raw.str.lower())
            for lst in w.related:
                rel.update(set(x.lower() for x in (lst if lst is not None else [])))
        phr = [x for x, _ in ph.most_common(10)]
        out[r.key] = (phr, [x for x, _ in rel.most_common(25) if x not in set(phr)][:15])
    return out


def records_v2(cand, meta):
    """Like records(), but phrasings and related searches come from this moment only."""
    ev = moment_evidence(cand)
    wd = wikidata_for(meta)
    recs = {}
    for r in cand.itertuples():
        ph, rel = ev[r.key]
        rec = {"name": str(r.topic_name), "date": iso(r.start_utc)[:10], "start_utc": iso(r.start_utc)[11:16],
               "phrasings": ph, "related": rel, "countries": int(r.reach),
               "countries_60min": int(r.reach_60), "minutes_to_half": int(r.minutes_to_half)}
        if r.topic_id in wd:
            rec["wikidata"] = wd[r.topic_id]
        recs[r.key] = rec
    return recs


def label2(cand, meta):
    """v2 labels for every candidate: per-moment evidence, forced scheduled/unscheduled, Haiku (Sonnet 5.5 would
    cost ~$1.2 for the v1 token volume at batch prices $1/$5 per MTok, over the $1 cap set for this run)."""
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    import anthropic
    client = anthropic.Anthropic()        # reads ANTHROPIC_API_KEY from the environment; never printed
    log = load_json(BATCH_LOG, {"batches": []})
    done = load_labels(PROMPT_VERSION_V2)
    recs = records_v2(cand, meta)
    todo = [(k, v) for k, v in recs.items() if k not in done]
    n_chars = sum(len(json.dumps(v, ensure_ascii=False)) for _, v in todo)
    est_in = n_chars / 2.5 + (len(todo) / CHUNK + 1) * 1100           # ~2.5 chars per token (multilingual)
    est = est_in * PRICE_IN_PER_MTOK / 1e6 + len(todo) * 90 * PRICE_OUT_PER_MTOK / 1e6
    est_sonnet = est_in * 1.0 / 1e6 + len(todo) * 90 * 5.0 / 1e6
    spent_all = total_spent_all(log)
    print(f"{len(recs):,} candidates, {len(done):,} already labelled (v2), {len(todo):,} to send; estimated cost "
          f"${est:.3f} with {CLAUDE_MODEL} (Sonnet 5.5 would be ~${est_sonnet:.2f}); spend so far ${spent_all:.4f}")
    if spent_all + est > SPEND_ALERT_USD:
        sys.exit(f"would exceed the ${SPEND_ALERT_USD:.0f} alert level (limit ${SPEND_LIMIT_USD:.0f}); not sending")
    if todo:
        bad = run_batch(client, todo, f"shock2-{len(log['batches'])}", log, V2)
        if bad:
            print(f"retrying {len(bad)} once")
            run_batch(client, [(k, recs[k]) for k in bad], f"shock2-retry-{len(log['batches'])}", log, V2)
    lab = pd.DataFrame(load_labels(PROMPT_VERSION_V2).values())
    print(f"labelled {len(lab):,}/{len(recs):,}; all Claude runs ${total_spent_all(load_json(BATCH_LOG)):.4f}")
    if len(lab):
        print(lab.scheduled.value_counts().to_string())
        print(lab.confidence.describe().round(3).to_string())


# ------------------------------------------------------------------ 1 thresholds
def thresholds(cand, n_current):
    named = cand[cand.named]
    out = {"candidates_non_sport_global": int(len(cand)), "current_shocks_json": n_current,
           "current_shocks_matched": int(cand.current_shock.sum()),
           "shock_moments_by_min_reach": {str(n): int(named[f"rule_shock_{n}"].sum()) for n in THRESHOLDS},
           "note": "Sport-free global moments of topics tagged shock, named topics only (as in shocks.json). "
                   "min reach = the topic's biggest moment must reach this many countries."}
    save_json(WORK / "shock_thresholds.json", out)
    print(json.dumps(out, indent=1))
    return out


# ------------------------------------------------------------------ 3 Claude labels
def validate(it, ids, allowed=SCHEDULED):
    try:
        return (it["i"] in ids and it["scheduled"] in allowed and it["event_type"] in EVENT_TYPES
                and isinstance(it["what_happened"], str) and 0 < len(it["what_happened"].strip()) <= 300
                and isinstance(it["confidence"], (int, float)) and 0 <= it["confidence"] <= 1)
    except (KeyError, TypeError):
        return False


def load_labels(version=PROMPT_VERSION):
    out = {}
    if LABELS.exists():
        for line in LABELS.read_text().splitlines():
            r = json.loads(line)
            if r.get("prompt_version") == version:
                out[r["key"]] = r
    return out


def spent(log):
    return sum(b.get("cost_usd") or 0 for b in log["batches"])


def total_spent_all(log):
    main = load_json(CACHE / "claude" / "batches.json", {"batches": []})
    return spent(main) + spent(log)


V1 = {"version": PROMPT_VERSION, "system": SYSTEM, "schema": SCHEMA, "allowed": SCHEDULED}
V2 = {"version": PROMPT_VERSION_V2, "system": SYSTEM_V2, "schema": SCHEMA_V2, "allowed": SCHEDULED_V2}


def make_requests(items, prefix, spec=V1):
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request
    reqs, members = [], {}
    for k in range(0, len(items), CHUNK):
        chunk = items[k:k + CHUNK]
        cid = f"{prefix}-{k // CHUNK:04d}"
        members[cid] = [key for key, _ in chunk]
        lines = [json.dumps({"i": j, **rec}, ensure_ascii=False) for j, (_, rec) in enumerate(chunk)]
        reqs.append(Request(custom_id=cid, params=MessageCreateParamsNonStreaming(
            model=CLAUDE_MODEL, max_tokens=10000, system=spec["system"], thinking={"type": "disabled"},
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": spec["schema"]}},
            messages=[{"role": "user", "content": "\n".join(lines)}])))
    return reqs, members


def run_batch(client, items, prefix, log, spec=V1):
    reqs, members = make_requests(items, prefix, spec)
    b = client.messages.batches.create(requests=reqs)
    entry = {"id": b.id, "prefix": prefix, "created": time.time(), "members": members, "status": "in_progress"}
    log["batches"].append(entry)
    save_json(BATCH_LOG, log)
    print(f"submitted batch {b.id}: {len(reqs)} requests, {len(items)} moments", flush=True)
    while True:
        s = client.messages.batches.retrieve(b.id)
        if s.processing_status == "ended":
            break
        print(f"  processing={s.request_counts.processing} succeeded={s.request_counts.succeeded}", flush=True)
        time.sleep(30)
    usage, good, bad = {"input_tokens": 0, "output_tokens": 0}, [], []
    with open(SDIR / f"{b.id}.jsonl", "w") as raw:
        for res in client.messages.batches.results(b.id):
            raw.write(res.to_json(indent=None) + "\n")
            keys = members[res.custom_id]
            if res.result.type != "succeeded":
                bad += keys
                continue
            msg = res.result.message
            usage["input_tokens"] += msg.usage.input_tokens
            usage["output_tokens"] += msg.usage.output_tokens
            text = next((blk.text for blk in msg.content if blk.type == "text"), "")
            try:
                its = json.loads(text)["items"]
            except (json.JSONDecodeError, KeyError, TypeError):
                its = []
            got = {}
            for it in its:
                if validate(it, set(range(len(keys))), spec["allowed"]) and it["i"] not in got:
                    got[it["i"]] = it
            for j, key in enumerate(keys):
                if j in got:
                    it = got[j]
                    good.append({"key": key, "prompt_version": spec["version"], "batch_id": b.id,
                                 "scheduled": it["scheduled"], "what_happened": it["what_happened"].strip(),
                                 "event_type": it["event_type"], "confidence": float(it["confidence"])})
                else:
                    bad.append(key)
    with open(LABELS, "a") as fh:
        for g in good:
            fh.write(json.dumps(g, ensure_ascii=False) + "\n")
    cost = (usage["input_tokens"] * PRICE_IN_PER_MTOK + usage["output_tokens"] * PRICE_OUT_PER_MTOK) / 1e6
    entry.update(status="ended", usage=usage, cost_usd=cost, n_good=len(good), invalid=bad)
    save_json(BATCH_LOG, log)
    print(f"  batch {b.id}: {len(good)} valid, {len(bad)} invalid; tokens in {usage['input_tokens']:,} "
          f"out {usage['output_tokens']:,}; cost ${cost:.4f}", flush=True)
    return bad


def label(cand, meta):
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    import anthropic
    client = anthropic.Anthropic()        # reads ANTHROPIC_API_KEY from the environment; never printed
    log = load_json(BATCH_LOG, {"batches": []})
    done = load_labels()
    recs = records(cand, meta)
    todo = [(k, v) for k, v in recs.items() if k not in done]
    # cost estimate from the shared step-3 price per token (~ 120 input + 70 output tokens per moment, + prompt)
    est = (len(todo) * 260 + (len(todo) / CHUNK + 1) * 900) * PRICE_IN_PER_MTOK / 1e6 + \
        len(todo) * 90 * PRICE_OUT_PER_MTOK / 1e6
    spent_all = total_spent_all(log)
    print(f"{len(recs):,} candidates, {len(done):,} already labelled, {len(todo):,} to send; "
          f"estimated cost ${est:.3f}; Claude spend so far (all runs) ${spent_all:.4f}")
    if spent_all + est > SPEND_ALERT_USD:
        sys.exit(f"would exceed the ${SPEND_ALERT_USD:.0f} alert level (limit ${SPEND_LIMIT_USD:.0f}); not sending")
    if todo:
        bad = run_batch(client, todo, f"shock-{len(log['batches'])}", log)
        if bad:                                   # retry malformed / missing answers once
            print(f"retrying {len(bad)} once")
            run_batch(client, [(k, recs[k]) for k in bad], f"shock-retry-{len(log['batches'])}", log)
    done = load_labels()
    lab = pd.DataFrame(done.values())
    print(f"labelled {len(lab):,}/{len(recs):,}; total shock-labelling cost ${spent(log):.4f}; "
          f"all Claude runs ${total_spent_all(log):.4f}")
    if len(lab):
        print(lab.scheduled.value_counts().to_string())
        print(lab.event_type.value_counts().to_string())


# ------------------------------------------------------------------ 4 blind sample
def sample(cand, meta):
    if SAMPLE.exists() and pd.read_csv(SAMPLE)[["scheduled_label", "event_type_label"]].notna().any().any():
        sys.exit(f"{SAMPLE} already has hand labels: not overwritten (move it away to draw a new one)")
    labels = load_labels()
    pool = cand[cand.named]
    shock, other = pool[pool.current_shock], pool[~pool.current_shock]
    rng = np.random.default_rng(SEED)
    a = shock.iloc[rng.choice(len(shock), SAMPLE_N // 2, replace=False)]
    b = other.iloc[rng.choice(len(other), SAMPLE_N - SAMPLE_N // 2, replace=False)]
    s = pd.concat([a.assign(stratum="current_shock"), b.assign(stratum="not_current_shock")])
    s = s.sample(frac=1, random_state=SEED).reset_index(drop=True)
    recs = records(s, meta)
    out, key = [], []
    for i, r in s.iterrows():
        rec = recs[r.key]
        out.append({"sample_id": i, "name": rec["name"], "date_utc": f"{rec['date']} {rec['start_utc']}",
                    "phrasings": "; ".join(rec["phrasings"]), "related_searches": "; ".join(rec["related"]),
                    "scheduled_label": "", "event_type_label": ""})
        lb = labels.get(r.key, {})
        key.append({"sample_id": i, "key": r.key, "topic_id": r.topic_id, "stratum": r.stratum,
                    "current_shock": bool(r.current_shock), **{f"rule_shock_{n}": bool(r[f"rule_shock_{n}"]) for n in THRESHOLDS},
                    "reach": int(r.reach), "minutes_to_half": int(r.minutes_to_half),
                    "claude_scheduled": lb.get("scheduled"), "claude_event_type": lb.get("event_type"),
                    "claude_confidence": lb.get("confidence"), "claude_what_happened": lb.get("what_happened")})
    pd.DataFrame(out).to_csv(SAMPLE, index=False)
    pd.DataFrame(key).to_csv(KEY, index=False)
    strata = {"current_shock": int(len(shock)), "not_current_shock": int(len(other))}
    save_json(WORK / "shock_sample_strata.json", {"population": strata, "sample": s.stratum.value_counts().to_dict(),
                                                  "seed": SEED})
    print(f"wrote {SAMPLE} ({len(out)} moments, {s.stratum.value_counts().to_dict()}); key in {KEY} (git-ignored)")
    print(f"labels to fill: scheduled_label = {' / '.join(SCHEDULED)}; event_type_label = {' / '.join(HUMAN_EVENT_TYPES)}")


def sample2(cand, meta):
    """Test sample for the final rules (step 4 now carries the moment-level is_sport and is_shock): 80 NEW named
    non-sport global moments, none of them in sample 1, 40 that the shock rule calls shocks and 40 others. Same
    columns as sample 1 plus the helper links; the key (strata, rule flags, Claude v2 labels) is KEY2."""
    if SAMPLE2.exists() and pd.read_csv(SAMPLE2)[["scheduled_label", "event_type_label"]].notna().any().any():
        sys.exit(f"{SAMPLE2} already has hand labels: not overwritten")
    if "is_shock" not in cand:
        sys.exit("moments.parquet has no is_shock column: run `make moments` first")
    used = set(pd.read_csv(KEY, usecols=["key"]).key)
    pool = cand[cand.named & ~cand.key.isin(used)]
    shock, other = pool[pool.is_shock.astype(bool)], pool[~pool.is_shock.astype(bool)]
    rng = np.random.default_rng(SEED2)
    a = shock.iloc[rng.choice(len(shock), SAMPLE2_N // 2, replace=False)]
    b = other.iloc[rng.choice(len(other), SAMPLE2_N - SAMPLE2_N // 2, replace=False)]
    s = pd.concat([a.assign(stratum="rule_shock"), b.assign(stratum="rule_not_shock")])
    s = s.sample(frac=1, random_state=SEED2).reset_index(drop=True)
    recs = records(s, meta)
    v2 = load_labels(PROMPT_VERSION_V2)
    out, key = [], []
    for i, r in s.iterrows():
        rec = recs[r.key]
        out.append({"sample_id": i, "name": rec["name"], "date_utc": f"{rec['date']} {rec['start_utc']}",
                    "phrasings": "; ".join(rec["phrasings"]), "related_searches": "; ".join(rec["related"]),
                    "scheduled_label": "", "event_type_label": ""})
        lb = v2.get(r.key, {})
        key.append({"sample_id": i, "key": r.key, "topic_id": r.topic_id, "stratum": r.stratum,
                    "is_shock": bool(r.is_shock), "current_shock": bool(r.current_shock),
                    "rule_shock_15": bool(r.rule_shock_15), "reach": int(r.reach),
                    "minutes_to_half": int(r.minutes_to_half), "claude_scheduled": lb.get("scheduled"),
                    "claude_event_type": lb.get("event_type"), "claude_confidence": lb.get("confidence"),
                    "claude_what_happened": lb.get("what_happened")})
    pd.DataFrame(out).to_csv(SAMPLE2, index=False)
    pd.DataFrame(key).to_csv(KEY2, index=False)
    strata = {"rule_shock": int(len(shock)), "rule_not_shock": int(len(other))}
    save_json(WORK / "shock_sample2_strata.json", {"population": strata, "sample": s.stratum.value_counts().to_dict(),
                                                   "seed": SEED2, "excluded_sample1": len(used)})
    print(f"wrote {SAMPLE2} ({len(out)} moments, {s.stratum.value_counts().to_dict()}; population {strata}); "
          f"key in {KEY2} (git-ignored)")
    helpers(SAMPLE2, KEY2)


# ------------------------------------------------------------------ 4b labelling helpers
HELPER_COLS = ["google_link", "news_link", "wiki_link", "moment_phrasings", "first_countries", "local_start_hint"]


def helpers(sample_path=SAMPLE, key_path=KEY):
    """Append look-up columns to the sample without showing any Claude output: date-restricted Google and Google
    News searches (moment date +/- 1 day), the Wikipedia page of the topic's Wikidata item, the moment's own top
    phrasings (counted over the countries in that moment), its first 5 countries and the local start time in the
    first country. Row order, ids and the label columns are kept exactly; the key file is only read for ids."""
    from urllib.parse import quote_plus
    s = pd.read_csv(sample_path, dtype=str, keep_default_na=False)
    if (s.scheduled_label != "").any() or (s.event_type_label != "").any():
        sys.exit(f"{sample_path} already has hand labels: not changed")
    s = s[[c for c in s.columns if c not in HELPER_COLS]]
    ids = pd.read_csv(key_path, usecols=["sample_id", "key", "topic_id"], dtype=str).set_index("sample_id")
    m = pd.read_parquet(INTERIM / "moments.parquet", columns=["topic_id", "start_utc", "countries"])
    m["key"] = [mkey(a, b) for a, b in zip(m.topic_id, m.start_utc)]
    m = m[m.key.isin(set(ids.key))].set_index("key")
    qid = pd.read_parquet(INTERIM / "topic_meta.parquet", columns=["topic_id", "qid"]).set_index("topic_id").qid
    cz = json.load(open(INTERIM / "country_timezones.json"))
    cols = {c: [] for c in HELPER_COLS}
    for sid, name_ in zip(s.sample_id, s.name):
        k = ids.loc[sid]
        mo = m.loc[k.key]
        start = pd.Timestamp(mo.start_utc)
        d0, d1 = (start - pd.Timedelta(days=1)).strftime("%m/%d/%Y"), (start + pd.Timedelta(days=1)).strftime("%m/%d/%Y")
        q = quote_plus(name_)
        cols["google_link"].append(f"https://www.google.com/search?q={q}&tbs=cdr:1,cd_min:{d0},cd_max:{d1}")
        cols["news_link"].append(f"https://www.google.com/search?q={q}&tbm=nws&tbs=cdr:1,cd_min:{d0},cd_max:{d1}")
        qq = qid.get(k.topic_id)
        cols["wiki_link"].append(f"https://www.wikidata.org/wiki/Special:GoToLinkedPage/enwiki/{qq}" if isinstance(qq, str) else "")
        cs = list(mo.countries)
        ph = pd.Series([c["phrasing"].lower() for c in cs if c["phrasing"]]).value_counts().head(5)
        cols["moment_phrasings"].append("; ".join(f"{p_} ({n_})" for p_, n_ in ph.items()))
        cols["first_countries"].append(", ".join(f"{c['country_code']} +{c['min_from_start']}m" for c in cs[:5]))
        c0 = cs[0]["country_code"]
        z = cz.get(c0, "UTC")
        cols["local_start_hint"].append(f"{start:%Y-%m-%d %H:%M} UTC = {start.tz_convert(z):%Y-%m-%d %H:%M} in {c0} ({z})")
    out = s.assign(**cols)
    out.to_csv(sample_path, index=False)
    print(f"added {', '.join(HELPER_COLS)} to {sample_path} ({len(out)} rows)")


# ------------------------------------------------------------------ 5 score
def md(df, index=True):
    d = df.reset_index() if index else df
    cols = [str(c) for c in d.columns]
    out = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    out += ["| " + " | ".join("" if pd.isna(v) else str(v) for v in r) + " |" for r in d.itertuples(index=False)]
    return "\n".join(out)


def kappa(a, b):
    from sklearn.metrics import cohen_kappa_score
    return float(cohen_kappa_score(a, b)) if len(set(a) | set(b)) > 1 else float("nan")


def prf(df, pred_col, w):
    """Precision/recall for 'unscheduled' (human label = truth), raw and stratum-weighted."""
    y = df.human_sched.eq("unscheduled")
    p = df[pred_col].astype(bool)
    res = {}
    for name_, wt in (("raw", pd.Series(1.0, index=df.index)), ("weighted", w)):
        tp, fp, fn = (wt * (y & p)).sum(), (wt * (~y & p)).sum(), (wt * (y & ~p)).sum()
        res[name_] = {"precision": round(tp / (tp + fp), 3) if tp + fp else None,
                      "recall": round(tp / (tp + fn), 3) if tp + fn else None}
    return res


def score():
    s = pd.read_csv(SAMPLE)
    k = pd.read_csv(KEY)
    df = s.merge(k, on="sample_id")
    df["human_sched"] = df.scheduled_label.astype(str).str.strip().str.lower().replace({"nan": None})
    df["human_type"] = df.event_type_label.astype(str).str.strip().str.lower().replace({"nan": None})
    bad = df[df.human_type.notna() & (df.human_type != "") & ~df.human_type.isin(HUMAN_EVENT_TYPES)]
    if len(bad):
        print(f"warning: unknown event_type_label values ignored: {sorted(set(bad.human_type))}")
    df = df[df.human_sched.isin(SCHEDULED)]
    if df.empty:
        sys.exit(f"no labelled rows yet: fill scheduled_label in {SAMPLE}")
    strata = load_json(WORK / "shock_sample_strata.json")
    pop = strata["population"]
    L = ["# Shock validation", "", f"_Generated by `pipeline/09_validate_shocks.py score`. {len(df)} hand-labelled moments "
         f"(stratified: current shocks vs other non-sport global moments; weighted = each stratum scaled to its "
         f"population, {pop}). Truth = the hand labels._", ""]
    # is_sport leak: hand label event_type "sport"
    df["human_sport"] = df.human_type.eq("sport")
    lk = df.groupby("stratum").human_sport.agg(["sum", "size"])
    leak_w = sum(pop[h] * lk.loc[h, "sum"] / lk.loc[h, "size"] for h in lk.index) / sum(pop[h] for h in lk.index)
    L += ["## is_sport leak (hand label event_type = sport)", "",
          f"- Overall: **{int(df.human_sport.sum())} of {len(df)}** sampled non-sport moments are really sport "
          f"({df.human_sport.mean():.1%}); weighted to all candidates: **{leak_w:.1%}**"] + \
         [f"- {h}: {int(r['sum'])} of {int(r['size'])} ({r['sum'] / r['size']:.1%})" for h, r in lk.iterrows()] + [""]
    # markets: stocks, indices, crypto, gold, currencies
    df["human_markets"] = df.human_type.eq("markets")
    mk = df.groupby("stratum").human_markets.agg(["sum", "size"])
    shock15 = df[df.rule_shock_15.astype(bool)]
    L += ["## Markets moments (hand label event_type = markets)", "",
          f"- Overall: **{int(df.human_markets.sum())} of {len(df)}** sampled moments ({df.human_markets.mean():.1%})",
          f"- Among current shocks (shocks.json): {int(mk.loc['current_shock', 'sum']) if 'current_shock' in mk.index else 0} "
          f"of {int(mk.loc['current_shock', 'size']) if 'current_shock' in mk.index else 0}",
          f"- Among shocks under the 15-country rule: {int(shock15.human_markets.sum())} of {len(shock15)}",
          f"- Among the other moments: {int(mk.loc['not_current_shock', 'sum']) if 'not_current_shock' in mk.index else 0} "
          f"of {int(mk.loc['not_current_shock', 'size']) if 'not_current_shock' in mk.index else 0}", ""]
    v2 = load_labels(PROMPT_VERSION_V2)
    df["c2_sched"] = df.key.map(lambda k: v2.get(k, {}).get("scheduled"))
    df["c2_conf"] = df.key.map(lambda k: v2.get(k, {}).get("confidence"))
    sections = [("all labelled rows", df), ("without the rows labelled sport", df[~df.human_sport])]
    for title, dd in sections:
        L += score_section(dd, title, pop)
    if df.c2_sched.notna().any():
        L += v2_section(df[~df.human_sport], pop)
    # event type confusion
    e = df[df.human_type.isin(HUMAN_EVENT_TYPES) & df.claude_event_type.isin(EVENT_TYPES)]
    if len(e):
        L += ["## Event type: hand (rows) vs Claude (columns)", "",
              "Claude could not answer `sport` or `markets`; those hand rows show where Claude put them.", "",
              f"accuracy **{(e.human_type == e.claude_event_type).mean():.3f}**, kappa "
              f"**{kappa(e.human_type, e.claude_event_type):.3f}** (n={len(e)}; without sport rows: "
              f"accuracy {(e[e.human_type != 'sport'].human_type == e[e.human_type != 'sport'].claude_event_type).mean():.3f}, "
              f"kappa {kappa(e[e.human_type != 'sport'].human_type, e[e.human_type != 'sport'].claude_event_type):.3f})", "",
              md(pd.crosstab(e.human_type, e.claude_event_type, rownames=["hand"], colnames=["Claude"])), ""]
    # proposed sport fix vs the hand sport rows
    sc = WORK / "sport_check.parquet"
    if sc.exists():
        fx = pd.read_parquet(sc).set_index("key").sport_fix
        df["fix_sport"] = df.key.map(fx).fillna(False).astype(bool)
        tp = int((df.fix_sport & df.human_sport).sum())
        L += ["## Proposed is_sport fix (pipeline/sport.py) vs the hand sport rows", "",
              f"- hand sport rows caught by the fix: **{tp} of {int(df.human_sport.sum())}**; non-sport rows the fix "
              f"would move to sport: **{int((df.fix_sport & ~df.human_sport).sum())} of {int((~df.human_sport).sum())}**", ""]
        miss = df[df.human_sport & ~df.fix_sport]
        if len(miss):
            L += ["Hand sport rows the fix misses: " + "; ".join(miss.name.astype(str)), ""]
        fp = df[df.fix_sport & ~df.human_sport]
        if len(fp):
            L += ["Rows the fix would move but labelled non-sport: " + "; ".join(fp.name.astype(str)), ""]
    (DOCS / "SHOCK_VALIDATION.md").write_text("\n".join(L) + "\n")
    print("\n".join(L))


SPEED_HOURS = (3, 6, 12)
CONF_LEVELS = (0.5, 0.6, 0.7)


def v2_section(df, pop, title="non-sport rows"):
    """Claude v2 (forced choice, per-moment evidence) vs hand labels, and the shock-rule variants, on the given
    rows (sample 1: hand event type != sport). If the rows carry is_shock (sample 2), the chosen rule comes first."""
    d = df[df.c2_sched.notna() & df.human_sched.isin(SCHEDULED_V2)].copy()
    smp = df.stratum.value_counts()
    w = d.stratum.map(lambda h: pop[h] / smp[h])
    L = [f"# Claude v2 labels and shock-rule variants ({title}, n={len(d)})", "",
         "v2 = per-moment evidence (phrasings and related searches from the moment only), forced choice "
         "scheduled / unscheduled with a confidence 0-1 (pipeline/09_validate_shocks.py label2).", "",
         "## Claude v2 vs hand labels", "",
         f"- accuracy **{(d.c2_sched == d.human_sched).mean():.3f}**, Cohen's kappa **{kappa(d.human_sched, d.c2_sched):.3f}**", "",
         md(pd.crosstab(d.human_sched, d.c2_sched, rownames=["hand"], colnames=["Claude v2"])), ""]
    d["c2_unsched_p"] = np.where(d.c2_sched.eq("unscheduled"), d.c2_conf, 1 - d.c2_conf)
    cal = d.assign(bin=pd.cut(d.c2_conf, [0, .6, .7, .8, .9, 1.0], include_lowest=True)).groupby("bin", observed=True).apply(
        lambda g: pd.Series({"n": len(g), "accuracy": round((g.c2_sched == g.human_sched).mean(), 3)}))
    L += ["Accuracy by Claude's confidence:", "", md(cal), ""]
    rules = {}
    if "is_shock" in d:
        rules["**is_shock: the chosen rule (Claude unscheduled, conf >= 0.5)**"] = "is_shock"
    for c in CONF_LEVELS:
        u = d.c2_sched.eq("unscheduled") & (d.c2_conf >= c)
        d[f"a_{c}"] = u
        rules[f"a) Claude unscheduled, conf >= {c}"] = f"a_{c}"
    for c in CONF_LEVELS:
        for h in SPEED_HOURS[1:]:
            d[f"b_{c}_{h}"] = d[f"a_{c}"] & (d.minutes_to_half <= h * 60)
            rules[f"b) a, conf >= {c} AND half of countries within {h} h"] = f"b_{c}_{h}"
    for c in CONF_LEVELS:
        d[f"c_{c}"] = d.rule_shock_15.astype(bool) & d[f"a_{c}"]
        rules[f"c) timing rule 15 AND Claude unscheduled, conf >= {c}"] = f"c_{c}"
    rules["(timing rule 15 alone)"] = "rule_shock_15"
    if "current_shock" in d:
        rules["(old shocks.json, 20-country timing rule)"] = "current_shock"
    rows = []
    for label_, col in rules.items():
        r = prf(d, col, w)
        rows.append({"rule": label_, "flagged": int(d[col].astype(bool).sum()), "precision": r["raw"]["precision"],
                     "recall": r["raw"]["recall"], "weighted precision": r["weighted"]["precision"],
                     "weighted recall": r["weighted"]["recall"]})
    L += ["## Shock-rule variants: precision / recall for 'unscheduled' (hand label = truth)", "",
          f"{int(d.human_sched.eq('unscheduled').sum())} of {len(d)} rows are unscheduled by hand. Speed = the "
          "moment's own minutes until half of its countries trended it.", "",
          md(pd.DataFrame(rows), index=False), ""]
    return L


def score_section(df, title, pop):
    """Claude agreement and timing-rule precision/recall on one subset of the labelled rows."""
    L = [f"# Scores: {title} (n={len(df)})", ""]
    smp = df.stratum.value_counts()
    w = df.stratum.map(lambda h: pop[h] / smp[h])
    # Claude vs human: scheduled
    c = df[df.claude_scheduled.isin(SCHEDULED)]
    acc3 = float((c.claude_scheduled == c.human_sched).mean())
    both = c[(c.claude_scheduled != "unsure") & (c.human_sched != "unsure")]
    L += ["## Claude vs hand labels: scheduled / unscheduled / unsure", "",
          f"- All three classes: accuracy **{acc3:.3f}**, Cohen's kappa **{kappa(c.human_sched, c.claude_scheduled):.3f}** (n={len(c)})",
          f"- Where neither said unsure: accuracy **{(both.claude_scheduled == both.human_sched).mean():.3f}**, "
          f"kappa **{kappa(both.human_sched, both.claude_scheduled):.3f}** (n={len(both)})", "",
          md(pd.crosstab(c.human_sched, c.claude_scheduled, rownames=["hand"], colnames=["Claude"])), ""]
    # timing rule and combined rules vs human 'unscheduled'
    d = df[df.human_sched != "unsure"].copy()
    wd = w.loc[d.index]
    d["claude_unsched"] = d.claude_scheduled.eq("unscheduled")
    rules = {"current shocks.json (old 20-country rule)": "current_shock"}
    for n in THRESHOLDS:
        rules[f"timing rule, min reach {n}"] = f"rule_shock_{n}"
        d[f"combo_{n}"] = d[f"rule_shock_{n}"].astype(bool) & d.claude_unsched
        rules[f"timing rule {n} AND Claude unscheduled"] = f"combo_{n}"
    rules["Claude unscheduled alone"] = "claude_unsched"
    rows = []
    for label_, col in rules.items():
        r = prf(d, col, wd)
        rows.append({"rule": label_, "precision": r["raw"]["precision"], "recall": r["raw"]["recall"],
                     "weighted precision": r["weighted"]["precision"], "weighted recall": r["weighted"]["recall"]})
    L += ["## Precision and recall for 'unscheduled' (hand label = truth; hand 'unsure' left out)", "",
          f"n = {len(d)}. Weighted = strata scaled to their population (the estimate for all non-sport global moments).", "",
          md(pd.DataFrame(rows), index=False), ""]
    return L


# ------------------------------------------------------------------ 5b score sample 2 (test; no tuning)
def score2():
    """Sample 2 = the test sample for the rules chosen on sample 1 (DECISIONS.md, Step 9). Same metrics as
    sample 1, nothing is tuned here. Writes docs/SHOCK_VALIDATION_2.md.
    Sport: sample 2 only holds moments the new sport rule calls non-sport, so hand 'sport' rows measure what the
    rule still misses (leak); wrongly-moved moments cannot be measured on this sample (sample 1 did that)."""
    s = pd.read_csv(SAMPLE2)
    k = pd.read_csv(KEY2)
    df = s.merge(k, on="sample_id")
    df["human_sched"] = df.scheduled_label.astype(str).str.strip().str.lower().replace({"nan": None})
    df["human_type"] = df.event_type_label.astype(str).str.strip().str.lower().replace({"nan": None})
    bad = df[df.human_type.notna() & ~df.human_type.isin(HUMAN_EVENT_TYPES)]
    if len(bad):
        print(f"warning: unknown event_type_label values ignored: {sorted(set(bad.human_type))}")
    bads = df[df.human_sched.notna() & ~df.human_sched.isin(SCHEDULED)]
    if len(bads):
        print(f"warning: unknown scheduled_label values ignored: {sorted(set(bads.human_sched))}")
    # junk topics (step 4 is_junk) are out of every chapter: skip them here too (the sample file is not changed)
    junk = set(pd.read_parquet(INTERIM / "topic_meta.parquet", columns=["topic_id", "is_junk"]).query("is_junk").topic_id) \
        if "is_junk" in pd.read_parquet(INTERIM / "topic_meta.parquet").columns else set()
    skipped = sorted(df[df.topic_id.isin(junk)].sample_id.tolist())
    if skipped:
        print(f"skipping junk-topic rows (sample_id): {skipped}")
    df = df[~df.topic_id.isin(junk)]
    df = df[df.human_sched.isin(SCHEDULED)]
    if df.empty:
        sys.exit(f"no labelled rows yet: fill scheduled_label in {SAMPLE2}")
    pop = load_json(WORK / "shock_sample2_strata.json")["population"]
    v2 = load_labels(PROMPT_VERSION_V2)
    df["c2_sched"] = df.key.map(lambda x: v2.get(x, {}).get("scheduled"))
    df["c2_conf"] = df.key.map(lambda x: v2.get(x, {}).get("confidence"))
    df["c2_type"] = df.key.map(lambda x: v2.get(x, {}).get("event_type"))
    df["human_sport"] = df.human_type.eq("sport")
    df["human_markets"] = df.human_type.eq("markets")
    L = ["# Shock validation, sample 2 (test)", "",
         f"_Generated by `pipeline/09_validate_shocks.py score2`. {len(df)} hand-labelled moments that the final rules "
         f"call non-sport, none from sample 1 (stratified: the shock rule says shock vs not; weighted = each stratum "
         f"scaled to its population, {pop}). Truth = the hand labels. The rules were chosen on sample 1; nothing is "
         f"tuned on this sample. Junk-topic rows skipped (sample_id): {skipped or 'none'}._", ""]
    lk = df.groupby("stratum").human_sport.agg(["sum", "size"])
    leak_w = sum(pop[h] * lk.loc[h, "sum"] / lk.loc[h, "size"] for h in lk.index) / sum(pop[h] for h in lk.index)
    L += ["## Sport the rule still misses (hand label event_type = sport)", "",
          f"- Overall: **{int(df.human_sport.sum())} of {len(df)}** ({df.human_sport.mean():.1%}); weighted to all "
          f"non-sport global moments: **{leak_w:.1%}**"] + \
         [f"- {h}: {int(r['sum'])} of {int(r['size'])} ({r['sum'] / r['size']:.1%})" for h, r in lk.iterrows()]
    miss = df[df.human_sport]
    if len(miss):
        L += ["", "Missed sport rows: " + "; ".join(miss.name.astype(str))]
    L += ["", "(Moments wrongly moved to sport are not in this sample; sample 1 measured those: 1 of 44.)", ""]
    mk = df.groupby("stratum").human_markets.agg(["sum", "size"])
    L += ["## Markets moments (hand label event_type = markets)", "",
          f"- Overall: **{int(df.human_markets.sum())} of {len(df)}**"] + \
         [f"- {h}: {int(r['sum'])} of {int(r['size'])}" for h, r in mk.iterrows()] + [""]
    if df.c2_sched.isna().any():
        print(f"warning: {int(df.c2_sched.isna().sum())} rows have no shock-v2 label")
    L += v2_section(df, pop, "all labelled rows")
    L += v2_section(df[~df.human_sport], pop, "without the rows labelled sport")
    e = df[df.human_type.isin(HUMAN_EVENT_TYPES) & df.c2_type.isin(EVENT_TYPES)]
    if len(e):
        en = e[e.human_type != "sport"]
        L += ["## Event type: hand (rows) vs Claude v2 (columns)", "",
              "Claude could not answer `sport` or `markets`; those hand rows show where Claude put them.", "",
              f"accuracy **{(e.human_type == e.c2_type).mean():.3f}**, kappa **{kappa(e.human_type, e.c2_type):.3f}** "
              f"(n={len(e)}; without sport rows: accuracy {(en.human_type == en.c2_type).mean():.3f}, "
              f"kappa {kappa(en.human_type, en.c2_type):.3f})", "",
              md(pd.crosstab(e.human_type, e.c2_type, rownames=["hand"], colnames=["Claude v2"])), ""]
    (DOCS / "SHOCK_VALIDATION_2.md").write_text("\n".join(L) + "\n")
    print("\n".join(L))


# ------------------------------------------------------------------ chart verification sheets and estimate
CHART_N = 60
BOOT_N = 5000


def chart_pool(t, meta, m):
    """Shock moments as shocks.json selects them (not hidden, named), widest first."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("export05", Path(__file__).parent / "05_export.py")
    ex = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ex)
    hidden, _, _ = ex.visibility(t, meta)
    lab = pd.read_parquet(WORK / "string_topics.parquet", columns=["topic_id", "canonical_en"])
    named = set(lab[lab.canonical_en.notna() & (lab.canonical_en.str.lower() != "unknown")].topic_id)
    ok = ~m.topic_id.isin(hidden) & m.topic_id.isin(named) & (m.topic_name.astype(str).str.len() > 2)
    m = m.assign(key=[mkey(a, b) for a, b in zip(m.topic_id, m.start_utc)])
    return m[ok & m.is_shock.astype(bool)].sort_values(["reach", "reach_60"], ascending=False), m[ok]


def verify_sheet(t, meta, m):
    """Next chart verification sheet: the CHART_N widest shocks (after hand-label overrides) that have no hand label
    yet -> docs/shock_chart_verification.csv (then _2, _3, ...), same columns and helper links as the samples, empty
    label columns, no Claude output; key next to it (git-ignored). Refuses while an earlier sheet is unlabelled.
    Run `make moments` after labelling a sheet, so scheduled rows drop out and the next widest move up."""
    from kinds import load_hand_labels, verification_sheets
    sheets = verification_sheets(DOCS)
    for sp, _ in sheets:
        s_ = pd.read_csv(sp, dtype=str, keep_default_na=False)
        if (s_.scheduled_label.str.strip() == "").any():
            sys.exit(f"{sp.name} still has unlabelled rows: label it, run `make moments`, then run this again")
    hand = load_hand_labels(DOCS)
    pool, _ = chart_pool(t, meta, m)
    top = pool.head(CHART_N)
    todo = top[~top.key.isin(hand)]
    print(f"chart set: {len(top)} widest shocks; already hand-labelled (verified): {len(top) - len(todo)}; to label: {len(todo)}")
    if todo.empty:
        print("all chart shocks are verified: no sheet written")
        return
    n = len(sheets) + 1
    sp = DOCS / ("shock_chart_verification.csv" if n == 1 else f"shock_chart_verification_{n}.csv")
    kp = sp.with_name(sp.stem + "_key.csv")
    recs = records(todo, meta)
    rank = {k: i + 1 for i, k in enumerate(top.key)}
    out, key = [], []
    for i, r in enumerate(todo.itertuples()):
        rec = recs[r.key]
        out.append({"sample_id": i, "name": rec["name"], "date_utc": f"{rec['date']} {rec['start_utc']}",
                    "phrasings": "; ".join(rec["phrasings"]), "related_searches": "; ".join(rec["related"]),
                    "scheduled_label": "", "event_type_label": ""})
        key.append({"sample_id": i, "key": r.key, "topic_id": r.topic_id, "chart_rank": rank[r.key],
                    "reach": int(r.reach), "claude_scheduled": r.claude_scheduled})
    pd.DataFrame(out).to_csv(sp, index=False)
    pd.DataFrame(key).to_csv(kp, index=False)
    print(f"wrote {sp} ({len(out)} moments); key in {kp} (git-ignored)")
    helpers(sp, kp)


def event_groups(t, meta, m):
    """Candidate topics for each chart shock's event group -> docs/event_groups_review.csv (git-ignored): name
    matching proposes, the hand review accepts (column accept). Refuses to overwrite a file with decisions."""
    import events as ev
    p = DOCS / ev.REVIEW_FILE
    if p.exists() and (~pd.read_csv(p, dtype=str, keep_default_na=False).accept.str.strip().isin(["", "no-effect"])).any():
        sys.exit(f"{p} already has accept decisions: not overwritten (move it away to rebuild)")
    pool, _ = chart_pool(t, meta, m)
    top = pool.head(CHART_N)
    tt = pd.read_parquet(INTERIM / "topics.parquet", columns=["topic_id", "country_code", "level", "start_time_utc", "query_raw"])
    tt = tt[(tt.level == "country") & tt.topic_id.notna()]
    rows = ev.candidates(top[["topic_id", "moment_id", "start_utc"]].assign(event=top.topic_name), tt, meta)
    rows.to_csv(p, index=False)
    per = rows.groupby("event", sort=False).size() if len(rows) else pd.Series(dtype=int)
    print(f"wrote {p}: {len(rows)} candidate topics for {per.size} of {len(top)} chart events "
          f"(no candidates: {len(top) - per.size}); generic events (> {ev.MANY_CANDIDATES} candidates): "
          f"{', '.join(f'{k} {v}' for k, v in per[per > ev.MANY_CANDIDATES].items()) or 'none'}")
    print("fill `accept` with yes or no for every row (yes = the topic is about the same event)")


APPT_FOOTBALL_N = 10
APPT_PER_CATEGORY_N = 5
APPT_SHEET = DOCS / "appointment_chart_verification.csv"
APPT_KEY = DOCS / "appointment_chart_verification_key.csv"


def appointments_stage(t, meta, m):
    """Appointments chapter, preparation (Step 9 round 17): category and event figures for every global appointment
    moment (work/appointments_preview.parquet), the stratified chart set (top APPT_FOOTBALL_N football + top
    APPT_PER_CATEGORY_N of each other category by event reach, main topic only until the groups are reviewed), its
    event-group candidates (docs/event_groups_review_appointments.csv) and verification sheet
    (docs/appointment_chart_verification.csv), and the 'surprise inside an appointment' list."""
    import appointments as AP
    import events as ev
    from kinds import load_hand_labels
    _, shown = chart_pool(t, meta, m)
    shown_ids = set(shown.moment_id)
    app_topics = set(m[m.is_global & m.kind.eq("appointment")].topic_id)
    rows = t[["topic_id", "country_code", "start_time_utc"]]
    ns_topics = set(m[m.is_global & m.kind.eq("appointment") & ~m.is_sport.astype(bool)].topic_id)
    tr = pd.read_parquet(INTERIM / "topics.parquet", columns=["topic_id", "level", "start_time_utc", "query_raw", "related"],
                         filters=[("topic_id", "in", sorted(ns_topics))])
    tr = tr[tr.level == "country"]
    groups = ev.load_groups(DOCS, ev.APPOINTMENT_REVIEW_FILES) if ev.reviewed(DOCS, ev.APPOINTMENT_REVIEW_FILES[:1]) else None
    a = AP.build(m, meta, rows[rows.topic_id.isin(app_topics)], tr, SDIR / "labels.jsonl")
    a["shown"] = a.moment_id.isin(shown_ids)
    a = a[a.shown].copy()
    _hs = m[m.hand_scheduled.eq("scheduled")] if "hand_scheduled" in m else m.iloc[:0]
    a["event_id"] = AP.assign_events(a, dict(zip(_hs.moment_id, _hs.hand_event_type))).values
    import importlib.util as _ilu
    _sp = _ilu.spec_from_file_location("export05", Path(__file__).parent / "05_export.py")
    _ex = _ilu.module_from_spec(_sp)
    _sp.loader.exec_module(_ex)
    _hidden, _, _ = _ex.visibility(t, meta)
    extra = AP.extra_members(m, meta, a.moment_id, set(_hidden) | set(meta.index[meta.is_junk]))
    print(f"catalogue members from non-global moments: {len(extra)}")
    a = pd.concat([a, extra], ignore_index=True)
    a["is_sport"] = a.is_sport.astype(bool)
    _tp = set(a.topic_id) | {x for v in (groups or {}).values() for x in v}
    rows_by_topic = {k_: g for k_, g in rows[rows.topic_id.isin(_tp)].groupby("topic_id")}
    units = AP.event_units(a, rows_by_topic, groups)
    units = units[~units.event_id.isin(AP.rejected_events(DOCS))]
    units = units.sort_values(["event_reach", "rank_reach_60"], ascending=False).reset_index(drop=True)
    a.drop(columns=["text"]).to_parquet(WORK / "appointments_preview.parquet", index=False)
    units.drop(columns=["curve"]).to_parquet(WORK / "appointment_events.parquet", index=False)
    g_all = int(m.is_global.sum())
    dropped = a[a.event_id.isna()]
    kept = a[a.event_id.notna()]
    print(f"appointment moments shown: {len(a):,}; holiday dropped: {int((a.category == 'holiday').sum())}; "
          f"unassigned non-sport 'other': {int((dropped.category == 'other').sum())}; in events: {len(kept):,} "
          f"({len(kept) / g_all:.1%} of {g_all:,} global moments); sport {int(kept.is_sport.sum()):,}, non-sport "
          f"{int((~kept.is_sport).sum()):,}")
    print(f"events: {len(units):,} ({int(units.is_catalogue.sum())} from the catalogue, the rest single-moment units)")
    print("events per category:", units.category.value_counts().reindex(AP.CATEGORIES, fill_value=0).to_dict())
    for c in AP.CATEGORIES:
        if c == "holiday":
            continue
        top = units[units.category == c].head(10)
        print(f"\n## {c}: " + "; ".join(f"{r.event} {r.first_utc[:10]} ({r.event_reach}"
                                         + (f", {len(r.members)} moments" if len(r.members) > 1 else "") + ")"
                                         for r in top.itertuples()))
    cat_units = units[units.is_catalogue]
    print("\n## catalogue events found: " + "; ".join(f"{r.event} [{r.category}] {r.event_reach} ({len(r.members)})"
                                                   for r in cat_units.itertuples()))
    print("catalogue events with no member:", [e[1] for e in AP.CATALOGUE if e[0] not in set(units.event_id)])
    print("unassigned non-sport 'other':", "; ".join(f"{r.name} {r.date_utc[:10]}" for r in dropped[dropped.category == 'other'].itertuples()))
    # chart set by event, stratified
    chart = pd.concat([units[units.category == "football"].head(APPT_FOOTBALL_N)] +
                      [units[units.category == c].head(APPT_PER_CATEGORY_N) for c in AP.CATEGORIES
                       if c not in ("football", "holiday")])
    chart.drop(columns=["curve"]).to_parquet(WORK / "appointments_chart.parquet", index=False)
    print(f"\nchart set: {len(chart)} events ({chart.category.value_counts().to_dict()})")
    # follow-up files for chart events that are new: existing sheets and review files are never rewritten (they hold
    # hand labels and decisions); new events go to the next numbered file (_2, _3, ...)
    hand = load_hand_labels(DOCS)
    key_of = dict(zip(a.moment_id, a.key))
    chart = chart.assign(verified=[any(key_of.get(x) in hand for x in mem) for mem in chart.members])

    def _next(stem):
        i = 2
        while (DOCS / f"{stem}_{i}.csv").exists():
            i += 1
        return DOCS / f"{stem}_{i}.csv"
    reviewed_ids = set()
    for p_ in ev.review_files(DOCS, ev.APPOINTMENT_REVIEW_FILES):
        d_ = pd.read_csv(p_, dtype=str, keep_default_na=False)
        reviewed_ids |= set(d_.event_id) if "event_id" in d_ else set()
    in_sheets = set()
    for p_ in [APPT_KEY] + sorted(DOCS.glob("appointment_chart_verification_*_key.csv")):
        if p_.exists():
            in_sheets |= set(pd.read_csv(p_, dtype=str, keep_default_na=False).event_id)
    new_grp = chart[~chart.event_id.isin(reviewed_ids)]
    if len(new_grp):
        tt = pd.read_parquet(INTERIM / "topics.parquet", columns=["topic_id", "country_code", "level", "start_time_utc", "query_raw"])
        tt = tt[(tt.level == "country") & tt.topic_id.notna() & ~tt.topic_id.isin(set(meta.index[meta.is_junk]))]
        cand = AP.event_candidates(new_grp, tt, meta)
        if len(cand):
            p = _next("event_groups_review_appointments")
            cand.to_csv(p, index=False)
            print(f"wrote {p.name}: {len(cand)} candidates for {new_grp.event.tolist()}, "
                  f"{int((cand.accept == '').sum())} to review, {int((cand.accept == 'no-effect').sum())} no-effect")
        else:
            print(f"no event-group candidates for the new chart events {new_grp.event.tolist()}")
    todo = chart[~chart.verified & ~chart.event_id.isin(in_sheets)]
    print(f"chart events verified: {int(chart.verified.sum())} of {len(chart)}; new to label: {len(todo)} "
          f"({todo.event.tolist()})")
    if len(todo):
        sp = _next("appointment_chart_verification")
        kp = sp.with_name(sp.stem + "_key.csv")
        mm = m.set_index("moment_id").loc[todo.largest_member].reset_index()
        mm["key"] = [mkey(x, y) for x, y in zip(mm.topic_id, mm.start_utc)]
        recs = records(mm, meta)
        out, key = [], []
        for i, (r, u) in enumerate(zip(mm.itertuples(), todo.itertuples())):
            rec = recs[r.key]
            out.append({"sample_id": i, "name": u.event if u.is_catalogue else rec["name"],
                        "date_utc": f"{rec['date']} {rec['start_utc']}", "phrasings": "; ".join(rec["phrasings"]),
                        "related_searches": "; ".join(rec["related"]), "scheduled_label": "", "event_type_label": ""})
            key.append({"sample_id": i, "key": r.key, "topic_id": r.topic_id, "moment_id": int(r.moment_id),
                        "event_id": u.event_id, "event": u.event, "category": u.category,
                        "members": "; ".join(map(str, u.member_names)), "reach": int(r.reach),
                        "claude_scheduled": r.claude_scheduled})
        pd.DataFrame(out).to_csv(sp, index=False)
        pd.DataFrame(key).to_csv(kp, index=False)
        helpers(sp, kp)
    # surprise inside an appointment: hand-labelled scheduled, type viral_celebrity or other. The appointment is the
    # one the moment's own searches or Claude's summary name: an appointment-kind moment (any reach >= 10) starting
    # 12 h before to 6 h after, whose name tokens appear in that text; none if nothing is named (no guessing by time)
    sur = {k: v for k, v in hand.items() if v[0] == "scheduled" and v[1] in ("viral_celebrity", "other")}
    mk = m.assign(key=[mkey(x, y) for x, y in zip(m.topic_id, m.start_utc)])
    sm = mk[mk.key.isin(sur) & mk.is_global]
    apps = mk[mk.kind.eq("appointment") & (mk.reach >= 10) & ~mk.topic_id.isin(set(meta.index[meta.is_junk]))]
    summ = {x["key"]: x["what_happened"] for x in load_labels(PROMPT_VERSION_V2).values()}
    trs = pd.read_parquet(INTERIM / "topics.parquet", columns=["topic_id", "level", "start_time_utc", "query_raw", "related"],
                          filters=[("topic_id", "in", sorted(set(sm.topic_id)))])
    trs = {k_: g for k_, g in trs[trs.level == "country"].groupby("topic_id")}
    stop = {"live", "news", "match", "today", "2025", "2026", "film", "with", "from", "that", "this", "vs"}
    res = []
    for r in sm.itertuples():
        text = (summ.get(r.key, "") + " | " + " | ".join(AP.moment_terms(trs, r, k=80))).lower()
        near = apps[(apps.start_utc >= r.start_utc - pd.Timedelta(hours=12)) & (apps.start_utc <= r.start_utc + pd.Timedelta(hours=6))
                    & (apps.topic_id != r.topic_id)].sort_values("reach", ascending=False)
        hit = None
        for x in near.itertuples():
            toks = [w for w in re.findall(r"\w+", str(x.topic_name).lower()) if len(w) >= 4 and w not in stop]
            if toks and all(re.search(rf"\b{re.escape(w)}\b", text) for w in toks[:2]):
                hit = x
                break
        res.append({"moment": r.topic_name, "date_utc": f"{r.start_utc:%Y-%m-%d %H:%M}", "hand_type": sur[r.key][1],
                    "reach": int(r.reach), "appointment": getattr(hit, "topic_name", None),
                    "appointment_utc": f"{hit.start_utc:%Y-%m-%d %H:%M}" if hit is not None else None,
                    "appointment_reach": int(hit.reach) if hit is not None else None,
                    "claude_summary": summ.get(r.key)})
    sr = pd.DataFrame(res).sort_values("reach", ascending=False)
    sr.to_csv(WORK / "appointment_surprises.csv", index=False)
    print(f"\nsurprises inside appointments: {len(sr)} hand-labelled scheduled viral/other global moments; "
          f"appointment named in their searches: {int(sr.appointment.notna().sum())}")
    print(sr.drop(columns=["claude_summary"]).to_string(index=False))


def estimate(t, meta, m):
    """True number of shocks = flagged x precision / recall. flagged = moments the rule alone flags (is_shock_rule:
    Claude unscheduled, conf >= 0.5, rule-based sport) among the shocks.json population (not hidden, named).
    Precision and recall of that rule come from both hand samples: truth = hand unscheduled and not sport, prediction
    = the current rule on that moment; rows weighted by stratum within their sample, each sample's weights scaled to
    its row count; 95% interval from BOOT_N bootstrap resamples within sample x stratum. -> work/shock_estimate.json"""
    _, pop_m = chart_pool(t, meta, m)
    flagged = int(pop_m.is_shock_rule.astype(bool).sum())
    rule = set(m.loc[m.is_shock_rule.astype(bool), ["topic_id", "start_utc"]].apply(lambda r: mkey(r.topic_id, r.start_utc), axis=1))
    parts = []
    for sp, kp, stf, tag in ((SAMPLE, KEY, "shock_sample_strata.json", 1), (SAMPLE2, KEY2, "shock_sample2_strata.json", 2)):
        if not (sp.exists() and kp.exists()):
            continue
        d = pd.read_csv(sp).merge(pd.read_csv(kp, usecols=["sample_id", "key", "stratum"]), on="sample_id")
        d["hs"] = d.scheduled_label.astype(str).str.strip().str.lower()
        d["ht"] = d.event_type_label.astype(str).str.strip().str.lower()
        d = d[d.hs.isin(SCHEDULED_V2)].copy()
        popn = load_json(WORK / stf)["population"]
        nn = d.stratum.value_counts()
        d["w"] = d.stratum.map(lambda h: popn[h] / nn[h])
        d["w"] *= len(d) / d.w.sum()
        d["y"] = d.hs.eq("unscheduled") & d.ht.ne("sport")
        d["p"] = d.key.isin(rule)
        d["sample"] = tag
        parts.append(d)
    pool = pd.concat(parts, ignore_index=True)

    def pr(d):
        tp, fp, fn = (d.w * (d.p & d.y)).sum(), (d.w * (d.p & ~d.y)).sum(), (d.w * (~d.p & d.y)).sum()
        return tp / (tp + fp), tp / (tp + fn)
    P, R = pr(pool)
    rng = np.random.default_rng(SEED)
    groups = [g.index.values for _, g in pool.groupby(["sample", "stratum"])]
    boot = []
    for _ in range(BOOT_N):
        b = pool.loc[np.concatenate([rng.choice(g, len(g), replace=True) for g in groups])]
        p_, r_ = pr(b)
        boot.append(flagged * p_ / r_ if r_ > 0 else np.nan)
    lo, hi = np.nanpercentile(boot, [2.5, 97.5])
    out = {"flagged": flagged, "precision": round(float(P), 3), "recall": round(float(R), 3),
           "estimate": round(float(flagged * P / R), 1), "ci95": [round(float(lo), 1), round(float(hi), 1)],
           "n_rows": int(len(pool)), "n_true": int(pool.y.sum()), "bootstrap": BOOT_N,
           "method": "flagged x precision / recall; rule = Claude shock-v2 unscheduled conf >= 0.5 on rule-based "
                     "non-sport global moments (not hidden, named); precision/recall from hand samples 1 and 2 "
                     "(truth = hand unscheduled and not sport), stratum-weighted, bootstrap within sample x stratum"}
    save_json(WORK / "shock_estimate.json", out)
    print(json.dumps(out, indent=1))


# ------------------------------------------------------------------ is_sport fix check
def sport_check(cand, meta):
    """Proposed is_sport fix on all candidates: entity signal (sport.sport_fix) AND moment-level sporting-event
    evidence AND no moment-level override (death, accident, health, crime, outage). Writes work/sport_check.parquet
    (sport_fix = the moment-level decision, used by the scorer) and work/sport_check.json."""
    from sport import sport_fix, sport_moments
    ent = sport_fix(set(cand.topic_id), meta)
    entm = cand.topic_id.map(ent.set_index("topic_id").sport_fix).fillna(False).astype(bool)
    mom = sport_moments(cand, meta, ent).set_index("key")
    c = cand.assign(entity_sport=entm.values,
                    sport_fix=cand.key.map(mom.sport_moment).fillna(False).astype(bool),
                    entity_reason=cand.key.map(mom.entity_reason), event_evidence=cand.key.map(mom.event_evidence),
                    override=cand.key.map(mom.override), moment_text=cand.key.map(mom.moment_text_sample),
                    type=cand.topic_id.map(meta["type"]))
    c[["key", "topic_id", "topic_name", "entity_sport", "sport_fix", "entity_reason", "event_evidence", "override",
       "current_shock", "rule_shock_15"]].to_parquet(WORK / "sport_check.parquet", index=False)
    e = c[c.entity_sport]
    back = e[~e.sport_fix]
    out = {"candidates": int(len(c)), "entity_signal": int(len(e)), "sport_moment": int(c.sport_fix.sum()),
           "moved_back_to_non_sport": int(len(back)),
           "moved_back_because": {"override (death/accident/health/crime/outage)": int(back.override.notna().sum()),
                                  "no sporting-event evidence": int((back.override.isna() & back.event_evidence.isna()).sum())},
           "sport_moment_evidence": c[c.sport_fix].event_evidence.str.split(":").str[0].value_counts().to_dict(),
           "sport_among_current_shocks": int((c.sport_fix & c.current_shock).sum()), "current_shocks": int(c.current_shock.sum()),
           "sport_among_rule15_shocks": int((c.sport_fix & c.rule_shock_15).sum()), "rule15_shocks": int(c.rule_shock_15.sum())}
    save_json(WORK / "sport_check.json", out)
    print(json.dumps(out, indent=1, ensure_ascii=False))
    ath = back[back.type == "person"].sort_values("reach", ascending=False).head(30)
    L = ["| # | athlete moment | date (UTC) | countries | entity signal | why non-sport | moment searches (sample) |",
         "|---|---|---|---|---|---|---|"]
    for i, r in enumerate(ath.itertuples(), 1):
        why = f"override: {r.override}" if isinstance(r.override, str) else "no sporting-event evidence"
        L.append(f"| {i} | {r.topic_name} | {r.start_utc:%Y-%m-%d %H:%M} | {r.reach} | {r.entity_reason} | {why} | "
                 f"{str(r.moment_text)[:110].replace('|', '/')} |")
    (WORK / "sport_check_athletes_non_sport.md").write_text("\n".join(L) + "\n")
    print("\n".join(L))


# ------------------------------------------------------------------ waves validation (Step 9 round 27)
WAVE_VERSION = "wave-v1"
WDIR = CACHE / "claude" / "waves"
WAVE_LABELS = WDIR / "labels.jsonl"
WAVE_BATCH_LOG = WDIR / "batches.json"
WAVE_CATEGORIES = ["AI/tech", "politics/conflict", "finance/markets", "entertainment/culture", "people/celebrity",
                   "science/health", "generic/always-on query", "other"]
WAVE_SYSTEM = """You classify topics of Google search attention that trended in many countries in several different months.

Each input line is one JSON object:
  i: id to echo back
  name: the topic's name (English, from an earlier labelling step; may be imperfect)
  type: a coarse type from an earlier labelling step (person, media, product, company, event, place, other)
  phrasings: the searches people typed, in several languages, most frequent first
  related: other searches Google grouped with them, most frequent first
  wikidata: a matching Wikidata item (label, description), if one was found

For every object return one item:
  category: one of
    "AI/tech"                  AI tools and models, apps, gadgets, platforms, tech companies and their products
    "politics/conflict"        politicians as political actors, governments, elections, wars, policies, tariffs
    "finance/markets"          stocks, indices, crypto, gold, currencies, prices, banks
    "entertainment/culture"    films, series, music, games, shows, books, fashion
    "people/celebrity"         a person trending as a person (actor, singer, influencer, royal) rather than for a policy
    "science/health"           space, science, disease, medicine, health
    "generic/always-on query"  an everyday utility or habit query with no single story: weather, news, translate,
                               maps, time, calculator, email, a search engine or a word
    "other"                    none of the above
  why: one short sentence, based only on the evidence

Rules:
- Rely only on the evidence given. Many of these topics are from after your training data.
- A product or service people open every day (a search engine, mail, translate, weather) is "generic/always-on query",
  even if it belongs to a tech company. A tech product people search because of news or launches is "AI/tech".

Return exactly one item per input id."""
WAVE_SCHEMA = {"type": "object", "properties": {"items": {"type": "array", "items": {
    "type": "object", "properties": {"i": {"type": "integer"}, "category": {"type": "string", "enum": WAVE_CATEGORIES},
                                     "why": {"type": "string"}},
    "required": ["i", "category", "why"], "additionalProperties": False}}},
    "required": ["items"], "additionalProperties": False}
WAVE_REVIEW_CSV = DOCS / "waves_review.csv"        # git-ignored (hand labels)
WAVE_SAMPLE_N = 40
WAVE_SEED = 31
WAVE_LABEL_CHOICES = ["real recurring story", "always-on query", "misgrouped topic", "should be sport or ritual"]


def load_wave_labels():
    out = {}
    if WAVE_LABELS.exists():
        for line in WAVE_LABELS.read_text().splitlines():
            r = json.loads(line)
            if r.get("prompt_version") == WAVE_VERSION:
                out[r["key"]] = r
    return out


def wave_topic_ids(t, meta):
    """Wave topics as in the story export: is_wave, not junk, not hidden."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("export05", Path(__file__).parent / "05_export.py")
    ex = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ex)
    hidden, _, _ = ex.visibility(t, meta)
    w = meta[meta.is_wave.astype(bool) & ~meta.is_junk.fillna(False).astype(bool)].index
    return sorted(set(w) - hidden)


def waves_label(t, meta, m):
    """One-line Claude category for every wave topic (Batches API, cached in cache/claude/waves/)."""
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    import anthropic
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request
    WDIR.mkdir(parents=True, exist_ok=True)
    ids = wave_topic_ids(t, meta)
    done = load_wave_labels()
    todo = [x for x in ids if x not in done]
    tr = pd.read_parquet(INTERIM / "topics.parquet", columns=["topic_id", "level", "query_raw", "related"],
                         filters=[("topic_id", "in", todo or ["-"])])
    tr = tr[tr.level == "country"]
    wd = wikidata_for(meta)
    recs = {}
    for tid, g in tr.groupby("topic_id"):
        rel = pd.Series([str(q).lower() for v in g.related.dropna() for q in (v if not isinstance(v, str) else [v])])
        rec = {"name": str(meta.topic_name.get(tid, tid)), "type": str(meta["type"].get(tid)),
               "phrasings": g.query_raw.astype(str).str.lower().value_counts().head(8).index.tolist(),
               "related": rel.value_counts().head(8).index.tolist() if len(rel) else []}
        if tid in wd:
            rec["wikidata"] = {"label": wd[tid]["label"], "desc": wd[tid]["desc"]}
        recs[tid] = rec
    log = load_json(WAVE_BATCH_LOG, {"batches": []})
    spent_all = total_spent_all(load_json(BATCH_LOG, {"batches": []})) + spent(log)
    n_chars = sum(len(json.dumps(v, ensure_ascii=False)) for v in recs.values())
    est = (n_chars / 2.5 + (len(recs) / CHUNK + 1) * 600) * PRICE_IN_PER_MTOK / 1e6 + \
        len(recs) * 40 * PRICE_OUT_PER_MTOK / 1e6
    print(f"{len(ids)} wave topics, {len(done)} already labelled, {len(recs)} to send; estimated cost ${est:.4f} "
          f"with {CLAUDE_MODEL}; Claude spend so far (all runs) ${spent_all:.4f}")
    if spent_all + est > SPEND_ALERT_USD:
        sys.exit(f"would exceed the ${SPEND_ALERT_USD:.0f} alert level (limit ${SPEND_LIMIT_USD:.0f}); not sending")
    client = anthropic.Anthropic()        # reads ANTHROPIC_API_KEY from the environment; never printed
    for attempt in range(2):              # the second pass retries malformed / missing answers once
        items = [(k, recs[k]) for k in recs if k not in load_wave_labels()]
        if not items:
            break
        reqs, members = [], {}
        for k in range(0, len(items), CHUNK):
            chunk = items[k:k + CHUNK]
            cid = f"wave{attempt}-{k // CHUNK:04d}"
            members[cid] = [key for key, _ in chunk]
            lines = [json.dumps({"i": j, **rec}, ensure_ascii=False) for j, (_, rec) in enumerate(chunk)]
            reqs.append(Request(custom_id=cid, params=MessageCreateParamsNonStreaming(
                model=CLAUDE_MODEL, max_tokens=8000, system=WAVE_SYSTEM, thinking={"type": "disabled"},
                output_config={"effort": "low", "format": {"type": "json_schema", "schema": WAVE_SCHEMA}},
                messages=[{"role": "user", "content": "\n".join(lines)}])))
        b = client.messages.batches.create(requests=reqs)
        entry = {"id": b.id, "prefix": f"wave{attempt}", "created": time.time(), "members": members}
        log["batches"].append(entry)
        save_json(WAVE_BATCH_LOG, log)
        print(f"submitted batch {b.id}: {len(reqs)} requests, {len(items)} topics", flush=True)
        while client.messages.batches.retrieve(b.id).processing_status != "ended":
            time.sleep(20)
        usage, good, bad = {"input_tokens": 0, "output_tokens": 0}, [], []
        for res in client.messages.batches.results(b.id):
            keys = members[res.custom_id]
            if res.result.type != "succeeded":
                bad += keys
                continue
            msg = res.result.message
            usage["input_tokens"] += msg.usage.input_tokens
            usage["output_tokens"] += msg.usage.output_tokens
            text = next((blk.text for blk in msg.content if blk.type == "text"), "")
            try:
                its = json.loads(text)["items"]
            except (json.JSONDecodeError, KeyError, TypeError):
                its = []
            got = {it["i"]: it for it in its if isinstance(it, dict) and it.get("i") in range(len(keys))
                   and it.get("category") in WAVE_CATEGORIES and isinstance(it.get("why"), str)}
            for j, key in enumerate(keys):
                if j in got:
                    good.append({"key": key, "prompt_version": WAVE_VERSION, "batch_id": b.id,
                                 "category": got[j]["category"], "why": got[j]["why"].strip()[:300]})
                else:
                    bad.append(key)
        with open(WAVE_LABELS, "a") as fh:
            for g_ in good:
                fh.write(json.dumps(g_, ensure_ascii=False) + "\n")
        cost = (usage["input_tokens"] * PRICE_IN_PER_MTOK + usage["output_tokens"] * PRICE_OUT_PER_MTOK) / 1e6
        entry.update(status="ended", usage=usage, cost_usd=cost, n_good=len(good), invalid=bad)
        save_json(WAVE_BATCH_LOG, log)
        print(f"  {len(good)} valid, {len(bad)} invalid; cost ${cost:.4f}", flush=True)
    lab = pd.DataFrame(load_wave_labels().values())
    print(f"labelled {len(lab)}/{len(ids)}; waves cost ${spent(log):.4f}; all Claude runs "
          f"${total_spent_all(load_json(BATCH_LOG, {'batches': []})) + spent(log):.4f}")
    if len(lab):
        print(lab[lab.key.isin(ids)].category.value_counts().to_string())


def waves_sample():
    """Local hand-label sheet docs/waves_review.csv: every wave topic from data/export/story/waves_review.json, with
    a stratified sample of WAVE_SAMPLE_N (by Claude category, proportional, at least 2 per category where possible)
    flagged in_sample and listed first. The Claude category is NOT in the sheet (labels are blind). Never overwrites
    a sheet that already has labels."""
    if WAVE_REVIEW_CSV.exists() and (pd.read_csv(WAVE_REVIEW_CSV, dtype=str, keep_default_na=False).label.str.strip()
                                     != "").any():
        sys.exit(f"{WAVE_REVIEW_CSV} already has hand labels: not overwritten")
    j = load_json(EXPORT / "story" / "waves_review.json")
    d = pd.DataFrame(j["topics"])
    rng = random.Random(WAVE_SEED)
    cats = d.category.value_counts()
    alloc = {c: min(n, 2) for c, n in cats.items()}
    while sum(alloc.values()) < WAVE_SAMPLE_N:      # rest proportional to size (largest remainder)
        c = max(cats.index, key=lambda c: (cats[c] / (alloc[c] + 1)) if alloc[c] < cats[c] else -1)
        alloc[c] += 1
    pick = []
    for c, k in alloc.items():
        ids_ = sorted(d[d.category == c].topic_id)
        pick += rng.sample(ids_, k)
    d["in_sample"] = d.topic_id.isin(pick).astype(int)
    months = j["months"]
    out = pd.DataFrame({
        "in_sample": d.in_sample, "topic_id": d.topic_id, "topic": d["name"],
        "sample_phrasings": d.phrasings.map(" | ".join), "months_15plus": d.months_15plus,
        "months_15plus_list": d.months_15plus_list.map(", ".join), "peak_month": d.peak_month,
        "peak_countries": d.peak_countries, "distinct_countries": d.distinct_countries, "is_constant": d.is_constant,
        "shock_moments": d.shock_moments, "shock_dates": d.shock_dates.map(", ".join),
        **{f"c_{mo}{'_gap' if mo in j['gap_months'] else ''}": d.countries_per_month.map(lambda v, i=i: v[i])
           for i, mo in enumerate(months)},
        "label": "", "notes": ""})
    out = out.sort_values(["in_sample", "months_15plus"], ascending=False)
    out.to_csv(WAVE_REVIEW_CSV, index=False)
    print(f"wrote {WAVE_REVIEW_CSV} ({len(out)} topics, {int(out.in_sample.sum())} in the sample). label = "
          + " / ".join(WAVE_LABEL_CHOICES))
    print(d[d.in_sample == 1].category.value_counts().to_string())


WAVES_REPORT = DOCS / "WAVES_VALIDATION.md"       # local only (names the sample's topics with their labels)


def waves_score():
    """Hand labels of the waves sample (docs/waves_review.csv) against Claude's categories: confusion table, and the
    share of real recurring stories per category and overall (weighted by category size: the sample is stratified by
    Claude category; bootstrap 95% CI within strata). -> docs/WAVES_VALIDATION.md (local)."""
    d = pd.read_csv(WAVE_REVIEW_CSV, dtype=str, keep_default_na=False)
    lab = load_wave_labels()
    d["category"] = d.topic_id.map(lambda x: lab.get(x, {}).get("category"))
    pop = d.category.value_counts()                    # the topics on the sheet (all wave topics when it was drawn)
    s = d[(d.in_sample == "1") & (d.label.str.strip() != "")].copy()
    s["label"] = s.label.str.strip()
    bad = sorted(set(s.label) - set(WAVE_LABEL_CHOICES))
    if bad:
        sys.exit(f"unknown labels: {bad}")
    ct = pd.crosstab(s.category, s.label).reindex(index=[c for c in WAVE_CATEGORIES if c in set(s.category)],
                                                  columns=WAVE_LABEL_CHOICES, fill_value=0)
    ct["n"] = ct.sum(axis=1)
    ct["sheet topics"] = pop.reindex(ct.index).astype(int)
    real = s.label.eq("real recurring story")
    w = s.category.map(pop / s.category.value_counts())
    est = float((real * w).sum() / w.sum())
    rng = np.random.default_rng(WAVE_SEED)
    boots = []
    groups = {c: g for c, g in s.groupby("category")}
    for _ in range(4000):
        num_, den_ = 0.0, 0.0
        for c, g in groups.items():
            x = g.label.eq("real recurring story").values
            b = rng.choice(x, len(x), replace=True)
            num_ += b.mean() * pop[c]
            den_ += pop[c]
        boots.append(num_ / den_)
    lo, hi = np.percentile(boots, [2.5, 97.5])
    gen = s.category.eq("generic/always-on query")
    aon = s.label.eq("always-on query")
    out = {"labelled": int(len(s)), "labels": s.label.value_counts().to_dict(),
           "real_story_share_raw": round(float(real.mean()), 3),
           "real_story_share_weighted": round(est, 3), "real_story_share_ci95": [round(lo, 3), round(hi, 3)],
           "generic_category_precision_for_always_on": [int((gen & aon).sum()), int(gen.sum())],
           "always_on_labels_caught_by_generic": [int((gen & aon).sum()), int(aon.sum())],
           "always_on_by_claude_category": s[aon].category.value_counts().to_dict()}
    save_json(WORK / "waves_validation.json", out)
    L = ["# Waves validation (hand labels vs Claude categories)", "",
         f"Sample: {len(s)} wave topics, stratified by Claude category (docs/waves_review.csv). Rows: Claude's "
         "category; columns: hand label.", "", md(ct), "",
         f"- Real recurring story: {int(real.sum())} of {len(s)} ({real.mean():.0%} raw); weighted by category size "
         f"{est:.0%} (95% CI {lo:.0%}-{hi:.0%}).",
         f"- Claude's generic/always-on category: {int((gen & aon).sum())} of {int(gen.sum())} are hand-labelled "
         f"always-on; it catches {int((gen & aon).sum())} of the {int(aon.sum())} always-on labels (the others: "
         + ", ".join(f"{k} {v}" for k, v in out["always_on_by_claude_category"].items()) + ").", "",
         "| topic | Claude category | hand label | notes |", "|---|---|---|---|"]
    for r in s.sort_values(["category", "label"]).itertuples():
        L.append(f"| {r.topic} | {r.category} | {r.label} | {str(r.notes).replace('|', '/')} |")
    WAVES_REPORT.write_text("\n".join(L) + "\n")
    print(md(ct))
    print(json.dumps(out, indent=1, ensure_ascii=False))


def waves_verify_sheet():
    """Verification sheet for the top 30 clean waves by months at 15+ (data/export/story/waves.json `clean`): for each
    month at 15+, what drove the return (that month's most common searches, its related searches that are not among
    the story's usual ones, and Claude's one-line summary of shock moments that month). Writes the next numbered file
    docs/wave_chart_verification[_N].csv (never overwrites; local only)."""
    j = load_json(EXPORT / "story" / "waves.json")["clean"]
    months, gaps = j["months"], set(j["gap_months"])
    top = j["by_months_15plus"][:30]
    ids = sorted({x for s in top for x in s["topic_ids"]})
    tr = pd.read_parquet(INTERIM / "topics.parquet", columns=["topic_id", "level", "country_code", "start_time_utc",
                                                               "query_raw", "related"], filters=[("topic_id", "in", ids)])
    tr = tr[tr.level == "country"].copy()
    tr["month"] = tr.start_time_utc.dt.strftime("%Y-%m")
    m = pd.read_parquet(INTERIM / "moments.parquet", columns=["topic_id", "start_utc", "kind"])
    m = m[m.topic_id.isin(ids) & m.kind.eq("shock")]
    summ = {}
    if LABELS.exists():
        for line in LABELS.read_text().splitlines():
            x = json.loads(line)
            if x.get("prompt_version") == PROMPT_VERSION_V2:
                summ[x["key"]] = x["what_happened"]

    def rel_list(g):
        return pd.Series([str(q).lower() for v in g.related.dropna() for q in (v if not isinstance(v, str) else [v])])

    rows = []
    for rank, s_ in enumerate(top, 1):
        g = tr[tr.topic_id.isin(s_["topic_ids"])]
        usual = set(rel_list(g).value_counts().head(8).index) | {str(n).lower() for n in s_["topics"]}
        drivers = []
        for mo, c in zip(months, s_["countries_per_month"]):
            if c < 15:
                continue
            gm = g[g.month == mo]
            ph = gm.query_raw.astype(str).str.lower().value_counts().head(3).index.tolist()
            rl = [x for x in rel_list(gm).value_counts().index if x not in usual][:5]
            sh = [summ.get(f"{r.topic_id}|{pd.Timestamp(r.start_utc):%Y-%m-%dT%H:%MZ}") for r in
                  m[m.topic_id.isin(s_["topic_ids"]) & (m.start_utc.dt.strftime("%Y-%m") == mo)].itertuples()]
            sh = [x for x in sh if x]
            drivers.append(f"{mo}{' (gap)' if mo in gaps else ''}: {c} countries; searches: {', '.join(ph)}; "
                           f"new related: {', '.join(rl) or '-'}" + (f"; shock: {' / '.join(sh[:2])}" if sh else ""))
        rows.append({"rank": rank, "story_id": s_["story_id"], "story": s_["name"],
                     "topics_merged": " + ".join(s_["topics"]), "months_15plus": s_["months_15plus"],
                     "distinct_countries": s_["distinct_countries"], "peak_month": s_["peak_month"],
                     "countries_per_month": " ".join(f"{mo[2:]}:{c}{'*' if mo in gaps else ''}"
                                                     for mo, c in zip(months, s_["countries_per_month"])),
                     "what_drove_each_return": "\n".join(drivers), "label": "", "notes": ""})
    base = DOCS / "wave_chart_verification.csv"
    p, i = base, 2
    while p.exists():
        p, i = DOCS / f"wave_chart_verification_{i}.csv", i + 1
    pd.DataFrame(rows).to_csv(p, index=False)
    print(f"wrote {p} ({len(rows)} stories). label = {' / '.join(WAVE_LABEL_CHOICES)}; '*' = gap month")


if __name__ == "__main__":
    stage = sys.argv[1] if len(sys.argv) > 1 else ""
    if stage in ("waves-sample", "waves-score", "waves-verify-sheet"):
        {"waves-sample": waves_sample, "waves-score": waves_score, "waves-verify-sheet": waves_verify_sheet}[stage]()
        sys.exit()
    if stage == "waves-label":
        import importlib.util
        spec = importlib.util.spec_from_file_location("export05", Path(__file__).parent / "05_export.py")
        ex = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ex)
        waves_label(*ex.load())
        sys.exit()
    if stage == "score":
        score()
    elif stage == "score2":
        score2()
    elif stage == "helpers":
        helpers()
    elif stage in ("verify-sheet", "estimate", "event-groups", "appointments"):
        import importlib.util
        spec = importlib.util.spec_from_file_location("export05", Path(__file__).parent / "05_export.py")
        ex = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ex)
        t, meta, m = ex.load()
        {"verify-sheet": verify_sheet, "estimate": estimate, "event-groups": event_groups,
         "appointments": appointments_stage}[stage](t, meta, m)
    elif stage in ("thresholds", "label", "label2", "sample", "sample2", "sport-check"):
        t, meta, m, cand, n_cur = load()
        if stage == "thresholds":
            thresholds(cand, n_cur)
        elif stage == "label":
            thresholds(cand, n_cur)
            label(cand, meta)
        elif stage == "sample2":
            sample2(cand, meta)
        elif stage == "label2":
            label2(cand, meta)
        elif stage == "sport-check":
            sport_check(cand, meta)
        else:
            sample(cand, meta)
    else:
        print(__doc__)
