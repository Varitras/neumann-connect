"""Tests for the best-effort osc/schema walk.

This part was at 73% coverage with nothing exercising the walk itself, which
only came to light after it had already been restructured. The tests below
describe what the walk has to do: follow containers, ask osc/limits for
leaves, and treat every kind of refusal as "this device will not tell us".
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

pytest.importorskip("homeassistant")

from custom_components.neumann_kh import discovery_export
from custom_components.neumann_kh._util import build_nested
from custom_components.neumann_kh.discovery_export import (
    _async_discover_via_schema,
    _fetch_schema_subtree,
)
from custom_components.neumann_kh.ssc_client import SSCDeviceError


class _SchemaClient:
    """Answers osc/schema from a canned tree and osc/limits with a marker."""

    def __init__(self, tree: dict[str, Any], bundled: bool = True) -> None:
        self.tree = tree
        self.bundled = bundled
        self.limits_asked: list[tuple[str, ...]] = []

    @staticmethod
    def _path_of(request: dict[str, Any]) -> tuple[str, ...]:
        """The address the request asks about, as a path tuple."""
        node = request["osc"]
        payload = node.get("schema") or node.get("limits")
        if payload is None:
            return ()
        node = payload[0] if isinstance(payload, list) else payload
        path: list[str] = []
        while isinstance(node, dict) and node:
            key = next(iter(node))
            path.append(key)
            node = node[key]
        return tuple(path)

    def _level_at(self, path: tuple[str, ...]) -> dict[str, Any]:
        """One level of the tree, the way a device announces it.

        Containers are reported as an empty dict and leaves as null; the
        children of a container only appear when that path is asked for. The
        first version of this fake handed out whole subtrees at once, which no
        device does - and the walk then treated every container as a leaf.
        """
        node: Any = self.tree
        for key in path:
            node = node[key]
        return {
            key: {} if isinstance(value, dict) else None
            for key, value in node.items()
        }

    async def request(self, payload: dict[str, Any]) -> dict[str, Any]:
        path = self._path_of(payload)
        if "limits" in payload["osc"]:
            self.limits_asked.append(path)
            return {"osc": {"limits": [build_nested(path, {"type": "Number"})]}}

        wrapped = build_nested(path, self._level_at(path)) if path else self._level_at(path)
        return {"osc": {"schema": [wrapped] if self.bundled else wrapped}}


_TREE = {"device": {"identity": {"product": None}, "name": None}}


async def test_the_walk_follows_containers_and_asks_limits_for_leaves():
    client = _SchemaClient(_TREE)

    result = await _async_discover_via_schema(client)

    assert client.limits_asked == [("device", "identity", "product"), ("device", "name")]
    assert result["device"]["identity"]["product"] == {"type": "Number"}
    assert result["device"]["name"] == {"type": "Number"}


async def test_the_unbundled_response_form_is_understood():
    """The specification allows the tree with or without a surrounding list."""
    client = _SchemaClient(_TREE, bundled=False)

    result = await _async_discover_via_schema(client)

    assert result["device"]["name"] == {"type": "Number"}


@pytest.mark.parametrize(
    "answer",
    [
        SSCDeviceError("no such method"),
        RuntimeError("something else entirely"),
    ],
)
async def test_a_device_that_refuses_the_schema_yields_nothing(answer):
    """Every refusal means the same to the caller, so none may propagate.

    The guaranteed part of the discovery has already been collected by the
    time this runs; letting an error out would throw that away.
    """

    class _Refusing:
        async def request(self, payload):
            raise answer

    assert await _fetch_schema_subtree(_Refusing(), ()) is None
    assert await _async_discover_via_schema(_Refusing()) == {}


async def test_the_node_budget_stops_a_runaway_tree(monkeypatch):
    """A device inventing endless children must not walk forever."""
    monkeypatch.setattr(discovery_export, "_MAX_SCHEMA_NODES", 3)
    client = _SchemaClient({f"leaf{i}": None for i in range(20)})

    await _async_discover_via_schema(client)

    # Exactly the budget, not one more: the check used "greater than" against
    # the count, which let a limit of N through at N+1.
    assert len(client.limits_asked) <= 3, client.limits_asked


async def test_a_timeout_keeps_what_was_already_collected(monkeypatch):
    """The walk is best-effort, so a hang must not discard the partial result.

    Deliberately not timing-dependent beyond "immediate versus never": the
    first leaf answers at once, the second blocks on an event nobody sets.
    """
    monkeypatch.setattr(discovery_export, "_SCHEMA_DISCOVERY_TIMEOUT", 0.3)

    class _StallsOnTheSecondLeaf(_SchemaClient):
        def __init__(self) -> None:
            super().__init__({"first": None, "second": None})
            self.blocked = asyncio.Event()
            self.reached_second = False

        async def request(self, payload):
            if "limits" in payload["osc"] and self._path_of(payload) == ("second",):
                # Recorded before blocking - the base class only notes a path
                # once it answers, which this call never does.
                self.reached_second = True
                await self.blocked.wait()  # never released
            return await super().request(payload)

    client = _StallsOnTheSecondLeaf()

    result = await _async_discover_via_schema(client)

    assert result == {"first": {"type": "Number"}}, result
    assert client.reached_second, "it stopped before the leaf that hangs"
