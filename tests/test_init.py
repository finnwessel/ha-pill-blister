"""Home Assistant tests: config flow, setup, entities and services."""

from __future__ import annotations

from datetime import timedelta

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_fire_time_changed,
)

from custom_components.pill_blister.const import (
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
    CONF_PLACEBO,
    CONF_RULE_MODE,
    CONF_WINDOW_AFTER,
    CONF_WINDOW_BEFORE,
    DOMAIN,
    EVENT_NEEDS_ASSIGNMENT,
    EVENT_NOTICE_STARTED,
    EVENT_TAKEN,
)

OPTIONS = {
    CONF_CYCLE_ON: 21,
    CONF_CYCLE_OFF: 7,
    CONF_WINDOW_BEFORE: 2,
    CONF_WINDOW_AFTER: 12,
    CONF_ON_TIME: 60,
    CONF_MISSED_AFTER: 12,
    CONF_MISSED_RULES: [
        {"backup_days": 7, "text": "W1"},
        {"backup_days": 7, "text": "W2"},
        {"backup_days": 7, "text": "W3"},
    ],
    CONF_MULTI_MISSED: None,
    CONF_ILLNESSES: [
        {
            "key": "erbrechen",
            "name": "Erbrechen",
            "within_hours": 4,
            "replacement_hours": 12,
            "as_missed": True,
            "backup_days": 0,
            "text": "",
        }
    ],
}

STATUS = "sensor.test_pill_status"


async def _setup(hass: HomeAssistant, freezer: FrozenDateTimeFactory, when: str) -> MockConfigEntry:
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to(when)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test",
        unique_id="test",
        data={CONF_NAME: "Test", CONF_DOSE_TIME: "20:00", CONF_BLISTER_START: "2026-01-06"},
        options=OPTIONS,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_flow(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    user = {
        CONF_NAME: "Test",
        CONF_DOSE_TIME: "20:00:00",
        CONF_BLISTER_START: "2026-01-06",
        CONF_CYCLE_ON: 21,
        CONF_CYCLE_OFF: 7,
        CONF_WINDOW_BEFORE: 12,
        CONF_WINDOW_AFTER: 12,
        CONF_ON_TIME: 60,
    }
    result = await hass.config_entries.flow.async_configure(result["flow_id"], user)
    assert result["errors"] == {"base": "window_too_long"}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**user, CONF_WINDOW_BEFORE: 2}
    )
    assert result["step_id"] == "missed"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_MISSED_AFTER: 12, CONF_RULE_MODE: "weeks"}
    )
    assert result["step_id"] == "weeks"
    weeks = {}
    for w in (1, 2, 3):
        weeks[f"week{w}_days"] = 7
        weeks[f"week{w}_text"] = f"Woche {w}"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], weeks)
    assert result["step_id"] == "illness"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "illness_name": "Erbrechen",
            "within_hours": 4,
            "replacement_hours": 12,
            "outcome": "as_missed",
            "add_another": False,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_DOSE_TIME] == "20:00"
    assert result["options"][CONF_MISSED_RULES][1] == {"backup_days": 7.0, "text": "Woche 2"}
    assert result["options"][CONF_ILLNESSES][0]["key"] == "erbrechen"
    await hass.async_block_till_done()


async def test_flow_per_tablet_number(hass: HomeAssistant) -> None:
    """Quelecia-like: 28 tablets, no break, 2 placebo, rules per tablet range."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    user = {
        CONF_NAME: "Q",
        CONF_DOSE_TIME: "20:00:00",
        CONF_BLISTER_START: "2026-01-06",
        CONF_CYCLE_ON: 28,
        CONF_CYCLE_OFF: 0,
        CONF_PLACEBO: 28,
        CONF_WINDOW_BEFORE: 2,
        CONF_WINDOW_AFTER: 12,
        CONF_ON_TIME: 60,
    }
    result = await hass.config_entries.flow.async_configure(result["flow_id"], user)
    assert result["errors"] == {CONF_PLACEBO: "placebo_too_many"}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**user, CONF_PLACEBO: 2}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_MISSED_AFTER: 12, CONF_RULE_MODE: "pills"}
    )
    assert result["step_id"] == "phase"
    assert result["description_placeholders"]["missing"] == "1–26"
    phase = {"backup_days": 9, "text": "nachholen"}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**phase, "from_pill": 1, "to_pill": 17}
    )
    assert result["step_id"] == "phase"
    assert result["description_placeholders"]["missing"] == "18–26"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**phase, "from_pill": 10, "to_pill": 24}
    )
    assert result["errors"] == {"from_pill": "phase_overlap"}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**phase, "from_pill": 18, "to_pill": 24}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"from_pill": 25, "to_pill": 26, "backup_days": 0, "text": "-"}
    )
    assert result["step_id"] == "illness"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    opts = result["options"]
    assert opts[CONF_PLACEBO] == 2 and opts[CONF_RULE_MODE] == "pills"
    assert [(r["from_pill"], r["to_pill"]) for r in opts[CONF_MISSED_RULES]] == [
        (1, 17),
        (18, 24),
        (25, 26),
    ]
    await hass.async_block_till_done()
    state = hass.states.get("sensor.q_pill_status")
    assert state is not None and len(state.attributes["days"]) == 28

    # Changing the number of placebo tablets requires redoing the ranges.
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "general"}
    )
    setup_only = (CONF_NAME, CONF_DOSE_TIME, CONF_BLISTER_START)
    general = {k: v for k, v in user.items() if k not in setup_only}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**general, CONF_PLACEBO: 4}
    )
    assert result["step_id"] == "missed"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_MISSED_AFTER: 12, CONF_RULE_MODE: "pills"}
    )
    assert result["step_id"] == "phase"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**phase, "from_pill": 1, "to_pill": 17}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**phase, "from_pill": 18, "to_pill": 24}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_PLACEBO] == 4
    assert len(entry.options[CONF_MISSED_RULES]) == 2


async def test_status_and_mark_taken(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    entry = await _setup(hass, freezer, "2026-01-15 10:00:00+01:00")
    state = hass.states.get(STATUS)
    assert state.state == "later"
    assert state.attributes["pill_number"] == 10
    assert hass.states.get("date.test_pill_blister_start").state == "2026-01-06"
    assert hass.states.get("time.test_pill_dose_time").state == "20:00:00"

    taken = async_capture_events(hass, EVENT_TAKEN)
    freezer.move_to("2026-01-15 20:10:00+01:00")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(STATUS).state == "due"
    assert hass.states.get("binary_sensor.test_pill_due").state == "on"

    await hass.services.async_call(
        "button", "press", {"entity_id": "button.test_pill_taken"}, blocking=True
    )
    await hass.async_block_till_done()
    assert hass.states.get(STATUS).state == "done"
    assert taken[-1].data["punctuality"] == "on_time"
    assert taken[-1].data["source"] == "button"

    response = await hass.services.async_call(
        DOMAIN,
        "mark_taken",
        {"config_entry_id": entry.entry_id, "date": "2026-01-14", "time_unknown": True},
        blocking=True,
        return_response=True,
    )
    assert response == {"pending": False, "day": "2026-01-14"}


async def test_needs_assignment(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    entry = await _setup(hass, freezer, "2026-01-15 20:05:00+01:00")
    await hass.services.async_call(
        DOMAIN, "mark_taken", {"config_entry_id": entry.entry_id}, blocking=True
    )
    asked = async_capture_events(hass, EVENT_NEEDS_ASSIGNMENT)
    response = await hass.services.async_call(
        DOMAIN,
        "mark_taken",
        {"config_entry_id": entry.entry_id},
        blocking=True,
        return_response=True,
    )
    assert response["pending"] is True
    assert asked[0].data["options"] == ["2026-01-15"]
    assert hass.states.get("sensor.test_pill_pending_intake").state != "unknown"
    await hass.services.async_call(
        DOMAIN, "assign_intake", {"config_entry_id": entry.entry_id, "discard": True}, blocking=True
    )
    assert hass.states.get("sensor.test_pill_pending_intake").state == "unknown"


async def test_missed_notice(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    await _setup(hass, freezer, "2026-01-15 10:00:00+01:00")
    notices = async_capture_events(hass, EVENT_NOTICE_STARTED)
    freezer.move_to("2026-01-16 08:05:00+01:00")  # pill 10 (15.1.) not taken, deadline 08:00
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=61))
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.test_pill_notice").state == "on"
    assert notices and notices[0].data["pill"] == 10
    assert notices[0].data["text"] == "W2"


async def test_errors_are_validation_errors(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    entry = await _setup(hass, freezer, "2026-01-15 10:00:00+01:00")
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "remove_entry",
            {"config_entry_id": entry.entry_id, "date": "2026-01-13"},
            blocking=True,
        )
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "report_event",
            {"config_entry_id": entry.entry_id, "type": "unknown"},
            blocking=True,
        )


async def test_unload_persists(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    entry = await _setup(hass, freezer, "2026-01-15 20:10:00+01:00")
    await hass.services.async_call(
        DOMAIN, "mark_taken", {"config_entry_id": entry.entry_id}, blocking=True
    )
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(STATUS).state == "done"
