"""Full device discovery for backup/diagnostics with unknown devices.

Two combined methods:
1. Guaranteed part: query every path known to us for the model (fast, slow and
   EQ paths, see backup_export.known_paths_for_model) individually - always
   works, but only returns already known values.
2. Best-effort part: `osc/schema` (determine command tree) + `osc/limits` (type/
   range/options/writeable per endpoint) - OPTIONAL per the SSC specification,
   answered by both tested firmwares (KH 120 II 1_7_3, KH 750 2_1_2). If this
   part fails, it simply stays empty; the guaranteed part is unaffected.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from ._util import build_nested, deep_merge, extract
from .backup_export import async_read_paths, known_paths_for_model
from .ssc_client import SSCClient

_LOGGER = logging.getLogger(__name__)

# Protection against an unexpectedly huge or endless command tree. Both are
# compared with ">=", so they mean
# what they say: at most this many nodes, at most this many levels below the
# root. The node count used to be compared with ">" and allowed one more.
_MAX_SCHEMA_NODES = 500
_MAX_SCHEMA_DEPTH = 10
# Overall time limit for the best-effort schema part (osc/schema + osc/limits).
# With up to 500 nodes × individual request this could otherwise run very long.
_SCHEMA_DISCOVERY_TIMEOUT = 30.0
# Named so the client returns as soon as the answer is in. Without it every
# reply sat out the settle window (0.4 s), and on a KH 750 the walk ran into
# the time limit above with less than half of the tree.
_SCHEMA_REPLY = ("osc", "schema")
_LIMITS_REPLY = ("osc", "limits")


class DiscoveryTimeoutError(Exception):
    """The guaranteed part did not finish within DEVICE_ACTION_TIMEOUT_SECONDS."""


async def async_discover_all_values(client: SSCClient, model: str | None = None) -> dict[str, Any]:
    """Run both discovery methods and return a merged result."""
    return {
        "known_paths": await async_read_paths(
            client, known_paths_for_model(model), DiscoveryTimeoutError
        ),
        "schema_limits": await _async_discover_via_schema(client),
    }


async def _fetch_schema_subtree(client: SSCClient, path: tuple[str, ...]) -> dict[str, Any] | None:
    """Ask the device for the children of `path`, or None if it will not say.

    Best-effort by contract: osc/schema is optional per the SSC specification,
    so another firmware may reject it. Every failure - a rejection, a lost
    connection, a malformed answer - means the same thing to the caller, so
    they all return None rather than propagating. The known-paths part of the
    discovery has already been collected and must survive this.
    """
    request = (
        {"osc": {"schema": None}} if not path else {"osc": {"schema": [build_nested(path, None)]}}
    )
    try:
        response = await client.request(request, expect_path=_SCHEMA_REPLY)
    except Exception:
        _LOGGER.debug("osc/schema for path %s failed", path, exc_info=True)
        return None

    schema = extract(response, ("osc", "schema"))
    if not schema:
        return None

    # Bundled or unbundled response form (see SSC specification) - both are a
    # list of address trees; we look for the subtree at `path`.
    entries = schema if isinstance(schema, list) else [schema]
    for entry in entries:
        candidate = extract(entry, path) if path else entry
        if isinstance(candidate, dict):
            return candidate
    return None


async def _async_discover_via_schema(client: SSCClient) -> dict[str, Any]:
    """Best-effort: query osc/schema recursively, query osc/limits per leaf.

    Both methods are optional per the SSC specification; a device that rejects
    them leaves the result empty.
    """
    result: dict[str, Any] = {}
    node_count = 0

    async def _walk(path: tuple[str, ...], depth: int) -> None:
        nonlocal node_count
        if depth >= _MAX_SCHEMA_DEPTH or node_count >= _MAX_SCHEMA_NODES:
            return

        subtree = await _fetch_schema_subtree(client, path)
        if subtree is None:
            return

        for key, child_value in subtree.items():
            if node_count >= _MAX_SCHEMA_NODES:
                return
            node_count += 1
            child_path = path + (key,)
            if child_value == {}:
                # Container - continue searching one level deeper.
                await _walk(child_path, depth + 1)
                continue
            # Leaf (value was `null`) - query metadata via osc/limits.
            limits = await _async_query_limits(client, child_path)
            if limits is not None:
                deep_merge(result, build_nested(child_path, limits))

    try:
        await asyncio.wait_for(_walk((), 0), timeout=_SCHEMA_DISCOVERY_TIMEOUT)
    except TimeoutError:
        _LOGGER.debug(
            "osc/schema discovery aborted after %.0fs (using partial result)",
            _SCHEMA_DISCOVERY_TIMEOUT,
        )
    except Exception:
        # Includes connection loss: the guaranteed part has already been
        # collected and is worth keeping.
        _LOGGER.debug("osc/schema discovery aborted", exc_info=True)

    return result


async def _async_query_limits(client: SSCClient, path: tuple[str, ...]) -> Any:
    """Query osc/limits for a single path (see module docstring)."""
    request = {"osc": {"limits": [build_nested(path, None)]}}
    try:
        response = await client.request(request, expect_path=_LIMITS_REPLY)
    except Exception:
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
