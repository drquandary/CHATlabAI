---
name: lab-calendar
description: Self-contained lab calendar for the Chatterjee lab. Use for "lab calendar", "what's on", "add event", "deadline", "today's date", "next lab meeting", "submission deadline", "IRB renewal", "what's today", or any scheduling/deadline question. Maintains calendar/lab-calendar.ics with an auto-regenerated readable mirror at calendar/lab-calendar.md. No Google or external auth required.
---

# Lab Calendar

A self-contained calendar for the lab: events, deadlines, and "what's today". All data lives in
`calendar/lab-calendar.ics` (iCalendar format) with a readable `calendar/lab-calendar.md` mirror
that is **auto-regenerated on every change**. No Google Calendar, no external auth, no network.

## When to use

- "what's on the lab calendar today / this week"
- "add a lab meeting / deadline / IRB renewal"
- "next lab meeting"
- "submission deadline countdown"
- "what's today's date"

## Setup

The Python `icalendar` package is *optional*. If present it is used for richer recurrence (RRULE)
expansion; if absent the script falls back to a pure-stdlib iCalendar reader/writer so the calendar
is **always functional**. To install the optional package:

```bash
./install.sh   # or: python3 -m pip install icalendar
```

## Commands

All commands operate on `calendar/lab-calendar.ics` and regenerate `calendar/lab-calendar.md`
relative to the workspace root (auto-detected; override with `--ics` / `--md`).

### add

```bash
python3 .pi/skills/lab-calendar/scripts/cal.py add \
  --title "Lab Meeting" \
  --start 2026-07-01T10:00:00 \
  --end 2026-07-01T11:00:00 \
  [--location "Godcher Lab"] \
  [--desc "Weekly sync"] \
  [--rrule FREQ=WEEKLY]            # DAILY | WEEKLY | MONTHLY | YEARLY
```

Date/times accept `YYYY-MM-DD` (all-day) or `YYYY-MM-DDTHH:MM:SS`.

### list

```bash
python3 .pi/skills/lab-calendar/scripts/cal.py list [--from 2026-07-01] [--to 2026-08-01]
```

Lists events in date range (defaults to all upcoming + past).

### next

```bash
python3 .pi/skills/lab-calendar/scripts/cal.py next
```

Shows the next upcoming event (after now).

### today

```bash
python3 .pi/skills/lab-calendar/scripts/cal.py today
```

Prints the current date and any events scheduled for today.

### deadlines

```bash
python3 .pi/skills/lab-calendar/scripts/cal.py deadlines
```

Lists events whose title or description contains a deadline keyword
(`deadline`, `submission`, `IRB`, `renewal`) and shows a countdown in days.

## Safety

- All operations are on the local `.ics` / `.md` files only — no network, no external auth.
- The `.md` mirror is regenerated from the `.ics` on every `add`; never edit it by hand.

## Script reference

- `scripts/cal.py` — the whole skill. `python3 cal.py --help` for the command list.
