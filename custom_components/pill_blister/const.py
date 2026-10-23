"""Constants."""

from __future__ import annotations

DOMAIN = "pill_blister"
STORAGE_VERSION = 1
TICK_SECONDS = 60

CONF_NAME = "name"
CONF_PERSON = "person"
CONF_DOSE_TIME = "dose_time"
CONF_BLISTER_START = "blister_start"
CONF_CYCLE_ON = "cycle_on"
CONF_CYCLE_OFF = "cycle_off"
CONF_WINDOW_BEFORE = "window_before"  # hours
CONF_WINDOW_AFTER = "window_after"  # hours
CONF_ON_TIME = "on_time"  # minutes
CONF_MISSED_AFTER = "missed_after"  # hours
CONF_MISSED_RULES = "missed_rules"  # list of {backup_days, text}, week 1..3
CONF_MULTI_MISSED = "multi_missed"  # {backup_days, text} or None
CONF_ILLNESSES = "illnesses"  # list of illness rules

CONF_WEEK_DAYS = "week{}_days"
CONF_WEEK_TEXT = "week{}_text"
CONF_MULTI_DAYS = "multi_days"
CONF_MULTI_TEXT = "multi_text"
CONF_ILL_NAME = "illness_name"
CONF_ILL_WITHIN = "within_hours"
CONF_ILL_REPLACEMENT = "replacement_hours"
CONF_ILL_OUTCOME = "outcome"
CONF_ILL_DAYS = "backup_days"
CONF_ILL_TEXT = "text"
CONF_ADD_ANOTHER = "add_another"
CONF_REMOVE = "remove"

OUTCOME_AS_MISSED = "as_missed"
OUTCOME_OWN = "own_rule"
OUTCOME_CYCLE_END = "until_cycle_end"

WEEKS = 3

DEFAULT_CYCLE_ON = 21
DEFAULT_CYCLE_OFF = 7
DEFAULT_ON_TIME = 60

ATTR_CONFIG_ENTRY_ID = "config_entry_id"
ATTR_DATE = "date"
ATTR_TIME = "time"
ATTR_DATETIME = "datetime"
ATTR_TIME_UNKNOWN = "time_unknown"
ATTR_SOURCE = "source"
ATTR_DISCARD = "discard"
ATTR_TYPE = "type"
ATTR_EVENT_ID = "event_id"

SERVICE_MARK_TAKEN = "mark_taken"
SERVICE_REMOVE_ENTRY = "remove_entry"
SERVICE_ASSIGN_INTAKE = "assign_intake"
SERVICE_START_BLISTER = "start_blister"
SERVICE_REPORT_EVENT = "report_event"
SERVICE_REMOVE_EVENT = "remove_event"
SERVICE_MARK_REPLACEMENT = "mark_replacement"

EVENT_DUE = f"{DOMAIN}_due"
EVENT_MISSED = f"{DOMAIN}_missed"
EVENT_TAKEN = f"{DOMAIN}_taken"
EVENT_NEEDS_ASSIGNMENT = f"{DOMAIN}_needs_assignment"
EVENT_NOTICE_STARTED = f"{DOMAIN}_notice_started"
EVENT_NOTICE_ENDED = f"{DOMAIN}_notice_ended"
EVENT_ENTRY_CHANGED = f"{DOMAIN}_entry_changed"

STATUSES = ["later", "due", "overdue", "done", "pause", "last_pause_day"]

CARD_URL = f"/{DOMAIN}/pill-blister-card.js"
