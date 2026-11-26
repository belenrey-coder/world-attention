# All at Once: v2 list

Found in the v1 QA (milestone 9). Not fixed in v1.

1. **Fast scrolling.** Each chart's state must depend only on the current step (idempotent), and controls that unlock "after the steps" must unlock when the reader is past the last step, however they got there (fast scroll, keyboard End, a link).
2. **Tap targets to 44 px:** legend filters, jump buttons, "Show the data", table sort buttons.
3. **Phones:** step cards must not cover the ridgeline (Waves) or the bottom rows of the two-clocks chart (Closing).
4. **Your turn tooltip:** show the original search as typed, plus the English translation.
5. **Before the final:** run Lighthouse (accessibility ≥ 95) and a VoiceOver pass.
