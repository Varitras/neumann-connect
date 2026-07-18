# Neumann Connect – Home Assistant Custom Component

**English** | [Deutsch](./README.de.md)

Controls Neumann KH DSP loudspeakers (KH 80, KH 120 II, KH 150, KH 750 DSP)
via the Sennheiser Sound Control Protocol (SSC), TCP port 45. No additional
pip package needs to be installed – a lean, self-contained asyncio client is
included for the SSC protocol itself, and device discovery uses Home
Assistant's built-in Zeroconf component.

Change history: see [CHANGELOG.md](./CHANGELOG.md).

Custom icon/logo in `custom_components/neumann_kh/brand/` (an independent
design, not a copy of the official Neumann company logo). Requires **Home
Assistant 2026.3 or newer** (only from that version on do custom integrations
read their brand images directly from their own `brand/` folder, see the
[HA Developer Blog](https://developers.home-assistant.io/blog/2026/02/24/brands-proxy-api/)).
Older versions will display a generic icon instead.

Based on the SSC address paths documented in the
[khtool project](https://github.com/schwinn/khtool).

## Disclaimer

**This is a private hobby/test project, developed for my own setup and shared
"as-is".** It is not an official integration, and there is no warranty and no
guaranteed support or maintenance. Use at your own risk – especially with
writable settings that directly change the actual loudspeaker hardware (EQ,
levels, delay, factory reset). Always double-check changes in Neumann's own
MA1/Neumann.Control software or directly on the device.

Developed with AI assistance (Claude), with all testing, decisions and
validation performed by me against my own installation (KH 120 II, KH 750 DSP).

## Supported models

**Tested against real hardware:** KH 120 II, KH 750 DSP.

**Likely to work, but unverified** (same DSP/SSC basis according to the
manufacturer, no testing of my own): KH 80 DSP, KH 150, and their AES67
variants (KH 120 II AES67, KH 150 AES67). Value ranges (delay, logo
brightness, etc.) are taken from the KH 120 II and may differ slightly on
these models.

**Cannot be supported** (no DSP/network capability, purely analog): KH 310,
KH 420 and other classic analog KH monitors. These cannot be addressed via
SSC – a setup attempt will simply fail with "connection failed", which is not
a bug in this integration.

**Completely untested, possibly compatible:** The newer DSP subwoofers
KH 805 II, KH 810 II, KH 870 II (introduced 2024/2025, described by the
manufacturer as "building on the KH 750 DSP") are not yet included in the
model detection – if you own one of these devices and would like to test,
feel free to get in touch.

## Setup

1. Copy the folder `custom_components/neumann_kh` into your Home Assistant
   configuration directory (e.g. `/config/custom_components/neumann_kh`).
2. Restart Home Assistant.
3. **Settings → Devices & Services → Add Integration → "Neumann KH (SSC)"**.
4. You will get a menu with two options:
   - **"Search the network automatically"** – active mDNS scan (see below),
     results shown as a selection list. The recommended default route.
   - **"Enter manually"** – IP address, interface dropdown, port (fallback in
     case the automatic search does not find a device).
5. Create a separate entry for **each** loudspeaker (e.g. "KH 120 II Left",
   "KH 120 II Right", "KH 750 DSP Sub 1", "KH 750 DSP Sub 2").

## Automatic discovery (mDNS/Zeroconf)

According to the SSC specification, Neumann KH loudspeakers announce
themselves on the network via mDNS/Bonjour (service type `_ssc._tcp.local.`) –
just like AirPlay devices, for example. The integration uses Home Assistant's
already-running Zeroconf instance to actively search for a few seconds and
shows the devices it finds (model, IP address, serial number) for selection.

**Advantage with IPv6 link-local:** The discovered address already includes
the scope ID automatically (e.g. `fe80::...%3`) – for automatically
discovered devices you do **not** need to specify the network interface
manually.

**If nothing is found:** simply submit the form again without a selection to
repeat the search – or go back to the menu and choose "Enter manually". mDNS
only works reliably if HA is in the same network segment as the loudspeakers
in terms of multicast (with Docker, for example, `network_mode: host` is
required) – the same prerequisite that applies to the link-local connection
anyway.

## Determining the IPv6 link-local address & interface (only for "Enter manually")

By default the loudspeakers are only reachable via their IPv6 link-local
address (`fe80::...`). This address strictly requires a **scope ID** (network
interface), otherwise no operating system can resolve the route.

**Selecting the interface:** In the config flow, the interface field is a
**dropdown** listing all network interfaces that Home Assistant knows about on
the host (including their currently assigned IPv4/IPv6 addresses to help you
identify them). If the interface you want does not appear there (e.g. with
certain Docker network setups), you can also type a custom value into the same
field.

**Finding the address** (e.g. on the HA host or on a machine in the same
network segment):

```bash
# Using khtool itself (can be used independently of this integration):
python3 ./khtool.py -i eth0 --scan -q
```

The output shows one line per device, like:
```
IPv6 address: fe80::2a36:38ff:fe12:3456
```

**Determining interface names on the HA host** (only if you do want or need to
type it in manually – normally the dropdown selection in the config flow is
sufficient):
```bash
ip -6 addr show scope link
```
(Interface names such as `eth0`, `end0`, `enp1s0` – depending on the system.)

In the config flow you then enter, for example:
- **IP address:** `fe80::2a36:38ff:fe12:3456`
- **Interface:** select from the dropdown (or type `eth0` manually)

> If Home Assistant runs in Docker: the container needs `network_mode: host`
> or direct layer-2 access to the loudspeakers' network segment, otherwise the
> link-local address is not reachable.

## Entities created per loudspeaker

**Writable vs. read-only (by entity type):**

| Type | Writable? |
|---|---|
| `number` | Yes – numeric value via slider/input field |
| `select` | Yes – fixed set of options |
| `switch` | Yes – on/off |
| `text` | Yes – free text |
| `button` | Triggers a one-off action (no value, no reading/writing) |
| `sensor` | **No**, read-only |
| `binary_sensor` | **No**, read-only |

Values that ought to be writable according to the khtool metadata but are
**confirmed by actual testing not to be writable** (see "Known limitations")
are therefore deliberately implemented as `sensor`/`binary_sensor` instead of
`number`/`select`/`switch` – not because HA technically requires it, but
because a write attempt would fail there anyway.

**Enabled by default (non-subwoofer models such as the KH 120 II):** all
entities are enabled by default, **except** "Dimm" (does not exist there),
"Control mode" (safety exception) and "Save settings" (not functional).

| Entity | Type | Range | SSC path |
|---|---|---|---|
| Output level | `number` | 0–120 dB | `audio/out/level` |
| Dimm (default: disabled, not present on the KH 120 II) | `number` | −120–0 dB | `audio/out/dimm` |
| Delay | `number` | 0–5760 samples @48kHz (KH 750 DSP: 0–1000) | `audio/out/delay` |
| Logo brightness* | `number` | 0–125 % | `ui/logo/brightness` |
| Auto standby time | `number` | 1–240 min | `device/standby/auto_standby_time` |
| Standby threshold | `number` | −80 to −55 dBu | `device/standby/level` |
| Mute | `switch` | – | `audio/out/mute` |
| Identify device (on/off) | `switch` | – | `device/identification/visual` |
| Phase inversion (non-subwoofer only) | `switch` | – | `audio/out/phaseinversion` |
| Auto standby (non-subwoofer only; `binary_sensor` on the KH 750 DSP instead) | `switch` | – | `device/standby/enabled` |
| Input interface (default: disabled on subwoofer, otherwise enabled; writability unverified) | `select` | ANALOG ONLY/DIGITAL ONLY/DIGITAL DISCARDS ANALOG | `audio/in/interface` |
| Control mode (default: **always** disabled, see warning below) | `select` | NETWORK/LOCAL | `ui/control_mode` |
| Device name (default: disabled) | `text` | max. 52 characters | `device/name` |
| Input level (live) | `sensor` | dB | `m/in/level` |
| Standby countdown (default: disabled) | `sensor` | min | `device/standby/countdown` |
| Hardware version, current input (diagnostic) | `sensor` | text | `device/identity/hw_version`, `audio/in/current_input` |
| Input gain, input select, bass, mid, treble, output level SPL (non-subwoofer only; confirmed by testing not to be writable, diagnostic) | `sensor` | dB or text | `ui/input_gain`, `ui/input_select`, `ui/bass_gain`, `ui/mid_gain`, `ui/treble_gain`, `ui/output_level` |
| Input clipping | `binary_sensor` | – | `m/in/clip` |
| Warning (diagnostic) | `binary_sensor` | – | `warnings` |
| Save settings* (default: disabled, confirmed by testing to be non-functional) | `button` | – | `device/save_settings` |
| Restore factory defaults (default: disabled, two-step confirmation) | `button` | – | `device/restore` |
| Create backup (all known values except live measurements) | `button` | – | – |
| Run device discovery (diagnostic) | `button` | – | – |

\* **Only** on the KH 80 / KH 150 / KH 120 II – according to the khtool
documentation not available on the KH 750 DSP. The integration detects the
model automatically during setup and hides these entities for the KH 750 DSP.

### Additional entities only on a detected subwoofer (KH 750 DSP)

The KH 750 DSP has two additional bass-management outputs (`out1`/`out2`) for
connected satellite loudspeakers. All entities listed below are created **only**
if `KH 750` was detected as the model during setup (the device only identifies
itself as `KH 750` over SSC, without "DSP" – the integration accepts both
spellings).

| Entity | Type | Range | SSC path |
|---|---|---|---|
| Output 1/2 level (default: disabled) | `number` | 0–120 dB | `audio/out1/level`, `audio/out2/level` |
| Output 1/2 delay (default: disabled) | `number` | 0–1000 samples | `audio/out1/delay`, `audio/out2/delay` |
| Output 1/2 mute (default: disabled) | `switch` | – | `audio/out1/mute`, `audio/out2/mute` |
| Device temperature (default: enabled, unit Kelvin) | `sensor` | °C | `device/temperature` |
| Output level (live) (default: disabled) | `sensor` | dB | `m/out/level` |
| Output label (main output, diagnostic) | `sensor` | text | `audio/out/label` |
| Output 1/2 label, output 1/2 loudspeaker (default: disabled, diagnostic, read-only) | `sensor` | text ("Not assigned" instead of "UNKNOWN") | `audio/out1/label`, `audio/out1/loudspeaker`, `audio/out2/label`, `audio/out2/loudspeaker` |
| Subwoofer input gain, low cut, output level, phase, phase inversion, bass management, channel B input mode (confirmed by testing not to be writable, diagnostic) | `sensor` | dB or text | `ui/subwoofer_input_gain`, `ui/subwoofer_low_cut`, `ui/subwoofer_output_level`, `ui/subwoofer_phase`, `ui/subwoofer_phase_inversion`, `ui/bass_management`, `ui/channel_b_input_mode` |
| Output clipping (default: disabled) | `binary_sensor` | – | `m/out/clip` |
| Digital bypass (diagnostic) | `binary_sensor` | – | `audio/digital_bypass` |
| Auto standby status (read-only – confirmed by hardware testing not to be writable on the KH 750 DSP, see "Known limitations") | `binary_sensor` | – | `device/standby/enabled` |

Entities that are disabled by default can be enabled manually under
**Settings → Devices & Services → [device] → Entities**.

## Polling

All values of a loudspeaker are fetched every 30 seconds – and specifically
**each value individually** (one leaf path per SSC message), not as a combined
message and not as a container query. The reason (confirmed by two hardware
tests): the firmware rejects both a combined message containing several leaves
(as soon as one of them is unknown) and a container query such as
`{"device":null}` entirely. Only individual, concrete, existing leaf paths work
reliably. If the device rejects a single value (e.g. `dimm` on the KH 120 II),
only that one is skipped – the remaining values are still updated.

**Standby behaviour (important, not a bug):** when a loudspeaker (especially
the KH 750 DSP) goes into standby, it apparently also shuts down its network
stack and stops responding to SSC requests. All entities then correctly become
**"unavailable"** – this is the behaviour recommended by Home Assistant
(`CoordinatorEntity` automatically marks entities as unavailable as soon as a
poll cycle fails) and is not a bug in the integration. As soon as the device
wakes from standby, Home Assistant detects this again automatically – the
waiting time for that is dictated by HA's built-in retry mechanism: 5s → 10s →
20s → 40s → 80s between the first attempts, and every 80 seconds after that
(or, with a very long standby and HA ≥ 2026.6, up to every 10 minutes). This
is not a behaviour of this integration but Home Assistant's core mechanism for
`ConfigEntryNotReady`.

## Known limitations

- Auto standby is only non-writable on the KH 750 DSP (it works on the
  KH 120 II). Hence: KH 120 II → `switch`, KH 750 DSP → `binary_sensor`.
- Input switching (KH 120 II, `ui/input_select` and `audio/in/interface`)
  remains of unverified writability – disabled by default or read-only.
- Control mode (`ui/control_mode`) always remains disabled: switching to
  `LOCAL` could cut network control off from the device.
- Factory reset (`device/restore`) has a two-step safety confirmation: the
  first press only arms it, a second press within 30s triggers it.
  Alternatively via a physical switch sequence on the device itself:
  - **KH 80 DSP:** while booting (logo still red), move the SETTINGS switch
    up/down repeatedly until the logo briefly flickers pink.
  - **KH 750 DSP:** while booting (power LED steady red), move the
    AUTO STANDBY/STANDBY switch up/down repeatedly.
  - **KH 120 II / KH 150:** while booting (logo flashing), move the CONTROL
    switch up/down repeatedly until the logo briefly flashes red/pink quickly.

  (Source: [Neumann KH Monitor Troubleshooting](https://help.neumann.com/hc/en-us/articles/39978248897049-KH-Monitor-Troubleshooting))
- The following KH 750 values are confirmed by testing not to be writable and
  are therefore read-only: bass management, channel B input mode, subwoofer
  input gain/low cut/output level/phase/phase inversion.
- The following KH 120 II values are likewise confirmed by testing not to be
  writable: input gain, input select, mid, treble, output level (SPL),
  "save settings".
- `dimm` (`audio/out/dimm`) does not exist on the KH 120 II – the entity
  remains (for other models) and shows "unknown" there.
- "Identify" is a switch, not an auto-stop button: the flashing only stops by
  itself after several minutes.
- Device temperature (KH 750 DSP): reported in Kelvin, converted to °C.

## Name memory, backup & device discovery

Three separate, persistent stores (independent of config entries, so they also
survive deleting and re-adding a device; all in `storage.py`), one entry per
serial number:

- **`.storage/neumann_kh_names`**: the most recently used name. When setting up
  again via automatic discovery, the name field is pre-filled from this.
- **`.storage/neumann_kh_backups`**: the result of the `Create backup` button –
  all known values except live measurements, including the rarely polled
  settings and the full EQ of every container (gain, boost, frequency, Q and
  filter type per band). The notification links to a
  download served by an authenticated endpoint; the link is signed and valid
  for one hour. Nothing is written to disk.
- **`.storage/neumann_kh_discovery`**: the result of the `Run device discovery`
  button (diagnostic) – combines our known paths with a best-effort attempt via
  `osc/schema` + `osc/limits` (optional SSC methods; not every firmware supports
  them – if this part fails, it is simply left empty). The serial number is
  redacted in this export (only the last 3 characters remain visible).

Backup and discovery only ever run manually via their respective buttons –
there is no automatic triggering in the background.

The selection list in the automatic scan also contains a "🔄 Search again"
entry to restart the network search directly from the list.

## EQ (parametric equalizer)

A complete 1:1 mapping of all EQ parameters (type/frequency/gain/boost/Q/
enabled per band) would come to roughly 800 entities on the KH 750 DSP – no
longer manageable. Deliberately reduced to container level instead:

- **One on/off switch per EQ container** (`switch`, category "Configuration",
  enabled by default): switches **all bands of that container together**
  (writes the same value into the entire `enabled` array). Shows "on" as soon
  as at least one band is active.
- **One "Reset to neutral" button per EQ container** (`button`, category
  "Configuration", enabled by default): sets gain **and** boost of all bands in
  that container to 0 dB. Frequency/Q/type/enabled remain unchanged – a true
  factory reset is not possible, as there are no documented default frequencies
  per band.

All container names deliberately start with "EQ" (e.g. "EQ2 Main output",
"EQ Crossover Output 1") so that they appear grouped together alphabetically in
the configuration section.

**Containers covered:**

| Model | Container | Bands |
|---|---|---|
| KH 120 II (non-subwoofer) | `audio/out/eq2` | 10 |
| KH 120 II (non-subwoofer) | `audio/out/eq3` | 20 |
| KH 750 DSP (main output) | `audio/out/eq2` | 10 |
| KH 750 DSP (out1/out2 each) | `eq1` (crossover) | 2 |
| KH 750 DSP (out1/out2 each) | `eq2` | 10 |
| KH 750 DSP (out1/out2 each) | `eq3` | 10 |

That adds up to **4 entities** (KH 120 II: 2 containers × switch+button) or
**14 entities** (KH 750 DSP: 7 containers × switch+button).
