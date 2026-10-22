"""Calendar: journal in the past, planned intakes and pauses ahead, notices as ranges."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import PillBlisterConfigEntry
from .entity import PillEntity

PUNCTUALITY = {
    "on_time": "pünktlich",
    "late": "später",
    "early": "früher",
    "missed": "zu spät",
    "unknown": "Uhrzeit unbekannt",
}
DOSE_MINUTES = 15


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PillBlisterConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([PillCalendar(entry.runtime_data)])


class PillCalendar(PillEntity, CalendarEntity):
    def __init__(self, controller) -> None:
        super().__init__(controller, "calendar", "calendar")

    @property
    def event(self) -> CalendarEvent | None:
        now = dt_util.now()
        upcoming = self._events(now - timedelta(days=1), now + timedelta(days=30))
        current = [e for e in upcoming if e.end_datetime_local > now]
        return min(current, key=lambda e: e.start_datetime_local) if current else None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        return self._events(start_date, end_date)

    def _events(self, start: datetime, end: datetime) -> list[CalendarEvent]:
        e = self.controller.engine
        if e is None:
            return []
        now = dt_util.now()
        today = now.date()
        out: list[CalendarEvent] = []
        # Start early enough to catch a pause that began before the range (filtered below).
        d: date = e.local(start).date() - timedelta(days=e.p.cycle_off + 1)
        last = e.local(end).date()
        while d <= last:
            pill = e.pill_number(d)
            entry = e.j.entries.get(d)
            if entry is not None:
                if entry.time is None:
                    out.append(
                        CalendarEvent(
                            start=d,
                            end=d + timedelta(days=1),
                            summary=f"Pille {pill} ✓",
                            description="Genommen · Uhrzeit unbekannt",
                            uid=f"taken-{d}",
                        )
                    )
                else:
                    t = e.local(entry.time)
                    desc = f"Genommen um {t:%H:%M} · {PUNCTUALITY[e.punctuality(d, entry.time)]}"
                    if entry.late_entry:
                        desc += " · nachgetragen"
                    out.append(
                        CalendarEvent(
                            start=t,
                            end=t + timedelta(minutes=DOSE_MINUTES),
                            summary=f"Pille {pill} ✓",
                            description=desc,
                            uid=f"taken-{d}",
                        )
                    )
            elif pill is not None and d >= today:
                dose = e.dose_dt(d)
                out.append(
                    CalendarEvent(
                        start=dose,
                        end=dose + timedelta(minutes=DOSE_MINUTES),
                        summary=f"Pille {pill}",
                        uid=f"dose-{d}",
                    )
                )
            elif pill is not None and d >= e.j.tracking_since:
                out.append(
                    CalendarEvent(
                        start=d,
                        end=d + timedelta(days=1),
                        summary=f"Pille {pill} nicht eingetragen",
                        uid=f"missing-{d}",
                    )
                )
            if e.cycle_pos(d) == e.p.cycle_on:  # first pause day
                pause_end = d + timedelta(days=e.p.cycle_off)
                out.append(
                    CalendarEvent(start=d, end=pause_end, summary="Pillenpause", uid=f"pause-{d}")
                )
            d += timedelta(days=1)
        for n in e.notices(now, include_past=True):
            out.append(
                CalendarEvent(
                    start=e.local(n.start),
                    end=e.local(n.end),
                    summary=f"Hinweis: {n.reason}",
                    description=n.text or None,
                    uid=f"notice-{n.id}",
                )
            )
        return [ev for ev in out if _overlaps(ev, start, end)]


def _overlaps(ev: CalendarEvent, start: datetime, end: datetime) -> bool:
    return ev.end_datetime_local > start and ev.start_datetime_local < end
