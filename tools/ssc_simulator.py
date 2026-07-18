"""Standalone SSC device simulator for Neumann KH speakers.

Speaks the Sennheiser Sound Control Protocol (SSC) the way the real hardware
does: JSON over TCP, every message terminated with "\\r\\n". It lets the
integration be exercised end to end without physical speakers.

The simulator deliberately reproduces the *verified* firmware behaviour rather
than what the khtool metadata advertises. Real devices reject far more than the
metadata suggests, so a permissive simulator would make the integration look
healthy while it is broken against real hardware:

* only single leaf paths are answered - collective/container queries fail (400)
* fields confirmed to be read-only reject a "set" (405)
* paths a model does not have are unknown (404)
* "osc/schema" and "osc/limits" are rejected unless --enable-schema is given

Usage:
    python tools/ssc_simulator.py --model "KH 120 II"
    python tools/ssc_simulator.py --model "KH 750" --port 8046

Run several instances on different ports to simulate multiple devices.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from typing import Any

_LOGGER = logging.getLogger("ssc_simulator")

_TERMINATOR = b"\r\n"
_MAX_LINE_BYTES = 1_048_576

MODEL_KH_120_II = "KH 120 II"
MODEL_KH_750 = "KH 750"
MODELS = (MODEL_KH_120_II, MODEL_KH_750)

# Error codes as observed on real hardware.
_ERR_BAD_REQUEST = 400
_ERR_NOT_FOUND = 404
_ERR_NOT_ALLOWED = 405

_ERR_DESCRIPTIONS = {
    _ERR_BAD_REQUEST: "message not understood",
    _ERR_NOT_FOUND: "no such address",
    _ERR_NOT_ALLOWED: "method not allowed",
}

# EQ containers per model: (path prefix, band count). Mirrors eq_containers.py.
_EQ_NON_SUBWOOFER = (
    (("audio", "out", "eq2"), 10),
    (("audio", "out", "eq3"), 20),
)
_EQ_SUBWOOFER = (
    (("audio", "out", "eq2"), 10),
    (("audio", "out1", "eq1"), 2),
    (("audio", "out1", "eq2"), 10),
    (("audio", "out1", "eq3"), 10),
    (("audio", "out2", "eq1"), 2),
    (("audio", "out2", "eq2"), 10),
    (("audio", "out2", "eq3"), 10),
)

# Read-only on every model: identity, live metering, derived counters.
_READ_ONLY_COMMON = frozenset(
    {
        ("device", "identity", "product"),
        ("device", "identity", "serial"),
        ("device", "identity", "version"),
        ("device", "identity", "hw_version"),
        ("device", "standby", "countdown"),
        ("device", "temperature"),
        ("audio", "in", "current_input"),
        ("m", "in", "level"),
        ("m", "in", "clip"),
        ("m", "out", "level"),
        ("m", "out", "clip"),
        ("warnings",),
    }
)

# Confirmed NOT writable on the KH 120 II (real hardware test).
_READ_ONLY_KH_120_II = frozenset(
    {
        ("ui", "input_gain"),
        ("ui", "input_select"),
        ("ui", "bass_gain"),
        ("ui", "mid_gain"),
        ("ui", "treble_gain"),
        ("ui", "output_level"),
        ("device", "save_settings"),
    }
)

# Confirmed NOT writable on the KH 750 (real hardware test).
_READ_ONLY_KH_750 = frozenset(
    {
        ("ui", "bass_management"),
        ("ui", "channel_b_input_mode"),
        ("ui", "subwoofer_input_gain"),
        ("ui", "subwoofer_low_cut"),
        ("ui", "subwoofer_output_level"),
        ("ui", "subwoofer_phase"),
        ("ui", "subwoofer_phase_inversion"),
        ("audio", "digital_bypass"),
        ("audio", "out", "label"),
        ("audio", "out1", "label"),
        ("audio", "out2", "label"),
    }
)


def _eq_state(containers: tuple[tuple[tuple[str, ...], int], ...]) -> dict[str, Any]:
    """Build the EQ part of the state: enabled/gain/boost arrays per container."""
    state: dict[str, Any] = {}
    for path, band_count in containers:
        node = state
        for key in path[:-1]:
            node = node.setdefault(key, {})
        node[path[-1]] = {
            "enabled": [False] * band_count,
            "gain": [0.0] * band_count,
            "boost": [0.0] * band_count,
        }
    return state


def _merge(target: dict[str, Any], source: dict[str, Any]) -> None:
    """Recursively merge source into target (source wins on leaves)."""
    for key, value in source.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _merge(target[key], value)
        else:
            target[key] = value


def _build_state(model: str) -> dict[str, Any]:
    """Build the initial device state for the given model.

    Paths a model does not have are deliberately absent, so the simulator
    answers 404 for them - exactly like the real device (e.g. "dimm" does not
    exist on the KH 120 II).
    """
    is_subwoofer = model == MODEL_KH_750
    state: dict[str, Any] = {
        "device": {
            "identity": {
                "product": model,
                "serial": "SIM0001234" if not is_subwoofer else "SIM0007500",
                "version": "2_1_2" if is_subwoofer else "1_7_3",
                "hw_version": "1.0",
            },
            "name": f"Simulated {model}",
            "restore": "",
            "standby": {
                "enabled": True,
                "auto_standby_time": 120,
                "level": -70.0,
                "countdown": 0,
            },
            "identification": {"visual": False},
        },
        "audio": {
            "in": {"interface": "ANALOG ONLY", "current_input": "ANALOG"},
            "out": {
                "level": 100.0,
                "delay": 0,
                "mute": False,
            },
        },
        "ui": {"control_mode": "NETWORK"},
        "m": {"in": {"level": [-40.0, -41.5], "clip": [False, False]}},
        "warnings": [],
    }

    if is_subwoofer:
        _merge(
            state,
            {
                "device": {"temperature": 310.0},
                "audio": {
                    "digital_bypass": False,
                    "out": {"dimm": 0.0, "label": "Main"},
                    "out1": {
                        "level": 100.0,
                        "delay": 0,
                        "mute": False,
                        "label": "Out 1",
                        "loudspeaker": "UNKNOWN",
                    },
                    "out2": {
                        "level": 100.0,
                        "delay": 0,
                        "mute": False,
                        "label": "Out 2",
                        "loudspeaker": "UNKNOWN",
                    },
                },
                "ui": {
                    "bass_management": "5.1",
                    "channel_b_input_mode": "STEREO",
                    "subwoofer_input_gain": "0 dB",
                    "subwoofer_low_cut": "OFF",
                    "subwoofer_output_level": "100 dB",
                    "subwoofer_phase": "0",
                    "subwoofer_phase_inversion": "OFF",
                },
                "m": {"out": {"level": [-35.0], "clip": [False]}},
            },
        )
        _merge(state, _eq_state(_EQ_SUBWOOFER))
    else:
        _merge(
            state,
            {
                "device": {"save_settings": False},
                "audio": {"out": {"phaseinversion": False}},
                "ui": {
                    "logo": {"brightness": 60},
                    "input_gain": "0 dB",
                    "input_select": "ANALOG",
                    "bass_gain": "0 dB",
                    "mid_gain": "0 dB",
                    "treble_gain": "0 dB",
                    "output_level": "100 dB",
                },
            },
        )
        _merge(state, _eq_state(_EQ_NON_SUBWOOFER))

    return state


def _read_only_paths(model: str) -> frozenset[tuple[str, ...]]:
    """Return every path that rejects a "set" on this model."""
    specific = _READ_ONLY_KH_750 if model == MODEL_KH_750 else _READ_ONLY_KH_120_II
    return _READ_ONLY_COMMON | specific


def _collect_leaves(
    payload: dict[str, Any], prefix: tuple[str, ...] = ()
) -> list[tuple[tuple[str, ...], Any]]:
    """Flatten a request into (path, value) pairs, stopping at non-dict values."""
    leaves: list[tuple[tuple[str, ...], Any]] = []
    for key, value in payload.items():
        path = prefix + (key,)
        if isinstance(value, dict) and value:
            leaves.extend(_collect_leaves(value, path))
        else:
            leaves.append((path, value))
    return leaves


def _build_nested(path: tuple[str, ...], value: Any) -> dict[str, Any]:
    """Turn a path plus value into the nested dict the protocol expects."""
    result: Any = value
    for key in reversed(path):
        result = {key: result}
    return result


def _error(code: int) -> dict[str, Any]:
    """Build an SSC error response in the format real devices return."""
    return {"osc": {"error": [code, {"desc": _ERR_DESCRIPTIONS[code]}]}}


class SSCSimulator:
    """Holds the state of one simulated speaker and answers SSC requests."""

    def __init__(self, model: str, enable_schema: bool = False) -> None:
        self.model = model
        self.enable_schema = enable_schema
        self.state = _build_state(model)
        self.read_only = _read_only_paths(model)

    def _resolve(self, path: tuple[str, ...]) -> tuple[bool, Any]:
        """Look a path up in the state. Returns (found, value)."""
        node: Any = self.state
        for key in path:
            if not isinstance(node, dict) or key not in node:
                return False, None
            node = node[key]
        return True, node

    def _apply_set(self, path: tuple[str, ...], value: Any) -> None:
        node: Any = self.state
        for key in path[:-1]:
            node = node[key]
        node[path[-1]] = value

    def handle(self, request: dict[str, Any]) -> dict[str, Any]:
        """Answer a single decoded SSC request."""
        # osc/schema and osc/limits are optional per the specification and are
        # rejected by the tested firmware.
        if "osc" in request and not self.enable_schema:
            return _error(_ERR_BAD_REQUEST)

        leaves = _collect_leaves(request)
        if len(leaves) != 1:
            # Collective messages are rejected by the real firmware.
            return _error(_ERR_BAD_REQUEST)

        path, value = leaves[0]
        found, current = self._resolve(path)
        if not found:
            return _error(_ERR_NOT_FOUND)
        if isinstance(current, dict):
            # Container query (e.g. {"device": null}) - rejected by the firmware.
            return _error(_ERR_BAD_REQUEST)

        if value is None:
            return _build_nested(path, current)

        if path in self.read_only:
            return _error(_ERR_NOT_ALLOWED)

        self._apply_set(path, value)
        return _build_nested(path, value)


async def _handle_client(
    simulator: SSCSimulator,
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
) -> None:
    peer = writer.get_extra_info("peername")
    _LOGGER.info("Client connected: %s", peer)
    try:
        while True:
            try:
                raw_line = await reader.readuntil(b"\n")
            except (asyncio.IncompleteReadError, ConnectionResetError):
                break
            except asyncio.LimitOverrunError:
                _LOGGER.warning("Line exceeded the limit, dropping connection")
                break

            line = raw_line.strip()
            if not line:
                continue

            try:
                request = json.loads(line)
            except json.JSONDecodeError:
                # Real devices stay silent on malformed input; the client
                # ignores unparsable lines as well.
                _LOGGER.debug("Ignored invalid JSON: %s", line)
                continue

            if not isinstance(request, dict):
                response = _error(_ERR_BAD_REQUEST)
            else:
                response = simulator.handle(request)

            _LOGGER.debug("%s -> %s", line.decode("utf-8", "replace"), response)
            writer.write(json.dumps(response).encode("utf-8") + _TERMINATOR)
            await writer.drain()
    finally:
        _LOGGER.info("Client disconnected: %s", peer)
        writer.close()


async def run(model: str, host: str, port: int, enable_schema: bool) -> None:
    """Start the simulator and serve until interrupted."""
    simulator = SSCSimulator(model, enable_schema=enable_schema)

    async def client_connected(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        await _handle_client(simulator, reader, writer)

    server = await asyncio.start_server(
        client_connected, host=host, port=port, limit=_MAX_LINE_BYTES
    )
    _LOGGER.info("Simulating %s on [%s]:%d", model, host, port)
    _LOGGER.info("Configure the integration with host %s and port %d", host, port)
    async with server:
        await server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description="Neumann KH SSC device simulator")
    parser.add_argument("--model", choices=MODELS, default=MODEL_KH_120_II)
    parser.add_argument("--host", default="::1", help="bind address (default: IPv6 loopback)")
    parser.add_argument("--port", type=int, default=8045)
    parser.add_argument(
        "--enable-schema",
        action="store_true",
        help="answer osc/schema and osc/limits instead of rejecting them",
    )
    parser.add_argument("--verbose", action="store_true", help="log every request")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    try:
        asyncio.run(run(args.model, args.host, args.port, args.enable_schema))
    except KeyboardInterrupt:
        _LOGGER.info("Shutting down")


if __name__ == "__main__":
    main()
