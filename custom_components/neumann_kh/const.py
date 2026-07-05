"""Konstanten für die Neumann KH (SSC) Integration.

Dieses Modul sammelt alle festen Werte an einer Stelle:
- Domain-Name der Integration
- Konfigurationsschlüssel (config_entry.data / options)
- Standardwerte (Port, Update-Intervall)
- SSC-Adresspfade (siehe Sennheiser Sound Control Protocol Spezifikation
  und https://github.com/schwinn/khtool)
- Produktnamen, die zusätzliche Funktionen unterstützen (Logo-Helligkeit,
  save_settings) - laut khtool nur KH 80 / KH 150 / KH 120 II, NICHT KH 750 DSP.
"""

from __future__ import annotations

DOMAIN = "neumann_kh"

# --- Config Entry Keys ---------------------------------------------------
CONF_INTERFACE = "interface"  # Netzwerk-Interface für IPv6 Link-Local Scope-ID
CONF_SERIAL = "serial"  # Seriennummer, dient als eindeutige ID
CONF_MODEL = "model"  # Produktname (z. B. "KH 120 II", "KH 750 DSP")

# --- Standardwerte ---------------------------------------------------------
DEFAULT_PORT = 45  # SSC-Standardport lt. Sennheiser-Spezifikation
DEFAULT_TIMEOUT = 3.0  # Sekunden, Verbindungs-/Antwort-Timeout
DEFAULT_QUERY_SETTLE = 0.4  # Sekunden Ruhezeit, bis Mehrfachantworten als vollständig gelten
UPDATE_INTERVAL_SECONDS = 30

# Modelle, die Logo-Helligkeit + save_settings unterstützen (lt. khtool-Doku)
MODELS_WITH_LOGO_AND_SAVE = ("KH 80", "KH 150", "KH 120", "KH 120 II")

# --- Zeroconf/mDNS-Gerätesuche ---------------------------------------------
# Lt. SSC-Spezifikation muss jedes SSC-Gerät, das TCP unterstützt, sich per
# DNS-SD unter diesem Dienst-Typ bekannt machen.
SSC_ZEROCONF_SERVICE_TYPE = "_ssc._tcp.local."
SCAN_DURATION_SECONDS = 4.0

# --- SSC Adresspfade (als Tupel von Schlüsseln, für verschachteltes JSON) ---
PATH_IDENTITY_VENDOR = ("device", "identity", "vendor")
PATH_IDENTITY_PRODUCT = ("device", "identity", "product")
PATH_IDENTITY_SERIAL = ("device", "identity", "serial")
PATH_IDENTITY_VERSION = ("device", "identity", "version")

PATH_SAVE_SETTINGS = ("device", "save_settings")

PATH_LOGO_BRIGHTNESS = ("ui", "logo", "brightness")

PATH_INPUT_GAIN = ("audio", "in", "gain")
PATH_INPUT_PHASE_INVERT = ("audio", "in", "phase_invert")

PATH_OUTPUT_LEVEL = ("audio", "out", "level")
PATH_OUTPUT_DIMM = ("audio", "out", "dimm")
PATH_OUTPUT_DELAY = ("audio", "out", "delay")
PATH_OUTPUT_MUTE = ("audio", "out", "mute")
PATH_OUTPUT_SOLO = ("audio", "out", "solo")
PATH_OUTPUT_PHASE_CORRECTION = ("audio", "out", "phase_correction")

# Live-Pegelmessung über den "expert"-Meter-Zweig (siehe khtool --expert Beispiel)
PATH_METER_INPUT_LEVEL = ("m", "audio")

# Wertebereiche lt. khtool --help
LEVEL_MIN = 0.0
LEVEL_MAX = 120.0
DIMM_MIN = -120.0
DIMM_MAX = 0.0
DELAY_MIN = 0
DELAY_MAX = 3360
BRIGHTNESS_MIN = 0
BRIGHTNESS_MAX = 100
