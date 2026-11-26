// "Methodology" text for every chart (docs/SPEC.md, Global rules · Interaction). One entry per chart, in story
// order. Each covers: source and collection, what counts, how countries and searches are counted, time rules.
// The Opening text follows the spec; the others are drafts from the spec, the boards and the data notes (for review).

const SOURCE = "Source: Google Trends “Trending Now” national feeds for 125 countries, archived every 10 minutes from Nov. 27, 2024, to May 17, 2026 (GoogleTrendArchive on Hugging Face). This analysis uses the GoogleTrendArchive snapshot from Nov. 27, 2024, to May 17, 2026 (revision 29ffe37172a0c9b73297493141789d9732eca09b); the archive has since been extended to Nov. 13, 2026. English topic names and translations were generated with Claude, an AI model, and spot-checked by hand.";
const FEEDS = "Every count uses the 125 national feeds. Only for the weather hour in the United States, Canada and Russia, which span many time zones, do we use their regional feeds, each region in its own zone.";
const GAPS = "Google’s collection has gaps on a few days; those days are hatched and their counts are lower bounds.";

export const METHODS = {
  opening: [
    `${SOURCE} Each country has one national list, refreshed every 10 minutes, so countries that appear in the same refresh tie. ${FEEDS}`,
    "A country counts as soon as the topic appears on its trending list. The topic is merged: every spelling and language of Pope Francis (“papa francisco”, “ローマ教皇”, “mort du pape”…) counts as one. Of the 125 countries in the archive, 123 had him trending within 24 hours of the announcement.",
    "“Searched as” lists up to three Pope titles that trended in that country at its first refresh, local-language titles first, then by searches. Titles appear as they trended in each country’s feed; many countries search world news in English. The archive stores titles in lower case.",
    "We added 21 titles, most of them in local languages and found by hand in the same refreshes, to the Pope Francis event, together with the topics they belong to (which also hold “pope”, “папа римський” and “教宗” in a few countries), from 2 hours before the announcement to 24 hours after: Sweden “påve franciskus”; Russia “папа римский”; Portugal “papa”; the Netherlands “paus”, “paus overleden”; South Korea “교황”; Belgium “pape”, “paus”; Croatia “papa”; Vietnam “giáo hoàng francis”; Italy “papa francesco pasqua”; Austria “papst”; Japan “ローマ教皇”; Poland “papiez”, “папа римский”; Switzerland “papst”; Czechia “papež”; Latvia “папа римский”; Bosnia and Herzegovina “papa”; Israel “папа римский”; Moldova “papa de la roma”.",
    "Times are UTC. Local time uses each country’s capital, on that date. In countries with several time zones the clock differed elsewhere; at 07:50 UTC it was 3:50 a.m. in Washington and 12:50 a.m. in Los Angeles.",
  ],
  local: [
    `${SOURCE}`,
    "A topic is every search Google’s feeds group under one subject, merged across languages by our pipeline (about 683,000 topics in 18 months). We count the countries whose national list ever had it trending: 1 country, 2 to 14, or 15 or more.",
    "The falling words are a fixed random sample of real searches from each pile (the most common phrasing of each topic, with an English translation when it differs), not one word per topic: pile heights follow the shares. Junk topics and hidden topics are left out, and every sampled topic trended at least 3 times. To protect private individuals, topics about people who trended in fewer than 15 countries are not shown.",
  ],
  shocks: [
    `${SOURCE}`,
    "A global moment is a topic trending in 15 or more countries within one hour. A shock is a global moment nobody scheduled. These are the 60 widest, each checked by hand and counted at event level: the main topic plus the topics accepted as the same event, from 2 hours before the moment to 24 hours after.",
    "Each line counts the countries trending every 10 minutes for 3 hours, timed from the third country to start (so one early feed doesn’t set the clock). Types: deaths and outages from a keyword rule and hand labels; politics or conflict and other from the pipeline’s sub-kind rule.",
    "Times are UTC; countries in the same 10-minute refresh tie.",
  ],
  appointments: [
    `${SOURCE}`,
    "An appointment is a global moment (15 or more countries within an hour) that was on the calendar: a match, a ceremony, a launch. Each event counts once, on the day of its scheduled start (or of its first moment). Its reach is the number of countries where any topic about it trended in its window.",
    "Days are UTC days. “Without football” and “without any sport” remove those events and recount. Typical-day figures use full-coverage days only. " + GAPS,
    "Google Trends catches sudden jumps in searching, so events that spike, like football matches, may look more dominant than they are.",
  ],
  compare: [
    `${SOURCE}`,
    "Reach = countries where any topic about the event trended in its window. League matches are domestic league games identified from their searches, so their counts are lower bounds. Non-sport events come from our catalogue and were checked by hand; events made of a single topic are left out.",
    "The dashed line is a typical match: the median reach of football events.",
  ],
  iran: [
    `${SOURCE}`,
    "Countries per UTC day whose national list had any Iran topic trending; Iran and the Iran–Israel war are merged into one story. The tooltip shows the day’s top 3 searches, ranked by countries.",
    GAPS + " January 2026 has only 5 days of data.",
  ],
  speed: [
    `${SOURCE}`,
    "Two returns of one wave on one clock: cumulative new countries, timed from the third new country’s first trend, every 10 minutes for 6 hours and then hourly, up to 24 hours. Countries already searching the story in the 24 hours before are left out, so each line counts only the return.",
    "The comparison: every non-sport moment that reached 50 or more countries within 72 hours. Times are UTC.",
  ],
  ridge: [
    `${SOURCE}`,
    "A wave is a story that keeps coming back. These 18 were checked by hand as recurring, taken from the top of a list ranked by months with 15 or more countries (Venezuela and Nicolás Maduro are merged). Each row counts, per month, the countries where any of the story’s topics trended at least once.",
    "Partial months are hatched and labeled with their days collected (Nov. 2024 4/30, Sep. 2025 21/30, Dec. 2025 28/31, Jan. 2026 5/31, May 2026 17/31); values there are lower bounds. What brought a story back comes from hand-written notes, else the month’s biggest moment.",
  ],
  weathermap: [
    `${SOURCE}`,
    `Weather counts only “today” searches (“clima”, “tempo”, “天気”…); “weather tomorrow” is left out. Each country’s hour is the local hour with the most weather trends over the archive (20 or more trends). ${FEEDS}`,
    "The map shows world time (UTC) with solar-time meridians; a country lights up when it is 6 a.m. there on its typical clock.",
  ],
  usualday: [
    `${SOURCE}`,
    "Same weather searches as the map. The line is the mean number of countries where a weather trend started in each local hour (0–23), over the 472 full-coverage days. Each row of the grid is one local day; days on or next to a collection gap are marked.",
    "Hours are each country’s local clock, not UTC.",
  ],
  holidays: [
    `${SOURCE}`,
    "Holidays that appear twice in the archive (Halloween, Diwali and Eid al-Adha appear once and are left out). Each holiday is a hand-checked group of topics (about 90% precise). Countries are counted per UTC day, from 10 days before each holiday date to 5 days after.",
    "A holiday is “moving” when its date shifted by more than 3 days between the two years. “Both years” counts the countries where it trended in both windows.",
  ],
  clocks: [
    `${SOURCE}`,
    `One row per country, east at the top, by the capital’s UTC offset on Apr. 21, 2025. Weather = the hour its “today” weather searches usually peak. Pope Francis = its first trend on Apr. 21, 2025, as in the Opening, on the capital’s clock. New Year’s Eve 2025/26 = its peak, for the 48 countries with a clear one (2 or more trends in the peak 10 minutes, no tie).`,
    `World time is UTC (the weather day runs 15:00 to 15:00 UTC so the morning stays in one piece); local time is each country’s wall clock. ${FEEDS}`,
  ],
  yourturn: [
    `${SOURCE}`,
    "Each hour, a country shows its top active trend. A shared topic is one active in two or more countries that hour; the five widest are colored. A topic is strong when over half of its countries started it in the last 3 hours, pale when it lingers. Hidden topics never appear: they are sensitive searches (crime, death, sexual content and the like) seen in two countries or fewer, plus junk entries such as single characters; they still count in totals.",
    "The day strip shows each UTC day’s widest moment (shocks and appointments at event level). Country Wrapped is built from the same 18 months; feeds that refresh less often catch fewer short trends.",
    GAPS,
  ],
};

/** The Methodology panel's HTML for a chart key. */
export const methodologyHtml = (key) => (METHODS[key] || []).map((p) => `<p>${p}</p>`).join("");
