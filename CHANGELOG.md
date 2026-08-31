# Changelog

All notable changes to NaviWatch are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.3.2] - 2026-08-31

### Fixed

- **`dock_distance` read ~0.75m even while docked.** The mower's own position estimate (SLAM/odometry) doesn't place its coordinate origin exactly on the physical charging station, so measuring distance against a fixed `(0,0)` carried that drift into the sensor. The dock never moves, so every observed `docked` state with a known position is now taken as a fresh zero-point (`dock_offset_x`/`dock_offset_y`), and `dock_distance` measures against that calibrated offset instead. Live-verified on 2026-08-31: the sensor snapped from the old ~0.75m to 0.0m at the exact moment the mower registered as docked, then tracked a subsequent mowing run correctly from there.
- **A rate-limited MQTT credential fetch during setup killed the integration until it was manually reloaded.** `async_setup()` guarded `async_get_devices()` with `ConfigEntryNotReady`, but the `_async_connect_mqtt()` call directly below it was unguarded, so the `NavimowApiError` from `async_get_mqtt_user_info()` propagated out of `async_setup_entry()` as a plain exception. Home Assistant treats anything other than `ConfigEntryNotReady` as a permanent setup failure and schedules no retry. At the hourly OAuth rotation the entry reloads and immediately re-fetches MQTT credentials, which Segway rate-limits (`Request too frequent. Please retry after 1 minute.`) — observed on a US account on 2026-08-17 at 18:17, after which the integration stayed dead for 8.5 hours despite the error being transient by its own description. It now raises `ConfigEntryNotReady`, so Home Assistant backs off and retries; verified live on 2026-08-18 at 13:37, where the same rate limit resolved itself in 6 seconds.
- **The MQTT credential refresh could sustain the very rate limit it was hitting.** `_handle_mqtt_connection_changed()` schedules `_async_refresh_mqtt_credentials()` via `async_create_task()` on every disconnect. When that refresh was rate-limited it logged a warning and returned, leaving the client with stale credentials — so it reconnected, failed, disconnected, and triggered another refresh. Observed on 2026-08-18 between 12:34 and 13:33: 36 attempts bursting roughly every 1.6 seconds. A single-flight guard now collapses piled-up disconnect tasks into one in-flight refresh, and a 65-second cooldown — just past the minute the server itself asks for, so scheduling jitter cannot land the retry back inside the same window — caps the worst case at one call per cooldown instead of about 37. `update_credentials()` remains outside the lock so MQTT work never holds it.
- **Replacing the MQTT client left the old one running in the background.** `update_credentials()` rebuilds the client when it finds one that exists but is not connected, and `_connect_locked()` assigned the new client straight over `self._client` without stopping the old one. paho's `loop_start()` thread runs `loop_forever()`, which reconnects on its own after any unexpected disconnect — only an explicit `disconnect()` ends it. The overwritten client therefore kept running with its callbacks still bound, so every disconnect it saw scheduled another credential refresh, while `async_shutdown()` could only ever reach the newest client; restarting Home Assistant was the only way to clear the rest. Because every client is built with the same client ID, each new connection also made the broker evict the previous session, so zombie and live client kicked each other out indefinitely — reported at 21–63 refreshes per second and roughly 14.8 million warnings in a week. `_connect_locked()` now stops the previous client on every path, and four further routes to the same outcome are closed with it: `disconnect()` takes `_connect_lock` like every other entry point, so it can no longer report success while a rebuild waits in the executor; a one-way closed flag stops the credential-refresh task — which outlives entry unload — from building a client after shutdown; the callbacks check that they belong to the current client, so a dying one cannot report a late connection; and a rebuild that fails is retried on the next poll instead of waiting for the hourly token rotation. `_disconnect_client()` also calls `disconnect()` before `loop_stop()` rather than after, so the socket is actually closed instead of being left open until the keepalive timeout. Stopping a client is bounded by a timeout as well, since that stop now happens while holding the lock every connection path sits behind and a wedged paho thread would otherwise block unload, reload and every future reconnect; and a rebuild that fails between assigning the new client and starting it tears that client down before re-raising, which also removes a leak on the setup path.
- **A failed connection *attempt* never triggered a credential refresh.** The coordinator refreshes credentials from `on_connection_changed(False)`, which the client only raised from `on_disconnect`. paho does not report a failed attempt that way — `loop_forever()` catches the error and calls `_handle_on_connect_fail()` instead. That is exactly the path a rotated token takes, since the token travels in the WSS `Authorization` header and a stale one is rejected at the HTTP upgrade, before any CONNACK. The refresh that would have fixed it was never scheduled, leaving recovery to an unrelated disconnect or to the hourly REST poll. `on_connect_fail` is now bound, and since "not connected" consequently arrives repeatedly during paho's backoff, entity updates are only pushed on an actual transition while the refresh still runs on every attempt. A refused CONNACK is also no longer logged at `WARNING` on every retry — paho retries forever, so a broker that keeps refusing used to produce that line indefinitely; only the first failure of a run is a warning now.

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
