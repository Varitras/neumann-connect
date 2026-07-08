"""Vollständige Geräte-Discovery für Backup/Diagnose bei unbekannten Geräten.

Zwei kombinierte Methoden:
1. Garantierter Teil: alle uns bekannten Pfade (POLL_PATHS + SUBWOOFER_POLL_PATHS)
   einzeln abfragen - funktioniert immer, liefert aber nur bereits bekannte Werte.
2. Best-effort-Teil: `osc/schema` (Befehlsbaum ermitteln) + `osc/limits` (Typ/
   Bereich/Optionen/writeable je Endpunkt) - laut SSC-Spezifikation OPTIONALE
   Methoden, die nicht jede Firmware unterstützt. Schlägt dieser Teil fehl,
   bleibt er einfach leer, der garantierte Teil ist davon unberührt.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from ._util import build_nested, deep_merge, extract
from .const import POLL_PATHS, SUBWOOFER_POLL_PATHS
from .ssc_client import SSCClient, SSCConnectionError, SSCDeviceError, SSCTimeoutError

_LOGGER = logging.getLogger(__name__)

# Schutz gegen einen unerwartet riesigen oder endlosen Befehlsbaum, falls ein
# Gerät osc/schema doch unterstützt.
_MAX_SCHEMA_NODES = 500
_MAX_SCHEMA_DEPTH = 10
# Gesamt-Zeitlimit für den Best-effort-Schema-Teil (osc/schema + osc/limits).
# Bei bis zu 500 Knoten × einzelner Anfrage könnte das sonst sehr lange laufen.
_SCHEMA_DISCOVERY_TIMEOUT = 30.0


async def async_discover_all_values(client: SSCClient) -> dict[str, Any]:
    """Führt beide Discovery-Methoden aus und liefert ein zusammengeführtes Ergebnis."""
    return {
        "known_paths": await _async_query_known_paths(client),
        "schema_limits": await _async_discover_via_schema(client),
    }


async def _async_query_known_paths(client: SSCClient) -> dict[str, Any]:
    """Fragt alle bekannten Pfade einzeln ab (garantierter Teil, wie coordinator.py)."""
    result: dict[str, Any] = {}
    all_paths = list(POLL_PATHS) + list(SUBWOOFER_POLL_PATHS)
    for path in all_paths:
        try:
            value = await client.get(path)
        except SSCDeviceError:
            continue
        except (SSCConnectionError, SSCTimeoutError):
            raise
        except Exception:  # noqa: BLE001 - ein Bug bei einem Pfad soll die Discovery nicht abbrechen
            _LOGGER.exception("Unerwarteter Fehler bei Discovery-Pfad %s, überspringe", path)
            continue
        if value is not None:
            deep_merge(result, build_nested(path, value))
    return result


async def _async_discover_via_schema(client: SSCClient) -> dict[str, Any]:
    """Best-effort: osc/schema rekursiv abfragen, pro Blatt osc/limits abfragen.

    Beide Methoden sind laut SSC-Spezifikation optional - viele Geräte lehnen
    sie mit Fehler 400/404 ab. In diesem Fall bleibt das Ergebnis leer.
    """
    result: dict[str, Any] = {}
    node_count = 0

    async def _walk(path: tuple[str, ...], depth: int) -> None:
        nonlocal node_count
        if depth > _MAX_SCHEMA_DEPTH or node_count > _MAX_SCHEMA_NODES:
            return

        request = {"osc": {"schema": None}} if not path else {"osc": {"schema": [build_nested(path, None)]}}
        try:
            response = await client.request(request)
        except SSCDeviceError:
            return
        except (SSCConnectionError, SSCTimeoutError):
            raise
        except Exception:  # noqa: BLE001 - Discovery ist best-effort, nie abbrechen
            _LOGGER.debug("osc/schema für Pfad %s fehlgeschlagen", path, exc_info=True)
            return

        schema = extract(response, ("osc", "schema"))
        if not schema:
            return
        # Bundled- oder unbundled-Antwortform (siehe SSC-Spezifikation) - beide
        # sind eine Liste von Address Trees, wir suchen den Teilbaum an `path`.
        entries = schema if isinstance(schema, list) else [schema]
        subtree: dict | None = None
        for entry in entries:
            candidate = extract(entry, path) if path else entry
            if isinstance(candidate, dict):
                subtree = candidate
                break
        if subtree is None:
            return

        for key, child_value in subtree.items():
            if node_count > _MAX_SCHEMA_NODES:
                return
            node_count += 1
            child_path = path + (key,)
            if child_value == {}:
                # Container - eine Ebene tiefer weitersuchen.
                await _walk(child_path, depth + 1)
            else:
                # Blatt (Wert war `null`) - Metadaten per osc/limits abfragen.
                limits = await _async_query_limits(client, child_path)
                if limits is not None:
                    deep_merge(result, build_nested(child_path, limits))

    try:
        await asyncio.wait_for(_walk((), 0), timeout=_SCHEMA_DISCOVERY_TIMEOUT)
    except asyncio.TimeoutError:
        _LOGGER.debug(
            "osc/schema-Discovery nach %.0fs abgebrochen (Teilergebnis wird verwendet)",
            _SCHEMA_DISCOVERY_TIMEOUT,
        )
    except (SSCConnectionError, SSCTimeoutError):
        raise
    except Exception:  # noqa: BLE001 - Best-effort, darf die Discovery nie zum Absturz bringen
        _LOGGER.debug("osc/schema-Discovery abgebrochen", exc_info=True)

    return result


async def _async_query_limits(client: SSCClient, path: tuple[str, ...]) -> Any:
    """Fragt osc/limits für einen einzelnen Pfad ab (siehe Moduldocstring)."""
    request = {"osc": {"limits": [build_nested(path, None)]}}
    try:
        response = await client.request(request)
    except SSCDeviceError:
        return None
    except (SSCConnectionError, SSCTimeoutError):
        raise
    except Exception:  # noqa: BLE001 - Best-effort
        _LOGGER.debug("osc/limits für Pfad %s fehlgeschlagen", path, exc_info=True)
        return None

    limits = extract(response, ("osc", "limits"))
    if not limits:
        return None
    entries = limits if isinstance(limits, list) else [limits]
    for entry in entries:
        candidate = extract(entry, path)
        if candidate is not None:
            return candidate
    return None
