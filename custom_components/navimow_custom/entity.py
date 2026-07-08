"""Shared base entity for the Navimow (custom) integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import NavimowCoordinator


class NavimowEntity(CoordinatorEntity[NavimowCoordinator]):
    """Basis-Entity mit gemeinsamem DeviceInfo fuer alle Plattformen."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: NavimowCoordinator) -> None:
        super().__init__(coordinator)
        device_id = coordinator.device_id or "unknown"
        raw = coordinator.device_info_raw
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=raw.get("name") or "Navimow",
            manufacturer="Segway",
            model=raw.get("model"),
            sw_version=raw.get("firmware"),
        )
