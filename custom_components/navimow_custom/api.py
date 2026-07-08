"""REST API client for the Navimow (custom) integration.

Bewusst eigenstaendig statt auf mower_sdk.api.MowerAPI (sdk-reference/) aufgesetzt: nur die
live verifizierten Endpunkte (siehe dokumentation/sdk-notizen.md), ohne Abhaengigkeit von
einem Alpha-Paket mit ungeklaerter Lizenz (GPLv3/MIT-Widerspruch) und bekannten Bugs in
benachbarten Modulen (cloud.py-Topic-Parsing).
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from homeassistant.helpers import config_entry_oauth2_flow

from .const import API_BASE_URL

_LOGGER = logging.getLogger(__name__)


class NavimowApiError(Exception):
    """Raised when the Navimow API returns an error."""

    def __init__(self, message: str, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


class NavimowApiClient:
    """Thin REST client for Segway's Navimow cloud API.

    Nutzt HA's OAuth2Session, die Access-Token vor jedem Request automatisch bei Bedarf
    auffrischt (async_ensure_token_valid) - kein eigenes Token-Refresh-Handling noetig.
    """

    def __init__(self, oauth_session: config_entry_oauth2_flow.OAuth2Session) -> None:
        self._oauth_session = oauth_session

    @property
    def access_token(self) -> str:
        """Aktuell gueltiger Access-Token (fuer MQTT-Auth-Header)."""
        return self._oauth_session.token["access_token"]

    async def _request(
        self, method: str, endpoint: str, json: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        url = f"{API_BASE_URL}{endpoint}"
        headers = {"requestId": str(uuid.uuid4())}
        response = await self._oauth_session.async_request(method, url, json=json, headers=headers)
        response.raise_for_status()
        data: dict[str, Any] = await response.json()
        if data.get("code") != 1:
            raise NavimowApiError(data.get("desc", "Unknown Navimow API error"), code=data.get("code"))
        return data

    async def async_get_devices(self) -> list[dict[str, Any]]:
        data = await self._request("GET", "/openapi/smarthome/authList")
        return data.get("data", {}).get("payload", {}).get("devices", [])

    async def async_get_vehicle_status(self, device_ids: list[str]) -> list[dict[str, Any]]:
        if not device_ids:
            return []
        data = await self._request(
            "POST",
            "/openapi/smarthome/getVehicleStatus",
            json={"devices": [{"id": d} for d in device_ids]},
        )
        return data.get("data", {}).get("payload", {}).get("devices", [])

    async def async_get_mqtt_user_info(self) -> dict[str, Any]:
        data = await self._request("GET", "/openapi/mqtt/userInfo/get/v2")
        return data.get("data", {})

    async def async_send_command(
        self, device_id: str, command_name: str, params: dict[str, Any] | None
    ) -> None:
        execution: dict[str, Any] = {"command": command_name}
        if params is not None:
            execution["params"] = params
        data = await self._request(
            "POST",
            "/openapi/smarthome/sendCommands",
            json={"commands": [{"devices": [{"id": device_id}], "execution": execution}]},
        )
        results = data.get("data", {}).get("payload", {}).get("commands", [])
        for result in results:
            if result.get("status") == "ERROR":
                error_code = result.get("errorCode") or "COMMAND_FAILED"
                # Geraet bereits im Zielzustand ist kein echter Fehler (z.B. Doppelklick).
                if error_code == "alreadyInState":
                    continue
                raise NavimowApiError(f"Navimow command failed: {error_code}")

    async def async_start_mowing(self, device_id: str) -> None:
        await self.async_send_command(device_id, "action.devices.commands.StartStop", {"on": True})

    async def async_stop(self, device_id: str) -> None:
        await self.async_send_command(device_id, "action.devices.commands.StartStop", {"on": False})

    async def async_pause(self, device_id: str) -> None:
        await self.async_send_command(device_id, "action.devices.commands.PauseUnpause", {"on": False})

    async def async_resume(self, device_id: str) -> None:
        await self.async_send_command(device_id, "action.devices.commands.PauseUnpause", {"on": True})

    async def async_dock(self, device_id: str) -> None:
        await self.async_send_command(device_id, "action.devices.commands.Dock", None)
