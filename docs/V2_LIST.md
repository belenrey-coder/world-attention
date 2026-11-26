# All at Once: v2 list

Found in the v1 QA (milestone 9). Not fixed yet. (Item 1 of the first list, fast scrolling and step state, was fixed in v1.1.)

The article is desktop only (Nov. 26, 2026): target 1280–1920 px wide, minimum 1024 px. Below 1024 px the title screen shows "Best read on a computer." Phone layouts are no longer tested; the earlier phone item (step cards covering the ridgeline and the two-clocks chart) is dropped.

1. **Click targets to 44 px:** legend filters, jump buttons, "Show the data", table sort buttons.
2. **Your turn tooltip:** show the original search as typed, plus the English translation.
3. **Before the final:** run Lighthouse (accessibility ≥ 95) and a VoiceOver pass.

Note: a manual "Run workflow" trigger is already in place (`workflow_dispatch` in `.github/workflows/pages.yml`): on the Actions page, open "Deploy site to Pages" and use "Run workflow" to redeploy without a push.
