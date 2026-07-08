# NaviWatch

🇬🇧 English | 🇩🇪 [Deutsch](README.de.md)

Unofficial Home Assistant integration for Segway Navimow robotic mowers.

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=MadMorpheus&repository=naviwatch&category=Integration)

Independently developed against live-observed Segway API behavior — no code taken from the official `navimow-sdk`, no dependency on other Navimow integrations.

## Why this integration? 🐛→✅

Existing community integrations reproducibly freeze after about an hour and don't recover on their own — only a manual reload helps. NaviWatch was built specifically to fix this with a built-in watchdog:

* Compares the REST-polled status against the last known MQTT status on every poll
* Forces an MQTT reconnect on a mismatch
* Debounce prevents the same persisting mismatch from triggering unnecessary repeated reconnects
* Live-tested over several hours, including a full mowing cycle, an automated stop, and manual docking — no freeze, no manual intervention needed

## Features ✨

### Mower Control

* Start mowing
* Pause mowing
* Send mower to dock

### Device Monitoring

* Real-time mower state (`lawn_mower` entity)
* Battery sensor
* MQTT connection status as a diagnostic sensor

### Real-Time Communication

* Hybrid of REST polling (ground truth) and MQTT push
* MQTT updates react within seconds to real state changes

### Native Home Assistant Integration

* Native `lawn_mower` entity, full automation compatibility
* Own brand icon/logo
* Translated: English, German

## What this integration can't (yet) do

* **No position/map data (zones)** — not reachable after extensive live testing across REST and all known MQTT channels
* **No mowing progress/remaining time** — no corresponding field in any observed API response

## Prerequisites 📋

* Home Assistant, tested with Core **2026.5.4** (≥ 2026.3 recommended for local brand icons)
* A Segway account that can sign in to the official app

## Installation 🛠️

This integration is not in the default HACS store — it must be added as a custom repository:

1. HACS → Integrations → top-right menu → **Custom repositories**
2. Repository: `https://github.com/MadMorpheus/naviwatch`
3. Category: **Integration**
4. Search for `NaviWatch` and install it
5. Restart Home Assistant
6. Settings → Devices & Services → Add Integration → search `NaviWatch`

**Manual installation** (alternative, without HACS):

1. Copy `custom_components/navimow_custom/` from this repo to `<config>/custom_components/navimow_custom/`
2. Restart Home Assistant
3. Settings → Devices & Services → Add Integration → search `NaviWatch`

Uses the `navimow_custom` domain internally, so it can be installed alongside other Navimow integrations without collision — running both is optional, not required.

## Usage 🎮

After setup (OAuth2 login with your Segway account), you'll see:

* A `lawn_mower` entity (start/pause/dock)
* A battery `sensor`
* A `binary_sensor` for the MQTT connection status

The poll interval can be adjusted in the integration's options.

## Troubleshooting 🔧

* Seeing repeated reconnects in the logs (`Navimow Watchdog: ...`)? That's normal behavior for a real state change — a 5-minute debounce prevents unnecessary repeated reconnects for the same persisting mismatch.
* Make sure your account can sign in to the official Navimow app — this integration uses the same OAuth2 flow.
* If you run into issues: check the Home Assistant logs for messages from `custom_components.navimow_custom` and open an issue with relevant log excerpts: `https://github.com/MadMorpheus/naviwatch/issues`

## License

MIT — see [`LICENSE`](LICENSE).
