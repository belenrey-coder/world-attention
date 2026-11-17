"""Static calendar of major individual-sport events, Dec 2024 - May 2026, for the moment-level is_sport rule.

Sources (English Wikipedia, read 2026-11-13; see DECISIONS.md, Step 9):
  tennis  "2025 ATP Tour", "2026 ATP Tour", "2025 WTA Tour", "2026 WTA Tour" (schedule week columns) and
          "2025 ATP Finals" (exact dates). The season pages list the Monday of each tournament week; a window is
          (first week's Monday - 1 day) .. (last week's Monday + 6 days), because most of these events start on a
          Sunday. The United Cup starts on a Friday or Saturday: its window starts 3 days before its first Monday.
  F1      "2024/2025/2026 Formula One World Championship" (race dates). A race weekend is Friday .. race Sunday.
          The 2026 Saudi Arabian GP (cancelled) and Bahrain GP (moved to October 2026) are not in this range.
  golf    "2025 PGA Tour", "2026 PGA Tour" (final-round dates of the men's majors). A major is Thursday .. Sunday.
  cricket "2025 Indian Premier League" (22 Mar - 3 Jun 2025; suspended 9-16 May, resumed 17 May), "2026 Indian
          Premier League" (28 Mar - 31 May 2026), "2025 ICC Champions Trophy" (19 Feb - 9 Mar 2025), "2026 ICC Men's
          T20 World Cup" (7 Feb - 8 Mar 2026); read 2026-11-17. For cricketers.
  winter  "2026 Winter Olympics" (read 2026-11-16): 6-22 February 2026, first competitions on 4 February. For winter
          athletes (figure skaters, skiers, ...), whose season otherwise has no event in this calendar.
Moments are matched on their UTC start date, from the window's first day to one day after its last day (late
finals in the Americas end after midnight UTC).
"""
from datetime import date, timedelta

D = date.fromisoformat


def weeks(first_monday, last_monday=None, lead=1):
    first = D(first_monday)
    last = D(last_monday) if last_monday else first
    return first - timedelta(days=lead), last + timedelta(days=6)


TENNIS = {
    "United Cup 2025": weeks("2024-12-30", lead=3),
    "Australian Open 2025": weeks("2025-01-13", "2025-01-20"),
    "Qatar Open (WTA 1000) 2025": weeks("2025-02-10"),
    "Dubai Championships (WTA 1000) 2025": weeks("2025-02-17"),
    "Indian Wells 2025": weeks("2025-03-03", "2025-03-10"),
    "Miami Open 2025": weeks("2025-03-17", "2025-03-24"),
    "Monte-Carlo Masters 2025": weeks("2025-04-07"),
    "Madrid Open 2025": weeks("2025-04-21", "2025-04-28"),
    "Italian Open (Rome) 2025": weeks("2025-05-05", "2025-05-12"),
    "French Open 2025": weeks("2025-05-26", "2025-06-02"),
    "Wimbledon 2025": weeks("2025-06-30", "2025-07-07"),
    "Canadian Open 2025": weeks("2025-07-28", "2025-08-04"),
    "Cincinnati Open 2025": weeks("2025-08-04", "2025-08-11"),
    "US Open 2025": weeks("2025-08-25", "2025-09-01"),
    "China Open (Beijing) 2025": weeks("2025-09-22", "2025-09-29"),
    "Shanghai Masters 2025": weeks("2025-09-29", "2025-10-06"),
    "Wuhan Open (WTA 1000) 2025": weeks("2025-10-06"),
    "Paris Masters 2025": weeks("2025-10-27"),
    "WTA Finals 2025": weeks("2025-11-03"),
    "ATP Finals 2025": (D("2025-11-09"), D("2025-11-16")),
    "Davis Cup Finals 2025": weeks("2025-11-17"),
    "United Cup 2026": weeks("2026-01-05", lead=3),
    "Australian Open 2026": weeks("2026-01-19", "2026-01-26"),
    "Qatar Open (WTA 1000) 2026": weeks("2026-02-09"),
    "Dubai Championships (WTA 1000) 2026": weeks("2026-02-16"),
    "Indian Wells 2026": weeks("2026-03-02", "2026-03-09"),
    "Miami Open 2026": weeks("2026-03-16", "2026-03-23"),
    "Monte-Carlo Masters 2026": weeks("2026-04-06"),
    "Madrid Open 2026": weeks("2026-04-20", "2026-04-27"),
    "Italian Open (Rome) 2026": weeks("2026-05-04", "2026-05-11"),
}

F1_RACES = {
    "Qatar GP 2024": "2024-12-01", "Abu Dhabi GP 2024": "2024-12-08",
    "Australian GP 2025": "2025-03-16", "Chinese GP 2025": "2025-03-23", "Japanese GP 2025": "2025-04-06",
    "Bahrain GP 2025": "2025-04-13", "Saudi Arabian GP 2025": "2025-04-20", "Miami GP 2025": "2025-05-04",
    "Emilia Romagna GP 2025": "2025-05-18", "Monaco GP 2025": "2025-05-25", "Spanish GP 2025": "2025-06-01",
    "Canadian GP 2025": "2025-06-15", "Austrian GP 2025": "2025-06-29", "British GP 2025": "2025-07-06",
    "Belgian GP 2025": "2025-07-27", "Hungarian GP 2025": "2025-08-03", "Dutch GP 2025": "2025-08-31",
    "Italian GP 2025": "2025-09-07", "Azerbaijan GP 2025": "2025-09-21", "Singapore GP 2025": "2025-10-05",
    "United States GP 2025": "2025-10-19", "Mexico City GP 2025": "2025-10-26", "São Paulo GP 2025": "2025-11-09",
    "Las Vegas GP 2025": "2025-11-22", "Qatar GP 2025": "2025-11-30", "Abu Dhabi GP 2025": "2025-12-07",
    "Australian GP 2026": "2026-03-08", "Chinese GP 2026": "2026-03-15", "Japanese GP 2026": "2026-03-29",
    "Miami GP 2026": "2026-05-03", "Canadian GP 2026": "2026-05-24",
}
F1 = {k: (D(v) - timedelta(days=2), D(v)) for k, v in F1_RACES.items()}

GOLF_FINALS = {"Masters 2025": "2025-04-13", "PGA Championship 2025": "2025-05-18", "U.S. Open 2025": "2025-06-15",
               "The Open 2025": "2025-07-20", "Masters 2026": "2026-04-12", "PGA Championship 2026": "2026-05-17"}
GOLF = {k: (D(v) - timedelta(days=3), D(v)) for k, v in GOLF_FINALS.items()}

WINTER = {"Winter Olympics 2026": (D("2026-02-04"), D("2026-02-22"))}

CRICKET = {"IPL 2025": (D("2025-03-22"), D("2025-05-08")), "IPL 2025 (resumed)": (D("2025-05-17"), D("2025-06-03")),
           "IPL 2026": (D("2026-03-28"), D("2026-05-31")),
           "ICC Champions Trophy 2025": (D("2025-02-19"), D("2025-03-09")),
           "ICC Men's T20 World Cup 2026": (D("2026-02-07"), D("2026-03-08"))}

CALENDAR = {"tennis": TENNIS, "f1": F1, "golf": GOLF, "winter": WINTER, "cricket": CRICKET}
SPORT_OF_DESC = [("tennis", r"tennis player"), ("f1", r"racing driver|formula one|formula 1|f1 driver"),
                 ("golf", r"golfer"), ("cricket", r"cricketer"),
                 ("winter", r"figure skater|ice dancer|speed skater|skier|ski jumper|snowboarder|biathlete|luger|"
                            r"bobsledder|skeleton racer|curler|ice hockey player")]


def sport_of(desc):
    """'tennis' / 'f1' / 'golf' from a Wikidata description, else None."""
    import re
    if not isinstance(desc, str):
        return None
    for sport, rx in SPORT_OF_DESC:
        if re.search(rx, desc, re.I):
            return sport
    return None


def event_on(sport, day):
    """Name of the calendar event of this sport whose window contains the UTC date `day` (+1 day slack), or None."""
    hits = [(a, name) for name, (a, b) in CALENDAR.get(sport, {}).items() if a <= day <= b + timedelta(days=1)]
    return max(hits)[1] if hits else None      # overlapping windows: the most recently started event
