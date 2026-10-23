"""Engine tests (no Home Assistant needed)."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from custom_components.pill_blister.engine import (
    AssignmentNeeded,
    EngineError,
    IllnessRule,
    Journal,
    MissedRule,
    Params,
    PillBlister,
)

TZ = ZoneInfo("Europe/Berlin")
START = date(2026, 1, 6)  # Tuesday


def at(d: date, hh: int, mm: int = 0) -> datetime:
    return datetime.combine(d, time(hh, mm)).replace(tzinfo=TZ)


def day(n: int) -> date:
    """Pill n (1-based) of the blister started on START."""
    return START + timedelta(days=n - 1)


def make(**kw) -> PillBlister:
    params = Params(
        tz=TZ,
        cycle_on=21,
        cycle_off=7,
        window_before=timedelta(hours=2),
        window_after=timedelta(hours=12),
        on_time=timedelta(minutes=60),
        missed_after=timedelta(hours=12),
        missed_rules=(
            MissedRule(7, "Woche 1: nachholen, 7 Tage zusätzlich verhüten"),
            MissedRule(7, "Woche 2: nachholen"),
            MissedRule(7, "Woche 3: Pause auslassen"),
        ),
        multi_missed=MissedRule(14, "Mehrere vergessen: Arzt fragen"),
        illnesses=(
            IllnessRule("vomit", "Erbrechen", within_hours=4, replacement_hours=12),
            IllnessRule(
                "diarrhoea",
                "Starker Durchfall",
                within_hours=4,
                as_missed=False,
                backup_days=3,
                text="3 Tage",
            ),
        ),
    )
    params = Params(**{**params.__dict__, **kw})
    journal = Journal(blister_start=START, dose_time=time(20, 0), tracking_since=START)
    return PillBlister(params, journal)


def fill(e: PillBlister, upto: int, hh: int = 20) -> None:
    for n in range(1, upto + 1):
        e.mark_taken(at(day(n), 23), at(day(n), hh), day=day(n))


# ------------------------------------------------------------------ cycle


def test_cycle_positions():
    e = make()
    assert e.pill_number(day(1)) == 1
    assert e.pill_number(day(10)) == 10
    assert e.pill_number(day(21)) == 21
    assert e.pill_number(day(22)) is None  # pause
    assert e.is_dose_day(day(29))  # next blister
    assert e.pill_number(day(29)) == 1
    assert e.blister_start_for(day(25)) == START
    assert e.blister_start_for(day(30)) == day(29)
    assert e.week_index(day(1)) == 0 and e.week_index(day(8)) == 1 and e.week_index(day(21)) == 2


def test_status_phases():
    e = make()
    fill(e, 9)
    assert e.status(at(day(10), 10)) == "later"
    assert e.status(at(day(10), 20, 30)) == "due"
    e.mark_taken(at(day(10), 20, 31))
    assert e.status(at(day(10), 21)) == "done"
    fill(e, 21)
    assert e.status(at(day(23), 12)) == "pause"
    assert e.status(at(day(28), 12)) == "last_pause_day"


# ------------------------------------------------------------------ assignment


def test_intake_in_window_assigns_automatically():
    e = make()
    entry = e.mark_taken(at(day(10), 19, 0))  # 1 h early, inside 2 h before
    assert entry.day == day(10)
    assert not entry.late_entry


def test_after_midnight_counts_for_yesterday_if_open():
    e = make()
    fill(e, 9)
    entry = e.mark_taken(at(day(11), 0, 30))  # yesterday (pill 10) still open
    assert entry.day == day(10)
    assert e.punctuality(day(10), entry.time) == "late"


def test_six_am_for_today_is_asked_not_guessed():
    e = make()
    fill(e, 10)
    try:
        e.mark_taken(at(day(11), 6, 30))  # only in yesterday's window, yesterday done
    except AssignmentNeeded as exc:
        assert exc.pending.options == [day(10), day(11)]
    else:
        raise AssertionError("expected AssignmentNeeded")
    entry = e.assign_pending(at(day(11), 6, 31), day(11))
    assert entry is not None and entry.day == day(11)
    assert e.punctuality(day(11), entry.time) == "early"
    assert e.j.pending is None


def test_outside_every_window_today_only():
    e = make(window_after=timedelta(hours=8))
    fill(e, 10)
    try:
        e.mark_taken(at(day(11), 6, 0))  # yesterday's window ended at 04:00
    except AssignmentNeeded as exc:
        assert exc.pending.options == [day(11)]
    else:
        raise AssertionError("expected AssignmentNeeded")


def test_outside_window_with_yesterday_open_offers_both():
    e = make()
    fill(e, 9)
    try:
        e.mark_taken(at(day(11), 9, 0))  # 13 h after yesterday's dose, window ends at 08:00
    except AssignmentNeeded as exc:
        assert exc.pending.options == [day(10), day(11)]
    else:
        raise AssertionError("expected AssignmentNeeded")
    assert e.assign_pending(at(day(11), 9, 1), None) is None  # discard
    assert e.j.pending is None


def test_already_done_in_window_asks():
    e = make()
    fill(e, 10)
    try:
        e.mark_taken(at(day(10), 21, 0))
    except AssignmentNeeded as exc:
        assert exc.pending.options == [day(10)]  # replace today's entry
    else:
        raise AssertionError("expected AssignmentNeeded")


def test_explicit_day_and_after_midnight_time():
    e = make()
    t = e.resolve_time(day(10), time(0, 30))
    assert t == at(day(11), 0, 30)
    t = e.resolve_time(day(10), time(19, 15))
    assert t == at(day(10), 19, 15)
    entry = e.mark_taken(at(day(12), 9), t, day=day(10))
    assert entry.late_entry  # recorded two days later


def test_time_unknown_and_errors():
    e = make()
    entry = e.mark_taken(at(day(5), 9), day=day(3), time_unknown=True)
    assert entry.time is None and entry.late_entry
    for call, key in (
        (lambda: e.mark_taken(at(day(5), 9), at(day(5), 12)), "time_in_future"),
        (lambda: e.mark_taken(at(day(24), 9), at(day(24), 9), day=day(24)), "not_a_dose_day"),
        (lambda: e.remove_entry(day(4)), "no_entry"),
        (lambda: e.assign_pending(at(day(5), 9), day(5)), "nothing_pending"),
    ):
        try:
            call()
        except EngineError as exc:
            assert exc.key == key, exc.key
        else:
            raise AssertionError(key)


def test_pause_intake_is_rejected():
    e = make()
    fill(e, 21)
    try:
        e.mark_taken(at(day(24), 20))
    except EngineError as exc:
        assert exc.key == "no_dose_day"
    else:
        raise AssertionError("expected EngineError")


# ------------------------------------------------------------------ notices


def test_no_notice_before_deadline_and_missed_after():
    e = make()
    fill(e, 9)
    assert e.notices(at(day(11), 7, 59)) == []  # pill 10 open, deadline 08:00
    notices = e.notices(at(day(11), 8, 1))
    assert len(notices) == 1
    n = notices[0]
    assert n.kind == "missed" and n.pill == 10
    assert n.start == at(day(11), 8) and n.end == at(day(10), 20) + timedelta(days=7)
    assert n.text.startswith("Woche 2")


def test_late_intake_beyond_deadline_counts_as_missed():
    e = make()
    fill(e, 9)
    e.mark_taken(at(day(11), 9), at(day(11), 9), day=day(10))  # 13 h late
    n = e.notices(at(day(11), 9, 5))[0]
    assert n.kind == "late"
    assert n.reason == "Pille 10 13 h zu spät"
    assert n.end == at(day(11), 9) + timedelta(days=7)


def test_late_within_deadline_has_no_notice():
    e = make()
    fill(e, 9)
    e.mark_taken(at(day(11), 2), at(day(11), 2))  # 6 h late, inside 12 h
    assert e.notices(at(day(11), 10)) == []


def test_multiple_missed_uses_multi_rule():
    e = make()
    fill(e, 3)
    e.mark_taken(at(day(5), 20), day=day(5))
    # pill 4 and 6 missed
    notices = e.notices(at(day(7), 9))
    assert [n.pill for n in notices] == [4, 6]
    assert notices[1].text.startswith("Mehrere") and notices[1].end == at(day(6), 20) + timedelta(
        days=14
    )


def test_untracked_days_before_setup_are_ignored():
    e = make()
    e.j.tracking_since = day(8)
    fill_from = range(8, 10)
    for n in fill_from:
        e.mark_taken(at(day(n), 21), day=day(n))
    assert e.notices(at(day(10), 10)) == []
    assert e.missing_days(at(day(10), 10)) == []
    states = {d["pill"]: d["state"] for d in e.days(at(day(10), 10))}
    assert states[1] == "untracked" and states[8] == "taken" and states[10] == "open"


def test_vomiting_replacement_window_then_resolved():
    e = make()
    fill(e, 10)
    e.report_event(at(day(10), 22), "vomit", at(day(10), 22))  # 2 h after intake
    n = e.notices(at(day(10), 22, 5))
    assert len(n) == 1 and n[0].kind == "replacement"
    assert n[0].end == at(day(11), 8)
    e.mark_replacement(at(day(10), 23), at(day(10), 23))
    assert e.notices(at(day(10), 23, 5)) == []


def test_vomiting_without_replacement_becomes_missed_rule():
    e = make()
    fill(e, 10)
    e.report_event(at(day(10), 22), "vomit", at(day(10), 22))
    n = e.notices(at(day(11), 8, 30))
    assert len(n) == 1 and n[0].kind == "illness"
    assert n[0].end == at(day(10), 22) + timedelta(days=7)
    assert n[0].text.startswith("Woche 2")


def test_event_outside_effect_window_is_ignored():
    e = make()
    fill(e, 10)
    e.report_event(at(day(11), 2), "diarrhoea", at(day(11), 2))  # 6 h after intake
    assert e.notices(at(day(11), 3)) == []


def test_illness_with_own_rule():
    e = make()
    fill(e, 10)
    e.report_event(at(day(10), 21), "diarrhoea", at(day(10), 21))
    n = e.notices(at(day(10), 21, 5))
    assert n[0].kind == "illness" and n[0].text == "3 Tage"
    assert n[0].end == at(day(10), 21) + timedelta(days=3)


def test_notice_expires():
    e = make()
    fill(e, 9)
    assert e.notices(at(day(11), 9))
    fill_rest = range(11, 21)
    for k in fill_rest:
        e.mark_taken(at(day(k), 21), day=day(k))
    assert e.notices(at(day(17), 20, 1)) == []  # 7 days after pill 10's dose time


# ------------------------------------------------------------------ snapshot


def test_snapshot_and_roundtrip():
    e = make()
    fill(e, 9)
    e.mark_taken(at(day(10), 20, 5))
    snap = e.snapshot(at(day(10), 21))
    assert snap["status"] == "done"
    assert snap["pill_number"] == 10
    assert snap["pause_start"] == "2026-01-27" and snap["next_blister"] == "2026-02-03"
    assert snap["punctuality"] == "on_time"
    assert len(snap["days"]) == 21 and snap["days"][10]["state"] == "future"
    data = e.j.to_dict()
    restored = Journal.from_dict(data)
    assert restored.to_dict() == data


def test_overdue_after_midnight():
    e = make()
    fill(e, 9)
    assert e.status(at(day(11), 0, 30)) == "overdue"
    assert e.is_due(at(day(11), 0, 30))
    assert e.snapshot(at(day(11), 0, 30))["overdue_day"] == day(10).isoformat()
    assert e.status(at(day(11), 8, 30)) == "later"
    assert e.missing_days(at(day(11), 8, 30)) == [day(10)]


def test_start_blister_moves_cycle():
    e = make()
    e.start_blister(date(2026, 1, 31))  # shortened pause
    assert e.pill_number(date(2026, 1, 31)) == 1
    assert e.status(at(date(2026, 1, 31), 10)) == "later"


def test_untracked_days_are_not_offered():
    e = make()
    e.j.tracking_since = day(10)
    e.mark_taken(at(day(10), 20, 5))
    try:
        e.mark_taken(at(day(10), 20, 10))
    except AssignmentNeeded as exc:
        assert exc.pending.options == [day(10)]
    else:
        raise AssertionError("expected AssignmentNeeded")


def test_illness_until_cycle_end():
    e = make(
        illnesses=(
            IllnessRule(
                "erbrechen",
                "Erbrechen",
                within_hours=4,
                as_missed=False,
                until_cycle_end=True,
                text="Rest des Zyklus",
            ),
        )
    )
    fill(e, 10)
    e.report_event(at(day(10), 22), "erbrechen", at(day(10), 22))
    n = e.notices(at(day(10), 22, 5))
    assert len(n) == 1 and n[0].kind == "illness"
    assert n[0].end == at(day(29), 20)  # pill 1 of the next blister
    for k in range(11, 22):
        e.mark_taken(at(day(k), 21), day=day(k))
    assert e.notices(at(day(28), 12))[0].kind == "illness"
    assert e.notices(at(day(29), 20, 1)) == []


def test_setup_day_does_not_flag_untracked_yesterday():
    e = make()
    e.j.tracking_since = day(11)
    assert e.status(at(day(11), 7)) == "later"
    assert e.open_overdue(at(day(11), 7)) is None
