"""Sensor platform for the Navimow (custom) integration."""

from __future__ import annotations

import math

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfLength
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
            NavimowPositionXSensor(coordinator),
            NavimowPositionYSensor(coordinator),
            NavimowDockDistanceSensor(coordinator),
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

    Live verifiziert 2026-07-09 (Zone 1 = ID 9, Zone 2 = ID 4 - interne Partition-IDs, nicht
    identisch mit der "Zone 1"/"Zone 2"-Nummerierung in der Segway-App). Bleibt None, solange
    keine passende Nachricht empfangen wurde (siehe location.py, dokumentation/sdk-notizen.md).
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
            "task_delay": data.task_delay,
        }


class NavimowMowProgressSensor(NavimowEntity, SensorEntity):
    """Routen-Fortschritt der aktuellen Maehaufgabe (0-100), ueber den 'location'-Kanal.

    Planroute, nicht Flaechenabdeckung (siehe location.py). Live verifiziert 2026-07-09 -
    stimmte exakt mit dem in der Segway-App angezeigten Wert ueberein.
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


class NavimowPositionXSensor(NavimowEntity, SensorEntity):
    """X-Position in Metern, lokales kartesisches Koordinatensystem relativ zur Ladestation.

    KEIN GPS - siehe location.py. Live verifiziert 2026-07-09.
    """

    _attr_translation_key = "position_x"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfLength.METERS

    def __init__(self, coordinator: NavimowCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_id}_position_x"

    @property
    def native_value(self) -> float | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.pos_x


class NavimowPositionYSensor(NavimowEntity, SensorEntity):
    """Y-Position in Metern, lokales kartesisches Koordinatensystem relativ zur Ladestation.

    KEIN GPS - siehe location.py. Live verifiziert 2026-07-09.
    """

    _attr_translation_key = "position_y"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfLength.METERS

    def __init__(self, coordinator: NavimowCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_id}_position_y"

    @property
    def native_value(self) -> float | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.pos_y


class NavimowDockDistanceSensor(NavimowEntity, SensorEntity):
    """Luftlinien-Abstand von der Ladestation (Ursprung des Koordinatensystems), in Metern.

    Abgeleitet aus position_x/position_y (sqrt(x^2+y^2)) - kein eigenes Feld aus der API.
    Zusatznutzen: Bleibt der Wert trotz state=mowing ueber laengere Zeit unveraendert, ist das
    ein moegliches (zusaetzliches) Freeze-/Stillstand-Signal, unabhaengig vom REST/MQTT-
    Status-Vergleich des Watchdogs.
    """

    _attr_translation_key = "dock_distance"
    _attr_device_class = SensorDeviceClass.DISTANCE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfLength.METERS

    def __init__(self, coordinator: NavimowCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_id}_dock_distance"

    @property
    def native_value(self) -> float | None:
        data = self.coordinator.data
        if data is None or data.pos_x is None or data.pos_y is None:
            return None
        return round(math.sqrt(data.pos_x**2 + data.pos_y**2), 2)
