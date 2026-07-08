# NaviWatch — unofficial Navimow integration for Home Assistant

🇬🇧 English | 🇩🇪 [Deutsch](info.de.md)

Monitor and control Segway Navimow robotic mowers in Home Assistant — independently developed against live-observed Segway API behavior, no code taken from the official `navimow-sdk`.

## Why this integration?

Existing community integrations reproducibly freeze after about an hour and don't recover on their own — only a manual reload helps. This integration was built specifically to fix that:

- **Watchdog against freezes**: compares the REST-polled status against the last known MQTT status on every poll; forces an MQTT reconnect on a mismatch (with debounce, so the same persisting mismatch doesn't trigger unnecessary repeated reconnects)
- Live-tested over several hours, including a full mowing cycle, an automated stop, and manual docking — no freeze, no manual intervention needed

## Features

- `lawn_mower` entity: start, pause, dock
- Battery sensor
- MQTT connection status as a diagnostic sensor
- Hybrid of REST polling (ground truth) and MQTT push (updates within seconds)
- Own icon/logo, translated to English/German

## What this integration can't (yet) do

- **No position/map data (zones)** — not reachable after extensive live testing across REST and all known MQTT channels
- **No mowing progress/remaining time** — no corresponding field in any observed API response

## Prerequisites

- Home Assistant (tested with Core 2026.5.4)
- A Segway account that can sign in to the official app

## Installation

1. HACS → Integrations → top-right menu → **Custom repositories**
2. Repository: `https://github.com/MadMorpheus/naviwatch`, Category: **Integration**
3. Search for `NaviWatch` in HACS and install
4. Restart Home Assistant
5. Settings → Devices & Services → Add Integration → search `NaviWatch`

Uses the `navimow_custom` domain internally and can therefore be installed alongside other Navimow integrations without collision — running both is optional, not required.

---

*Unofficial integration, not authorized or supported by Segway/Navimow. Independently developed from live testing against the real API.*
