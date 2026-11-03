"""Config and options flow.

Setup: person, intake time, blister start and the intake window (all required), then the
rules for a missed pill from the package leaflet (required), either per blister week or per
range of pill numbers (multiphasic pills like Quelecia/Qlaira), then any number of events
like vomiting or diarrhoea. Nothing medical is pre-filled.

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
    CONF_FROM_PILL,
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
    CONF_PLACEBO,
    CONF_REMOVE,
    CONF_RULE_MODE,
    CONF_TO_PILL,
    CONF_WEEK_DAYS,
    CONF_WEEK_TEXT,
    CONF_WINDOW_AFTER,
    CONF_WINDOW_BEFORE,
    DEFAULT_CYCLE_OFF,
    DEFAULT_CYCLE_ON,
    DEFAULT_ON_TIME,
    DEFAULT_PLACEBO,
    DOMAIN,
    OUTCOME_AS_MISSED,
    OUTCOME_CYCLE_END,
    OUTCOME_OWN,
    RULE_MODE_PILLS,
    RULE_MODE_WEEKS,
    WEEKS,
)

GENERAL_KEYS = (
    CONF_PERSON,
    CONF_CYCLE_ON,
    CONF_CYCLE_OFF,
    CONF_PLACEBO,
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
        _req(CONF_PLACEBO, d, DEFAULT_PLACEBO): _number(0, 30, 1),
        _req(CONF_WINDOW_BEFORE, d): _number(0, 12, 0.5, "h"),
        _req(CONF_WINDOW_AFTER, d): _number(0, 23.5, 0.5, "h"),
        _req(CONF_ON_TIME, d, DEFAULT_ON_TIME): _number(0, 720, 5, "min"),
    }


def _general_errors(user_input: dict[str, Any]) -> dict[str, str]:
    before, after = float(user_input[CONF_WINDOW_BEFORE]), float(user_input[CONF_WINDOW_AFTER])
    if before + after >= 24:
        return {"base": "window_too_long"}
    if int(user_input.get(CONF_PLACEBO) or 0) >= int(user_input[CONF_CYCLE_ON]):
        return {CONF_PLACEBO: "placebo_too_many"}
    return {}


def _general(user_input: dict[str, Any]) -> dict[str, Any]:
    return {
        CONF_PERSON: user_input.get(CONF_PERSON) or None,
        CONF_CYCLE_ON: int(user_input[CONF_CYCLE_ON]),
        CONF_CYCLE_OFF: int(user_input[CONF_CYCLE_OFF]),
        CONF_PLACEBO: int(user_input.get(CONF_PLACEBO) or 0),
        CONF_WINDOW_BEFORE: float(user_input[CONF_WINDOW_BEFORE]),
        CONF_WINDOW_AFTER: float(user_input[CONF_WINDOW_AFTER]),
        CONF_ON_TIME: float(user_input[CONF_ON_TIME]),
    }


def _active_pills(opt: dict[str, Any]) -> int:
    return int(opt[CONF_CYCLE_ON]) - int(opt.get(CONF_PLACEBO) or 0)


def _missed_fields(d: dict[str, Any]) -> dict[vol.Marker, Any]:
    return {
        _req(CONF_MISSED_AFTER, d): _number(0.5, 48, 0.5, "h"),
        _req(CONF_RULE_MODE, d, RULE_MODE_WEEKS): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=[RULE_MODE_WEEKS, RULE_MODE_PILLS],
                translation_key="rule_mode",
                mode=selector.SelectSelectorMode.LIST,
            )
        ),
        _opt(CONF_MULTI_DAYS, d): _number(0, 60, 1, "d"),
        _opt(CONF_MULTI_TEXT, d): TEXT,
    }


def _missed(user_input: dict[str, Any]) -> dict[str, Any]:
    multi = None
    if user_input.get(CONF_MULTI_DAYS) not in (None, ""):
        multi = {
            "backup_days": float(user_input[CONF_MULTI_DAYS]),
            "text": str(user_input.get(CONF_MULTI_TEXT) or "").strip(),
        }
    return {
        CONF_MISSED_AFTER: float(user_input[CONF_MISSED_AFTER]),
        CONF_RULE_MODE: user_input.get(CONF_RULE_MODE, RULE_MODE_WEEKS),
        CONF_MULTI_MISSED: multi,
    }


def _missed_defaults(opt: dict[str, Any]) -> dict[str, Any]:
    d: dict[str, Any] = {
        CONF_MISSED_AFTER: opt.get(CONF_MISSED_AFTER),
        CONF_RULE_MODE: opt.get(CONF_RULE_MODE),
    }
    if multi := opt.get(CONF_MULTI_MISSED):
        d[CONF_MULTI_DAYS], d[CONF_MULTI_TEXT] = multi["backup_days"], multi["text"]
    return d


def _week_fields(d: dict[str, Any]) -> dict[vol.Marker, Any]:
    fields: dict[vol.Marker, Any] = {}
    for week in range(1, WEEKS + 1):
        fields[_req(CONF_WEEK_DAYS.format(week), d)] = _number(0, 60, 1, "d")
        fields[_req(CONF_WEEK_TEXT.format(week), d)] = TEXT
    return fields


def _weeks(user_input: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "backup_days": float(user_input[CONF_WEEK_DAYS.format(w)]),
            "text": str(user_input[CONF_WEEK_TEXT.format(w)]).strip(),
        }
        for w in range(1, WEEKS + 1)
    ]


def _week_defaults(opt: dict[str, Any]) -> dict[str, Any]:
    d: dict[str, Any] = {}
    if opt.get(CONF_RULE_MODE, RULE_MODE_WEEKS) != RULE_MODE_WEEKS:
        return d
    for w, rule in enumerate(opt.get(CONF_MISSED_RULES) or [], start=1):
        d[CONF_WEEK_DAYS.format(w)] = rule["backup_days"]
        d[CONF_WEEK_TEXT.format(w)] = rule["text"]
    return d


def _phase_fields(d: dict[str, Any], active: int) -> dict[vol.Marker, Any]:
    return {
        _req(CONF_FROM_PILL, d): _number(1, active, 1),
        _req(CONF_TO_PILL, d): _number(1, active, 1),
        _req(CONF_ILL_DAYS, d): _number(0, 60, 1, "d"),
        _req(CONF_ILL_TEXT, d): TEXT,
    }


def _uncovered(phases: list[dict[str, Any]], active: int) -> list[int]:
    covered = {n for r in phases for n in range(r["from_pill"], r["to_pill"] + 1)}
    return [n for n in range(1, active + 1) if n not in covered]


def _ranges(pills: list[int]) -> str:
    """[1, 2, 3, 7] -> '1–3, 7'."""
    out: list[str] = []
    for n in pills:
        if out and out[-1].split("–")[-1] == str(n - 1):
            out[-1] = f"{out[-1].split('–')[0]}–{n}"
        else:
            out.append(str(n))
    return ", ".join(out)


def _phase(
    user_input: dict[str, Any], phases: list[dict[str, Any]], active: int
) -> tuple[dict[str, Any] | None, dict[str, str]]:
    first, last = int(user_input[CONF_FROM_PILL]), int(user_input[CONF_TO_PILL])
    if first > last:
        return None, {CONF_TO_PILL: "phase_order"}
    if first < 1 or last > active:
        return None, {CONF_TO_PILL: "phase_range"}
    if set(range(first, last + 1)) - set(_uncovered(phases, active)):
        return None, {CONF_FROM_PILL: "phase_overlap"}
    return {
        "from_pill": first,
        "to_pill": last,
        "backup_days": float(user_input[CONF_ILL_DAYS]),
        "text": str(user_input[CONF_ILL_TEXT]).strip(),
    }, {}


def _rules_fit(opt: dict[str, Any]) -> bool:
    """Per-pill rules still cover exactly the active pills (after a cycle change)."""
    if opt.get(CONF_RULE_MODE) != RULE_MODE_PILLS:
        return True
    rules = list(opt.get(CONF_MISSED_RULES) or [])
    active = _active_pills(opt)
    return not _uncovered(rules, active) and all(r["to_pill"] <= active for r in rules)


class _MissedRulesSteps:
    """Missed-pill steps shared by the config and the options flow.

    ``self._work`` holds the options being built; ``_rules_done`` continues the flow.
    """

    _work: dict[str, Any]
    _phases: list[dict[str, Any]]
    _defaults: dict[str, Any]

    async def _rules_done(self) -> ConfigFlowResult:
        raise NotImplementedError

    async def async_step_missed(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._work.update(_missed(user_input))
            if self._work[CONF_RULE_MODE] == RULE_MODE_PILLS:
                self._phases = []
                return await self.async_step_phase()
            return await self.async_step_weeks()
        return self.async_show_form(  # type: ignore[attr-defined,no-any-return]
            step_id="missed",
            data_schema=vol.Schema(_missed_fields(_missed_defaults(self._defaults))),
        )

    async def async_step_weeks(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._work[CONF_MISSED_RULES] = _weeks(user_input)
            return await self._rules_done()
        return self.async_show_form(  # type: ignore[attr-defined,no-any-return]
            step_id="weeks", data_schema=vol.Schema(_week_fields(_week_defaults(self._defaults)))
        )

    async def async_step_phase(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        active = _active_pills(self._work)
        errors: dict[str, str] = {}
        if user_input is not None:
            rule, errors = _phase(user_input, self._phases, active)
            if rule:
                self._phases.append(rule)
                if not _uncovered(self._phases, active):
                    self._work[CONF_MISSED_RULES] = sorted(
                        self._phases, key=lambda r: r["from_pill"]
                    )
                    return await self._rules_done()
        missing = _uncovered(self._phases, active)
        # Pre-fill the next range from the stored rules (options flow) or the next gap.
        old = []
        if self._defaults.get(CONF_RULE_MODE) == RULE_MODE_PILLS:
            old = list(self._defaults.get(CONF_MISSED_RULES) or [])
        nxt = next((r for r in old if r["from_pill"] in missing), None)
        d: dict[str, Any] = (
            {
                CONF_FROM_PILL: nxt["from_pill"],
                CONF_TO_PILL: min(nxt["to_pill"], active),
                CONF_ILL_DAYS: nxt["backup_days"],
                CONF_ILL_TEXT: nxt["text"],
            }
            if nxt
            else {CONF_FROM_PILL: missing[0] if missing else 1}
        )
        if user_input is not None and errors:
            d = user_input
        placebo = int(self._work.get(CONF_PLACEBO) or 0)
        return self.async_show_form(  # type: ignore[attr-defined,no-any-return]
            step_id="phase",
            data_schema=vol.Schema(_phase_fields(d, active)),
            errors=errors,
            description_placeholders={
                "active": str(active),
                "placebo": f"{active + 1}–{active + placebo}"
                if placebo > 1
                else str(active + 1)
                if placebo
                else "–",
                "missing": _ranges(missing),
            },
        )


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


class PillBlisterConfigFlow(_MissedRulesSteps, ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._work: dict[str, Any] = {}
        self._phases: list[dict[str, Any]] = []
        self._defaults: dict[str, Any] = {}  # nothing medical is pre-filled
        self._illnesses: list[dict[str, Any]] = []

    async def _rules_done(self) -> ConfigFlowResult:
        return await self.async_step_illness()

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
                self._work = _general(user_input)
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
                    options={**self._work, CONF_ILLNESSES: self._illnesses},
                )
        return self.async_show_form(
            step_id="illness", data_schema=_illness_schema(False, True), errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> PillBlisterOptionsFlow:
        return PillBlisterOptionsFlow()


class PillBlisterOptionsFlow(_MissedRulesSteps, OptionsFlow):
    def __init__(self) -> None:
        self._work: dict[str, Any] = {}
        self._phases: list[dict[str, Any]] = []
        self._defaults: dict[str, Any] = {}

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        self._defaults = dict(self.config_entry.options)
        self._work = dict(self.config_entry.options)
        menu = ["general", "missed", "add_illness"]
        if self.config_entry.options.get(CONF_ILLNESSES):
            menu.append("remove_illness")
        return self.async_show_menu(step_id="init", menu_options=menu)

    def _save(self, **changes: Any) -> ConfigFlowResult:
        return self.async_create_entry(data={**self.config_entry.options, **changes})

    async def _rules_done(self) -> ConfigFlowResult:
        return self._save(**self._work)

    async def async_step_general(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _general_errors(user_input)
            if not errors:
                self._work.update(_general(user_input))
                if not _rules_fit(self._work):
                    # Pill ranges no longer match the number of active pills: redo them.
                    return await self.async_step_missed()
                return self._save(**self._work)
        d = user_input or dict(self.config_entry.options)
        return self.async_show_form(
            step_id="general", data_schema=vol.Schema(_general_fields(d)), errors=errors
        )

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
