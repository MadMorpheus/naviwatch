"""Binary sensor platform for the Navimow (custom) integration."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import NavimowCoordinator
from .entity import NavimowEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: NavimowCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        NavimowMqttConnectedSensor(coordinator, device_id) for device_id in coordinator.device_ids
    )


class NavimowMqttConnectedSensor(NavimowEntity, BinarySensorEntity):
    """Sichtbarkeit fuer den Watchdog: zeigt, ob der schnelle MQTT-Pfad aktiv ist.

    Der MQTT-Client ist fuer ALLE Geraete des Accounts gemeinsam - dieser Wert ist also pro
    Geraet identisch, wird aber trotzdem pro Geraet als eigene Entity angezeigt, damit man
    ihn direkt neben dem jeweiligen Maeher im Dashboard sieht. Auch wenn diese Entity "aus"
    ist, liefert der REST-Poll-Fallback weiterhin Daten (siehe coordinator.py) - dieser
    Sensor macht nur sichtbar, ob der schnelle Pfad gerade funktioniert, nicht ob der
    jeweilige Maeher grundsaetzlich erreichbar ist.
    """

    _attr_translation_key = "mqtt_connected"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: NavimowCoordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}_mqtt_connected"

    @property
    def is_on(self) -> bool | None:
        data = self._device_data
        if data is None:
            return None
        return data.mqtt_connected
