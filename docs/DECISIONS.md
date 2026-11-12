# Decisions log

Every choice and threshold in the cleaning and topic-merging pipeline. Thresholds live in `pipeline/common.py` unless noted.

## Environment

- **Python 3.9.6** (the only interpreter on this machine). Pinned versions are those `pip` resolved for 3.9: pandas 2.2, pyarrow 21, sentence-transformers 5.1, torch 2.8, anthropic 0.125. The `anthropic` 1.x SDK needs Python ≥ 3.10.
- The API key is loaded from `.env` with python-dotenv. The code never prints or logs it.

## Step 1: download

- Config `trending_queries` maps to `googletrendarchive_preprocessed_170526.csv` (1.9 GB, 10,204,597 rows, 2024-11-28 → 2026-05-17). Config `locations` maps to `Trends_LocationList.csv` (1,358 locations). The file names come from the dataset card's `configs` block.
- Disk check: the script aborts unless free space is at least 4× the download size.
- The raw CSV is kept and also saved as `data/raw/trending_queries.parquet` (all columns as strings) for faster reloads.

## Step 2: cleaning

- **Locations.** `XX` = country feed (`level=country`). `XX-YYY` = sub-national region (`level=region`, `country_code` = first two letters). Purely numeric codes (US Nielsen DMA metros such as `501`) are dropped: 1,127,988 rows. Kept: 9,076,609 rows (3,456,593 country, 5,620,016 region). No other code formats occur.
- **`region`** is the sub-national region's name from the location list. It is null for country rows. It is *not* a world region or continent.
- **Timestamps.** The stored values end in `Z`, and the dataset's R preprocessing stripped a Pacific "UTC-x" label, but the wall-clock is Central European. They are localized as `Europe/Berlin` and converted to UTC.
  - Autumn DST ambiguous hour: assumed CEST (summer time). 1,879 start times are affected.
  - Spring nonexistent hour: shifted forward.
  - 1,423,857 rows have no end time (still trending when scraped). They are left null.
- **Validation** = earliest start of the exact `query_norm` on the event's UTC date. Tolerance 15 min; the script stops before writing if any check fails. All three passed with 0 min difference: pope francis 2025-04-21 07:50, cloudflare 2025-11-18 11:20, jimmy carter 2024-12-29 20:50. The check is limited to the event date because "pope francis" also trended on 2025-04-20, around his Easter appearance.
- **`local_time`** = start time in one zone per country: the brief's 8 explicit zones, then `pytz.country_timezones[cc][0]` for the rest. The full mapping is in `data/interim/country_timezones.json`. It is stored as naive local wall-clock time plus `local_tz`, since one column can't hold mixed zones.
- **`query_norm`**:
  - NFKC, then lowercase.
  - Latin letters transliterated to ASCII (é→e, ø→o, ß→ss).
  - Greek accents dropped.
  - Arabic/Persian/Hebrew optional diacritics removed. Alef/hamza variants → ا, alef maqsura and Persian yeh → ي, Persian keheh → ك (`أول`/`اول` and `فى`/`في` are the same word).
  - Punctuation, symbols and control characters → space; spaces collapsed.
  - Combining marks in Indic/Thai and similar scripts are **kept**: they are vowels, not accents. Cyrillic is left as is (й is a letter).
  - Result: 923,336 raw strings → 895,618 normalized strings. One row normalizes to an empty string.
- **`related`** = `trend_breakdown` split on commas, each item normalized the same way, empties and duplicates dropped, original order kept.

## Step 3: topic merging

All merging runs on the 895,618 distinct `query_norm` strings, and results are mapped back to rows.

- **Importance.** A string is "important" if it trended in ≥ 2 countries or is in any country's top 1% of strings by summed `search_volume_lower`. That gives 155,279 strings (152,657 multi-country, 11,614 top-1%, overlapping).
- **3-day window** (`WINDOW_DAYS=2`): for each UTC day d, strings active on d are compared with strings active on days d, d+1, d+2. Two strings can be merged only if they trended within 2 days of each other at least once. A string is one node for all time, so a merge applies to all of its dates.
- **Generic related searches.** A related search that appears with ≥ 25 distinct trend strings (`GENERIC_DEGREE`, about the 99th percentile) is generic and never counts as evidence. A manual list (news, live, cnn, bbc, today, hoy, en vivo, ao vivo, live score, results, score, weather, google, youtube, facebook, wikipedia) is also blocked. Total: 15,427 terms (`work/generic_related.csv`).

### (a) Typos

- **Exact:** identical `query_norm`.
- **Fuzzy:** rapidfuzz `fuzz.ratio ≥ 92` (normalized Indel similarity ≥ 0.92); both strings ≥ 6 characters; identical sets of digit sequences ("iphone 16" ≠ "iphone 17").
- **Token guard** (`typo_ok`), added after inspecting samples. Accept only if:
  - the strings are identical once spaces and connector words (vs, x, v, mot, …) are removed;
  - or a single word changes and both versions are ≥ 4 characters with word-level ratio ≥ 80;
  - or words are only added, ≤ 3 characters in total ("cf montreal" / "montreal").

  This rejects "uc"/"ut basketball", lottery "thu nam"/"thu tu" (Thursday/Wednesday), "btc usd"/"btc usdt" and "21st"/"22nd day of Ramadan" (Persian).
- **Result:** 40,864 fuzzy pairs, of which 34,478 are kept.
- **Added at your review (applied in combine, `filter_typo_edges`):**
  - if either string has ≤ 8 characters, the pair needs similarity ≥ 0.96. With one edit an 8-character string already falls below 0.94, so in practice short strings are never typo-merged.
  - two strings are never typo-merged if both have a Claude name with confidence ≥ 0.5 and those names differ (compared after `norm()`, so case, accents and punctuation don't count).

### (b) Wikidata

**Current method (after the Claude run, as you requested).** The original per-string search (below) was stopped by the rate limit and replaced:

1. **Verify Claude's QIDs** with `wbgetentities`, 50 ids per request (`03_topics.py wikidata-verify`). A QID counts as verified if the item exists (redirects followed to the target), it isn't a disambiguation/category/list item, one of its labels or aliases (English plus the trending countries' languages) matches Claude's name or the search string after `norm()` (exactly, or `fuzz.ratio ≥ 90`; parentheticals in Claude's name are ignored), and Claude's confidence is ≥ 0.7. Results are in `work/wikidata_claude_check.parquet`.
2. **Look up English names** (`03_topics.py wikidata-names`). The input is the deduplicated `canonical_en` of important strings typed person, team, place or company with confidence ≥ 0.5 and no verified QID. The lookup uses `wbsearchentities` with `language=en` and takes the first exact label/alias match. If Claude's name has a parenthetical ("Georgia (country)"), it is searched without the parenthetical, and the parenthetical's words must appear in the item's description. Results are in `work/wikidata_name_lookup.parquet`.
3. Both are combined in `work/wikidata_qids.parquet`, which combine uses.

- **User-Agent:** `world-attention-research/0.1 (<project GitHub URL>)`. The URL is read from the `WD_CONTACT_URL` environment variable, and the code refuses to call Wikidata without it. No email is used. Every response is cached (`cache/wikidata/entities/`, `cache/wikidata/en/`).
- **Results (Nov 2026 run):**
  - Claude QIDs: 1,537 strings checked. 242 verified; 1,056 point to an item with a different name (mostly made-up IDs: "Anthony Fauci" → an English bishop); 85 match but have confidence < 0.7; 83 don't exist; 71 are disambiguation, category or list items.
  - Name lookup: 51,545 strings, 43,010 distinct names; 36,691 strings (30,086 names) matched; 6,928 strings (6,448 names) had no exact match.
  - In total, 36,933 strings have a QID in `wikidata_qids.parquet`.
- **Rate limiting.** Even with the identified User-Agent, Wikidata throttled the lookup to about 0.5 requests/s and sent about 35,000 HTTP 429 replies, so the lookup took about 104 h instead of the estimated 4.8 h. 6,476 names (7,926 strings) failed after 6 attempts. A retry pass at 0.5 requests/s fixed none of them in 2 h and was stopped on 2026-11-09. **Decision:** these names are final "no ID" (status `no_id_rate_limited` in `wikidata_name_lookup.parquet`). `lookup_names` skips them, so they are never retried. Their strings still merge through the Claude, typo and semantic layers; they just have no QID, so no QID merges and no QID cannot-links.

**Original method (superseded, kept for reference):**

- **Name-like strings** (`looks_like_name`):
  - 1–4 words, 3–40 characters, no digits;
  - no question, intent or match words (how, what, live, score, news, weather, vs, x, ضد, พบ, против, …);
  - CJK strings ≤ 12 characters.

  640k strings qualify overall, 110k of them important.
- **Lookup:** `wbsearchentities`, `type=item`, `limit=7`. Languages are those of the countries where the string trended, most rows first. The country → language map is `COUNTRY_LANG` in `wikidata.py`. The script tries at most 2 languages and stops at the first strong match.
- **Strong match:** the `match.text` of a label or alias, normalized with the same `norm()`, equals the string. The first strong result wins. The number of strong candidates is stored (`wd_n_strong`) for ambiguity. Disambiguation, category, list and template items are ignored.
- **Politeness:** User-Agent `world-attention-research/0.1 (academic data-cleaning project; python-requests)`, with no personal contact. `maxlag=5`. One connection. On a 429, all requests pause for the `Retry-After` value. Every response is cached.
- **Claude QIDs** are used only if Claude picked one of the Wikidata search candidates the script actually retrieved, with confidence ≥ 0.7. Otherwise they are stored as `claude_qid_unverified` and not used, since an LLM can produce QIDs that don't exist.

### (c) Meaning (embeddings)

- **Model:** `intfloat/multilingual-e5-small`, input `"query: " + query_norm`, L2-normalized, float16. Cached in `cache/embeddings/` (895,618 × 384). Took 5 min on Apple MPS.
- **Candidates:** cosine ≥ 0.93 within the window, giving 831,957 pairs. Below 0.93, sampled pairs were mostly unrelated: "francesco sarcina"/"francisco lindor", "chris hemsworth"/"liam hemsworth".
- **Always required:** identical digit sets; and neither string is a "hub" (< 4 characters, only digits, or itself a generic related search). Without the hub rule, "2026" chained ~500 different 2026 events into one group.
- **Accepted rules:**
  - `high_cos+guard`: cosine ≥ 0.96 and the words are the same or only similar variants (`swap_guard`). This rejects swaps of unlike words such as "hom nay"/"hom qua" (today/yesterday) and "mien bac"/"mien nam" (north/south lottery).
  - `high_cos+added_words+related`: cosine ≥ 0.96, one string is the other plus **exactly one** extra word, and there is related-search evidence: one string is in the other's Google related list, or they share ≥ 2 non-generic related searches. Never between a team or person name and a match string ("atletico madrid" vs "atletico madrid vs athletic club"). Allowing more added words let "ramadan 2025" absorb "kurban bayram namazi 2025".
  - `cos+related_link`: cosine ≥ 0.93, one string is in the other's related list (non-generic), and the guard passes or they share ≥ 2 non-generic related searches.
- **Result:** 100,370 accepted edges (62,607 / 19,468 / 18,295 by the three rules).

### (d) Claude naming

- **Prompt v2** (used for the full run) adds: `canonical_en` must always be in English; translate names and titles when a common English form exists ("blaue hunde tschernobyl" → "Blue dogs of Chernobyl"); a proper name with no English form is romanized, never in another script or mixed scripts. Validation now also rejects a `canonical_en` with non-Latin characters, which sends that string to the retry batch.
- **Non-English v1 test labels**, found by review of all 500 and re-sent with v2 (`REDO_V1` in `claude_label.py`):

  | string | v1 label |
  |---|---|
  | blaue hunde tschernobyl | Blaue Hunde Tschernobyl |
  | нурлан сабуров новости | Nurlan Sabуров (mixed scripts) |
  | el caballero de los siete reinos estreno | El Caballero de los Siete Reinos |
  | sturmtief | Sturmtief (storm low, Germany) |
  | familia | Família |
  | serie tremembe | Série Tremembé |
  | حب بلا حدود 51 | Hob Bila Hodood episode 51 (romanized, not translated) |
  | مسلسل وننسي اللي كان الحلقة 1 | Wenensy Elly Kan (romanized, not translated) |

  The other 492 v1 labels are kept: they are English, or proper names with no English form ("Kazuraiza", "Trabzonspor").
- **Confidence below 0.5:** the label may name a topic (`topic_name`) but never creates or blocks a merge. The thresholds actually used are higher: same-name merges need ≥ 0.6, a Claude QID ≥ 0.7, group-level name blocking ≥ 0.8, and the typo name block ≥ 0.5.

- **Model** `claude-haiku-5-5` via the Message Batches API, 150 strings per request.
- **Temperature 0 cannot be set:** Haiku 5.5 rejects non-default sampling parameters (HTTP 400), so the parameter is omitted. Instead: thinking off (`thinking: disabled`), `effort: low`, output constrained with a JSON schema (`output_config.format`), and every answer cached. Labels are stable because each string is labeled exactly once.
- **Input per string:** most common raw form; first and last UTC date; number of days; up to 6 countries plus the total; up to 8 related searches; and the Wikidata strong match (id, label, description) or up to 3 search candidates.
- **Output per string:** `canonical_en`, `wikidata_qid`, `type` (10 values), `intent` (7 values), `confidence`. The model is told to rely on related searches, countries and date for anything it doesn't know, and to answer "unknown" rather than guess.
- **Validation:** every item is checked (id in request, non-empty name ≤ 150 characters, QID pattern `Q\d+`, enum values, confidence 0–1). Missing or invalid items are re-sent once in a retry batch, then given up.
- **Cost guard:** prices are $0.05/MTok in and $0.25/MTok out (batch, 50% off). Spend is logged per batch. `claude-full` aborts if total spend plus the estimate would exceed $5.

### (e) Combine

- **Union-find order:**
  1. same QID;
  2. same `canonical_en` (case-insensitive, confidence ≥ 0.6, not "unknown");
  3. typo edges (best score first);
  4. semantic edges (best cosine first).
- **Cannot-link:** two groups with different QIDs are never merged. In the typo and semantic layers, two groups whose confident Claude names (confidence ≥ 0.8) don't overlap are not merged either. This targets spelling-close but different names that string rules can't separate ("athletic"/"atletico", Athletic Bilbao vs Atlético Madrid). It only takes full effect after the full Claude run.
- **Size cap:** typo and semantic unions that would create a group larger than **50 strings** are refused. This stops chaining; QID and canonical merges are exempt.
- **`topic_id`** = the group's most common QID, else its most common `canonical_en`, else its most common `query_norm` (weighted by rows). **`topic_name`** = the most common `canonical_en`, else the Wikidata label, else the most common raw string.
- A topic is a *thing*, not an event. "Real madrid vs barcelona" in October and in April is one topic, because a string is one node across time.

**Generic short strings (fix of 2026-11-09).** Strings like "real", "madrid", "carlos", "united", "cf" or "liga" were pulling unrelated searches into big topics. A string that is a single word, or has ≤ 4 characters, may now be part of a multi-string topic only if (a) Claude labeled that exact string with confidence ≥ 0.8 and the topic's name, or (b) its Wikidata ID is the topic's ID. Otherwise it is its own topic.
- **Enforcement:**
  - In the union-find, typo and semantic edges touching such a string need its own ID to equal the other group's ID, or its own ≥ 0.8 name to be among the other group's confident names. This blocked 1,132 typo and 6,568 semantic merges.
  - Same-name merges skip short strings labeled below 0.8.
  - At the end, every short string in a multi-string topic is re-checked against the topic's final name and ID; 7 were detached.
  - The same rule applies to cross-language links: 2,594 links were refused.
- **Name-lookup IDs on short strings:** a name-lookup ID is only a lookup of Claude's name, so on a short string it counts only if that label has confidence ≥ 0.8. 5,390 such IDs were dropped ("carlos", labeled "Carlos Alcaraz" at 0.5, no longer joins through the ID). Verified Claude IDs count as they are: "real" stays in Real Madrid because Wikidata lists "Real" as an alias of Q8682.
- **What stays:** short strings that Claude itself labeled at ≥ 0.8 stay ("mu", "man" → Manchester United; "pl", "premier" → Premier League; "liga" → La Liga), as the rule allows.

**Unique `topic_id` (bug found while applying the fix).** A group without an ID took its Claude name as `topic_id`, so two separate groups with the same name collapsed into one topic, bypassing every merge rule. Low-confidence labels were effectively merging topics this way, e.g. "cf" (0.4) ended up in La Liga. Now the biggest group keeps the plain ID and the others get `<id> [<their most common string>]`: 3,927 collisions resolved. Names may repeat; IDs don't.

**Recall rules (2026-11-11, `pipeline/recall.py`).** Four extra union-find layers run after the same-name layer and before typos/semantic, so each pair goes through the usual guards: QID cannot-link, the short-string gate, and the 50-string cap. Every pair must have trended within the 3-day window.

| rule | what it merges | name block | unions made |
|---|---|---|---|
| 4 `claude_near` | important strings, both Claude confidence ≥ 0.7, names near-identical after `norm()` (ratio ≥ 95), same numbers, same word count (or equal without spaces), every differing word close (ratio ≥ 75) | no | 832 |
| 3 `match_key` | `sports_match` strings (confidence ≥ 0.5) whose Claude names split on vs / v / x / – / contra / gegen / contre / mot into the same two teams, sorted; tokens fc, cf, afc, sc, ac, cd, fk, sk, club, cp, the are dropped from team names | no | 3,342 |
| 1 `word_set` | same set of words, ignoring order; simple plurals (-s, -es after ch/sh/x/z; not -ss, -us, -is, words < 5 letters); ё = е. Latin accents were already folded by `norm()` | yes | 14,920 |
| 2 `containment` | B = all words of A + only generic extras: today/live/results/time/news/standings/table/score and equivalents in es, pt, fr, de, it, tr, id, nl, pl, vi, ru, ar; month names; years 2023–2027; day numbers only next to a month word ("december 26", not "iphone 16"). A must not be short (single word / ≤ 4 chars) or a generic related term. Key groups > 60 strings are skipped as too generic | yes | 16,346 |

- **Order:** rules 3 and 4 compare Claude names, which differ by construction ("Real Madrid vs Barcelona" / "Barcelona vs Real Madrid"), so they don't use the confident-name block. Rules 1 and 2 do: 1,721 and 3,078 pairs were refused because confident names differ.
- **Net effect:** many of these pairs would otherwise have been joined later by typo or semantic edges; those layers made 3,264 and 14,342 fewer unions. Topics went from 798,353 to 780,533 after combine, and from 787,885 to 771,163 after linking.
- **Review:** 20 random merges per rule were reviewed; see `data/interim/work/recall_examples.md` (local). No false merges were seen. Known weak spot: generic Claude names such as "Earthquake" or "Winter storm" can join different countries' events within 3 days. That already happened for identical names; rule 4 adds near-identical ones ("Winter storm" / "Winter storms").
- **Score:** on the labeled sample (177 pairs, predictions recomputed from the current topics), recall rose from 0.712 to 0.728 and precision stayed at 0.958 (0.957 before). Most remaining misses are cross-language or paraphrase pairs ("4 czerwca" / "4 de junio", "automóvel" / "automóvil") that these rules don't target.
- **Fresh sample v3** (`03_topics.py validation-v3`, seed 23), drawn after the rules, with no string shared with the earlier samples. It has 120 Latin-script pairs (45 same topic, 15 linked, 40 hard negatives, 20 random same-window negatives) plus 20 Arabic/Cyrillic sports-match pairs (10 same, 10 hard negatives). `docs/validation_sample_v3.csv` and its key `docs/validation_key_v3.csv` are local and git-ignored. This is the honest final score: label it, then run `python pipeline/score_validation.py v3`.
- **Scoring changes:** `score_validation.py` now recomputes predictions from the current topics (by string id) and prints the frozen ones alongside; the pandas `groupby.apply` DeprecationWarning is fixed. The `validation` stage no longer overwrites a sample that has hand labels.

**Rule 5 `raw_match_key` (2026-11-11), for all strings, not only Claude-labeled ones.**
- **Key:** the raw search string is split on a match separator in any language: vs, v, x, mot, contra, contro, gegen, contre, versus, against, lwn, ضد, مقابل, против, срещу, проти, proti, protiv, εναντιον, đấu với, พบ, 対, 對, বনাম, बनाम, karşı, vastaan, kontra, naspram, and a dash with spaces around it, so "al-hilal" and "saint-etienne" are never split. Exactly one separator is required; "e"/"y" ("and") are not separators.
- **Team names:** normalized with `norm()`. Plurals are stemmed. Club tokens (fc, cf, ac, …) are dropped, and so are generic extras (today, live, prediction, lineups, where to watch, dates, years). Each team has 1–4 words and isn't only digits. The key is the two teams, sorted.
- **Merging:** strings with the same key merge if they trended within the 3-day window, behind all the usual guards. As an extra guard, a pair is skipped when both strings have confident Claude match names (≥ 0.8) that give different teams.
- **Result:** 122,184 strings have a key. 19,967 new merges, 530 refused by the size cap. It runs after the Claude match key, so typo (−8,164) and semantic (−3,197) merges went down. Topics went from 774,319 after combine to **765,159** after linking (was 771,190).
- **Moments:** global moments went from 8,303 to 8,014 (split match moments now join). Moments reaching 100+ countries within 60 min went from 63 to 73; all 10 new ones are sport, and non-sport stays at 5.
- **Review:** 20 random merges were reviewed (`data/interim/work/recall_examples.md`, local); all are the same match ("metz - paris" / "metz x paris fc", "newcastle đấu với ipswich town" / "newcastle - ipswich town"). Known ambiguity: dropping "fc" makes "Paris" and "Paris FC" one team name.

**"Como" questions vs the club Como (2026-11-11).** "Como" means "how" in Spanish and Portuguese. A string starting with como/cómo may stay in a topic about the football club Como only if one of these holds:
- Claude labeled that string itself as a Como team or match;
- it has a club token (1907, calcio, fc, women, coppa, cup);
- it has a match separator ("como vs inter", "como x lazio", "como lwn juventus");
- the word right after "como" is an opponent named in Claude's Como match labels ("como inter rigore").

Anything else is detached at the end of combine (`como_guard`), and such strings never link into a Como topic. In the current data this changes nothing (0 detached, 0 links refused): questions like "como va el inter" or "como quedo el madrid" are already their own topics. The guard keeps it that way.

**Generic event names (2026-11-11).** A string is a generic event if Claude typed it `event`, it has no QID, and its Claude name is only generic words (`GENERIC_EVENT_WORDS` in `combine.py`: earthquake, storm, winter, snow, rain, tsunami, warning, power, outage, blackout, flood, wildfire, fire, heat, election, results, today, live, …). Examples: "Earthquake", "Winter storm", "Tsunami warning", "Power outage", "Election results". Not generic: "Alaska earthquake", "US election results". A group containing such a string (and no QID) merges only with a group that shares at least one country (`generic_event_no_shared_country` in the merge stats). The same-name layer pairs these strings per country instead of in one star. Cross-language links follow the same rule.
- **Effect:** 250 strings qualify. The rule removed 27 merges in the same-name layer, and refused 34 near-name, 2 typo, 2 semantic and 2 link merges. Topics went from 771,163 to 771,190 after linking.
- **Limitation:** the effect is small because strings that themselves trend in many countries still bridge everything. The bare string "earthquake" trended in dozens of countries, so the "Earthquake" topic still has 40 strings across 82 countries. 289 more strings with generic names are typed `other` (mostly weather) and aren't covered, since the rule is for events.

**Manual overrides (`pipeline/overrides.csv`, columns `string, action, topic`).** Applied at the end of combine, after every merge layer and the short-string check. Strings are matched after `norm()`.
- `detach`: the string becomes its own topic, with no QID, named by its own most common raw form, and its topic never takes part in cross-language linking (as child or parent).
- `move`: the string joins the topic whose QID or Claude name (case-insensitive) equals `topic`.
- Unknown strings or targets are reported and skipped; a malformed row stops the run.
- First row: `real, detach`. "real" is a generic word in several languages. It had stayed in Real Madrid only because Wikidata lists "Real" as an alias of Q8682.

Applied overrides are logged in `work/combine_summary.json` (`overrides_applied`) and marked in `string_topics.parquet` (`override`).

### (g) Cross-language linking (`03_topics.py link`, `pipeline/link.py`)

Runs after combine. It attaches a small topic (child, national reach ≤ 3) to the bigger topic it is about (parent, reach ≥ 3 and larger than the child). This catches phrasings that other layers missed because Claude gave them a different English name. Example: German "papst tot" was labelled "Pope dead" and stayed a Germany-only topic.

- **Evidence** comes from Google's related searches, in **either direction**: a child string lists a parent string, or a parent string lists the child string. The two strings must have trended within 2 days of each other. "papst tot" is only found in reverse, because "papst franziskus" lists it.
- **Acceptance:**
  - the English names (Claude) have cosine ≥ 0.86 (multilingual-e5-small);
  - and either ≥ 2 pieces of evidence holding ≥ 50% of the child's evidence, or cosine ≥ 0.92 with one piece;
  - and the **parent trended in another country** (outside the child's) within ±2 days of a child trend day. Linking means "this was not only ours", not filing a local event under a generic class.
- **Guards**, each added after reading samples:
  - Type compatibility: never match ↔ club or person ↔ club; a fixture only joins a fixture.
  - Two people link only if one name contains the other. Before this, "Claire Chazal" → "Anne-Sophie Lapix" was accepted.
  - Weather only links to weather. Before this, "Houston weather" → Houston was accepted.
  - If both names contain numbers, the numbers must match (Channel 12 ≠ Channel 13).
  - A place only absorbs place-like strings ("maryland basketball" ≠ Maryland).
  - Two English names can't each have content words the other lacks (Pittsburgh ≠ Philadelphia weather, riyal ≠ dollar).
  - No junk parents ("8"), and a venue is not its namesake (Johan Cruijff Arena ≠ Johan Cruyff).
- **Manual overrides:** `docs/link_overrides.csv`. "Pope dead" → Pope Francis: its evidence split evenly between Francis and Leo XIV, but it trended in Feb and on 21 Apr 2025. Never-link: Liga 1 Peru standings, latina en vivo, Siemens Energy.
- **Result:** 12,567 links, 15,194 strings moved, 774,449 topics. The most impactful links are listed in `docs/link_review.csv`. A random sample of 30 accepted links had no clear errors; the weakest are single-name guesses ("kwan" → Steven Kwan).
- **Reversible:** the pre-link values are kept in `topic_id_combine` / `topic_name_combine`, and the stage always restarts from them.
- **Consequence:** "Tsunami warning California" is no longer US-only, because the same topic trended worldwide during the July 2025 Kamchatka tsunami. Known misses: German "Winter Olympics closing ceremony 2026" stays Germany-only.

### (f) Validation

- 200 pairs (seed 11): 100 random pairs inside multi-string topics, 50 hard negatives (embedding neighbours with cosine ≥ 0.93 placed in different topics), and 50 random different-topic pairs from the same 3-day window.
- The answer key is `docs/validation_key.csv`; open it only after labeling. Because hard negatives are over-sampled, recall from this sample is a hard-case estimate, not population recall.

### Final validation results (2026-11-11)

Scored with `pipeline/score_validation.py [v3]`, with predictions from the current topics. Two numbers are reported:
- **raw:** precision and recall on the labeled pairs as sampled. Hard negatives are over-sampled, so recall here is a hard-case figure.
- **population estimate:** each sampling group is weighted by how many pairs of that kind exist in the full set of pairs the pipeline could merge (string pairs within the 3-day window), counted from the current topics with the sampler's restrictions.

| sample | labeled pairs | raw precision | raw recall | **population precision** | **population recall** |
|---|---|---|---|---|---|
| v1 = `docs/validation_sample.csv` (drawn 2026-11-09, before the recall rules) | 177 | 0.958 | 0.736 | 0.960 | 0.555 |
| **v3 = `docs/validation_sample_v3.csv`** (drawn after the recall rules; fresh strings) | 140 | 0.960 | 0.758 | **0.970** | **0.642** |

**The final, honest score is the v3 population estimate: precision ≈ 0.97, recall ≈ 0.64.**
- **Before the raw match key:** v3 was precision 0.964, recall 0.539.
- **Where recall is lost:** in pairs that are close in meaning but sit in different topics ("hard negatives": about 490,000 such pairs, two-thirds of them really the same topic). Cross-language and paraphrase pairs ("ballon coupe du monde 2026" / "bola da copa 2026") and pairs that differ by a word ("domenica in sanremo 2025" / "elodie vestito sanremo 2025") stay apart.
- **Caveats:**
  - The stratum sizes come from today's topics, not the topics at draw time.
  - Same-topic pairs were drawn topic-first, not uniformly.
  - 20–41 random negatives cannot detect rare missed pairs among billions, so recall is an upper bound.
  - `docs/validation_sample_v1.csv` (drawn Nov 5) is unlabeled and not scored.

## Step 4: moments (`pipeline/04_moments.py`)

- **National feeds only.** Reach and spread use the 125 country feeds; region rows are not counted, so one country with many trending regions counts once.
- **Splitting (v2, burst detection).** v1 split a topic at 48 h gaps, which failed for topics that trend somewhere every day. "Weather" became one moment from Nov 2024 to Sep 2025, and the 11 Dec 2024 ChatGPT outage was buried inside a 10–14 Dec moment that started in Oman. v2 works in two passes:
  1. **Sessions:** per (topic, country), trends are one session until the country goes **24 h** without the topic trending. A country that trends a topic every day has one long session, which is its baseline.
  2. **Bursts:** per topic, session *starts* are sorted, and a new moment begins when the next start is more than **6 h** after the previous one. Countries already inside a running session are baseline: they don't join the burst or chain it forward.

  Result: 3.15M sessions, 2.05M moments, 139 moments ≥ 7 days, and 12 cases where one topic has two global moments within 24 h (e.g. La Liga matchdays, CNN). The 11 Dec 2024 replay now works: Facebook 17:50 UTC (67 countries), Instagram/Messenger 18:00, Google Gemini 18:50, ChatGPT 23:20 (116 countries within 60 min).
- **Trend end** = `end_time_utc`, else start + `duration_minutes` (capped at 24 h), else start.
- **Per moment:** `start_utc`, `end_utc`, `reach` (countries), `countries` (per country: first UTC start, minutes from the moment's start, max volume bucket, most common raw phrasing), `minutes_to_half` (minutes until ceil(reach/2) countries had started), `peak_volume` (max `search_volume_lower`), and topic `type`/`intent`/`qid` (the most common value among the topic's strings, weighted by rows).
- **Global moment:** at least **15** countries had started by **60 min after the third country's first trend**. Measuring from the third country, not the first, means one or two early outliers (a time-zone artefact or an earlier local story) don't disqualify a real global spike. `docs/GLOBAL_MOMENTS.md` lists the top 300, sorted by countries in that window, then total reach.

- **Sport is flagged separately (`is_sport`).** Claude types `sports_match` or `team`, plus league and competition topics matched by name (`LEAGUE_RE` in `04_moments.py`: Premier League, La Liga, Champions League, NBA, World Cup, Grand Prix, …; never people, companies, products or places). Athletes are not counted as sport.

  **Why sport is treated separately:** a scheduled match makes dozens of countries trend the same search within minutes, because kickoff is the same moment everywhere and Google lists fixtures in many feeds. That is synchronized by the fixture list, not a sign of a shared reaction. It also dominates the counts: 6,082 of 8,014 global moments are sport, and 68 of the 73 that reached 100+ countries within 60 minutes (after all 2026-11-11 rules; 6,513 of 8,441 and 58 of 63 before), and 58 of the 63 moments that reached 100+ countries within 60 minutes are matches or clubs (Real Madrid 6 times, FC Barcelona 4 times). The 5 non-sport ones are the two ChatGPT outages (23 Jan 2025, 11 Dec 2024) and the deaths of Diogo Jota, Hulk Hogan and Ozzy Osbourne. So any claim about "the world paying attention together" should be quoted without sport, or with sport shown separately. `docs/GLOBAL_MOMENTS_NO_SPORT.md` is the sport-free top 300 next to `docs/GLOBAL_MOMENTS.md`.

## Step 5: export (`pipeline/05_export.py`)

- National feeds only. Every file must be ≤ 2,000,000 bytes, or the script fails. Compact JSON (no spaces); `data/export/manifest.json` lists every file and its size.
- **Days** use each country's **local** date (`local_time`, one zone per country), because "what was Brazil searching on 3 Jan" means the Brazilian day. Topics are ranked within (day, country) by summed volume buckets, then number of trends, then earliest start. Each month file has its own topic table (`[topic_id, name, type]`) and references topics by position. If a month exceeds 2 MB it is split into equal date ranges (`YYYY-MM-1.json`, …).
- **moments_global.json:** every global moment with its full timeline `[country, minutes_from_start, phrasing]`. If it exceeds 2 MB it is split by start month, and the main file becomes a list of the parts.
- **topics_index.json:** topics with reach ≥ 2 countries or present in any daily top 10. Fields: id, name, type, qid, reach, trends, number of moments, local months (indices into `months`), countries. If it exceeds 2 MB it is sharded, most-trended topics first, so the first shard alone covers the popular searches.
- **wrapped/<CC>.json:**
  - *Uniquely local:* topics that trended in this country's national feed and **no other** (reach = 1), ranked by summed volume, then trend count; top 10. (v1 used "≥ 80% of the topic's volume", which gave the US the Super Bowl.) Weak cross-language merges show up here: Germany's "Pope dead" is a German phrasing that wasn't merged into Pope Francis.
  - *Busiest day:* the local date with the most trends, plus its top 5 topics.
  - *Attention twin:* the highest Jaccard similarity of topic sets (any trend in the national feed), with two runners-up.
  - *Weather hour:* the local hour with the most **weather** trend starts (needs ≥ 20 weather trends, else null), with its histogram. *Busiest hour:* the local hour with the most trend starts of any kind. *Night share:* the share of trends starting 00:00–04:59 local. Result: 85 countries have a weather hour of 6 a.m., 16 in the evening (about 8 p.m.), and 4 are null.
  - *Global moments:* the number of global moments the country joined, its share of all global moments, and how often it was among the first 3 countries.
  - *Top topic per month:* by summed volume in the local month.
- **Weather category** (`topic_meta.category`, set in step 4): Claude's types have no weather class, so a topic is `weather` if its name or most common string matches a multilingual list of weather words (`WEATHER_EN`, `WEATHER_LOCAL` in `04_moments.py`). Exclusions: Claude types person/team/match/media/company/product, and `NOT_WEATHER_RE`.
  - **Hand review (Nov 2026).** Every weather topic matched only by an ambiguous word (1,547 topics, 7% of weather trends) was read one by one. The other 5,101 contain an unambiguous weather word. The false-positive families became exclusion rules:
    - **Space and sky:** geomagnetic and solar storms, auroras, Snow Moon, meteor showers (*lluvia de estrellas*, *mưa sao băng*), solar terms (Grain Rain), "rains" of spiders and toads.
    - **People, teams and brands:** Frost (Emma, Scott, Maxwell, Sadie…), Snow (Snow Man, Dan Snow, snow leopard), Storm (Toni Storm, Melbourne Storm, Seattle Storm, Storm Shadow missile), Rain (Rain or Shine, the singer Rain), Tornado FC, Activision Blizzard, Diablo.
    - **Lookalike words:** Vietnamese *mùa* ("season", which normalizes to *mua* like *mưa* "rain"; it had pulled in every "Winter Olympics" event), Dutch *weer* "again", Swedish *väder* vs Dutch/English *vader*, Serbian *radno vreme* "opening hours", Finnish *sää* vs SAA the airline, Turkish *Yağmur* as a first name.
    - **Titles:** the telenovela *Tormenta de pasiones*, the film *Mưa đỏ*, the series *Aynı Yağmur Altında*, *Chuva Ácida*.
    - **Sport:** rain delays, and any "X vs Y" fixture.
    - **Non-weather forecasts:** gold, Bitcoin, currency, fuel, housing, pension and election forecasts (*Wahlprognose*), northern lights, air quality, smoke.
  - One-off corrections go in `docs/weather_overrides.csv` (topic_id, is_weather); it is empty for now. Result: **6,132 weather topics**.
  - **Evening weather hour (checked):** 16 countries peak at 8 p.m., and in every one the top search at that hour is **"weather tomorrow"**. These countries check the next day's forecast the night before: Saudi Arabia, Kuwait, Qatar, Iraq, Iran, Syria, Yemen, Libya, Taiwan, Czechia, Bulgaria, Azerbaijan, Uzbekistan, Cambodia, Mozambique and Cameroon. Most also have a smaller morning peak (32–57% of their weather trends fall between 4 and 9 a.m.).
- **hours/YYYY-MM.json** (map frames): for each UTC hour and country, the highest-volume trend *active* in that hour (start ≤ hour < end, at most 24 h; ties go to the latest start). Arrays are aligned with `countries`; -1 means no trend, which is how collection gaps appear.
- **similarity.json:** the 125 × 125 Jaccard matrix on topic sets, plus a second matrix that excludes football matches and clubs. Each includes an average-linkage cluster order for a reordered matrix chart.
- **routine.json:** trend starts by **local** hour × category (Claude type, with weather split out), per country and worldwide. An extra `nba` series matches NBA team and league names. Worldwide, weather peaks at 6 a.m., football at 8 p.m., and NBA in Europe at 6 a.m.
- **coverage.json:** trends per UTC day and country. A day is a gap if its total is < 25% of the median day. Gaps: 2025-09-02 to 09-28 (several runs), 2025-12-07 to 12-10, 2026-01-04 to 01-30, and 2024-11-27 (a partial first day caused by the UTC shift).
- **"Biggest day of shared attention."** Ranked by summed `reach_60` of global moments that aren't matches or clubs, 11 Dec 2024 is **#5 of 458**. Days 1–4 are still sport-driven through players (Roland Garros final 2025-06-08, Champions League final 2025-05-31). It is defensible as the biggest *non-sport* day, but not as the biggest day overall.

- **Wrapped data quality (fix of 2026-11-09).**
  - `low_data` = true when the median covered day has < 5 national trends (monthly averages over non-gap days, median over months; the same measure as CHECKS.md C4 "thin feeds"). 5 countries are flagged: EE (2.7), MK (4.4), LV (4.4), CU (4.6), MD (4.9). `median_trends_per_day` is in each card and `low_data` in `wrapped/index.json`.
  - For US, CA and RU, the time-of-day stats (`hour_histogram`, `busiest_hour`, `weather_hour`, `night_share`) come from the regional feeds, each region in its own time zone (`REGION_TZ`, now in `common.py`, shared with C3). Unlisted regions use the country zone. Results: US night share 3.8%, CA 5.1%, RU 8.9%, all busiest at 20:00; they match C3's region-zone numbers. `time_of_day_source` says which method a card uses.
  - **No `busiest_hour`** in Wrapped cards or `wrapped/index.json` (removed 2026-11-09): C4 shows it is mostly the 19:00 UTC collection bump (it changes in 87 of 125 countries without that hour). `night_share`, `weather_hour` and the hour histograms stay.
- **`is_sport`** is included in every moment of `moments_global.json` (and its monthly parts), so the site can filter sport. C11 checks that it is a boolean on every moment.

- **Sensitive topics (2026-11-11).**
  - **Decisions:** hand decisions are read from `pipeline/sensitive_decisions.csv` (`topic_id, decision, note`; git-ignored). It holds the 7 priority-1 topics, all `keep`.
  - **Default rule:** every other topic is hidden if its name or most common string matches `SENSITIVE_RE` (crime, death, sexual and accident keywords, now in `common.py`) and it trended in ≤ 2 countries. Otherwise it is kept. This hides 3,839 topics (3,843 by the rule, minus 4 kept by hand). All 7 decision topic ids exist in the current topics.
  - **What hidden means:** the topic never appears in topic lists on the site (daily top 10, hourly map frames, topics index, Wrapped cards), and the next topic takes its slot. It still counts in totals, coverage, routine and similarity stats.
  - **Wrapped cards only:** they also skip `event` topics whose name contains accident, crash, shooting, death, dies, died or dead, plus the topic "homosexuality" (511 topics), and take the next topic instead. These topics, including the kept priority-1 ones, can still appear in daily lists.
  - **Verified:** 0 hidden topics appear in any export file and 0 skipped topics appear on any card. The counts are in `work/visibility_summary.json`.

## Step 6: profile (`pipeline/06_profile.py`)

- Formerly `04_profile.py`, renamed to match the brief's numbering. It adds moment statistics, the 20 biggest global moments and export sizes. The biggest-topics table is now 20 rows.

## Step 7: checks (`pipeline/07_checks.py` → `docs/CHECKS.md`)

- **C2 known events:** 16 events with publicly reported UTC times (approximate; verify before quoting). Each is matched to the moment (reach ≥ 3) that starts closest to the true time and matches the event's names, within ±18 h. Taking the *biggest* moment instead picked topics that were already trending before the event (e.g. "Pope Leo XIV" from the morning, "Snapchat" at 02:00), so it was dropped.
- **C3 time zones:** regional feeds are re-timed with their own zones (hand map of US, CA, AU, BR, MX, RU and ID subdivisions → IANA zones, `REGION_TZ`) and compared with the single country zone.
- **C4 artifacts:** the **19:00 UTC excess**. Many national feeds have more trend starts in the 19:00 UTC hour than in their neighbours, steadily every month. 19:00 UTC is 21:00 Berlin, the collector's clock, so this is treated as a collection artifact. The check replaces that hour with the mean of 18:00 and 20:00 and reports what changes. Other parts: feed size over time, and thin feeds (median < 5 trends/day).
- **C6 sensitivity:** single-country share under 5 definitions; global-moment counts on a grid of 10–25 countries × 30–120 min; the rank of 11 Dec 2024 under 4 rules × 3 metrics; weather hour under 3 definitions; night-owl ranking under 3 definitions of night.
- **C7 gaps:** countries missing > 10% of the days on which ≥ 80% of countries report; attention twins recomputed using only days on which ≥ 95% of countries report.
- **C9 blocs:** Jaccard vs overlap coefficient vs TF-IDF cosine (topics shared by ≥ 2 countries); 15 clusters with average linkage; adjusted Rand index; 20 topic bootstraps; a version without football.
- **C11 exports:** strict JSON (no NaN), < 2 MB, every topic/country reference resolves, array shapes match.
- **Hand-review lists:** `review_sensitive.csv` matches crime/death/sexual keywords, plus person topics with reach ≤ 2 and ≤ 3 trends, among the topics shown on the site, in 3 priority tiers. `review_types.csv` holds 10 topics per Claude type, sampled with weight √trends.
- **Validation sample** (regenerated): 75 random same-topic pairs, 25 pairs created by the link stage, 50 hard and 50 random negatives.

- **19:00 UTC collection bump (fix of 2026-11-09).** `topics.parquet` has a flag `utc19_bump` for trends starting 19:00–19:59 UTC: 287,362 national trends (8.3%, against 4.2% if evenly spread). Nothing is dropped or changed. C4 reports the busiest hour with and without them: worldwide 19:00 UTC (8.3%) → 18:00 UTC (7.6%) without; in local time 20:00 → 19:00. 87 of 125 countries change their busiest local hour, so a Wrapped "busiest hour" is mostly a collection artifact. Night shares barely move.
- **Validation sample:** topics changed, so `docs/validation_sample.csv` was regenerated. The previous one is kept as `docs/validation_sample_v1.csv`, with its answer key in `docs/validation_key_v1.csv`, which is git-ignored like `docs/validation_key.csv`.

## Step 8: story export (`pipeline/08_story_export.py`, `make story`)

- One JSON per chapter in `data/export/story/` (`opening`, `local`, `shocks`, `appointments`, `waves`, `rituals`, `timemachine/` by month, `wrapped/`), each < 1 MB. `docs/STORY_NUMBERS.md` lists every quoted number with its file and key, and is regenerated on each run.
- **Sensitive topics:** follows step 5's visibility rules. Hidden topics never appear (checked: 0 of 45,639 referenced topic ids are hidden). Wrapped cards keep step 5's choices, which also skip accident, crash, shooting and death events. `local.json` examples also leave out people.
- **Kinds** (shock / appointment / wave / ritual / local) use the STORY_CANDIDATES.md rules. A topic whose biggest moment reached < 15 countries is "local" unless it is a ritual.
- **Shock kind** (death / outage / other): a keyword rule on the topic name, the moment's phrasings, the topic's searches in its first 48 h, and Google's related searches. 98 deaths, 30 outages, the rest other. Some deaths stay "other".
- **Shocks left out:** the unnamed topics "i", "c" and "t" (23–24 Jun 2025, up to 54 countries) and "working" (Cloudflare day).
- **Weather by hour:** US, CA and RU use regional feeds in each region's own zone; the others use one zone per country. Each curve is also given without the 19:00 UTC bump.
- **Opening:** the Pope Francis timeline starts at the first scrape after the announcement (07:50 UTC), where 20 countries already tie.

## Open issues (need a decision)

_Updated 2026-11-09, after the short-string, sport, 19:00 UTC and Wrapped fixes (rerun from combine: combine, link, validation, moments, export, profile, checks)._

**Resolved**
- The Claude full run is done: 155,277 of 155,279 important strings labeled (2 failed twice and stay unlabeled). Total API spend is $3.17 (cap $5).
- Wikidata is populated and final: 31,543 strings have an ID used for merging (36,933 found, minus 5,390 name-lookup IDs dropped from short low-confidence strings), and 26,014 topics have an ID. 6,476 names (7,926 strings) failed from rate limiting and are final "no ID"; there are no further lookups.
- Generic short strings no longer pull unrelated searches into big topics, and `topic_id` is unique per group (see "(e) Combine").
- Topics: 895,618 strings → 774,319 after combine → **765,159** after linking (771,190 before the raw match key; 787,885 before the recall rules).
- **Validation (final):** v3 population estimate precision 0.970, recall 0.642 (see "Final validation results").

**Still open**
1. **Hand review (yours).**
   - `docs/validation_sample.csv`: 200 pairs, regenerated for the new topics; the old one is `docs/validation_sample_v1.csv`. Fill `same_topic_label`, then run `make score`.
   - `docs/review_sensitive.csv`: topics to keep or hide.
   - `docs/review_types.csv`.
   - Spot checks: `docs/link_review.csv`, `docs/GLOBAL_MOMENTS.md`, `docs/GLOBAL_MOMENTS_NO_SPORT.md`.
2. **Known false merges.** Re-check groups such as "atletico madrid", "barcelos"/"barcelona" and Ramadan/Bayram in PROFILE.md ("10 merges that look questionable") and through the validation sample. Measured precision is ≈ 0.97 (v3 population estimate).
3. **Data-check warnings** (`docs/CHECKS.md`; 4 PASS, 4 WARN, 0 FAIL):
   - C2: 15/16 known events found; "Charlie Kirk shot" falls in the September 2025 collection gap.
   - C3: 4 of 7 multi-zone countries are distorted by one zone per country. Wrapped now uses regional zones for US, CA and RU; BR (also WARN) still uses one zone.
   - C4: the 19:00 UTC collection bump (busiest hour changes in 87 of 125 countries without it), plus unstable and thin feeds (5 Wrapped cards are `low_data`).
   - C6: the single-country share depends on its definition.
   - C8 is now PASS, but only just: 61% agreement against a 60% threshold.
4. **Sport dominates global moments** (6,082 of 8,014; 68 of 73 reaching 100+ countries in an hour). How the site presents this is undecided; the data now has `is_sport` and a sport-free list.
5. **How the site gets its data** is undecided. `data/export/` is git-ignored for now. The export now carries `is_sport` on global moments and `low_data` / `time_of_day_source` on Wrapped cards; `busiest_hour` is gone.
6. **Git:** nothing is committed yet. `docs/validation_key*.csv` is git-ignored and must never be published.
7. **Scope:** steps 3g (linking) and 4–7 go beyond the original brief. No new steps or features are added without your approval.
