"""Shared base entity for the Navimow (custom) integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import NavimowCoordinator, NavimowData


class NavimowEntity(CoordinatorEntity[NavimowCoordinator]):
    """Basis-Entity mit gemeinsamem DeviceInfo fuer alle Plattformen.

    Der Coordinator verwaltet jetzt ALLE Maeher des Accounts gemeinsam (self.data ist ein
    dict[device_id, NavimowData]) - jede Entity gehoert aber weiterhin zu GENAU einem
    Maeher, daher braucht jede Instanz jetzt zusaetzlich ihre eigene device_id, um sich aus
    dem geteilten Coordinator-Dict den richtigen Datensatz zu holen (siehe _device_data).
    """

    _attr_has_entity_name = True

    def __init__(self, coordinator: NavimowCoordinator, device_id: str) -> None:
        super().__init__(coordinator)
        self.device_id = device_id
        raw = coordinator.device_info_raw(device_id)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=raw.get("name") or "Navimow",
            manufacturer="Segway",
            model=raw.get("model"),
            sw_version=raw.get("firmware"),
        )

    @property
    def _device_data(self) -> NavimowData | None:
        """Der Datensatz GENAU dieses Maehers aus dem account-weiten Coordinator-Dict.

        Zentrale Stelle statt in jeder Entity self.coordinator.data.get(self.device_id) zu
        wiederholen - reduziert das Risiko, beim naechsten Sensor-Typ versehentlich wieder
        auf coordinator.data direkt (statt auf den eigenen device_id-Eintrag) zuzugreifen.
        """
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get(self.device_id)
