# Changelog

**English** | [Deutsch](./CHANGELOG.de.md)

All notable changes to this integration are documented here.
The format is loosely based on [Keep a Changelog](https://keepachangelog.com/).

## [1.17.1] – Keep the connection invariant on cancellation

### Fixed
- A cancelled request could leave its TCP connection open. Connecting and
  draining leftover lines happen before the request is sent and both can be
  cancelled, but only the send and read phase dropped the connection
  afterwards. The client then kept a socket the caller considered gone. The
  poll loop cancels requests when a cycle exceeds its time limit, so this was
  reachable in normal operation

## [1.17.0] – Reconfigure, backup restore and a security fix

### Security
- Backup and discovery exports are no longer written to `/config/www/`, which
  Home Assistant serves under `/local/` **without any authentication**. They go
  to `<config>/neumann_kh/` instead, a folder that is never served over HTTP
- Restoring a backup writes only paths on an explicit allowlist of settings.
  Command paths – among them `device/restore`, the factory reset – are never
  replayed. `ui/control_mode` is written last, because a backup taken in LOCAL
  can cut network control off while the restore is still running

### Added
- **Reconfigure**: address, interface and port of a configured speaker can be
  changed in place, keeping entity IDs, history and automations. A speaker
  whose serial number does not match the entry is refused
- **Restore backup**: writes a stored backup back to the device. Disabled by
  default and confirmed with two presses, like the factory reset. It refuses a
  backup from another model or serial, reports values the device adjusted, and
  says how far it got if the connection drops
- Devices that do not identify as Neumann are flagged during setup. They stay
  usable – SSC is not exclusive to Neumann – and the reported manufacturer is
  shown in the device info

### Changed
- Backup and discovery now cover the rarely polled settings, the logo
  brightness and the full EQ of every container (gain, boost, frequency, Q and
  filter type per band). Previously only the fast poll paths were exported
- A read returns as soon as the requested path has arrived instead of always
  waiting out the settle window. Measured on a KH 750, a full slow poll cycle
  went from 19.2 s to 1.6 s
- Minimum Home Assistant version raised to 2024.11.0

### Fixed
- Answers could bleed between requests: extra lines of one answer stayed on the
  socket, and the next request for the same path returned the previous value
- A failing platform setup left the connection and coordinator behind, so the
  next attempt stacked another one on top
- Device discovery could pick an IPv4 address out of an mDNS record, which then
  failed setup as "not a valid IPv6 address"
- A device that never stopped sending could hold a read – and the client lock –
  open indefinitely
- The link-local check accepted only addresses starting with `fe80` instead of
  the full `fe80::/10` range
- A cancelled priority request could leave the poll loop pausing before every
  single path
- A restored value on a slow-poll path – the device name among them – reached
  the device but not the interface for up to five minutes
- A restore applied whatever backup existed at the second press rather than the
  one shown in the confirmation, and pushed one coordinator update per value
  instead of one for the whole run
- Exports of two speakers with colliding masked serials overwrote each other,
  and are now written atomically
- The README claimed every value is polled every 30 seconds; the rarely
  changing ones are polled every 5 minutes

## [1.16.0] – Localisation and test tooling

### Added
- Device simulator (`tools/ssc_simulator.py`) that reproduces the verified
  firmware behaviour of the KH 120 II and KH 750, so the integration can be
  exercised end to end without hardware
- End-to-end tests that set the integration up against the simulator, plus
  tests for the simulator itself (42 tests in total)

### Changed
- User-facing messages follow the Home Assistant language instead of being
  fixed German: error messages use translation keys, and notifications,
  dynamic config flow labels, EQ container names and the unassigned output
  state are available in German and English
- Repository language is English throughout (comments, docstrings, log and
  developer messages); the bilingual documentation stays as it is
- Test suite targets Linux (WSL2 or CI) and Home Assistant 2026.7. The slow
  end-to-end tests are deselected by default so the everyday run stays fast;
  continuous integration always runs the full set

### Removed
- Three unused storage modules left over from an earlier refactor

## [1.15.2] – Quality assurance

### Added
- Automated test suite (33 tests): protocol client against a local test server
  (including timeouts, connection drops, and the cancellation hardening from
  1.15.0), poll coordination including regression tests for the bug fixed in
  1.15.1, helper functions and export sanitization
- Continuous integration via GitHub Actions: Home Assistant and HACS
  validation, linter and test run on every push and pull request

### Changed
- Two stylistic corrections in the SSC client (consistent error cause chain,
  simplified connection close) – no change in behaviour

### Fixed
- Added the missing dependency declaration for the `network` component in the
  manifest (used for interface selection during manual setup; previously it
  only worked indirectly via `zeroconf`)

## [1.15.1] – Bugfix

### Fixed
- Changed values would jump back to their previous state shortly after being
  changed and stayed wrong for up to 5 minutes, even though the loudspeaker had
  long since applied the new value. Affected were the less frequently polled
  settings (among others input gain, output level, bass/mid/treble, input
  select, device name, and on the subwoofer additionally bass management,
  channel B mode, subwoofer input level, low cut, digital bypass as well as the
  EQ on/off switches). Present since the poll split in 1.14.0

## [1.15.0] – Robustness & privacy

### Fixed / hardened
- If a poll cycle is aborted by the time limit, the connection is now discarded
  cleanly. This prevents a late-arriving response from being attributed to a
  later request, where it would cause wrong values or a wrongly skipped path
- Write actions (levels, switches, select lists, device name, EQ, factory reset
  and others) now report an unreachable loudspeaker as a clear error message
  instead of writing an unhandled error to the log
- If the first connection right after setup fails (e.g. device switched off),
  the open network connection is closed before Home Assistant retries the setup
- After a failed fetch of the rarely polled values, these are now retrieved
  immediately on the next successful cycle instead of waiting for the regular
  interval (5 min) on cached values

### Privacy
- The settings backup now only contains a redacted serial number – in the
  downloaded file and in the filename (previously this was only the case for
  the device diagnostics). The internal association remains unchanged
- Filenames of exported files are additionally sanitized so that they cannot
  under any circumstances leave the export folder

### Changed
- Manual setup: the IPv6 address may now contain the interface directly (e.g.
  `fe80::1%eth0`); a separately selected interface still takes precedence. In
  addition, the port is checked against a valid range (1–65535)

## [1.14.0] – Efficiency & robustness

### Changed
- Poll cycle split into fast and slow paths: changing values are still polled
  every 30 s, while rarely changing values (device identity, static
  configuration, output labels, EQ status) are only polled every 5 minutes.
  This significantly reduces the number of network requests per cycle
  (KH 750 DSP: 47 → 23 per fast cycle) and creates more headroom against the
  cycle time limit. Values not re-polled in between are preserved via a cache
  (no briefly "unknown" entities)
- Input interface (`audio/in/interface`) is now enabled by default on the
  KH 750 DSP as well (confirmed writable on KH 120 II and KH 750 DSP)

### Fixed / hardened
- The backup and discovery buttons are protected against accidental
  double-triggering (an already running operation is not started again)
- The best-effort discovery run (`osc/schema`) now has an overall time limit of
  30 s and, if exceeded, uses the partial result collected up to that point
  instead of running indefinitely

## [1.13.1] – Documentation fix

### Changed
- Clarified the README introduction: device discovery uses `zeroconf` via Home
  Assistant's built-in component (no manual pip install required). Only the SSC
  protocol itself works without any third-party library (own asyncio client)

## [1.13.0] – Bugfix for connection loss, extended model detection, cleanup

### Fixed
- If the loudspeaker was unreachable, the generic per-path error handler caught
  `SSCConnectionError`/`SSCTimeoutError` instead of passing them on to the outer
  handling. This led to log flooding and sometimes to exceeding the poll cycle
  time limit. It now aborts immediately after the first failed connection attempt
- `storage.py` merged back into a single file – the three `.storage/` output
  files (`neumann_kh_names`, `neumann_kh_backups`, `neumann_kh_discovery`) are
  unaffected by this

### Changed
- `manifest.json`: `documentation`/`issue_tracker` now point to this repository
- Extended model detection: now also accepts "KH 750 DSP" (not just "KH 750"),
  as well as "KH 80 DSP", "KH 150 AES67", "KH 120 II AES67" for logo
  brightness/save settings (unverified)
- README: new section on supported/unsupported models; IPv4-related instructions
  removed (according to the official documentation the loudspeakers are
  IPv6-only)

## [1.12.0] – Bass gain moved to diagnostics, storage split

### Changed
- `ui/bass_gain` (KH 120 II) moved from `select` (writable) to `sensor`
  (diagnostic, read-only) – not writable, in line with mid gain/treble gain
- `storage.py` split into three separate modules: `name_storage.py`,
  `backup_storage.py`, `discovery_storage.py` – as a result they also end up as
  three separate files under `.storage/`

### Fixed
- `translations/en.json` was briefly out of sync with `strings.json` after the
  bass gain change

## [1.11.1] – EQ switches at container level instead of per band

### Changed
- EQ on/off switches now switch all bands of a container together (one SSC write
  for the entire `enabled` array) instead of creating one switch per individual
  band – considerably fewer entities (4 instead of 32 on the KH 120 II, 14
  instead of 61 on the KH 750 DSP)
- All EQ container names now consistently start with "EQ" so that they appear
  grouped together alphabetically in the "Configuration" section
- EQ switches and reset buttons are now enabled by default

## [1.11.0] – EQ support, discovery anonymization

### Added
- EQ support: one on/off switch per EQ container (partial SSC array write) plus
  a "Reset to neutral" button (sets gain and boost of all bands to 0 dB).
  Covered: `eq2`/`eq3` on the main output, plus `eq1`/`eq2`/`eq3` on `out1`/`out2`
  on the KH 750 DSP
- README: new overview table showing which entity types are writable

### Changed
- The serial number in the discovery export is now redacted (only the last 3
  characters remain visible)
- Backup and discovery only ever run manually via their respective buttons

## [1.10.0] – Name memory, backup & device discovery

### Added
- New persistent store (`storage.py`, one entry per serial number, independent
  of config entries)
- Name memory: the most recently used name per serial number is pre-filled when
  setting up again via automatic discovery (two-stage scan flow: first select
  the device, then confirm the name)
- "🔄 Search again" as an entry in the scan selection list
- "Create backup" button: reads all known values (without live measurements) and
  stores them persistently as well as as a JSON file
- "Run device discovery" button (diagnostic): combines known paths with a
  best-effort attempt via the optional SSC methods `osc/schema` + `osc/limits`

## [1.9.0] – Non-writable values corrected, bugfixes

### Changed (KH 120 II, not writable → now read-only)
- Input gain, input select, mid gain, output level (SPL), treble gain
- "Save settings" button disabled by default (not functional)

### Changed (KH 750 DSP, not writable → now read-only)
- Bass management, channel B input mode, subwoofer input gain, subwoofer low
  cut, subwoofer output level, subwoofer phase, subwoofer phase inversion

### Fixed
- Output 1/2 mute (`out1_mute`/`out2_mute`, KH 750 DSP) was missing entirely –
  added back
- `settle_time` in `ssc_client.py` now uses the intended constant instead of a
  hard-wired value
- Removed an unused constant

### Cleaned up
- Code comments shortened consistently (concise and technical)

## [1.8.1] – Bugfix: device discovery no longer found any loudspeakers

### Fixed
- `discovery.py`: corrected the parameter names of the mDNS callback
  `_on_change()` (`zeroconf`, `service_type` – python-zeroconf calls this handler
  with named arguments, not positionally; a rename led to a `TypeError` and an
  empty device list)

## [1.8.0] – Responsiveness & robustness

### Added
- Priority path for user actions: a "set" (switch, select, slider) now cuts in
  between two individual queries of a running poll cycle instead of waiting up
  to ~25s for it to finish

### Changed (robustness)
- Apply the confirmed value in an HA-idiomatic way: `_apply_confirmed_value()`
  uses the coordinator's `async_set_updated_data()` instead of mutating
  `coordinator.data` directly
- Defensive numeric conversion: `number`/`sensor` entities catch non-numeric
  device values (showing "unknown" instead of raising an exception)
- The connection is always closed on unload, even if a platform fails to unload
  cleanly
- Correct link-local detection for the entire IPv6 range fe80::/10 (RFC 4291),
  not just an exact "fe80" prefix

## [1.7.0] – Mark already connected loudspeakers in the search

### Added
- During the automatic network scan, loudspeakers that are already set up are
  marked with "✓ already connected" in the selection list

## [1.6.3] – Bugfix: binary_sensor setup failed

### Fixed
- `binary_sensor.py`: two entities passed `entity_category` as a plain string
  instead of the `EntityCategory` enum expected by Home Assistant – newer HA
  versions reject this

## [1.6.2] – Switches/selects no longer briefly jump back

### Fixed
- Fixed a race condition: after a "set", the value already confirmed by the
  device in the same response is now applied directly, instead of triggering a
  complete poll cycle. New shared method
  `NeumannKHEntity._apply_confirmed_value()`

## [1.6.1] – Auto standby correction: model-specific, not universal

### Fixed
- Auto standby is now model-dependent: on non-subwoofer models (KH 120 II etc.)
  a writable `switch`, on the KH 750 DSP it remains a pure `binary_sensor` (not
  writable there)

## [1.6.0] – Corrected value ranges and new entities

### Corrected (value ranges)
- Delay: KH 120 II 0-5760 samples, KH 750 DSP (main/out1/out2) 0-1000 samples –
  now model-dependent
- Standby time: 1-240 min
- Standby threshold: -80 to -55 dBu
- Logo brightness: 0-125 %
- Subwoofer input gain: -12 to +2 dB
- Subwoofer low cut: -12 to 0 dB

### Changed (number → select, as these are fixed steps rather than a continuous range)
- Bass/mid/treble (KH 120 II): now `select` with fixed steps
- Subwoofer phase: now `select` (0°/-45°/-90°/-135°)
- Subwoofer phase inversion: now `select` ("0"/"-180")

### Added
- Input gain (non-subwoofer) as a writable `number`
- Output level SPL (non-subwoofer) as a `select`
- Input select and input interface as `select`
- Control mode (`select`, NETWORK/LOCAL) – disabled by default (safety exception)
- Device name (`text`, max. 52 characters) – new platform `text.py`
- "Restore factory defaults" button with two-step safety confirmation
- Digital bypass (`binary_sensor`, subwoofer only)
- Output label for the main output (`sensor`, subwoofer only)
- "UNKNOWN" for output 1/2 loudspeaker is displayed as "Not assigned"

### Changed (behaviour)
- "Identify" is now a switch (on/off) instead of an auto-stop button
- "Auto standby" was briefly read-only in this version (corrected in 1.6.1, see
  above)
- All KH 120 II entities are now enabled by default, except "Dimm" and "Control
  mode"

### Code hardening
- Shared helper functions (`_util.py`) instead of duplicated implementations
- `ssc_client.py`: `asyncio.LimitOverrunError` is caught
- `coordinator.py`: an error on one poll path no longer brings down the entire
  cycle; overall time limit per poll cycle added
- `config_flow.py`: an empty name is now also rejected during manual setup
- The firmware version is shown as `sw_version` in the device info

## [1.5.0] – Subwoofer support (KH 750 DSP) and code hardening

### Added (only on a detected subwoofer)
- Two additional output channels `out1`/`out2`: level, delay, mute, as well as
  label and assigned loudspeaker type (diagnostic)
- Subwoofer calibration: input gain, low cut, phase, phase inversion
- Subwoofer output level as a fixed selection of 94/100/108/114 dB SPL
- Device temperature (`device_class: temperature`)
- Output level metering and output clip indicator
- Bass management mode, channel B input mode (diagnostic)

### Changed (code hardening, all models)
- Shared helper functions (`_util.py`) instead of duplicated implementations
- `ssc_client.py`: protection against unexpectedly large/never-terminated device
  responses
- `coordinator.py`: an error on a single poll path no longer brings down the
  entire cycle; overall time limit added
- `config_flow.py`: an empty name is now also rejected during manual setup
- The firmware version is shown as `sw_version` in the device info

## [1.4.1] – Custom icon/logo

### Added
- Independent brand design (`brand/` folder): dark anthracite, stylized
  loudspeaker chassis symbol, "NEUMANN CONNECT" wordmark. Requires Home
  Assistant 2026.3 or newer

## [1.4.0] – Clip indicator, auto standby, identify, tone controls, info sensors

### Added
- Clip indicator (`binary_sensor`) – shows when at least one input channel is
  clipping
- Auto standby – on/off switch, time and threshold sliders as well as a
  countdown sensor
- "Identify device" button – makes the logo/LEDs flash briefly
- Tone controls bass/mid/treble as number entities
- Info/diagnostic sensors: device name, hardware version, current input, input
  interface type, control mode
- Warning sensor (`binary_sensor`)

## [1.3.2] – Entity defaults adjusted

### Changed
- "Dimm" is now disabled by default (does not exist on the KH 120 II)
- "Input level (live)" is now enabled by default

## [1.3.1] – Improved error handling

### Changed
- The coordinator now polls each value individually (one leaf path per SSC
  message) instead of per container
- The device identity is no longer re-queried on every poll cycle
- Differentiated error handling: a general connection error fails the entire
  poll cycle; if the device only rejects a single path, only that one is skipped

## [1.3.0] – SSC paths corrected

### Changed
- The coordinator polls values per container (`device`, `ui`, `audio`, `m` as
  four separate SSC messages) instead of in a single combined message
- Corrected SSC paths: input gain (`ui/input_gain`), phase inversion
  (`audio/out/phaseinversion`), live level metering (`m/in/level`, which returns
  a list of values rather than a single value)
- The `input_level_meter` sensor shows the loudest channel for list values

### Removed
- `solo` switch (`audio/out/solo`) – not supported by the model

### Added
- New exception `SSCDeviceError`: detects requests rejected by the device and
  converts them into clear error messages

## [1.2.0] – Active network discovery

### Added
- Entry menu in the config flow: "Search the network automatically" or "Enter
  manually"
- Active mDNS/Zeroconf scan via Home Assistant's existing Zeroconf instance,
  results shown as a selection list
- For automatically discovered devices, the IPv6 scope ID is applied
  automatically

## [1.1.0] – Interface selection as a dropdown

### Changed
- The network interface field in manual setup is now a dropdown, with a
  free-text fallback for interfaces that are not listed

## [1.0.1] – Form values are retained on errors

### Fixed
- On an error the config flow showed a completely empty form – values that had
  already been entered were lost. The most recently entered values are now
  carried over as editable suggestions

## [1.0.0] – Initial release

### Added
- Self-contained asyncio SSC client (TCP port 45, JSON protocol)
- Config flow (manual entry: name, IP address, interface, port)
- `DataUpdateCoordinator` with a 30-second poll interval
- Entities: output level, dimm, delay, logo brightness (`number`); mute, phase
  inversion (`switch`); input gain, live input level (`sensor`); save settings
  (`button`)
- Model detection: logo brightness/save settings only on KH 80/150/120 II, not
  on the KH 750 DSP
