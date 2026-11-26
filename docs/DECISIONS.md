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

- **Sport is flagged separately (`is_sport`).** Since 2026-11-16, global moments also use the moment-level rule (Step 9, round 2); the topic rule below is kept as `is_sport_topic`. Claude types `sports_match` or `team`, plus league and competition topics matched by name (`LEAGUE_RE` in `04_moments.py`: Premier League, La Liga, Champions League, NBA, World Cup, Grand Prix, …; never people, companies, products or places). Athletes are not counted as sport.

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
- **Weather days** are counted only on full-coverage days: 486 of the archive's 537 days, gap days excluded.
  - (a) the topic "Weather", meaning the 22 topics Claude named exactly "Weather", one per language group: 409 days in 10+ countries;
  - (a') the single English "weather" topic: 294 days;
  - (b) any of the 6,212 weather-category topics: all 486 days.
- **Rituals by topic:** Ramadan, Eid, Easter and "is it down" have two counts.
  - The strict count includes only searches phrased "when is …" or "is … down".
  - The whole-topic count includes every trend of topics whose Claude name matches. "Is it down" means outage-named topics, excluding power outages and blackouts. The article uses the whole-topic count.
  - The two differ a lot: Ramadan peaks at 75 countries whole-topic vs 10 strict.
- **Shocks tagged "other"** get a sub-kind: disaster or accident, politics or conflict, viral or celebrity, launch, or other. It's a keyword rule on Claude's type, the name, the searches and the related searches (`sub_kind_rule` in `shocks.json`). The 40 biggest are listed in `shocks.json` → `other_top40` and in STORY_NUMBERS.md.

## Step 9: shock validation (`pipeline/09_validate_shocks.py`, `make shocks-*`)

Started 2026-11-13. It checks whether the "shock" kind really captures unscheduled events before the definition is final. **`shocks.json` and `STORY_NUMBERS.md` are not changed until the scores have been reviewed.** They were built with the old 20-country rule.

- **Threshold.** The 535 sport-free shocks in `shocks.json` came from a topic-level shock rule requiring the topic's biggest moment to reach **20** countries, on top of the moment being global (15+ countries within 60 min of the third). The rule now lives in `pipeline/kinds.py`, shared by steps 8 and 9, with `SHOCK_MIN_REACH = 15` for consistency with the global-moment rule.
  - **Counts** (sport-free global moments of shock topics, named topics only): min reach 20 → **535**, the same 535 as `shocks.json`; **15 → 698**; 10 → 698.
  - **Why 10 equals 15:** a global moment already has 15+ countries, so every candidate's topic has a biggest moment of 15+, and any threshold ≤ 15 gives the same set. 20 is the meaningful robustness variant. `make story` has not been rerun, so the exported files still hold the 20-country version.
- **Candidates:** every non-sport global moment (`is_global`, `is_sport` false, topic not hidden), 1,932 moments. It's not only current shocks, so recall can be measured.
- **Claude labels:** `claude-haiku-5-5`, Message Batches API, 40 moments per request, thinking off, output constrained by a JSON schema, malformed answers retried once, everything cached (`cache/claude/shocks/`, prompt version `shock-v1`), with the same key handling and spend cap as step 3.
  - **Input per moment:** topic name, UTC date and start, up to 8 phrasings from the moment, the topic's top 10 Google related searches (weighted by rows), countries reached, countries within 60 min, minutes to half, and the Wikidata item if the topic has a QID.
  - **Output:** `scheduled` (scheduled / unscheduled / unsure), `what_happened` (one sentence), `event_type` (death, outage, disaster, politics_conflict, launch, viral_celebrity, other) and `confidence`.
  - **Instructions:** rely only on the evidence, don't add facts not in the evidence, assume events may be after the training data, answer "unsure" rather than guess, and call something a death only when phrasings or related searches point to one.
- **Labeling run (2026-11-13):** one batch of 49 requests. All 1,932 answers passed the schema, none needed a retry. Tokens in 460,342, out 144,874, cost **$0.059**; all Claude runs total $3.23 (cap $5).
  - **scheduled:** unsure 1,124, scheduled 441, unscheduled 367. The large "unsure" share is expected from the instructions not to guess. Many non-sport global moments are athletes or sport-adjacent sites ("Livescore", "Yalla Shoot") whose trigger isn't visible.
  - **event_type:** other 1,232, viral_celebrity 265, death 118, launch 110, outage 109, politics_conflict 70, disaster 28.
  - **Caveat:** related searches are Google's list for the whole topic, gathered over all its trends, not for that one moment. A topic's later or earlier news can therefore color Claude's label for a given date. For example, a 15 Aug 2025 moment was labeled an outage because the topic's related searches mention the April 2025 Spain blackout. The phrasings are per moment.
- **Blind sample** (`make shocks-sample`, seed 13): 100 named candidates, 50 current shocks and 50 other non-sport global moments, shuffled.
  - `docs/shock_validation_sample.csv` shows only the name, date and time, phrasings and related searches, with blank `scheduled_label` and `event_type_label`.
  - `docs/shock_validation_key.csv` holds the stratum, the timing-rule flags (current file, 10 / 15 / 20) and Claude's labels. Both are git-ignored (REVIEW_FILES.md). The sample step refuses to overwrite a labeled sample.
  - **Population of each stratum** (named candidates): 535 current shocks, 1,387 others (`work/shock_sample_strata.json`). The strata split the whole candidate set, so weighted estimates are valid for any rule, including the 15-country rule, whose 163 extra shocks all fall in the "others" stratum.
- **Labeling helpers** (`09_validate_shocks.py helpers`, 2026-11-13). Six columns are appended to the sample, with no Claude output and nothing from the key except ids:
  - `google_link` and `news_link`: Google and Google News searches for the topic name, limited to the moment's date ± 1 day (`tbs=cdr:1,cd_min,cd_max`);
  - `wiki_link`: Wikidata's `Special:GoToLinkedPage/enwiki/<QID>`, which opens the English Wikipedia page of the topic's item, or the Wikidata item if there is none; 70 of 100 rows have one;
  - `moment_phrasings`: the top phrasings within that moment, with the number of countries using each;
  - `first_countries`: the first 5 countries with minutes from the start;
  - `local_start_hint`: the UTC start and the local time in the first country.

  Row order, ids and the empty label columns were verified unchanged, and the key file is untouched. The stage refuses to run once labels exist.
- **"sport" hand label and the is_sport leak (2026-11-13).** `event_type_label` may also be `sport`, for rows that are really sport (athletes, competitions, clubs, sport sites) and leaked into the non-sport candidates. Claude was not offered this label.
  - **Leak rate:** the scorer reports how many sampled moments are labeled sport, overall, within current shocks and within the rest, plus a weighted estimate for all candidates.
  - **Scores twice:** every shock score is computed on all labeled rows and again without the sport rows.
  - **Event-type confusion:** hand `sport` appears as a row, to show where Claude put the leaked moments.
- **Proposed is_sport fix** (`pipeline/sport.py`, `09_validate_shocks.py sport-check`; *not yet used by step 4*). The current rule only knows Claude's sports_match/team types and league names, so athletes (typed person), sport sites and tournaments leak. A topic becomes sport if any of these holds:
  - its Wikidata description names a sport role or body (tennis player, footballer, cricketer, racing driver, club, tournament, …);
  - its name is a sport site or channel (Yalla Shoot, Livescore, Flashscore, ESPN, Marca, DAZN, …);
  - its name ends like a competition ("Cincinnati Open", "Asia Cup", "Pichichi Trophy");
  - at least 3 of its top 10 Google related searches (2 for people) are fixtures ("x vs y", any language) or sport terms. Places never qualify this way, because a country's related searches are full of its team's fixtures ("Andorra").

  **Draft result: 1,006 of the 1,932 candidates (52.1%) move to sport:** 840 by Wikidata, 76 by related searches, 70 as sites, 20 by competition name (387 topics). That includes 169 of the 535 current shocks and 247 of the 703 shocks under the 15-country rule.
  - **Known misses:** footballers without a Wikidata match (e.g. Gonzalo García, Mingueza).
  - **Status:** the rule was drafted before any hand labels existed. It will be tuned on the hand `sport` rows: the scorer reports how many of them the fix catches and which non-sport rows it would wrongly move. It moves into `04_moments.add_sport` only after the scores are reviewed, since that changes moments, candidates and `shocks.json`.
- **Moment-level sport rule (2026-11-13, replaces the entity-only draft above; still not used by step 4).** Sport must describe the *moment*, not the person: an athlete's death, collapse, injury, arrest or scandal is not sport and can be a shock (Diogo Jota, Hulk Hogan, Edoardo Bove). A candidate moment is sport only if all three hold:
  1. its topic has an entity signal (Wikidata sport role, sport site or tournament name; the 1,006 above);
  2. **the moment itself looks like a sporting event**, judged from the topic's national trend rows inside the moment (`start_utc`..`end_utc`): their raw searches and their *own* Google related searches (the per-row `related` column, not the topic-wide list), plus the moment's phrasings. Any of:
     - a fixture ("x vs y" in any language, the step-3 match key);
     - an event word (score, result, live, stream, highlights, lineup, final, round, transfer, debut, …);
     - the topic is a competition or sport site;
     - a **known competition date**: a fixture moment ("a vs b") within a day whose name contains the athlete's surname or a team named in this moment's own searches ("bayern" on the day of Real Madrid vs Bayern);
  3. **no moment-level override**: death, accident, health (collapse, hospital, injury, illness), crime (arrest, police, court case, doping, ban) or outage words in those same searches (`OVERRIDE_RE`: "murió", "died", "cause of death", "accident", "malore", "injury", "arrested", "doping", …).
  - **Result:** of the 1,006 entity-flagged moments, **457 move back to non-sport**: 41 by override, 416 for lack of sporting-event evidence. **549 of 1,932 (28.4%) are sport**: 220 by fixture, 183 by event word, 115 by competition date, 31 as competition or site topics. That includes 73 of the 535 current shocks and 94 of the 703 under the 15-country rule.
  - **The 30 widest athlete moments that are now non-sport** are in `data/interim/work/sport_check_athletes_non_sport.md` (local), for review.
  - **Things to check:**
    - injuries suffered *during* a match count as non-sport by this rule (Musiala at the Club World Cup, Djokovic and Sinner at Wimbledon);
    - Sinner on 26 Jan 2025 (the Australian Open final) is blocked by "doping" in its related searches;
    - some match days are still missed (Yamal 9 Apr 2025, Mbappé 15 Apr 2026, Kalmurza with a Cyrillic team name);
    - true non-sport news stays non-sport (Horner fired, De Bruyne and Alexander-Arnold departures).
- **Moment-level sport rule v2 (2026-11-13, your decisions; still not used by step 4).** It replaces the override handling of v1 above.
  1. **A surprise during a scheduled sporting event is sport.** Overrides are split in two:
     - **Always** apply, even on a match day: death; health emergencies (collapse, cardiac, hospital, coma; treated like death because Bove's on-pitch collapse was named non-sport); accidents outside play (car, plane or road words); crime (arrest, police, charged, sentenced); outage.
     - **In-play** words are *lifted* when the moment has fixture or competition evidence: injury, doping, suspension or ban, an accident or crash without a vehicle word (Vonn at the Olympics), and "retired"/"retirement" (a tennis player retiring hurt mid-match). With no such evidence they still make the moment non-sport.
  2. **Support:** an override word counts only if it is in the moment's own phrasings or in at least 2 of its related searches. One stray related search isn't enough. This fixes Sinner on 26 Jan 2025, the AO final, where "doping" appeared only in one related search.
  3. **Announcements are an always-override:** fired, sacked, leaving, departure, transfer, signing, contract, appointed, "where is X going", next or new club, joins, presentation. So Horner, Salah, Ten Hag, Eze, Mbeumo and Dončić's trade are non-sport. "transfer", "signs", "fichaje" and "contrato" no longer count as sporting-event words. De Bruyne and Alexander-Arnold (announcement days whose searches show only names) are non-sport because no fixture falls in their window.
  4. **Date check:**
     - **Clubs:** each athlete's clubs and national teams come from Wikidata P54 ("member of sports team"), fetched for 327 athletes and cached in `cache/wikidata/claims_p54/`. Team names come from the cached entity labels in all languages.
     - **Transliteration:** moment words are also transliterated (unidecode), so Cyrillic and Arabic team names match ("кайрата" → Kairat Almaty vs Real Madrid).
     - **Competition names** in the moment's searches count as competition evidence, now also in Spanish, Portuguese, French, Italian, German, Arabic, Russian and Turkish (copa, كأس, кубок, …).
     - **Window:** a competition only counts if it started between 12 h before and 3 h after the athlete's moment, not ± 1 day. Women's fixtures count only for athletes with a women's team.
     - **Co-trending athletes:** at least 2 *other* athletes (different Wikidata IDs, not the athlete's own name in other scripts) in the moment's searches during a competition window count as a match day (Nico Williams with Merino, Oyarzabal and Dembélé on Spain vs France day).
     - **Generic club words** (sport, club, racing, sociedad, …) are not team names. They had matched De Bruyne to "Sport Club Internacional".
  - **Wikidata reads:** the P54 and entity reads now use `maxlag=30`, because Wikidata's replica lag was ~17 s and `maxlag=5` refused every request. Search requests keep `maxlag=5`.
  - **Checked cases:**
    - sport: Yamal 9 Apr 2025 (Dortmund vs Barcelona), Mbappé 15 Apr 2026, Kalmurza, Sinner 26 Jan 2025, Musiala, Djokovic and Sinner at Wimbledon, Vonn, Nico Williams and Unai Simón 5 Jun 2025;
    - non-sport: Bove, Hogan, Horner, De Bruyne, Alexander-Arnold.
    - The evidence text names the first competition found in the window, which can be another fixture than the athlete's own (e.g. "Portugal vs Spain" for Unai Simón). The decision is what is scored.
  - **Result:** **827 of the 1,932 candidates (42.8%) are sport.** Of the 1,006 entity-flagged moments, 179 stay non-sport: 30 by override, 149 with no sporting-event evidence.
    - Evidence for the 827: fixture 237, competition in searches 227, club via P54 225, competition or site topic 57, team named in searches 44, co-trending athletes 27, event word 8, surname 2.
    - Among shocks: **120 of the 535 current shocks** and **171 of the 703 under the 15-country rule** are sport.
  - **The 30 widest athletes still non-sport** are in `data/interim/work/sport_check_athletes_non_sport.md`. Mostly deaths and accidents (Hogan, Bove, Clarke, Foreman, Costa, Antonio, Joshua, Woods) and announcements (Horner, Salah, Haaland's contract, Eze). Also some tennis days without a visible fixture (Sinner 1 Jul and 9 Aug 2025, Djokovic 8 Mar 2025, Sabalenka 23 Apr 2026).
- **Individual-sport calendar (2026-11-13; still not used by step 4).** `pipeline/sport_calendar.py` holds a small static calendar, Dec 2024 – May 2026.
  - **Tennis:** Grand Slams, ATP and WTA 1000s, ATP and WTA Finals, the United Cup and the Davis Cup Finals.
  - **F1:** race weekends.
  - **Golf:** men's majors.

  An athlete moment (Claude type person) whose Wikidata description makes them a tennis player, racing driver or golfer, and that starts inside a window of that sport (UTC date, with one day of slack after the window for late finals in the Americas), counts as a competition day: `calendar: <event>`. Like any competition evidence, this lifts in-play override words, but never an always-override. Where windows overlap (Canada and Cincinnati), the label names the most recently started event.
  - **Tennis sources:** English Wikipedia, read 2026-11-13: the schedule week columns of "2025 ATP Tour", "2026 ATP Tour", "2025 WTA Tour" and "2026 WTA Tour", plus "2025 ATP Finals" for exact dates (9–16 Nov 2025). The season pages give the Monday of each tournament week, so a window runs from that Monday minus 1 day (most events start on a Sunday) to the last week's Monday plus 6 days. The United Cup starts 3 days before its first Monday.
  - **F1 sources:** "2024", "2025" and "2026 Formula One World Championship" race dates; a weekend is Friday to the race Sunday. The page notes that the 2026 Saudi Arabian GP was cancelled and the Bahrain GP moved to October 2026, so neither falls in the range.
  - **Golf sources:** "2025 PGA Tour" and "2026 PGA Tour" final-round dates of the majors (Masters, PGA Championship, U.S. Open, The Open); a major runs Thursday to Sunday.
  - **Rechecked, now sport:** Sinner 1 Jul 2025 (Wimbledon), Sinner 9 Aug 2025 (Cincinnati), Djokovic 8 Mar 2025 (Indian Wells), Sabalenka 23 Apr 2026 (Madrid). Also Leclerc 20 Apr 2025 (Saudi Arabian GP weekend).
  - **New counts:** **sport 874 of 1,932 (45.2%)**; 132 of the 1,006 entity-flagged moments stay non-sport (30 by override, 102 with no evidence). Calendar evidence decides 241 moments. Sport among the 535 current shocks: **121**; among the 703 under the 15-country rule: **173**.
- **"markets" hand label (2026-11-13).** `event_type_label` may also be `markets` (stocks, indices, crypto, gold, currencies). Like `sport`, Claude was not offered it. It gets its own row in the event-type confusion table, and the scorer counts sampled markets moments overall, among current shocks, among shocks under the 15-country rule, and among the other moments. Markets rows are not removed from the shock scores; only `sport` rows have a with/without variant.
- **Scoring** (`make shocks-score` → `docs/SHOCK_VALIDATION.md`):
  - Claude vs hand labels on scheduled: accuracy and Cohen's kappa, with and without "unsure".
  - Precision and recall for "unscheduled" (hand label = truth, hand "unsure" left out) for the current file, the timing rule at 10 / 15 / 20, each timing rule AND Claude "unscheduled", and Claude alone. Raw, and weighted by stratum population (current shocks vs the rest).
  - Event-type confusion and agreement.

### Step 9, round 2 (2026-11-16): your corrected labels, tuning on sample 1, rules wired into step 4

Sample 1 (`docs/shock_validation_sample.csv`, 100 moments) is now the **tuning** sample. Sample 2 (below) is kept untouched for testing. You corrected five labels: Heidi Klum, Bove, Rio Ferdinand, Dan Ashworth and Christian Horner. After the corrections, 56 of the 100 rows are sport and 44 are not; 28 are unscheduled and 72 scheduled, with no "unsure".

**1. Sport rule, retuned on the 56 hand sport rows** (`pipeline/sport.py`, `pipeline/sport_calendar.py`)
- **Health stays an always-override,** even during a match: collapse, cardiac arrest, hospital, coma, illness. Bove (1 Dec 2024, "malore") is non-sport and unscheduled. In-match injuries are in-play words, lifted on competition days, so they stay sport: Musiala 5 Jul 2025 (fixture PSG vs Bayern), and Djokovic 24 Jan 2025 and Sinner (Australian Open 2025 and Wimbledon) by fixture or calendar.
- **Before tuning,** the rule caught 36 of 56 and wrongly moved 1 of 44 (Postecoglou). The 20 misses fell into five groups, and the changes are:
  - **Related searches name other athletes or clubs.** Many footballers had no Wikidata item or a wrong one: Isco matched "international standard for job names", Gonzalo García a PhD, Jack Fletcher an army officer. A related search now counts as sport if any 1–4-word part of it is a search whose Wikidata item has a sport description (athlete, club, competition), not counting the topic's own item or its own name tokens. These entities also give the topic an identity, like P54: (a) the sport for the calendar, taken from the co-trending athletes when the topic has no description (Medvedev), and (b) its club for the fixture-date check, from clubs named directly or clubs shared by at least 2 of the co-trending athletes (Wikidata P54).
  - **Non-athletes are guarded.** If the topic's own Wikidata description names a non-sport role (actress, singer, model, presenter, politician, journalist, …), related entities are ignored. Margarida Corceiro, an actress whose related searches are F1 drivers, had become sport on the Monaco GP weekend.
  - **Winter Olympics.** `sport_calendar.py` now has the 2026 Winter Olympics: competitions 4–22 Feb 2026, from English Wikipedia's "2026 Winter Olympics", read 2026-11-16 (Games 6–22 Feb, first events 4 Feb). It applies to figure skaters, ice dancers, skiers, ski jumpers, snowboarders, biathletes, lugers, bobsledders, curlers and ice hockey players. Those roles were added to the sport descriptions, and Olympic words to the competition terms: "олимпиада", "jo 2026", "jeux olympiques", "giochi olimpici", "milano cortina". This fixes Cizeron and Gumennik.
  - **Places with clubs.** A place (never sport by related searches before) is a candidate "club place" when at least 3 of its related searches are sport. Its moment is sport only with a fixture of a club named after the place: in its own searches, or a club fixture within −12 h…+3 h. This fixes Paris (15 Apr 2025, PSG vs Aston Villa) and Monaco (18 Sep 2025, Champions League).
  - **Cup names.** Topic names starting with coppa, copa, coupe, taça, pokal, supercopa or supercup are competition names. This fixes Coppa Italia.
  - **Generic name tokens** (south, north, east, west, central, saint, port, new, royal, santa, são, …) are no longer club keys. Postecoglou had matched "South Africa vs Tanzania" through South Melbourne.
- **After tuning: 48 of 56 hand sport rows caught; 1 of 44 non-sport rows wrongly moved.** Remaining misses:
  - **Transfer days with no match** (Mbeumo 21 Jul 2025, Leoni 13 Aug 2025): your rule says announcements are non-sport, and no fixture falls in the window. Labelling them sport contradicts that rule; if transfers should be sport, the announcement override has to change.
  - **National-team match days without a link to the team** (Álex Baena 8 Jun 2025, Pedro Porro 5 Jun 2025, Alexsandro 5 Jun 2025): no Wikidata item, or P54 without the national team, and too few co-trending athletes. Porro's related searches name only "europa league" and one teammate.
  - **Club known only through teammates** (Fabio Silva 19 Jan 2025, Jack Fletcher 26 Dec 2025): no shared club was found. One batch of P54 lookups is still missing because Wikidata's query-service lag (~42 s) is above our `maxlag=30`. It will be retried on the next run and may fix these two.
  - **Pablo Torre** (16 Aug 2025): the related searches name a coach and one player, with no shared club.
  - **Wrongly moved: Dan Ashworth** (8 Dec 2024). Manchester United's sporting director, dismissed on a United match day. His searches have no dismissal word, so the club match counts.
- **All candidates:** sport 1,050 of 1,932 (54.3%). Of the 1,198 entity-flagged moments, 148 stay non-sport: 34 by override, 114 with no evidence. Evidence for the 1,050:

  | Evidence | Moments |
  |---|---:|
  | Club date (P54 or related clubs) | 314 |
  | Calendar | 269 |
  | Fixture | 268 |
  | Competition in searches | 72 |
  | Competition or site topic | 61 |
  | Team in searches | 38 |
  | Club named after the place | 10 |
  | Co-trending athletes | 7 |
  | Event word | 6 |
  | Surname | 5 |

**2. Claude labels v2** (`09_validate_shocks.py label2`, prompt `shock-v2`, `make shocks-label2`)
- **What changed from v1.** Each moment gets only its own evidence: the phrasings and Google related searches of the topic's national rows inside the moment (start .. end, at least 1 h), ranked by how many rows have them; top 10 phrasings, top 15 related. Claude must choose scheduled or unscheduled ("unsure" was removed) and give a confidence 0–1. Event type and the one-line summary are kept. Same schema validation, retry and cache (`cache/claude/shocks/labels.jsonl`, by prompt version).
- **Model: Haiku 5.5, not Sonnet 5.5.** Sonnet 5.5 batch pricing is $1 / $5 per MTok (Anthropic pricing page, read 2026-11-16), 20× Haiku. The estimate for this run was ~$1.25, over your $1 cap.
- **Run:** 1,932 of 1,932 valid on the first try; 450k input and 142k output tokens; **$0.058**. Total Claude spend across all runs: **$3.29** (limit $10, alert at $5). Claude says unscheduled for 1,060 and scheduled for 872; median confidence 0.70.
- **Agreement with your labels** (sample 1, non-sport rows, n = 44): **accuracy 0.750, kappa 0.404**. v1, counting only rows where neither said "unsure", was 0.870 / 0.721 on 23 rows; v2 must answer on all 44. Claude's mistakes lean toward "unscheduled": 9 of your 16 scheduled rows. Accuracy by confidence: 0.60 at ≤ 0.6 (n = 20), 1.00 at > 0.8 (n = 16).

**3. Shock-rule variants** (sample 1, non-sport rows; 28 of 44 unscheduled by hand)

| Rule | Flagged | Precision | Recall | Weighted P | Weighted R |
|---|---:|---:|---:|---:|---:|
| a) Claude unscheduled, conf ≥ 0.5 | 30 | 0.80 | 0.86 | 0.77 | 0.86 |
| a) conf ≥ 0.6 | 20 | 0.85 | 0.61 | 0.80 | 0.51 |
| a) conf ≥ 0.7 | 15 | 0.93 | 0.50 | 0.96 | 0.38 |
| b) a AND half of countries within 6 h or 12 h | same as a) at every confidence | | | | |
| c) timing rule 15 AND Claude unscheduled, conf ≥ 0.5 | 22 | 0.82 | 0.64 | 0.82 | 0.28 |
| c) conf ≥ 0.6 / ≥ 0.7 | 16 / 13 | 0.88 / 0.92 | 0.50 / 0.43 | | 0.22 / 0.19 |
| Timing rule 15 alone | 32 | 0.66 | 0.75 | 0.57 | 0.33 |

- **The looser speed test changes nothing.** Every global moment already has 15+ countries within an hour of the third, so only 22 of the 882 non-sport global moments take more than 6 h to reach half their countries, and 1 takes more than 12 h. On all 882 moments, b) at 6 h removes 15 of a)'s 627, and at 12 h it removes 1.
- **Chosen rule: a) at conf ≥ 0.5,** i.e. any moment Claude calls unscheduled. The timing rule is the weak link: its weighted recall is 0.33, so it misses two thirds of the real shocks, and adding it (c) keeps precision about the same (0.82 vs 0.80) while cutting weighted recall from 0.86 to 0.28. Raising the confidence bar buys precision (0.93 at 0.7) at a large recall cost (0.50 raw, 0.38 weighted). With 44 rows, the gap between 0.80 and 0.85 precision is one moment. About 1 in 5 shocks will be a scheduled event Claude misread: mostly releases and broadcasts, the 9 false "unscheduled". For a chapter about surprises that is a visible cost, so sample 2 tests exactly this rule. If its precision comes out too low, the next step is conf ≥ 0.7, not the timing rule.

**4. Wired into step 4** (`pipeline/04_moments.py`, `pipeline/kinds.py`; `make story` not run)
- **`is_sport` is now moment-level for global moments.** The topic rule (Claude type plus `LEAGUE_RE`) is kept as `is_sport_topic`; it is also the fixtures list the moment rule checks dates against, so the rule is not circular. A global moment of a non-sport topic becomes sport when `sport.py` finds an entity signal, sporting-event evidence in that moment and no override; the evidence is kept in `sport_evidence`. Non-global moments keep the topic rule, since the moment rule was only tuned and validated on global moments. `meta.is_sport` stays topic-level.
- **`is_shock`** = global, non-sport, and Claude shock-v2 unscheduled with confidence ≥ `SHOCK_MIN_CONF` (0.5), from the cached labels (`kinds.shock_moments`). Moments without a label are not shocks; `moments_summary.json` counts them (0 now).
- **Rebuilt moments:** 8,014 global moments; 7,132 sport (6,082 by the topic rule plus 1,050 by the moment rule) and 882 non-sport, of which **627 are shocks**.
- **Kinds** (`kinds.topic_kinds`; written to `data/interim/work/topic_kinds.parquet` for review): a topic is a shock if it has a shock moment, is in 10+ countries on at most 4 days, and has a shock-eligible type. Precedence is unchanged: appointment and ritual win. This gives **341 shock topics** (1,268 under the old timing rule); all 927 that left became waves.
- **Step 8** (`08_story_export.py`) now takes `shocks.json` from the moment flag (`is_shock`, not hidden, named topics only). Not run yet; shocks.json and STORY_NUMBERS.md are unchanged.
- **Mismatch to decide:** 253 of the 627 shock moments belong to topics whose kind is not shock: 161 waves (in 10+ countries on more than 4 days), 49 appointments, 43 rituals. In the timeline (`peaks.json`, kind per topic) those moments will show the topic's kind, while `shocks.json` lists them as shocks.

**5. Test sample 2** (`09_validate_shocks.py sample2`, `make shocks-sample2`)
- **80 new named non-sport global moments,** none from sample 1: 40 the new rule calls shocks and 40 others, seed 29. Population after removing sample 1: 586 shocks and 236 others (`data/interim/work/shock_sample2_strata.json`, for weighting).
- **Files:** `docs/shock_validation_sample2.csv` has the same columns and helper links as sample 1 and empty label columns. `docs/shock_validation_key2.csv` holds the strata, `is_shock`, the old flags and Claude v2's labels. Both are git-ignored and listed in `docs/REVIEW_FILES.md`.
- **Scoring sample 2 is not written yet.** After you label, it needs a score stage for sample 2: precision and recall of `is_shock` and of the sport rule on these rows.

### Step 9, round 3 (2026-11-16): your decisions on transfers, moment kinds and sample 2

**1. Transfers are announcements (non-sport).** The announcements always-override stays as it is. You will relabel Mbeumo (21 Jul 2025) and Leoni (13 Aug 2025) in sample 1 as unscheduled / other. After that, the sport rule's score on sample 1 becomes 48 of 54 hand sport rows caught. The two rows weren't relabelled yet when this was written; rerun `make shocks-score` after relabelling.

**2. Kinds belong to moments, not topics.**
- **Each moment gets its own kind in step 4** (`kinds.moment_kinds`, `moments.parquet` column `kind`). Later rules win:
  - **wave:** reached 15+ countries and none of the rules below applies. That covers spread without a clear trigger, and global moments that Claude calls unscheduled with confidence < 0.5.
  - **appointment:** a sport moment (moment-level `is_sport`), a topic whose name matches a scheduled-event pattern (`APPOINT_RE`: final, awards, election, launch, premiere, …), or a global non-sport moment that Claude (shock-v2) calls scheduled.
  - **ritual:** the topic is a ritual (`kinds.topic_ritual`, same as before): weather, holidays, lotteries, prayer times, horoscopes and rates, or a non-sport other / product / company / unlabeled topic with 15+ moments in 10+ countries.
  - **local:** reached < 15 countries, unless ritual.
  - **shock:** `is_shock` (the validated rule). It wins even over ritual, so a storm on a weather topic or an outage of a daily-searched app is a shock.
- **Dropped from the old topic rule:** "a person with 10+ moments in 10+ countries is an appointment". A single moment of a frequently trending person is not scheduled because the person trends often. The shock timing and persistence conditions are dropped too; the moment-level shock rule replaces them.
- **Every trend row takes the kind of its moment.** Step 4 writes `data/interim/work/row_moments.parquet` (topic, country, start → moment_id). All 3,456,593 national rows map to a moment.
- **A topic's kind is only a summary:** the kind of its biggest moment (by reach, then countries within 60 min), in `topic_meta.parquet` column `kind`. Topics with no national moment (region-only) are local. The summary appears only in `manifest.json` counts and is available for Wrapped-style summaries; no chart uses it.
- **Step 8 changes (`08_story_export.py`, not run):**
  - `shocks.json` = moments of kind shock (not hidden, named).
  - `peaks.json`: each moment's own kind.
  - Time machine: each entry is (topic, kind of the moment the trend belongs to), so a topic can appear twice in a month with different kinds.
  - Wrapped `kind_shares`: share of the country's trends by their moment's kind.
  - `manifest.json`: kind counts for moments, global moments and topic summaries.
  - The old `topic_kinds` rule is kept only for the timing-rule columns of sample 1 (`09_validate_shocks.py`).
- **Counts after rebuilding step 4:**
  - Global moments (8,014): appointment 7,238, shock 627, wave 77, ritual 72.
  - All moments (2.03M): local 1,938,073, ritual 77,854, appointment 12,123, wave 3,141, shock 627.
  - Topic summaries: local 743,874, ritual 13,575, appointment 5,439, wave 1,887, shock 384.
- **Dry run of step 8** into a scratch folder (the real `data/export/story/` and `STORY_NUMBERS.md` are unchanged): `shocks.json` would hold 621 moments (627 minus hidden or unnamed topics: death 111, outage 98, other 412), and the timeline holds 8,014 peaks.

**3. Sample-2 scoring** (`09_validate_shocks.py score2`, `make shocks-score2` → `docs/SHOCK_VALIDATION_2.md`). Same metrics as sample 1; nothing is tuned on sample 2.
- **Sport the rule still misses:** hand `sport` rows, raw and weighted by the sample-2 strata. Moments wrongly moved to sport can't be measured here, because sample 2 only holds moments the rule calls non-sport; sample 1 measured those (1 of 44).
- **Markets** counts.
- **Claude v2 vs hand:** accuracy, kappa, confusion table and accuracy by confidence, on all rows and without sport rows.
- **Precision and recall of `is_shock`** (the chosen rule) first, then the same variants as on sample 1 (Claude at conf ≥ 0.5 / 0.6 / 0.7, with 6 h / 12 h speed tests, the timing rule AND Claude, the timing rule alone, the old shocks.json), raw and weighted.
- **Event-type confusion** against Claude v2.
- Tested on a throwaway copy with stand-in labels; the key and sample were unchanged.

### Step 9, round 4 (2026-11-16): moment kinds vs the wave pattern; outage check

**1. Sample 1 rescored after your relabel.** In the saved file, Mbeumo and Leoni now say `unscheduled`, but `event_type_label` still says `sport`, so `make shocks-score` still counts them as sport rows (56). I didn't edit your file. Scored on a scratch copy with `other` for those two rows:
- **Sport rule:** 48 of 54 hand sport rows caught; 1 of 46 non-sport rows wrongly moved (Ashworth).
- **Claude v2:** accuracy 0.761, kappa 0.413.
- **Chosen shock rule** (Claude unscheduled, conf ≥ 0.5): precision 0.81, recall 0.87; weighted 0.81 / 0.88.
- **Timing rule 15 alone:** precision 0.67, recall 0.73; weighted 0.63 / 0.38.

**2. Two layers: moment kind and topic pattern.** (`pipeline/kinds.py`, step 4, step 8)
- **Moment kind:** shock | appointment | ritual | other, which describes what each spike was. Later rules win:
  - other: the default;
  - appointment: sport moment, scheduled-event name, or Claude says scheduled;
  - ritual: ritual topic;
  - shock: `is_shock`.
- **"Wave" and "local" are no longer kinds.** A wave is a topic pattern, and "local" is a reach (< 15 countries), not what happened. Because the local rule no longer overrides appointment, small sport moments are now appointments. All moments (2.03M): other 1,789,152, appointment 164,185, ritual 77,854, shock 627. Global moments: appointment 7,238, shock 627, other 77, ritual 72. Topic summaries (biggest moment's kind): other 710,514, appointment 40,686, ritual 13,575, shock 384.
- **Topic pattern `is_wave`:** the topic trends in 15+ countries in at least `WAVE_MIN_MONTHS` separate UTC calendar months (`kinds.wave_months`; topic_meta `wave_months` and `is_wave`; moments carry `is_wave` too). It doesn't depend on moment kinds. The data covers 19 months.

  | N (months) | Wave topics | Sport topics | Ritual topics | Neither |
  |---:|---:|---:|---:|---:|
  | 3 | 1,481 | 804 | 49 | 632 |
  | 4 | 878 | 420 | 38 | 421 |
  | 6 | 426 | 174 | 26 | 226 |

  (Hidden topics excluded. "Sport" is the topic rule, so athletes count as people, not sport.)
  - **Top 20 by months (the same for every N),** non-sport and non-ritual: Donald Trump, Lamine Yamal, X (Twitter), Google, Cristiano Ronaldo, BBC, Flashscore, BYD, McDonald's, ChatGPT, CNN, Novak Djokovic, Earthquake, Lionel Messi, Bruce Willis, Sydney Sweeney, Iga Świątek, Monaco, Tom Cruise, Ticketmaster. These are always-on topics; months alone don't separate a rising wave from a constant presence.
  - **The 20 biggest topics exactly at each threshold** (where the cut-off decides):
    - 3 months: Diogo Jota, DeepSeek, "2026", Val Kilmer, Ali Khamenei, Cloudflare outage, Squid Game season 3, Pope Leo XIV, Squid Game, Spotify Wrapped, Epstein files, María Corina Machado, Myanmar, Lily Phillips, YouTube outage, Jonas Urbig, Heidi Klum, Eurovision 2025, The Last of Us, Manuel Neuer.
    - 4 months: Eric Dane, 67 (meme), Zohran Mamdani, Stranger Things 5, Gonzalo García, Travis Scott, Musiala, Luigi Mangione, Olivia Rodrigo, Olise, Jim Carrey, Travis Kelce, Szczęsny, NATO, Claude AI, Greenland, Virginia Giuffre, De Bruyne, Oil price, Sora.
    - 6 months: Roblox, Luis Enrique, Hakimi, Flightradar24, Solar eclipse, Doué, Claude, Joe Biden, GTA VI, Modrić, Kristi Noem, Marmoush, "A", Mourinho, Alexander-Arnold, Millie Bobby Brown, Woltemade, Argentina, Vitinha, Meta Platforms.
  - **AI tools and the Epstein files** (months with 15+ countries): ChatGPT 16, Google Gemini 14, Jeffrey Epstein 9, OpenAI 8, Grok 8, Claude 6, Claude AI 4, Sora 4, ChatGPT outage 4, **DeepSeek 3**, **Epstein files 3**, Perplexity 2.
  - **Proposed N = 3:** the only threshold that includes DeepSeek and the "Epstein files" topic. At N = 4 the other AI tools and Jeffrey Epstein are still in. The cost of N = 3 is repeated news (a death and its follow-ups, Diogo Jota; repeated outages, Cloudflare), plus clubs and always-on brands. Two open choices: whether `is_wave` should leave out sport topics and rituals (804 and 49 at N = 3), and whether athletes should count.
- **Step 8 (not run; checked with a dry run into a scratch folder):**
  - `waves.json`: keeps the curated series and adds `wave_topics`, every non-hidden `is_wave` topic (1,481) with its countries per month, months first. The file is 172 kB.
  - Time machine: colours = the 4 moment kinds. Topic entries are `[topic_id, name, kind index, is_wave 0/1]`, so wave is a flag, not a fifth colour.
  - Timeline (`peaks.json`): adds an `is_wave` field; 4,282 of the 8,014 peaks are on wave topics.
- **What changes for the site** (there is no front-end in this repo, so nothing here breaks):
  - `kinds` in the time machine and peaks is now `[shock, appointment, ritual, other]`. Code that maps kind indices to five colours must be updated, because index 2 was "wave" and is now "ritual".
  - Time-machine topic entries have a 4th element; readers that take the first 3 still work.
  - Wrapped: `kind_shares` has the 4 kinds, so `kind_shares.local` no longer exists. `local_share` is now its own field on each card and in `wrapped/index.json`: the share of the country's trends whose moment reached < 15 countries (US 0.94). STORY_NUMBERS adds that mean. Per-file size is unchanged (largest time-machine month 0.64 MB).

**3. Outages: 28 → 98 (report only; the rule is unchanged).** The full list (date, topic, countries, old topic kind, top phrasings) is in `data/interim/work/outages98.csv` (local). Findings:
- **All 28 old outages are still in.** Of the 70 new ones, **62 come from topics the old rule called "wave"**: in 10+ countries on more than 4 days, like ChatGPT, Google Gemini, OpenAI, BBC, Spotify, YouTube, X, Instagram and Roblox. That persistence test removed every moment of such a topic, including real outages (ChatGPT 11 Dec 2024 and 23 Jan 2025, YouTube 15 Oct 2025). **8 come from a topic the old ritual rule caught**: all 8 are Bet365, a product/company topic with 15+ moments in 10+ countries.
- **Routine status searches:** only **21 of the 98** have a status word in their top phrasings ("is X down", "downdetector", "status", "se cayó"). 56 of the 70 new ones show only the brand name, so "outage" comes from the sub-kind keyword rule on the topic's later searches or related searches. Likely routine or mislabelled: **BBC × 8** and **Bet365 × 8**, none with a status phrasing.
- **One outage often hits several topics:** the 98 moments fall on 66 days, and 20 days have 2 or more (11 Dec 2024: Facebook, Instagram, Gemini, ChatGPT; 18 Nov 2025: Cloudflare, Bet365, ChatGPT). The number of outage *events* is closer to 66 than 98.

### Step 9, round 5 (2026-11-16): sample 1 final, wave refinements, outage evidence

**1. Sample 1 with your fixed labels** (`make shocks-score`; Mbeumo and Leoni are now unscheduled / other):
- **Sport:** 54 of 100 rows are sport (weighted 61.1%). The sport rule catches 48 of 54 and wrongly moves 1 of 46 (Ashworth). Remaining misses: Baena, Porro, Alexsandro (national-team days), Fabio Silva, Jack Fletcher (club only via teammates; one P54 batch is still blocked by Wikidata lag), Pablo Torre.
- **Claude v2 vs hand** (46 non-sport rows): accuracy 0.761, kappa 0.413.
- **Chosen shock rule** (Claude unscheduled, conf ≥ 0.5): precision 0.81, recall 0.87; weighted 0.81 / 0.88. Timing rule 15 alone: 0.67 / 0.73; weighted 0.63 / 0.38.

**2. Wave refinements (N stays 3)** (`kinds.wave_flags`, `04_moments.sporty`)
- **`is_wave`** = 15+ countries in at least 3 separate UTC months, and not:
  - a sport topic (topic rule);
  - an athlete or other sport topic the topic rule misses: the sport rule's entity signal (Wikidata sport description, sport site or channel, competition name, or sport related searches for people), or most of the topic's global moments are sport (club cities such as Paris and Monaco);
  - a ritual topic.
- **`is_constant`** = 15+ countries in 12 or more months, for any topic (`CONSTANT_MIN_MONTHS = 12`, of the 18 full months). A topic can be both.
- **Counts:** 385 wave topics (not hidden), of which 43 are also constant; 159 constant topics overall. The exclusions took 1,481 → 385.
- **Top 30 wave topics** by months, non-constant first: Iran 11, iPhone 17 11, Dua Lipa 11, The New York Times 11, "test" 11, "Videos" 11, IPTV 11, Outlook 10, YouTube 10, Shakira 10, Justin Bieber 10, Prime Video 10, PlayStation 5 10, Sabrina Carpenter 10, Bitcoin price (BTC/USD) 10, Jason Statham 10, Julia Roberts 10, Venezuela 9, Spotify 9, Nicolás Maduro 9, Jeffrey Epstein 9, Twitter (X) outage 9, Emmanuel Macron 9, Binance 9, Yahoo 9, Nintendo Switch 2 9, Demi Moore 9, Ariana Grande 9, Jackie Chan 9, Major League Baseball 9.
- **Wave and constant (43):** X, Donald Trump, Google, BBC, McDonald's, BYD, Tom Cruise, ChatGPT, Sydney Sweeney, CNN, Bruce Willis, Ticketmaster, Earthquake (×2), Instagram, Putin, "News", Netflix, Taylor Swift, Elon Musk, Disney, Teams, Tarjeta roja, GTA 6, Tesla, TikTok, Israel, Google Gemini, Angelina Jolie, Apple, WhatsApp, Stranger Things, Titanic, BBC News, Epic Games, Netanyahu, Amazon, DiCaprio, Nvidia, Starlink, Madonna, Harry Potter, "f".
- **Checks (months with 15+ countries):**
  - **In:** DeepSeek 3, Epstein files 3, Jeffrey Epstein 9, Claude 6, Claude AI 4, Grok 8, Google Gemini 14 (constant), ChatGPT 16 (constant), OpenAI 8, Sora 4. Markets: S&P 500 8, Dow Jones 5, Nasdaq 3, Bitcoin price (BTC/USD) 10, Oil price 4.
  - **Not in:** Tariffs (15+ countries in only 1 month, April 2025, a spike rather than a wave). Bitcoin (18 months) and Gold price (12) are rituals by the existing rule (the frequent-topic rule and `RITUAL_RE` "gold price"), so `is_wave` leaves them out, though both are constant.
- **Still in the wave list but questionable:** sport the exclusions miss (Major League Baseball, DFB-Pokal, Tarjeta roja, Valencia) and generic strings ("test", "Videos", "live", "News", "f"). Not changed.

**3. Selection rule for the Waves chapter's series** (`waves.json` → `wave_series_rule`, `wave_series`, `hand_picked_vs_rule`)
- **Rule:** each wave topic gets a theme, from keyword groups first (AI tools; markets and crypto; Epstein), otherwise from its Claude type (people; tech and brands; media and entertainment; events; places and politics; other). In each theme, the **5 non-constant wave topics** with the most months in 15+ countries (ties: more countries overall) are the series. Constant wave topics are listed apart per theme, because they are always present rather than rising and falling.
- **Selected, per theme:**

  | Theme | Series (months with 15+ countries) |
  |---|---|
  | AI tools | Grok 8, OpenAI 8, Claude 6, Claude AI 4, Sora 4 (constant: ChatGPT, Google Gemini) |
  | Markets and crypto | Bitcoin price (BTC/USD) 10, Binance 9, Nvidia stock 8, S&P 500 8, Dow Jones 5 |
  | Epstein | Jeffrey Epstein 9, Virginia Giuffre 4, Epstein files 3 |
  | Places and politics | Iran 11, Venezuela 9, Malta 9, Saudi Arabia 9, Syria 8 |
  | People | Dua Lipa, Shakira, Justin Bieber, Sabrina Carpenter, Jason Statham |
  | Tech and brands | iPhone 17, IPTV, Outlook, YouTube, Prime Video |
  | Media and entertainment | The New York Times, BTS, Radio, Fortnite, Al Jazeera |
  | Events | Major League Baseball, Full moon, Solar eclipse, DFB-Pokal, Papal conclave |
  | Other | "test", "Videos", Valencia, Classroom, "live" |

- **The hand-picked series against the rule:**
  - **Selected:** ChatGPT (through OpenAI and Sora; ChatGPT itself is constant), Claude, Grok, Epstein files, Bitcoin (through Bitcoin price (BTC/USD)), S&P 500, Dow Jones.
  - **Not selected:**
    - Google Gemini: constant, so it is listed apart;
    - DeepSeek and Nasdaq: waves with 3 months each, below the top 5 of their themes;
    - Gold price: not a wave (ritual);
    - Tariffs: not a wave (1 month).
  - The hand-picked series stay in `waves.json` (`monthly`, `daily`) next to the rule-based ones until you choose.

**4. Outages need evidence in the moment's own searches** (`08_story_export.py`)
- **Rule:** a shock is an outage only if one of the moment's own searches is outage evidence. Those searches are the per-country phrasings plus the raw and related searches of the topic's national rows inside the moment (start .. end, at least 1 h). Before, outage words anywhere in the topic's 48 h searches or all of its related searches counted. Otherwise the event type is other (or death, which keeps its old rule).
- **Evidence words** (several languages): outage, down, not working, stopped working, server status / status page / service status, downdetector, error, problem(s), issue(s); caído/a, se cayó, no funciona, no carga, falla(s); caiu, fora do ar, não funciona, instável; panne, ne fonctionne pas; Störung, Ausfall, geht nicht, funktioniert nicht; non funziona, disservizio; kesinti, çöktü, erişim sorunu; gangguan, tidak bisa; не работает, сбой, упал; storing, werkt niet; awaria, nie działa; 障害, 繋がらない, ダウン, عطل, توقف, لا يعمل, خلل, 故障, 宕机, 장애, 오류.
- **Not evidence:** a search about planes, the military or markets. A first pass without this exclusion tagged "pakistan shot down indian jets", "aviao caiu", "why is gold down today", "caida criptomonedas", "trump backs down", "delta flight status" and "big beautiful bill status" as outages. "Status" alone, and "bug", no longer count.
- **Result:** **64 outage moments on 47 distinct days** (98 on 66 days before this rule; 28 in the current shocks.json). 60 of the 98 stay; 26 of the original 28 stay. The two originals that drop, Reddit 19 Dec 2025 and Claude AI 20 Apr 2026, show only the brand name in their own searches. 4 are added: Canva 20 Oct 2025 and 5 Dec 2025 (AWS and Cloudflare days), "Cloudflare challenge page unblock" 18 Nov 2025, and Wordle 9 Apr 2026 ("wordle down").
- **BBC:** all 8 moments are now other (sub-kind viral or celebrity); none had outage evidence. **Bet365:** 7 of 8 are now other; 20 Feb 2026 stays an outage ("bet 365 down", "bet365 app not working").
- `shocks.json` gets an `outage_evidence` field (the matching search). The list is in `data/interim/work/outages_v2.csv` (local).

### Step 9, round 6 (2026-11-16): junk topics, last sport leaks in waves, waves rule notes

**1. Junk topics are left out everywhere** (`04_moments.junk_topics` → topic_meta `is_junk` and `junk_reason`)
- **Rule** (a topic is junk if any of these hold):
  1. **single character:** the name is one character ("A", "e", "f", "V");
  2. **bare number:** the name is only digits ("2026", "2024", "0", "7"); "9-1-1" and "+31" stay;
  3. **unknown:** Claude named the topic "unknown", never anything else, and it has no Wikidata match ("test", "live", "working", "what", "next", "home", "ok", "in", "on"). Topics Claude was never asked to name are *not* junk;
  4. **generic word:** the name, without a "[…]" language suffix, is on a list of generic search-box words: news, sport(s), football, radio, time, email, mail, video(s), film, movie(s), game(s), score, live tv, translate, weather, …, plus English, Spanish, Portuguese, French and German stopwords and question words. A ritual topic is exempt, so the generic "Weather" topics (category weather) stay.
- **Kept on purpose:** real short topics are unaffected because none of the rules match them: Iran, Gemini, X (Twitter), NBA, UFC, CNN, BTS, BBC, BYD, G7, XRP. Ambiguous short words that aren't on the list also stay: Dog, Air, Red, Gas, Who, Age.
- **Removed:** 1,140 topics (bare number 646, single character 257, generic word 127, unknown 110), 19,037 national trends (0.55%), 69 of them reaching 15+ countries. **Top 50 by reach:** 2026, A, e, c, m, n, i, News, t, working, test, Radio, 2024, live, f, Videos, G, s, r, Time, Sport, B, Football, Live TV, 2027, Email, Video, what, d, Film, next, home, Translate, Games, H, Score, V, j, 3, k, ok, Mail, 2028, in, 0, on, Game, Sports, Movies, 2.
  - "V" (BTS's V) and "Translate" (Google Translate) are real meanings lost by the rule; "orai rytoj" (Lithuanian for "weather tomorrow") is junk because Claude named it "unknown".
- **Where it applies:**
  - **Step 5:** `visibility()` adds junk topics to the hidden set, whatever the sensitive decisions say. This takes effect on the next `make export`, not run yet. Until then, four current Wrapped cards name a junk topic: LT most-local "orai rytoj", and busiest-day top topics IR "Film", KZ "2026" and KH "best".
  - **Step 8:** junk rows and moments are dropped at load, so they leave every chapter and the denominators of the Wrapped shares.
  - **Waves:** `is_wave` and `is_constant` leave junk out.
  - **Step 9:** `score2` skips junk-topic rows and prints their sample_ids; the sample files are not changed. **No sample-2 moment is junk** (and no sample-1 moment).
- **How the chapters change** (dry run of step 8 into a scratch folder, before vs after):

  | Chapter | Before | After |
  |---|---:|---:|
  | Local: topics in 1 country | 580,756 (84.8%; 33.9% of trends) | 579,959 (84.9%; 34.0%) |
  | Local: topics in 2–14 countries | 92,450 | 92,201 |
  | Local: topics in 15+ countries | 11,301 (1.7%; 40.3% of trends) | 11,232 (1.6%; 40.2%) |
  | Local: median single-country share | 21.2% | 21.3% |
  | Local: most / least local | Japan 92.3%, Turkmenistan 1.3% | Japan 92.4%, Turkmenistan 1.4% |
  | Shocks | 621 | 614: News × 2 (junk) and Tarjeta roja × 5 (now sport, below) |
  | Outages | 64 on 47 days | unchanged |
  | Timeline peaks | 8,014 | 7,999: the unnamed "c / e / i / m / n / r / t" moments of 23–24 Jun 2025, "2026", "Live TV" × 2, "News" × 2, "working" |
  | Wave topics | 385 | 360 |
  | Wrapped mean shares | appointment 47.2%, other 46.5%, local 58.8% | appointment 47.5%, other 46.2%, local 58.6% |

**2. Last sport leaks in `is_wave`** (`sport.py`, `04_moments.sporty`)
- **New sport sites:** tarjeta roja, roja directa / rojadirecta, pirlo tv, fútbol libre, marca tv.
- **New competition names:** names containing "pokal", starting "major league", or ending in league / liga / ligue / lig / serie a/b / bundesliga; also "primera división" and "friendlies".
- **Club places count as sport for waves:** places with 3+ sport related searches (Georgia, Budapest, Azerbaijan, Panama).
- **"Other"-typed topics with sport related searches count too** (Teams: NFL and NBA searches; Valencia; Madrid; Scratch). Products and companies don't (Max, Stake stay waves).
- **Result:** Major League Baseball, DFB-Pokal, Tarjeta roja, Valencia, Madrid, Georgia, Budapest, Azerbaijan, Panama, International friendlies, Süper Lig, Pakistan Super League, Primera División (Argentina), Teams and Scratch are no longer waves. With junk this gives **360 wave topics**, 157 constant, 39 both.
- **Side effect on moments:** the site pattern is part of the moment-level sport rule, so Tarjeta roja's 5 global moments are now sport (global sport 7,137, moment rule adds 1,055; shocks 622, 614 after junk and hidden). No sample-1 or sample-2 moment changed its sport flag.

**3. Waves selection rule kept as is.** The themes are an editorial choice; the members of each theme are chosen by the rule. The new "other" and "events" series after the fixes are Classroom, Windy, Fast, 67 (meme), NATO, and Full moon, Solar eclipse, Papal conclave, Tomorrowland, Hong Kong fire.
- **DeepSeek and Nasdaq** are wave topics (3 months each) but fall outside the top 5 of their themes (AI tools; markets and crypto). They are **not added by hand**.
- **Tariffs** reached 15+ countries in only one month (April 2025): a one-month spike, not a wave. It stays out of the wave series; the existing daily series for 25 Mar – 20 Apr 2025 still covers it.

### Step 9, round 7 (2026-11-16): junk allowlist

- **`JUNK_ALLOW`** (`04_moments.py`, by topic_id) keeps real topics the junk rule would remove: **"V"** (BTS's V) and **"Translate"** (Google Translate). Junk is now 1,138 topics: bare number 646, single character 256, generic word 126, unknown 110. Wave topics are unchanged at 360.
- **Other entries in the top 200 junk list that may be real topics** (reported, not allowlisted):
  - **likely real:** "seek" (6 countries; probably the Seek job site), "444" (4, Claude type media; probably the Hungarian news site 444.hu), "are" (4; top search "åre", the Swedish ski resort);
  - **tools, like Translate:** "Calculator" (7, Claude type product) and "Mail" (23, product);
  - **ambiguous:** "808", "unl", "uta", "adrián", "Die" (media), "999", "1992", "more" ("møre").
  - Everything else in the top 200 is single letters, digits, years, stopwords or generic words (news, sport, video, live TV, games, music, calendar, … in several languages).

### Step 9, round 8 (2026-11-16): allowlist rule

- **Rule for `JUNK_ALLOW`:** a topic the junk rule removes is allowed back only if it names one specific thing (a person, product, site or place). Generic tools and ambiguous words stay junk.
- **Allowed** (by topic_id): "V" (BTS's V), "Translate" (Google Translate), **"seek"** (Seek, the job site), **"444"** (444.hu, Hungarian news site) and **"are"** (Åre, the Swedish ski resort).
- **Stay junk:**
  - generic tools: "Calculator", "Mail";
  - ambiguous: "808", "unl", "uta", "adrián", "Die", "999", "1992", "more".
- **Result:** junk is 1,135 topics (bare number 645, single character 256, generic word 126, unknown 108). Wave topics are unchanged at 360.

### Step 9, round 9 (2026-11-17): test sample scored, threshold revisited, cricket, story rebuilt

**1. Sample 2 (test) results** (`make shocks-score2` → `docs/SHOCK_VALIDATION_2.md`, local; 80 moments, none junk)
- **Claude v2 vs hand:** accuracy 0.738, kappa 0.496 (without sport rows 0.765 / 0.529). Claude called 19 of the 46 scheduled moments unscheduled, mostly at confidence ≤ 0.6.
- **Chosen rule (conf ≥ 0.5):** precision 0.70, recall 0.82; weighted 0.70 / 0.92. Without sport rows: 0.72 / 0.82; weighted 0.72 / 0.90.
- **Other rules:** conf ≥ 0.6: 0.91 / 0.62 (weighted 0.91 / 0.69). conf ≥ 0.7: 0.93 / 0.41. Timing rule 15 alone: 0.61 / 0.50. Old shocks.json: 0.71 / 0.59.
- **Sport the rule still missed:** 12 of 80 (weighted 9.7%), 11 of them in the non-shock half; 7 were cricketers.

**2. Threshold revisited after the test sample.** On sample 2, conf ≥ 0.6 beat 0.5 on precision. Because looking at the test sample and then choosing is tuning on it, the rule was decided on sample 1 only: switch to 0.6 only if it also beats 0.5 on precision there without a large recall loss.

| Sample (non-sport rows) | conf ≥ 0.5 P / R (weighted) | conf ≥ 0.6 P / R (weighted) | conf ≥ 0.7 P / R (weighted) |
|---|---|---|---|
| Sample 1 (n = 46) | 0.81 / 0.87 (0.81 / 0.88) | 0.86 / 0.60 (0.83 / 0.51) | 0.94 / 0.50 (0.97 / 0.41) |
| Sample 2 (n = 68) | 0.72 / 0.82 (0.72 / 0.90) | 0.91 / 0.62 (0.91 / 0.67) | 0.93 / 0.41 (0.93 / 0.45) |

- **Sample 1 decides it:** 0.6 gains only 0.05 precision (0.02 weighted) and loses 0.27 recall (0.37 weighted). **`is_shock` stays at conf ≥ 0.5.**
- **Pooled over both samples** (114 non-sport rows, 64 unscheduled). Rows are weighted by stratum within their own sample, and each sample's weights are scaled to its row count; 95% CIs come from 5,000 bootstrap resamples within sample × stratum.
  - conf ≥ 0.5: precision **0.75 [0.64, 0.86]**, recall **0.89 [0.81, 0.96]**;
  - conf ≥ 0.6: 0.88 [0.75, 0.98], 0.60 [0.47, 0.74];
  - conf ≥ 0.7: 0.95 [0.84, 1.00], 0.43 [0.30, 0.57].
- **What it means:** about one shock in four is a scheduled event that Claude misread, and the rule finds about nine in ten real ones.

**3. Cricket and league tables** (`sport_calendar.py`, `sport.py`). These are the only two changes made after the test sample.
- **Cricket calendar** (English Wikipedia, read 2026-11-17):
  - "2025 Indian Premier League": 22 Mar – 3 Jun 2025, suspended 9–16 May (India–Pakistan crisis) and resumed 17 May, so two windows;
  - "2026 Indian Premier League": 28 Mar – 31 May 2026;
  - "2025 ICC Champions Trophy": 19 Feb – 9 Mar 2025;
  - "2026 ICC Men's T20 World Cup": 7 Feb – 8 Mar 2026.
  - It applies to athletes whose Wikidata description says "cricketer".
- **League-table phrases** count as competition names (topic names) and as competition evidence in a moment's searches: "standings", "clasificación", "tabla" (not "tabla periódica"), "tabla de posiciones", "classifica", "tabelle", "ترتيب الدوري".
- **Diagnostic only (no further retuning on sample 2):**
  - **7 of the 12** sample-2 sport misses are now caught: Sarfaraz Khan, Allah Ghazanfar, Naman Dhir, Ishant Sharma (IPL), Abhishek Sharma (T20 World Cup), and "Spanish football league standings" × 2.
  - **Still missed:** Shahbaz Ahmed, Shubham Dubey, Wrocław, Eric García, Emma Raducanu.
  - No non-sport sample-2 row moved to sport.
- **All global moments:** 34 more are sport (moment rule now adds 1,095; global non-sport 837), 6 of them former shocks. Shock moments: 610 in moments.parquet, 602 in shocks.json (hidden and unnamed topics left out).

**4. `make export` and `make story` run** (2026-11-17). Changes in `docs/STORY_NUMBERS.md` against the previous version (old timing rule, topic kinds, no junk filter):

| Number | Before | After |
|---|---:|---:|
| Shock moments | 535 | 602 |
| … deaths | 98 | 111 |
| … outages | 28 | 64 |
| … other | 409 | 427 |
| Topics in 1 country | 580,756 (84.8%; 33.9% of trends) | 579,959 (84.9%; 34.0%) |
| Topics in 15+ countries | 11,301 (1.7%; 40.3% of trends) | 11,234 (1.6%; 40.2%) |
| Median single-country share | 21.2% | 21.3% |
| Most local country | Japan 92.3% | Japan 92.4% |
| Wave topics | — | 360 |
| Timeline peaks | 8,014 | 7,999 |

- **Wrapped mean shares:** shock 2.1% → 1.1%, appointment 40.4% → 47.5%, ritual 5.2% → 5.1%, "other" 46.2% (new), local share 58.6% (now a reach measure; it was the "local" kind at 45.2%), "wave" kind gone (was 7.2%).
- **The five widest shocks** are now ChatGPT 23 Jan 2025 (121 countries), Diogo Jota, Hulk Hogan, Venezuela 3 Jan 2026 (117) and ChatGPT 11 Dec 2024 (116). Ozzy Osbourne, Michelle Trachtenberg and Eric Dane (110–112) are still shocks, just below the top 5.
- **Not shocks under the new rule:** Bianca Censori (Grammys, Claude: scheduled) and Edoardo Bove. Claude v2 calls Bove's moment scheduled, while your sample-1 label is unscheduled: one of the rule's known errors.

### Step 9, round 10 (2026-11-17): hand labels override, chart verification, true-shock estimate

**1. Hand labels override Claude and the sport rule** (`kinds.load_hand_labels`, `04_moments.add_shock`, step 8)
- **Source:** every moment labelled by hand, in sample 1, sample 2 and the chart verification sheets (local, git-ignored files; without them nothing is overridden).
- **What the hand labels decide:**
  - `is_shock` = hand unscheduled and hand event type ≠ sport;
  - `is_sport` = hand event type is sport;
  - the scheduled/unscheduled input of the moment kinds (`scheduled_final`);
  - in step 8, the death / outage / other split: hand death → death, hand outage → outage, anything else → other. The sub-kind comes from the hand type: disaster → disaster or accident, politics_conflict → politics or conflict, launch, viral_celebrity → viral or celebrity, markets, other.
- **The rule alone** is kept as `is_shock_rule` (used for the estimate below).
- **Result:** all 180 hand labels apply to global moments. Shock moments are now 599; the rule alone gives 610.
- `shocks.json` gets `verified` (true if hand-labelled unscheduled) and `kind_source` (hand label or rule).

**2. Chart verification** (`09_validate_shocks.py verify-sheet`, `make shocks-verify`)
- **The chart set** is the 60 widest shocks (countries, then countries within 60 min) among shocks.json's population (not hidden, named). `shocks.json` gets `chart_top60` (moment ids and the number verified).
- **Sheet 1:** `docs/shock_chart_verification.csv` holds the 53 chart shocks without a hand label (7 of the 60 were already hand-labelled unscheduled, so verified). It has the same columns and helper links as the samples, empty label columns and no Claude output. Its key, `docs/shock_chart_verification_key.csv`, has the moment key, chart rank and Claude's label. Both are git-ignored.
- **Loop:** after labelling a sheet, run `make moments`. Rows marked scheduled (or sport) stop being shocks and the next widest move up. Then `make shocks-verify` writes `_2` with the chart shocks still unlabelled, until all 60 are verified. It refuses while an earlier sheet has unlabelled rows.

**3. Estimated true number of shocks** (`09_validate_shocks.py estimate` → `work/shock_estimate.json`; STORY_NUMBERS reads it on the next `make story`)
- **Method:** estimate = flagged × precision / recall.
  - flagged = **602** moments the rule alone flags among shocks.json's population;
  - precision and recall of the current rule come from both hand samples (180 rows, 64 truly unscheduled non-sport). Truth = hand unscheduled and not sport; prediction = the current rule on that moment, so hand-sport rows count as false positives when flagged;
  - rows are weighted by stratum within their sample, and each sample's weights are scaled to its row count;
  - the 95% interval comes from 5,000 bootstrap resamples within sample × stratum.
- **Result:** precision 0.706, recall 0.895. **Estimated true shocks: 475 [400, 548].**
  - Precision is lower than the 0.75 reported in round 9 because sport rows now count: a leaked sport moment that the rule flags is a false positive here.

### Step 9, round 11 (2026-11-17): chart verified, story rebuilt

- **Sheet 1** (`docs/shock_chart_verification.csv`, 53 rows): all labelled. 50 unscheduled, 3 scheduled (Robert Francis Prevost, Travis Scott, Olivia Rodrigo), none sport. Event types: death 27, outage 14, politics_conflict 6, viral_celebrity 3, other 3.
- **After `make moments`:** the three scheduled moments are no longer shocks, and the next three widest moved into the chart set.
- **Sheet 2** (`docs/shock_chart_verification_2.csv`, 3 rows): Joe Biden (unscheduled, viral_celebrity), New Orleans (unscheduled, disaster) and the YouTube outage (unscheduled, outage).
- **All 60 chart shocks are hand-verified.** `make shocks-verify` writes no further sheet. 236 hand labels now override Claude. Shock moments: 596 in moments.parquet (610 by the rule alone).
- **`make story` rerun.** `shocks.json` has **588 shocks**: death 115, outage 74, other 399. 117 are hand-verified, including the 60 in `chart_top60`. Before the verification labels, it had 602: death 111, outage 64, other 427.
  - **Why the counts moved:** fewer shocks because some hand labels say scheduled; more outages because the hand labels now decide the death / outage / other split (14 outages in sheet 1 alone).
- **STORY_NUMBERS.md** adds:
  - chart set verified: 60 of 60;
  - shocks verified by hand label: 117;
  - estimated true number of shocks: **475 [400, 548]** (flagged 602 by the rule alone; precision 0.706, recall 0.895; round 10).

### Step 9, round 12 (2026-11-17): event reach for readers

**Two counts, and why they differ (Pope Francis, 21 Apr 2025).** `opening.json` said 120 countries in 24 h, 109 within 60 min. `shocks.json` said reach 101, reach_60 92.
- **The opening** counts 15 topics matching "pope francis" over a fixed window, 21 Apr 06:00 – 22 Apr 06:00 UTC.
- **The shock** counts one topic (Q450675) and only the countries whose session of it *starts* in the burst that began 07:50 UTC.
- **The 19 countries in the opening but not the shock:**
  - **6 through other topics only:** Argentina ("murio el papa"), Kazakhstan ("папа римский умер"), Lithuania ("pope died") and Kenya ("pope francis death"), all through "Death of Pope Francis"; Colombia ("Quotes of Pope Francis"); Costa Rica ("Pope Francis Vatican", 22 Apr 01:30).
  - **13 through the Easter overlap:** France, Romania, Switzerland, Slovakia, Belgium, Italy, Poland, Hungary, Croatia, Bulgaria, Brazil, the United States and Mexico. They were trending the Pope from Easter weekend (sessions from 19–20 Apr), so their searches on the 21st belong to the Easter moment.
- **The first-hour gap** (109 vs 92) has the same 17 countries behind it: all of them are missing from the shock moment entirely.
- **The same 24 h count (name-matched topics) for the top shocks:** ChatGPT 23 Jan 2025 123, Diogo Jota 122, **Pope Francis 120**, Venezuela 120 (a loose match), ChatGPT 11 Dec 2024 119, Hulk Hogan 118. Pope Francis ranks 3rd by that measure, 6th by its own topic over 24 h (114), and about 13th by moment reach (101).

**Definition** (`pipeline/events.py`):
- **Event reach** = countries where any topic in the event's group trended from 2 h before the moment start to 24 h after.
- **Event reach within 60 min** and **event minutes to half** are counted from the moment start; rows up to 2 h earlier count as minute 0. This differs from the moment's `reach_60`, which counts from the third country's first trend.
- **The event group** = the moment's topic + the candidate topics accepted by hand.
- **Event reach is what readers see** for the opening and the 60 chart shocks. **Moment reach stays internal:** shock detection, the global-moment rule, the time machine.
- **The chart set itself is still chosen by moment reach** (the 60 widest verified shocks) and then shown and ranked by event reach. A shock outside the 60 could have a larger event reach.

**Candidates** (`09_validate_shocks.py event-groups` → `docs/event_groups_review.csv`, git-ignored):
- **What counts as a candidate:** for each chart shock, every non-junk topic that trended in the event window and whose name matches. That means the same name, a name containing the event's name ("Death of Pope Francis"), a multi-word name inside it, or, for people, the surname (flagged "surname only: check it is the same person").
- **Columns:** event, candidate topic, match kind, top phrasings in the window, countries in the window, countries added (those that didn't trend the main topic) and their codes, and an empty `accept`.
- **Nothing is auto-accepted.** Events with more than 25 candidates are flagged "generic". Result: 435 candidates for 53 of the 60 events (7 have none), 95 of which add at least one country. Generic: Iran 22 Jun 2025 (84 candidates) and Venezuela 3 Jan 2026 (39).

**After the review** (not done yet):
- `make story` uses the accepted groups once every row has a decision. `opening.json` and `shocks.json` → `chart_top60.by_event_reach` then carry event reach, event reach within 60 min and event minutes to half, and STORY_NUMBERS lists the top five by event reach.
- Until then, step 8 keeps the old opening (name pattern, fixed window) and moment reach.
- A dry run with only full-name matches accepted reproduced the opening's 120 / 109 / 10 minutes.

**METHODOLOGY.md:** new section "Moment reach and event reach" with the Pope Francis example. "Moments" and "Kinds" are updated to the current rules (moment-level sport, moment kinds, the validated shock rule, waves as a topic pattern, junk topics).

### Step 9, round 13 (2026-11-17): no-effect candidates marked automatically

- **Rule:** a candidate topic is marked `accept = "no-effect"` when accepting it can never change a number we show (event reach, event reach within 60 min, event minutes to half). That holds when every country it trended in the event window also trended the main topic, and never earlier than the main topic did. Minutes count from the moment start and are clipped at 0, so rows up to 2 h before the start tie at minute 0.
- **Why this is safe:** the main topic is always in the group, so such a row can't lower any country's first time, whatever else is accepted. No-effect rows count as decided but are not added to the group; they don't affect any result either way.
- **Check:** for every event, accepting all candidates and accepting all except the no-effect ones give identical numbers.
- **Result:** of the 435 candidates, **317 are no-effect** and **118 remain to review**, in 24 events; the other 29 events with candidates have none left to review.
  - Biggest groups to review: Iran 22 Jun 2025 (54), Pope Francis 21 Apr 2025 and 22 Feb 2025 (7 each), Facebook 11 Dec 2024 (7), Venezuela 3 Jan 2026 (6), Anthony Joshua (6).
- **Columns and order:** the file adds `earlier_countries` (countries where the candidate trended before the main topic) and `can_change`. Rows that can change a number come first, grouped by event in chart order (most countries added first); the no-effect rows follow.

### Step 9, round 14 (2026-11-17): event groups reviewed, story on event reach

**Review result** (`docs/event_groups_review.csv`): all 118 rows that can change a number are decided, 72 accepted and 46 rejected; 317 stay no-effect.
- **Accepted, per event:**
  - **Pope Francis, 21 Apr 2025:** Death of…, Quotes of…, Last appearance of…, Pope Francis Vatican, Name of…, Pope Francis death, and a second "Pope Francis" topic.
  - **Iran, 22 Jun 2025:** 15 topics on the US strikes, among them US strikes on Iran, United States attacks Iran, Iran–United States conflict and USA vs Iran.
  - **Facebook, 11 Dec 2024:** 7 outage and login topics.
  - **Anthony Joshua:** 5 car-crash topics.
  - **Chuck Norris:** 4 death topics.
  - **Venezuela, 3 Jan 2026:** 5 topics.
  - Smaller groups for the other events.

**`make story` rerun on event reach.**
- **Opening** (`opening.json`, basis "event reach"): Pope Francis main topic + 7 accepted topics, window 21 Apr 05:50 – 22 Apr 07:50 UTC. **120 countries, 109 within 60 min, 10 minutes to half**, first trend 07:50 UTC. Unchanged from the name-pattern version.
- **Chart, top 20 by event reach** (event reach / within 60 min / minutes to half; moment reach in brackets):

  | # | Shock | Date | Event reach | Within 60 min | Min to half | Moment reach |
  |---:|---|---|---:|---:|---:|---:|
  | 1 | ChatGPT | 2025-01-23 | 123 | 120 | 10 | (121) |
  | 2 | Diogo Jota | 2025-07-03 | 122 | 90 | 60 | (120) |
  | 3 | Pope Francis | 2025-04-21 | 120 | 109 | 10 | (101) |
  | 4 | ChatGPT | 2024-12-11 | 119 | 116 | 20 | (116) |
  | 5 | Venezuela | 2026-01-03 | 119 | 55 | 70 | (117) |
  | 6 | Hulk Hogan | 2025-07-24 | 118 | 106 | 20 | (118) |
  | 7 | Chuck Norris | 2026-03-20 | 116 | 2 | 140 | (91) |
  | 8 | Eric Dane | 2026-02-20 | 112 | 58 | 60 | (112) |
  | 9 | Ozzy Osbourne | 2025-07-22 | 110 | 104 | 10 | (110) |
  | 10 | Michelle Trachtenberg | 2025-02-26 | 110 | 95 | 30 | (110) |
  | 11 | Jimmy Carter | 2024-12-29 | 109 | 76 | 40 | (109) |
  | 12 | Val Kilmer | 2025-04-02 | 109 | 60 | 50 | (109) |
  | 13 | Gene Hackman | 2025-02-27 | 107 | 51 | 70 | (106) |
  | 14 | Diane Keaton | 2025-10-11 | 102 | 77 | 40 | (101) |
  | 15 | ChatGPT | 2025-11-18 | 100 | 1 | 200 | (86) |
  | 16 | David Lynch | 2025-01-16 | 99 | 89 | 20 | (99) |
  | 17 | Cloudflare outage | 2025-11-18 | 99 | 76 | 30 | (95) |
  | 18 | Rob Reiner | 2025-12-15 | 99 | 4 | 160 | (99) |
  | 19 | Google Gemini | 2025-01-23 | 96 | 90 | 10 | (96) |
  | 20 | Roblox | 2025-08-23 | 96 | 1 | 490 | (96) |

  The 60th chart shock by event reach is the YouTube outage of 15 Oct 2025 (62).
- **STORY_NUMBERS.md:** the top five now quote event reach / within 60 min / minutes to half (`chart_top60.by_event_reach`). Pope Francis enters at 3rd and Hulk Hogan drops out of the five.

**Open: "within 60 min" counts from the first trend.** For 17 chart shocks, one or two countries trended early and the main spike came hours later, so "within 60 min" is tiny. Examples: Chuck Norris 2 of 116 (81 countries by 3 h), ChatGPT 18 Nov 2025 1 of 100, Rob Reiner 4 of 99, Roblox 1 of 96, Google Gemini 11 Dec 2024 1 of 74, El Mencho, Kim Sae-ron, Frank Caprio, Pam Bondi, New Orleans. The global-moment rule avoids this by counting from the third country. Counting the event figures the same way would fix it; that is not changed yet and is a decision for you.

**Ranks 61–100 by moment reach, checked for event reach.** Two bounds for each: the main topic alone, and every name-matched candidate that can change a number accepted.
- **14 could beat the 60th chart shock (62)** under the upper bound:
  - Taylor Swift 26 Aug 2025 (61–72);
  - Jorge Costa (64–67);
  - Elon Musk 20 Jan 2025 (66–68);
  - Kristi Noem (69–70);
  - Michail Antonio (62–65);
  - Iran 5 Apr 2026 (64–82);
  - ChatGPT 10 Jun 2025 (59–81);
  - GTA 6 (57–73);
  - Flightradar24 (59–63);
  - Cloudflare outage 5 Dec 2025 (54–63);
  - PlayStation Network (54–71);
  - Nintendo Switch 2 (59–63);
  - OPEC (54–63);
  - Tomorrowland (53–68).
- **4 beat it on their main topic alone:** Jorge Costa, Elon Musk, Kristi Noem, Iran.
- None of the 14 was hand-labelled.
- **Verification sheet:** `docs/shock_chart_verification_3.csv` (14 rows, same columns and links, empty labels; key `_3_key` with both bounds). It is part of the verification-sheet loop, so its labels override Claude after `make moments`.
- **Their event-group candidates:** `docs/event_groups_review_extra.csv` (112 rows: 60 to review, 52 no-effect). It is kept apart so the finished review stays complete and step 8 keeps using it.
- **Undecided:** whether the chart set should then be re-chosen by event reach (it is still the 60 widest by moment reach). Not changed.

### Step 9, round 15 (2026-11-17): first-hour figures count from the third country

- **Decision:** for the opening and the chart shocks, "within 60 min" and "minutes to half" now count from the **third country's first trend** in the event window, the same reference as the global-moment rule. Event reach (countries in the window) is unchanged. Rows before the reference count as minute 0.
- **Why:** with the moment start as reference, 17 chart shocks looked slow only because one or two countries trended early. Examples: Chuck Norris 2 of 116 within 60 min (81 countries by 3 h), ChatGPT 18 Nov 2025 1 of 100, Rob Reiner 4 of 99, Roblox 1 of 96 (round 14).
- **Code:** `events.from_third` / `events.metrics`. In `opening.json`, `within_60_min` and `minutes_to_half` use the third country, a new field `third_country_utc` gives the reference, and `by_country[].minutes_from_first` and `cumulative_by_10_min` stay relative to the first trend. `shocks.json` → `chart_top60.reach_basis` states the basis.
- **The opening should not change:** 20 countries were already trending at the first scrape (07:50 UTC), so the third country's first trend is also 07:50.
- **`make story` is not rerun yet,** so the files on disk still show the round-14 figures.
- **Next, after your review of the 14 extra shocks and their event groups:**
  1. re-choose the chart's 60 by event reach (among the verified shocks with reviewed event groups);
  2. rerun `make story`;
  3. show the new top 20.
- **METHODOLOGY.md** ("Moment reach and event reach") states the third-country reference, with Chuck Norris as the example.

### Step 9, round 16 (2026-11-17): the 14 extra shocks reviewed, chart re-chosen by event reach

- **Sheet 3** (`docs/shock_chart_verification_3.csv`, 14 rows): 13 unscheduled. 1 scheduled, Elon Musk 20 Jan 2025 (inauguration day), which is no longer a shock. After `make moments`: 250 hand labels apply; shock moments 595 (610 by the rule alone).
- **Extra event groups** (`docs/event_groups_review_extra.csv`): 41 accepted, 19 rejected, 52 no-effect. Step 8 now reads every `event_groups_review*.csv` file and switches to event reach only when all of them are fully decided.
- **Chart re-chosen by event reach:** the 60 hand-verified shocks with the largest event reach, among the 100 widest by moment reach. Ranks 61–100 were checked in round 14; only the 14 extra shocks could reach the old 60th place, and they are now verified and grouped. Ties go to event reach within 60 min, then moment reach. All 60 are hand-verified.
  - **Entered (8):** ChatGPT 10 Jun 2025 (80), Iran 5 Apr 2026 (77), GTA 6 (73), Taylor Swift 26 Aug 2025 (72), PlayStation Network 7 Feb 2025 (71), Kristi Noem (69), Tomorrowland (68), Jorge Costa (67).
  - **Left (8):** Roblox 19 Dec 2025 (65), Air India crash (65), Enhypen (65), Felix Baumgartner (65), Character.AI (64), Joe Biden (64), New Orleans (64), YouTube outage 15 Oct 2025 (62).
  - The 60th is now Jorge Costa (67).
- **`make story` rerun** (first-hour figures from the third country, round 15).
  - **Opening:** 120 countries, 109 within 60 min, 10 minutes to half (third country at 07:50 UTC, the same as the first trend).
  - **Shocks:** 587 in shocks.json (death 115, outage 74, other 398); 130 hand-verified.
- **Top 20 by event reach** (event reach / within 60 min / minutes to half, moment reach in brackets):

  | # | Shock | Date | Event reach | Within 60 min | Min to half | Moment reach |
  |---:|---|---|---:|---:|---:|---:|
  | 1 | ChatGPT | 2025-01-23 | 123 | 120 | 10 | (121) |
  | 2 | Diogo Jota | 2025-07-03 | 122 | 111 | 20 | (120) |
  | 3 | Pope Francis | 2025-04-21 | 120 | 109 | 10 | (101) |
  | 4 | ChatGPT | 2024-12-11 | 119 | 117 | 10 | (116) |
  | 5 | Venezuela | 2026-01-03 | 119 | 55 | 70 | (117) |
  | 6 | Hulk Hogan | 2025-07-24 | 118 | 106 | 10 | (118) |
  | 7 | Chuck Norris | 2026-03-20 | 116 | 106 | 20 | (91) |
  | 8 | Eric Dane | 2026-02-20 | 112 | 61 | 50 | (112) |
  | 9 | Ozzy Osbourne | 2025-07-22 | 110 | 104 | 10 | (110) |
  | 10 | Michelle Trachtenberg | 2025-02-26 | 110 | 95 | 30 | (110) |
  | 11 | Jimmy Carter | 2024-12-29 | 109 | 79 | 30 | (109) |
  | 12 | Val Kilmer | 2025-04-02 | 109 | 64 | 40 | (109) |
  | 13 | Gene Hackman | 2025-02-27 | 107 | 57 | 60 | (106) |
  | 14 | Diane Keaton | 2025-10-11 | 102 | 78 | 30 | (101) |
  | 15 | ChatGPT | 2025-11-18 | 100 | 55 | 40 | (86) |
  | 16 | David Lynch | 2025-01-16 | 99 | 89 | 20 | (99) |
  | 17 | Cloudflare outage | 2025-11-18 | 99 | 80 | 20 | (95) |
  | 18 | Rob Reiner | 2025-12-15 | 99 | 18 | 110 | (99) |
  | 19 | Google Gemini | 2025-01-23 | 96 | 90 | 10 | (96) |
  | 20 | Roblox | 2025-08-23 | 96 | 21 | 80 | (96) |

- **Not covered:** shocks below the 100 widest by moment reach (moment reach ≤ 52) were not checked for event reach. To reach 67 they would need 15+ extra countries from split topics.

### Step 9, round 17 (2026-11-18): Appointments chapter, preparation

**Scope:** every global moment of kind appointment (`pipeline/appointments.py`; `09_validate_shocks.py appointments`, `make appointments-prep`; step 8 chapter `appointments.json`, not run).

**Figures per moment**, the same definition as the shock chart:
- **Event reach:** main topic + accepted topics about the same event, from 2 h before the moment start to 24 h after.
- **Within 60 min and minutes to half:** from the third country's first trend.
- **Event curve:** countries started every 10 min for 6 h, from the same reference.
- **Until the appointment event groups are reviewed,** event reach uses the main topic only.

**Category rule** (first match wins):
- **Sport moments:**
  - **other sport:** the name or sport evidence matches NBA, NFL, NHL, MLB, UFC, boxing, WWE, cricket / IPL / T20, tennis (ATP, WTA, the Slams), F1 / Grand Prix, MotoGP, golf, the Olympics, rugby, cycling, darts, basketball, …; or a Wikidata description of the topic or of either side of the fixture names a non-football sport (basketball, American football, baseball, ice hockey, cricket, tennis, racing, golf, …);
  - **football:** every other sport moment.
- **Non-sport moments,** read on the name + Claude's one-line summary (shock-v2) + the moment's own searches:
  - **religious:** conclave, pope, Vatican, Ramadan, Eid, Easter, …;
  - **award/ceremony:** Oscars, Grammys, Golden Globes, Emmys, Nobel, Eurovision, Ballon d'Or, The Game Awards, "awards", "ceremony", nominations;
  - **election/politics:** elections, votes, inaugurations, speeches, debates, summits, budgets, White House / Oval Office meetings, press conferences;
  - **holiday:** Christmas, New Year, Halloween, Valentine's, Mother's Day, Black Friday, carnival, …;
  - **launch/release:** product events, film / series / game / album releases, trailers, premieres;
  - **other:** the rest.
- **First version fixed:** "olimpi…" matched the club Olimpia (Paraguay), so the Olympics now need "olympics / olimpiadas / juegos olímpicos / …"; meetings and press conferences were added to politics.
- **Holidays are mostly rituals** (type holiday), so they rarely become appointments.

**Counts** (shown moments: not hidden, named):
- **7,286 appointments = 91.1% of the 7,999 global moments;** sport 7,120, non-sport 166.
- **By category:** football 5,880, other sport 1,240, holiday 3, award/ceremony 42, election/politics 11, launch/release 49, religious 2, other 59.

**Top 10 per category** (event reach, main topic only):
- **football:** Barcelona vs Inter 6 May 2025 (125), PSG vs Arsenal 7 May 2025 (124), Real Madrid vs Rayo Vallecano 1 Feb 2026 (123), Sevilla vs Barcelona (123), Alavés vs Real Madrid 14 Dec 2025 (123), Barcelona vs Alavés (122), Real Madrid vs Rayo 9 Mar 2025 (122), Atlético vs Barcelona 2 Apr 2025 (122), Real Madrid vs Leganés 5 Feb 2025 (122), Talavera vs Real Madrid (122).
- **other sport:** Carlos Alcaraz 8 Jun 2025 (96), NBA 20 Jun 2025 (94), Formula One 25 May 2025 (92), NBA 22 Jun 2025 (87), Jannik Sinner 13 Jul 2025 (87), Formula One 29 Jun 2025 (86), Sinner 8 Jun 2025 (82), Roland Garros 8 Jun 2025 (81), Formula One 6 Jul 2025 (81), Formula One 4 May 2025 (79).
- **holiday (3 in all):** Riccardo Muti 1 Jan 2025 (30) and Yannick Nézet-Séguin 1 Jan 2026 (26), both Vienna New Year's Concert conductors; Green Day 8 Feb 2026 (21).
- **award/ceremony:** Bianca Censori (Grammys, 102), María Corina Machado (Nobel, 67), Amy Madigan (51), No Other Land (45), Timothée Chalamet (42), Elden Ring Nightreign (42), Flow (film) (40), Olivia Dean (39), Astro Bot (39), Emilia Pérez (36).
- **election/politics:** Elon Musk 20 Jan 2025 (66), CDU/CSU 23 Feb 2025 (56), Kash Patel (42), Carrie Underwood (inauguration, 41), AfD (40), Die Linke (35), Greens (31), BSW (27), Donald Trump 16 Jun 2025 (26), Bill Clinton (inauguration, 22).
- **launch/release:** iPhone 16e (84), BTS 4 Mar 2026 (65), Samsung 30 Dec 2025 (63), Epic Games 15 May 2025 (56), Shrek 5 (56), Spotify 4 Dec 2024 (54), Steam Machine (53), Netflix 26 Nov 2025 (48), iPhone 17e (46), Epic Games 29 Apr 2025 (41).
- **religious (2 in all):** Robert Francis Prevost 8 May 2025 (68), Pope Benedict XVI 8 May 2025 (19).
- **other:** Travis Scott 11 May 2025 (83), Olivia Rodrigo 10 May 2026 (71), MetLife Stadium 13 and 9 Jul 2025 (55, 51), Pizza (51), Bibi (48), Perplexity AI (45), Volodymyr Zelensky 28 Feb 2025 (43), Heidi Klum 5 Dec 2025 (38), CNN 21 Apr 2025 (33).
- **Things to check:**
  - Green Day under holiday;
  - MetLife Stadium (Club World Cup final days) and Zelensky's Oval Office meeting under other;
  - Elon Musk 20 Jan 2025 under politics (hand-labelled scheduled: inauguration day).

**Top 20 by event reach** are all football. The widest is Barcelona vs Inter, 6 May 2025 (125). Football's first-hour figures are low (Barcelona vs Inter: 17 within 60 min, 90 minutes to half), because a fixture trends for hours before kickoff and countries join gradually.

**Chart set**, stratified: the top 10 football and the top 5 of each other category (holiday and religious have only 3 and 2), 40 moments.
- **Event-group candidates:** `docs/event_groups_review_appointments.csv` (git-ignored). Same format and no-effect rule as the shocks; 164 candidates, **77 to review**, 87 no-effect.
- **The two chapters switch separately:** the shock chapter now reads only its own review files (`events.SHOCK_REVIEW_FILES`) and the appointments chapter only `event_groups_review_appointments.csv` (`events.APPOINTMENT_REVIEW_FILES`), so an unreviewed appointments file can't switch the shocks back to moment reach.
- **Verification:** 12 of the 40 are already hand-labelled (verified). `docs/appointment_chart_verification.csv` (git-ignored, same columns and helper links, empty labels) holds the other **28**; its key `appointment_chart_verification_key.csv` has the category and Claude's label. Its labels join the hand-label overrides (`kinds.HAND_SHEETS`) on the next `make moments`.
- **`appointments.json`** (dry run only): counts, category rule, the chart set with curves, and the top 20 by event reach; monthly files `appointments/YYYY-MM.json` carry every moment with its curve (19 files, largest 108 kB). `verified` = hand-labelled scheduled. STORY_NUMBERS gets an "Appointments" section on the next `make story`.

**Surprise inside an appointment** (`work/appointment_surprises.csv`, local): 29 global moments hand-labelled scheduled with type viral_celebrity or other.
- **How the appointment is matched:** an appointment-kind moment (reach ≥ 10) starting from 12 h before to 6 h after, whose name the moment's own searches or Claude's summary contain. No guessing by time.
- **Matched (8):**
  - Travis Scott 11 May 2025 → FC Barcelona (El Clásico day);
  - Olivia Rodrigo 10 May 2026 → FC Barcelona;
  - Flow (film) → Oscars 2025;
  - Mick Jagger → Oscars 2025;
  - Adam Sandler → Timothée Chalamet (Oscars night);
  - Taylor Swift 9 Feb 2025 → Super Bowl;
  - Iceland at Eurovision 2025 → Eurovision 2025;
  - Erika Vikman → Eurovision.
- **Not matched (21),** among them:
  - Robert Francis Prevost: the papal election is the moment itself;
  - María Corina Machado (Nobel day);
  - Amy Madigan, Robert Redford and Diane Keaton on 15–16 Mar 2026 (Oscars night);
  - Heidi Klum, Rio Ferdinand and Nicole Scherzinger on 5 Dec 2025 (World Cup draw);
  - "2026 Grammy Award nominations".
  - Their ceremonies either have no appointment moment of reach ≥ 10 or aren't named in their searches; the list keeps Claude's summary for checking.

### Step 9, round 18 (2026-11-18): appointments counted by scheduled event

**Why:** by topic, the award top 5 were people and films, and the German election appeared as five parties. Non-sport appointments are now counted by **scheduled event** (`appointments.CATALOGUE`, `assign_events`, `event_units`).

**Rule:**
- **Catalogue:** a hand-made list of 38 scheduled events, each with a UTC window (the event day, or the night of a ceremony across midnight UTC), a category and a pattern.
- **Assignment:** a moment joins an event when it starts inside the window and its text matches the pattern. The text is the name + Claude's one-line summary + the moment's own searches; for sport moments, the name + phrasings.
- **Sport moments:** ceremony, election, launch and religious events take only non-sport moments; an "Olympique Lyonnais" match had joined the Olympics closing ceremony. Finals, draws and the Super Bowl take both.
- **Finals and draws split across topics are grouped the same way:** the Champions League final 2025 is Doué, Hakimi, Kvaratskhelia, Mayulu, Donnarumma, Acerbi, Linkin Park and others; the World Cup 2026 draw is Heidi Klum, Rio Ferdinand and Nicole Scherzinger.
- **Every other appointment moment is its own unit** (a match, a trailer).
- **Left out:** holidays (in Rituals: the Vienna New Year's Concert × 2 and one other), and 48 non-sport moments of category "other" whose event is unclear (players on match days, earnings reports, Travis Scott and Olivia Rodrigo, MetLife Stadium on non-final days, Zelensky, Robert Redford and Diane Keaton on Oscars night 2026 without Oscars in their searches, …).
- **Event reach:** countries where any topic of the event trended in its window; within 60 min, minutes to half and the 10-minute curve over 6 h from the third country's first trend.
- **Other-sport rule extended:** NBA, NFL and IPL side names (Lakers, Celtics, Knicks, …, Chiefs, Eagles, …, Mumbai Indians, Delhi Capitals, …). "Celtics vs Lakers" and "Mumbai Indians vs Delhi Capitals" had been football; "New York Red Bulls" is excluded from "Bulls".

**Counts:**
- **7,236 appointment moments in events** = 90.3% of the 8,014 global moments (sport 7,120, non-sport 116). They make **7,165 events**: 38 catalogue events and 7,127 single-moment units.
- **Events by category:** football 5,753, other sport 1,344, award/ceremony 21, election/politics 5, launch/release 41, religious 1, other 0.

**Catalogue events found** (event reach; number of moments):
- **football:** Club World Cup final 2025 113 (11), Europa League final 2025 98 (4), Champions League final 2025 93 (12), World Cup 2026 draw 47 (3).
- **other sport:** Roland Garros men's final 2025 101 (3), Wimbledon men's final 2025 89 (2), Super Bowl LIX 57 (2), Super Bowl LX 46 (4).
- **award/ceremony:** Grammys 2025 92 (2), Nobel Peace Prize 2025 67 (1), Oscars 2025 62 (7), Oscar nominations 2025 57 (2), The Game Awards 2024 54 (3), Oscars 2026 51 (1), Grammys 2026 41 (2), Eurovision 2026 final 35 (6), Grammy nominations 2026 34 (1), Nobel Literature 2025 32 (1), Eurovision 2025 semi-final 1 30 (2), Eurovision 2025 final 30 (5), Winter Olympics 2026 opening ceremony 29 (3), The Game Awards 2025 28 (3), Eurovision 2025 semi-final 2 23 (3), Eurovision 2026 semi-final 1 23 (1), Victoria's Secret Fashion Show 2025 21 (1), Eurovision 2026 semi-final 2 20 (2), Winter Olympics 2026 closing ceremony 19 (1).
- **election/politics:** German federal election 2025 71 (5), Trump inauguration 2025 68 (3), G7 summit 2025 20 (1), Polish presidential election 2025 19 (1).
- **launch/release:** Apple event Feb 2025 (iPhone 16e) 83 (1), Spotify Wrapped and year-end recaps 2024 63 (2), Stranger Things 5 release 48 (1), Apple event Mar 2026 (iPhone 17e) 47 (2), Spotify Wrapped and year-end recaps 2025 42 (2), Stranger Things 5 finale 31 (1).
- **religious:** Conclave 2025 (Pope Leo XIV) 72 (2).

**Top 10 per category** (all units):
- **football:** Barcelona vs Inter 6 May 2025 (125), PSG vs Arsenal (124), Real Madrid vs Rayo 1 Feb 2026 (123), Sevilla vs Barcelona (123), Alavés vs Real Madrid 14 Dec 2025 (123), Barcelona vs Alavés (122), Real Madrid vs Rayo 9 Mar 2025 (122), Atlético vs Barcelona (122), Real Madrid vs Leganés (122), Talavera vs Real Madrid (122). The Club World Cup final (113) is below the top 10 single matches.
- **other sport:** Roland Garros men's final 2025 (101), NBA 20 Jun 2025 (94), Formula One 25 May 2025 (92), Wimbledon men's final 2025 (89), NBA 22 Jun 2025 (87), Formula One 29 Jun (86), 6 Jul (81), 4 May (79), Warriors vs Timberwolves 13 May 2025 (79), Formula One 20 Apr (78).
- **award/ceremony:** Grammys 2025 (92), Nobel Peace 2025 (67), Oscars 2025 (62), Oscar nominations 2025 (57), The Game Awards 2024 (54), Oscars 2026 (51), Grammys 2026 (41), Eurovision 2026 final (35), The Game Awards nominations 17 Nov 2025 (35), Grammy nominations 2026 (34).
- **election/politics (5 in all):** German federal election 2025 (71), Trump inauguration 2025 (68), Kash Patel's confirmation vote (42), G7 summit 2025 (20), Polish presidential election 2025 (19).
- **launch/release:** Apple Feb 2025 (83), BTS 4 Mar 2026 (65), Samsung 30 Dec 2025 (63), Spotify Wrapped 2024 (63), Epic Games 15 May 2025 (56), Shrek 5 trailer (56), Steam Machine (53), Stranger Things 5 release (48), Apple Mar 2026 (47), Spotify Wrapped 2025 (42).
- **religious (1):** Conclave 2025 (72).

**Chart set, by event:** the top 10 football events and the top 5 events of each other category (31 events: religious has 1, other none).
- **`docs/event_groups_review_appointments.csv`** (regenerated, git-ignored): candidates per event (topics in the event window whose name matches any member topic, not already members), same format and no-effect rule. 215 candidates, **110 to review**, 105 no-effect. It is keyed by `event_id`; `events.load_groups` reads it per event.
- **`docs/appointment_chart_verification.csv`** (regenerated, git-ignored): one row per chart event (its widest moment; catalogue events show the event name). 10 events already have a hand-labelled member (verified); **21 to label**. Existing labels would be kept (there were none). The key has `event_id`, the event, the category and its member moments.

**Step 8** (`appointments.json` and monthly `appointments/YYYY-MM.json`, dry run only) now works by event: counts, the catalogue, the chart events with curves, and the top 20 events. A dry run gave 7,165 events (catalogue fix applied after it) and `appointments.json` at 40 kB.

### Step 9, round 19 (2026-11-18): hand-labelled scheduled moments join catalogue events

- **Rule** (`appointments.assign_events`): after the pattern pass, a moment hand-labelled **scheduled** that starts inside a catalogue event's window joins that event even without the event's name in its searches, but only if its hand event type fits the event's category (`HAND_TYPE_FITS`):
  - other and viral_celebrity → award/ceremony, religious, election/politics;
  - politics_conflict → election/politics;
  - launch → launch/release;
  - sport → football or other sport, and only an event of the moment's own sport category.
  - The sport / non-sport restriction still applies. If windows overlap, the first fitting event in catalogue order wins.
- **Why the type check:** without it, the window alone also pulled in Isco and Álex Baena (hand type sport, the Nations League final night) into the Roland Garros final, Epic Games (launch) into Eurovision 2025 semi-final 2, Perplexity AI (launch) into the Oscar nominations 2025, and Donald Trump on 8 May 2025 (politics_conflict) into the Conclave.
- **Result, 4 moments join:**
  - Oscars 2026: Robert Redford and Diane Keaton (3 moments, reach 51 → 53);
  - Eurovision 2026 final: Moldova (7 moments, reach 35 → 36);
  - Champions League final 2025: "William Saliba vs Pacho", a hand-labelled football moment that night (13 moments, reach stays 93).
- **The chart set is unchanged** (the same 31 events, members and reach), so `docs/event_groups_review_appointments.csv` and `docs/appointment_chart_verification.csv` were **not regenerated**.

### Step 9, round 20 (2026-11-20): appointment chart verified, story rebuilt

- **Your review:**
  - **Verification sheet** (21 rows): 19 scheduled; G7 summit 2025 and "Spotify Wrapped and year-end recaps 2024" unscheduled.
  - **Event groups** (`event_groups_review_appointments.csv`): 62 accepted, 48 rejected, 105 no-effect.
- **Rejected events leave Appointments** (`appointments.rejected_events`): a catalogue event whose verification row is labelled unscheduled is dropped as a whole. Its labelled moment also becomes a shock in step 4 through the hand-label override. Without the rule, Spotify Wrapped 2024 would have stayed through its other member, Apple Music Replay.
- **`make moments`:** 271 hand labels apply; shock moments 597 (610 by the rule alone).
- **`make story`:** `appointments.json` uses the reviewed event groups.
  - **Appointments:** 7,237 appointment moments in events (90.5% of 7,999 global moments; sport 7,120, non-sport 117) form 7,162 events (36 catalogue events).
  - **Events by category:** football 5,752, other sport 1,344, award/ceremony 21, election/politics 4, launch/release 40, religious 1.
  - **Left out:** 3 holiday moments and 45 unclear non-sport moments.
- **Chart set: 30 events, 29 verified.**
  - **Football:** Barcelona vs Inter 6 May 2025 (125), PSG vs Arsenal (124), Real Madrid vs Rayo 1 Feb 2026 (123), Sevilla vs Barcelona (123), Alavés vs Real Madrid 14 Dec 2025 (123), Barcelona vs Alavés (122), Real Madrid vs Rayo 9 Mar 2025 (122), Atlético vs Barcelona (122), Real Madrid vs Leganés (122), Talavera vs Real Madrid (122).
  - **Other sport:** Roland Garros men's final 2025 (104), NBA 22 Jun 2025 (101), NBA 20 Jun 2025 (100), Formula One 25 May 2025 (92), Wimbledon men's final 2025 (90).
  - **Award/ceremony:** Grammys 2025 (97), Nobel Peace Prize 2025 (69), Oscars 2025 (62), Oscar nominations 2025 (57), The Game Awards 2024 (54).
  - **Election/politics** (4 left): German federal election 2025 (71), Trump inauguration 2025 (68), Kash Patel's confirmation vote (42), Polish presidential election 2025 (20).
  - **Launch/release:** Apple event Feb 2025 (83), Samsung 30 Dec 2025 (66), BTS 4 Mar 2026 (65), Epic Games 15 May 2025 (57), **Shrek 5 trailer (56, unverified)**.
  - **Religious:** Conclave 2025 (76).
- **Open:** Shrek 5 replaced Spotify Wrapped 2024 in launch/release. It has no hand label and its event-group candidates were not in the review. The chart's numbers for it are the main topic only.
- **Slow first-hour figures** for some scheduled events, counted from the third country in the window, which starts up to 2 h before (or the catalogue window): Roland Garros final 6 within 60 min (200 min to half), Wimbledon final 5 (200), Alavés vs Real Madrid 4 (150), Oscars 2025 11 (130). Countries search ahead of the event and keep joining through it; this is the appointment pattern, not an error.

### Step 9, round 21 (2026-11-20): old Appointments chapter removed; Shrek 5; Winter Olympics and Super Bowls

**1. One Appointments chapter.** The original step-8 chapter (section 4: hand-picked El Clásicos, Super Bowls, Club World Cup, holidays, with a 10-day build-up) also wrote `appointments.json` and was overwritten by the event-based chapter, which left 16 stale keys in STORY_NUMBERS. It is removed; the event-based chapter (5b) is the only writer. `make story` was rerun to regenerate STORY_NUMBERS.

**2. Shrek 5 trailer** (27 Feb 2025, event reach 56; entered launch/release when Spotify Wrapped 2024 dropped out):
- **Verification:** `docs/appointment_chart_verification_2.csv` (one row, same columns and links; key `_2_key`).
- **Event-group candidates:** `docs/event_groups_review_appointments_2.csv`: 4 candidates, all no-effect ("shrek 5 teaser trailer", "shrek 5 dreamworks", "shrek 5 ne zaman", "shrek 5 uscita"), so nothing to review.
- **Wiring:** the `_2` labels join the hand-label overrides (`kinds.HAND_SHEETS`), and an unscheduled label drops the event (`appointments.rejected_events`). The appointments chapter uses event groups once the main review file is decided; follow-up review files add their accepted rows as they are decided (`events.APPOINTMENT_REVIEW_FILES`).

**3. Winter Olympics 2026 and Super Bowls LIX / LX** (analysis only; the chart set is not changed).
- **Coverage gap:** Appointments contains only **global** moments (15+ countries within 60 min of the third). Most topics of these events spread over the day and are not global moments, so the chapter barely sees them.
- **Super Bowl LIX** (window 9 Feb 2025 06:00 – 10 Feb 08:00 UTC):
  - **Global moments in the chapter:** only NFL (42) and Taylor Swift (37), grouped as catalogue event "Super Bowl LIX" (event reach 57).
  - **Not global:** Super Bowl (55), Kendrick Lamar (56), Travis Kelce (47), Jalen Hurts, Saquon Barkley, Jon Batiste, Patrick Mahomes, Lady Gaga, "Super Bowl LIX halftime show", "Philadelphia Eagles", and others.
  - **The catalogue window started at 18:00,** after the 12:30 "Super Bowl" moment.
  - **Grouped as one event** (all Super Bowl, NFL, team, player and halftime topics in the window): **106 countries**, which would rank **1st in other sport** (current 1st: Roland Garros final 2025, 104).
- **Super Bowl LX** (window 8 Feb 2026 06:00 – 9 Feb 08:00 UTC):
  - **In the chapter:** NFL (20), Ricky Martin (31), Green Day (21) and Charlie Puth (17), grouped as "Super Bowl LX" (46).
  - **Not global:** Bad Bunny (60), Sam Darnold (23), "Super Bowl LX winner", "Bad Bunny Super Bowl halftime show", Seahawks, Patriots.
  - **A topic named "Super Bowl LIX"** trends that day in 52 countries: a merge of plain "super bowl" searches across years.
  - **Grouped:** **95 countries**, **4th in other sport** (after 104, 101, 100).
- **Winter Olympics 2026 opening ceremony** (window 6 Feb 15:00 – 7 Feb 06:00 UTC):
  - **In the chapter:** Charlize Theron, Laura Pausini and Sabrina Impacciatore, grouped as "Winter Olympics 2026 opening ceremony" (29). Predazzo is a sport moment of its own.
  - **Not in the chapter:** Mariah Carey (23, not global), San Siro, "Opening ceremony of the 2026 Winter Olympics".
  - **Grouped:** ceremony, performer and Games topics give **43 countries**, or 45 with sport-event topics such as Predazzo and the 2028 / 2030 Games. That ranks **7th in award/ceremony** (5th place: The Game Awards 2024, 54).
- **Winter Olympics 2026 overall** (4–23 Feb):
  - **In the chapter:** almost none of it. The sport topics are not global moments: "2026 Winter Olympics ice hockey" 106 countries, alpine skiing 105, snowboarding slopestyle 101, …
  - **Grouped over the Games:** **118 countries**. The **best single day is 11 Feb, 110 countries**, which would rank **1st in other sport**. Four days pass 100: 11 Feb (110), 14 Feb (102), 17 Feb (101) and 18 Feb (103).
- **Options (not done):**
  - widen the two Super Bowl catalogue windows and let catalogue events take non-global appointment moments of their topics;
  - add "Winter Olympics 2026" as a multi-day catalogue event ranked by its best day.

### Step 9, round 22 (2026-11-20): catalogue events take every trend in their window; Super Bowls; Winter Olympics

**The global-moment rule favors fast events.** A moment is global only if 15 countries start it within an hour of the third, which suits shocks and kickoffs. Appointments that build up over the day fall short: on Super Bowl day 2025, "Super Bowl" (55), Kendrick Lamar (56) and Travis Kelce (47) were never global moments, and the Winter Olympics' sport topics (ice hockey 106, alpine skiing 105) spread over the day. Event reach (all accepted topics, the event's window) corrects this for appointments.

**1. Catalogue events take every trend of their topics inside the window** (`appointments.extra_members`), for all catalogue events.
- **Who joins:** besides global appointment moments, any other moment that overlaps the window and whose name or phrasings match the event's pattern, with the same sport / non-sport rule. It must have reach ≥ 5 (`EXTRA_MIN_REACH`), not be a shock, and not be hidden or junk. These moments only join catalogue events, never become single units.
- **Result:** 391 more members, all non-global moments, counted separately (`counts.non_global_members_of_catalogue_events`). The share of global moments stays global-only: 7,237 of 7,999 (90.5%), sport 7,120, non-sport 117. That gives 7,152 events.
- **Generic patterns tightened** before widening the pool:
  - German election: "bundestagswahl", "german (federal) election", "wahl 2025", "wahlergebnis", "hochrechnung" and the party names, no bare "election" / "wahl";
  - Polish election: "wybory", "polish", "poland", the candidates;
  - G7: "g7" only.

**2. Super Bowls.**
- **Windows** now cover the whole day: LIX 9 Feb 2025 00:00 – 10 Feb 08:00 UTC, LX 8 Feb 2026 00:00 – 9 Feb 08:00 UTC, so both include pregame, game and halftime.
- **Patterns** add players, teams and halftime acts (Mahomes, Jalen Hurts, Kelce, Saquon, SZA, Jon Batiste; Darnold, Drake Maye).
- **Year-named Super Bowl topics are assigned by date:** a topic named "Super Bowl LIX" that trends on Super Bowl LX day (a merge of plain "super bowl" searches across years) counts for the event whose window its trends fall in, and is shown as "Super Bowl (searches that day)".
- **Result:** Super Bowl LIX **106** countries (23 moments), Super Bowl LX **96** (20).

**3. Winter Olympics 2026 as a multi-day event** (`MULTI_DAY`, `figures_multi_day`): window 4–22 Feb 2026 (to 23 Feb 00:00 UTC), category other sport, pattern on Olympic names in several languages (not "Olympique").
- **Ranked by its best UTC day; total reach over the Games as a second number;** flagged `multi_day`.
- **Result:** best day **11 Feb, 109 countries**; **119 over the Games**; 72 moments.
- The hand-labelled window join (round 19) is skipped for multi-day events.

**4. Chart set rebuilt** (30 events, 25 verified). New: Club World Cup final, Europa League final, Champions League final, Winter Olympics, Super Bowl LIX, Grammys 2026, Oscars 2026, Eurovision 2025 final, Spotify Wrapped 2025, Stranger Things 5 release and finale. Out: NBA 20 Jun, Formula One, Nobel Peace, Oscar nominations, Game Awards 2024, BTS, Epic Games, Shrek 5 and others.
- **Top 5 per category:**
  - football: Barcelona vs Inter (125), Club World Cup final 2025 (125, 23 moments), Europa League final 2025 (125, 10), PSG vs Arsenal (124), Champions League final 2025 (124, 41);
  - other sport: Winter Olympics 2026 (109 best day, 119 total), Super Bowl LIX (106), Roland Garros final 2025 (105), Wimbledon final 2025 (103), NBA 22 Jun 2025 (101); Super Bowl LX (96) is 7th;
  - award/ceremony: Grammys 2025 (102), Grammys 2026 (84), Oscars 2026 (81), Eurovision 2025 final (73), Oscars 2025 (70);
  - election/politics: Trump inauguration 2025 (78), German federal election 2025 (78), Kash Patel (42), Polish presidential election 2025 (20);
  - launch/release: Spotify Wrapped and year-end recaps 2025 (104), Stranger Things 5 release (86), Stranger Things 5 finale (85), Apple event Feb 2025 (85), Samsung 30 Dec 2025 (66);
  - religious: Conclave 2025 (115, 26 moments).
- **Follow-up files** (new chart events only; existing sheets and review files are never rewritten, because they hold hand labels and decisions):
  - `docs/appointment_chart_verification_3.csv`: 5 to label (Europa League final 2025, Grammys 2026, Spotify Wrapped 2025, Stranger Things 5 release, Stranger Things 5 finale);
  - `docs/event_groups_review_appointments_3.csv`: 697 candidates for 13 events, **60 to review**, 637 no-effect.
  - The loaders read every numbered follow-up file; `HAND_SHEETS` and `rejected_events` cover `appointment_chart_verification_*.csv`.
  - Sevilla vs Barcelona and Kash Patel appear in `_3` only because they had no candidates before; their rows are no-effect.
- **Open: first-hour figures for whole-day windows.** For catalogue events, "within 60 min" and "minutes to half" count from the third country's first trend in the window, which can be hours before the event: Super Bowl LIX 12 within 60 min and 1,030 minutes to half, Winter Olympics best day 610, German election 580, Trump inauguration 520. They describe the day's build-up, not the event's spread. Counting from each event's scheduled start time (kickoff, ceremony start) would fix it; not done.
- **Not covered:** shocks below the chart, Shrek 5 (now out of the chart; its one-row sheet stays).

### Step 9, round 23 (2026-11-21): timing from each catalogue event's scheduled start

**Rule** (`appointments.START_TIMES`, `timing_from_start`):
- **Catalogue events** count their timing from a scheduled start, entered by hand with a cited source each (sources read 2026-11-20/21). The figures are:
  - **anticipation:** countries whose first trend in the window is before the start;
  - **by 60 min after the start:** cumulative, including the anticipation;
  - **new in the first hour;**
  - **minutes to half:** minutes from the start until half of the event-reach countries trended; 0 if half were already there before the start;
  - **event reach:** countries by the end of the window.
  - The curve is [minutes after the start, countries] every 10 min for 6 h.
- **Multi-day events** (Winter Olympics) time from the opening ceremony start and keep best day / total for reach.
- **Football matches outside the catalogue:** reach only, no timing (no kickoff times from a reliable source).
- **Other single-moment units** keep the third-country basis; `timing_basis` says which applies.
- **Chart ranking** keeps the third-country count as its tie-break (`rank_reach_60`), so the chart set is unchanged.

**Start times and sources** (UTC; all times as stated by the source):
- **Wikipedia** (verbatim text):
  - Super Bowl LIX 2025-02-09 23:30 (kickoff 5:30 p.m. CT) and Super Bowl LX 2026-02-08 23:30 (3:30 p.m. PT);
  - Europa League final and Champions League final 2025, 19:00 (21:00 UTC+2);
  - Club World Cup final 2025-07-13 19:00 (3 p.m. EDT);
  - World Cup 2026 draw 2025-12-05 17:00 (12:00 UTC−5);
  - Eurovision 2025 and 2026 finals 19:00 (21:00 CEST);
  - Winter Olympics opening ceremony 2026-02-06 19:00 (20:00 CET) and closing ceremony 2026-02-22 19:30;
  - Polish presidential election 2025-05-18 19:00 (polls close 21:00 CEST);
  - Conclave 2025-05-08 16:07 (white smoke 6:07 p.m. CEST).
- **Wikipedia, from the fetch tool's page summary rather than verbatim text** (flagged in `start_note`): Eurovision 2025 and 2026 semi-finals, 19:00 (21:00 CEST).
- **Official and news sources:**
  - **Trump inauguration:** 2025-01-20 17:00, oath scheduled at noon ET (NPR).
  - **German federal election:** 2025-02-23 17:00, polls close 18:00 CET (Bundeswahlleiterin).
  - **Grammys:** 2025-02-03 01:00 (CBS News) and 2026-02-02 01:00 (grammy.com), both 8 p.m. ET.
  - **Oscars:** 2025-03-03 00:00 (Academy press office) and 2026-03-15 23:00 (ABC News), both 7 p.m. ET.
  - **Oscar nominations 2025:** 2025-01-23 13:30, 8:30 a.m. ET (Forbes).
  - **Grammy nominations 2026:** 2025-11-07 16:00, 11 a.m. ET (grammy.com).
  - **Nobel Literature 2025:** 2025-10-09 11:00, 13:00 CEST at the earliest; **Nobel Peace 2025:** 2025-10-10 09:00, 11:00 CEST (nobelprize.org).
  - **Game Awards:** 2024-12-13 01:00 (GameSpot) and 2025-12-12 01:00 (Windows Central), both main show 8 p.m. ET.
  - **Victoria's Secret Fashion Show 2025:** 2025-10-15 23:00, 7 p.m. ET (Forbes).
  - **Stranger Things 5:** release 2025-11-27 01:00 and finale 2026-01-01 01:00, both 5 p.m. PT (Forbes).
  - **Apple event Feb 2025:** 2025-02-19 16:00, 8 a.m. PT (TechRadar live blog; MacRumors posted 8:02 PST).
  - **Roland Garros final:** 2025-06-08 13:00, not before 15:00 CEST (ATP).
  - **Wimbledon final:** 2025-07-13 15:00, not before 16:00 BST; it started 16:10 (ATP).
  - The URLs are in `START_TIMES` and in `appointments.json` (`start_source`).
- **No cited start, so no timing:**
  - Spotify Wrapped 2024 and 2025: Spotify published no time; one blog citing the BBC gives 13:00 GMT for 2025, which was not used;
  - Apple event Mar 2026 (iPhone 17e);
  - G7 2025 (dropped).

**Results:** anticipation / by 60 min after the start / minutes to half / event reach.

| Event | Anticipation | By +60 min | Min to half | Reach |
|---|---:|---:|---:|---:|
| Champions League final 2025 | 121 | 122 | 0 | 124 |
| Europa League final 2025 | 115 | 124 | 0 | 125 |
| Club World Cup final 2025 | 112 | 125 | 0 | 125 |
| Super Bowl LIX | 97 | 106 | 0 | 106 |
| Winter Olympics 2026 (from the opening ceremony) | 87 | 94 | 0 | 109 best day, 119 total |
| Super Bowl LX | 76 | 90 | 0 | 96 |
| Trump inauguration 2025 | 74 | 76 | 0 | 78 |
| Grammys 2025 | 71 | 76 | 0 | 102 |
| Grammys 2026 | 63 | 70 | 0 | 84 |
| Stranger Things 5 release | 53 | 69 | 0 | 86 |
| German federal election 2025 | 47 | 67 | 0 | 78 |
| World Cup 2026 draw | 39 | 74 | 0 | 98 |
| Victoria's Secret Fashion Show 2025 | 39 | 46 | 0 | 52 |
| Eurovision 2025 final | 37 | 56 | 0 | 73 |
| Eurovision 2026 final | 36 | 47 | 0 | 61 |
| Oscars 2026 | 34 | 60 | 10 | 81 |
| Eurovision 2025 / 2026 semi-final 1 | 34 / 34 | 44 / 40 | 0 / 0 | 44 / 42 |
| Wimbledon final 2025 | 32 | 96 | 10 | 103 |
| The Game Awards 2024 / 2025 | 30 / 28 | 41 / 36 | 0 / 0 | 58 / 51 |
| Oscars 2025 | 28 | 49 | 20 | 70 |
| Stranger Things 5 finale | 23 | 63 | 0 | 85 |
| Roland Garros final 2025 | 22 | 81 | 20 | 105 |
| Conclave 2025 | 16 | 103 | 3 | 115 |
| Eurovision 2025 / 2026 semi-final 2 | 11 / 9 | 35 / 22 | 10 / 20 | 38 / 31 |
| Polish presidential election 2025 | 11 | 20 | 0 | 20 |
| Nobel Peace Prize 2025 | 7 | 54 | 10 | 70 |
| Apple event Feb 2025 | 6 | 55 | 40 | 85 |
| Oscar nominations 2025 | 5 | 41 | 30 | 57 |
| Olympics opening / closing ceremony | 5 / 5 | 20 / 19 | 30 / 0 | 29 / 20 |
| Grammy nominations 2026 | 2 | 18 | 90 | 43 |
| Nobel Literature 2025 | 1 | 29 | 10 | 34 |

- **Reading the table:** finals, Super Bowls, award nights and elections are mostly *anticipated*: most of their countries trend before the start, so half are reached before it begins (minutes to half 0). Announcements nobody can watch in advance are not: the conclave (16 before the white smoke, 103 within the hour), the Nobel prizes, the Apple event and the Oscar and Grammy nominations.
- The Spotify Wrapped 2025 chart event has reach only (104).

### Step 9, round 24 (2026-11-21): sheet 3 labelled; all 30 chart events verified

- **Labels:**
  - **Sheet 3:** Europa League final 2025, Grammys 2026 and Stranger Things 5 release and finale are scheduled. Spotify Wrapped 2025 is **unscheduled**, so it leaves Appointments (`rejected_events`).
  - **Shrek 5** (sheet 2) is unscheduled, so it is dropped too; it was already outside the chart.
  - **Review 3:** 45 accepted, 15 rejected, 637 no-effect.
- **Fix:** step 4 recorded hand labels only on global moments, so four sheet-3 labels never applied: the widest member of a catalogue event can be a non-global moment (round 22). Step 4 now records `hand_scheduled` / `hand_event_type` on every labelled moment (277 of 277 labels; 272 global). The sport and shock overrides still apply to global moments only.
- **Rebuilt** (`make moments`, appointments stage, `make story`):
  - **Chart set:** 30 events, **all 30 verified**. **No new sheet:** the only chart events new to the review files (Sevilla vs Barcelona, Kash Patel) had no candidates, and none was unlabelled.
  - **Launch/release:** BTS (65) replaces Spotify Wrapped 2025.
  - **Final chart:**
    - **football:** Barcelona vs Inter (125), Club World Cup final 2025 (125), Europa League final 2025 (125), PSG vs Arsenal (124), Champions League final 2025 (124), Real Madrid vs Rayo 1 Feb 2026 (123), Sevilla vs Barcelona (123), Alavés vs Real Madrid (123), Barcelona vs Alavés (122), Real Madrid vs Rayo 9 Mar 2025 (122).
    - **other sport:** Winter Olympics 2026 (109 best day, 119 total), Super Bowl LIX (106), Roland Garros final (105), Wimbledon final (103), NBA 22 Jun 2025 (101).
    - **award/ceremony:** Grammys 2025 (102), Grammys 2026 (84), Oscars 2026 (81), Eurovision 2025 final (74), Oscars 2025 (70).
    - **election/politics:** Trump inauguration (78), German federal election (78), Kash Patel (42), Polish presidential election (20).
    - **launch/release:** Stranger Things 5 finale (87), Stranger Things 5 release (86), Apple event Feb 2025 (85), Samsung 30 Dec 2025 (66), BTS 4 Mar 2026 (65).
    - **religious:** Conclave 2025 (115).
  - **Counts:** 7,236 global appointment moments (90.5%), plus 391 non-global members of catalogue events; 7,151 events (36 catalogue).

### Step 9, round 25 (2026-11-21): Appointments calendar (`appointments_daily.json`)

- **File** (step 8; 32 kB): one row per UTC day of the archive, 537 days (27 Nov 2024 – 17 May 2026). Fields: `date`, `events` (appointment events that day), `widest_event`, `widest_category`, `widest_event_reach`, and `gap` (1 on the 51 collection-gap days, where counts are lower).
- **Same events as `appointments.json`:** 7,151 in total. Each event counts once, on the UTC day of its cited scheduled start (`start_utc`), else of its first moment. The multi-day Winter Olympics counts on its opening-ceremony day (6 Feb 2026). The widest event that day is the one with the largest event reach (ties: the third-country count, as in the chart).
- **Numbers** (STORY_NUMBERS): 484 of 537 days have at least one appointment event; the median is 13 per full-coverage day; the busiest day is 18 May 2025 (44 events).
- **The widest days:** Europa League final (21 May 2025), Club World Cup final (13 Jul 2025) and Barcelona vs Inter (6 May 2025), each at 125 countries.
- **Super Bowl days:** Super Bowl LIX's day (9 Feb 2025) is led by Plymouth Argyle vs Liverpool (117) ahead of the Super Bowl (106).

### Step 9, round 26 (2026-11-23): Calendar detail and reach comparison

- **`appointments_daily.json` rewritten** (167 kB). It uses the same events and day rule as before and keeps the old fields and the gap flag. New per-day fields:
  - `events_by_category`: counts for the 7 categories; the totals still sum to 7,151.
  - `widest_non_football`: name, category and event reach, or null.
  - `widest_searches`: up to 3 real searches of the widest event, in their original language. These are the phrasings trended in the most countries in the event's window; hidden sensitive topics are excluded. For the multi-day Winter Olympics the window is the whole Games.
- **`appointments.json` gains `reach_comparison`:**
  - Football: 5,752 events, median event reach 35; 1,882 reach 50+ countries, 331 reach 100+ and 25 reach 120+.
  - The 5 widest league matches, all La Liga, at 122–123: Real Madrid vs Rayo Vallecano (1 Feb 2026), Sevilla vs Barcelona, Alavés vs Real Madrid, Barcelona vs Alavés, Real Madrid vs Rayo Vallecano (9 Mar 2025).
  - Every non-sport event with event reach 40+: 27 events, led by the Conclave (115) and the Grammys 2025 (102).
  - The 5 widest other-sport events: Winter Olympics 109, Super Bowl LIX 106, Roland Garros men's final 105, Wimbledon men's final 103, NBA Finals game 7 (22 Jun 2025) 101.
- **League-match rule:**
  - A league match is a football fixture ("A vs B") outside the catalogue whose text names a domestic league ("la liga", "liga española", "premier league", "serie a" …) and no cup, European, international, friendly, final or knockout round.
  - The text is the name, Claude's summary, and the fixture's searches and Google related queries inside its window. Claude's summaries cover few football moments, and the related queries are what name the competition.
  - 1,037 of 5,752 football events pass. This is a conservative count: matches without league evidence are left out.
  - Spot checks: Real Madrid vs Leganés (5 Feb 2025, Copa del Rey) and Talavera vs Real Madrid (Copa del Rey) are excluded; so are Atlético vs Barcelona (2 Apr 2025 cup semi, no league evidence) and Kairat vs Real Madrid (Champions League).
- **Check without football** (full-coverage days):
  - 422 of 486 days (86.8%) still have an appointment event in 15+ countries.
  - The median is 2 events per day without football, against 13 with it.

### Step 9, round 27 (2026-11-23): Waves validation round

- **Claude category** (`09_validate_shocks.py waves-label`; claude-haiku-5-5 via the Batches API, prompt `wave-v1`, cached in `cache/claude/waves/`):
  - One category per wave topic, from its name, type, searches, related searches and Wikidata description: AI/tech, politics/conflict, finance/markets, entertainment/culture, people/celebrity, science/health, generic/always-on query, or other.
  - All 360 of 360 answers were valid. The run cost $0.0076, bringing total Claude spend to $3.29.
- **`waves_review.json`** (step 8): one row per wave topic. Each row has its name, up to 5 phrasings (those trended in the most countries), category with Claude's reason, months at 15+ (count and list), peak month and countries, distinct countries, `is_constant`, shock moments (count and dates), and countries for every month. A `month_coverage` block gives days collected / days per month and flags gap months.
- **Months and gaps, as the data has them:**
  - The archive spans 19 calendar months (2024-11 to 2026-05), with a 4-day November 2024 and a 17-day May 2026.
  - Gap months by `gap_days` are 2024-11, 2025-09 (21 of 30 days), 2025-12 (28 of 31) and 2026-01 (5 of 31).
- **`waves.json` gains `by_category`:** topics and country-months per category, plus the top 30 by months at 15+ and by distinct countries. The same tables come again without constant topics and generic queries.
- **Checks:**
  - (a) AI/tech is not the largest category. People/celebrity leads both by topics (91; AI/tech 44) and by country-months (20,131; AI/tech 12,192). Without constants it still leads, 86 vs 33 topics and 17,892 vs 6,487 country-months. All 19 generic topics are constants, so dropping generic changes nothing further.
  - (b) S&P 500 (8 months), Nasdaq (3) and Dow Jones Industrial Average (5) are each a single wave topic.
  - (b, continued) No tariff topic is a wave: the best, "Trump tariffs", has 15+ countries in only 1 month. The 250 tariff-matching topics taken together have 9 such months, but the wave rule is per topic, and the loose keyword match includes non-Trump tariffs.
  - (c) 110 of 360 wave topics also have at least one shock moment (220 shock moments).
- **Hand-label sheet** (`09_validate_shocks.py waves-sample`; `docs/waves_review.csv`, git-ignored):
  - It lists all 360 topics; 40 are flagged `in_sample`, drawn per Claude category (at least 2 per category, the rest proportional, seed 31).
  - Labels: real recurring story / always-on query / misgrouped topic / should be sport or ritual.
  - Claude's category is left out of the sheet so the labels stay blind. The sheet is never overwritten once labelled.

### Step 9, round 28 (2026-11-23): Waves sample scored, athlete leak fixed, clean wave set

- **Score** (`09_validate_shocks.py waves-score`; report in `docs/WAVES_VALIDATION.md`, local):
  - The 40 hand labels: 23 real recurring story, 10 always-on query, 4 misgrouped topic, 3 should be sport or ritual.
  - Real recurring stories, weighted by category size: 57% (95% CI 45–70%).
  - Claude's generic/always-on category is precise (2 of 2 are hand always-on) but catches only 2 of the 10 always-on labels. The others were Claude-categorised as entertainment/culture (3: Disney, Harry Potter, Titanic), AI/tech (2: Tesla, Epic Games), people/celebrity (2: Jennifer Lopez, Robin Williams) and other (1: The New York Times).
  - The 3 sport labels were all athletes, Claude-categorised as people/celebrity. Misgrouped: Saudi Arabia, Dubai, Fast, Solar eclipse.
- **Athlete leak** (`sport.wave_athletes`, called from `04_moments.sporty`):
  - Nick Woltemade, Dani Olmo and Prashant Veer have no Wikidata item and too few sport searches among the top 10 related searches of their strings.
  - The new check looks at the topic's top 30 related searches over all its rows. It counts fixtures, sport terms, sport entities and extra football/cricket words; 4+ signals, or one athlete-only word ("transfermarkt", "cricketer", "footballer" …), marks an athlete. At 3 signals, Justin Timberlake and Olivia Rodrigo would go too (partners and fans).
  - It removes 7 wave topics: Nick Woltemade, Dani Olmo, Prashant Veer, Gavi, Eduardo Camavinga, Dean Huijsen and Diogo Jota. Wave topics: 360 → 353.
- **Clean wave set** (`waves.json` `clean`):
  - The 353 wave topics minus 39 constants and 8 hand-dropped topics. Athletes are already out.
  - 15 topics are merged into 13 stories through a hand-reviewed list (`WAVE_MERGES_BY_NAME`). Candidates were clean topics sharing a name word; merged were the same entity or the same launch, with most 15+ months shared: iPhone 17 / 17 Pro / 17 Pro Max; iPhone 18 / 18 Pro / 18 Pro Max; PlayStation 5 / PlayStation; YouTube / YouTube outage; both Bitcoin price topics; Jeffrey Epstein / Epstein files; Claude / Claude AI; Pope Francis / Pope Francis Vatican; Rockstar Games GTA 6 / Rockstar Games; Squid Game / season 3; Samsung / Galaxy S26 Ultra; Iran / Iran–Israel war; Meta Platforms / Meta stock.
  - Kept apart: different people (Brigitte / Emmanuel Macron), different products of one maker (Sora / OpenAI), different phone generations (iPhone, 16, 17, 18) and annual rituals of a service (Spotify Wrapped / Spotify).
  - Result: 291 stories.
- **Clean-set categories:**
  - People/celebrity is still first by country-months (15,955; entertainment/culture 14,857, politics/conflict 11,258, AI/tech 5,898).
  - By stories, entertainment/culture is first (79, against 77 people/celebrity).
  - The top 30 by months at 15+ and by distinct countries carry countries per month, with the gap months listed.
- **Not dropped:** 12 unlabelled stories Claude calls generic/always-on (YouTube, Outlook, Spotify, Classroom, Flightradar24, Reddit …). The clean rule drops hand labels only.
- **Merged stories can pass 12 months:** iPhone 17 and PlayStation 5 reach 14 months at 15+ once merged, though no single topic of theirs is constant.
- **Verification sheet** (`09_validate_shocks.py waves-verify-sheet`; `docs/wave_chart_verification.csv`, local): the top 30 clean waves by months at 15+. For each month at 15+ it shows that month's searches, the related searches that are new that month, and Claude's summary of shock moments that month.

### Step 9, round 29 (2026-11-23): Clean waves without generic and merged-constant stories

- **Two rules after merging** (step 8). The clean set now also drops:
  - stories in Claude's generic/always-on category (2 of 2 were hand always-on in the sample);
  - merged stories at 12+ months at 15+ (the constant rule applied to the story).
- **14 stories removed** (`waves.json` `clean.removed_stories`; 12 generic, 3 constant, YouTube both):
  - Constant after merge: iPhone 17 (14 months; iPhone 17 + 17 Pro + 17 Pro Max), PlayStation 5 (14; + PlayStation), YouTube (12; + YouTube outage, also generic).
  - Generic: Outlook (10), Spotify (9), Classroom (8), Flightradar24 (6), Reddit (5), Downdetector (4), Google Maps, Amazon Prime, Meet, Uber and Football matches today (3 each).
- **Clean set:** 277 stories.
- **Categories:**
  - By country-months, people/celebrity is still first (15,955), ahead of entertainment/culture (14,468), politics/conflict (11,258) and AI/tech (5,395).
  - By stories, entertainment/culture is first (78), with people/celebrity at 76.
- **Top by months at 15+:** Iran, Dua Lipa and IPTV (11 each), then Samsung, Shakira, Justin Bieber, Prime Video, Meta, Sabrina Carpenter, Bitcoin price, Jason Statham and Julia Roberts (10 each).
- **Top by distinct countries:** Iran (123), Pope Francis (122), Venezuela (120), DeepSeek (117), Facebook (115).
- **Verification sheet regenerated** (it had no labels): `docs/wave_chart_verification.csv` (local), the top 30 of the new clean set. Ranks 25–30 tie at 8 months and are ordered by distinct countries.

### Step 9, round 30 (2026-11-23): Wave chart set (`waves_chart.json`)

- **Chart set** (step 8, from the local verification sheet):
  - 19 of the 30 verified stories are labelled real recurring story (10 always-on, 1 misgrouped). Venezuela and Nicolás Maduro are merged (`WAVE_CHART_MERGES`), giving 18 stories.
  - Groups (`WAVE_CHART_GROUPS`, chosen by hand):
    - pop stars (7): Dua Lipa, Shakira, Justin Bieber, Sabrina Carpenter, Ariana Grande, BTS, Demi Moore;
    - crises/politics (5): Iran, Venezuela (Nicolás Maduro), Jeffrey Epstein, Emmanuel Macron, Syria;
    - tech/companies (6): Samsung, Meta, Nintendo Switch 2, Grok, OpenAI, Nvidia stock.
- **`waves_chart.json` fields** per story: countries per month (19 months; `month_coverage` gives days collected / days and gap months), months at 15+, distinct countries, peak month, the hand notes, and the returns.
- **Returns:** every month at 15+ is a return, 167 in all. Each carries the story's biggest moment that month (most countries; date, countries, countries within 60 min, `is_global`) and its kind: shock if it is in shocks.json, appointment if it is a member of an appointment event, otherwise neither.
- **Biggest moment's kind** (shock / appointment / neither):
  - pop stars 1 / 3 / 63 of 67;
  - crises/politics 3 / 0 / 44 of 47;
  - tech/companies 12 / 4 / 37 of 53;
  - all 16 / 7 / 144 of 167 (10% / 4% / 86%).
- **Why most are "neither":** shocks and appointments are global moments (15+ countries within 60 min). Only 24 of the 167 biggest moments are global (pop stars 3, crises/politics 3, tech/companies 18); the rest are slow builds over hours or days.
  - Iran, 12 Jun 2025: 70 countries, 3 within 60 min.
  - Syria, the fall of Assad: 75 countries, 6 within 60 min.
  - Demi Moore's Golden Globe: 59 countries, 3 within 60 min.
- **Second view** (`returns_by_group_any_moment`): whether the month has any shock, else any appointment, moment of the story. It changes little: 18 / 7 / 142 overall. One change is Iran in June 2025, whose global shock (the US strikes on 22 Jun, 62 countries) is not the month's biggest moment.
- **Reading:** the waves' returns are mostly not instant global moments. Tech/companies returns are the most shock- and launch-driven (outages, Grok and OpenAI news, launches, earnings). Pop-star and crisis returns build across countries over hours or days.

### Step 9, round 31 (2026-11-24): Wave speed (`waves_speed.json`)

- **Counting, the same for every curve:**
  - Origin = the moment's start (its first country).
  - Countries where the topic set trended in the 24 h before the origin are `already_trending` and are left out.
  - The clock starts at the third new country's first trend, as in the global-moment rule.
  - The curve counts cumulative distinct new countries (the first two count at 0), every 10 min for 6 h, then hourly to 72 h.
  - `hours_to_half` = hours until half of the 72-hour total.
  - Wave stories count any topic of the story; the four shocks count their topic plus the reviewed event group; the baseline counts each moment's own topic.
- **Daily series:** the 18 chart stories, countries per UTC day over all 537 archive days (51 gap days listed).
- **Biggest returns** (72 h; 1 h / 24 h / 72 h countries and hours to half):
  - The slow ones: Iran 12 Jun 2025 (3 / 69 / 73, 5.7 h, 27 already trending), Syria (6 / 75 / 75, 11.2 h), Demi Moore (3 / 59 / 61, 6.7 h), Shakira (4 / 20 / 26, 11.8 h), Dua Lipa (3 / 16 / 25, 15.3 h) and Jeffrey Epstein (3 / 19 / 27, 16.2 h, 30 already trending).
  - The fast ones are shock-driven: Venezuela 3 Jan 2026 (54 / 120 / 120, 1.2 h), Meta (22 / 27 / 28, 0.2 h), OpenAI (27 / 29 / 41, 0.7 h), Grok (20 / 49 / 49, 1.3 h) and BTS (16 / 65 / 65, 1.5 h).
  - Iran from the US strikes, 22 Jun 2025: 50 / 68 / 70, 0.5 h.
- **Four shocks** (same counts): Pope Francis 95 / 104 / 105, 0.33 h (16 already trending at Easter); ChatGPT outage 118 / 121 / 121, 0.17 h; Diogo Jota 111 / 122 / 122, 0.33 h; Venezuela 55 / 119 / 119, 1.17 h.
- **Fair baseline:** every non-sport, non-hidden moment whose 72-hour total reaches the threshold, global or not. Median share of the 72-hour countries reached within 1 h, and median hours to half:

  | group | 50+ countries | 30+ countries |
  |---|---|---|
  | all | 851 moments: 7%, 12 h | 3,316: 11%, 11.7 h |
  | shocks | 122: 54%, 0.83 h | 324: 62%, 0.67 h |
  | appointments | 33: 17%, 2.8 h | 87: 41%, 1.5 h |
  | wave returns | 14: 8%, 3.7 h | 34: 17%, 3.8 h |
  | everything else | 688: 6%, 17.7 h | 2,885: 10%, 15.7 h |

  Quartiles and 10% histograms are in `baseline`.
- **Reading:**
  - Shocks are the fast exception, which their definition makes partly circular.
  - Most wide moments build over half a day.
  - Wave returns sit between the two: a small share within the first hour, like everything else, but half their countries within about 4 hours. That is faster than the typical slow build, because several returns are driven by shocks or launches.
  - The ordering holds at both thresholds.

### Step 9, round 32 (2026-11-24): Rituals validation round (`rituals_review.json`)

- **Rule** (pipeline/kinds.py `topic_ritual`): a topic is ritual if any of:
  - its Claude category is weather;
  - its Claude type is holiday;
  - its name matches RITUAL_RE (lotteries, prayer times, horoscopes, daily puzzles, rates, weather words, TV guide);
  - it is not sport, its type is other / product / company / unlabeled, and it has 15+ moments of 10+ countries.

  Every moment of a ritual topic is ritual unless it is a shock.
- **Ritual topics:** 13,573 not hidden with national rows. They are listed in `rituals_review/ritual_topics_1..5.json` with name, phrasings, countries, trends, peak day and proposed cycle. Proposed cycles:
  - daily 49, weekly 140, yearly 1,269;
  - unclear (sporadic) 1,897; under 5 trends 10,218.
  - The daily rule is active on 30%+ of a 60+ day span: Trending Now flags surges, so even a daily ritual misses most days.
  - 55 look like sport (27 of the 3,355 with 5+ trends): UEFA, Livescore, "Today's matches", IPL fixtures …
- **Weather clock:**
  - "Today" phrasings peak at 06:00 local (31%; 61% between 05:00 and 09:59). "Tomorrow" phrasings peak at 20:00 local (78%; 98% between 18:00 and 23:59).
  - Local time: US, CA and RU use regional feeds in each region's zone; every other country uses one zone per country.
  - Without the 14 countries with several UTC offsets (pytz: AU BR CA CD CL EC ES ID MX NZ PT RU UA US) the peaks are the same.
  - Countries' peak hour: 06:00 for 90 countries, 20:00 for 18, 07:00 for 11, 05:00 for 5. The counts barely change without the 19 UTC hour.
- **Scrapes:**
  - The archive has collection dates, not scrape times; the scraper runs once a day.
  - Proxy: the latest trend start in each day's collection. It falls at 09:00–11:00 UTC on 477 of 486 days (10:00 on 48%), so the daily run is in the UTC morning, not at 19:00.
  - Trends starting at 19:00 UTC are not more often 20 h+ (14.7% vs 13.4% median for other hours) or estimated.
  - So the 19:00 UTC excess is not a cut-off at the edge of the 24-hour window. Its cause stays open (CHECKS C4); the `utc19_bump` flag stays.
- **Weather days** (full-coverage days, 10+ countries): (a) the 22 topics named "Weather", 409 of 486 days; (a') the single "Weather" id, 294; (b) any of the 6,212 weather topics, 486. Listed: the 22 named topics and a random 40 (seed 41).
- **Holidays** (whole-topic groups by Claude topic name; topics, the two occurrences' peak days, countries in both years):
  - Ramadan: 332 topics; 28 Feb 2025 (74) / 17 Feb 2026 (75); 82 countries in both years.
  - Eid: 575; 30 Mar 2025 (81) / 20 Mar 2026 (67); 86.
  - Easter: 418; 20 Apr 2025 (83) / 5 Apr 2026 (77); 95.
  - Christmas: 1,220; 24 Dec 2024 (100) / 24 Dec 2025 (98); 107.
  - New Year: 726; 31 Dec 2024 (125) / 31 Dec 2025 (123); 125.
  - Valentine's Day: 289; 13 Feb 2025 (86) / 14 Feb 2026 (73); 106.
  - Lunar New Year: 178; 28 Jan 2025 (39) / 17 Feb 2026 (51); 54.
  - Mother's Day: 124; 11 May 2025 (68) / 10 May 2026 (72); 88.
  - Black Friday: 260; 28 Nov 2024 (42) / 27 Nov 2025 (38); 54.
  - Once in the archive: Halloween (75 topics; 31 Oct 2025, 53) and Diwali (49; 20 Oct 2025, 48).
  - Small extra peaks are false matches the labels should catch: Eid and Lunar New Year on 31 Dec 2024, Christmas on 26 Mar 2026. Occurrences use the UTC year (New Year counts New Year's Eve with the new year), and both-years is taken between the two largest.
  - Hand-label sheet: `docs/rituals_review.csv` (local, `09_validate_shocks.py rituals-sample`), 60 topics, at least 3 per holiday, the rest proportional (seed 43).
- **Cycle scan.** It covers non-sport topics only: no sport topics, athletes or mostly-sport topics, and the step-4 sport check on the candidates drops 1,256 more. It works per topic and country in local dates and hours.
  - Daily (50+ days, 60%+ at one local hour ±1): 335 topics. Weather in its many languages (06:00; tomorrow 21:00), lotteries, Wordle and NYT hints, Fajr prayer, TV channels.
  - Weekly (8+ weeks, 70%+ on one weekday): 140 topics. Lotteries on their draw days, "cuma mesajları" (Friday messages), and US/GB/CA service keywords (investments, childcare, flu shots, loans) that may be a Trending Now artifact.
  - Yearly (same local date ±1 in both years, at most 10 active days): 9,897 topics. Led by New Year's Eve (117 countries), New Year's Day, International Women's Day, Valentine's Day, Christmas, Mother's Day …
  - Some sport still passes (PGA Tour, NASCAR, Moto2, Masters Tournament).
- **"Is it down":**
  - 652 topics, 3,941 trends; 47% of them fall inside an outage shock (2 h before to 24 h after its start; 74 outage shocks).
  - All of its top 10 days match an outage. The top three: Cloudflare (18 Nov 2025, 99 countries), Cloudflare with Canva and Bet365 (5 Dec 2025, 63), X (10 Mar 2025, 60).

### Step 9 round 33: rituals labels scored, clean holiday groups, rituals.json (2026-11-24)
- **Holiday labels** (`docs/rituals_review.csv`, 60 topics from the round 32 groups; `09_validate_shocks.py rituals-score` → `work/rituals_validation.json`):
  - 54 of 60 about the holiday (90%, 95% Wilson 80–95%). Unweighted: at least 3 per holiday, the rest proportional.
  - Precision per holiday: Easter 3 of 5, Christmas 13 of 16, Eid 6 of 7; every other holiday (Ramadan 4, New Year 10, and 3 each for Halloween, Valentine's Day, Diwali, Lunar New Year, Mother's Day, Black Friday) is all about the holiday.
  - All 6 unrelated topics are people (serkan bayram, pasquale allevi, piolo pascual, natale dalla vecchia, Kerstin G, matthieu noel). The clean rule removes all 6 and none of the 54 holiday topics; 2 New Year topics move to Lunar New Year.
- **Clean holiday groups** (`08_story_export.py`, section 6b). A broad name rule per holiday, then removed in this order:
  - Wikidata place (P625 coordinates, not human), Claude type place, Wikidata human (P31 = Q5), Claude type person. P31/P625 come from a new cached lookup, `wikidata.get_p31` (`cache/wikidata/claims_p31/`; same User-Agent rule).
  - Holiday words used as names (`HOL_NAME_RE`): Bayram/Akbayram/Bayramoğlu, Ramazan (people), Pascual/Pasquale/Pascoal, Noel/Noelia/Manoel, Natale (people), Natal (the city and its clubs), KwaZulu-Natal, Kerstin/Bickerstaff, Valentina/Valentino/Valentin …
  - A holiday phrase next to the word keeps the topic (`HOL_CTX`: Père Noël, papai noel, marché de Noël, veglia pasquale, colomba pasquale, San Valentín, Valentin nap, valentinovo).
  - Other days that share the word (`HOL_OTHER_RE`): Turkish national bayrams, Nevruz, hari raya natal / nyepi / waisak, Tết Đoan Ngọ / Thanh Minh / Tết dương lịch, national women's days on other dates, and searches that only share the date "8 March" (football, horoscopes, lotteries).
  - Topics with names (people, places) removed: Ramadan 27 of 412, Eid 25 of 632, Easter 42 of 415, Christmas 136 of 1,220, Valentine's Day 176 of 294. Halloween, Diwali, Mother's Day, Black Friday, New Year and Lunar New Year lose none.
  - Removed as other days: Eid 21, Lunar New Year 14, Women's Day 30. Clean topics: Ramadan 385, Eid 586, Easter 373, Christmas 1,084, New Year 650, Valentine's Day 111, Lunar New Year 175, Women's Day 134.
- **Lunar New Year greetings.** Chinese / Lunar New Year topics, gong xi fa cai, kung hei fat choi, xin nian kuai le, capodanno cinese, año nuevo chino … move from New Year to Lunar New Year (84 topics).
- **情人節.** Chinese 情人節 / 七夕 topics stay in Valentine's Day only if their widest day is within 7 days of 14 February. 7 are removed: Qixi in August, White Day on 14 March, the 14th of other months. The topic Claude named "Qixi Festival" peaks on 14 Feb 2025 and stays.
- **Odd peaks:**
  - Eid on 2024-12-31 (16 → 6 countries): Arabic "عيد رأس السنة" (feast of the new year), named "Eid al-Nahda (New Year's Eve)" by Claude. It is now in New Year only. The 6 countries left come from an Eid greetings topic that also holds New Year greetings (the same phrase is said for both); left as is.
  - Lunar New Year on 2024-12-31 (22 → 23): real searches. At the Gregorian New Year people look up the coming Chinese New Year ("chinese new year 2025", "chinese zodiac 2025", 除夕); the same echo appears on 2025-12-31. Kept.
  - Christmas on 2026-03-26 (40 → 0): Noelia Castillo, a Spanish euthanasia case, matched "noel". Removed by the name rule.
- **International Women's Day** is added with the same outputs. 8 March: 106 countries (2025) and 109 (2026); 114 in both years.
- **Holiday windows.** Countries per UTC day from 10 days before to 5 days after each holiday date (`HOLIDAY_DATES`; Ramadan = first day of fasting; Mother's Day = second Sunday of May; Eid al-Fitr in both years plus Eid al-Adha 2025). Days outside the archive are null. Peak and countries in both years are taken within the windows:

  | Holiday | First year | Second year | Both years |
  |---|---|---|---|
  | Ramadan | 28 Feb 2025 (74) | 17 Feb 2026 (75) | 77 |
  | Eid al-Fitr | 30 Mar 2025 (81) | 20 Mar 2026 (67) | 86 |
  | Easter | 20 Apr 2025 (83) | 5 Apr 2026 (77) | 85 |
  | Christmas | 24 Dec 2024 (100) | 24 Dec 2025 (98) | 106 |
  | New Year | 31 Dec 2024 (125) | 31 Dec 2025 (123) | 125 |
  | Valentine's Day | 13 Feb 2025 (86) | 14 Feb 2026 (73) | 102 |
  | Lunar New Year | 28 Jan 2025 (40) | 17 Feb 2026 (51) | 54 |
  | Mother's Day | 11 May 2025 (68) | 10 May 2026 (72) | 75 |
  | Black Friday | 28 Nov 2024 (42) | 27 Nov 2025 (38) | 54 |
  | Women's Day | 8 Mar 2025 (106) | 8 Mar 2026 (109) | 114 |

  Once in the archive: Eid al-Adha 2025 (6 Jun, 68), Halloween (31 Oct 2025, 53), Diwali (20 Oct 2025, 48). The Black Friday 2024 window starts before the archive (27 Nov 2024).
- **"Is it down" moves to Shocks** (`shocks.json` key `is_it_down`: by day, strict phrasing by day, share inside outage shocks, top 10 days). Its topics leave the rituals review lists (13,573 → 13,565 ritual topics). Step 4 moment kinds were unchanged in this round; round 34 changes them.
- **`rituals.json` is now the chart file:**
  - Weather clock: share of trends by local hour (all, today, tomorrow) and each country's peak hour (all, today, tomorrow; today and tomorrow need 20+ trends).
  - Weather days, and the clean holiday windows.
  - The round 13 whole-topic / strict counts for Ramadan, Eid and Easter, and the "when is" series, are gone; the clean groups replace them.

### Step 9 round 34: "is it down" moments are other, not ritual (2026-11-24)
- **Rule** (`pipeline/kinds.py`):
  - `outage_topics` marks topics whose Claude name says outage / down / not working.
  - `topic_ritual` no longer counts them as ritual (no cycle).
  - `moment_kinds` makes their moments "other" unless they are a shock. Shocks still win, and appointment no longer applies to them either.
  - Step 8's "is it down" group (`shocks.json`) uses the same rule.
- **Tighter outage rule.** The old rule's "\bdown\b" also caught shot down, stepping down, shutting down, closing down, Down Syndrome Day, County Down GAA, System of a Down, 3 Doors Down, Tour Down Under, Black Hawk Down and others. These are now excluded (`OUTAGE_TOPIC_EXCLUDE_RE`): 662 → 463 topics, all on topic_meta.
- **Waves unchanged.** The wave exclusion keeps the rule from before this round (`topic_ritual(..., exclude_outage=False)`), so `is_wave` changes for no topic.
- **What moved** (rerun: moments, export, profile, checks, story):
  - 7 of 2,031,818 moments change kind: 5 ritual → other ("Apple Weather app outage" ×2, "Apple Weather app not working", "is wordle down", "this is not working strands") and 2 appointment → other ("marathon servers down", "sportsnet down world series"). All reach 1–2 countries.
  - Those 7 topics' summary kinds change the same way. No global moment changes kind.
  - The 463 outage topics now have 1,443 moments: 27 shocks, 1,416 other. Of their 34 global moments, 27 are shocks and 7 other.
- **Numbers:**
  - Shocks: "is it down" is now 463 topics, with 1,808 of 3,623 trends inside outage shocks (50%; was 652 topics, 1,839 of 3,941, 47%). Its widest day and the top 10 matches are unchanged (18 Nov 2025, 99 countries; 10 of 10).
  - Rituals: ritual topics 13,565 → 13,568. World Down Syndrome Day and other non-outage "down" topics are back in the ritual lists; yearly cycle 1,268 → 1,269, too few trends 10,211 → 10,213.
  - Every holiday, weather and other Rituals number, every shock count, CHECKS.md and PROFILE.md are unchanged.

### Step 9 round 35: two clocks, Rituals vs Shocks (2026-11-25)
- **Export:** `two_clocks.json` (`08_story_export.py` section 6c). For every country with trends in each case's window, national feeds:
  - the peak: the 10-minute step with the most trends of the case's topics (ties: earliest). For Pope Francis it is the first trend instead, as in `opening.json` (same topics and window).
  - its UTC offset that day (DST-aware, `country_timezones.json`), the same instant on the local clock, the trends, the top phrasing, and whether the peak step was tied.
- **US, CA, RU:** one national feed spans several zones. The national row uses the zone in `country_timezones.json` (US America/Chicago, CA America/Toronto, RU Europe/Moscow). `zones[]` adds each zone's peak from the regional feeds (`REGION_TZ`), in that zone's own clock. The zones are extra and are not in the spreads.
- **Cases:**
  - New Year's Eve 2024/25 and 2025/26: clean New Year group, 30 Dec 12:00 to 1 Jan 12:00 UTC.
  - Christmas Eve 2024 and 2025: clean Christmas group, 23 Dec 12:00 to 26 Dec 00:00 UTC.
  - Weather "today": every weather phrasing without a tomorrow word, all days. The typical peak is the local hour and, separately, the UTC hour with the most trends (20+ trends; US/CA/RU regional, as the weather clock).
  - Pope Francis on 21 Apr 2025: first trends.
- **Spread:** quartiles and IQR in hours over countries, from the reference: midnight (UTC, or the local wall clock) for the holidays, 00:00 on 21 Apr for the Pope. Hours of day (weather, the Pope's local hour) are unwrapped around their circular mean. For the holidays I added two things you didn't ask for: countries within 1 h / 3 h of midnight on each clock, and the spread over countries with a clear peak (2+ trends in the step, no tie).
- **Results:**

  | Case | Countries | IQR UTC / local (h) | Within 1 h of the median, UTC / local |
  |---|---|---|---|
  | Weather today | 120 | 3.0 / 0.0 | 58 / 116 |
  | Pope Francis | 120 | 0.33 / 2.7 | 110 / 43 |
  | New Year's Eve 2024/25 | 125 | 23.5 / 23.3 | 5 / 3 |
  | New Year's Eve 2025/26 | 125 | 23.0 / 23.5 | 3 / 2 |
  | Christmas Eve 2024 | 106 | 16.8 / 14.8 | 9 / 20 |
  | Christmas Eve 2025 | 111 | 21.7 / 18.1 | 7 / 11 |

  - Weather: 116 of 120 countries peak at 06:00 local (local IQR 0 h), while the UTC peaks spread over 3 h (13 h between the 10th and 90th percentiles).
  - Pope Francis: the reverse. 110 countries start within 1 h of the median UTC time; the local clocks spread over 2.7 h (IQR).
- **New Year's Eve, all countries:** the busiest-step rule is noisy. Most countries have few trends in the window (median 10) and 1–2 in the peak step, so ties take the earliest step. The peaks split between the morning of 31 Dec local (wishes, greetings) and local midnight. Within 1 h of midnight: 13 countries on the UTC clock vs 50 on the local clock (2024/25), and 12 vs 48 (2025/26).
- **New Year's Eve, clear peaks only** (49 and 48 countries): local IQR 0.33 h vs 6.2 h UTC (2024/25), and 0.17 h vs 5.5 h (2025/26). 43 of them peak within 1 h of local midnight, against 11 and 9 within 1 h of UTC midnight. The US zones peak near their own midnight (New York 23:50, Chicago 23:10, Denver 23:50 local), and so does Moscow (00:00).
- **Christmas Eve** does not show the effect. Its searches spread over 24 December (films, lights, opening hours), most countries have 1–3 trends, and only 10–11 countries have a clear peak.

### Step 9 round 36: weather "usual day" (2026-11-25)
- **Export:** `weather_day.json` (`08_story_export.py`, after `rituals.json`). The rows, the 'today' / 'tomorrow' split and the zones are the same as the weather clock: national feeds in one zone, and US/CA/RU from their regional feeds, each in its own zone. A country counts once per local hour if any of its zones has a trend starting then.
- **Day:** the local calendar date of the trend's start.
- **by_day:** each day carries a flag and the number of countries per local hour 0–23, for 'today' and for 'tomorrow'.
- **Flags:** a local day overlaps the UTC day before and after it, so a day is:
  - "gap" if the date is a collection gap day (51 days);
  - "next to a gap or archive edge" if the day before or after is a gap day or outside the archive (14 days);
  - "outside archive" (2 days: the local days just before and after the archive);
  - full coverage otherwise: 472 of 539 days.
- **Usual day:** the mean and median per local hour over the 472 full-coverage days.
  - 'Today': peak at 06:00 local, mean 19.75 countries (median 19). Next is 07:00 with 13.7.
  - 'Tomorrow': peak at 20:00 local, mean 8.5 countries (median 6). Next is 21:00 with 2.9. Almost no 'tomorrow' trends start at other hours.
- **Not checked:** whether the 19:00 UTC collection bump (CHECKS C4) adds to the 20:00 'tomorrow' peak for countries at UTC+1.

### Step 9 round 37: weather and the global-moment rule (2026-11-25; report only, no pipeline change)
- **Global weather moments:** 1 of 36,128 weather-category moments, on 1 day. It is topic "Weather", moment 920899, starting 2025-05-20 22:10 UTC, with reach 18 and 15 countries within 60 min of the third. Every phrasing is plain "weather", so it is 'today'. No 'tomorrow' moment passes. The next-best weather moments reach 12 and 11.
- **Countries:**
  - 15 of 18 are at UTC+0 to +3: 13 European countries (FI, HR, RS, AT, SE, AL, NL, BE, DK, MK, CZ, HU, NO) plus CI and GH.
  - The other three are JP, NP and TT.
  - Each country starts between 06:20 and 07:10 local. JP is first at 22:10 UTC, NP follows at 00:50, Europe at 04:10–05:10, West Africa at 06:40–07:00, and TT at 10:30.
  - So the moment is the European morning: about 13 countries at UTC+1/+2 reach 6–7 a.m. within the same hour. It is not one shared instant.
- **Kind:** shock. Claude's shock label calls it unscheduled, so `is_shock` wins over ritual. It is in `shocks.json` → `moments` (sub-kind other, not verified), but not in `chart_top60` or `other_top40`. It is not in `appointments.json`. It is a false shock.
- **Why so rare:** each language is its own topic ("hava durumu", "天気", ...), and 6 a.m. moves one hour per time zone. Only the European band of UTC+1/+2 countries can put 15 countries into one hour.
- **The rule's anchor:** the rule counts from the third country of a moment. Weather moments are long sessions, so a burst later in a session is not counted. A sliding 60-minute window finds 6 topic-days with 15+ countries:
  - "Weather", 2025-04-07 03:50 UTC: 18 countries, all at 6–7 a.m. local.
  - "Weather forecast" on 2025-12-23, 2026-01-01, 2026-02-19 and 2026-03-15, each at 18:50–19:40 UTC: 15–19 countries, almost all "weather tomorrow" at 20:00 local in UTC+1. These sit on the 19:00 UTC collection bump (CHECKS C4).
  - "Weather today", 2026-04-14 11:10 UTC: 20 countries at mixed local hours, which looks like a collection artefact.
  - All of these moments are ritual. None is flagged global.
- **Against the usual day** (`weather_day.json`, 472 full-coverage days): 9,322 country-days have a 'today' weather trend starting at 6 a.m. local (19.75 a day). Only 18 country-trends are in a global weather moment, about 0.2%. On 2025-05-21 itself, 23 countries started 'today' weather at 6 a.m. local, the same as an ordinary day. Weather is a ritual of the local clock, and the global-moment rule, which measures one shared UTC hour, almost never sees it.
- **Possible fix, not made:** set weather moments to ritual even when Claude labels them shocks. This is your decision. You approved it in round 38.

### Step 9 round 38: weather takes precedence over shock; 'tomorrow' robustness (2026-11-25)
- **Rule** (`04_moments.py` `add_shock`): weather-category moments are never shocks. Both `is_shock` and the rule-alone `is_shock_rule` are False for them, so their kind is ritual even when Claude calls them unscheduled. The `moment_kinds` docstring is updated.
- **Rerun:** `make after-topics`, `make shocks-estimate` and `make story`. No Claude calls.
- **What moved:**
  - One moment changes kind: "Weather", 2025-05-20, from shock to ritual. No other weather moment was a shock.
  - Shock moments: 598 → 597. Rule alone: 610 → 609.
  - Sport-free global shocks in `shocks.json`: 590 → 589; of kind other, 401 → 400; sub-kind other, 79 → 78. The top 40 and the chart's top 60 are unchanged.
  - Estimate: flagged 602 → 601; true shocks 475 [400, 548] → 474 [399, 546].
  - Speed baseline (30+ countries in 72 h): shocks 324 → 323; everything else 2,885 → 2,886, median 15.67 → 15.59 h to half.
  - CHECKS, PROFILE, waves and the ritual topic counts are unchanged.
- **'Tomorrow' robustness** (`weather_day.json` → `tomorrow_robustness`, over the 472 full-coverage days). The table shows mean countries per day at each local hour:

  | Version | Trends | 19:00 | 20:00 | 21:00 | Peak |
  |---|---|---|---|---|---|
  | All | 9,580 | 0.06 | 8.53 | 2.91 | 20:00 |
  | (a) without starts at 19:00–19:59 UTC | 8,655 | 0.06 | 7.25 | 2.47 | 20:00 |
  | (b) without UTC+1 countries | 8,666 | 0.05 | 7.25 | 2.47 | 20:00 |

  - At 20:00 local, (a) and (b) remove the same trends: for a UTC+1 country, 20:00 local is 19:00 UTC.
  - Removing them takes the peak from 8.5 to 7.25 countries, about 15%. The peak stays at 20:00 in both versions and stays far above every other hour.
  - So the collection bump does not make the 8 p.m. peak. It may add about 1 country a day to it, through the UTC+1 countries, but this check cannot separate that from those countries' real 8 p.m. habit.

### Step 9 round 39: Country Wrapped refresh, "your turn" (2026-11-25)
- **Cards** (`08_story_export.py` section 8): `wrapped/<CC>.json` and `wrapped/index.json` are rebuilt on the current pipeline: shock rule, outage and weather fixes, athlete filter, clean holiday groups. 125 countries, 5 low_data (CU, EE, LV, MD, MK).
- **What each card adds:**
  - `local_share`: share of its topics found in no other national feed, as in `local.json`. Rank 1 is the most local, ranked among all 125 and among those that aren't low_data. The old `local_share` (share of trends whose moment reached < 15 countries) is renamed `small_moment_share`.
  - `uniquely_local_top5`: one-country topics without hidden or Wrapped-skip topics, sorted by trends and then volume. I changed this from step 5's volume-first order, which picked one-off 1M-volume draws such as "Euromillions draw 28 March 2025". Each topic has its top 3 phrasings.
  - `shocks`: which of the 60 chart shocks it joined, using event reach (main topic plus accepted topics, start −2 h to +24 h, as `shocks.json`). Also the global moments it joined (not hidden) and how often it was among the first 3 countries. Ties with the third country count, because times are in 10-minute steps.
  - `appointments.widest_3`: its 3 widest appointment events (the `appointments.json` units by event reach; a country joins if it trended any of the event's topics in the event window).
  - `waves`: which of the 18 verified wave stories (`waves_chart.json`) it joined, with the story's months at 15+ countries in which it took part.
  - `rituals`:
    - the weather 'today' and 'tomorrow' peak local hours, as `rituals.json` (20+ trends; US/CA/RU regional);
    - the top weather phrasing;
    - the holidays it searched in both years (clean groups, −10..+5 days).
  - `attention_twin` (Jaccard on topic sets, all topics) and `attention_twin_without_sport` (without sports matches, clubs and athletes: category sports_match / team, `is_athlete`), each with 2 runners-up.
  - `low_data`, `biggest_day` (from step 5), `kind_shares`.
- **Removed** from the cards: `most_local_topic` (now `uniquely_local_top5`), `weather_hour` and `time_of_day_source` (now under `rituals`).
- **Bug fixed:** the name `low` was reused in the holiday block, so the first run flagged 0 cards as low_data. The set is now `LOW_DATA`.
- **Numbers:**
  - Twins: the same in both versions for 71 of 125. Mutual twins: 44 on all topics, 62 without sport.
  - Chart shocks joined per country: median 49 of 60 (min 4, max 60).
  - Among the first 3 countries most often: Brazil 3,351, the US 2,662, the UK 2,658.
  - Verified waves joined: median 12 of 18; 25 countries joined all 18.
  - Weather 'today' hour: 120 cards have one, 98 of them at 06:00.
  - Most local (not low_data): Japan 92.4%, South Korea 86.2%, Iran 83.9%.
- **Data, not a bug:** Japan's top weather phrasing is "cuaca besok" (Indonesian). Japan's feed has many foreign-resident weather searches (Indonesian, Vietnamese, Korean).
- **Widest 3 appointments** are the same three football matches for most countries (Barcelona vs Inter, the Club World Cup final, the Europa League final). There is no version without football yet; this is your call.
- **Validation** (`09_validate_shocks.py wrapped-review`, local files, git-ignored):
  - `docs/WRAPPED_VALIDATION.md` has every country's twin in both versions, flagged when the two share an official language (Wikidata P37, one SPARQL request, cached in `cache/wikidata/official_languages.json`) or the main search language (`COUNTRY_LANG`).
    - All topics: 70 of 125 share an official language, 77 share it or the main language.
    - Without sport: 70 and 78.
    - P37 has no English for the US and no language for UY, so "same main language" is the fallback.
    - Twins without a shared language are mostly thin or mirror-like feeds. Turkmenistan is the all-topics twin of Armenia, Azerbaijan and Kyrgyzstan (Jaccard up to 0.54); without sport these become Georgia and Uzbekistan.
  - `docs/wrapped_review.csv`: 40 uniquely local topics, one per country for 40 random countries (seed 47), drawn from each card's top 5. The label column is for you: truly local / merge failure (same topic elsewhere) / should be hidden. The sample is never overwritten once labelled.
- **Time machine, simplified:** `days.json` has every UTC day of the archive (537 days; 487 with a global moment; 51 gap days), with its 5 widest global moments (not hidden, by moment reach then within 60 min): name, kind, countries, countries within 60 min, start, is_sport. The top-5 entries are 2,139 appointments, 189 shocks, 15 ritual and 7 other. The countries are moment reach: Pope Francis has 101 here against 120 event reach in the shock chart. The hourly frames (`data/export/hours/`, `timemachine/`) are unchanged.

### Step 9 round 40: Wrapped card fixes, event reach in days.json (2026-11-25)
- **Appointments:** each card adds `widest_3_without_football` (the same units, category not football) and keeps `widest_3`. The list is nearly the same everywhere: the Conclave 2025, the Winter Olympics 2026, and the Super Bowl LIX (Wimbledon for some).
- **Surprising twin** (`surprising_twin`): the most similar country on the no-sport Jaccard matrix that shares neither an official language (Wikidata P37, the cache written by `wrapped-review`) nor the main search language (`COUNTRY_LANG`). It also records its Jaccard and its rank among all countries. It differs from the no-sport twin for 78 of 125 countries, and from the all-topics twin for 103. Examples: France → Germany (rank 2), the US → Germany (rank 4), India → Bangladesh (rank 2), Japan → Taiwan (rank 1).
- **First 3:** `first3_share` = global moments where the country was among the first 3, divided by the global moments it joined, with its rank among the 120 countries that aren't low_data. The raw count is kept.
  - Highest: Brazil 70% (3,351 of 4,816), then the UK 46% and the US 46%.
  - Brazil's lead may partly reflect how fast its feed updates. Not checked.
- **Rituals:** `top_weather_phrasings` gives the top 3 (it was 1).
- **days.json:** when a moment belongs to a verified shock event or an appointment event, `countries` is the event reach, as in the charts, and `event` gives the event's name.
  - Verified shock events use the event groups: main topic plus accepted topics, start −2 h to +24 h, verified shocks among the 100 widest.
  - Appointment events use the `appointments.json` units and their members.
  - Otherwise it is the moment reach. `reach_basis` says which, and `moment_countries` keeps the moment reach.
  - Entries are ranked by `countries`, with one entry per event per day.
  - Top-5 entries: 2,130 from appointment events, 66 from verified shock events, 154 moments. Pope Francis on 2025-04-21 now shows 120, the same as the shock chart.

### Step 9 round 41: hours/ frames with shared topics; Wrapped local rule from hand labels; Brazil's first 3 (2026-11-25)
**A. Map frames.** `data/export/hours/YYYY-MM.json` moves from step 5 to step 8 (section 7b), because the kinds need the moment kinds and the verified waves. Step 5 no longer writes them, and step 7's hours check no longer sees them; step 8 checks their shape itself.
- **Same rules:** national feeds; the highest-volume trend active in each UTC hour per country (at most 24 h, ties to the latest start); hidden topics never shown; -1 = none. Every hour of a collection-gap day is now -1 and listed in `gap_hours`.
- **New per hour:** `shared` = the top 5 topics by countries with the topic active that hour, as [topic, countries, kind].
- **Kind:** shock if any active trend is in a shock moment, else appointment, else wave (a verified wave story topic, `waves_chart.json`), else ritual, else other.
- **Files:** 19, one per month; largest 1.22 MB, total 20.4 MB, all under 2 MB.
- **Hours with a topic shared by 15+ countries:** 11,548 of 12,624 non-gap hours. The count is high because a trend counts as active for up to 24 h. Of the top-5 entries with 15+ countries: appointment 46,047, other 4,851, shock 3,251, ritual 1,352, wave 282.

**B. Wrapped local topics.**
- **Hand labels** (`docs/wrapped_review.csv`, scored by `09_validate_shocks.py wrapped-score` → `work/wrapped_validation.json`): 34 of 40 truly local (85%, 95% CI 71–93%), 6 merge failures. None should be hidden.
- **New rule for `uniquely_local_top5`:** no football fixtures (a name with "vs", "v", " : " or " x ", or Claude type / category sports_match or team, or an athlete), no weather-category topics, at least 5 trends.
- **What the rule does with the sample:**
  - It removes 4 of the 6 merge failures: three football fixtures and Danish "Weather".
  - Two stay: "خرید بیت کوین" ("buy Bitcoin", IR) and "break fast today" (SG, iftar).
  - It also removes 6 truly local topics, as the rule intends: Panathinaikos basketball (a team), four city or national weather topics, and Wicknell Chivayo (4 trends).
- **Cards:** the top 5 changes on 61 of 125 cards. Dropped from the old top 5s: 65 with fewer than 5 trends, 47 weather topics, 22 fixtures, teams or athletes.
- **Examples (before → after):**
  - FR: drops "meteo toulon", adds "TV programme tonight (France)". This is a duplicate of "programme télé ce soir", a merge failure.
  - US: drops "Atlanta weather" and "dc weather", adds "lsu baseball" and "padres game today". Baseball games that aren't fixture-named or sports_match still pass.
  - BR: drops "previsão do tempo são paulo", adds "garota do momento".
  - DK: drops "Weather", adds "novo aktier". "Danish Meteorological Institute" stays (not weather category).
  - AR: drops four "clima ..." topics; now "quini 6", "quiniela de tucuman", "la joaqui", "pronostico cordoba", "river id". "pronostico cordoba" is a weather forecast outside the weather category.
- **Most distinctive appointment** (`appointments.most_distinctive`): among the appointment events the country joined with a total reach of 15+, the one with the smallest total reach. Total reach = every country in the event window; `event_reach_total` for multi-day events. All 125 cards have one. The most common are Formula 1 standings (15 cards), Chelsea FC (11) and Paris Saint-Germain vs Monaco (10).

**C. Brazil's first3_share.**
- **Feed update frequency** (median minutes between consecutive distinct trend starts): Brazil 10 min, median country 30 min. 25 of the 120 countries that aren't low_data are at 10 min.
- **Feed speed explains much of the pattern:** Spearman −0.67 between the step and first3_share (ties shared). Median first3_share with ties shared is 9.9% at 10 min against 2.0% at 30 min.
- **Ties shared** (`first3_share_ties_shared`: countries tied at the third country's 10-minute step share the remaining places): Brazil 50%, Indonesia 24%, UK 24%, US 22%. Brazil was 70% before.
- **Brazil's lead holds**, also among the 10-minute feeds, where the next is 24%. Its first-3 count shrinks a lot when ties are shared, but no other fast feed comes close. The data can't separate "Brazil searches first" from "Brazil's feed is collected first within each 10-minute step".

### Step 9 round 42: tighter local top 5, appointment share (2026-11-25)
- **Local top 5, rules added** (`08_story_export.py`, section 8):
  - **Sport phrases** (`SPORT_PHRASE_RE`, on the topic name and raw string): "game today", "match today", score / placar / marcador / skor, baseball / basketball (and Spanish and Portuguese forms), standings / tabla de posiciones / klasemen / puan durumu, line-up words, "live" next to a team or league word, NBA / NFL / NHL / MLB / IPL.
  - **Clubs and leagues by name:** fc / afc / cf / cd, liga / league / lig, الدوري, ลีก, sport(s), NB I / NB II, MPBL / PBA / KBO / NPB.
  - Claude types and categories sports_match / team and athletes stay excluded (round 41). There is no "league" type.
  - **Weather-like topics** outside the weather category (`WEATHER_LIKE_RE`): forecast words in several languages (forecast, pronóstico, previsão, météo, wetter, clima, погода, hava durumu, cuaca, thời tiết, 天気, 날씨, طقس, pogoda, počasí, időjárás, vremea, vrijeme, orai ...) and meteorological institutes (DHMZ, BMKG, DMI, SMHI, AEMET, INMET, PAGASA, IMD, JMA, KMA, SMN, Met Office ...).
  - **Near-duplicates:** going down the card's list in trends order, a topic is skipped when it shares 2+ words with a topic already kept and the shared words make up ≥ 60% of the smaller word set. Words are lower-case, accent-free tokens of 3+ characters from the name (without a parenthesised country), the raw string and the top 3 phrasings, minus generic words (today, live, price, results, channel, news ...).
- **Tuning:** a first version without accent folding and the generic-word list paired different topics (Channel 3 vs Channel 7 in Thailand, coffee vs petrol prices in Vietnam) and missed France's TV pair. A first club pattern with \bsc\b / \bse\b / \bca\b would have dropped "sc lottery" and Portuguese "se", so it was narrowed.
- **Result:** 36 of 125 cards change from round 41. 83 of 125 now differ from the plain list. 5 near-duplicates are skipped:
  - France: "TV programme tonight (France)" behind "programme télé ce soir".
  - Kenya: "Kenya Power (KPLC)" behind "kenya power".
  - Nigeria: "bbc hausa live" and "BBC Hausa" behind "bbc hausa.com".
  - Libya: "منظومة حجز الدولار" (the dollar booking system) behind "مصرف ليبيا المركزي" (the central bank, whose booking system shares the words).
- **Examples (round 41 → round 42):**
  - CZ: −ČT Sport, čt sport plus, čt sport živě; +novinky, prostřeno, ondřej sokol
  - SA: −هدافين الدوري السعودي, مباريات اليوم الدوري السعودي; +حافز, Study suspension
  - ID: −BMKG (Indonesian Meteorology Agency), bmkg juanda; +Vidio, asmara gen z
  - US: −lsu baseball, padres game today; +laura ingraham, sc lottery
  - FR: −TV programme tonight (France); +Eric Antoine
- **Still through:** clubs without a club word, such as "gcz" (CH), "hearts of oak" (GH), "man cty" / "manc" (UG) and "marathon hoy" (HN).
- **Short lists:** 19 cards have fewer than 5 topics after the rules, most of them because of the 5-trend minimum (for example AL, AO, BF, GE, ML, NI, SY, TM with 1).
- **Appointment share** replaces `most_distinctive`, which picked teams and standings rather than events. `appointments.appointment_share` = the global moments (not hidden) the country joined that are appointments, divided by all the global moments it joined, with its rank among the 120 countries that aren't low_data.
  - Highest: Turkmenistan 100%, Haiti 99%, Mali 99%. Median 93%. Lowest: Norway 77%, Finland 74%, Lithuania 67%.
  - The range is narrow because global moments are mostly sport.

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
