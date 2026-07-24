# Changelog

All notable changes to NaviWatch are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.2.1] - 2026-07-24

### Fixed

- **Leaked MQTT connections after a failed first refresh could spiral into a reconnect storm.** If the very first data refresh during setup failed (`async_config_entry_first_refresh()` raising `ConfigEntryNotReady`), the MQTT client created just before it was never disconnected, because the coordinator hadn't been stored yet and so was never reachable for cleanup. Home Assistant's automatic setup retry then created another coordinator and another live MQTT connection on each attempt, while the orphaned ones kept trying to reconnect forever in the background. Enough retries left multiple connections fighting over the same broker session, which could show up as rapid, continuous connect/disconnect cycling (`rc=7`) across several client IDs at once. `async_setup_entry()` now explicitly shuts down the coordinator (disconnecting the MQTT client) if the first refresh fails, before re-raising. If your instance is already affected, a full Home Assistant restart is required to clear out the orphaned connections — reloading the integration alone won't reach them.

### Added

- `mqtt_client.py` now registers an `on_subscribe` callback and logs, per topic, whether the broker acknowledged (`DEBUG`) or rejected (`WARNING`, e.g. an ACL denial) a channel subscription — including the undocumented `location` channel. Previously there was no way to tell from the logs whether a subscribe for a given channel actually succeeded; a rejected subscription and a silently-never-sending channel looked identical in the log.

## [0.2.0] - 2026-07-09

### Added

- Zone, mow progress, position (local X/Y in meters relative to the dock), heading, target zone, and task-delay sensors, based on the undocumented MQTT `.../realtimeDate/location` channel.

## [0.1.1]

### Fixed

- A blocking call in the MQTT client (`client.tls_set()`, and later `disconnect()`) ran directly on Home Assistant's event loop instead of in an executor thread, which HA's blocking-call detector flagged after a restart. Both now run in an executor thread.

## [0.1.0]

### Added

- Initial release: custom Home Assistant integration for the Segway Navimow i220 LiDAR Pro, combining REST polling with MQTT push updates and a watchdog that forces a reconnect when MQTT silently misses a state change.
