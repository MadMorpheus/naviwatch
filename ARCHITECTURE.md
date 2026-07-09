# Architecture

How NaviWatch is built, and — most importantly — how often each entity actually updates and what triggers it.

## REST poll vs. MQTT push

NaviWatch combines two data sources:

* **REST poll** — the ground truth. Runs on a fixed interval (`poll_interval_seconds` option, default 120s), independent of everything else.
* **MQTT push** — event-driven updates from Segway's cloud broker. Reacts within seconds to real changes, but never on a fixed schedule — some channels can stay silent for many minutes.

A watchdog compares the two on every REST poll: if the REST-reported state differs from the last MQTT-reported state, it forces an MQTT reconnect (with a 5-minute debounce so the same persisting mismatch doesn't retrigger it repeatedly). This is what makes the integration resilient against the freeze bug seen in other Navimow integrations — REST polling is deliberately kept independent of MQTT's own message-driven update timing (see "Why entity updates and the poll schedule are kept separate" below for why that independence matters).

## Update triggers per entity

| Entity | Source | Interval / trigger |
|---|---|---|
| `lawn_mower` (state, `raw_state`) | REST poll **+** MQTT `state` channel | REST: fixed ~120s. MQTT: event-driven, only on a real state change (e.g. docked→mowing), usually within seconds of the real transition |
| `sensor` battery | REST poll (primary), MQTT `state` channel (if present in the payload) | ~120s via REST — the reliable, guaranteed source |
| `binary_sensor` MQTT connection | The MQTT client itself (paho `on_connect`/`on_disconnect`) | Purely event-driven — changes only on an actual connect/disconnect, no fixed interval |
| Zone sensor (state) | MQTT `location` channel, type-2 message (`currentMowBoundary`) | Only when the mower crosses a zone boundary — not continuous, can take several minutes |
| Mowing progress sensor | MQTT `location` channel, type-2 message (`currentMowProgress`) | Same message as zone state, so the same (fairly infrequent) cadence |
| Position (`position_x`/`position_y` attributes) | MQTT `location` channel, type-1 message (pose) | Much more frequent — roughly every few seconds while actively mowing, less often when idle |
| `target_zone` attribute | MQTT `location` channel, type-3 message | Set once at mow start / zone selection, unchanged until the next start |
| `task_delay` attribute | MQTT `location` channel, type-4 message | Only on a rain/schedule delay, rare |

**In short:** REST is the only fixed heartbeat (~120s, independent of everything else). Everything from the `location` channel is purely event-driven and depends on real mower behavior — position updates often, zone/progress/target-zone/delay much less so.

## The undocumented `location` MQTT channel

The stock Segway API/SDK only documents the `state`, `event`, and `attributes` MQTT channels. `location` (`/downlink/vehicle/{id}/realtimeDate/location`) was found by inspecting a third-party fork's public source code, not from official documentation — see the "Known risks" section in the [README](README.md) for what that means for long-term reliability. Its payload is a JSON **array** (not an object) of items keyed by `type`:

| Type | Meaning | Fields |
|---|---|---|
| 1 | Pose | `postureX`/`postureY` (meters, local Cartesian grid relative to the dock — **not GPS**), `postureTheta` (radians), `vehicleState` |
| 2 | Progress | `currentMowBoundary` (current physical zone), `currentMowProgress` (0–10000, route progress — not area coverage) |
| 3 | Target zone | `partitionIds` (set at mow start, absent for a "mow all" command) |
| 4 | Delay | `taskDelay` (rain/schedule delay) |

Decoding lives in `custom_components/navimow_custom/location.py`.

## Why entity updates and the poll schedule are kept separate

Home Assistant's `DataUpdateCoordinator.async_set_updated_data()` is convenient for push updates, but it also resets the coordinator's next-scheduled-poll timer on every call. During active mowing, `location` messages (mostly pose updates) arrive roughly every 2 seconds — calling `async_set_updated_data()` from the message handler would reset the 120-second REST-poll countdown before it could ever elapse, silently starving the REST poll (and with it the watchdog) for as long as the mower kept moving. This was found live (2026-07-09) via `custom_components.navimow_custom: debug` logging, which showed Home Assistant's own `"Manually updated navimow_custom data"` debug line firing every ~2 seconds instead of the expected ~120s poll cadence.

The fix: MQTT push handlers update `self.data` directly and call `async_update_listeners()` instead of `async_set_updated_data()`, so entities still refresh instantly on push data without ever touching the poll schedule.
