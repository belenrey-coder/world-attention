# Review files (local only)

The pipeline writes a few hand-review files that are **not published** in this repository. They exist only on the machine that runs the pipeline and are git-ignored (see `.gitignore`).

| File | Written by | What it is for |
|---|---|---|
| `docs/review_sensitive.csv` | `pipeline/07_checks.py` | Topics shown on the site that match crime/death/sexual keywords or look like private people; decide keep or hide |
| `docs/validation_sample.csv`, `docs/validation_sample_v1.csv`, `docs/validation_sample_v3.csv` | `pipeline/03_topics.py validation` | String pairs to label by hand (same topic or not), scored with `pipeline/score_validation.py` |
| `docs/validation_key.csv`, `docs/validation_key_v1.csv`, `docs/validation_key_v3.csv` | `pipeline/03_topics.py validation` | Answer keys for the validation samples; open only after labeling |
| `docs/review_types.csv` | `pipeline/07_checks.py` | Topics sampled per Claude type to check the type by hand (fill `correct_type`) |
| `docs/link_review.csv` | `pipeline/03_topics.py link` | Every cross-language link the link step accepted, for spot checks |
| `docs/shock_validation_sample.csv` | `pipeline/09_validate_shocks.py sample` | 100 global moments to label by hand (scheduled / unscheduled, event type), scored with `09_validate_shocks.py score` |
| `docs/shock_validation_key.csv` | `pipeline/09_validate_shocks.py sample` | Answer key for the shock sample (strata, timing-rule flags, Claude's labels); open only after labeling |
| `docs/shock_validation_sample2.csv` | `pipeline/09_validate_shocks.py sample2` | Test sample for the final shock and sport rules: 80 new global moments (40 the rule calls shocks, 40 others), none from the first sample |
| `docs/shock_validation_key2.csv` | `pipeline/09_validate_shocks.py sample2` | Answer key for the test sample (strata, rule flags, Claude's labels); open only after labeling |
| `docs/shock_chart_verification.csv` (then `_2`, `_3`, …) | `pipeline/09_validate_shocks.py verify-sheet` | The 60 widest shocks for the chart that have no hand label yet, to label (scheduled / unscheduled, event type); labels override Claude in step 4 |
| `docs/shock_chart_verification_key.csv` (then `_2_key`, …) | `pipeline/09_validate_shocks.py verify-sheet` | Key for each verification sheet (moment key, chart rank, Claude's label); open only after labelling |
| `docs/event_groups_review.csv` | `pipeline/09_validate_shocks.py event-groups` | Candidate topics for each chart shock's event group (name matches in the event window), to accept or reject; accepted ones count towards event reach |
| `docs/event_groups_review_appointments.csv` | `pipeline/09_validate_shocks.py appointments` | Candidate topics for each appointment chart event's group, to accept or reject (no-effect rows marked) |
| `docs/appointment_chart_verification.csv`, `docs/appointment_chart_verification_key.csv` | `pipeline/09_validate_shocks.py appointments` | The appointment chart set's moments without a hand label, to label (scheduled / unscheduled, event type); key with category and Claude's label; labels override Claude in step 4 |
| `docs/waves_review.csv` | `pipeline/09_validate_shocks.py waves-sample` (after `make story`) | Every wave topic (months at 15+, peak, countries per month, shocks); 40 stratified topics flagged `in_sample` to label (real recurring story / always-on query / misgrouped topic / should be sport or ritual). Claude's category is left out so the labels stay blind |
| `docs/wave_chart_verification.csv` (then `_2`, …) | `pipeline/09_validate_shocks.py waves-verify-sheet` | The top 30 clean waves by months at 15+, with what drove each month at 15+ (that month's searches, its new related searches, Claude's summary of shock moments), to label; never overwritten |
| `docs/WAVES_VALIDATION.md` | `pipeline/09_validate_shocks.py waves-score` | Waves sample hand labels against Claude's categories (confusion table, per-topic labels) |
| `docs/rituals_review.csv` | `pipeline/09_validate_shocks.py rituals-sample` (after `make story`) | 60 topics from the holiday whole-topic groups (at least 3 per holiday), to label: about the holiday / unrelated match. Labelled; scored with `rituals-score` (work/rituals_validation.json) |
| `docs/wrapped_review.csv` | `pipeline/09_validate_shocks.py wrapped-review` (after `make story`) | 40 uniquely local topics (one per country, 40 countries), to label: truly local / merge failure (same topic elsewhere) / should be hidden. The same stage writes the local twin report `docs/WRAPPED_VALIDATION.md`. Labelled; scored with `wrapped-score` (work/wrapped_validation.json) |
| `pipeline/sensitive_decisions.csv` | by hand | Keep/hide decisions for sensitive topics, read by `pipeline/05_export.py` (columns `topic_id, decision, note`) |

**Why they are not published:** they list raw Google Trends searches and small local topics, and those can contain the names of private individuals, such as people in local news about accidents, arrests or missing persons, or people who trended in only one or two countries. Publishing them would spread those names further than the original trend did. The validation answer keys are also kept private so the hand labeling stays blind.

To get them, run the pipeline (`make topics`, then `make after-topics`). They are regenerated from the data each time.
