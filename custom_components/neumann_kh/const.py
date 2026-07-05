"""Konstanten für die Neumann KH (SSC) Integration.

Dieses Modul sammelt alle festen Werte an einer Stelle:
- Domain-Name der Integration
- Konfigurationsschlüssel (config_entry.data / options)
- Standardwerte (Port, Update-Intervall)
- SSC-Adresspfade (siehe Sennheiser Sound Control Protocol Spezifikation
  und https://github.com/schwinn/khtool)
- Produktnamen, die zusätzliche Funktionen unterstützen (Logo-Helligkeit,
  save_settings) - laut khtool nur KH 80 / KH 150 / KH 120 II, NICHT KH 750 DSP.
- Produktnamen mit Subwoofer-spezifischen Funktionen (Bass-Management-
  Ausgänge, Subwoofer-UI-Werte) - per echtem khtool-Dump für KH 750 bestätigt.
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
# Lt. SSC-Spezifikation muss jedes SSC-Gerät, das TCP unterstützt, sich per
# DNS-SD unter diesem Dienst-Typ bekannt machen.
SSC_ZEROCONF_SERVICE_TYPE = "_ssc._tcp.local."
SCAN_DURATION_SECONDS = 4.0

# --- SSC Adresspfade (als Tupel von Schlüsseln, für verschachteltes JSON) ---
#
# WICHTIG: Ursprünglich basierten diese Pfade auf dem KH-80-Beispiel aus der
# khtool-Dokumentation. Echte `khtool -q`-Dumps einer KH 120 II (Firmware
# 1_7_3) und einer KH 750 (Firmware 2_1_2) haben gezeigt, dass mehrere Pfade
# anders heißen bzw. modellabhängig gar nicht existieren. Die Pfade unten
# sind gegen diese realen Dumps verifiziert.
#
# Zur Abfrage-Strategie (zwei gescheiterte Zwischenschritte, bevor der
# aktuelle funktionierte): (1) Eine Sammelnachricht mit mehreren Blättern
# scheitert komplett, sobald auch nur EIN Blatt darin unbekannt ist
# ("message not understood", Fehler 400). (2) Eine Container-Abfrage wie
# {"device":null} wird von der Firmware ebenfalls nicht unterstützt
# ("address not found", Fehler 404). Es funktionieren NUR einzelne, konkrete,
# existierende Blattpfade - siehe POLL_PATHS/SUBWOOFER_POLL_PATHS unten und
# coordinator.py.
PATH_IDENTITY_VENDOR = ("device", "identity", "vendor")
PATH_IDENTITY_PRODUCT = ("device", "identity", "product")
PATH_IDENTITY_SERIAL = ("device", "identity", "serial")
PATH_IDENTITY_VERSION = ("device", "identity", "version")

PATH_SAVE_SETTINGS = ("device", "save_settings")

PATH_LOGO_BRIGHTNESS = ("ui", "logo", "brightness")

# Eingangsverstärkung: liegt bei der KH 120 II unter "ui", NICHT unter
# "audio/in/gain" (das war die falsche KH-80-Annahme).
PATH_INPUT_GAIN = ("ui", "input_gain")

PATH_OUTPUT_LEVEL = ("audio", "out", "level")
PATH_OUTPUT_DIMM = ("audio", "out", "dimm")  # nicht im -q-Dump enthalten - evtl. modellabhängig, siehe README
PATH_OUTPUT_DELAY = ("audio", "out", "delay")
PATH_OUTPUT_MUTE = ("audio", "out", "mute")
# Es gibt nur EINE Phasenumkehr für den gesamten (Haupt-)Ausgang, keine
# getrennte Ein-/Ausgangs-Phasenumkehr (die alte "phase_correction"/
# "phase_invert"-Unterscheidung existiert bei der KH 120 II nicht).
PATH_OUTPUT_PHASE_INVERSION = ("audio", "out", "phaseinversion")

# Live-Pegelmessung: liegt unter "m/in/level" und liefert eine LISTE von
# Werten (ein Wert pro Kanal, z. B. [-122.8, -122.8]), kein Einzelwert.
PATH_METER_INPUT_LEVEL = ("m", "in", "level")

# Clip-Indikator: liegt unter "m/in/clip", ebenfalls eine LISTE (ein
# Bool-Wert pro Kanal), analog zu PATH_METER_INPUT_LEVEL.
PATH_METER_CLIP = ("m", "in", "clip")

# Auto-Standby (Energiesparfunktion). Wertebereiche für auto_standby_time
# (Minuten) und level (dB-Schwellwert) sind NICHT offiziell dokumentiert -
# die Grenzen unten sind konservative Schätzwerte basierend auf beobachteten
# Standardwerten (KH 120 II: 30 min / -60 dB; KH 750: 19 min / -65 dB). Das
# Gerät lehnt zu weit außerhalb liegende Werte im Zweifel einfach ab (siehe
# SSCDeviceError).
PATH_STANDBY_ENABLED = ("device", "standby", "enabled")
PATH_STANDBY_AUTO_TIME = ("device", "standby", "auto_standby_time")
PATH_STANDBY_LEVEL = ("device", "standby", "level")
PATH_STANDBY_COUNTDOWN = ("device", "standby", "countdown")  # nur lesbar, Restzeit bis Standby

# Gerät identifizieren: True lässt lt. SSC-Konvention (siehe Sennheiser SSC
# Developer's Guide, "identification"-Container) das Logo/die LEDs kurz
# blinken, um das physische Gerät zu finden.
PATH_IDENTIFY = ("device", "identification", "visual")

# Klangregler. ACHTUNG: Die Firmware liefert diese Werte als JSON-STRINGS
# (z. B. "0"), nicht als Zahlen - siehe value_is_string in number.py.
# Wertebereich NICHT offiziell dokumentiert und NICHT gegen echte Hardware
# verifiziert (bewusst vorsichtig gewählt).
PATH_UI_BASS_GAIN = ("ui", "bass_gain")
PATH_UI_MID_GAIN = ("ui", "mid_gain")
PATH_UI_TREBLE_GAIN = ("ui", "treble_gain")

# Reine Info-/Diagnose-Pfade (nur lesbar)
PATH_DEVICE_NAME = ("device", "name")
PATH_IDENTITY_HW_VERSION = ("device", "identity", "hw_version")
PATH_INPUT_CURRENT = ("audio", "in", "current_input")
PATH_INPUT_INTERFACE_TYPE = ("audio", "in", "interface")
PATH_UI_CONTROL_MODE = ("ui", "control_mode")
PATH_WARNINGS = ("warnings",)  # Top-Level-Schlüssel, keine Verschachtelung

# --- Subwoofer-spezifisch (nur KH 750, siehe MODELS_WITH_SUBWOOFER_FEATURES) -
#
# Gerätetemperatur: Rohwert im -q-Dump ist "307" (plain Integer, keine
# erkennbare Einheit dokumentiert). ANNAHME (nicht verifiziert): Kelvin,
# da 307 K ≈ 34,85 °C ein plausibler Wert für die Elektronik im Gehäuse ist.
# Falls diese Annahme falsch ist, zeigt der Sensor einen falschen °C-Wert -
# aber keine Fehlfunktion, da rein lesend.
PATH_DEVICE_TEMPERATURE = ("device", "temperature")

# Ausgangs-Pegelmessung/Clip (Pendant zu PATH_METER_INPUT_LEVEL/CLIP, aber
# für die Ausgänge) - im KH-750-Dump 3 Kanäle (Hauptausgang + out1 + out2).
PATH_METER_OUTPUT_LEVEL = ("m", "out", "level")
PATH_METER_OUTPUT_CLIP = ("m", "out", "clip")

# Bass-Management/Routing-Infos (nur lesbar, Optionen nicht dokumentiert)
PATH_UI_BASS_MANAGEMENT = ("ui", "bass_management")
PATH_UI_CHANNEL_B_INPUT_MODE = ("ui", "channel_b_input_mode")

# Subwoofer-Klangregler/Kalibrierung. subwoofer_input_gain und
# subwoofer_low_cut sind ECHTE Zahlen (kein String), subwoofer_phase und
# subwoofer_phase_inversion dagegen STRINGS (wie die Klangregler oben).
# Wertebereiche NICHT offiziell dokumentiert.
PATH_UI_SUB_INPUT_GAIN = ("ui", "subwoofer_input_gain")
PATH_UI_SUB_LOW_CUT = ("ui", "subwoofer_low_cut")
# subwoofer_output_level ist ein STRING-ENUM ("94"/"100"/"108"/"114") -
# passend zu den dokumentierten festen SPL-Stufen anderer KH-Modelle
# (siehe z. B. KH 120A: 94/100/108/114 dB SPL bei 0 dBu Eingang).
PATH_UI_SUB_OUTPUT_LEVEL = ("ui", "subwoofer_output_level")
SUB_OUTPUT_LEVEL_OPTIONS = ("94", "100", "108", "114")
PATH_UI_SUB_PHASE = ("ui", "subwoofer_phase")  # String, vermutlich Grad (0-180)
PATH_UI_SUB_PHASE_INVERSION = ("ui", "subwoofer_phase_inversion")  # String "0"/"1"

# Zusätzliche Bass-Management-Ausgänge (für angeschlossene Zusatzlautsprecher,
# analog/digital durchgeschleift). Je Kanal: Pegel, Delay, Mute, Label
# (Anzeigename) und zugewiesener Lautsprechertyp.
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
# (jeweils eine eigene, spezifische SSC-Nachricht - siehe coordinator.py für
# die Begründung: weder Sammelnachrichten noch Container-Abfragen wie
# {"device":null} werden von der getesteten Firmware unterstützt, NUR
# einzelne, konkrete, existierende Blattpfade funktionieren zuverlässig).
# Geräte-Identität (Hersteller/Modell/Seriennummer/Version) wird bewusst
# NICHT wiederholt gepollt - die wird bereits einmalig beim Einrichten
# abgefragt und in den Config-Entry-Daten gespeichert.
POLL_PATHS = (
    PATH_INPUT_GAIN,
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
    PATH_UI_BASS_GAIN,
    PATH_UI_MID_GAIN,
    PATH_UI_TREBLE_GAIN,
    PATH_DEVICE_NAME,
    PATH_IDENTITY_HW_VERSION,
    PATH_INPUT_CURRENT,
    PATH_INPUT_INTERFACE_TYPE,
    PATH_UI_CONTROL_MODE,
    PATH_WARNINGS,
)

# Zusätzliche Pfade, NUR für Modelle mit Subwoofer-Funktionen abgefragt
# (siehe MODELS_WITH_SUBWOOFER_FEATURES) - hält die Poll-Zyklen anderer
# Modelle kurz und vermeidet unnötige (wenn auch harmlose, da einzeln
# abgefangene) Fehlanfragen.
SUBWOOFER_POLL_PATHS = (
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

# Wertebereiche lt. khtool --help
LEVEL_MIN = 0.0
LEVEL_MAX = 120.0
DIMM_MIN = -120.0
DIMM_MAX = 0.0
DELAY_MIN = 0
DELAY_MAX = 3360
BRIGHTNESS_MIN = 0
BRIGHTNESS_MAX = 100

# Unten: NICHT offiziell dokumentiert, NICHT gegen echte Hardware
# verifiziert - konservativ geschätzt anhand beobachteter Standardwerte.
# Das Gerät lehnt außerhalb seines tatsächlichen Bereichs liegende Werte
# einfach ab (SSCDeviceError -> klare HA-Fehlermeldung, kein Risiko).
STANDBY_AUTO_TIME_MIN = 1
STANDBY_AUTO_TIME_MAX = 90
STANDBY_LEVEL_MIN = -90.0
STANDBY_LEVEL_MAX = 0.0
TONE_GAIN_MIN = -12.0
TONE_GAIN_MAX = 12.0

# Subwoofer-Wertebereiche - ebenfalls unverifiziert, siehe README.
SUB_INPUT_GAIN_MIN = -12.0
SUB_INPUT_GAIN_MAX = 12.0
SUB_LOW_CUT_MIN = -12.0
SUB_LOW_CUT_MAX = 12.0
SUB_PHASE_MIN = 0.0
SUB_PHASE_MAX = 180.0
