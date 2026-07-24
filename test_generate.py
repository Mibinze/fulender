#!/usr/bin/env python3
"""Tests für die Terminierungs-Erkennung (fix vs. noch nicht fix).

Standalone ausführbar: python3 test_generate.py
"""
from datetime import date

from generate import (
    bl_blocker_window,
    classify_bl_matchday,
    generate_bundesliga_events,
)

COMP = {"label": "BL", "description": "1. Bundesliga 2026/27", "id": "bl1_2026"}
STADIUMS = {"1. FC Köln": "RheinEnergieSTADION, Köln"}
KOELN = "1. FC Köln"

OTHERS = [
    ("FC Bayern München", "Borussia Dortmund"),
    ("RB Leipzig", "SC Freiburg"),
    ("FC Augsburg", "VfB Stuttgart"),
    ("SV Werder Bremen", "1. FSV Mainz 05"),
    ("VfL Wolfsburg", "TSG 1899 Hoffenheim"),
    ("Eintracht Frankfurt", "FC St. Pauli"),
    ("Bayer 04 Leverkusen", "Holstein Kiel"),
    ("1. FC Union Berlin", "1. FC Heidenheim 1846"),
]


def game(matchday, dt_utc, t1, t2, match_id=None):
    return {
        "matchID": match_id if match_id is not None else abs(hash((matchday, t1, t2))) % 100000,
        "group": {"groupOrderID": matchday, "groupName": f"{matchday}. Spieltag"},
        "team1": {"teamName": t1, "shortName": t1},
        "team2": {"teamName": t2, "shortName": t2},
        "matchDateTimeUTC": dt_utc,
        "matchIsFinished": False,
    }


def matchday(md, koeln_time, other_times):
    """Ein kompletter Spieltag: Köln-Spiel + 8 weitere Partien."""
    games = [game(md, koeln_time, KOELN, "FC Bayern München")]
    for (t1, t2), t in zip(OTHERS, other_times):
        games.append(game(md, t, t1, t2))
    return games


checks = []


def check(name, cond):
    checks.append((name, bool(cond)))
    print(f"  {'OK  ' if cond else 'FAIL'}  {name}")


# --------------------------------------------------------------------------
# classify_bl_matchday
# --------------------------------------------------------------------------
print("\nclassify_bl_matchday:")
ANCHOR = date(2026, 9, 5)

# Rohspielplan: alle 9 Spiele Sa 15:30 Ortszeit (13:30 UTC)
uniform = matchday(2, "2026-09-05T13:30:00Z", ["2026-09-05T13:30:00Z"] * 8)
sched, reason = classify_bl_matchday(uniform, ANCHOR)
check("Rohspielplan (alle zeitgleich) -> NICHT terminiert", sched is False)

# TV-terminiert: über Fr/Sa/So aufgefächert
spread = matchday(
    2,
    "2026-09-05T13:30:00Z",
    [
        "2026-09-04T18:30:00Z",
        "2026-09-05T13:30:00Z",
        "2026-09-05T13:30:00Z",
        "2026-09-05T13:30:00Z",
        "2026-09-05T16:30:00Z",
        "2026-09-06T13:30:00Z",
        "2026-09-06T15:30:00Z",
        "2026-09-06T17:30:00Z",
    ],
)
sched, reason = classify_bl_matchday(spread, ANCHOR)
check("aufgefächerte Anstoßzeiten -> terminiert", sched is True)

# Gar keine Zeiten (alles Mitternacht UTC)
untimed = matchday(2, "2026-09-05T00:00:00Z", ["2026-09-05T00:00:00Z"] * 8)
sched, _ = classify_bl_matchday(untimed, ANCHOR)
check("keine Anstoßzeiten -> NICHT terminiert", sched is False)

# Teilterminierung: Köln hat Zeit, Rest noch Platzhalter
partial = matchday(2, "2026-09-04T18:30:00Z", ["2026-09-05T00:00:00Z"] * 8)
sched, _ = classify_bl_matchday(partial, ANCHOR)
check("teilweise terminiert -> terminiert", sched is True)

# Letzter Spieltag: planmäßig zeitgleich
sched, _ = classify_bl_matchday(uniform, ANCHOR, simultaneous=True)
check("zeitgleich + simultaneous-Flag -> terminiert", sched is True)

# Einzelspiel ohne Spieltagskontext
single_default = [game(2, "2026-09-05T13:30:00Z", KOELN, "FC Bayern München")]
sched, _ = classify_bl_matchday(single_default, ANCHOR)
check("Einzelspiel im Default-Slot (Sa 15:30) -> NICHT terminiert", sched is False)

single_friday = [game(2, "2026-09-04T18:30:00Z", KOELN, "FC Bayern München")]
sched, _ = classify_bl_matchday(single_friday, ANCHOR)
check("Einzelspiel Fr 20:30 -> terminiert", sched is True)

single_sat_evening = [game(2, "2026-09-05T16:30:00Z", KOELN, "FC Bayern München")]
sched, _ = classify_bl_matchday(single_sat_evening, ANCHOR)
check("Einzelspiel Sa 18:30 -> terminiert", sched is True)

check("leerer Spieltag -> NICHT terminiert", classify_bl_matchday([], ANCHOR)[0] is False)

# --------------------------------------------------------------------------
# bl_blocker_window
# --------------------------------------------------------------------------
print("\nbl_blocker_window:")
s, e = bl_blocker_window(date(2026, 9, 5), {})           # Samstag
check("Sa-Anker -> Fr bis So (Ende exkl. Mo)", (s, e) == (date(2026, 9, 4), date(2026, 9, 7)))

s, e = bl_blocker_window(date(2027, 1, 12), {})          # Dienstag (Englische Woche)
check("Di-Anker -> Di bis Do", (s, e) == (date(2027, 1, 12), date(2027, 1, 15)))

s, e = bl_blocker_window(date(2027, 5, 19), {})          # Mittwoch (Englische Woche)
check("Mi-Anker -> Di bis Do", (s, e) == (date(2027, 5, 18), date(2027, 5, 21)))

s, e = bl_blocker_window(date(2026, 9, 5), {"window_days": 4})
check("window_days-Override greift", (s, e) == (date(2026, 9, 4), date(2026, 9, 8)))

# --------------------------------------------------------------------------
# End-to-end über generate_bundesliga_events
# --------------------------------------------------------------------------
print("\ngenerate_bundesliga_events (end-to-end):")
ph_config = {
    "matchday_dates": [
        {"date": "2026-08-29", "name": "Spieltag 1"},
        {"date": "2026-09-05", "name": "Spieltag 2"},
        {"date": "2026-09-12", "name": "Spieltag 3"},
        {"date": "2026-09-19", "name": "Spieltag 4"},
    ]
}

raw = []
# ST1 terminiert (aufgefächert), Köln Sa 15:30 Ortszeit
raw += matchday(
    1,
    "2026-08-29T13:30:00Z",
    ["2026-08-28T18:30:00Z"] + ["2026-08-29T13:30:00Z"] * 3
    + ["2026-08-29T16:30:00Z"] + ["2026-08-30T13:30:00Z"] * 3,
)
# ST2 Rohspielplan (alle zeitgleich)
raw += matchday(2, "2026-09-05T13:30:00Z", ["2026-09-05T13:30:00Z"] * 8)
# ST3 Teilterminierung, Köln Fr 20:30
raw += matchday(3, "2026-09-11T18:30:00Z", ["2026-09-12T00:00:00Z"] * 8)
# ST4 komplett ohne Zeiten
raw += matchday(4, "2026-09-19T00:00:00Z", ["2026-09-19T00:00:00Z"] * 8)

filtered = [m for m in raw if KOELN in (m["team1"]["teamName"], m["team2"]["teamName"])]
events = generate_bundesliga_events(ph_config, filtered, COMP, STADIUMS, raw)


def is_blocker(ev):
    return str(ev.get("uid")).startswith("placeholder-")


check("ST1 terminiert -> praeziser Termin", not is_blocker(events[0]))
check("ST1 Startzeit = Sa 15:30 Ortszeit", str(events[0].get("dtstart").dt) == "2026-08-29 15:30:00+02:00")
check("ST2 Rohspielplan -> Blocker", is_blocker(events[1]))
check("ST2 Blocker startet Freitag", events[1].get("dtstart").dt == date(2026, 9, 4))
check("ST2 Blocker endet Montag (exkl.)", events[1].get("dtend").dt == date(2026, 9, 7))
check("ST3 Teilterminierung -> praeziser Termin", not is_blocker(events[2]))
check("ST3 Startzeit = Fr 20:30 Ortszeit", str(events[2].get("dtstart").dt) == "2026-09-11 20:30:00+02:00")
check("ST4 ohne Zeiten -> Blocker", is_blocker(events[3]))
check("ST2 Blocker nennt die Paarung", "1. FC Köln" in str(events[1].get("summary")))

# Regression: der letzte Spieltag mit simultaneous-Flag
ph_last = {"matchday_dates": [{"date": "2027-05-22", "name": "Spieltag 34", "simultaneous": True}]}
raw_last = matchday(1, "2027-05-22T13:30:00Z", ["2027-05-22T13:30:00Z"] * 8)
filtered_last = [m for m in raw_last if KOELN in (m["team1"]["teamName"], m["team2"]["teamName"])]
ev_last = generate_bundesliga_events(ph_last, filtered_last, COMP, STADIUMS, raw_last)
check("letzter Spieltag (simultaneous) -> praeziser Termin", not is_blocker(ev_last[0]))

# --------------------------------------------------------------------------
failed = [n for n, ok in checks if not ok]
print(f"\n{len(checks) - len(failed)}/{len(checks)} Tests bestanden")
if failed:
    for n in failed:
        print(f"  FEHLGESCHLAGEN: {n}")
    raise SystemExit(1)
print("Alle Tests bestanden.")
