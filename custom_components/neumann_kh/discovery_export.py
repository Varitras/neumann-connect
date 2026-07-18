"""Full device discovery for backup/diagnostics with unknown devices.

Two combined methods:
1. Guaranteed part: query every path known to us for the model (fast, slow and
   EQ paths, see backup_export.known_paths_for_model) individually - always
   works, but only returns already known values.
2. Best-effort part: `osc/schema` (determine command tree) + `osc/limits` (type/
   range/options/writeable per endpoint) - per the SSC specification OPTIONAL
   methods that not every firmware supports. If this part fails, it simply
   stays empty; the guaranteed part is unaffected.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from ._util import build_nested, deep_merge, extract
from .backup_export import known_paths_for_model
from .ssc_client import SSCClient, SSCConnectionError, SSCDeviceError, SSCTimeoutError

_LOGGER = logging.getLogger(__name__)

# Protection against an unexpectedly huge or endless command tree in case a
# device does support osc/schema.
_MAX_SCHEMA_NODES = 500
_MAX_SCHEMA_DEPTH = 10
# Overall time limit for the best-effort schema part (osc/schema + osc/limits).
# With up to 500 nodes × individual request this could otherwise run very long.
_SCHEMA_DISCOVERY_TIMEOUT = 30.0


async def async_discover_all_values(
    client: SSCClient, model: str | None = None
) -> dict[str, Any]:
    """Run both discovery methods and return a merged result."""
    return {
        "known_paths": await _async_query_known_paths(client, model),
        "schema_limits": await _async_discover_via_schema(client),
    }


async def _async_query_known_paths(
    client: SSCClient, model: str | None
) -> dict[str, Any]:
    """Query all known paths individually (guaranteed part, like coordinator.py)."""
    result: dict[str, Any] = {}
    for path in known_paths_for_model(model):
        try:
            value = await client.get(path)
        except SSCDeviceError:
            continue
        except (SSCConnectionError, SSCTimeoutError):
            raise
        except Exception:  # noqa: BLE001 - a bug at one path should not abort the discovery
            _LOGGER.exception("Unexpected error at discovery path %s, skipping", path)
            continue
        if value is not None:
            deep_merge(result, build_nested(path, value))
    return result


async def _async_discover_via_schema(client: SSCClient) -> dict[str, Any]:
    """Best-effort: query osc/schema recursively, query osc/limits per leaf.

    Both methods are optional per the SSC specification - many devices reject
    them with error 400/404. In that case the result stays empty.
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
        except (SSCDeviceError, SSCConnectionError, SSCTimeoutError):
            # Best-effort by contract: a device that does not support
            # osc/schema, or drops the connection while walking it, must not
            # cost us the known values already collected.
            _LOGGER.debug("osc/schema for path %s failed", path, exc_info=True)
            return
        except Exception:  # noqa: BLE001 - discovery is best-effort, never abort
            _LOGGER.debug("osc/schema for path %s failed", path, exc_info=True)
            return

        schema = extract(response, ("osc", "schema"))
        if not schema:
            return
        # Bundled or unbundled response form (see SSC specification) - both are
        # a list of address trees; we look for the subtree at `path`.
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
                # Container - continue searching one level deeper.
                await _walk(child_path, depth + 1)
            else:
                # Leaf (value was `null`) - query metadata via osc/limits.
                limits = await _async_query_limits(client, child_path)
                if limits is not None:
                    deep_merge(result, build_nested(child_path, limits))

    try:
        await asyncio.wait_for(_walk((), 0), timeout=_SCHEMA_DISCOVERY_TIMEOUT)
    except asyncio.TimeoutError:
        _LOGGER.debug(
            "osc/schema discovery aborted after %.0fs (using partial result)",
            _SCHEMA_DISCOVERY_TIMEOUT,
        )
    except Exception:  # noqa: BLE001 - best-effort, must never crash the discovery
        # Includes connection loss: the guaranteed part has already been
        # collected and is worth keeping.
        _LOGGER.debug("osc/schema discovery aborted", exc_info=True)

    return result


async def _async_query_limits(client: SSCClient, path: tuple[str, ...]) -> Any:
    """Query osc/limits for a single path (see module docstring)."""
    request = {"osc": {"limits": [build_nested(path, None)]}}
    try:
        response = await client.request(request)
    except Exception:  # noqa: BLE001 - best-effort, incl. connection loss
        _LOGGER.debug("osc/limits for path %s failed", path, exc_info=True)
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
