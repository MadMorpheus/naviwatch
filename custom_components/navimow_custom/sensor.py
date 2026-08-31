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
    # Ein vollstaendiger Satz Sensoren PRO Geraet im Account, nicht mehr nur fuer eines.
    entities: list[SensorEntity] = []
    for device_id in coordinator.device_ids:
        entities.extend(
            [
                NavimowBatterySensor(coordinator, device_id),
                NavimowZoneSensor(coordinator, device_id),
                NavimowMowProgressSensor(coordinator, device_id),
                NavimowPositionXSensor(coordinator, device_id),
                NavimowPositionYSensor(coordinator, device_id),
                NavimowDockDistanceSensor(coordinator, device_id),
                NavimowHeadingSensor(coordinator, device_id),
            ]
        )
    async_add_entities(entities)


class NavimowBatterySensor(NavimowEntity, SensorEntity):
    _attr_translation_key = "battery"
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE

    def __init__(self, coordinator: NavimowCoordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}_battery"

    @property
    def native_value(self) -> int | None:
        data = self._device_data
        if data is None:
            return None
        return data.battery


class NavimowZoneSensor(NavimowEntity, SensorEntity):
    """Aktuelle physische Maeh-Zone ueber den undokumentierten 'location'-MQTT-Kanal.

    Live verifiziert 2026-07-09 (Zone 1 = ID 9, Zone 2 = ID 4 - interne Partition-IDs, nicht
    identisch mit der "Zone 1"/"Zone 2"-Nummerierung in der Segway-App). Bleibt None, solange
    keine passende Nachricht empfangen wurde (siehe location.py, dokumentation/sdk-notizen.md).
    """

    _attr_translation_key = "zone"

    def __init__(self, coordinator: NavimowCoordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}_zone"

    @property
    def native_value(self) -> int | None:
        data = self._device_data
        if data is None:
            return None
        return data.zone

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        data = self._device_data
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

    def __init__(self, coordinator: NavimowCoordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}_mow_progress"

    @property
    def native_value(self) -> int | None:
        data = self._device_data
        if data is None:
            return None
        return data.mow_progress_pct


class NavimowPositionXSensor(NavimowEntity, SensorEntity):
    """X-Position in Metern, lokales kartesisches Koordinatensystem relativ zur Ladestation.

    KEIN GPS - siehe location.py. Live verifiziert 2026-07-09.
    """

    _attr_translation_key = "position_x"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfLength.METERS

    def __init__(self, coordinator: NavimowCoordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}_position_x"

    @property
    def native_value(self) -> float | None:
        data = self._device_data
        if data is None:
            return None
        return data.pos_x


class NavimowPositionYSensor(NavimowEntity, SensorEntity):
    """Y-Position in Metern, lokales kartesisches Koordinatensystem relativ zur Ladestation.

    KEIN GPS - siehe location.py. Live verifiziert 2026-07-09.
    """

    _attr_translation_key = "position_y"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfLength.METERS

    def __init__(self, coordinator: NavimowCoordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}_position_y"

    @property
    def native_value(self) -> float | None:
        data = self._device_data
        if data is None:
            return None
        return data.pos_y


class NavimowDockDistanceSensor(NavimowEntity, SensorEntity):
    """Luftlinien-Abstand von der Ladestation, in Metern.

    Abgeleitet aus position_x/position_y - kein eigenes Feld aus der API. Nicht einfach
    sqrt(x^2+y^2): der Koordinatenursprung (0,0) des Maehers faellt wegen Restdrift der
    SLAM/Odometrie-Positionsschaetzung nicht exakt mit der physischen Ladestation zusammen
    (live beobachtet: ~0,75m Anzeige trotz angedockt). Stattdessen wird gegen den zuletzt im
    Zustand "docked" kalibrierten Nullpunkt (dock_offset_x/y, siehe coordinator.py
    _apply_dock_calibration) gerechnet - vor der ersten Kalibrierung faellt das auf die alte
    Annahme (0,0) = Ladestation zurueck.
    Zusatznutzen: Bleibt der Wert trotz state=mowing ueber laengere Zeit unveraendert, ist das
    ein moegliches (zusaetzliches) Freeze-/Stillstand-Signal, unabhaengig vom REST/MQTT-
    Status-Vergleich des Watchdogs.
    """

    _attr_translation_key = "dock_distance"
    _attr_device_class = SensorDeviceClass.DISTANCE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfLength.METERS

    def __init__(self, coordinator: NavimowCoordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}_dock_distance"

    @property
    def native_value(self) -> float | None:
        data = self._device_data
        if data is None or data.pos_x is None or data.pos_y is None:
            return None
        offset_x = data.dock_offset_x if data.dock_offset_x is not None else 0.0
        offset_y = data.dock_offset_y if data.dock_offset_y is not None else 0.0
        return round(math.sqrt((data.pos_x - offset_x) ** 2 + (data.pos_y - offset_y) ** 2), 2)


class NavimowHeadingSensor(NavimowEntity, SensorEntity):
    """Blickrichtung des Maehers in Grad (0-360), umgerechnet aus 'postureTheta' (Radiant).

    Kein Kompass - relativ zum selben lokalen Koordinatensystem wie position_x/position_y
    (Ursprung/Ausrichtung an der Ladestation), siehe location.py.
    """

    _attr_translation_key = "heading"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "°"

    def __init__(self, coordinator: NavimowCoordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}_heading"

    @property
    def native_value(self) -> float | None:
        data = self._device_data
        if data is None or data.pos_theta is None:
            return None
        return round(math.degrees(data.pos_theta) % 360, 1)
