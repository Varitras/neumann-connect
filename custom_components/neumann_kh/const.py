"""Konstanten der Neumann KH (SSC) Integration: Domain, Config-Keys,
Standardwerte, SSC-Adresspfade, Modell-Listen und Wertebereiche.
"""

from __future__ import annotations

DOMAIN = "neumann_kh"

# --- Config Entry Keys ---------------------------------------------------
CONF_INTERFACE = "interface"  # Netzwerk-Interface für IPv6 Link-Local Scope-ID
CONF_SERIAL = "serial"  # Seriennummer, dient als eindeutige ID
CONF_MODEL = "model"  # Produktname (z. B. "KH 120 II", "KH 750")
CONF_FIRMWARE_VERSION = "firmware_version"  # z. B. "1_7_3", nur informativ (sw_version)

# --- Standardwerte ---------------------------------------------------------
DEFAULT_PORT = 45  # SSC-Standardport
DEFAULT_TIMEOUT = 3.0  # Sekunden, Verbindungs-/Antwort-Timeout
DEFAULT_QUERY_SETTLE = 0.4  # Sekunden Ruhezeit bis Mehrfachantworten als vollständig gelten
UPDATE_INTERVAL_SECONDS = 30
POLL_CYCLE_TIMEOUT_SECONDS = 25.0  # Zeitlimit für einen kompletten Poll-Zyklus

# Modelle mit Logo-Helligkeit + save_settings
MODELS_WITH_LOGO_AND_SAVE = ("KH 80", "KH 150", "KH 120", "KH 120 II")

# Modelle mit Subwoofer-/Bass-Management-Funktionen (out1/out2, Temperatur,
# Ausgangs-Metering, Subwoofer-UI-Werte)
MODELS_WITH_SUBWOOFER_FEATURES = ("KH 750",)

# --- Zeroconf/mDNS-Gerätesuche ---------------------------------------------
SSC_ZEROCONF_SERVICE_TYPE = "_ssc._tcp.local."
SCAN_DURATION_SECONDS = 4.0

# --- SSC Adresspfade (Tupel von Schlüsseln, für verschachteltes JSON) -------
PATH_IDENTITY_PRODUCT = ("device", "identity", "product")
PATH_IDENTITY_SERIAL = ("device", "identity", "serial")
PATH_IDENTITY_VERSION = ("device", "identity", "version")

PATH_SAVE_SETTINGS = ("device", "save_settings")
PATH_LOGO_BRIGHTNESS = ("ui", "logo", "brightness")

# Eingangsverstärkung (nur Nicht-Subwoofer-Modelle) - nur lesbar.
PATH_INPUT_GAIN = ("ui", "input_gain")

PATH_OUTPUT_LEVEL = ("audio", "out", "level")
PATH_OUTPUT_DIMM = ("audio", "out", "dimm")  # nicht bei allen Modellen vorhanden
PATH_OUTPUT_DELAY = ("audio", "out", "delay")
PATH_OUTPUT_MUTE = ("audio", "out", "mute")
PATH_OUTPUT_LABEL = ("audio", "out", "label")  # nur KH 750
PATH_OUTPUT_PHASE_INVERSION = ("audio", "out", "phaseinversion")  # nur Nicht-Subwoofer

# Ausgangspegel als feste SPL-Stufe (94/100/108/114 dB SPL), nur lesbar
# (Rückseiten-Schalter). Nur Nicht-Subwoofer-Modelle.
PATH_UI_OUTPUT_LEVEL = ("ui", "output_level")

# Live-Pegelmessung: Liste von Werten (ein Wert pro Kanal), kein Einzelwert.
PATH_METER_INPUT_LEVEL = ("m", "in", "level")
PATH_METER_CLIP = ("m", "in", "clip")

# Auto-Standby: nur bei Nicht-Subwoofer-Modellen schreibbar; bei der KH 750
# per Test nicht schreibbar (siehe binary_sensor.py).
PATH_STANDBY_ENABLED = ("device", "standby", "enabled")
PATH_STANDBY_AUTO_TIME = ("device", "standby", "auto_standby_time")
PATH_STANDBY_LEVEL = ("device", "standby", "level")
PATH_STANDBY_COUNTDOWN = ("device", "standby", "countdown")  # nur lesbar

# Gerät identifizieren (Logo/LEDs blinken). Als Schalter umgesetzt, da das
# Blinken nicht zuverlässig schnell von selbst aufhört.
PATH_IDENTIFY = ("device", "identification", "visual")

# Klangregler (nur Nicht-Subwoofer-Modelle). String-Enums mit festen Stufen
# -> `select`, nicht `number`. Nur Bass Gain ist schreibbar.
PATH_UI_BASS_GAIN = ("ui", "bass_gain")
BASS_GAIN_OPTIONS = ("-6", "-4", "-2", "0")
PATH_UI_MID_GAIN = ("ui", "mid_gain")  # nur lesbar
PATH_UI_TREBLE_GAIN = ("ui", "treble_gain")  # nur lesbar

# Eingangsauswahl/-Interface: Schreibbarkeit unverifiziert, standardmäßig
# deaktiviert (input_interface) bzw. nur lesbar (input_select).
PATH_INPUT_SELECT = ("ui", "input_select")  # nur lesbar
PATH_INPUT_INTERFACE_TYPE = ("audio", "in", "interface")
INPUT_INTERFACE_OPTIONS = ("ANALOG ONLY", "DIGITAL ONLY", "DIGITAL DISCARDS ANALOG")

# Steuerungsmodus NETWORK/LOCAL. Standardmäßig deaktiviert: Wechsel zu LOCAL
# kappt die Netzwerksteuerung bis zur manuellen Rückstellung am Gerät.
PATH_UI_CONTROL_MODE = ("ui", "control_mode")
CONTROL_MODE_OPTIONS = ("NETWORK", "LOCAL")

# Reine Info-/Diagnose-Pfade (nur lesbar)
PATH_IDENTITY_HW_VERSION = ("device", "identity", "hw_version")
PATH_INPUT_CURRENT = ("audio", "in", "current_input")
PATH_WARNINGS = ("warnings",)  # Top-Level-Schlüssel, keine Verschachtelung

PATH_DEVICE_NAME = ("device", "name")
DEVICE_NAME_MAX_LENGTH = 52

# Werkseinstellungen wiederherstellen. Mit Zwei-Schritt-Sicherheitsabfrage
# umgesetzt (siehe button.py) - destruktive Aktion an echter Hardware.
PATH_RESTORE = ("device", "restore")
RESTORE_FACTORY_DEFAULTS_VALUE = "FACTORY_DEFAULTS"

# --- Subwoofer-spezifisch (nur KH 750) -------------------------------------
PATH_DIGITAL_BYPASS = ("audio", "digital_bypass")  # nur lesbar

# Gerätetemperatur, Einheit Kelvin -> Umrechnung in sensor.py.
PATH_DEVICE_TEMPERATURE = ("device", "temperature")

# Ausgangs-Pegelmessung/Clip (Pendant zu PATH_METER_INPUT_LEVEL/CLIP).
PATH_METER_OUTPUT_LEVEL = ("m", "out", "level")
PATH_METER_OUTPUT_CLIP = ("m", "out", "clip")

# Bass-Management/Routing: nur lesbar (per Test bestätigt nicht schreibbar).
PATH_UI_BASS_MANAGEMENT = ("ui", "bass_management")
PATH_UI_CHANNEL_B_INPUT_MODE = ("ui", "channel_b_input_mode")

# Subwoofer-Kalibrierung: nur lesbar (per Test bestätigt nicht schreibbar).
PATH_UI_SUB_INPUT_GAIN = ("ui", "subwoofer_input_gain")
PATH_UI_SUB_LOW_CUT = ("ui", "subwoofer_low_cut")
PATH_UI_SUB_OUTPUT_LEVEL = ("ui", "subwoofer_output_level")
PATH_UI_SUB_PHASE = ("ui", "subwoofer_phase")
PATH_UI_SUB_PHASE_INVERSION = ("ui", "subwoofer_phase_inversion")

# Zusätzliche Bass-Management-Ausgänge (für angeschlossene Zusatzlautsprecher).
# Label nur lesbar; Loudspeaker-Zuordnung schreibbar (siehe select.py).
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

# Pfade, die der Coordinator bei jedem Poll-Zyklus einzeln abfragt (siehe
# coordinator.py: Sammelnachrichten/Container-Abfragen werden abgelehnt).
POLL_PATHS = (
    PATH_INPUT_GAIN,
    PATH_OUTPUT_LEVEL,
    PATH_OUTPUT_DIMM,
    PATH_OUTPUT_DELAY,
    PATH_OUTPUT_MUTE,
    PATH_OUTPUT_PHASE_INVERSION,
    PATH_UI_OUTPUT_LEVEL,
    PATH_METER_INPUT_LEVEL,
    PATH_METER_CLIP,
    PATH_STANDBY_ENABLED,
    PATH_STANDBY_AUTO_TIME,
    PATH_STANDBY_LEVEL,
    PATH_STANDBY_COUNTDOWN,
    PATH_IDENTIFY,
    PATH_UI_BASS_GAIN,
    PATH_UI_MID_GAIN,
    PATH_UI_TREBLE_GAIN,
    PATH_INPUT_SELECT,
    PATH_UI_CONTROL_MODE,
    PATH_DEVICE_NAME,
    PATH_RESTORE,
    PATH_IDENTITY_HW_VERSION,
    PATH_INPUT_CURRENT,
    PATH_INPUT_INTERFACE_TYPE,
    PATH_WARNINGS,
)

# Zusätzliche Pfade, nur für Modelle mit Subwoofer-Funktionen.
SUBWOOFER_POLL_PATHS = (
    PATH_DIGITAL_BYPASS,
    PATH_OUTPUT_LABEL,
    PATH_DEVICE_TEMPERATURE,
    PATH_METER_OUTPUT_LEVEL,
    PATH_METER_OUTPUT_CLIP,
    PATH_UI_BASS_MANAGEMENT,
    PATH_UI_CHANNEL_B_INPUT_MODE,
    PATH_UI_SUB_INPUT_GAIN,
    PATH_UI_SUB_LOW_CUT,
    PATH_UI_SUB_OUTPUT_LEVEL,
    PATH_UI_SUB_PHASE,
    PATH_UI_SUB_PHASE_INVERSION,
    PATH_OUT1_LEVEL,
    PATH_OUT1_DELAY,
    PATH_OUT1_MUTE,
    PATH_OUT1_LABEL,
    PATH_OUT1_LOUDSPEAKER,
    PATH_OUT2_LEVEL,
    PATH_OUT2_DELAY,
    PATH_OUT2_MUTE,
    PATH_OUT2_LABEL,
    PATH_OUT2_LOUDSPEAKER,
)

# --- Wertebereiche -----------------------------------------------------
LEVEL_MIN = 0.0
LEVEL_MAX = 120.0
DIMM_MIN = -120.0
DIMM_MAX = 0.0

# Delay-Bereich ist modellabhängig.
DELAY_MIN = 0
DELAY_MAX_DEFAULT = 5760  # KH 120 II und andere Nicht-Subwoofer-Modelle
DELAY_MAX_SUBWOOFER = 1000  # KH 750: Hauptausgang, out1, out2

BRIGHTNESS_MIN = 0
BRIGHTNESS_MAX = 125

STANDBY_AUTO_TIME_MIN = 1
STANDBY_AUTO_TIME_MAX = 240
STANDBY_LEVEL_MIN = -80.0
STANDBY_LEVEL_MAX = -55.0
STANDBY_LEVEL_UNIT = "dBu"
