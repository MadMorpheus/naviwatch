"""OAuth2 implementation for the Navimow (custom) integration."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.config_entry_oauth2_flow import LocalOAuth2Implementation

from .const import CLIENT_ID, CLIENT_SECRET, DOMAIN, OAUTH2_AUTHORIZE, OAUTH2_TOKEN

_LOGGER = logging.getLogger(__name__)


class NavimowOAuth2Implementation(LocalOAuth2Implementation):
    """OAuth2 implementation for Navimow.

    Segway's Authorize-URL erwartet zusaetzlich channel=homeassistant (uebernommen aus
    segwaynavimow/NavimowHA, live verifiziert 2026-07-08). Live-Test zeigte ausserdem, dass
    Segway den von uns gesendeten state-Parameter beim Redirect NICHT unveraendert
    zurueckgibt (siehe dokumentation/sdk-notizen.md) - im echten, HA-gefuehrten Flow
    (im Gegensatz zu unserem Standalone-Testskript) scheint das laut der seit laengerem
    produktiv laufenden NavimowHA-Integration aber zu funktionieren. Falls sich das beim
    ersten echten Testlauf als Problem erweist: async_step_oauth2_authorize in
    config_flow.py ist die Stelle, an der man die state-Validierung lockern muesste.
    """

    def __init__(self, hass: HomeAssistant) -> None:
        super().__init__(
            hass=hass,
            domain=DOMAIN,
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
            authorize_url=OAUTH2_AUTHORIZE,
            token_url=OAUTH2_TOKEN,
        )

    @property
    def name(self) -> str:
        return "Navimow"

    async def async_generate_authorize_url(self, flow_id: str) -> str:
        url = await super().async_generate_authorize_url(flow_id)
        parsed = urlparse(url)
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        query.setdefault("channel", "homeassistant")
        return urlunparse(parsed._replace(query=urlencode(query)))

    async def _async_refresh_token(self, token: dict[str, Any]) -> dict[str, Any]:
        """Navimow-Token: kein garantierter refresh_token, ~1h Gueltigkeit (live gemessen).

        Segway liefert bei einem abgelehnten/abgelaufenen refresh_token keinen klar
        genormten Fehler - String-Heuristik auf die Fehlermeldung, analog NavimowHA.
        """
        if "refresh_token" not in token:
            raise ConfigEntryAuthFailed(
                "Navimow access token expired and no refresh token is available. "
                "Re-authentication required."
            )
        try:
            return await super()._async_refresh_token(token)
        except ConfigEntryAuthFailed:
            raise
        except Exception as err:
            err_str = str(err).lower()
            if any(k in err_str for k in ("401", "403", "invalid", "expired", "unauthorized", "forbidden")):
                _LOGGER.warning("Navimow refresh token rejected by server (%s), re-auth required.", err)
                raise ConfigEntryAuthFailed(f"Navimow refresh token expired: {err}") from err
            _LOGGER.warning("Navimow token refresh failed (possibly transient): %s", err)
            raise
