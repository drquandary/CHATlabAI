#!/usr/bin/env python3
"""
CHATLabAI lab-calendar skill — self-contained lab calendar.

Maintains calendar/lab-calendar.ics (iCalendar) with an auto-regenerated
calendar/lab-calendar.md readable mirror.

Commands:
    add      --title --start [--end] [--location] [--desc] [--rrule FREQ=...]
    list     [--from YYYY-MM-DD] [--to YYYY-MM-DD]
    next
    today
    deadlines

The `icalendar` package is OPTIONAL. If present it is used for richer RRULE
expansion; if absent a pure-stdlib iCalendar reader/writer keeps the calendar
fully functional (basic single-occurrence events + simple FREQ recurrence).
No network, no external auth.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone

# --------------------------------------------------------------------------- paths
HERE = os.path.dirname(os.path.abspath(__file__))
# workspace root = .pi/skills/lab-calendar/scripts/ -> up 4
WORKSPACE_ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
DEFAULT_ICS = os.path.join(WORKSPACE_ROOT, "calendar", "lab-calendar.ics")
DEFAULT_MD = os.path.join(WORKSPACE_ROOT, "calendar", "lab-calendar.md")

# Deadline keyword detection (case-insensitive)
DEADLINE_KEYWORDS = ("deadline", "submission", "irb", "renewal")

# --------------------------------------------------------------------------- icalendar?
try:
    from icalendar import Calendar, Event  # type: ignore
    from icalendar.prop import vRecur  # type: ignore
    HAS_ICALENDAR = True
except Exception:  # pragma: no cover - optional dep
    HAS_ICALENDAR = False


# ===========================================================================
# Pure-stdlib iCalendar reader/writer (fallback + used for I/O regardless)
# ===========================================================================
PRODID = "-//CHATLabAI//Lab Calendar//EN"
SEED_ICS = (
    "BEGIN:VCALENDAR\n"
    "VERSION:2.0\n"
    f"PRODID:{PRODID}\n"
    "CALSCALE:GREGORIAN\n"
    "END:VCALENDAR\n"
)


def _fold(line: str) -> str:
    """RFC 5545 line folding (max 75 octets)."""
    out = []
    while len(line.encode("utf-8")) > 75:
        # cut at 75 octets
        cut = 75
        while len(line[:cut].encode("utf-8")) > 75:
            cut -= 1
        out.append(line[:cut])
        line = " " + line[cut:]
    out.append(line)
    return "\n".join(out)


def _unfold(text: str) -> list[str]:
    """Undo RFC 5545 line folding: a line beginning with space/tab continues the previous."""
    lines = []
    for raw in text.splitlines():
        if raw[:1] in (" ", "\t"):
            if lines:
                lines[-1] += raw[1:]
        else:
            lines.append(raw)
    return lines


def _escape(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def _unescape(text: str) -> str:
    return (
        text.replace("\\n", "\n")
        .replace("\\,", ",")
        .replace("\\;", ";")
        .replace("\\\\", "\\")
    )


def _parse_ics_datetime(value: str):
    """Parse DATE (YYYYMMDD) or DATE-TIME (YYYYMMDDTHHMMSS[Z])."""
    value = value.strip()
    if "T" in value:
        # date-time
        if value.endswith("Z"):
            dt = datetime.strptime(value[:-1], "%Y%m%dT%H%M%S")
            return dt.replace(tzinfo=timezone.utc)
        return datetime.strptime(value, "%Y%m%dT%H%M%S")
    # date only (all-day)
    d = datetime.strptime(value, "%Y%m%d")
    return d.date()


def _fmt_ics_datetime(value) -> str:
    """Format a datetime/date to iCalendar VALUE."""
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            return value.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        return value.strftime("%Y%m%dT%H%M%S")
    # date
    return value.strftime("%Y%m%d")


def _dt_value_type(value) -> str:
    return "DATE" if isinstance(value, date) and not isinstance(value, datetime) else "DATE-TIME"


# ---------------------------------------------------------------- event model
def _parse_rrule(rrule_str: str) -> dict | None:
    """Parse a simple RRULE like 'FREQ=WEEKLY;INTERVAL=1'. Returns dict or None."""
    if not rrule_str:
        return None
    parts = {}
    for tok in rrule_str.split(";"):
        if "=" in tok:
            k, v = tok.split("=", 1)
            parts[k.upper()] = v.upper()
    if "FREQ" not in parts:
        return None
    parts.setdefault("INTERVAL", "1")
    return parts


def _rrule_freq_to_delta(freq: str, interval: int):
    f = freq.upper()
    if f == "DAILY":
        return timedelta(days=interval)
    if f == "WEEKLY":
        return timedelta(weeks=interval)
    if f == "MONTHLY":
        return None  # month arithmetic handled specially
    if f == "YEARLY":
        return None  # year arithmetic handled specially
    return None


def _add_months(dt, months: int):
    """Add N months to a datetime/date, clamping the day to month-end."""
    is_date = isinstance(dt, date) and not isinstance(dt, datetime)
    base = dt
    m = base.month - 1 + months
    y = base.year + m // 12
    m = m % 12 + 1
    d = min(base.day, _days_in_month(y, m))
    if is_date:
        return date(y, m, d)
    return base.replace(year=y, month=m, day=d)


def _add_years(dt, years: int):
    is_date = isinstance(dt, date) and not isinstance(dt, datetime)
    base = dt
    y = base.year + years
    try:
        d = base.replace(year=y)
    except ValueError:  # Feb 29
        d = base.replace(year=y, day=28)
    return d


def _days_in_month(y: int, m: int) -> int:
    if m == 12:
        nxt = date(y + 1, 1, 1)
    else:
        nxt = date(y, m + 1, 1)
    return (nxt - timedelta(days=1)).day


def expand_rrule(start, rrule: dict | None, until: datetime) -> list:
    """Expand a simple RRULE into a list of occurrence start values (up to `until`).

    Uses `icalendar` if available for correctness; otherwise a small stdlib
    expander covering DAILY/WEEKLY/MONTHLY/YEARLY with INTERVAL, COUNT, UNTIL.
    """
    if rrule is None:
        return [start]

    freq = rrule.get("FREQ", "").upper()
    interval = max(1, int(rrule.get("INTERVAL", "1")))
    count = int(rrule["COUNT"]) if "COUNT" in rrule else None
    until_str = rrule.get("UNTIL")
    rrule_until = _parse_ics_datetime(until_str) if until_str else None

    occurrences = []
    cur = start
    n = 0
    # cap iterations defensively
    for _ in range(10000):
        if count is not None and n >= count:
            break
        if isinstance(cur, datetime) and isinstance(until, datetime):
            if cur > until:
                break
        elif isinstance(cur, datetime):
            if cur.date() > until.date() if hasattr(until, "date") else cur > until:
                break
        if rrule_until is not None and isinstance(cur, datetime) and isinstance(rrule_until, datetime):
            if cur > rrule_until:
                break
        occurrences.append(cur)
        n += 1
        # advance
        delta = _rrule_freq_to_delta(freq, interval)
        if delta is not None:
            cur = cur + delta
        elif freq == "MONTHLY":
            cur = _add_months(cur, interval)
        elif freq == "YEARLY":
            cur = _add_years(cur, interval)
        else:
            break
    return occurrences


# ---------------------------------------------------------------- I/O
def read_events(ics_path: str) -> list[dict]:
    """Parse the .ics file into a list of event dicts.

    Each event: {uid, summary, dtstart, dtend, location, description, rrule}
    dtstart/dtend are datetime or date.
    """
    if not os.path.exists(ics_path):
        return []
    with open(ics_path, "r", encoding="utf-8") as f:
        text = f.read()
    if "BEGIN:VEVENT" not in text:
        return []

    events: list[dict] = []
    in_event = False
    cur: dict = {}
    # key=value property parser (handles PROPERTY;PARAMS:value)
    prop_re = re.compile(r"^([A-Z\-]+)([^:]*):(.*)$")
    for line in _unfold(text):
        if line == "BEGIN:VEVENT":
            in_event = True
            cur = {}
            continue
        if line == "END:VEVENT":
            if cur:
                events.append(cur)
            in_event = False
            continue
        if not in_event:
            continue
        m = prop_re.match(line)
        if not m:
            continue
        key = m.group(1).upper()
        params = m.group(2)
        val = _unescape(m.group(3))
        if key == "UID":
            cur["uid"] = val
        elif key == "SUMMARY":
            cur["summary"] = val
        elif key == "LOCATION":
            cur["location"] = val
        elif key == "DESCRIPTION":
            cur["description"] = val
        elif key == "RRULE":
            cur["rrule"] = _parse_rrule(val)
        elif key == "DTSTART":
            cur["dtstart"] = _parse_ics_datetime(val)
            cur["dtstart_value_type"] = "DATE" if ";VALUE=DATE" in params.upper() else "DATE-TIME"
        elif key == "DTEND":
            cur["dtend"] = _parse_ics_datetime(val)
    return events


def write_calendar(ics_path: str, events: list[dict]) -> None:
    """Write all events to the .ics file (full rewrite)."""
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", f"PRODID:{PRODID}", "CALSCALE:GREGORIAN"]
    for ev in events:
        lines.append("BEGIN:VEVENT")
        lines.append(_fold(f"UID:{ev['uid']}"))
        lines.append(_fold(f"SUMMARY:{_escape(ev['summary'])}"))
        dtstart = ev["dtstart"]
        vt = _dt_value_type(dtstart)
        lines.append(_fold(f"DTSTART;VALUE={vt}:{_fmt_ics_datetime(dtstart)}"))
        if ev.get("dtend") is not None:
            vt2 = _dt_value_type(ev["dtend"])
            lines.append(_fold(f"DTEND;VALUE={vt2}:{_fmt_ics_datetime(ev['dtend'])}"))
        if ev.get("location"):
            lines.append(_fold(f"LOCATION:{_escape(ev['location'])}"))
        if ev.get("description"):
            lines.append(_fold(f"DESCRIPTION:{_escape(ev['description'])}"))
        if ev.get("rrule"):
            rrule_str = ";".join(f"{k}={v}" for k, v in ev["rrule"].items())
            lines.append(_fold(f"RRULE:{rrule_str}"))
        # DTSTAMP required by spec
        lines.append(_fold(f"DTSTAMP:{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"))
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    os.makedirs(os.path.dirname(ics_path), exist_ok=True)
    with open(ics_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def regenerate_md(md_path: str, events: list[dict]) -> None:
    """Regenerate the readable .md mirror from the events list."""
    lines = [
        "# Lab Calendar",
        "",
        "> Auto-regenerated by the `lab-calendar` skill from `lab-calendar.ics`. Do not edit by hand.",
        "",
    ]
    if not events:
        lines.append("No events yet.")
        lines.append("")
    else:
        # sort by start
        def _sk(ev):
            ds = ev.get("dtstart")
            return ds if ds is not None else datetime.min

        sorted_ev = sorted(events, key=_sk)
        lines.append("| Date | Title | Location | Description |")
        lines.append("|------|-------|----------|-------------|")
        for ev in sorted_ev:
            ds = ev.get("dtstart")
            de = ev.get("dtend")
            when = _format_when(ds, de)
            title = ev.get("summary", "(untitled)")
            loc = ev.get("location", "") or ""
            desc = (ev.get("description", "") or "").replace("\n", " ")
            lines.append(f"| {when} | {title} | {loc} | {desc} |")
        lines.append("")
    os.makedirs(os.path.dirname(md_path), exist_ok=True)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


# ---------------------------------------------------------------- formatting helpers
def _format_when(ds, de) -> str:
    if ds is None:
        return ""
    if isinstance(ds, datetime):
        s = ds.strftime("%a %Y-%m-%d %H:%M")
        if de and isinstance(de, datetime):
            if de.date() == ds.date():
                s += "–" + de.strftime("%H:%M")
            else:
                s += " – " + de.strftime("%Y-%m-%d %H:%M")
        return s
    # all-day date
    s = ds.strftime("%a %Y-%m-%d (all-day)")
    if de and isinstance(de, date) and de != ds:
        s += " – " + de.strftime("%Y-%m-%d")
    return s


def _to_datetime_for_compare(d):
    """Normalize date/datetime to a naive datetime for comparison."""
    if d is None:
        return None
    if isinstance(d, datetime):
        if d.tzinfo is not None:
            return d.astimezone(timezone.utc).replace(tzinfo=None)
        return d
    # date -> midnight
    return datetime(d.year, d.month, d.day)


def _parse_arg_date(s: str | None, default: datetime | None = None):
    if not s:
        return default
    s = s.strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    raise SystemExit(f"error: could not parse date/time '{s}' (use YYYY-MM-DD or YYYY-MM-DDTHH:MM[:SS])")


# ---------------------------------------------------------------- commands
def cmd_add(args):
    ics_path = args.ics
    md_path = args.md
    events = read_events(ics_path)

    start = _parse_arg_date(args.start)
    end = _parse_arg_date(args.end) if args.end else None
    if end is None and start is not None:
        # default 1h duration for timed events; none for all-day
        end = start + timedelta(hours=1)

    # Accept --rrule either as a full rule ("FREQ=WEEKLY;COUNT=4") or a bare freq
    # ("WEEKLY" / "DAILY" / "MONTHLY" / "YEARLY"). Normalize to a full RRULE.
    if args.rrule:
        raw = args.rrule.strip()
        if raw.upper().startswith("FREQ="):
            rrule = _parse_rrule(raw)
        else:
            rrule = _parse_rrule(f"FREQ={raw}")
    else:
        rrule = None

    uid = f"chatlab-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}@chatlabai"
    ev = {
        "uid": uid,
        "summary": args.title,
        "dtstart": start,
        "dtend": end,
        "location": args.location or "",
        "description": args.desc or "",
        "rrule": rrule,
    }
    events.append(ev)
    write_calendar(ics_path, events)
    regenerate_md(md_path, events)
    print(f"Added: {args.title}")
    print(f"  When: {_format_when(start, end)}")
    if args.location:
        print(f"  Where: {args.location}")
    if args.rrule:
        print(f"  Recurrence: {args.rrule}")
    print(f"  ICS: {ics_path}")
    print(f"  MD:  {md_path}")


def cmd_list(args):
    ics_path = args.ics
    events = read_events(ics_path)
    now = datetime.now()
    frm = _parse_arg_date(getattr(args, "from"), default=datetime.min)
    to = _parse_arg_date(args.to, default=datetime.max)

    # expand recurrence within [frm, to]
    expanded = []
    for ev in events:
        start = ev.get("dtstart")
        if start is None:
            continue
        rrule = ev.get("rrule")
        # expand up to `to`
        occurrences = expand_rrule(start, rrule, to)
        for occ in occurrences:
            occ_dt = _to_datetime_for_compare(occ)
            if occ_dt is None:
                continue
            if occ_dt < frm or occ_dt > to:
                continue
            e2 = dict(ev)
            # shift end by same delta if timed
            if ev.get("dtend") and isinstance(occ, datetime) and isinstance(ev.get("dtstart"), datetime):
                delta = occ - ev["dtstart"]
                e2["dtstart"] = occ
                e2["dtend"] = ev["dtend"] + delta
            else:
                e2["dtstart"] = occ
            expanded.append(e2)

    expanded.sort(key=lambda e: _to_datetime_for_compare(e["dtstart"]) or datetime.min)

    if not expanded:
        print("No events in range.")
        regenerate_md(args.md, events)  # keep mirror in sync
        return

    print(f"{'Date':<28} {'Title':<30} Location")
    print("-" * 80)
    for ev in expanded:
        when = _format_when(ev["dtstart"], ev.get("dtend"))
        print(f"{when:<28} {ev.get('summary',''):<30} {ev.get('location','')}")
    print(f"\n{len(expanded)} event(s).")
    regenerate_md(args.md, events)


def cmd_next(args):
    events = read_events(args.ics)
    now = datetime.now()
    horizon = now + timedelta(days=365 * 5)
    candidates = []
    for ev in events:
        start = ev.get("dtstart")
        if start is None:
            continue
        occurrences = expand_rrule(start, ev.get("rrule"), horizon)
        for occ in occurrences:
            occ_dt = _to_datetime_for_compare(occ)
            if occ_dt is not None and occ_dt >= now:
                e2 = dict(ev)
                e2["dtstart"] = occ
                if ev.get("dtend") and isinstance(occ, datetime) and isinstance(ev.get("dtstart"), datetime):
                    e2["dtend"] = ev["dtend"] + (occ - ev["dtstart"])
                candidates.append(e2)
    if not candidates:
        print("No upcoming events.")
        return
    candidates.sort(key=lambda e: _to_datetime_for_compare(e["dtstart"]))
    ev = candidates[0]
    occ_dt = _to_datetime_for_compare(ev["dtstart"])
    delta = occ_dt - now
    days = delta.days
    print("Next event:")
    print(f"  {ev.get('summary','(untitled)')}")
    print(f"  When: {_format_when(ev['dtstart'], ev.get('dtend'))}")
    if ev.get("location"):
        print(f"  Where: {ev['location']}")
    if ev.get("description"):
        print(f"  Notes: {ev['description']}")
    if days == 0:
        hrs = delta.seconds // 3600
        print(f"  In: today ({hrs}h)" if hrs else "  In: today")
    else:
        print(f"  In: {days} day(s)")


def cmd_today(args):
    today = date.today()
    now = datetime.now()
    print(f"Today: {today.strftime('%A, %B %d, %Y')} ({today.isoformat()})")
    events = read_events(args.ics)
    todays = []
    for ev in events:
        start = ev.get("dtstart")
        if start is None:
            continue
        occurrences = expand_rrule(start, ev.get("rrule"), now + timedelta(days=1))
        for occ in occurrences:
            occ_date = occ.date() if isinstance(occ, datetime) else occ
            if occ_date == today:
                e2 = dict(ev)
                e2["dtstart"] = occ
                if ev.get("dtend") and isinstance(occ, datetime) and isinstance(ev.get("dtstart"), datetime):
                    e2["dtend"] = ev["dtend"] + (occ - ev["dtstart"])
                todays.append(e2)
    if not todays:
        print("No events today.")
        return
    todays.sort(key=lambda e: _to_datetime_for_compare(e["dtstart"]) or datetime.min)
    print(f"{len(todays)} event(s) today:")
    for ev in todays:
        print(f"  - {_format_when(ev['dtstart'], ev.get('dtend'))}: {ev.get('summary','(untitled)')}")
        if ev.get("location"):
            print(f"      where: {ev['location']}")


def cmd_deadlines(args):
    events = read_events(args.ics)
    now = datetime.now()
    horizon = now + timedelta(days=365 * 2)
    deadlines = []
    for ev in events:
        hay = f"{ev.get('summary','')} {ev.get('description','')}".lower()
        if not any(kw in hay for kw in DEADLINE_KEYWORDS):
            continue
        start = ev.get("dtstart")
        if start is None:
            continue
        occurrences = expand_rrule(start, ev.get("rrule"), horizon)
        for occ in occurrences:
            occ_dt = _to_datetime_for_compare(occ)
            if occ_dt is None:
                continue
            e2 = dict(ev)
            e2["dtstart"] = occ
            if ev.get("dtend") and isinstance(occ, datetime) and isinstance(ev.get("dtstart"), datetime):
                e2["dtend"] = ev["dtend"] + (occ - ev["dtstart"])
            deadlines.append(e2)
    if not deadlines:
        print("No deadline events found.")
        print("(Events are flagged as deadlines if their title/description contains: "
              + ", ".join(DEADLINE_KEYWORDS) + ")")
        return
    deadlines.sort(key=lambda e: _to_datetime_for_compare(e["dtstart"]) or datetime.min)
    print("Deadlines:")
    for ev in deadlines:
        occ_dt = _to_datetime_for_compare(ev["dtstart"])
        delta = occ_dt - now
        days = delta.days
        when = _format_when(ev["dtstart"], ev.get("dtend"))
        if days < 0:
            countdown = f"{abs(days)} day(s) ago"
        elif days == 0:
            countdown = "TODAY"
        else:
            countdown = f"in {days} day(s)"
        print(f"  - [{countdown}] {ev.get('summary','(untitled)')}  ({when})")


# ---------------------------------------------------------------- CLI
def build_parser():
    p = argparse.ArgumentParser(
        prog="cal.py",
        description="CHATLabAI lab calendar — self-contained lab calendar (add/list/next/today/deadlines).",
    )
    p.add_argument("--ics", default=DEFAULT_ICS, help=f"path to .ics (default: {DEFAULT_ICS})")
    p.add_argument("--md", default=DEFAULT_MD, help=f"path to .md mirror (default: {DEFAULT_MD})")
    sub = p.add_subparsers(dest="command", required=True)

    a = sub.add_parser("add", help="add an event")
    a.add_argument("--title", required=True)
    a.add_argument("--start", required=True, help="YYYY-MM-DD or YYYY-MM-DDTHH:MM[:SS]")
    a.add_argument("--end", default=None, help="YYYY-MM-DD or YYYY-MM-DDTHH:MM[:SS] (default: +1h)")
    a.add_argument("--location", default=None)
    a.add_argument("--desc", default=None)
    a.add_argument("--rrule", default=None, help="e.g. FREQ=WEEKLY (DAILY|WEEKLY|MONTHLY|YEARLY)")
    a.set_defaults(func=cmd_add)

    l = sub.add_parser("list", help="list events")
    l.add_argument("--from", dest="from", default=None, help="YYYY-MM-DD")
    l.add_argument("--to", default=None, help="YYYY-MM-DD")
    l.set_defaults(func=cmd_list)

    n = sub.add_parser("next", help="show next upcoming event")
    n.set_defaults(func=cmd_next)

    t = sub.add_parser("today", help="show today's date and events")
    t.set_defaults(func=cmd_today)

    d = sub.add_parser("deadlines", help="show deadline events with countdown")
    d.set_defaults(func=cmd_deadlines)
    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
