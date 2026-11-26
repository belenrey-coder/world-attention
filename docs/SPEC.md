# All at Once: Interaction and Build Spec

Nov 26, 2026 · @Someone

## How to use this spec

This is the build contract for the article: every chart, what readers see, what they can do, when things move, and how it degrades on phones, keyboards and reduced motion. The final boards on the design canvas are the visual reference; where a board and this doc disagree, this doc wins. Each chapter lists its data, its scroll steps, its interactions (trigger → behavior), its states, and its phone, keyboard and reduced-motion versions.

**Story order (8 chapters):** Opening · Most searches stay home · Shocks · Appointments · Waves · Rituals · Closing · Your turn. Cut and not to be built: the Gemini twist, the bridge from Appointments to Shocks, "is it down?", and "weather tomorrow".

## Global rules

**Color.** Two schemes, one job each. Nothing else gets a hue.

| Role | Scheme | Values |
| --- | --- | --- |
| How many countries (scale, ordered) | PuBu | #ECE7F2 · #D0D1E6 · #A6BDDB · #74A9CF · #3690C0 · #0570B0 · #023858 |
| Which topic or kind (identity) | GnBu steps | deep #084081 · blue #0868AC · sky #43A2CA · teal #2E9A8C · green #5BAA6E · aqua #7BCCC4 · mint #A8DDB5 |
| Ink, muted text, faint text | neutral | #121A26 · #5B6675 · #8A94A3 |
| Rules, land, gaps, context marks | neutral | rule #DDE3EA · land #E9ECEF · gap #F3F4F7 · context lines #CDD3DA · other data #C5CAD6 |

Topic colors are always labeled directly; color is never the only cue. Missing or partial data is hatched (45°, #DDE1E7 on white) and labeled with its days (e.g. "5/31 days").

**Type.** Headlines and body: Source Serif 4 (body 18–20 px, line-height 1.5). Labels, captions, controls: Libre Franklin (11–14 px). Kickers: Libre Franklin 800, uppercase, letter-spacing .06em.

**Layout.** Text column 640 px; charts 1,100 px wide on desktop. Below 700 px: one column, 16 px side gutters, charts at full width, no horizontal scroll. Scroll steps sit in a text card on the left of a sticky chart (desktop) or over the chart (phones).

**Motion.** One rule: motion only presents a change; the end state is always static and readable.

- Default transition 600 ms, cubic-in-out; color-only changes 300 ms.
- A step change starts when its text card crosses 50% of the viewport (Scrollama offset 0.5) and reverses when scrolling back.
- Nothing moves position between scroll steps unless the spec says so; steps change emphasis, color or axis only.
- `prefers-reduced-motion`: no tweening. Steps cut straight to their end state; autoplay is off and replaced by a Play button.

**Interaction.** Every hover has a tap equivalent; tap targets are at least 44 px. Tooltips follow the pointer on desktop and dock to the bottom of the chart on phones. Escape closes any tooltip, card or open row. Every chart has a "Show the data" toggle that reveals a plain HTML table, and an `aria-label` sentence stating its takeaway.

**Keyboard.** Tab moves through controls in reading order; arrow keys move through marks inside a focused chart (countries, lines, rows, days); Enter opens; Escape closes. A visible focus ring (2 px #121A26).

**Data.** Charts read small, aggregated JSON files built from the pipeline. Nothing private is ever published: no API keys, samples, verification or review files, shocks.json, data/export, SHOCK\_VALIDATION reports, CSV or parquet. Every chart file carries its source note and as-of date.

## Chapter 0 · Opening: the day the world searched for one man

The cold open replays April 21, 2025: Pope Francis reached 20 countries at the first refresh, 60 ten minutes later, 109 within the hour (120 in 24 hours, merged topic). Takeaway for the alt text: "Within 10 minutes, more than half of the countries were searching for Pope Francis."

**Data:** `opening.json`, one row per country: ISO code, name, first-trending refresh (UTC, 10-minute bins 07:50–08:50, then "Later"), minutes after the first refresh, local time, phrasing searched. **Visuals:** Equal Earth map (countries filled by refresh bin, PuBu, darkest = 07:50) and a square chart below (one square per country, columns by refresh, same shades). Not trending = #E9ECEF. Microstates are dots.

| Element | Trigger | Behavior | Timing |
| --- | --- | --- | --- |
| Headline block | Page load | Kicker, title, dek, byline, two paragraphs; no motion | Static |
| Map + squares playback | Chart reaches 50% of viewport | One refresh at a time: its column of squares drops in and the same countries fill on the map. Counter reads "08:00 UTC · 65 countries" | 700 ms per refresh, 8 refreshes, about 6 s; plays once |
| End state | Playback ends | Full map and squares stay; scrubber appears | Static |
| Scrubber + ▶ Replay | Drag, click or arrow keys | Stops at any refresh; map and squares show only countries up to that refresh | Instant on drag; Replay reruns the 6 s sequence |
| Hover / tap a country or square | Pointer or tap | Country and its square outline together (2 px #121A26). Tooltip: country · refresh (UTC) · local time with a short phrase ("5:00 a.m. in Buenos Aires") · how it was searched | Tooltip 150 ms fade |
| Find your country | Type in a search box (autocomplete, 125 countries) | Country outlined on map and squares; a generated sentence: "In Japan, Pope Francis started trending at 5 p.m., ten minutes after the first countries." | 300 ms |
| Show the data | Click | Sortable table of 117 trending countries + CSV download | Instant |

**States.** Default before scroll: empty map (all land #E9ECEF). During playback: partially filled. After: full map, scrubber at "Later". Search with no match: "We don't have data for that country".

**Phones.** Map full width, squares below it; tooltip docks to the bottom; scrubber 44 px tall. **Keyboard.** Tab to the map, then arrow keys move country by country in order of refresh; Enter pins the tooltip. **Reduced motion.** No playback; the final map shows with the scrubber and a ▶ Play button.

Not built on purpose: zoom and pan, replaying other events here. The chapter ends with the sentence introducing the four ways (shocks, appointments, waves, rituals).

## Chapter 1 · Most searches never leave home

Pope Francis was the exception: of about 683,000 topics that trended in 18 months, 84.9% never left one country, 13.5% reached 2 to 14, and 1.6% reached 15 or more.

**Data:** `local.json` (STORY\_NUMBERS): three groups with topic counts (579,959 · 92,204 · 11,234) and shares, plus a sample of real searches per group with translation and countries. **Visual:** three piles of real search words, heights proportional to share (84.9 : 13.5 : 1.6), words in grey #BCC4CF with highlighted examples in PuBu; big number + label above each pile; two named examples per pile.

| Element | Trigger | Behavior | Timing |
| --- | --- | --- | --- |
| Guess first | Before the piles | Slider "What share of trending topics never left one country?" (0–100%). Submit reveals the answer next to the guess. "Skip" link | Reveal 600 ms |
| Scroll step 1 · rain | Step card at 50% | Real searches fall from the top | Words fall over about 3 s, staggered |
| Scroll step 2 · settled | Step card at 50% | Words settle into three piles; numbers and labels fade in; Pope Francis highlighted in the 1.6% pile | 800 ms settle, labels 300 ms after |
| ↻ Replay the rain | Click | Reruns step 1 → 2 | About 4 s |
| Hover / tap a search | Pointer or tap a word | Tooltip: original search · English translation · "Trended in N countries: …" · which pile | 150 ms |
| Find a topic | Type a search | Matching word lights up (PuBu #0570B0), all others dim to 30%; card says which pile and how many countries | 300 ms |
| Show the data | Click | Three-row table + download of the sampled searches | Instant |

**States.** Before scroll: empty area with the three labels hidden. Settled: final piles. Search with no match: "Not in our sample; try another word".

**Phones.** Piles stack vertically (85% first), word sample reduced to about 150 per pile. **Keyboard.** Tab to each pile; arrows step through words; Enter opens the tooltip. **Reduced motion.** No rain; the settled piles show directly, with Replay hidden.

Not built on purpose: a share-of-slots toggle, the per-country localness ranking (it belongs to Your turn). Bridge sentence: "So when the whole world searches for the same thing, it is the exception."

## Chapter 2 · Shocks

Most shocks reach half their countries within an hour: the 60 widest shocks, each checked by hand, are 30 deaths, 15 outages, 8 moments of politics or conflict and 7 other.

**Data:** `shocks_chart.json` (to be derived from the pipeline's chart\_top60; see open decisions in the build plan): per shock its name, date, type, countries reached (event level), countries within 1 hour, minutes to half, and a curve of countries every 10 minutes for 3 hours, timed from the third country. **Visual:** step-line chart, x = 0 to 3 hours from the third country, y = countries reached (0–125). Context lines #CDD3DA, 1 px. Types (GnBu): death #084081, outage #43A2CA, politics or conflict #5BAA6E, other #8A94A3. Highlighted lines 3 px with direct labels at the right edge.

| Element | Trigger | Behavior | Timing |
| --- | --- | --- | --- |
| Scroll step 1 · four stories | Step card at 50% | 56 lines in context grey; four in their type color with labels: ChatGPT down (widest), Pope Francis (half in 10 min), Diogo Jota (slow start, then 122), Venezuela (kept spreading) | Lines draw left to right on first entry, 1.2 s |
| Scroll step 2 · what they were | Step card at 50% | Every line takes its type color; the legend turns into counts (30 deaths, 15 outages, 8 politics or conflict, 7 other). Nothing moves | Color 300 ms |
| Hover / tap · nearest line | Pointer near any line (Voronoi), or tap | That line goes 3 px and dark; tooltip: name · type · date · countries in 24 h | 150 ms |
| Find a shock | Search box ("e.g. Ozzy") | Matching line highlighted, others fade to 15% | 300 ms |
| Legend as filter | Tap a legend item (after step 2) | Keeps that type in color, fades the rest; tap again to clear | 300 ms |
| Measure toggle | "Countries reached" / "Share of its final reach" | Only the y-axis rescales (0–125 ↔ 0–100%); lines keep their x positions | 600 ms |
| Click a line | Click or Enter | Event card: name · type · date and first trending time · countries in 24 h and within 1 hour · minutes to half · ▶ Replay it on the opening map (same encoding as Chapter 0) | Card 300 ms; replay as Chapter 0 |
| Show the data | Click | 60-row sortable table + CSV | Instant |

**States.** Default: step 1. Filtered: one type in color. Selected: one line + card. Reset button appears whenever a filter, search or selection is active.

**Phones.** Chart full width, labels move into a list under the chart; tap selects the nearest line. **Keyboard.** Arrow keys move through the 60 lines in order of reach; Enter opens the card; Escape closes. **Reduced motion.** No line drawing; step changes are instant.

Not built on purpose: zoom on the time axis, free re-sorting. The Gemini twist is cut.

## Chapter 3 · Appointments

Nine in ten global moments were scheduled (7,236 of 7,999), and 98% of those were sport; on 481 of 486 days at least one scheduled event trended in 15 or more countries.

**Data:** `appointments_daily.json` (per UTC day: event count at 15+ countries, widest event's reach, the same two numbers without football and without any sport, gap flag, top events with real searches) and `appointments_compare.json` (event reach for the comparison). **Visual 1:** calendar of 486 days, one square per day, rows Mon–Sun, columns by week, month labels. Count bins: 0 · 1–4 · 5–9 · 10–19 · 20–29 · 30+ (PuBu); reach bins: 15–49 · 50–79 · 80–99 · 100–114 · 115–125. Gap days hatched. **Visual 2:** the comparison bars.

| Element | Trigger | Behavior | Timing |
| --- | --- | --- | --- |
| Step 1 · the calendar | Step card at 50% | Calendar fills week by week; caption "On a typical day there were 13" | Fill 1.2 s, left to right |
| Step 2 · weekends | Step card at 50% | Saturday and Sunday rows stay full strength, weekdays dim to 40%; row labels show averages (24 on Saturday, 7 on Monday) | 300 ms |
| Step 3 · the whole world | Step card at 50% | Switches to widest reach; days over 100 countries outlined (204 days, 199 football). Note: "The news did that 15 times" | 600 ms color |
| Step 4 · the exceptions | Step card at 50% | Non-sport days outlined and labeled: the Oscars, the inauguration, the conclave | 300 ms |
| Filter (unlocks after step 4) | Everything · Without football · Without any sport | Recolors days; sentence updates: 481 → 422 → 61 of 486 days; typical day 13 → 2 | 600 ms |
| Measure toggle | Number of events · Widest reach | Swaps the bins and legend | 600 ms |
| Hover / tap a day | Pointer or tap | Tooltip: date and weekday · number of events · widest event and its reach · up to 3 real searches | 150 ms |
| Caveat box | Always visible after the calendar | Google Trends catches sudden jumps, so football may look more dominant than it is; ▸ How we measured this expands | Expand 300 ms |
| Comparison · guess first | Reader drags a bar | "Real Madrid vs Rayo Vallecano trended in 123 countries. How many searched the Oscars?" Bar follows the drag; Reveal button | Instant |
| Comparison · reveal | Click Reveal (or skip) | Answer: Oscars 81; then the grouped bars (5 widest league matches, 5 widest other sport, 15 non-sport) with the guess marker and a dashed line for a typical match (35 countries) | Bars grow 600 ms |

**States.** Default: count view, Everything. Gap days hatched in every view. Comparison before guess: only the Real Madrid bar and an empty Oscars bar.

**Phones.** Calendar rotates: weeks as rows, Mon–Sun as 7 columns, months down the page; filters become a 3-button segmented control. **Keyboard.** Arrows move day by day in the calendar; the guess bar takes left and right arrows (step 1 country). **Reduced motion.** No fills; steps cut to their states.

Open: the comparison chart may be replaced (board 3e option A: the 20 widest scheduled events, 15 of them Real Madrid or Barcelona). Build the guess-first version until Belen decides. The bridge to Shocks is cut.

## Chapter 4 · Waves

What makes a wave is that it comes back, and each return can build slowly or break at once: of 851 moments that reached 50+ countries, about 1 in 7 was a shock, and the typical one took 12 hours to reach half its countries.

**Data:** `waves_daily.json` (Iran: countries per day, gap days, top searches per day), `waves_speed.json` (two returns on one clock: Syria / fall of Assad and Iran / US strikes, 10-minute curves, pre-trigger countries removed), `waves_chart.json` (18 stories in 3 groups, countries per month for 19 months, month coverage with days collected, notes and labels per peak). **Visuals:** (1) Iran daily area, PuBu; (2) two-returns line chart, same encoding as Shocks (x = hours from the third country), lines in GnBu deep blue (Iran) and teal (Syria); (3) article-level sentence; (4) ridgeline, 18 rows on one month axis, groups in GnBu: crises and politics #0868AC, stars #2E9A8C, tech and companies #5BAA6E.

| Element | Trigger | Behavior | Timing |
| --- | --- | --- | --- |
| Iran daily | Enters view | Area draws left to right; hatched gap days; label "January 2026 had only 5 days of data" | 1.2 s |
| Hover / tap a day (Iran) | Pointer or tap | Tooltip: date · countries · top 3 searches that day | 150 ms |
| Two returns | Enters view | Syria line draws, then Iran; labels "spread over half a day" and "50 countries within the hour" | 1 s each, 300 ms apart |
| Ridgeline step 1 | Step card at 50% | All 18 rows as pale fills in their group color with outlines | Rows fade in top to bottom, 40 ms stagger |
| Step 2 · crises | Step card at 50% | Crises rows fill in blue; others stay pale; one label per lit row (e.g. "Israel–Iran war · 113") | 300 ms |
| Step 3 · stars | Step card at 50% | Stars rows fill in teal; shaded band "awards season" Jan–Mar 2025 and Jan–Mar 2026 | 300 ms |
| Step 4 · tech | Step card at 50% | Tech rows fill in green; band "January 2025" | 300 ms |
| Hover a row | Pointer | Row outline darkens; tooltip at the nearest month: story · month · countries · what brought it back (from notes) | 150 ms |
| Tap a row | Click, tap or Enter | Row opens in place to a daily bar chart of that story with facts of its biggest return; rows below slide down; tap again or Escape to close | 400 ms open/close |
| Group filter | Show only: crises and politics · stars · tech and companies | Same as the step states, reader-controlled; "All" resets | 300 ms |

**Partial months.** Hatched with a label of their days: Nov 2024 4/30, Sep 2025 21/30, Dec 2025 28/31, Jan 2026 5/31, May 2026 17/31 (the archive ends May 17). Values there are lower bounds; the note says so.

**States.** Default ridgeline: step 1 (all pale). One row open at a time. **Phones.** Ridgeline rows 44 px tall, labels above each row, months every 3; the open row becomes a full-width panel. **Keyboard.** Up and down arrows move between rows; Enter opens; left and right move through months in a focused row. **Reduced motion.** No drawing or stagger; open rows appear without sliding.

## Chapter 5 · Rituals

Some shared moments are habits: on a usual day weather starts trending in about 20 countries at 6 a.m. local time, and every year the world returns to the same holidays, even when their dates move. "Weather tomorrow" is cut.

**Data:** `weather_day.json` (per country: typical UTC hour of the 6 a.m. weather peak, time zone per day, top phrasing; usual day = mean countries starting to trend per local hour over 472 full days; every day × 24 local hours grid; gap days) and `rituals.json` (holiday groups, daily countries per holiday for both occurrences, peak days, fixed vs moving, countries both years). **Visuals:** (1) Equal Earth world map with solar-time meridians; (2) usual-day line (GnBu blue #0868AC) over a day × hour grid (PuBu, scale); (3) holiday circle and its unrolled timelines (fixed dates GnBu green #5BAA6E, moving dates GnBu blue #0868AC, first occurrence as grey ghost #D3D8E0); (4) small map of countries both years.

| Element | Trigger | Behavior | Timing |
| --- | --- | --- | --- |
| Weather map | Enters view | Shows 12:00 UTC: countries at their 6 a.m. lit in GnBu blue, others #E1E5EB; the 6 a.m. meridian bold, other hours faint dashed | Static on entry |
| ▶ Play one day | Click | World time runs 00:00 → 23:00; the 6 a.m. line sweeps west and countries light as it passes | 12 s per day (0.5 s per hour), loops once |
| Scrubber | Drag or arrow keys | Stops at any hour; caption updates ("12:00 world time: 6 a.m. in Mexico and Central America") | Instant |
| Pick your country | Select (125) | Country outlined; card: its 6 a.m. in UTC and how it writes the search ("clima", "tempo", "天気") | 300 ms |
| Usual day | Enters view | Line and grid appear together; label "6 a.m.: about 20 countries" | 600 ms fade |
| Hover an hour / a day | Pointer or tap | Hour: its average countries. Day row: date and the countries that searched at 6 a.m. | 150 ms |
| Holiday step 1 | Step card at 50% | Circle of the year with each holiday's first occurrence as spikes (length = countries per day), labeled | Spikes grow 800 ms |
| Step 2 | Step card at 50% | First occurrence turns grey; the second draws over it. Fixed dates land on their ghosts; moving dates rotate, labeled with the shift ("Easter · 15 days earlier") | Rotation 1.2 s |
| Step 3 | Step card at 50% | The circle opens at January 1 into two stacked timelines, first above, second below | 1.2 s morph |
| Step 4 | Step card at 50% | Connectors join each holiday's two peaks: straight for the same date, slanted when it moved | 600 ms |
| Tap a holiday | Click or tap | Small map of countries where it trended both years + sentence (e.g. Ramadan, 77 countries both years) | 300 ms |
| Filter | All · Fixed dates · Moving dates | Fades the other set to 15% | 300 ms |

**States.** Map default 12:00 UTC. Holidays default after steps: unrolled with connectors, Ramadan selected. **Phones.** Map full width; the circle at 340 px; unrolled timelines scroll vertically as two rows with months every 2. **Keyboard.** Play is a button; arrows scrub hours; Tab through holidays, Enter opens the map. **Reduced motion.** No play loop (Play steps one hour per press), no rotation or morph: steps swap states.

"Is it down?" is cut; the board's note says so.

## Closing · Two ways to be together

Shocks line up on the world's clock; rituals line up on each country's own: on local clocks 116 of 120 countries search the weather at 6 a.m., while 110 of 120 searched for Pope Francis within the same world hour.

**Data:** `two_clocks.json`: per country (120), its row order east to west, the UTC hour and local hour of its usual weather peak, the UTC and local time it first searched for Pope Francis; New Year's Eve peaks for the 48 countries with a clear one. **Visual:** dot plot, one row per country (east at top, west at bottom, country labels every few rows), x = 24 hours. Weather dots GnBu teal #2E9A8C, Pope Francis dots GnBu blue #0868AC. Toggle World time / Local time.

| Element | Trigger | Behavior | Timing |
| --- | --- | --- | --- |
| Step 1 · weather, world clock | Step card at 50% | Weather dots on world time form a staircase (the morning moves west); Chile marked | Dots fade in by row, 15 ms stagger |
| Step 2 · local clock | Step card at 50% | Toggle flips to Local time: dots slide horizontally into one line at 6 a.m.; rows never move | 900 ms |
| Step 3 · Pope Francis | Step card at 50% | Weather dots fade to 20%; Pope dots appear in one column on world time, then scatter on local time (two panels side by side) | 600 ms fade, 900 ms slide |
| Toggle (after steps) | World time · Local time | Moves every visible dot horizontally | 900 ms |
| Event picker | Weather · Pope Francis · New Year's Eve | Swaps the dots (New Year's Eve: each country at its own midnight) | 600 ms |
| Pick your country | Select | Its row lights up in every view (#121A26 ring + label) | 300 ms |
| Hover / tap a dot | Pointer or tap | Tooltip: country · world time · local time · event | 150 ms |

**Closing text.** After the chart: the four kinds in one paragraph, then the admission that our own rule (15 countries within an hour) caught the weather only once (a May morning, 13 European countries), then the hand-off line: "So what did your country share with the world, and what did it keep to itself?"

**States.** Default: weather, world time. **Phones.** Rows at 4 px, labels for 6 reference countries only; toggle sticky at the top of the chart. **Keyboard.** Toggle with Space; arrows move country by country; picker is a select. **Reduced motion.** Dots jump between clocks without sliding.

No contrasting color here: both events stay in the GnBu family; the clocks are told apart by position.

## Your turn · Pick any hour, then your country

The reader explores alone: every hour of the 18 months on a map where countries searching the same thing share a color, then a Country Wrapped card for their own country.

**Data:** `frames/YYYY-MM.json`, one file per month, loaded on demand (only April 2025 is built today; the pipeline must export all 19 months): per hour, the shared topics active (topic, kind, countries, countries new in the last 3 hours, member countries), each country's top search, gap hours. `days.json`: per day the widest moment and its kind, gap flag. `wrapped/XX.json` per country: local share and rank, global moments joined, shocks joined, first-to-search share, waves ridden, scheduled share, weather hour and phrasing, holidays both years, search twins, biggest day, top local searches. **Visuals:** Equal Earth map, day strip, hour slider, legend list, Wrapped card.

| Element | Trigger | Behavior | Timing |
| --- | --- | --- | --- |
| Default on arrival | Section enters view | Monday, April 21, 2025, 08:00 world time (Pope Francis), so the reader starts on a moment they know | Map fades in 600 ms |
| Map colors | Every frame | Top 5 shared topics colored, in GnBu order: shocks take deep blue #0868AC, then teal, green, sky, aqua. Strong color when over half of a topic's countries started it in the last 3 hours; pale when it lingers. Country with its own search: #E6E8EC; no data: #F1F2F5 | Color 300 ms |
| Legend list | Every frame | Up to 5 topics: name · "104 countries, 102 in the last 3 hours" or "lingering from earlier"; last row "its own search (hover to see it)" | With the map |
| Hour slider + ▶ | Drag, arrows, or Play | Moves through 24 hours of the chosen day | Play 1 s per hour |
| Day strip | Click a bar or drag the handle | Each bar is the day's widest moment (height = countries; shocks deep blue, appointments grey #AEB8C6, others #C9CFD8); hatched gap days. Choosing a day keeps the hour | Instant; frames file loads in the background with a skeleton map |
| Jump buttons | Click | Pope Francis dies · ChatGPT goes down · Champions League final · New Year's Eve · Iran, US strikes | Map cross-fades 300 ms |
| Hover / tap a country | Pointer or tap | Tooltip: country · local time · its top search (translated) · the shared topic it is part of, if any | 150 ms |
| Gap hour | Day or hour without data | Map hatched with "No data for this hour: Google's collection had a gap" | Instant |
| Country Wrapped | Select a country (dropdown, defaults to the reader's locale if known, else Mexico) | Card: what it kept to itself (share, rank, 5 local searches) · what it shared (global moments joined, biggest shocks joined, first to search\*, waves ridden, scheduled share vs typical, weather hour and phrasing, holidays both years) · search twins · biggest day. Footnote on feed frequency | 300 ms |
| Compare | Below the card | Short lines for Japan, United States, Brazil (or the reader's picks) | Static |

**States.** Loading frames: grey map with "Loading April 2025…". Empty card fields: "Almost everything it searched, it shared." **Phones.** Map full width; legend below; slider and day strip stacked, 44 px handles; card full width. **Keyboard.** Left and right arrows change the hour, Page Up and Page Down the day; Tab to the jump buttons and the country select. **Reduced motion.** Play steps one hour per press; no cross-fades.

Pipeline fix still open: grouped local topics use the shared word as a label ("juarez: becas benito"); use the main member's full name.

## Build plan for Claude Code

Build the article as a static site in the `world-attention` repo: Vite + vanilla JavaScript modules + D3 v7 + Scrollama, deployed to GitHub Pages, one chapter per milestone, each reviewed in the browser before the next.

**Stack.** Vite 5; D3 v7 (`d3-geo` `geoEqualEarth`); Scrollama 3 (offset 0.5); TopoJSON `world-atlas` 50m for land and countries; Google Fonts Source Serif 4 and Libre Franklin. No framework. CSS custom properties hold every color in Global rules.

**Files.**

```
site/
  index.html            article text and chapter containers, in story order
  src/main.js           loads data, starts Scrollama, mounts chapters
  src/styles.css        type, layout, color tokens, reduced motion
  src/lib/              tooltip.js, scrolly.js, table.js (Show the data), search.js, a11y.js
  src/charts/           opening.js, local.js, shocks.js, appointments.js, waves.js, rituals.js, clocks.js, yourturn.js
  public/data/          aggregated JSON only (list below)
scripts/export_site_data.py   builds public/data from the pipeline outputs
.github/workflows/pages.yml   build and deploy
```

**Data files** (all aggregated, each with `source` and `as_of`): opening.json, local.json, shocks\_chart.json, appointments\_daily.json, appointments\_compare.json, waves\_daily.json, waves\_speed.json, waves\_chart.json, weather\_day.json, rituals.json, two\_clocks.json, days.json, frames/2024-11.json … frames/2026-05.json, wrapped/XX.json. Keep each frames file under 1 MB gzipped.

**Never commit:** API keys, private samples, verification or review files, shocks.json, data/export, SHOCK\_VALIDATION reports, CSV or parquet. Add them to `.gitignore` before the first commit and check `git status` before every push.

**Milestones.**

1. Skeleton: page, type, color tokens, Scrollama engine, tooltip, Show-the-data table, reduced-motion switch.
2. Opening, then Most stay home.
3. Shocks.
4. Appointments.
5. Waves.
6. Rituals.
7. Closing.
8. Your turn (frames loading last).
9. QA: 375 px phone, keyboard only, screen reader labels, `prefers-reduced-motion`, Lighthouse accessibility ≥ 95, no console errors; deploy.

**Open decisions before or during the build.**

- [ ] Belen OKs publishing `shocks_chart.json` (60 shocks, derived from the excluded shocks.json; aggregated curves and labels only).
- [ ] Appointments comparison: keep guess-first bars or switch to board 3e option A.
- [ ] Export frames for all 19 months (only April 2025 exists).
- [ ] Reader's country default: browser language only, no IP lookup.
- [ ] Fix grouped-topic labels in Wrapped.
- [ ] Methods text: 475 → 474.

**The prompt to paste into Claude Code** (with this spec saved as `docs/SPEC.md` and the final boards in `docs/boards/`):

```text
You are building "All at Once", an NYT/Upshot-style scrollytelling article for my CS 448B final, in the world-attention repo.

Read first: docs/SPEC.md (the build contract: global rules, eight chapters, build plan) and the reference boards in docs/boards/*.html (open them; they are the visual target). Where a board and the spec disagree, the spec wins.

Stack: Vite + vanilla JS modules + D3 v7 + Scrollama, static site in site/, deployed to GitHub Pages by .github/workflows/pages.yml. No framework.

Rules:
- Colors: PuBu only where color measures how many countries; GnBu steps only where color tells topics apart; neutrals for everything else. Put them in CSS custom properties.
- Motion only presents a change; end states are static. Honor prefers-reduced-motion everywhere.
- Every hover has a tap equivalent; keyboard works in every chart; every chart has Show the data and an aria-label stating its takeaway.
- Data: write scripts/export_site_data.py to build aggregated JSON into site/public/data from the pipeline outputs. Never commit API keys, samples, verification or review files, shocks.json, data/export, SHOCK_VALIDATION reports, CSV or parquet. Update .gitignore first and show me git status before any push.

Work milestone by milestone as in the spec's build plan. After each milestone: run the dev server, tell me what to check in the browser, list anything in the spec you could not follow, and wait for my OK before the next one. Start with milestone 1 (skeleton) and the export script for the Opening data.
```
