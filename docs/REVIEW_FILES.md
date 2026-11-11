# Review files (local only)

The pipeline writes a few hand-review files that are **not published** in this repository. They exist only on the machine that runs the pipeline and are git-ignored (see `.gitignore`).

| File | Written by | What it is for |
|---|---|---|
| `docs/review_sensitive.csv` | `pipeline/07_checks.py` | Topics shown on the site that match crime/death/sexual keywords or look like private people; decide keep or hide |
| `docs/validation_sample.csv`, `docs/validation_sample_v1.csv`, `docs/validation_sample_v3.csv` | `pipeline/03_topics.py validation` | String pairs to label by hand (same topic or not), scored with `pipeline/score_validation.py` |
| `docs/validation_key.csv`, `docs/validation_key_v1.csv`, `docs/validation_key_v3.csv` | `pipeline/03_topics.py validation` | Answer keys for the validation samples; open only after labeling |
| `docs/review_types.csv` | `pipeline/07_checks.py` | Topics sampled per Claude type to check the type by hand (fill `correct_type`) |
| `docs/link_review.csv` | `pipeline/03_topics.py link` | Every cross-language link the link step accepted, for spot checks |
| `pipeline/sensitive_decisions.csv` | by hand | Keep/hide decisions for sensitive topics, read by `pipeline/05_export.py` (columns `topic_id, decision, note`) |

**Why they are not published:** they list raw Google Trends searches and small local topics, and those can contain the names of private individuals, such as people in local news about accidents, arrests or missing persons, or people who trended in only one or two countries. Publishing them would spread those names further than the original trend did. The validation answer keys are also kept private so the hand labeling stays blind.

To get them, run the pipeline (`make topics`, then `make after-topics`). They are regenerated from the data each time.
