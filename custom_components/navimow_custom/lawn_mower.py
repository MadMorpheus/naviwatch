"""Lawn mower platform for the Navimow (custom) integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.lawn_mower import (
    LawnMowerActivity,
    LawnMowerEntity,
    LawnMowerEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import NavimowCoordinator
from .entity import NavimowEntity

# Kein REST/MQTT-Rohwert kennt "returning" fuer isDocking direkt, sondern nur ueber die
# in coordinator.py bereits kanonisierten Werte - siehe dortige _RAW_STATE_MAP.
#
# "idle" -> PAUSED statt DOCKED: live beobachtet 2026-07-09, dass "isIdel" auch auftritt,
# waehrend der Maeher manuell mitten im Garten gestoppt wurde (nicht an der Ladestation) -
# "idle" bedeutet nur "steht still", nicht zwingend "gedockt". HAs LawnMowerActivity kennt
# kein eigenes IDLE, PAUSED passt semantisch deutlich besser als DOCKED.
_STATE_TO_ACTIVITY: dict[str, LawnMowerActivity] = {
    "mowing": LawnMowerActivity.MOWING,
    "paused": LawnMowerActivity.PAUSED,
    "returning": LawnMowerActivity.RETURNING,
    "docked": LawnMowerActivity.DOCKED,
    "idle": LawnMowerActivity.PAUSED,
    "error": LawnMowerActivity.ERROR,
}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: NavimowCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([NavimowLawnMowerEntity(coordinator)])


class NavimowLawnMowerEntity(NavimowEntity, LawnMowerEntity):
    _attr_name = None
    _attr_supported_features = (
        LawnMowerEntityFeature.START_MOWING | LawnMowerEntityFeature.PAUSE | LawnMowerEntityFeature.DOCK
    )

    def __init__(self, coordinator: NavimowCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_id}_lawn_mower"

    @property
    def activity(self) -> LawnMowerActivity | None:
        if self.coordinator.data is None:
            return None
        return _STATE_TO_ACTIVITY.get(self.coordinator.data.state)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Diagnose-Attribute, damit der Watchdog (Ziel 1) sichtbar/nachvollziehbar bleibt."""
        data = self.coordinator.data
        if data is None:
            return {}
        return {
            "raw_state": data.raw_state,
            "mqtt_connected": data.mqtt_connected,
            "last_rest_update": data.last_rest_update.isoformat(),
            "last_mqtt_update": data.last_mqtt_update.isoformat() if data.last_mqtt_update else None,
        }

    async def async_start_mowing(self) -> None:
        await self.coordinator.async_send_command("async_start_mowing")

    async def async_pause(self) -> None:
        await self.coordinator.async_send_command("async_pause")

    async def async_dock(self) -> None:
        await self.coordinator.async_send_command("async_dock")
