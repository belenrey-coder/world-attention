# Story candidates

_Analysis of the pipeline outputs (`moments.parquet`, `topics.parquet`); not a pipeline step. National feeds only. A moment is one topic in one burst of attention (see DECISIONS.md, Step 4). Sport is included._

## Headlines (read with the tables below)

- **Sport owns reach.** 39 of the top 40 single moments by reach are football matches; the only exception is the ChatGPT outage of 23 Jan 2025 (121 countries). PSG vs Bayern (4 Jul 2025, Club World Cup) reached all 125 countries; El Clásico peaked at 124 (11 May 2025). Use the sport-free list (`GLOBAL_MOMENTS_NO_SPORT.md`) for anything about shared reactions.
- **Shocks are mostly deaths and outages.** Diogo Jota (120 countries), Hulk Hogan (118), Eric Dane (112), Ozzy Osbourne (110), Jimmy Carter (109) and the Cloudflare outage (95) reach half their countries within an hour or two.
- **AI is the clearest non-sport wave.** ChatGPT trended in 120–123 countries a month in Dec 2024–Jan 2025, and its outages are among the fastest big moments (121 countries, 23 Jan 2025). DeepSeek was a one-month burst (118 countries in Jan 2025, then ≤ 32). Gemini and Claude grow late: Claude was at ≤ 22 countries a month until Oct 2025, jumped to 64 in Nov 2025, and reached 57–75 in Feb–Apr 2026.
- **News waves:** the Epstein files peak in Dec 2025–Feb 2026 (95 countries in Feb 2026). Tariffs are a 2 Apr 2025 spike (28 countries in one moment). The April 2025 market fall peaks on 7 Apr (S&P 500 in 47 countries). Gold price climbs into 2026 (51–61 countries a month at its highs).
- **Rituals are the most persistent topics.** Weather trended in 10+ countries on 295 days, weather forecasts on 193. Holidays (New Year, Earth Day, Women's Day, Valentine's) are the biggest ritual moments. The Ramadan/Eid "when is" searches peak with the start of Ramadan (57 countries, 26 Feb 2025).
- **Collection gaps:** Sep 2025, 7–10 Dec 2025 and most of Jan 2026 are missing, so monthly series dip there, e.g. ChatGPT shows 0 countries in Jan 2026.

**Measures**: reach = countries in one moment; speed = minutes until half of a moment's countries had started (moments of 30+ countries); persistence = days on which the topic trended in 10+ countries; recurrence = number of separate moments of 10+ countries.

## 1. Top 40 topics by each measure

### (a) Reach: countries in one moment

| # | topic | countries | date | type | tag |
|---|---|---|---|---|---|
| 1 | Paris Saint-Germain vs Bayern Munich | 125 | 2025-07-04 | sports_match | appointment |
| 2 | Barcelona vs Real Madrid | 124 | 2025-05-11 | sports_match | appointment |
| 3 | Paris Saint-Germain vs Arsenal | 124 | 2025-04-28 | sports_match | appointment |
| 4 | Borussia Dortmund vs Barcelona | 124 | 2025-04-15 | sports_match | appointment |
| 5 | Real Madrid vs Arsenal | 123 | 2025-04-07 | sports_match | appointment |
| 6 | Benfica vs Barcelona | 123 | 2025-03-11 | sports_match | appointment |
| 7 | Valencia vs Barcelona | 123 | 2025-02-06 | sports_match | appointment |
| 8 | Real Madrid vs Athletic Bilbao | 123 | 2025-04-20 | sports_match | appointment |
| 9 | Real Madrid vs Celta Vigo | 123 | 2025-05-03 | sports_match | appointment |
| 10 | Barcelona vs Paris Saint-Germain | 123 | 2025-09-30 | sports_match | appointment |
| 11 | Paris Saint-Germain vs Tottenham Hotspur | 123 | 2025-08-12 | sports_match | appointment |
| 12 | Real Madrid vs Barcelona | 122 | 2025-01-11 | sports_match | appointment |
| 13 | Espanyol vs Barcelona | 122 | 2026-01-03 | sports_match | appointment |
| 14 | Atlético Madrid vs Barcelona | 122 | 2025-04-02 | sports_match | appointment |
| 15 | Real Madrid vs Atlético Madrid | 122 | 2025-03-12 | sports_match | appointment |
| 16 | Real Madrid vs Leganés | 122 | 2025-02-05 | sports_match | appointment |
| 17 | Barcelona vs Girona | 122 | 2025-03-29 | sports_match | appointment |
| 18 | Barcelona vs Villarreal | 122 | 2025-05-17 | sports_match | appointment |
| 19 | Barcelona vs Las Palmas | 122 | 2025-02-22 | sports_match | appointment |
| 20 | Elche vs Barcelona | 122 | 2025-11-01 | sports_match | appointment |
| 21 | Talavera vs Real Madrid | 122 | 2025-12-17 | sports_match | appointment |
| 22 | Paris Saint-Germain vs Atlético Madrid | 122 | 2025-06-14 | sports_match | appointment |
| 23 | Club Brugge vs Barcelona | 122 | 2025-11-05 | sports_match | appointment |
| 24 | ChatGPT | 121 | 2025-01-23 | product | wave |
| 25 | Liverpool vs Tottenham Hotspur | 121 | 2024-12-21 | sports_match | appointment |
| 26 | Barcelona vs Mallorca | 121 | 2024-12-03 | sports_match | appointment |
| 27 | Getafe vs Barcelona | 121 | 2025-01-18 | sports_match | appointment |
| 28 | Real Madrid vs Getafe | 121 | 2025-04-23 | sports_match | appointment |
| 29 | Real Madrid vs Girona | 121 | 2024-12-07 | sports_match | appointment |
| 30 | Barcelona vs Inter Milan | 121 | 2025-05-06 | sports_match | appointment |
| 31 | Real Madrid vs Sevilla | 121 | 2024-12-21 | sports_match | appointment |
| 32 | Aston Villa vs Liverpool | 121 | 2025-02-18 | sports_match | appointment |
| 33 | Barcelona vs Celta Vigo | 121 | 2025-04-19 | sports_match | appointment |
| 34 | Leicester City vs Manchester City | 121 | 2024-12-29 | sports_match | appointment |
| 35 | Manchester City vs AFC Bournemouth | 121 | 2025-03-30 | sports_match | appointment |
| 36 | Real Betis vs Real Madrid | 121 | 2025-02-28 | sports_match | appointment |
| 37 | Elche vs Real Madrid | 121 | 2025-11-23 | sports_match | appointment |
| 38 | Real Madrid vs RB Salzburg | 121 | 2025-01-22 | sports_match | appointment |
| 39 | Real Valladolid vs Barcelona | 121 | 2025-05-03 | sports_match | appointment |
| 40 | Barcelona vs Real Sociedad | 121 | 2025-03-01 | sports_match | appointment |

### (b) Speed: minutes to half its countries (moments of 30+ countries)

Times are on the scraper's 10-minute grid, so 0–10 min means half the countries appeared in the same scrape. Such ties are partly a collection effect, not proof of simultaneous attention; *19 UTC* marks moments that start in the 19:00 UTC collection hour (CHECKS.md C4).

| # | topic | min to half | countries | date | 19 UTC | type | tag |
|---|---|---|---|---|---|---|---|
| 1 | Barcelona vs Atlético Madrid | 0 | 56 | 2025-06-07 16:20 |  | sports_match | appointment |
| 2 | Senny Mayulu | 0 | 54 | 2025-05-31 20:40 |  | person | shock |
| 3 | Panama Canal | 0 | 44 | 2025-01-20 17:30 |  | place | shock |
| 4 | Okami | 0 | 34 | 2024-12-13 03:40 |  | media | shock |
| 5 | Divinity (video game series) | 0 | 32 | 2025-12-12 01:20 |  | media | shock |
| 6 | ChatGPT | 10 | 121 | 2025-01-23 11:40 |  | product | wave |
| 7 | Atlético Madrid vs Valencia | 10 | 119 | 2025-12-13 12:00 |  | sports_match | appointment |
| 8 | Chelsea vs Leeds United | 10 | 116 | 2025-12-03 19:20 | yes | sports_match | appointment |
| 9 | Brighton vs Chelsea | 10 | 115 | 2025-02-14 19:00 | yes | sports_match | appointment |
| 10 | Manchester City vs Salford City | 10 | 114 | 2026-02-14 14:00 |  | sports_match | appointment |
| 11 | WSG Tirol vs Real Madrid | 10 | 114 | 2025-08-12 16:00 |  | sports_match | appointment |
| 12 | Atlético Madrid vs Rayo Vallecano | 10 | 113 | 2025-04-24 18:30 |  | sports_match | appointment |
| 13 | Bayern Munich vs 1. FC Köln | 10 | 112 | 2026-05-16 12:30 |  | sports_match | appointment |
| 14 | Atlético Madrid vs Real Sociedad | 10 | 110 | 2026-03-07 16:30 |  | sports_match | appointment |
| 15 | Ozzy Osbourne | 10 | 110 | 2025-07-22 18:00 |  | person | shock |
| 16 | Atlético Madrid vs Celta Vigo | 10 | 104 | 2026-05-09 15:30 |  | sports_match | appointment |
| 17 | AC Milan vs Feyenoord | 10 | 103 | 2025-02-18 16:40 |  | sports_match | appointment |
| 18 | Monza vs Inter Milan | 10 | 102 | 2025-08-12 18:30 |  | sports_match | appointment |
| 19 | Pope Francis | 10 | 101 | 2025-04-21 07:50 |  | person | appointment |
| 20 | Al-Nassr vs Al-Wasl | 10 | 100 | 2025-02-03 17:00 |  | sports_match | appointment |
| 21 | Al-Qadsiah vs Al-Nassr | 10 | 100 | 2025-04-18 17:00 |  | sports_match | appointment |
| 22 | RB Salzburg vs Bayern Munich | 10 | 100 | 2025-01-06 16:00 |  | sports_match | appointment |
| 23 | FC Cincinnati vs Inter Miami | 10 | 99 | 2025-07-26 22:30 |  | sports_match | appointment |
| 24 | Al-Nassr vs Al-Ittihad | 10 | 98 | 2024-12-06 16:00 |  | sports_match | appointment |
| 25 | Atlético Madrid vs Villarreal | 10 | 98 | 2025-01-25 14:10 |  | sports_match | appointment |
| 26 | Dinamo Zagreb vs Real Betis | 10 | 98 | 2025-12-11 16:50 |  | sports_match | appointment |
| 27 | Marbella vs Atlético Madrid | 10 | 98 | 2025-01-04 19:30 | yes | sports_match | appointment |
| 28 | Atlético Madrid vs Levante | 10 | 97 | 2025-11-08 16:30 |  | sports_match | appointment |
| 29 | Real Oviedo vs Atlético Madrid | 10 | 97 | 2026-02-28 19:00 | yes | sports_match | appointment |
| 30 | Al-Riyadh vs Al-Nassr | 10 | 96 | 2026-02-02 14:20 |  | sports_match | appointment |
| 31 | Google Gemini | 10 | 96 | 2025-01-23 11:40 |  | product | wave |
| 32 | Atlético Madrid vs Sevilla | 10 | 95 | 2025-11-01 14:20 |  | sports_match | appointment |
| 33 | Al-Raed vs Al-Nassr | 10 | 94 | 2025-01-30 16:00 |  | sports_match | appointment |
| 34 | Esteghlal vs Al-Nassr | 10 | 94 | 2025-03-03 15:00 |  | sports_match | appointment |
| 35 | Fiorentina vs Real Betis | 10 | 94 | 2025-05-08 18:10 |  | sports_match | appointment |
| 36 | Al-Khaleej vs Al Nassr | 10 | 93 | 2025-01-21 13:50 |  | sports_match | appointment |
| 37 | Al-Nassr vs Al-Ettifaq | 10 | 93 | 2025-12-30 16:30 |  | sports_match | appointment |
| 38 | Atlético Madrid vs RCD Mallorca | 10 | 92 | 2025-02-01 16:30 |  | sports_match | appointment |
| 39 | Sportfreunde Siegen vs Borussia Dortmund | 10 | 92 | 2025-07-30 15:50 |  | sports_match | appointment |
| 40 | Strasbourg vs Paris Saint-Germain | 10 | 92 | 2026-02-01 18:50 |  | sports_match | appointment |

### (c) Persistence: days trending in 10+ countries

| # | topic | days in 10+ countries | countries_total | type | tag |
|---|---|---|---|---|---|
| 1 | Weather | 295 | 123 | other | ritual |
| 2 | Weather forecast | 193 | 124 | other | ritual |
| 3 | FC Barcelona | 97 | 125 | team | appointment |
| 4 | Real Madrid CF | 96 | 125 | team | appointment |
| 5 | La Liga | 96 | 124 | event | appointment |
| 6 | Carlos Alcaraz | 93 | 103 | person | appointment |
| 7 | Premier League | 90 | 123 | event | appointment |
| 8 | Jannik Sinner | 88 | 98 | person | appointment |
| 9 | NBA | 87 | 120 | event | appointment |
| 10 | Chelsea FC | 85 | 123 | team | appointment |
| 11 | Arsenal FC | 85 | 123 | team | appointment |
| 12 | Manchester City | 85 | 115 | team | appointment |
| 13 | Aryna Sabalenka | 84 | 84 | person | appointment |
| 14 | Alexander Zverev | 83 | 50 | person | appointment |
| 15 | Liverpool FC | 81 | 119 | team | appointment |
| 16 | Iga Świątek | 79 | 62 | person | appointment |
| 17 | Manchester United | 76 | 118 | team | appointment |
| 18 | Inter Milan | 73 | 105 | team | appointment |
| 19 | Galatasaray S.K. | 73 | 80 | team | appointment |
| 20 | UEFA Champions League | 67 | 125 | event | appointment |
| 21 | Atlético Madrid | 67 | 107 | team | appointment |
| 22 | Juventus | 67 | 100 | team | appointment |
| 23 | Paris Saint-Germain FC | 66 | 125 | team | appointment |
| 24 | Bayern Munich | 64 | 104 | team | appointment |
| 25 | Tarjeta roja | 61 | 24 | media | wave |
| 26 | AC Milan | 60 | 91 | team | appointment |
| 27 | FC Bayern Munich | 59 | 109 | team | appointment |
| 28 | Al Nassr | 58 | 115 | team | appointment |
| 29 | Novak Djokovic | 57 | 88 | person | appointment |
| 30 | AS Roma | 57 | 66 | team | appointment |
| 31 | SSC Napoli | 56 | 89 | team | appointment |
| 32 | Sporting CP | 56 | 84 | team | appointment |
| 33 | Premier League table | 54 | 67 | other | appointment |
| 34 | Formula One | 53 | 110 | event | appointment |
| 35 | Real Betis | 52 | 105 | team | appointment |
| 36 | Weather tomorrow | 51 | 82 | other | ritual |
| 37 | Fenerbahçe S.K. | 51 | 62 | team | appointment |
| 38 | FC Porto | 50 | 55 | team | appointment |
| 39 | Donald Trump | 49 | 122 | person | appointment |
| 40 | Paris Saint-Germain | 48 | 85 | team | appointment |

### (d) Recurrence: separate moments of 10+ countries

| # | topic | moments of 10+ countries | max_reach | type | tag |
|---|---|---|---|---|---|
| 1 | Weather | 159 | 32 | other | ritual |
| 2 | Weather forecast | 131 | 43 | other | ritual |
| 3 | Real Madrid CF | 93 | 115 | team | appointment |
| 4 | FC Barcelona | 93 | 113 | team | appointment |
| 5 | La Liga | 87 | 101 | event | appointment |
| 6 | Chelsea FC | 86 | 74 | team | appointment |
| 7 | Manchester City | 85 | 70 | team | appointment |
| 8 | Arsenal FC | 85 | 61 | team | appointment |
| 9 | Premier League | 83 | 103 | event | appointment |
| 10 | Liverpool FC | 81 | 89 | team | appointment |
| 11 | Jannik Sinner | 81 | 86 | person | appointment |
| 12 | NBA | 80 | 94 | event | appointment |
| 13 | Carlos Alcaraz | 79 | 94 | person | appointment |
| 14 | Aryna Sabalenka | 77 | 68 | person | appointment |
| 15 | Alexander Zverev | 76 | 33 | person | appointment |
| 16 | Manchester United | 74 | 96 | team | appointment |
| 17 | Inter Milan | 73 | 70 | team | appointment |
| 18 | Galatasaray S.K. | 73 | 60 | team | appointment |
| 19 | Iga Świątek | 71 | 57 | person | appointment |
| 20 | Atlético Madrid | 67 | 82 | team | appointment |
| 21 | Juventus | 66 | 85 | team | appointment |
| 22 | Paris Saint-Germain FC | 65 | 108 | team | appointment |
| 23 | Bayern Munich | 64 | 63 | team | appointment |
| 24 | AC Milan | 60 | 50 | team | appointment |
| 25 | FC Bayern Munich | 59 | 87 | team | appointment |
| 26 | Al Nassr | 58 | 70 | team | appointment |
| 27 | AS Roma | 58 | 41 | team | appointment |
| 28 | Sporting CP | 56 | 74 | team | appointment |
| 29 | SSC Napoli | 56 | 62 | team | appointment |
| 30 | Real Betis | 51 | 84 | team | appointment |
| 31 | Fenerbahçe S.K. | 51 | 38 | team | appointment |
| 32 | UEFA Champions League | 50 | 113 | event | appointment |
| 33 | Formula One | 50 | 78 | event | appointment |
| 34 | FC Porto | 50 | 38 | team | appointment |
| 35 | Paris Saint-Germain | 49 | 46 | team | appointment |
| 36 | Novak Djokovic | 48 | 72 | person | appointment |
| 37 | Lamine Yamal | 47 | 86 | person | appointment |
| 38 | Tarjeta roja | 47 | 21 | media | wave |
| 39 | Coco Gauff | 46 | 70 | person | appointment |
| 40 | Borussia Dortmund | 46 | 68 | team | appointment |

## 2. Shock, appointment, wave, ritual

Tags are rule-based, from the Claude type plus timing, and are a starting point for reading, not ground truth:
- **ritual**: weather, holidays, lotteries, prayer times, daily puzzles and prices, or a product, company or other topic with 15+ separate 10-country moments (outside sport);
- **appointment**: scheduled in advance (sport, finals, awards, elections, releases, launches, draws), and people with 10+ separate 10-country moments (athletes, performers on tour);
- **shock**: unscheduled and sudden (half of its countries within 3 hours, 20+ countries, at most 4 days in 10+ countries);
- **wave**: everything else that spreads more slowly or lasts ("minor" = small and short, not listed).

Counts of tagged topics with a moment of 20+ countries: appointment 3,974, wave 890, shock 694, ritual 120.

### Shock: 15 best examples

| # | topic | max_reach | best_date | best_min_to_half | persistence_days | moments_10plus | type |
|---|---|---|---|---|---|---|---|
| 1 | Diogo Jota | 120 | 2025-07-03 | 60 | 2 | 2 | person |
| 2 | Hulk Hogan | 118 | 2025-07-24 | 20 | 1 | 1 | person |
| 3 | Eric Dane | 112 | 2026-02-20 | 60 | 4 | 3 | person |
| 4 | Michelle Trachtenberg | 110 | 2025-02-26 | 30 | 3 | 2 | person |
| 5 | Ozzy Osbourne | 110 | 2025-07-22 | 10 | 2 | 2 | person |
| 6 | Jimmy Carter | 109 | 2024-12-29 | 40 | 2 | 1 | person |
| 7 | Val Kilmer | 109 | 2025-04-02 | 50 | 1 | 1 | person |
| 8 | Gene Hackman | 106 | 2025-02-27 | 70 | 2 | 2 | person |
| 9 | Diane Keaton | 101 | 2025-10-11 | 40 | 2 | 2 | person |
| 10 | Bianca Censori | 101 | 2025-02-02 | 150 | 2 | 1 | person |
| 11 | Rob Reiner | 99 | 2025-12-15 | 160 | 2 | 2 | person |
| 12 | David Lynch | 99 | 2025-01-16 | 20 | 1 | 2 | person |
| 13 | James Ransone | 97 | 2025-12-21 | 180 | 2 | 1 | person |
| 14 | Cloudflare outage | 95 | 2025-11-18 | 30 | 3 | 3 | company |
| 15 | Michael Madsen | 93 | 2025-07-03 | 70 | 2 | 1 | person |

### Appointment: 15 best examples

| # | topic | max_reach | best_date | best_min_to_half | persistence_days | moments_10plus | type |
|---|---|---|---|---|---|---|---|
| 1 | Paris Saint-Germain vs Bayern Munich | 125 | 2025-07-04 | 1830 | 8 | 5 | sports_match |
| 2 | Barcelona vs Real Madrid | 124 | 2025-05-11 | 330 | 11 | 10 | sports_match |
| 3 | Paris Saint-Germain vs Arsenal | 124 | 2025-04-28 | 1450 | 6 | 5 | sports_match |
| 4 | Borussia Dortmund vs Barcelona | 124 | 2025-04-15 | 250 | 4 | 4 | sports_match |
| 5 | Real Madrid vs Arsenal | 123 | 2025-04-07 | 1970 | 6 | 6 | sports_match |
| 6 | Benfica vs Barcelona | 123 | 2025-03-11 | 540 | 4 | 4 | sports_match |
| 7 | Valencia vs Barcelona | 123 | 2025-02-06 | 770 | 4 | 4 | sports_match |
| 8 | Real Madrid vs Athletic Bilbao | 123 | 2025-04-20 | 420 | 3 | 3 | sports_match |
| 9 | Real Madrid vs Celta Vigo | 123 | 2025-05-03 | 940 | 3 | 3 | sports_match |
| 10 | Barcelona vs Paris Saint-Germain | 123 | 2025-09-30 | 2030 | 2 | 1 | sports_match |
| 11 | Paris Saint-Germain vs Tottenham Hotspur | 123 | 2025-08-12 | 1450 | 2 | 2 | sports_match |
| 12 | Real Madrid vs Barcelona | 122 | 2025-01-11 | 1840 | 15 | 10 | sports_match |
| 13 | Espanyol vs Barcelona | 122 | 2026-01-03 | 890 | 6 | 6 | sports_match |
| 14 | Atlético Madrid vs Barcelona | 122 | 2025-04-02 | 90 | 5 | 5 | sports_match |
| 15 | Real Madrid vs Atlético Madrid | 122 | 2025-03-12 | 300 | 5 | 7 | sports_match |

### Wave: 15 best examples

| # | topic | max_reach | best_date | best_min_to_half | persistence_days | moments_10plus | type |
|---|---|---|---|---|---|---|---|
| 1 | ChatGPT | 121 | 2025-01-23 | 10 | 15 | 10 | product |
| 2 | Venezuela | 117 | 2026-01-03 | 70 | 7 | 9 | place |
| 3 | Iran | 97 | 2026-02-27 | 1200 | 14 | 14 | place |
| 4 | Qatar | 97 | 2025-06-23 | 310 | 2 | 2 | place |
| 5 | Google Gemini | 96 | 2025-01-23 | 10 | 11 | 11 | product |
| 6 | Roblox | 96 | 2025-08-23 | 490 | 6 | 4 | product |
| 7 | Anora | 92 | 2025-03-02 | 920 | 2 | 1 | media |
| 8 | DeepSeek | 89 | 2025-01-26 | 780 | 6 | 3 | company |
| 9 | El Mencho | 89 | 2026-02-22 | 260 | 2 | 1 | person |
| 10 | Ali Khamenei | 88 | 2026-02-28 | 660 | 5 | 5 | person |
| 11 | iPhone 16e | 88 | 2025-02-19 | 300 | 2 | 1 | product |
| 12 | ChatGPT | 86 | 2025-11-18 | 220 | 3 | 3 | product |
| 13 | Andy Byron | 85 | 2025-07-17 | 300 | 2 | 1 | person |
| 14 | Spotify | 84 | 2025-04-16 | 20 | 13 | 12 | company |
| 15 | MacBook Neo | 84 | 2026-03-03 | 1360 | 4 | 2 | product |

### Ritual: 15 best examples

| # | topic | max_reach | best_date | best_min_to_half | persistence_days | moments_10plus | type |
|---|---|---|---|---|---|---|---|
| 1 | New Year's Eve | 119 | 2025-12-30 | 700 | 6 | 2 | holiday |
| 2 | Earth Day | 114 | 2025-04-20 | 2030 | 5 | 3 | holiday |
| 3 | New Year's Day | 112 | 2025-12-31 | 700 | 4 | 2 | holiday |
| 4 | International Women's Day | 109 | 2026-03-07 | 940 | 7 | 3 | holiday |
| 5 | Valentine's Day | 105 | 2025-02-12 | 2400 | 6 | 3 | holiday |
| 6 | Happy New Year 2025 | 99 | 2024-12-29 | 1990 | 2 | 1 | holiday |
| 7 | 2025 New Year | 96 | 2024-12-30 | 1470 | 3 | 2 | holiday |
| 8 | Merry Christmas | 95 | 2025-12-23 | 1610 | 5 | 3 | holiday |
| 9 | Labour Day | 87 | 2026-04-30 | 760 | 4 | 2 | holiday |
| 10 | Father's Day | 87 | 2025-06-12 | 2900 | 2 | 1 | holiday |
| 11 | Eid Mubarak | 82 | 2025-03-29 | 920 | 6 | 3 | holiday |
| 12 | Happy New Year | 82 | 2025-12-30 | 1610 | 5 | 3 | holiday |
| 13 | Easter | 81 | 2025-04-19 | 860 | 7 | 6 | holiday |
| 14 | Christmas | 76 | 2025-12-23 | 1720 | 6 | 3 | holiday |
| 15 | Mother's Day | 75 | 2026-05-08 | 1490 | 10 | 6 | holiday |

## 3. Candidate checks

Each candidate is the set of topics whose (English, Claude) name matches a pattern, optionally limited to a date window. *max reach* = countries in its biggest moment; *moments* = all moments (in brackets: of 10+ countries); *countries* = countries where it ever trended; *peak dates* = the three biggest moments (countries, topic); *top phrasings* = most common raw searches. Rituals "when is …" and "is X down" match the searches themselves (as do prayer times): their *countries* and *top phrasings* count only those searches, while *max reach*, *moments* and *peak dates* describe the topics those searches belong to (e.g. the search 'is fortnite down' sits in the Epic Games topic).

### Sport

| candidate | max reach | moments (10+) | countries | peak dates | top phrasings |
|---|---|---|---|---|---|
| Winter Olympics 2026 | 114 | 628 (35) | 118 | 2026-02-03 (114, 2026 Winter Olympics); 2026-02-10 (106, 2026 Winter Olympics ice hockey); 2026-02-14 (105, 2026 Winter Olympics alpine skiing) | 2026 winter olympics ice hockey; 2026 winter olympics; 2026 winter olympics alpine skiing; 2026 winter olympics men's snowboarding slopestyle; 2026 winter olympics snowboarding; 2026 winter olympics women's snowboarding halfpipe |
| Club World Cup 2025 | 99 | 430 (23) | 121 | 2025-06-12 (99, FIFA Club World Cup); 2025-06-23 (44, FIFA Club World Cup); 2025-07-13 (36, FIFA Club World Cup) | fifa club world cup; mundial de clubes; club world cup; fifa club world cup standings; fifa club world cup brackets; coupe du monde des clubs fifa |
| El Clásico (Real Madrid vs Barcelona) | 124 | 238 (33) | 125 | 2025-05-11 (124, Barcelona vs Real Madrid); 2025-04-25 (123, Barcelona vs Real Madrid); 2025-01-11 (122, Real Madrid vs Barcelona) | real madrid vs barcelona; barcelona vs real madrid; برشلونة ضد الريال; barcelone – real madrid; barca vs real madrid; el clasico |
| Champions League final 2025 (PSG vs Inter, 31 May) | 91 | 46 (5) | 124 | 2025-05-31 (91, PSG vs Inter Milan); 2025-05-31 (64, Paris Saint-Germain vs Inter Milan); 2025-05-30 (30, UEFA Champions League final) | psg vs inter; psg inter; psg - inter; بي اس جي ضد الإنتر; inter vs psg; псж – интер |
| Super Bowl LIX (9 Feb 2025) | 89 | 207 (6) | 105 | 2025-02-08 (89, Super Bowl LIX); 2025-02-09 (55, Super Bowl); 2025-02-08 (35, Super Bowl) | super bowl 2025; super bowl; superbowl; super bowl 2024; eagles vs chiefs; taylor swift super bowl |
| Super Bowl LX (8 Feb 2026) | 74 | 172 (6) | 99 | 2026-02-07 (74, Super Bowl); 2026-02-08 (37, Super Bowl LIX); 2026-02-07 (26, Super Bowl LIX) | superbowl; super bowl 2026; super bowl; super bowl 2025; patriots vs seahawks; bad bunny super bowl |
| London Marathon | 25 | 69 (2) | 38 | 2025-04-26 (25, London Marathon 2025); 2026-04-26 (15, London Marathon 2026); 2025-04-27 (8, London Marathon) | london marathon 2025; london marathon 2026; london marathon; london marathon results; london marathon 2025 results; london marathon 2027 |
| Boston Marathon | 7 | 31 (0) | 14 | 2025-04-21 (7, Boston Marathon 2025); 2026-04-20 (6, Boston Marathon 2026); 2025-04-21 (4, Boston Marathon) | boston marathon 2025; boston marathon 2026; boston marathon; boston marathon results; boston marathon bombing; boston marathon start time |
| Berlin Marathon | 9 | 14 (0) | 12 | 2025-09-21 (9, Berlin Marathon 2025); 2025-06-29 (1, Berlin Half Marathon); 2025-09-01 (1, Berlin Half Marathon) | berlin marathon 2025; berlin marathon; halbmarathon; berlin halbmarathon 2026; berlin half marathon 2026; berlin marathon live |
| Chicago Marathon | 14 | 13 (1) | 17 | 2025-10-12 (14, Chicago Marathon 2025); 2025-10-21 (2, Chicago Marathon); 2025-12-11 (2, Chicago Marathon) | chicago marathon 2025; chicago marathon; chicago marathon 2026; chicago marathon results; chicago marathon tracking; marathon chicago 2025 |
| New York City Marathon | 15 | 15 (1) | 20 | 2025-11-02 (15, New York City Marathon 2025); 2025-11-01 (4, New York City Marathon 2025); 2025-11-02 (2, NYC Marathon tracking) | new york marathon 2025; nyc marathon 2025; marathon new york 2025; new york marathon; nyc marathon 2026; how to track nyc marathon runners |
| Tokyo Marathon | 9 | 19 (0) | 15 | 2025-03-01 (9, Tokyo Marathon 2025); 2026-02-28 (8, Tokyo Marathon 2026); 2025-08-15 (3, Tokyo Marathon 2026) | tokyo marathon 2026; 東京マラソン; tokyo marathon 2025; 東京馬拉松 2026; tokyo marathon; tokyo marathon results |
| World Cup 2026: draw | 43 | 60 (4) | 84 | 2025-12-04 (43, 2026 FIFA World Cup draw); 2025-12-05 (17, FIFA World Cup draw); 2025-12-04 (12, 2026 World Cup draw) | sorteo mundial 2026; قرعة كاس العالم 2026; world cup draw; tirage au sort coupe du monde 2026; grupos del mundial 2026; world cup draw 2026 |
| World Cup 2026: playoffs | 9 | 40 (0) | 34 | 2025-12-05 (9, 2026 FIFA World Cup qualification playof); 2026-03-26 (8, 2026 FIFA World Cup qualification playof); 2025-11-16 (7, Italy football (World Cup 2026 playoffs)) | repechaje mundial 2026; italie foot; repechaje mundial 2026 europa; barrage coupe du monde 2026; bombos mundial 2026; world cup playoffs |

### News

| candidate | max reach | moments (10+) | countries | peak dates | top phrasings |
|---|---|---|---|---|---|
| Epstein files | 68 | 397 (17) | 104 | 2026-01-31 (68, Jeffrey Epstein); 2026-01-31 (45, Epstein files); 2025-12-19 (39, Epstein files) | epstein; jeffrey epstein; epstein files; epstein files pdf; эпштейн; justice gov epstein |
| Tariffs | 28 | 701 (2) | 67 | 2025-04-02 (28, Trump tariffs); 2025-04-02 (11, Tariffs); 2025-04-02 (9, Reciprocal tariffs) | trump tariffs; tariff; aranceles; donald trump douane; 關稅; tariffs |
| April 2025 market fall (2–14 Apr) | 47 | 575 (24) | 60 | 2025-04-07 (47, S&P 500); 2025-04-07 (34, Dow Jones Industrial Average); 2025-04-02 (32, S&P 500) | sp500; s&p 500; nvidia stock; nasdaq; nikkei; dow jones |
| Bitcoin | 63 | 1,159 (70) | 90 | 2024-12-04 (63, Bitcoin); 2025-10-10 (51, Bitcoin); 2026-02-04 (48, Bitcoin) | bitcoin; bitcoin price; btc usd; btc; bitcoin price usd; bitcoin kurs |
| Gold price | 38 | 1,473 (24) | 81 | 2026-03-22 (38, Gold price); 2025-10-21 (35, Gold price); 2026-02-27 (32, Gold price) | gold price; gold; سعر الذهب اليوم; gold price today; gold prices; giá vàng hôm nay |
| Conclave and Pope Leo XIV | 79 | 382 (14) | 114 | 2025-05-08 (79, Pope Leo XIV); 2025-05-07 (37, Papal conclave); 2025-03-02 (30, Papal conclave) | conclave; new pope; pope leo; papst; conclave film; papst leo |

### AI

| candidate | max reach | moments (10+) | countries | peak dates | top phrasings |
|---|---|---|---|---|---|
| ChatGPT | 121 | 860 (41) | 125 | 2025-01-23 (121, ChatGPT); 2024-12-11 (116, ChatGPT); 2025-11-18 (86, ChatGPT) | chatgpt; openai; chat gpt; sora; chat; chatgpt down |
| Gemini | 96 | 264 (14) | 119 | 2025-01-23 (96, Google Gemini); 2026-02-03 (91, Google Gemini); 2025-06-10 (90, Google Gemini) | gemini; gemini ai; nano banana; google gemini; gemini 3; nano banana pro |
| Claude | 49 | 326 (19) | 86 | 2026-03-01 (49, Claude); 2025-11-18 (45, Claude); 2026-04-20 (43, Claude) | claude; anthropic; claude ai; claude code; opus 4.7; opus 4.6 |
| DeepSeek | 89 | 143 (5) | 118 | 2025-01-26 (89, DeepSeek); 2025-01-24 (28, DeepSeek); 2025-03-17 (25, DeepSeek) | deepseek; deepseek r1; deep seek; deepseek ai; deepseek v4; deepseek ai model |
| Grok | 49 | 204 (10) | 79 | 2025-06-10 (49, Grok); 2025-02-17 (44, Grok 3); 2026-02-03 (37, Grok) | grok; grok ai; grok 3; grok 4; grok3; elon musk grok 3 |

### Rituals

| candidate | max reach | moments (10+) | countries | peak dates | top phrasings |
|---|---|---|---|---|---|
| Weather | 43 | 36,128 (318) | 125 | 2025-02-14 (43, Weather forecast); 2024-12-23 (38, Weather forecast); 2026-03-15 (36, Weather forecast) | weather; weather tomorrow; الطقس غدًا; الطقس; weather today; cuaca besok |
| Lotteries | 20 | 10,292 (1) | 107 | 2025-05-03 (20, DV lottery results); 2026-02-26 (9, Lottery results); 2025-05-03 (9, DV Lottery 2026 results) | lotto; xsmb; ตรวจหวย; online lottery; lottery; lottery results today |
| Prayer times | 67 | 2,008 (11) | 39 | 2026-02-15 (67, Ramadan 2026); 2025-02-26 (57, Ramadan 2025); 2025-06-04 (35, Eid al-Adha 2025) | iftar time today; مواقيت الصلاة; iftar time; jadwal sholat; اوقات الصلاة; namaz vakitleri |
| "When is Eid / Ramadan / Easter" | 57 | 546 (15) | 32 | 2025-02-26 (57, Ramadan 2025); 2025-02-26 (56, Ramadan); 2025-03-27 (41, Eid al-Fitr 2025) | when is eid; when is easter 2025; when is ramadan; when is easter; when is ramadan 2025; when is ramadan 2026 |
| "Is X down" | 70 | 1,686 (89) | 61 | 2024-12-04 (70, Epic Games); 2025-11-01 (67, Epic Games); 2025-10-15 (61, YouTube outage) | downdetector; is chatgpt down; is reddit down; is steam down; is claude down; is youtube down |

## 4. Monthly series: countries per month

Countries whose national feed had the topic trending at least once that month (UTC). Gaps in collection (Sep 2025, 7–10 Dec 2025, Jan 2026; see PROFILE.md) lower some months.

| month | ChatGPT | Gemini | Claude | DeepSeek | Grok | Epstein files | Bitcoin | Gold price |
|---|---|---|---|---|---|---|---|---|
| 2024-11 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 6 |
| 2024-12 | 120 | 77 | 2 | 10 | 4 | 2 | 69 | 15 |
| 2025-01 | 123 | 96 | 5 | 118 | 3 | 5 | 49 | 14 |
| 2025-02 | 59 | 34 | 18 | 13 | 57 | 26 | 51 | 28 |
| 2025-03 | 68 | 11 | 1 | 32 | 38 | 2 | 48 | 33 |
| 2025-04 | 55 | 22 | 4 | 11 | 5 | 7 | 51 | 41 |
| 2025-05 | 51 | 23 | 20 | 2 | 5 | 7 | 46 | 26 |
| 2025-06 | 89 | 90 | 10 | 0 | 50 | 42 | 37 | 27 |
| 2025-07 | 39 | 6 | 2 | 2 | 47 | 33 | 55 | 16 |
| 2025-08 | 58 | 48 | 3 | 5 | 24 | 12 | 38 | 20 |
| 2025-09 | 51 | 52 | 7 | 0 | 1 | 7 | 24 | 25 |
| 2025-10 | 66 | 41 | 22 | 5 | 7 | 8 | 59 | 51 |
| 2025-11 | 105 | 99 | 64 | 0 | 9 | 39 | 56 | 24 |
| 2025-12 | 48 | 34 | 21 | 1 | 9 | 71 | 34 | 38 |
| 2026-01 | 0 | 5 | 0 | 1 | 14 | 42 | 38 | 11 |
| 2026-02 | 64 | 96 | 57 | 2 | 46 | 95 | 69 | 58 |
| 2026-03 | 64 | 28 | 70 | 1 | 32 | 29 | 42 | 61 |
| 2026-04 | 68 | 78 | 75 | 23 | 41 | 23 | 57 | 46 |
| 2026-05 | 22 | 14 | 23 | 3 | 7 | 14 | 27 | 34 |

Topics matched per series: ChatGPT: 184; Gemini: 47; Claude: 55; DeepSeek: 56; Grok: 28; Epstein files: 101; Bitcoin: 142; Gold price: 149.

