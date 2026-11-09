"""Step 3(d): Claude naming for the important subset, via the Message Batches API.

    mode "test"  -> 500 random important strings, then print samples + cost + full-run estimate and STOP
    mode "full"  -> every remaining important string (run only after approval)
    mode "retry" -> resend strings whose answers failed validation (each string is retried at most once)

Caching: every batch result is written to cache/claude/raw/<batch_id>.jsonl and every validated
label to cache/claude/labels.jsonl (keyed by query_norm + PROMPT_VERSION). Strings with a cached
label, or that are part of a batch still in flight, are never sent again.

Note: claude-haiku-5-5 rejects non-default sampling parameters, so `temperature=0` cannot be
sent. We disable thinking, use effort "low", constrain output with a JSON schema and cache
every answer, which makes the labels stable for this project.
"""
import json
import re
import sys
import time
from datetime import date, timedelta

import numpy as np
import pandas as pd
from dotenv import load_dotenv

from common import (CACHE, CLAUDE_CHUNK, CLAUDE_MODEL, PRICE_IN_PER_MTOK, PRICE_OUT_PER_MTOK, ROOT,
                    SPEND_ALERT_USD, SPEND_LIMIT_USD, WORK, load_json, save_json)

PROMPT_VERSION = "v2"   # v2 adds the "always English" rule; v1 labels are kept unless listed in REDO_V1
# v1 test labels whose canonical_en was not English (found by review, see DECISIONS.md); re-sent with v2
REDO_V1 = ["blaue hunde tschernobyl", "нурлан сабуров новости", "el caballero de los siete reinos estreno",
           "sturmtief", "familia", "serie tremembe", "حب بلا حدود 51", "مسلسل وننسي اللي كان الحلقة 1"]
TEST_N = 500
CDIR = CACHE / "claude"
RAW = CDIR / "raw"
RAW.mkdir(parents=True, exist_ok=True)
LABELS = CDIR / "labels.jsonl"
BATCH_LOG = CDIR / "batches.json"

TYPES = ["person", "event", "sports_match", "team", "product", "company", "place", "media", "holiday", "other"]
INTENTS = ["question", "news", "live", "result", "how_to", "shopping", "other"]

SYSTEM = f"""You label Google Trends search strings so that different phrasings of the same topic can be merged.

Each input line is one JSON object for one trending search string:
  i: id to echo back
  q: the search string (as typed, lowercased)
  first / last: first and last UTC date it trended (YYYY-MM-DD); n_days: number of distinct days
  countries: ISO country codes where it trended (most frequent first); n_countries: total count
  related: other searches Google grouped with it
  wd: a Wikidata item whose label or alias exactly matches the string, if one was found
  wd_cands: other Wikidata search results, if no exact match was found

For every input object return one item with:
  canonical_en: a short English name for the topic the person was searching for (e.g. "Pope Francis",
    "Death of Pope Francis", "Real Madrid vs Barcelona", "Cloudflare outage"). Use the common English
    name of the person, team, place, product or event; translate non-English searches. Leave out
    intent words such as "news", "live", "score", "today", "how to".
    canonical_en must ALWAYS be in English. Translate names and titles of films, series, books, songs,
    events, organisations and common nouns whenever a common English form exists (e.g. "blaue hunde
    tschernobyl" -> "Blue dogs of Chernobyl", "el caballero de los siete reinos" -> "A Knight of the
    Seven Kingdoms", "familia" -> "Family"). A proper name with no English form is written in Latin
    script (romanised), never in another script and never mixed scripts.
  wikidata_qid: the Q-id of the item the topic is about, only if you are confident; copy it from wd or
    wd_cands when one of them is the right item. Otherwise null. Never invent an id.
  type: one of {", ".join(TYPES)}
  intent: one of {", ".join(INTENTS)}  (what the searcher wanted: a question answered, news, a live
    stream or live score, a final result, instructions, to buy something, or other)
  confidence: 0 to 1, how sure you are that canonical_en names the right topic

Many strings are about events after your training data. For anything you do not recognise, rely on the
related searches, the countries and the date to infer the topic. If they are not enough, set
canonical_en to "unknown", type "other" and a low confidence. Do not guess.

Return exactly one item per input id, in any order."""

SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "i": {"type": "integer"},
                    "canonical_en": {"type": "string"},
                    "wikidata_qid": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                    "type": {"type": "string", "enum": TYPES},
                    "intent": {"type": "string", "enum": INTENTS},
                    "confidence": {"type": "number"},
                },
                "required": ["i", "canonical_en", "wikidata_qid", "type", "intent", "confidence"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}
QID_RE = re.compile(r"^Q[1-9]\d*$")
# canonical_en may only use Latin letters (incl. accents), digits, punctuation and symbols
NON_LATIN = re.compile(r"[^\u0000-\u024F\u1E00-\u1EFF\u2000-\u206F\u20A0-\u20CF\u2100-\u214F]")
EPOCH = date(1970, 1, 1)


def test_sample_ids(s):
    imp = s[s.important].sort_values("sid")
    return imp.sample(TEST_N, random_state=42).sid.tolist()


def _d(n):
    return (EPOCH + timedelta(days=int(n))).isoformat()


def build_record(row, wd):
    qn = row.name  # query_norm is the index
    rec = {"q": row.top_raw.lower().strip() or qn, "first": _d(row.first_day), "last": _d(row.last_day),
           "n_days": len(row.days), "countries": list(row.countries[:6]), "n_countries": int(row.n_countries),
           "related": [t for t in row.related_top if t != qn][:8]}
    w = wd.get(qn)
    if w is not None:
        if isinstance(w.get("wd_qid"), str):
            rec["wd"] = {"id": w["wd_qid"], "label": w["wd_label"], "desc": (w["wd_desc"] or "")[:80]}
        elif isinstance(w.get("wd_candidates"), str):
            c = json.loads(w["wd_candidates"])[:3]
            if c:
                rec["wd_cands"] = [{"id": x["id"], "label": x["label"], "desc": (x["description"] or "")[:60]} for x in c]
    return rec


def validate(item, valid_ids):
    try:
        if item["i"] not in valid_ids:
            return False
        ce = item["canonical_en"]
        if not isinstance(ce, str) or not ce.strip() or len(ce) > 150 or NON_LATIN.search(ce):
            return False
        q = item["wikidata_qid"]
        if q is not None and (not isinstance(q, str) or not QID_RE.match(q)):
            return False
        if item["type"] not in TYPES or item["intent"] not in INTENTS:
            return False
        c = item["confidence"]
        return isinstance(c, (int, float)) and 0 <= c <= 1
    except (KeyError, TypeError):
        return False


def load_labels():
    """Current label per string: the v2 label if there is one, else the v1 label (unless the v1
    label is in REDO_V1, which is dropped so the string is re-sent)."""
    out, redo = {}, set(REDO_V1)
    if LABELS.exists():
        for line in LABELS.read_text().splitlines():
            r = json.loads(line)
            v, q = r.get("prompt_version"), r["query_norm"]
            if v == PROMPT_VERSION or (v == "v1" and q not in redo and out.get(q, {}).get("prompt_version") != PROMPT_VERSION):
                out[q] = r
    return out


def cost_of(usage):
    return (usage["input_tokens"] * PRICE_IN_PER_MTOK + usage["output_tokens"] * PRICE_OUT_PER_MTOK) / 1e6


def make_requests(recs, prefix):
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request
    reqs, members = [], {}
    for k in range(0, len(recs), CLAUDE_CHUNK):
        chunk = recs[k:k + CLAUDE_CHUNK]
        lines = []
        for j, (qn, rec) in enumerate(chunk):
            lines.append(json.dumps({"i": j, **rec}, ensure_ascii=False))
        cid = f"{prefix}-{k // CLAUDE_CHUNK:05d}"
        members[cid] = [qn for qn, _ in chunk]
        reqs.append(Request(custom_id=cid, params=MessageCreateParamsNonStreaming(
            model=CLAUDE_MODEL, max_tokens=12000, system=SYSTEM,
            thinking={"type": "disabled"},
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
            messages=[{"role": "user", "content": "\n".join(lines)}])))
    return reqs, members


def submit_and_collect(client, recs, prefix, log):
    reqs, members = make_requests(recs, prefix)
    batch = client.messages.batches.create(requests=reqs)
    entry = {"id": batch.id, "prefix": prefix, "created": time.time(), "members": members,
             "status": "in_progress", "usage": None}
    log["batches"].append(entry)
    save_json(BATCH_LOG, log)
    print(f"submitted batch {batch.id}: {len(reqs)} requests, {len(recs)} strings")
    return collect(client, entry, log)


def collect(client, entry, log):
    while True:
        b = client.messages.batches.retrieve(entry["id"])
        if b.processing_status == "ended":
            break
        rc = b.request_counts
        print(f"  {entry['id']}: processing={rc.processing} succeeded={rc.succeeded} errored={rc.errored}", flush=True)
        time.sleep(30)
    usage = {"input_tokens": 0, "output_tokens": 0}
    good, bad = [], []
    with open(RAW / f"{entry['id']}.jsonl", "w") as raw:
        for res in client.messages.batches.results(entry["id"]):
            raw.write(res.to_json(indent=None) + "\n")
            qns = entry["members"][res.custom_id]
            if res.result.type != "succeeded":
                bad += qns
                continue
            msg = res.result.message
            usage["input_tokens"] += msg.usage.input_tokens
            usage["output_tokens"] += msg.usage.output_tokens
            text = next((blk.text for blk in msg.content if blk.type == "text"), "")
            try:
                items = json.loads(text)["items"]
            except (json.JSONDecodeError, KeyError, TypeError):
                items = []
            got = {}
            for it in items:
                if validate(it, set(range(len(qns)))) and it["i"] not in got:
                    got[it["i"]] = it
            for j, qn in enumerate(qns):
                if j in got:
                    it = got[j]
                    good.append({"query_norm": qn, "prompt_version": PROMPT_VERSION, "batch_id": entry["id"],
                                 "canonical_en": it["canonical_en"].strip(), "wikidata_qid": it["wikidata_qid"],
                                 "type": it["type"], "intent": it["intent"], "confidence": float(it["confidence"])})
                else:
                    bad.append(qn)
    with open(LABELS, "a") as f:
        for g in good:
            f.write(json.dumps(g, ensure_ascii=False) + "\n")
    entry.update(status="ended", usage=usage, cost_usd=cost_of(usage), n_good=len(good), invalid=bad)
    save_json(BATCH_LOG, log)
    print(f"  batch {entry['id']} ended: {len(good)} valid, {len(bad)} invalid/missing; "
          f"tokens in {usage['input_tokens']:,} out {usage['output_tokens']:,}; cost ${cost_of(usage):.4f}")
    return entry


def total_spent(log):
    return sum(b.get("cost_usd") or 0 for b in log["batches"])


def run(s, mode):
    load_dotenv(ROOT / ".env")
    import anthropic
    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment; never printed
    log = load_json(BATCH_LOG, {"batches": []})
    for e in log["batches"]:          # resume anything left in flight by an interrupted run
        if e["status"] != "ended":
            collect(client, e, log)

    wdp = WORK / "wikidata_links.parquet"
    wd = pd.read_parquet(wdp).set_index("query_norm").to_dict("index") if wdp.exists() else {}
    labels = load_labels()
    in_log = {qn for e in log["batches"] for m in e["members"].values() for qn in m}
    retried = {qn for e in log["batches"] if e["prefix"].startswith("retry") for m in e["members"].values() for qn in m}
    by_q = s.set_index("query_norm")

    if mode == "test":
        ids = test_sample_ids(s)
        todo = [q for q in s.set_index("sid").loc[ids, "query_norm"] if q not in labels and q not in in_log]
    elif mode == "full":
        todo = [q for q in s.loc[s.important].sort_values("vol_sum", ascending=False).query_norm
                if q not in labels and q not in in_log]
        sent_v2 = {qn for e in log["batches"] if e["prefix"] in ("full", "redo") for m in e["members"].values() for qn in m}
        todo += [q for q in REDO_V1 if q not in labels and q not in sent_v2 and q in by_q.index]
    else:  # retry: failed strings from earlier batches, each at most once
        failed = {qn for e in log["batches"] for qn in (e.get("invalid") or [])}
        todo = [q for q in failed if q not in labels and q not in retried]
    print(f"mode={mode}: {len(todo):,} strings to send (already labelled {len(labels):,}; spent so far ${total_spent(log):.4f})")

    if mode == "full" and todo:
        per_string = _cost_per_string(log)
        est = per_string * len(todo)
        print(f"estimated cost for {len(todo):,} strings: ${est:.2f} (at ${per_string*1000:.3f} per 1,000 strings)")
        if total_spent(log) + est > SPEND_ALERT_USD and "--force" not in sys.argv:
            sys.exit(f"Estimate exceeds the ${SPEND_ALERT_USD:.0f} alert level (limit ${SPEND_LIMIT_USD:.0f}). "
                     "Re-run with --force only after confirming.")
    if todo:
        recs = [(q, build_record(by_q.loc[q], wd)) for q in todo]
        prefix = {"test": "test", "full": "full", "retry": f"retry{len(log['batches'])}"}[mode]
        submit_and_collect(client, recs, prefix, log)

    if mode in ("test", "full"):   # retry malformed answers once, automatically
        failed = {qn for e in log["batches"] for qn in (e.get("invalid") or [])}
        labels = load_labels()
        retried = {qn for e in log["batches"] if e["prefix"].startswith("retry") for m in e["members"].values() for qn in m}
        again = [q for q in failed if q not in labels and q not in retried]
        if again:
            print(f"retrying {len(again)} malformed/missing answers once")
            submit_and_collect(client, [(q, build_record(by_q.loc[q], wd)) for q in again],
                               f"retry{len(log['batches'])}", log)

    report(s, log, mode)


def _cost_per_string(log):
    done = [b for b in log["batches"] if b.get("usage")]
    n = sum(b["n_good"] + len(b.get("invalid") or []) for b in done)
    return total_spent(log) / n if n else 0.0


def report(s, log, mode):
    labels = load_labels()
    lab = pd.DataFrame(labels.values())
    spent = total_spent(log)
    print(f"\n=== Claude labelling: {len(lab):,} strings labelled; total spent ${spent:.4f} ===")
    if mode == "test":
        ids = test_sample_ids(s)
        test_q = set(s.set_index("sid").loc[ids, "query_norm"])
        t = lab[lab.query_norm.isin(test_q)]
        print(f"test strings labelled: {len(t)}/{len(test_q)}")
        print(t.type.value_counts().to_string())
        print(f"unknown: {(t.canonical_en.str.lower() == 'unknown').sum()}, with QID: {t.wikidata_qid.notna().sum()}")
        smp = t.sample(min(20, len(t)), random_state=7)[["query_norm", "canonical_en", "wikidata_qid", "type",
                                                         "intent", "confidence"]]
        smp.to_csv(WORK / "claude_test_samples.csv", index=False)
        print(smp.to_string(index=False))
        remaining = int(s.important.sum()) - len(lab)
        per = _cost_per_string(log)
        print(f"\nactual cost of test: ${spent:.4f}")
        print(f"estimated cost of full run ({remaining:,} more strings): ${per*remaining:.2f}  "
              f"(limit ${SPEND_LIMIT_USD:.0f})")
        save_json(WORK / "claude_test_summary.json", {"test_cost_usd": spent, "per_string_usd": per,
                                                     "remaining": remaining, "est_full_usd": per * remaining})
