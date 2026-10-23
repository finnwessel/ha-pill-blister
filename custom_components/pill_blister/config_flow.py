"""Config and options flow.

Setup: person, intake time, blister start and the intake window (all required), then the
rules for a missed pill per blister week from the package leaflet (required), then any
number of events like vomiting or diarrhoea. Nothing medical is pre-filled.

Options: general settings, missed-pill rules, add or remove an event.
Intake time and blister start are changed through their entities afterwards.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.util import slugify

from .const import (
    CONF_ADD_ANOTHER,
    CONF_BLISTER_START,
    CONF_CYCLE_OFF,
    CONF_CYCLE_ON,
    CONF_DOSE_TIME,
    CONF_ILL_DAYS,
    CONF_ILL_NAME,
    CONF_ILL_OUTCOME,
    CONF_ILL_REPLACEMENT,
    CONF_ILL_TEXT,
    CONF_ILL_WITHIN,
    CONF_ILLNESSES,
    CONF_MISSED_AFTER,
    CONF_MISSED_RULES,
    CONF_MULTI_DAYS,
    CONF_MULTI_MISSED,
    CONF_MULTI_TEXT,
    CONF_NAME,
    CONF_ON_TIME,
    CONF_PERSON,
    CONF_REMOVE,
    CONF_WEEK_DAYS,
    CONF_WEEK_TEXT,
    CONF_WINDOW_AFTER,
    CONF_WINDOW_BEFORE,
    DEFAULT_CYCLE_OFF,
    DEFAULT_CYCLE_ON,
    DEFAULT_ON_TIME,
    DOMAIN,
    OUTCOME_AS_MISSED,
    OUTCOME_CYCLE_END,
    OUTCOME_OWN,
    WEEKS,
)

GENERAL_KEYS = (
    CONF_PERSON,
    CONF_CYCLE_ON,
    CONF_CYCLE_OFF,
    CONF_WINDOW_BEFORE,
    CONF_WINDOW_AFTER,
    CONF_ON_TIME,
)


def _number(
    minimum: float, maximum: float, step: float, unit: str | None = None
) -> selector.NumberSelector:
    config = selector.NumberSelectorConfig(
        min=minimum, max=maximum, step=step, mode=selector.NumberSelectorMode.BOX
    )
    if unit is not None:
        config["unit_of_measurement"] = unit
    return selector.NumberSelector(config)


TEXT = selector.TextSelector(selector.TextSelectorConfig(multiline=True))


def _req(key: str, d: dict[str, Any], default: Any = None) -> vol.Required:
    value = d.get(key, default)
    return vol.Required(key, default=value) if value is not None else vol.Required(key)


def _opt(key: str, d: dict[str, Any]) -> vol.Optional:
    value = d.get(key)
    if value not in (None, ""):
        return vol.Optional(key, description={"suggested_value": value})
    return vol.Optional(key)


def _general_fields(d: dict[str, Any]) -> dict[vol.Marker, Any]:
    return {
        _opt(CONF_PERSON, d): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="person")
        ),
        _req(CONF_CYCLE_ON, d, DEFAULT_CYCLE_ON): _number(1, 90, 1, "d"),
        _req(CONF_CYCLE_OFF, d, DEFAULT_CYCLE_OFF): _number(0, 30, 1, "d"),
        _req(CONF_WINDOW_BEFORE, d): _number(0, 12, 0.5, "h"),
        _req(CONF_WINDOW_AFTER, d): _number(0, 23.5, 0.5, "h"),
        _req(CONF_ON_TIME, d, DEFAULT_ON_TIME): _number(0, 720, 5, "min"),
    }


def _general_errors(user_input: dict[str, Any]) -> dict[str, str]:
    before, after = float(user_input[CONF_WINDOW_BEFORE]), float(user_input[CONF_WINDOW_AFTER])
    if before + after >= 24:
        return {"base": "window_too_long"}
    return {}


def _general(user_input: dict[str, Any]) -> dict[str, Any]:
    return {
        CONF_PERSON: user_input.get(CONF_PERSON) or None,
        CONF_CYCLE_ON: int(user_input[CONF_CYCLE_ON]),
        CONF_CYCLE_OFF: int(user_input[CONF_CYCLE_OFF]),
        CONF_WINDOW_BEFORE: float(user_input[CONF_WINDOW_BEFORE]),
        CONF_WINDOW_AFTER: float(user_input[CONF_WINDOW_AFTER]),
        CONF_ON_TIME: float(user_input[CONF_ON_TIME]),
    }


def _missed_fields(d: dict[str, Any]) -> dict[vol.Marker, Any]:
    fields: dict[vol.Marker, Any] = {_req(CONF_MISSED_AFTER, d): _number(0.5, 48, 0.5, "h")}
    for week in range(1, WEEKS + 1):
        fields[_req(CONF_WEEK_DAYS.format(week), d)] = _number(0, 60, 1, "d")
        fields[_req(CONF_WEEK_TEXT.format(week), d)] = TEXT
    fields[_opt(CONF_MULTI_DAYS, d)] = _number(0, 60, 1, "d")
    fields[_opt(CONF_MULTI_TEXT, d)] = TEXT
    return fields


def _missed(user_input: dict[str, Any]) -> dict[str, Any]:
    rules = [
        {
            "backup_days": float(user_input[CONF_WEEK_DAYS.format(w)]),
            "text": str(user_input[CONF_WEEK_TEXT.format(w)]).strip(),
        }
        for w in range(1, WEEKS + 1)
    ]
    multi = None
    if user_input.get(CONF_MULTI_DAYS) not in (None, ""):
        multi = {
            "backup_days": float(user_input[CONF_MULTI_DAYS]),
            "text": str(user_input.get(CONF_MULTI_TEXT) or "").strip(),
        }
    return {
        CONF_MISSED_AFTER: float(user_input[CONF_MISSED_AFTER]),
        CONF_MISSED_RULES: rules,
        CONF_MULTI_MISSED: multi,
    }


def _missed_defaults(opt: dict[str, Any]) -> dict[str, Any]:
    d: dict[str, Any] = {CONF_MISSED_AFTER: opt.get(CONF_MISSED_AFTER)}
    for w, rule in enumerate(opt.get(CONF_MISSED_RULES) or [], start=1):
        d[CONF_WEEK_DAYS.format(w)] = rule["backup_days"]
        d[CONF_WEEK_TEXT.format(w)] = rule["text"]
    if multi := opt.get(CONF_MULTI_MISSED):
        d[CONF_MULTI_DAYS], d[CONF_MULTI_TEXT] = multi["backup_days"], multi["text"]
    return d


def _illness_schema(required_name: bool, add_another: bool) -> vol.Schema:
    name = vol.Required(CONF_ILL_NAME) if required_name else vol.Optional(CONF_ILL_NAME)
    fields: dict[vol.Marker, Any] = {
        name: selector.TextSelector(),
        vol.Optional(CONF_ILL_WITHIN): _number(0.5, 48, 0.5, "h"),
        vol.Optional(CONF_ILL_REPLACEMENT): _number(0, 48, 0.5, "h"),
        vol.Optional(CONF_ILL_OUTCOME, default=OUTCOME_AS_MISSED): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=[OUTCOME_AS_MISSED, OUTCOME_CYCLE_END, OUTCOME_OWN],
                translation_key="outcome",
                mode=selector.SelectSelectorMode.LIST,
            )
        ),
        vol.Optional(CONF_ILL_DAYS): _number(0, 60, 1, "d"),
        vol.Optional(CONF_ILL_TEXT): TEXT,
    }
    if add_another:
        fields[vol.Required(CONF_ADD_ANOTHER, default=False)] = selector.BooleanSelector()
    return vol.Schema(fields)


def _illness(
    user_input: dict[str, Any], existing: list[dict[str, Any]]
) -> tuple[dict[str, Any] | None, dict[str, str]]:
    name = str(user_input.get(CONF_ILL_NAME) or "").strip()
    if user_input.get(CONF_ILL_WITHIN) in (None, ""):
        return None, {CONF_ILL_WITHIN: "required"}
    own = user_input.get(CONF_ILL_OUTCOME) == OUTCOME_OWN
    if own and user_input.get(CONF_ILL_DAYS) in (None, ""):
        return None, {CONF_ILL_DAYS: "required"}
    key = slugify(name) or "event"
    taken = {r["key"] for r in existing}
    base, n = key, 2
    while key in taken:
        key, n = f"{base}_{n}", n + 1
    return {
        "key": key,
        "name": name,
        "within_hours": float(user_input[CONF_ILL_WITHIN]),
        "replacement_hours": float(user_input.get(CONF_ILL_REPLACEMENT) or 0),
        "as_missed": user_input.get(CONF_ILL_OUTCOME, OUTCOME_AS_MISSED) == OUTCOME_AS_MISSED,
        "until_cycle_end": user_input.get(CONF_ILL_OUTCOME) == OUTCOME_CYCLE_END,
        "backup_days": float(user_input.get(CONF_ILL_DAYS) or 0),
        "text": str(user_input.get(CONF_ILL_TEXT) or "").strip(),
    }, {}


class PillBlisterConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._options: dict[str, Any] = {}
        self._illnesses: list[dict[str, Any]] = []

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _general_errors(user_input)
            if not errors:
                name = str(user_input[CONF_NAME]).strip()
                await self.async_set_unique_id(slugify(name))
                self._abort_if_unique_id_configured()
                self._data = {
                    CONF_NAME: name,
                    CONF_DOSE_TIME: str(user_input[CONF_DOSE_TIME])[:5],
                    CONF_BLISTER_START: str(user_input[CONF_BLISTER_START]),
                }
                self._options = _general(user_input)
                return await self.async_step_missed()
        d = user_input or {}
        schema = vol.Schema(
            {
                _req(CONF_NAME, d): selector.TextSelector(),
                _req(CONF_DOSE_TIME, d): selector.TimeSelector(),
                _req(CONF_BLISTER_START, d): selector.DateSelector(),
                **_general_fields(d),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_missed(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._options.update(_missed(user_input))
            return await self.async_step_illness()
        return self.async_show_form(step_id="missed", data_schema=vol.Schema(_missed_fields({})))

    async def async_step_illness(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if str(user_input.get(CONF_ILL_NAME) or "").strip():
                rule, errors = _illness(user_input, self._illnesses)
                if rule:
                    self._illnesses.append(rule)
                    if user_input.get(CONF_ADD_ANOTHER):
                        return self.async_show_form(
                            step_id="illness", data_schema=_illness_schema(False, True)
                        )
            if not errors:
                return self.async_create_entry(
                    title=self._data[CONF_NAME],
                    data=self._data,
                    options={**self._options, CONF_ILLNESSES: self._illnesses},
                )
        return self.async_show_form(
            step_id="illness", data_schema=_illness_schema(False, True), errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> PillBlisterOptionsFlow:
        return PillBlisterOptionsFlow()


class PillBlisterOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        menu = ["general", "missed", "add_illness"]
        if self.config_entry.options.get(CONF_ILLNESSES):
            menu.append("remove_illness")
        return self.async_show_menu(step_id="init", menu_options=menu)

    def _save(self, **changes: Any) -> ConfigFlowResult:
        return self.async_create_entry(data={**self.config_entry.options, **changes})

    async def async_step_general(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _general_errors(user_input)
            if not errors:
                return self._save(**_general(user_input))
        d = user_input or dict(self.config_entry.options)
        return self.async_show_form(
            step_id="general", data_schema=vol.Schema(_general_fields(d)), errors=errors
        )

    async def async_step_missed(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self._save(**_missed(user_input))
        d = _missed_defaults(dict(self.config_entry.options))
        return self.async_show_form(step_id="missed", data_schema=vol.Schema(_missed_fields(d)))

    async def async_step_add_illness(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        existing = list(self.config_entry.options.get(CONF_ILLNESSES) or [])
        if user_input is not None:
            rule, errors = _illness(user_input, existing)
            if rule:
                return self._save(**{CONF_ILLNESSES: [*existing, rule]})
        return self.async_show_form(
            step_id="add_illness", data_schema=_illness_schema(True, False), errors=errors
        )

    async def async_step_remove_illness(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        rules = self.config_entry.options.get(CONF_ILLNESSES) or []
        if user_input is not None:
            remove = set(user_input.get(CONF_REMOVE) or [])
            return self._save(**{CONF_ILLNESSES: [r for r in rules if r["key"] not in remove]})
        options = [selector.SelectOptionDict(value=r["key"], label=r["name"]) for r in rules]
        schema = vol.Schema(
            {
                vol.Required(CONF_REMOVE, default=[]): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=options, multiple=True)
                )
            }
        )
        return self.async_show_form(step_id="remove_illness", data_schema=schema)
