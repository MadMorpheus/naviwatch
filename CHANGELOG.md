# Changelog

All notable changes to NaviWatch are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Fixed

- **A rate-limited MQTT credential fetch during setup killed the integration until it was manually reloaded.** `async_setup()` guarded `async_get_devices()` with `ConfigEntryNotReady`, but the `_async_connect_mqtt()` call directly below it was unguarded, so the `NavimowApiError` from `async_get_mqtt_user_info()` propagated out of `async_setup_entry()` as a plain exception. Home Assistant treats anything other than `ConfigEntryNotReady` as a permanent setup failure and schedules no retry. At the hourly OAuth rotation the entry reloads and immediately re-fetches MQTT credentials, which Segway rate-limits (`Request too frequent. Please retry after 1 minute.`) — observed on a US account on 2026-08-17 at 18:17, after which the integration stayed dead for 8.5 hours despite the error being transient by its own description. It now raises `ConfigEntryNotReady`, so Home Assistant backs off and retries; verified live on 2026-08-18 at 13:37, where the same rate limit resolved itself in 6 seconds.
- **The MQTT credential refresh could sustain the very rate limit it was hitting.** `_handle_mqtt_connection_changed()` schedules `_async_refresh_mqtt_credentials()` via `async_create_task()` on every disconnect. When that refresh was rate-limited it logged a warning and returned, leaving the client with stale credentials — so it reconnected, failed, disconnected, and triggered another refresh. Observed on 2026-08-18 between 12:34 and 13:33: 36 attempts bursting roughly every 1.6 seconds. A single-flight guard now collapses piled-up disconnect tasks into one in-flight refresh, and a 60-second cooldown (matching the server's own retry advice) caps the worst case at one call per minute instead of about 37. `update_credentials()` remains outside the lock so MQTT work never holds it.

## [0.3.0] - 2026-07-27

### Added

- **Multi-mower support.** A single account can now have any number of mowers; the coordinator polls all of them in one REST call, shares one MQTT client across all of them, and routes incoming messages by the `device_id` embedded in each MQTT topic. `coordinator.data` is now `dict[device_id, NavimowData]` instead of a single object, and every entity now takes a `device_id` to look up its own slice. Previously, only `devices[0]` from the account was ever used, which could pick a different mower on every restart if the account's device order wasn't stable, leaving orphaned "ghost" devices behind in the entity registry.
- The base multi-device rewrite (the `dict[device_id, ...]` coordinator, the shared MQTT client, per-device entities) was contributed by [github.com/klarah32](https://github.com/klarah32) — thank you! One thing was adapted from that contribution before merging: the bounded command-verification feature (`COMMAND_VERIFICATION_SPECS`/`last_command_result`, added in 0.2.2) had been dropped in the process. It's restored here, now tracked per `device_id` instead of globally, and re-verified live against a real mower (`pause`/`start_mowing` both confirmed `verified`) on 2026-07-27.

### Known limitation

- Only one Home Assistant config entry (one Segway/Navimow account) is supported. Multiple mowers under the *same* account are picked up automatically; a second, separate account is not — `config_flow.py` still ties its `unique_id` to the integration domain rather than to an account.

## [0.2.2] - 2026-07-27

### Added

- **Bounded command verification** after `start_mowing`/`pause`/`dock`. Previously, the service call returned after a single poll regardless of outcome — a command accepted by the cloud but never actually carried out by the mower (obstacle, dead zone) would go unnoticed. Now the coordinator polls (up to a per-command timeout) until the target state is actually reached, and exposes the outcome as `last_command_result` (`verified` or `timeout`, plus the last known state) on the lawn mower entity's attributes. `dock` runs its verification in the background (budget up to 15 minutes for the return trip) so the service call itself doesn't block. Live-verified against the real mower on 2026-07-13, including a real ~1:38 min return trip — this release just catches it up in version control; it had been running unversioned since then.

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
