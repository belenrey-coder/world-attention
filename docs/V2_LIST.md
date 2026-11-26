# All at Once: v2 list

Found in the v1 QA (milestone 9). Not fixed yet. (Item 1 of the first list, fast scrolling and step state, was fixed in v1.1.)

1. **Tap targets to 44 px:** legend filters, jump buttons, "Show the data", table sort buttons.
2. **Phones:** step cards must not cover the ridgeline (Waves) or the bottom rows of the two-clocks chart (Closing).
3. **Your turn tooltip:** show the original search as typed, plus the English translation.
4. **Before the final:** run Lighthouse (accessibility ≥ 95) and a VoiceOver pass.
Note: a manual "Run workflow" trigger is already in place (`workflow_dispatch` in `.github/workflows/pages.yml`): on the Actions page, open "Deploy site to Pages" and use "Run workflow" to redeploy without a push.
