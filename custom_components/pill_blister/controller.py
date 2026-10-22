"""Home Assistant glue: storage, clock, events and the engine."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date, datetime, time, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    CONF_BLISTER_START,
    CONF_CYCLE_OFF,
    CONF_CYCLE_ON,
    CONF_DOSE_TIME,
    CONF_ILLNESSES,
    CONF_MISSED_AFTER,
    CONF_MISSED_RULES,
    CONF_MULTI_MISSED,
    CONF_NAME,
    CONF_ON_TIME,
    CONF_PERSON,
    CONF_WINDOW_AFTER,
    CONF_WINDOW_BEFORE,
    DEFAULT_ON_TIME,
    DOMAIN,
    EVENT_DUE,
    EVENT_ENTRY_CHANGED,
    EVENT_MISSED,
    EVENT_NEEDS_ASSIGNMENT,
    EVENT_NOTICE_ENDED,
    EVENT_NOTICE_STARTED,
    EVENT_TAKEN,
    STORAGE_VERSION,
    TICK_SECONDS,
)
from .engine import (
    AssignmentNeeded,
    Entry,
    IllnessRule,
    Journal,
    MissedRule,
    Params,
    PillBlister,
)

_LOGGER = logging.getLogger(__name__)


def build_params(hass: HomeAssistant, options: dict[str, Any]) -> Params:
    rules = tuple(MissedRule.from_dict(r) for r in options[CONF_MISSED_RULES])
    return Params(
        tz=dt_util.get_time_zone(hass.config.time_zone) or dt_util.DEFAULT_TIME_ZONE,
        cycle_on=int(options[CONF_CYCLE_ON]),
        cycle_off=int(options[CONF_CYCLE_OFF]),
        window_before=timedelta(hours=float(options[CONF_WINDOW_BEFORE])),
        window_after=timedelta(hours=float(options[CONF_WINDOW_AFTER])),
        on_time=timedelta(minutes=float(options.get(CONF_ON_TIME, DEFAULT_ON_TIME))),
        missed_after=timedelta(hours=float(options[CONF_MISSED_AFTER])),
        missed_rules=rules,  # type: ignore[arg-type]
        multi_missed=MissedRule.from_dict(options.get(CONF_MULTI_MISSED)),
        illnesses=tuple(IllnessRule.from_dict(r) for r in options.get(CONF_ILLNESSES) or []),
    )


class PillController:
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.name: str = entry.data[CONF_NAME]
        self.person: str | None = entry.options.get(CONF_PERSON) or entry.data.get(CONF_PERSON)
        self.params = build_params(hass, dict(entry.options))
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}"
        )
        self.engine: PillBlister | None = None
        self._fired: dict[str, list[str]] = {"due": [], "missed": [], "notices": []}
        self._listeners: list[Callable[[], None]] = []
        self._unsubs: list[CALLBACK_TYPE] = []
        self.snapshot: dict[str, Any] = {}

    # ------------------------------------------------------------ lifecycle

    async def async_start(self) -> None:
        data = await self._store.async_load()
        journal: Journal | None = None
        if data:
            try:
                journal = Journal.from_dict(data["journal"])
                self._fired = {
                    k: list(v) for k, v in (data.get("fired") or {}).items()
                } or self._fired
            except (KeyError, TypeError, ValueError):
                _LOGGER.warning("Stored journal of %s is invalid, starting fresh", self.name)
        if journal is None:
            journal = Journal(
                blister_start=date.fromisoformat(self.entry.data[CONF_BLISTER_START]),
                dose_time=time.fromisoformat(self.entry.data[CONF_DOSE_TIME]),
                tracking_since=dt_util.now().date(),
            )
        for key in ("due", "missed", "notices"):
            self._fired.setdefault(key, [])
        self.engine = PillBlister(self.params, journal)
        self._unsubs.append(
            async_track_time_interval(self.hass, self._on_tick, timedelta(seconds=TICK_SECONDS))
        )
        await self.async_refresh(save=False, fire=False)

    async def async_stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        await self._store.async_save(self._data())

    def _data(self) -> dict[str, Any]:
        assert self.engine
        return {"journal": self.engine.j.to_dict(), "fired": self._fired}

    @callback
    def async_add_listener(self, update: Callable[[], None]) -> CALLBACK_TYPE:
        self._listeners.append(update)

        @callback
        def remove() -> None:
            self._listeners.remove(update)

        return remove

    # ------------------------------------------------------------ refresh

    async def _on_tick(self, _now: datetime) -> None:
        await self.async_refresh(save=False)

    async def async_refresh(self, save: bool = True, fire: bool = True) -> None:
        assert self.engine
        now = dt_util.now()
        self.snapshot = self.engine.snapshot(now)
        if fire:
            self._fire_time_events(now)
        else:
            self._mark_current_as_fired(now)
        if save:
            self.engine.prune(now)
            self._store.async_delay_save(self._data, 1)
        for update in list(self._listeners):
            update()

    def _base(self) -> dict[str, Any]:
        return {"config_entry_id": self.entry.entry_id, "name": self.name, "person": self.person}

    def _mark_current_as_fired(self, now: datetime) -> None:
        """On startup, don't replay events that already happened before a restart."""
        snap = self.snapshot
        today = snap["today"]
        if snap["status"] in ("due", "overdue") and today not in self._fired["due"]:
            self._fired["due"].append(snap["overdue_day"] or today)
        for day in snap["missing"]:
            if day not in self._fired["missed"]:
                self._fired["missed"].append(day)
        for notice in snap["notices"]:
            if notice["id"] not in self._fired["notices"]:
                self._fired["notices"].append(notice["id"])
        self._trim()

    def _fire_time_events(self, now: datetime) -> None:
        snap = self.snapshot
        bus = self.hass.bus
        if snap["status"] == "due" and snap["today"] not in self._fired["due"]:
            self._fired["due"].append(snap["today"])
            bus.async_fire(
                EVENT_DUE, {**self._base(), "day": snap["today"], "pill": snap["pill_number"]}
            )
        for day in snap["missing"]:
            if day not in self._fired["missed"]:
                self._fired["missed"].append(day)
                pill = next((d["pill"] for d in snap["days"] if d["date"] == day), None)
                bus.async_fire(EVENT_MISSED, {**self._base(), "day": day, "pill": pill})
        active = {n["id"]: n for n in snap["notices"]}
        for nid, notice in active.items():
            if nid not in self._fired["notices"]:
                self._fired["notices"].append(nid)
                bus.async_fire(EVENT_NOTICE_STARTED, {**self._base(), **notice})
        for nid in list(self._fired["notices"]):
            if nid not in active:
                self._fired["notices"].remove(nid)
                bus.async_fire(EVENT_NOTICE_ENDED, {**self._base(), "id": nid})
        self._trim()

    def _trim(self) -> None:
        for key in ("due", "missed"):
            self._fired[key] = self._fired[key][-60:]

    # ------------------------------------------------------------ actions

    def _taken_event(self, entry: Entry, source: str) -> None:
        assert self.engine
        e = self.engine
        data: dict[str, Any] = {
            **self._base(),
            "day": entry.day.isoformat(),
            "pill": e.pill_number(entry.day),
            "time": e.local(entry.time).isoformat() if entry.time else None,
            "punctuality": e.punctuality(entry.day, entry.time),
            "source": source,
            "late_entry": entry.late_entry,
        }
        if entry.time is not None:
            data["deviation_min"] = round(e.deviation(entry.day, entry.time).total_seconds() / 60)
            data["in_window"] = e.in_window(entry.day, entry.time)
        self.hass.bus.async_fire(EVENT_TAKEN, data)

    def _changed(self, day: date, action: str) -> None:
        self.hass.bus.async_fire(
            EVENT_ENTRY_CHANGED, {**self._base(), "day": day.isoformat(), "action": action}
        )

    async def async_mark_taken(
        self,
        *,
        day: date | None = None,
        tod: time | None = None,
        time_unknown: bool = False,
        source: str = "manual",
    ) -> dict[str, Any]:
        assert self.engine
        now = dt_util.now()
        t: datetime | None = None
        if tod is not None:
            if day:
                t = self.engine.resolve_time(day, tod)
            else:
                # Without a date: the latest occurrence (23:50 entered at 00:10 = yesterday).
                t = datetime.combine(now.date(), tod, now.tzinfo)
                if t > now + timedelta(minutes=1):
                    t -= timedelta(days=1)
        try:
            entry = self.engine.mark_taken(
                now, t, day=day, time_unknown=time_unknown, source=source
            )
        except AssignmentNeeded as exc:
            self.hass.bus.async_fire(
                EVENT_NEEDS_ASSIGNMENT,
                {
                    **self._base(),
                    **exc.pending.to_dict(),
                    "choices": [self._choice(d, exc.pending.time) for d in exc.pending.options],
                },
            )
            await self.async_refresh()
            return {"pending": True, "options": [d.isoformat() for d in exc.pending.options]}
        self._taken_event(entry, source)
        self._changed(entry.day, "taken")
        await self.async_refresh()
        return {"pending": False, "day": entry.day.isoformat()}

    def _choice(self, day: date, t: datetime) -> dict[str, Any]:
        """Data for a push button: day, pill number, deviation."""
        assert self.engine
        e = self.engine
        return {
            "day": day.isoformat(),
            "pill": e.pill_number(day),
            "deviation_min": round(e.deviation(day, t).total_seconds() / 60),
            "in_window": e.in_window(day, t),
            "replaces": day in e.j.entries,
        }

    async def async_assign(self, day: date | None) -> None:
        assert self.engine
        entry = self.engine.assign_pending(dt_util.now(), day)
        if entry is not None:
            self._taken_event(entry, entry.source)
            self._changed(entry.day, "taken")
        await self.async_refresh()

    async def async_remove_entry(self, day: date) -> None:
        assert self.engine
        self.engine.remove_entry(day)
        self._fired["missed"] = [d for d in self._fired["missed"] if d != day.isoformat()]
        self._changed(day, "removed")
        await self.async_refresh()

    async def async_start_blister(self, day: date) -> None:
        assert self.engine
        self.engine.start_blister(day)
        await self.async_refresh()

    async def async_set_dose_time(self, tod: time) -> None:
        assert self.engine
        self.engine.set_dose_time(tod)
        await self.async_refresh()

    async def async_report_event(self, key: str, t: datetime | None) -> None:
        assert self.engine
        self.engine.report_event(dt_util.now(), key, t)
        await self.async_refresh()

    async def async_remove_event(self, event_id: str) -> None:
        assert self.engine
        self.engine.remove_event(event_id)
        await self.async_refresh()

    async def async_mark_replacement(self, t: datetime | None) -> None:
        assert self.engine
        entry = self.engine.mark_replacement(dt_util.now(), t)
        self._changed(entry.day, "replacement")
        await self.async_refresh()
