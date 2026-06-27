#!/usr/bin/env python3
import json
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError

import pytz
import yaml
from icalendar import Calendar, Event, Alarm

API_BASE = "https://api.openligadb.de/getmatchdata"
BERLIN = pytz.timezone("Europe/Berlin")

_fetch_cache: dict = {}


def load_config(path="config.yaml"):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def fetch_matches(shortcut, season):
    key = (shortcut, season)
    if key in _fetch_cache:
        return _fetch_cache[key]
    url = f"{API_BASE}/{shortcut}/{season}"
    for attempt in range(3):
        try:
            req = Request(url, headers={"User-Agent": "fulender/1.0"})
            with urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read())
                _fetch_cache[key] = result
                return result
        except (URLError, json.JSONDecodeError, TimeoutError) as e:
            print(f"  Versuch {attempt + 1}/3 fehlgeschlagen für {url}: {e}")
            if attempt < 2:
                time.sleep(2)
    print(f"  WARNUNG: Keine Daten von {url}")
    _fetch_cache[key] = []
    return []


def filter_by_group_names(matches, keywords):
    result = []
    for m in matches:
        gname = m.get("group", {}).get("groupName", "")
        if any(kw in gname for kw in keywords):
            result.append(m)
    return result


def filter_matches(matches, comp_config):
    filter_teams = comp_config.get("filter_teams")
    filter_rounds = comp_config.get("filter_rounds")

    if not filter_teams and not filter_rounds:
        return matches

    teams_set = set(filter_teams) if filter_teams else None
    rounds_set = set(filter_rounds) if filter_rounds else None

    result = []
    for m in matches:
        if rounds_set:
            gid = m.get("group", {}).get("groupOrderID")
            if gid not in rounds_set:
                continue
        if teams_set:
            t1 = m.get("team1", {}).get("teamName", "")
            t2 = m.get("team2", {}).get("teamName", "")
            if t1 not in teams_set and t2 not in teams_set:
                continue
        result.append(m)
    return result


def is_koeln_eliminated(matches):
    koeln_matches = []
    for m in matches:
        t1 = m.get("team1", {}).get("teamName", "")
        t2 = m.get("team2", {}).get("teamName", "")
        if "1. FC Köln" in (t1, t2):
            koeln_matches.append(m)

    koeln_matches.sort(key=lambda m: m.get("group", {}).get("groupOrderID", 0))

    last_finished = None
    for m in koeln_matches:
        if m.get("matchIsFinished"):
            last_finished = m

    if not last_finished:
        return False, 0

    results = last_finished.get("matchResults", [])
    final = None
    for r in sorted(results, key=lambda r: r.get("resultOrderID", 0), reverse=True):
        if r.get("resultTypeID") in (2, 3, 4):
            final = r
            break

    if not final:
        return False, last_finished.get("group", {}).get("groupOrderID", 0)

    t1 = last_finished.get("team1", {}).get("teamName", "")
    koeln_is_team1 = t1 == "1. FC Köln"
    koeln_goals = final["pointsTeam1"] if koeln_is_team1 else final["pointsTeam2"]
    opponent_goals = final["pointsTeam2"] if koeln_is_team1 else final["pointsTeam1"]

    if koeln_goals < opponent_goals:
        last_round = last_finished.get("group", {}).get("groupOrderID", 0)
        return True, last_round

    return False, last_finished.get("group", {}).get("groupOrderID", 0)


def generate_bundesliga_placeholders(placeholder_config):
    events = []
    entries = placeholder_config.get("matchday_dates", [])

    for i, entry in enumerate(entries):
        if isinstance(entry, str):
            matchday_date = date.fromisoformat(entry)
            name = f"Spieltag {i + 1}"
            verified = False
        else:
            matchday_date = date.fromisoformat(entry["date"])
            name = entry.get("name", f"Spieltag {i + 1}")
            verified = entry.get("verified", False)

        if verified:
            summary = f"BL: {name} (1. FC Köln)"
            description = f"1. Bundesliga 2026/27\n{name}\nDatum bestätigt (DFL Rahmenterminkalender)"
        else:
            summary = f"BL: {name} (1. FC Köln) [voraussichtlich]"
            description = (
                f"1. Bundesliga 2026/27\n{name}\n"
                f"Voraussichtliches Datum – berechnet aus DFL-Rahmenterminkalender.\n"
                f"Wird automatisch aktualisiert sobald offizielle Terminierung vorliegt."
            )

        events.append({
            "_placeholder": True,
            "_matchday": i + 1,
            "_date": matchday_date,
            "_label": "BL",
            "_summary": summary,
            "_description": description,
        })

    return events


def generate_dfb_placeholders(placeholder_config, eliminated, last_round):
    events = []
    for r in placeholder_config["rounds"]:
        round_date = date.fromisoformat(r["date"])
        round_name = r["name"]

        round_order = placeholder_config["rounds"].index(r) + 1
        if eliminated and round_order > last_round:
            break

        events.append({
            "_placeholder": True,
            "_matchday": round_order,
            "_date": round_date,
            "_label": "DFB",
            "_summary": f"DFB: {round_name} (1. FC Köln)",
            "_description": f"DFB-Pokal 2026/27\n{round_name}\nGenaue Terminierung steht noch aus",
        })
    return events


def load_manual_matches(path="overrides/manual_matches.yaml"):
    p = Path(path)
    if not p.exists():
        return []
    with open(p, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("matches", []) if data else []


def parse_utc(dt_str):
    s = dt_str.rstrip("Z")
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)


def resolve_location(match, comp_config, stadiums):
    loc = match.get("location")
    if loc and isinstance(loc, dict):
        parts = [loc.get("locationStadium", ""), loc.get("locationCity", "")]
        resolved = ", ".join(p for p in parts if p)
        if resolved:
            return resolved
    elif loc and isinstance(loc, str):
        return loc

    if comp_config.get("id", "").startswith("wm"):
        return None

    t1 = match.get("team1", {}).get("teamName", "")
    t2 = match.get("team2", {}).get("teamName", "")

    if t1 == "1. FC Köln":
        return stadiums.get("1. FC Köln")
    if t2 == "1. FC Köln":
        return stadiums.get(t1)

    return None


def build_event_from_api(match, comp_config, stadiums):
    match_id = match["matchID"]
    t1 = match.get("team1", {})
    t2 = match.get("team2", {})
    label = comp_config["label"]

    t1_name = t1.get("shortName") or t1.get("teamName", "?")
    t2_name = t2.get("shortName") or t2.get("teamName", "?")
    summary = f"{label}: {t1_name} – {t2_name}"

    dt_utc = parse_utc(match["matchDateTimeUTC"])
    dt_local = dt_utc.astimezone(BERLIN)

    event = Event()
    event.add("uid", f"{match_id}@fulender.calendar")
    event.add("dtstamp", datetime.now(timezone.utc))
    event.add("dtstart", dt_local)
    event.add("dtend", dt_local + timedelta(hours=2))
    event.add("summary", summary)

    group_name = match.get("group", {}).get("groupName", "")
    desc = f"{comp_config['description']}\n{group_name}"
    event.add("description", desc)

    location = resolve_location(match, comp_config, stadiums)
    if location:
        event.add("location", location)

    status = "CONFIRMED" if match.get("matchIsFinished") else "TENTATIVE"
    event.add("status", status)

    if match.get("lastUpdateDateTime"):
        try:
            lud = parse_utc(match["lastUpdateDateTime"])
            event.add("last-modified", lud)
        except (ValueError, KeyError):
            pass

    alarm = Alarm()
    alarm.add("action", "DISPLAY")
    alarm.add("description", f"Anpfiff: {summary}")
    alarm.add("trigger", timedelta(minutes=-15))
    event.add_component(alarm)

    return event


def build_event_from_placeholder(placeholder):
    d = placeholder["_date"]
    mid = placeholder.get("_uid") or f"placeholder-{placeholder['_label'].lower()}-{placeholder['_matchday']}"

    event = Event()
    event.add("uid", f"{mid}@fulender.calendar")
    event.add("dtstamp", datetime.now(timezone.utc))
    event.add("dtstart", d)
    event.add("dtend", d + timedelta(days=1))
    event.add("summary", placeholder["_summary"])
    event.add("description", placeholder["_description"])
    event.add("status", "TENTATIVE")

    return event


def build_calendar(events, config):
    cal = Calendar()
    cal.add("prodid", "-//fulender//Fussball-Kalender//DE")
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    cal.add("method", "PUBLISH")
    cal.add("x-wr-calname", config["calendar"]["name"])
    cal.add("x-wr-timezone", config["calendar"]["timezone"])
    cal.add("x-wr-caldesc", "Fußball-Kalender: 1. FC Köln (BL + DFB-Pokal) & WM 2026")

    for event in events:
        cal.add_component(event)
    return cal


def main():
    config = load_config()
    stadiums = config.get("stadiums", {})
    all_events = {}

    for comp in config["competitions"]:
        comp_id = comp["id"]
        print(f"Verarbeite: {comp['description']} ({comp_id})")

        raw_matches = fetch_matches(comp["api_shortcut"], comp["api_season"])

        ph_config = comp.get("placeholder", {})
        ph_type = ph_config.get("type") if ph_config.get("enabled") else None

        if ph_type == "wm_ko":
            api_count = 0
            ph_count = 0

            for round_cfg in ph_config["rounds"]:
                round_name = round_cfg["name"]
                round_api = filter_by_group_names(raw_matches, [round_name])
                dates = round_cfg["dates"]
                total = len(dates)

                for m in round_api:
                    event = build_event_from_api(m, comp, stadiums)
                    uid = str(event.get("uid"))
                    all_events[uid] = event
                    api_count += 1

                # Nur so viele Platzhalter anlegen, wie noch unbekannte Paarungen
                # offen sind. Sobald die API eine Paarung liefert, entfällt
                # dafür genau ein Ganztags-Platzhalter.
                remaining = total - len(round_api)
                round_key = round_name.lower().replace(" ", "-")
                for i in range(remaining):
                    num = i + 1
                    label = round_name if total == 1 else f"{round_name} ({num}/{total})"
                    ph = {
                        "_placeholder": True,
                        "_uid": f"placeholder-wm-ko-{round_key}-{num}",
                        "_matchday": num,
                        "_date": date.fromisoformat(dates[i]),
                        "_label": comp["label"],
                        "_summary": f"{comp['label']}: {label}",
                        "_description": (
                            f"WM 2026\n{label}\n"
                            "Paarung noch nicht bekannt – wird automatisch aktualisiert sobald die Teams feststehen."
                        ),
                    }
                    event = build_event_from_placeholder(ph)
                    uid = str(event.get("uid"))
                    all_events[uid] = event
                    ph_count += 1

            print(f"  {api_count} Spiele (API) + {ph_count} Platzhalter")
            continue

        filtered = filter_matches(raw_matches, comp)
        print(f"  API: {len(raw_matches)} Spiele geladen, {len(filtered)} nach Filter")

        if filtered:
            for m in filtered:
                event = build_event_from_api(m, comp, stadiums)
                uid = str(event.get("uid"))
                all_events[uid] = event
        elif ph_config.get("enabled"):
            if ph_type == "bundesliga":
                placeholders = generate_bundesliga_placeholders(ph_config)
                print(f"  Platzhalter: {len(placeholders)} Bundesliga-Spieltage generiert")
            elif ph_type == "dfb_pokal":
                if comp.get("auto_deactivate"):
                    all_dfb = fetch_matches(comp["api_shortcut"], comp["api_season"])
                    eliminated, last_round = is_koeln_eliminated(all_dfb)
                    if eliminated:
                        print(f"  Köln ist in Runde {last_round} ausgeschieden – keine weiteren Platzhalter")
                else:
                    eliminated, last_round = False, 0
                placeholders = generate_dfb_placeholders(ph_config, eliminated, last_round)
                print(f"  Platzhalter: {len(placeholders)} DFB-Pokal-Runden generiert")
            else:
                placeholders = []

            for ph in placeholders:
                event = build_event_from_placeholder(ph)
                uid = str(event.get("uid"))
                all_events[uid] = event
        else:
            print(f"  Keine Daten und keine Platzhalter konfiguriert")

    manual = load_manual_matches()
    if manual:
        print(f"Manuelle Overrides: {len(manual)} Einträge")
        for m in manual:
            comp_stub = {"label": m.get("_label", "?"), "description": m.get("_description", ""), "id": "manual"}
            event = build_event_from_api(m, comp_stub, stadiums)
            uid = str(event.get("uid"))
            all_events[uid] = event

    cal = build_calendar(list(all_events.values()), config)

    output = Path("docs/calendar.ics")
    output.parent.mkdir(exist_ok=True)
    output.write_bytes(cal.to_ical())
    print(f"\n{len(all_events)} Events geschrieben nach {output}")


if __name__ == "__main__":
    main()
