"""Konstanten für die Neumann KH (SSC) Integration.

Dieses Modul sammelt alle festen Werte an einer Stelle:
- Domain-Name der Integration
- Konfigurationsschlüssel (config_entry.data / options)
- Standardwerte (Port, Update-Intervall)
- SSC-Adresspfade (siehe Sennheiser Sound Control Protocol Spezifikation
  und https://github.com/schwinn/khtool)
- Produktnamen, die zusätzliche Funktionen unterstützen (Logo-Helligkeit,
  save_settings) - laut khtool nur KH 80 / KH 150 / KH 120 II, NICHT KH 750.
- Produktnamen mit Subwoofer-spezifischen Funktionen - per echtem
  khtool-Dump für KH 750 bestätigt.

WICHTIGE QUELLE für Wertebereiche/Optionen: khtools eigene interne
"khtool_commands.json" (vom Nutzer bereitgestellt) enthält strukturierte
Metadaten (Typ, schreibbar ja/nein, Min/Max, exakte Optionen) pro Modell/
Firmware-Version. Das ist eine deutlich zuverlässigere Quelle als reines
Raten - ABER: Ein echter Hardware-Test hat gezeigt, dass diese Datei nicht
IMMER mit dem tatsächlichen Geräteverhalten übereinstimmt (`ui/auto_standby`
ist dort als schreibbar gelistet, wurde von echter Hardware aber mit
"message not understood" abgelehnt). Deshalb: Wertebereiche/Optionen aus
dieser Datei werden übernommen (geringes Risiko - ein falscher Wert wird
einfach abgelehnt), aber ob ein Pfad grundsätzlich SCHREIBBAR ist, wird nur
dann als gesichert behandelt, wenn zusätzlich ein echter Hardware-Test dafür
vorliegt oder das Schreiben unkritisch ist (Ablehnung = klare Fehlermeldung,
kein Risiko).
"""

from __future__ import annotations

DOMAIN = "neumann_kh"

# --- Config Entry Keys ---------------------------------------------------
CONF_INTERFACE = "interface"  # Netzwerk-Interface für IPv6 Link-Local Scope-ID
CONF_SERIAL = "serial"  # Seriennummer, dient als eindeutige ID
CONF_MODEL = "model"  # Produktname (z. B. "KH 120 II", "KH 750")
CONF_FIRMWARE_VERSION = "firmware_version"  # z. B. "1_7_3", nur informativ (sw_version)

# --- Standardwerte ---------------------------------------------------------
DEFAULT_PORT = 45  # SSC-Standardport lt. Sennheiser-Spezifikation
DEFAULT_TIMEOUT = 3.0  # Sekunden, Verbindungs-/Antwort-Timeout
DEFAULT_QUERY_SETTLE = 0.4  # Sekunden Ruhezeit, bis Mehrfachantworten als vollständig gelten
UPDATE_INTERVAL_SECONDS = 30
# Gesamt-Zeitlimit für einen kompletten Poll-Zyklus (alle Einzelabfragen
# zusammen). Verhindert, dass ein "hängendes" Gerät einen Poll-Zyklus
# beliebig lange blockiert - siehe coordinator.py.
POLL_CYCLE_TIMEOUT_SECONDS = 25.0

# Modelle, die Logo-Helligkeit + save_settings unterstützen (lt. khtool-Doku)
MODELS_WITH_LOGO_AND_SAVE = ("KH 80", "KH 150", "KH 120", "KH 120 II")

# Modelle mit Subwoofer-/Bass-Management-spezifischen Funktionen (zusätzliche
# Ausgangskanäle out1/out2, Subwoofer-UI-Werte, Temperatur, Ausgangs-Metering)
# - per echtem khtool-Dump einer KH 750 (Firmware 2_1_2) verifiziert.
MODELS_WITH_SUBWOOFER_FEATURES = ("KH 750",)

# --- Zeroconf/mDNS-Gerätesuche ---------------------------------------------
SSC_ZEROCONF_SERVICE_TYPE = "_ssc._tcp.local."
SCAN_DURATION_SECONDS = 4.0

# --- SSC Adresspfade (als Tupel von Schlüsseln, für verschachteltes JSON) ---
PATH_IDENTITY_VENDOR = ("device", "identity", "vendor")
PATH_IDENTITY_PRODUCT = ("device", "identity", "product")
PATH_IDENTITY_SERIAL = ("device", "identity", "serial")
PATH_IDENTITY_VERSION = ("device", "identity", "version")

PATH_SAVE_SETTINGS = ("device", "save_settings")

PATH_LOGO_BRIGHTNESS = ("ui", "logo", "brightness")

# Eingangsverstärkung: liegt bei der KH 120 II unter "ui", NICHT unter
# "audio/in/gain". Laut khtool_commands.json schreibbar, -15 bis 0 dB.
# Existiert laut Schema NUR bei Nicht-Subwoofer-Modellen (KH 750 hat
# stattdessen "subwoofer_input_gain").
PATH_INPUT_GAIN = ("ui", "input_gain")

PATH_OUTPUT_LEVEL = ("audio", "out", "level")
PATH_OUTPUT_DIMM = ("audio", "out", "dimm")  # nicht im -q-Dump enthalten - modellabhängig, siehe README
PATH_OUTPUT_DELAY = ("audio", "out", "delay")
PATH_OUTPUT_MUTE = ("audio", "out", "mute")
# Bezeichnung des Hauptausgangs (z. B. "SUBWOOFER") - laut Schema NUR bei
# der KH 750 vorhanden (im KH-120-II-Dump fehlt "audio/out/label" komplett).
PATH_OUTPUT_LABEL = ("audio", "out", "label")
# Es gibt nur EINE Phasenumkehr für den gesamten (Haupt-)Ausgang, keine
# getrennte Ein-/Ausgangs-Phasenumkehr. Existiert laut Schema NUR bei
# Nicht-Subwoofer-Modellen (KH 750 hat stattdessen "subwoofer_phase_inversion").
PATH_OUTPUT_PHASE_INVERSION = ("audio", "out", "phaseinversion")

# Ausgangspegel als feste SPL-Stufe (94/100/108/114 dB SPL), Pendant zu
# "subwoofer_output_level" beim Sub. Nur bei Nicht-Subwoofer-Modellen.
PATH_UI_OUTPUT_LEVEL = ("ui", "output_level")

# Live-Pegelmessung: liegt unter "m/in/level" und liefert eine LISTE von
# Werten (ein Wert pro Kanal, z. B. [-122.8, -122.8]), kein Einzelwert.
PATH_METER_INPUT_LEVEL = ("m", "in", "level")
PATH_METER_CLIP = ("m", "in", "clip")

# Auto-Standby (Energiesparfunktion). WICHTIG: `device/standby/enabled`
# steht laut khtool_commands.json zwar als "writeable: true", wurde aber per
# echtem Hardware-Test auf der KH 750 mit Fehler 405 ("method not allowed")
# abgelehnt. Ein alternativer Pfad ("ui/auto_standby") wurde ebenfalls real
# getestet und mit Fehler 400 ("message not understood") abgelehnt. Beide
# Tests zusammen zeigen: Auto-Standby ist auf der getesteten Firmware NICHT
# schreibbar - wird deshalb nur als binary_sensor (lesend) abgebildet.
PATH_STANDBY_ENABLED = ("device", "standby", "enabled")
PATH_STANDBY_AUTO_TIME = ("device", "standby", "auto_standby_time")
PATH_STANDBY_LEVEL = ("device", "standby", "level")
PATH_STANDBY_COUNTDOWN = ("device", "standby", "countdown")  # nur lesbar, Restzeit bis Standby

# Gerät identifizieren: True lässt das Logo/die LEDs blinken, um das
# physische Gerät zu finden. Per Hardware-Test bestätigt: Es hört von selbst
# wieder auf, aber erst nach mehreren Minuten (nicht ~10 Sekunden, wie die
# allgemeine SSC-Doku für andere Sennheiser-Geräte vermuten ließ) - daher als
# Schalter (An/Aus) statt als "Auto-Stopp"-Button umgesetzt.
PATH_IDENTIFY = ("device", "identification", "visual")

# Klangregler (KH 120 II). Laut khtool_commands.json STRING-Enums mit exakt
# vier festen Stufen (kein kontinuierlicher Bereich) - deshalb als `select`,
# nicht als `number` umgesetzt. Existieren laut Schema NUR bei
# Nicht-Subwoofer-Modellen.
PATH_UI_BASS_GAIN = ("ui", "bass_gain")
BASS_GAIN_OPTIONS = ("-6", "-4", "-2", "0")
PATH_UI_MID_GAIN = ("ui", "mid_gain")
MID_GAIN_OPTIONS = ("-6", "-4", "-2", "0")
PATH_UI_TREBLE_GAIN = ("ui", "treble_gain")
TREBLE_GAIN_OPTIONS = ("-2", "-1", "0", "1")

# Eingangsauswahl (nur Nicht-Subwoofer-Modelle). Laut Schema schreibbar -
# ABER: Sowohl "ui/input_select" als auch "audio/in/interface" wurden mit
# FALSCHEN Werten (AES3/Network/SPDIF) getestet und abgelehnt. Die laut
# khtool_commands.json tatsächlich gültigen Werte wurden noch nicht gegen
# echte Hardware verifiziert - deshalb standardmäßig deaktiviert.
PATH_INPUT_SELECT = ("ui", "input_select")
INPUT_SELECT_OPTIONS = ("MONO", "AES3 R", "AES3 L", "ANALOG")
PATH_INPUT_INTERFACE_TYPE = ("audio", "in", "interface")
INPUT_INTERFACE_OPTIONS = ("ANALOG ONLY", "DIGITAL ONLY", "DIGITAL DISCARDS ANALOG")

# Steuerungsmodus NETWORK/LOCAL. ACHTUNG - siehe README "Bekannte Grenzen":
# Ein Wechsel zu "LOCAL" könnte die Netzwerksteuerung (und damit diese
# Integration) komplett vom Gerät trennen, bis manuell am Gerät zurück auf
# NETWORK gestellt wird. Deshalb standardmäßig deaktiviert und mit
# Warnhinweis versehen, NICHT weil das Schreiben selbst technisch unsicher
# wäre, sondern wegen der möglichen Konsequenz.
PATH_UI_CONTROL_MODE = ("ui", "control_mode")
CONTROL_MODE_OPTIONS = ("NETWORK", "LOCAL")

# Reine Info-/Diagnose-Pfade (nur lesbar)
PATH_IDENTITY_HW_VERSION = ("device", "identity", "hw_version")
PATH_INPUT_CURRENT = ("audio", "in", "current_input")
PATH_WARNINGS = ("warnings",)  # Top-Level-Schlüssel, keine Verschachtelung

# Gerätename: laut khtool_commands.json schreibbar (String, max. 52 Zeichen).
PATH_DEVICE_NAME = ("device", "name")
DEVICE_NAME_MAX_LENGTH = 52

# Werkseinstellungen wiederherstellen. Laut khtool_commands.json bestätigt:
# gültige Werte sind "" (Leerstring, Ruhezustand) oder "FACTORY_DEFAULTS".
# TROTZ dieser Bestätigung bewusst mit Zwei-Schritt-Sicherheitsabfrage
# umgesetzt (siehe button.py) - ein Werksreset ist eine destruktive Aktion
# an echter, teurer Hardware, unabhängig davon, ob der Wert dokumentiert ist.
PATH_RESTORE = ("device", "restore")
RESTORE_FACTORY_DEFAULTS_VALUE = "FACTORY_DEFAULTS"

# --- Subwoofer-spezifisch (nur KH 750, siehe MODELS_WITH_SUBWOOFER_FEATURES) -
#
# Digitaler Bypass-Modus - nur lesbar laut Schema (kein "writeable"-Flag).
PATH_DIGITAL_BYPASS = ("audio", "digital_bypass")

# Gerätetemperatur: Laut khtool_commands.json Einheit "K" (Kelvin) -
# bestätigt unsere vorherige Annahme.
PATH_DEVICE_TEMPERATURE = ("device", "temperature")

# Ausgangs-Pegelmessung/Clip (Pendant zu PATH_METER_INPUT_LEVEL/CLIP, aber
# für die Ausgänge) - im KH-750-Dump 3 Kanäle (Hauptausgang + out1 + out2).
PATH_METER_OUTPUT_LEVEL = ("m", "out", "level")
PATH_METER_OUTPUT_CLIP = ("m", "out", "clip")

# Bass-Management/Routing. Laut khtool_commands.json schreibbar mit festen
# Optionen - ABER standardmäßig deaktiviert, da ein falscher Wert die
# Ausgangsroutung des gesamten Systems durcheinanderbringen könnte (siehe
# README).
PATH_UI_BASS_MANAGEMENT = ("ui", "bass_management")
BASS_MANAGEMENT_OPTIONS = ("DISABLED", "ACTIVE")
PATH_UI_CHANNEL_B_INPUT_MODE = ("ui", "channel_b_input_mode")
CHANNEL_B_INPUT_MODE_OPTIONS = (
    "LFE-Mode II (>80Hz -> Output B)",
    "LFE-Mode I (<120Hz)",
    "Ext.BM LFE (fullrange)",
    "STEREO (right)",
)

# Subwoofer-Kalibrierung. input_gain/low_cut sind ECHTE Zahlen (kein
# String), phase/phase_inversion dagegen STRING-Enums mit festen Stufen
# (kein kontinuierlicher Bereich) - deshalb `select`, nicht `number`.
PATH_UI_SUB_INPUT_GAIN = ("ui", "subwoofer_input_gain")
PATH_UI_SUB_LOW_CUT = ("ui", "subwoofer_low_cut")
PATH_UI_SUB_OUTPUT_LEVEL = ("ui", "subwoofer_output_level")
SUB_OUTPUT_LEVEL_OPTIONS = ("94", "100", "108", "114")
PATH_UI_SUB_PHASE = ("ui", "subwoofer_phase")
SUB_PHASE_OPTIONS = ("0", "-45", "-90", "-135")
PATH_UI_SUB_PHASE_INVERSION = ("ui", "subwoofer_phase_inversion")
SUB_PHASE_INVERSION_OPTIONS = ("0", "-180")

# Zusätzliche Bass-Management-Ausgänge (für angeschlossene Zusatzlautsprecher,
# analog/digital durchgeschleift). Je Kanal: Pegel, Delay, Mute, Label
# (Anzeigename, nur lesbar) und zugewiesener Lautsprechertyp (laut Schema
# OHNE "writeable"-Flag, wird deshalb ebenfalls nur lesend abgebildet).
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

# Blattpfade, die der Coordinator bei jedem Poll-Zyklus EINZELN abfragt
# (jeweils eine eigene, spezifische SSC-Nachricht - siehe coordinator.py).
# Geräte-Identität wird bewusst NICHT wiederholt gepollt - die wird bereits
# einmalig beim Einrichten abgefragt und in den Config-Entry-Daten
# gespeichert.
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

# Zusätzliche Pfade, NUR für Modelle mit Subwoofer-Funktionen abgefragt.
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
# Bestätigt durch khtool_commands.json (khtools interne, strukturierte
# Metadaten-Datenbank) - siehe Moduldocstring zur Zuverlässigkeit dieser Quelle.
LEVEL_MIN = 0.0
LEVEL_MAX = 120.0
DIMM_MIN = -120.0
DIMM_MAX = 0.0

# Delay-Bereich ist MODELLABHÄNGIG unterschiedlich:
# KH 120 II Hauptausgang: 0-5760 Samples; KH 750 (Haupt/out1/out2): 0-1000.
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

# ui/input_gain (Nicht-Subwoofer-Modelle)
INPUT_GAIN_MIN = -15.0
INPUT_GAIN_MAX = 0.0

# ui/subwoofer_input_gain / subwoofer_low_cut (KH 750)
SUB_INPUT_GAIN_MIN = -12.0
SUB_INPUT_GAIN_MAX = 2.0
SUB_LOW_CUT_MIN = -12.0
SUB_LOW_CUT_MAX = 0.0
