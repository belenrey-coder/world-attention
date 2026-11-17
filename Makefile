PY := .venv/bin/python
T  := pipeline/03_topics.py

.PHONY: setup download clean-data strings typos embed semantic combine link validation topics moments export profile checks story shocks-thresholds shocks-label shocks-label2 shocks-sample shocks-sample2 shocks-score shocks-score2 shocks-verify shocks-estimate after-topics score

setup:
	python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

download:          ; $(PY) pipeline/01_download.py
clean-data:        ; $(PY) pipeline/02_clean.py
strings:           ; $(PY) $(T) strings
typos:             ; $(PY) $(T) typos
embed:             ; $(PY) $(T) embed
semantic:          ; $(PY) $(T) semantic
combine:           ; $(PY) $(T) combine
link:              ; $(PY) $(T) link
validation:        ; $(PY) $(T) validation
moments:           ; $(PY) pipeline/04_moments.py
export:            ; $(PY) pipeline/05_export.py
profile:           ; $(PY) pipeline/06_profile.py
checks:            ; $(PY) pipeline/07_checks.py
story:             ; $(PY) pipeline/08_story_export.py
shocks-thresholds: ; $(PY) pipeline/09_validate_shocks.py thresholds
shocks-label:      ; $(PY) pipeline/09_validate_shocks.py label
shocks-label2:     ; $(PY) pipeline/09_validate_shocks.py label2
shocks-sample:     ; $(PY) pipeline/09_validate_shocks.py sample
shocks-sample2:    ; $(PY) pipeline/09_validate_shocks.py sample2
shocks-score:      ; $(PY) pipeline/09_validate_shocks.py score
shocks-score2:     ; $(PY) pipeline/09_validate_shocks.py score2
shocks-verify:     ; $(PY) pipeline/09_validate_shocks.py verify-sheet
shocks-estimate:   ; $(PY) pipeline/09_validate_shocks.py estimate
score:             ; $(PY) pipeline/score_validation.py

# Step 3 without any paid API call (Claude labels are read from cache/claude/)
topics: strings typos embed semantic combine link validation

# Everything after topic merging
after-topics: moments export profile checks
