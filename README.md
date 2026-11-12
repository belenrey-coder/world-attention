# World attention: Google Trending Now, cleaned and merged into topics

The data foundation for a time machine of the world's attention: it cleans the data, merges every phrasing of a topic, detects moments and exports compact JSON for the site.

Source: *Google Trend Archive* (`aurman/GoogleTrendArchive` on Hugging Face). These are the "Trending Now" searches for every available country and region, Nov 2024 – May 2026.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

The Anthropic API key is read from `.env` (`ANTHROPIC_API_KEY=...`) with python-dotenv. `.env`, `.venv/`, `data/raw/`, `data/interim/` and `cache/` are git-ignored.

## Run

Each step reads the previous step's output. Run from the project root.

| Step | Command | Output | Time |
|---|---|---|---|
| 1 download | `.venv/bin/python pipeline/01_download.py` | `data/raw/` (CSV and a parquet copy) | ~2 min |
| 2 clean | `.venv/bin/python pipeline/02_clean.py` | `data/interim/trends.parquet`, `timestamp_checks.json` | ~2 min |
| 3 strings | `.venv/bin/python pipeline/03_topics.py strings` | `data/interim/work/strings.parquet` | 30 s |
| 3a typos | `.venv/bin/python pipeline/03_topics.py typos` | `work/edges_typo.parquet` | ~3 min |
| 3c embed | `.venv/bin/python pipeline/03_topics.py embed` | `cache/embeddings/` (computed once) | ~5 min (Apple MPS) |
| 3c semantic | `.venv/bin/python pipeline/03_topics.py semantic` | `work/edges_semantic.parquet` | ~2 min |
| 3b wikidata | `.venv/bin/python pipeline/03_topics.py wikidata [test\|important\|all]` | `work/wikidata_links.parquet`, `cache/wikidata/` | rate-limited, see DECISIONS |
| 3d Claude test | `.venv/bin/python pipeline/03_topics.py claude-test` | `cache/claude/` | ~5 min, ~$0.01 |
| 3d Claude full | `.venv/bin/python pipeline/03_topics.py claude-full` | `cache/claude/` | ≤ 24 h batch; **only after approval** |
| 3e combine | `.venv/bin/python pipeline/03_topics.py combine` | `data/interim/topics.parquet` | ~4 min |
| 3g link | `.venv/bin/python pipeline/03_topics.py link` | rewrites topics in `topics.parquet`; `docs/link_review.csv` | ~3 min |
| 3f validation | `.venv/bin/python pipeline/03_topics.py validation` | `docs/validation_sample.csv` | seconds |
| 4 moments | `.venv/bin/python pipeline/04_moments.py` | `data/interim/moments.parquet`, `topic_meta.parquet`, `docs/GLOBAL_MOMENTS.md` | ~3 min |
| 5 export | `.venv/bin/python pipeline/05_export.py` | `data/export/` (days, hours, moments_global, topics_index, wrapped, similarity, routine, coverage) | ~3 min |
| 6 profile | `.venv/bin/python pipeline/06_profile.py` | `docs/PROFILE.md` | ~1 min |
| 7 checks | `.venv/bin/python pipeline/07_checks.py` | `docs/CHECKS.md`, `docs/review_sensitive.csv`, `docs/review_types.csv` | ~1 min |
| 8 story | `make story` (`.venv/bin/python pipeline/08_story_export.py`) | `data/export/story/` (one JSON per chapter, < 1 MB each), `docs/STORY_NUMBERS.md` | ~1 min |

`make topics` reruns step 3 from cache (no API calls); `make after-topics` runs steps 4–7.

After you label `docs/validation_sample.csv` by hand (`same_topic_label` = 1 or 0), run `.venv/bin/python pipeline/score_validation.py`.

Manual topic fixes go in `pipeline/overrides.csv` (`string, action, topic`; actions `detach` or `move`). They are applied at the end of combine, so rerun from `make combine` after editing it. See `docs/DECISIONS.md`.

Every external call is cached: Wikidata responses go to `cache/wikidata/`, and Claude batch results and labels go to `cache/claude/`. A rerun never sends the same request twice. The Claude step logs token usage and cost in `cache/claude/batches.json`. `claude-full` refuses to start if its estimate would push total spend above $5 (the account limit is $10).

## Outputs

- `data/interim/trends.parquet`: every kept row (country and region feeds). Columns: UTC start/end, `local_time` + `local_tz`, `country_code`, `country_name`, `level`, `region`, `query_raw`, `query_norm`, `related` (list), and the original volume and duration fields.
- `data/interim/topics.parquet`: the same rows plus `topic_id` and `topic_name`.
- `data/interim/work/string_topics.parquet`: one row per distinct `query_norm`, with its topic, the layer that merged it, its QID and its Claude label.
- `data/interim/moments.parquet`: one row per moment (topic × time window) with per-country spread.
- `data/export/`: JSON for the site, each file < 2 MB; see `manifest.json`.
- `docs/PROFILE.md`, `docs/DECISIONS.md`, `docs/CHECKS.md`, `docs/GLOBAL_MOMENTS.md`, `docs/GLOBAL_MOMENTS_NO_SPORT.md`.
- Hand-review files (`review_sensitive.csv`, `validation_sample*.csv`, `validation_key*.csv`, `link_review.csv`) are written to `docs/` but stay local: see `docs/REVIEW_FILES.md`.

## Citation

Urman, A., Hannák, A., & Baumann, J. (2026). *Google Trend Archive: Global Real-Time Search Trends*. ICWSM 2026. Dataset: Hugging Face, https://doi.org/10.57967/hf/7531. Licensed CC BY 4.0.

```bibtex
@dataset{urman2026googletrendarchive,
  title={Google Trend Archive: Global Real-Time Search Trends},
  author={Urman, Aleksandra and Hann{\'a}k, Anik{\'o} and Baumann, Joachim},
  year={2026},
  publisher={Hugging Face},
  doi={10.57967/hf/7531},
  url={https://huggingface.co/datasets/aurman/GoogleTrendArchive}
}
```
