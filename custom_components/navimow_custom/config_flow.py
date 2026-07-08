"""Config flow for the Navimow (custom) integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import config_entry_oauth2_flow

from .auth import NavimowOAuth2Implementation
from .const import DOMAIN, REST_POLL_INTERVAL

_LOGGER = logging.getLogger(__name__)


class NavimowOAuth2FlowHandler(
    config_entry_oauth2_flow.AbstractOAuth2FlowHandler, domain=DOMAIN
):
    """Handle a Navimow (custom) OAuth2 config flow."""

    DOMAIN = DOMAIN
    VERSION = 1

    @property
    def logger(self) -> logging.Logger:
        return _LOGGER

    @property
    def oauth2_implementation(self) -> NavimowOAuth2Implementation:
        implementation = NavimowOAuth2Implementation(self.hass)
        config_entry_oauth2_flow.async_register_implementation(self.hass, DOMAIN, implementation)
        return implementation

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        _ = self.oauth2_implementation
        return await super().async_step_user()

    async def async_step_oauth2_authorize(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        _ = self.oauth2_implementation
        return await super().async_step_oauth2_authorize(user_input)

    async def async_step_reauth(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is None:
            return self.async_show_form(step_id="reauth_confirm", data_schema=None)
        return await super().async_step_user()

    async def async_oauth_create_entry(self, data: dict[str, Any]) -> FlowResult:
        if self.source == config_entries.SOURCE_REAUTH:
            existing_entry = self.entry
            self.hass.config_entries.async_update_entry(
                existing_entry, data={**existing_entry.data, **data}
            )
            await self.hass.config_entries.async_reload(existing_entry.entry_id)
            return self.async_abort(reason="reauth_successful")

        return self.async_create_entry(
            title="Navimow",
            data={"auth_implementation": DOMAIN, **data},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> config_entries.OptionsFlow:
        return NavimowOptionsFlowHandler(config_entry)


class NavimowOptionsFlowHandler(config_entries.OptionsFlow):
    """Options: derzeit nur das Poll-Intervall fuer den REST-Watchdog."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = self._config_entry.options.get(
            "poll_interval_seconds", int(REST_POLL_INTERVAL.total_seconds())
        )
        schema = vol.Schema(
            {vol.Required("poll_interval_seconds", default=current): vol.All(vol.Coerce(int), vol.Range(min=30))}
        )
        return self.async_show_form(step_id="init", data_schema=schema)
