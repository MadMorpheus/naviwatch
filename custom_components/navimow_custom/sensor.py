"""Sensor platform for the Navimow (custom) integration."""

from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import NavimowCoordinator
from .entity import NavimowEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: NavimowCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            NavimowBatterySensor(coordinator),
            NavimowZoneSensor(coordinator),
            NavimowMowProgressSensor(coordinator),
        ]
    )


class NavimowBatterySensor(NavimowEntity, SensorEntity):
    _attr_translation_key = "battery"
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE

    def __init__(self, coordinator: NavimowCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_id}_battery"

    @property
    def native_value(self) -> int | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.battery


class NavimowZoneSensor(NavimowEntity, SensorEntity):
    """Aktuelle physische Maeh-Zone ueber den undokumentierten 'location'-MQTT-Kanal.

    Noch nicht live verifiziert (siehe location.py, dokumentation/sdk-notizen.md) - bleibt
    None, solange keine passende Nachricht empfangen wurde.
    """

    _attr_translation_key = "zone"

    def __init__(self, coordinator: NavimowCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_id}_zone"

    @property
    def native_value(self) -> int | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.zone

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        data = self.coordinator.data
        if data is None:
            return {}
        return {
            "target_zone": data.target_zone,
            "position_x": data.pos_x,
            "position_y": data.pos_y,
            "task_delay": data.task_delay,
        }


class NavimowMowProgressSensor(NavimowEntity, SensorEntity):
    """Routen-Fortschritt der aktuellen Maehaufgabe (0-100), ueber den 'location'-Kanal.

    Planroute, nicht Flaechenabdeckung (siehe location.py). Noch nicht live verifiziert.
    """

    _attr_translation_key = "mow_progress"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE

    def __init__(self, coordinator: NavimowCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_id}_mow_progress"

    @property
    def native_value(self) -> int | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.mow_progress_pct
