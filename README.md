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

### Zone, Progress & Position 🗺️

* Current mowing zone, route progress (0–100%, confirmed to match the official app exactly), position (local X/Y in meters), heading, and distance from dock
* Sourced from an undocumented MQTT channel found by inspecting a third-party fork's source code — see [Known risks](#known-risks--this-could-break-and-its-not-in-my-hands-)

### Native Home Assistant Integration

* Native `lawn_mower` entity, full automation compatibility
* Own brand icon/logo
* Translated: English, German

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

## Already have another Navimow integration installed? 🔀

NaviWatch uses its own domain (`navimow_custom`), so it **can run side by side** with the official `segwaynavimow/NavimowHA` integration (or forks of it) without any conflict — no need to remove anything first.

* **Keep both**: useful while you're evaluating NaviWatch — you'll get a second set of entities (Home Assistant appends `_2` to names if they'd otherwise collide) so you can compare behavior before committing.
* **Switch over fully**: once you trust NaviWatch, remove the other integration via Settings → Devices & Services → find it → three-dot menu → **Delete**. Afterwards, update any automations/dashboards that reference the old entity IDs to point to NaviWatch's entities instead (Settings → Devices & Services → NaviWatch → device page lists the current entity IDs).
* There is no automatic migration of settings or history between the two integrations — each keeps its own entities and state history.

## Usage 🎮

After setup (OAuth2 login with your Segway account), you'll get one device with the following entities:

| Entity | What it is |
|---|---|
| `lawn_mower` | The main entity. State is one of `mowing`, `paused`, `returning`, `docked`, `error`. Supports Start/Pause/Dock. Diagnostic attributes (`raw_state`, `mqtt_connected`, `last_rest_update`, `last_mqtt_update`) let you confirm the watchdog is working. |
| Battery `sensor` | Battery percentage. |
| MQTT connection `binary_sensor` (diagnostic) | Whether the fast MQTT push path is currently connected. Not an indicator of overall reachability — REST polling keeps the mower entity working regardless. |
| Zone `sensor` | Current physical mowing zone/partition ID. This is an **internal ID assigned by Segway's backend**, not the same as the "Zone 1"/"Zone 2" labels in the app (confirmed live: two real zones showed IDs `9` and `4`). **These IDs are not sequential/predictable** — before building automations around a specific zone, start each zone once via the app and note the ID that appears (Developer Tools → States, or the entity's state on the dashboard). Attributes: `target_zone` (zone selected at mow start), `task_delay` (rain/schedule delay). |
| Mowing progress `sensor` | Route-plan progress, 0–100% for the current task (not area coverage). Confirmed live to match the percentage shown in the official app exactly. |
| Position X / Position Y `sensor` | Local Cartesian coordinates in meters, relative to the charging dock — **not GPS**. Useful for custom automations, e.g. defining your own sub-areas or detecting if the mower hasn't moved in a while. |
| Distance from dock `sensor` | Derived (`sqrt(x² + y²)`) straight-line distance from the dock, in meters. Doubles as a stall/freeze signal — an unmoving value while `state=mowing` is suspicious. |
| Heading `sensor` | Direction the mower currently faces, in degrees (0–360°). Relative to the same local coordinate system as position X/Y — not a compass. |

**Zone, mowing progress, position, distance, and heading all come from an undocumented MQTT channel** discovered by inspecting a third-party fork's source code, not from the official API — see [Known risks](#known-risks--this-could-break-and-its-not-in-my-hands-) for what that means for long-term reliability.

The poll interval can be adjusted in the integration's options.

Wondering exactly when/how often each entity updates? See [ARCHITECTURE.md](ARCHITECTURE.md).

## Troubleshooting 🔧

* Seeing repeated reconnects in the logs (`Navimow Watchdog: ...`)? That's normal behavior for a real state change — a 5-minute debounce prevents unnecessary repeated reconnects for the same persisting mismatch.
* Make sure your account can sign in to the official Navimow app — this integration uses the same OAuth2 flow.
* If you run into issues: check the Home Assistant logs for messages from `custom_components.navimow_custom` and open an issue with relevant log excerpts: `https://github.com/MadMorpheus/naviwatch/issues`

## Known risks — this could break, and it's not in my hands ⚠️

This is an independent, unofficial hobby project with no partnership or support agreement with Segway. Roughly in order of likelihood:

1. **Segway changes something on their backend.** No guarantee of API stability. The most fragile part is the **undocumented** MQTT `location` channel (zone/progress data) — reverse-engineered from a third-party fork, not part of any official API, and could change or disappear without notice. The core functionality (status, battery, start/pause/dock) uses the same endpoints as the official app, which is somewhat more stable but still not guaranteed.
2. **Segway rotates or restricts the shared OAuth client** (`client_id`/`client_secret`, a "public client" used by every community integration of this kind). If they ever lock that down, every non-official integration — including this one — would need new credentials.
3. **Home Assistant core changes.** Its OAuth2 framework or `DataUpdateCoordinator` API could change in a future major version. HA's blocking-call detector is also getting stricter over time and may flag currently-unnoticed issues in future releases.
4. **The `paho-mqtt` library changes.** This integration intentionally uses the older `CallbackAPIVersion.VERSION1` API, which a future major version could remove.
5. **Mower firmware updates.** New or changed `vehicleState` values (there's already one known firmware typo, `isIdel`) could fall outside the current state mapping.

**Bottom line:** this is a solo project with no vendor relationship and no active monitoring on Segway's side. If something changes upstream, the integration will likely fail silently (errors in the log) until someone notices and updates the code — there's no guarantee of a fix, or a fix on any particular timeline.

## License

MIT — see [`LICENSE`](LICENSE).
