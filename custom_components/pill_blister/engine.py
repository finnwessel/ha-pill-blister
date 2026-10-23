"""Pill Blister engine: cycle, intake window, journal, assignment and protection notices.

Pure Python without Home Assistant imports, so the rules can be tested in isolation.
All datetimes are timezone-aware; ``Params.tz`` is the local time zone.

Terms
-----
dose day      A calendar day on which a pill is scheduled (cycle position < cycle_on).
dose time     Planned intake time on a dose day (e.g. 20:00).
window        [dose - window_before, dose + window_after]: an intake in this range
              belongs to that dose day, also across midnight.
deadline      dose + missed_after: later (or never) counts as a missed pill.
notice        A warning that protection may be reduced, derived only from the rules the
              user entered from the package leaflet. The engine never states "protected".
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time, timedelta, tzinfo
from typing import Any

LATE_ENTRY_AFTER = timedelta(minutes=30)
RETENTION_DAYS = 400
SCAN_DAYS = 42


# --------------------------------------------------------------------------- rules


@dataclass(frozen=True)
class MissedRule:
    """What applies when a pill is missed (backup contraception for N days + text)."""

    backup_days: float
    text: str = ""

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> MissedRule | None:
        if not d:
            return None
        return cls(backup_days=float(d.get("backup_days", 0)), text=str(d.get("text") or ""))


@dataclass(frozen=True)
class IllnessRule:
    """An event like vomiting or diarrhoea shortly after an intake."""

    key: str
    name: str
    within_hours: float
    replacement_hours: float = 0.0  # 0 = no replacement pill possible
    as_missed: bool = True
    backup_days: float = 0.0  # only when not as_missed
    until_cycle_end: bool = False  # notice lasts for the remaining days of the cycle
    text: str = ""

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> IllnessRule:
        return cls(
            key=str(d["key"]),
            name=str(d["name"]),
            within_hours=float(d["within_hours"]),
            replacement_hours=float(d.get("replacement_hours") or 0),
            as_missed=bool(d.get("as_missed", True)),
            backup_days=float(d.get("backup_days") or 0),
            until_cycle_end=bool(d.get("until_cycle_end")),
            text=str(d.get("text") or ""),
        )


@dataclass(frozen=True)
class Params:
    tz: tzinfo
    cycle_on: int
    cycle_off: int
    window_before: timedelta
    window_after: timedelta
    on_time: timedelta
    missed_after: timedelta
    missed_rules: tuple[MissedRule, ...]  # index 0 = week 1, last one also for later weeks
    multi_missed: MissedRule | None = None
    illnesses: tuple[IllnessRule, ...] = ()

    @property
    def cycle_len(self) -> int:
        return self.cycle_on + self.cycle_off

    def illness(self, key: str) -> IllnessRule | None:
        return next((r for r in self.illnesses if r.key == key), None)


# --------------------------------------------------------------------------- journal


@dataclass
class Entry:
    day: date
    time: datetime | None  # None = taken, time unknown
    source: str = "manual"
    late_entry: bool = False  # recorded noticeably after the intake (nachgetragen)
    replacement: datetime | None = None  # replacement pill after vomiting etc.

    def to_dict(self) -> dict[str, Any]:
        return {
            "day": self.day.isoformat(),
            "time": self.time.isoformat() if self.time else None,
            "source": self.source,
            "late_entry": self.late_entry,
            "replacement": self.replacement.isoformat() if self.replacement else None,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Entry:
        return cls(
            day=date.fromisoformat(d["day"]),
            time=datetime.fromisoformat(d["time"]) if d.get("time") else None,
            source=d.get("source") or "manual",
            late_entry=bool(d.get("late_entry")),
            replacement=datetime.fromisoformat(d["replacement"]) if d.get("replacement") else None,
        )


@dataclass
class Event:
    id: str
    type: str
    time: datetime

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "type": self.type, "time": self.time.isoformat()}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Event:
        return cls(id=d["id"], type=d["type"], time=datetime.fromisoformat(d["time"]))


@dataclass
class Pending:
    """An intake that could not be assigned to a dose day unambiguously."""

    time: datetime
    source: str
    options: list[date]

    def to_dict(self) -> dict[str, Any]:
        return {
            "time": self.time.isoformat(),
            "source": self.source,
            "options": [d.isoformat() for d in self.options],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Pending:
        return cls(
            time=datetime.fromisoformat(d["time"]),
            source=d.get("source") or "manual",
            options=[date.fromisoformat(x) for x in d.get("options") or []],
        )


@dataclass
class Journal:
    blister_start: date
    dose_time: time
    tracking_since: date
    entries: dict[date, Entry] = field(default_factory=dict)
    events: list[Event] = field(default_factory=list)
    pending: Pending | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "blister_start": self.blister_start.isoformat(),
            "dose_time": self.dose_time.isoformat(timespec="minutes"),
            "tracking_since": self.tracking_since.isoformat(),
            "entries": [e.to_dict() for e in sorted(self.entries.values(), key=lambda e: e.day)],
            "events": [e.to_dict() for e in sorted(self.events, key=lambda e: e.time)],
            "pending": self.pending.to_dict() if self.pending else None,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Journal:
        entries = [Entry.from_dict(x) for x in d.get("entries") or []]
        return cls(
            blister_start=date.fromisoformat(d["blister_start"]),
            dose_time=time.fromisoformat(d["dose_time"]),
            tracking_since=date.fromisoformat(d["tracking_since"]),
            entries={e.day: e for e in entries},
            events=[Event.from_dict(x) for x in d.get("events") or []],
            pending=Pending.from_dict(d["pending"]) if d.get("pending") else None,
        )


# --------------------------------------------------------------------------- results


@dataclass(frozen=True)
class Notice:
    id: str
    kind: str  # missed | late | illness | replacement
    day: date
    pill: int
    start: datetime
    end: datetime
    reason: str  # short, machine-friendly German reason built by the engine
    text: str  # instruction text from the package leaflet rules
    event_type: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "day": self.day.isoformat(),
            "pill": self.pill,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "reason": self.reason,
            "text": self.text,
            "event_type": self.event_type,
        }


class AssignmentNeeded(Exception):
    """The intake was stored as pending; it must be assigned with ``assign_pending``."""

    def __init__(self, pending: Pending) -> None:
        super().__init__("intake needs assignment")
        self.pending = pending


class EngineError(ValueError):
    """User-facing error with a translation key."""

    def __init__(self, key: str, **placeholders: Any) -> None:
        super().__init__(key)
        self.key = key
        self.placeholders = {k: str(v) for k, v in placeholders.items()}


# --------------------------------------------------------------------------- engine


def _hours(td: timedelta) -> str:
    minutes = round(abs(td.total_seconds()) / 60)
    h, m = divmod(minutes, 60)
    if h and m:
        return f"{h} h {m} min"
    if h:
        return f"{h} h"
    return f"{m} min"


class PillBlister:
    def __init__(self, params: Params, journal: Journal) -> None:
        self.p = params
        self.j = journal

    # ---------------------------------------------------------------- calendar

    def local(self, dt: datetime) -> datetime:
        return dt.astimezone(self.p.tz)

    def cycle_pos(self, day: date) -> int:
        return (day - self.j.blister_start).days % self.p.cycle_len

    def is_dose_day(self, day: date) -> bool:
        return self.cycle_pos(day) < self.p.cycle_on

    def pill_number(self, day: date) -> int | None:
        pos = self.cycle_pos(day)
        return pos + 1 if pos < self.p.cycle_on else None

    def blister_start_for(self, day: date) -> date:
        return day - timedelta(days=self.cycle_pos(day))

    def week_index(self, day: date) -> int:
        return min(self.cycle_pos(day) // 7, len(self.p.missed_rules) - 1)

    def dose_dt(self, day: date) -> datetime:
        return datetime.combine(day, self.j.dose_time).replace(tzinfo=self.p.tz)

    def window(self, day: date) -> tuple[datetime, datetime]:
        dose = self.dose_dt(day)
        return dose - self.p.window_before, dose + self.p.window_after

    def deadline(self, day: date) -> datetime:
        return self.dose_dt(day) + self.p.missed_after

    def in_window(self, day: date, t: datetime) -> bool:
        start, end = self.window(day)
        return start <= t <= end

    def deviation(self, day: date, t: datetime) -> timedelta:
        return t - self.dose_dt(day)

    def punctuality(self, day: date, t: datetime | None) -> str:
        if t is None:
            return "unknown"
        dev = self.deviation(day, t)
        if t > self.deadline(day):
            return "missed"
        if abs(dev) <= self.p.on_time:
            return "on_time"
        return "late" if dev > timedelta(0) else "early"

    # ---------------------------------------------------------------- recording

    def _candidates(self, t: datetime) -> list[date]:
        local = self.local(t).date()
        days = [local - timedelta(days=1), local, local + timedelta(days=1)]
        return [d for d in days if self.is_dose_day(d) and self.in_window(d, t)]

    def resolve_time(self, day: date, tod: time) -> datetime:
        """Clock time entered for a dose day; times after midnight belong to the next date."""
        t = datetime.combine(day, tod).replace(tzinfo=self.p.tz)
        nxt = t + timedelta(days=1)
        start, end = self.window(day)
        if t < start and nxt <= end:
            return nxt
        return t

    def mark_taken(
        self,
        now: datetime,
        t: datetime | None = None,
        *,
        day: date | None = None,
        time_unknown: bool = False,
        source: str = "manual",
    ) -> Entry:
        """Record an intake.

        Without ``day`` the dose day is derived from the intake window. If that is not
        unambiguous, the intake is stored as pending and ``AssignmentNeeded`` is raised.
        """
        if time_unknown:
            if day is None:
                raise EngineError("day_required")
            return self._store(day, None, now, source, late_entry=True)
        t = t or now
        if t > now + timedelta(minutes=1):
            raise EngineError("time_in_future")
        if day is not None:
            if not self.is_dose_day(day):
                raise EngineError("not_a_dose_day", day=day.isoformat())
            return self._store(day, t, now, source)
        candidates = self._candidates(t)
        open_days = [d for d in candidates if self._is_open(d)]
        if len(open_days) == 1:
            return self._store(open_days[0], t, now, source)
        # In the window of an already recorded day → offer replacing it, plus open days.
        options = sorted(set(candidates) | set(self._options(t, open_only=bool(candidates))))
        if not options:
            raise EngineError("no_dose_day")
        self.j.pending = Pending(time=t, source=source, options=options)
        raise AssignmentNeeded(self.j.pending)

    def _options(self, t: datetime, open_only: bool = False) -> list[date]:
        local = self.local(t).date()
        days = [local - timedelta(days=1), local]
        open_days = [d for d in days if self.is_dose_day(d) and self._is_open(d)]
        if open_days or open_only:
            return open_days
        return [d for d in days if self.is_dose_day(d) and d >= self.j.tracking_since]

    def _is_open(self, day: date) -> bool:
        """No entry yet and tracked (days before setup are unknown, not open)."""
        return day not in self.j.entries and day >= self.j.tracking_since

    def _store(
        self, day: date, t: datetime | None, now: datetime, source: str, late_entry: bool = False
    ) -> Entry:
        old = self.j.entries.get(day)
        entry = Entry(
            day=day,
            time=t,
            source=source,
            late_entry=late_entry or (t is not None and now - t > LATE_ENTRY_AFTER),
            replacement=old.replacement if old else None,
        )
        self.j.entries[day] = entry
        if self.j.pending and day in self.j.pending.options:
            self.j.pending = None
        return entry

    def assign_pending(self, now: datetime, day: date | None) -> Entry | None:
        """Assign the pending intake to ``day`` or discard it (``day`` None)."""
        pending = self.j.pending
        if pending is None:
            raise EngineError("nothing_pending")
        self.j.pending = None
        if day is None:
            return None
        if not self.is_dose_day(day):
            self.j.pending = pending
            raise EngineError("not_a_dose_day", day=day.isoformat())
        return self._store(day, pending.time, now, pending.source)

    def remove_entry(self, day: date) -> None:
        if self.j.entries.pop(day, None) is None:
            raise EngineError("no_entry", day=day.isoformat())

    def start_blister(self, day: date) -> None:
        self.j.blister_start = day

    def set_dose_time(self, tod: time) -> None:
        self.j.dose_time = tod.replace(second=0, microsecond=0)

    def report_event(self, now: datetime, key: str, t: datetime | None = None) -> Event:
        if self.p.illness(key) is None:
            raise EngineError("unknown_event", type=key)
        t = t or now
        if t > now + timedelta(minutes=1):
            raise EngineError("time_in_future")
        ev = Event(id=uuid.uuid4().hex[:12], type=key, time=t)
        self.j.events.append(ev)
        return ev

    def remove_event(self, event_id: str) -> None:
        before = len(self.j.events)
        self.j.events = [e for e in self.j.events if e.id != event_id]
        if len(self.j.events) == before:
            raise EngineError("no_event")

    def mark_replacement(self, now: datetime, t: datetime | None = None) -> Entry:
        """Record a replacement pill for the intake affected by the latest open event."""
        t = t or now
        for ev, entry, rule in reversed(self._affected()):
            if rule.replacement_hours <= 0 or entry.replacement is not None:
                continue
            assert entry.time is not None
            if ev.time <= t <= entry.time + timedelta(hours=rule.replacement_hours):
                entry.replacement = t
                return entry
        raise EngineError("no_replacement_needed")

    def prune(self, now: datetime) -> None:
        limit = self.local(now).date() - timedelta(days=RETENTION_DAYS)
        self.j.entries = {d: e for d, e in self.j.entries.items() if d >= limit}
        self.j.events = [e for e in self.j.events if self.local(e.time).date() >= limit]

    # ---------------------------------------------------------------- notices

    def _affected(self) -> list[tuple[Event, Entry, IllnessRule]]:
        """Events with the intake they affect (latest timed intake within ``within_hours``)."""
        out = []
        timed = sorted((e for e in self.j.entries.values() if e.time), key=lambda e: e.time)
        for ev in sorted(self.j.events, key=lambda e: e.time):
            rule = self.p.illness(ev.type)
            if rule is None:
                continue
            before = [e for e in timed if e.time <= ev.time]
            if not before:
                continue
            entry = before[-1]
            if ev.time - entry.time <= timedelta(hours=rule.within_hours):
                out.append((ev, entry, rule))
        return out

    def notices(self, now: datetime, include_past: bool = False) -> list[Notice]:
        today = self.local(now).date()
        out: list[Notice] = []
        missed_per_blister: dict[date, int] = {}
        start_day = max(today - timedelta(days=SCAN_DAYS), self.j.tracking_since)
        d = start_day
        while d <= today:
            if self.is_dose_day(d):
                entry = self.j.entries.get(d)
                deadline = self.deadline(d)
                anchor: datetime | None = None
                kind = ""
                if entry is None and now > deadline:
                    anchor, kind = self.dose_dt(d), "missed"
                elif entry is not None and entry.time is not None and entry.time > deadline:
                    anchor, kind = entry.time, "late"
                if anchor is not None:
                    blister = self.blister_start_for(d)
                    missed_per_blister[blister] = missed_per_blister.get(blister, 0) + 1
                    rule = self.p.missed_rules[self.week_index(d)]
                    if missed_per_blister[blister] > 1 and self.p.multi_missed:
                        rule = self.p.multi_missed
                    pill = self.pill_number(d) or 0
                    if kind == "missed":
                        reason = f"Pille {pill} nicht eingenommen"
                    else:
                        reason = f"Pille {pill} {_hours(self.deviation(d, entry.time))} zu spät"  # type: ignore[union-attr]
                    if rule.backup_days > 0:
                        out.append(
                            Notice(
                                id=f"{kind}-{d.isoformat()}",
                                kind=kind,
                                day=d,
                                pill=pill,
                                start=deadline,
                                end=anchor + timedelta(days=rule.backup_days),
                                reason=reason,
                                text=rule.text,
                            )
                        )
            d += timedelta(days=1)

        for ev, entry, rule in self._affected():
            if entry.time is None or self.local(ev.time).date() < start_day:
                continue
            pill = self.pill_number(entry.day) or 0
            rep_deadline = entry.time + timedelta(hours=rule.replacement_hours)
            replaced = (
                entry.replacement is not None and ev.time <= entry.replacement <= rep_deadline
            )
            if replaced:
                continue
            if rule.replacement_hours > 0 and now <= rep_deadline:
                out.append(
                    Notice(
                        id=f"replacement-{ev.id}",
                        kind="replacement",
                        day=entry.day,
                        pill=pill,
                        start=ev.time,
                        end=rep_deadline,
                        reason=(
                            f"{rule.name} nach Pille {pill} · Ersatzpille bis "
                            f"{self.local(rep_deadline):%H:%M} möglich"
                        ),
                        text=rule.text,
                        event_type=rule.key,
                    )
                )
                continue
            if rule.until_cycle_end:
                # Until pill 1 of the next blister (remaining days of the cycle incl. pause).
                next_start = self.blister_start_for(entry.day) + timedelta(days=self.p.cycle_len)
                end = self.dose_dt(next_start)
                text = rule.text
            else:
                if rule.as_missed:
                    mrule = self.p.missed_rules[self.week_index(entry.day)]
                    days, text = mrule.backup_days, mrule.text or rule.text
                else:
                    days, text = rule.backup_days, rule.text
                if days <= 0:
                    continue
                end = ev.time + timedelta(days=days)
            out.append(
                Notice(
                    id=f"illness-{ev.id}",
                    kind="illness",
                    day=entry.day,
                    pill=pill,
                    start=ev.time,
                    end=end,
                    reason=f"{rule.name} nach Pille {pill}",
                    text=text,
                    event_type=rule.key,
                )
            )

        if include_past:
            return out
        return [n for n in out if n.start <= now < n.end]

    # ---------------------------------------------------------------- snapshot

    def open_overdue(self, now: datetime) -> date | None:
        """Yesterday's dose if still open and its window has not closed."""
        yesterday = self.local(now).date() - timedelta(days=1)
        if (
            self.is_dose_day(yesterday)
            and self._is_open(yesterday)
            and now <= self.window(yesterday)[1]
        ):
            return yesterday
        return None

    def status(self, now: datetime) -> str:
        today = self.local(now).date()
        if self.open_overdue(now):
            return "overdue"
        if not self.is_dose_day(today):
            return "last_pause_day" if self.cycle_pos(today) == self.p.cycle_len - 1 else "pause"
        if today in self.j.entries:
            return "done"
        return "due" if now >= self.dose_dt(today) else "later"

    def is_due(self, now: datetime) -> bool:
        return self.status(now) in ("due", "overdue")

    def missing_days(self, now: datetime) -> list[date]:
        """Dose days of the current blister before today without an entry."""
        today = self.local(now).date()
        start = self.blister_start_for(today)
        end = today if self.is_dose_day(today) else start + timedelta(days=self.p.cycle_on)
        out = []
        d = max(start, self.j.tracking_since)
        while d < end:
            if self.is_dose_day(d) and d not in self.j.entries and now > self.window(d)[1]:
                out.append(d)
            d += timedelta(days=1)
        return out

    def last_taken(self) -> Entry | None:
        timed = [e for e in self.j.entries.values() if e.time]
        return max(timed, key=lambda e: e.time) if timed else None  # type: ignore[arg-type,return-value]

    def days(self, now: datetime) -> list[dict[str, Any]]:
        """The dose days of the current blister (in a pause: the one just finished)."""
        today = self.local(now).date()
        start = self.blister_start_for(today)
        events_by_day: dict[date, list[str]] = {}
        for ev, entry, _rule in self._affected():
            events_by_day.setdefault(entry.day, []).append(ev.id)
        out = []
        for k in range(self.p.cycle_on):
            d = start + timedelta(days=k)
            entry = self.j.entries.get(d)
            item: dict[str, Any] = {
                "date": d.isoformat(),
                "pill": k + 1,
                "weekday": d.weekday(),
            }
            if entry is not None:
                item["state"] = "taken"
                item["time"] = self.local(entry.time).isoformat() if entry.time else None
                item["punctuality"] = self.punctuality(d, entry.time)
                if entry.time is not None:
                    item["deviation_min"] = round(
                        self.deviation(d, entry.time).total_seconds() / 60
                    )
                    item["in_window"] = self.in_window(d, entry.time)
                item["late_entry"] = entry.late_entry
                item["source"] = entry.source
                if entry.replacement:
                    item["replacement"] = self.local(entry.replacement).isoformat()
            elif d > today:
                item["state"] = "future"
            elif d < self.j.tracking_since:
                item["state"] = "untracked"
            elif now <= self.window(d)[1]:
                item["state"] = "open"
            else:
                item["state"] = "missing"
            if d in events_by_day:
                item["events"] = events_by_day[d]
            out.append(item)
        return out

    def snapshot(self, now: datetime) -> dict[str, Any]:
        today = self.local(now).date()
        start = self.blister_start_for(today)
        notices = self.notices(now)
        dose_today = self.dose_dt(today)
        entry_today = self.j.entries.get(today)
        pos = self.cycle_pos(today)
        overdue = self.open_overdue(now)
        return {
            "status": self.status(now),
            "today": today.isoformat(),
            "pill_number": self.pill_number(today),
            "cycle_day": pos + 1,
            "cycle_on": self.p.cycle_on,
            "cycle_off": self.p.cycle_off,
            "blister_start": start.isoformat(),
            "pause_start": (start + timedelta(days=self.p.cycle_on)).isoformat(),
            "next_blister": (start + timedelta(days=self.p.cycle_len)).isoformat(),
            "dose_time": self.j.dose_time.isoformat(timespec="minutes"),
            "dose_today": dose_today.isoformat() if self.is_dose_day(today) else None,
            "window_start": self.window(today)[0].isoformat() if self.is_dose_day(today) else None,
            "window_end": self.window(today)[1].isoformat() if self.is_dose_day(today) else None,
            "missed_deadline": self.deadline(today).isoformat()
            if self.is_dose_day(today)
            else None,
            "taken_at": self.local(entry_today.time).isoformat()
            if entry_today and entry_today.time
            else None,
            "punctuality": self.punctuality(today, entry_today.time) if entry_today else None,
            "overdue_day": overdue.isoformat() if overdue else None,
            "overdue_deadline": self.deadline(overdue).isoformat() if overdue else None,
            "missing": [d.isoformat() for d in self.missing_days(now)],
            "days": self.days(now),
            "notices": [n.to_dict() for n in notices],
            "notice_until": max(n.end for n in notices).isoformat() if notices else None,
            "pending": self.j.pending.to_dict() if self.j.pending else None,
            "events": [
                {"id": ev.id, "type": ev.type, "time": self.local(ev.time).isoformat()}
                for ev in self.j.events
                if self.local(ev.time).date() >= start - timedelta(days=1)
            ],
        }


def with_params(engine: PillBlister, **changes: Any) -> PillBlister:
    return PillBlister(replace(engine.p, **changes), engine.j)
