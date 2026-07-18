"""Constants of the Neumann KH (SSC) integration: domain, config keys,
default values, SSC address paths, model lists and value ranges.
"""

from __future__ import annotations

DOMAIN = "neumann_kh"

# --- Config Entry Keys ---------------------------------------------------
CONF_INTERFACE = "interface"  # Network interface for IPv6 link-local scope ID
CONF_SERIAL = "serial"  # Serial number, used as unique ID
CONF_MODEL = "model"  # Product name (e.g. "KH 120 II", "KH 750")
CONF_VENDOR = "vendor"  # Manufacturer as reported by the device
CONF_FIRMWARE_VERSION = "firmware_version"  # e.g. "1_7_3", informational only (sw_version)

# Both test devices report this verbatim as device/identity/vendor (KH 120 II
# on firmware 1_7_3, KH 750 on 2_1_2). Used as the fallback for devices that
# do not expose the field, and to recognise a Neumann device during setup.
DEFAULT_VENDOR = "Georg Neumann GmbH"
VENDOR_MARKER_NEUMANN = "neumann"

# --- Default values --------------------------------------------------------
DEFAULT_PORT = 45  # SSC default port
DEFAULT_TIMEOUT = 3.0  # Seconds, connection/response timeout
DEFAULT_QUERY_SETTLE = 0.4  # Seconds of quiet time until multiple responses count as complete
UPDATE_INTERVAL_SECONDS = 30
POLL_CYCLE_TIMEOUT_SECONDS = 25.0  # Time limit for a complete poll cycle

# Models with logo brightness + save_settings
# Models with logo brightness + save_settings. "KH 80"/"KH 150"/"KH 120 II"
# are confirmed (KH 120 II via real hardware test, the others per
# khtool documentation). The "DSP"/"AES67" variants are UNVERIFIED
# additions (unknown which exact product name these devices actually
# report over SSC) - analogous to the KH 750/KH 750 DSP finding that
# the official product name does not necessarily match the SSC reported value.
# "KH 120" (without "II") is likewise unverified - the original
# KH 120 from 2010, per research, probably had no DSP yet; kept
# here anyway (harmless if this value never occurs).
MODELS_WITH_LOGO_AND_SAVE = (
    "KH 80",
    "KH 80 DSP",
    "KH 150",
    "KH 150 AES67",
    "KH 120",
    "KH 120 II",
    "KH 120 II AES67",
)

# Models with subwoofer/bass management features (out1/out2, temperature,
# output metering, subwoofer UI values)
# Officially the product is called "KH 750 DSP", but the device reports
# itself over SSC only as "KH 750" (confirmed via real hardware dump) - both
# variants are accepted in case another firmware/unit reports the
# full name.
MODELS_WITH_SUBWOOFER_FEATURES = ("KH 750", "KH 750 DSP")

# --- Zeroconf/mDNS device discovery ----------------------------------------
SSC_ZEROCONF_SERVICE_TYPE = "_ssc._tcp.local."
SCAN_DURATION_SECONDS = 4.0

# --- SSC address paths (tuple of keys, for nested JSON) ---------------------
PATH_IDENTITY_PRODUCT = ("device", "identity", "product")
PATH_IDENTITY_VENDOR = ("device", "identity", "vendor")
PATH_IDENTITY_SERIAL = ("device", "identity", "serial")
PATH_IDENTITY_VERSION = ("device", "identity", "version")

PATH_SAVE_SETTINGS = ("device", "save_settings")
PATH_LOGO_BRIGHTNESS = ("ui", "logo", "brightness")

# Input gain (non-subwoofer models only) - read-only.
PATH_INPUT_GAIN = ("ui", "input_gain")

PATH_OUTPUT_LEVEL = ("audio", "out", "level")
PATH_OUTPUT_DIMM = ("audio", "out", "dimm")  # not present on all models
PATH_OUTPUT_DELAY = ("audio", "out", "delay")
PATH_OUTPUT_MUTE = ("audio", "out", "mute")
PATH_OUTPUT_LABEL = ("audio", "out", "label")  # KH 750 only
PATH_OUTPUT_PHASE_INVERSION = ("audio", "out", "phaseinversion")  # non-subwoofer only

# Output level as a fixed SPL step (94/100/108/114 dB SPL), read-only
# (rear-panel switch). Non-subwoofer models only.
PATH_UI_OUTPUT_LEVEL = ("ui", "output_level")

# Live level metering: list of values (one value per channel), not a single value.
PATH_METER_INPUT_LEVEL = ("m", "in", "level")
PATH_METER_CLIP = ("m", "in", "clip")

# Auto standby: writable only on non-subwoofer models; on the KH 750
# not writable per test (see binary_sensor.py).
PATH_STANDBY_ENABLED = ("device", "standby", "enabled")
PATH_STANDBY_AUTO_TIME = ("device", "standby", "auto_standby_time")
PATH_STANDBY_LEVEL = ("device", "standby", "level")
PATH_STANDBY_COUNTDOWN = ("device", "standby", "countdown")  # read-only

# Identify device (logo/LEDs blink). Implemented as a switch, since the
# blinking does not reliably stop quickly on its own.
PATH_IDENTIFY = ("device", "identification", "visual")

# Tone controls (non-subwoofer models only). String enums with fixed steps
# -> `select`, not `number`. Only bass gain is writable.
PATH_UI_BASS_GAIN = ("ui", "bass_gain")  # read-only (KH 120 II)
PATH_UI_MID_GAIN = ("ui", "mid_gain")  # read-only
PATH_UI_TREBLE_GAIN = ("ui", "treble_gain")  # read-only

# input_interface: confirmed writable (KH 120 II + KH 750 DSP), enabled
# by default. input_select in contrast is read-only.
PATH_INPUT_SELECT = ("ui", "input_select")  # read-only
PATH_INPUT_INTERFACE_TYPE = ("audio", "in", "interface")
INPUT_INTERFACE_OPTIONS = ("ANALOG ONLY", "DIGITAL ONLY", "DIGITAL DISCARDS ANALOG")

# Control mode NETWORK/LOCAL. Disabled by default: switching to LOCAL
# cuts off network control until manually reset on the device.
PATH_UI_CONTROL_MODE = ("ui", "control_mode")
CONTROL_MODE_OPTIONS = ("NETWORK", "LOCAL")

# Pure info/diagnostic paths (read-only)
PATH_IDENTITY_HW_VERSION = ("device", "identity", "hw_version")
PATH_INPUT_CURRENT = ("audio", "in", "current_input")
PATH_WARNINGS = ("warnings",)  # Top-level key, no nesting

PATH_DEVICE_NAME = ("device", "name")
DEVICE_NAME_MAX_LENGTH = 52

# Restore factory defaults. Implemented with a two-step confirmation
# (see button.py) - destructive action on real hardware.
PATH_RESTORE = ("device", "restore")
RESTORE_FACTORY_DEFAULTS_VALUE = "FACTORY_DEFAULTS"

# --- Subwoofer-specific (KH 750 only) --------------------------------------
PATH_DIGITAL_BYPASS = ("audio", "digital_bypass")  # read-only

# Device temperature, unit Kelvin -> conversion in sensor.py.
PATH_DEVICE_TEMPERATURE = ("device", "temperature")

# Output level metering/clip (counterpart to PATH_METER_INPUT_LEVEL/CLIP).
PATH_METER_OUTPUT_LEVEL = ("m", "out", "level")
PATH_METER_OUTPUT_CLIP = ("m", "out", "clip")

# Bass management/routing: read-only (confirmed not writable per test).
PATH_UI_BASS_MANAGEMENT = ("ui", "bass_management")
PATH_UI_CHANNEL_B_INPUT_MODE = ("ui", "channel_b_input_mode")

# Subwoofer calibration: read-only (confirmed not writable per test).
PATH_UI_SUB_INPUT_GAIN = ("ui", "subwoofer_input_gain")
PATH_UI_SUB_LOW_CUT = ("ui", "subwoofer_low_cut")
PATH_UI_SUB_OUTPUT_LEVEL = ("ui", "subwoofer_output_level")
PATH_UI_SUB_PHASE = ("ui", "subwoofer_phase")
PATH_UI_SUB_PHASE_INVERSION = ("ui", "subwoofer_phase_inversion")

# Additional bass management outputs (for connected extra speakers).
# Label read-only; loudspeaker assignment writable (see select.py).
PATH_OUT1_LEVEL = ("audio", "out1", "level")
PATH_OUT1_DELAY = ("audio", "out1", "delay")
PATH_OUT1_MUTE = ("audio", "out1", "mute")
PATH_OUT1_LABEL = ("audio", "out1", "label")
PATH_OUT1_LOUDSPEAKER = ("audio", "out1", "loudspeaker")

PATH_OUT2_LEVEL = ("audio", "out2", "level")
PATH_OUT2_DELAY = ("audio", "out2", "delay")
PATH_OUT2_MUTE = ("audio", "out2", "mute")
PATH_OUT2_LABEL = ("audio", "out2", "label")
PATH_OUT2_LOUDSPEAKER = ("audio", "out2", "loudspeaker")

# Paths the coordinator queries individually on every poll cycle (see
# coordinator.py: collective messages/container queries are rejected).
# Contains all values that can actually change at runtime.
POLL_PATHS = (
    PATH_OUTPUT_LEVEL,
    PATH_OUTPUT_DIMM,
    PATH_OUTPUT_DELAY,
    PATH_OUTPUT_MUTE,
    PATH_OUTPUT_PHASE_INVERSION,
    PATH_METER_INPUT_LEVEL,
    PATH_METER_CLIP,
    PATH_STANDBY_ENABLED,
    PATH_STANDBY_AUTO_TIME,
    PATH_STANDBY_LEVEL,
    PATH_STANDBY_COUNTDOWN,
    PATH_IDENTIFY,
    PATH_UI_CONTROL_MODE,
    PATH_WARNINGS,
)

# Rarely/never changing values (identity, static configuration, fixed
# rear-panel switches, device name): queried only every SLOW_POLL_EVERY_N_CYCLES
# to reduce the poll scope. User actions on writable
# fields below (e.g. device name) apply the confirmed value
# immediately themselves anyway - the slow poll is only the safeguard that
# a value changed externally (via MA1) eventually gets picked up.
SLOW_POLL_PATHS = (
    PATH_INPUT_GAIN,
    PATH_UI_OUTPUT_LEVEL,
    PATH_UI_BASS_GAIN,
    PATH_UI_MID_GAIN,
    PATH_UI_TREBLE_GAIN,
    PATH_INPUT_SELECT,
    PATH_DEVICE_NAME,
    PATH_RESTORE,
    PATH_IDENTITY_HW_VERSION,
    PATH_INPUT_CURRENT,
    PATH_INPUT_INTERFACE_TYPE,
)

# How often (in poll cycles) the SLOW_POLL_PATHS are queried as well.
# 10 × 30s = every 5 minutes.
SLOW_POLL_EVERY_N_CYCLES = 10

# Additional paths, only for models with subwoofer features. The
# live measurements (metering, clip) and mutable output values stay in the
# fast poll; static diagnostic/label values go into the slow one.
SUBWOOFER_POLL_PATHS = (
    PATH_METER_OUTPUT_LEVEL,
    PATH_METER_OUTPUT_CLIP,
    PATH_DEVICE_TEMPERATURE,
    PATH_OUT1_LEVEL,
    PATH_OUT1_DELAY,
    PATH_OUT1_MUTE,
    PATH_OUT2_LEVEL,
    PATH_OUT2_DELAY,
    PATH_OUT2_MUTE,
)

# Rarely changing subwoofer values (only every SLOW_POLL_EVERY_N_CYCLES).
SUBWOOFER_SLOW_POLL_PATHS = (
    PATH_DIGITAL_BYPASS,
    PATH_OUTPUT_LABEL,
    PATH_UI_BASS_MANAGEMENT,
    PATH_UI_CHANNEL_B_INPUT_MODE,
    PATH_UI_SUB_INPUT_GAIN,
    PATH_UI_SUB_LOW_CUT,
    PATH_UI_SUB_OUTPUT_LEVEL,
    PATH_UI_SUB_PHASE,
    PATH_UI_SUB_PHASE_INVERSION,
    PATH_OUT1_LABEL,
    PATH_OUT1_LOUDSPEAKER,
    PATH_OUT2_LABEL,
    PATH_OUT2_LOUDSPEAKER,
)

# --- Value ranges ------------------------------------------------------
LEVEL_MIN = 0.0
LEVEL_MAX = 120.0
DIMM_MIN = -120.0
DIMM_MAX = 0.0

# Delay range is model-dependent.
DELAY_MIN = 0
DELAY_MAX_DEFAULT = 5760  # KH 120 II and other non-subwoofer models
DELAY_MAX_SUBWOOFER = 1000  # KH 750: main output, out1, out2

BRIGHTNESS_MIN = 0
BRIGHTNESS_MAX = 125

STANDBY_AUTO_TIME_MIN = 1
STANDBY_AUTO_TIME_MAX = 240
STANDBY_LEVEL_MIN = -80.0
STANDBY_LEVEL_MAX = -55.0
STANDBY_LEVEL_UNIT = "dBu"
