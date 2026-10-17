"""Standalone SSC device simulator for Neumann KH speakers.

Speaks the Sennheiser Sound Control Protocol (SSC) the way the real hardware
does: JSON over TCP, every message terminated with "\\r\\n". It lets the
integration be exercised end to end without physical speakers.

The simulator deliberately reproduces the *verified* firmware behaviour rather
than what the khtool metadata advertises. Real devices reject far more than the
metadata suggests, so a permissive simulator would make the integration look
healthy while it is broken against real hardware:

* errors are nested in the request's shape, as recorded from the devices: a
  missing path is a 404 at its first missing node, a container query a 404 at
  the container, a set on a read-only field a 405 and a value of the wrong
  type a 406, both at the leaf
* a bundle answers every leaf it can - gets and sets alike - and lists the
  rest as errors; a missing leaf's 404 then sits at its parent
* "osc/schema" is answered in the recorded form, "osc/limits" with the recorded
  envelope and the type only (both tested firmwares support them);
  --disable-schema mimics firmware that does not

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
_ERR_NOT_ACCEPTABLE = 406
_ERR_PARAMETER_NOT_FOUND = 454

_ERR_DESCRIPTIONS = {
    _ERR_BAD_REQUEST: "message not understood",
    _ERR_NOT_FOUND: "address not found",
    _ERR_NOT_ALLOWED: "method not allowed",
    _ERR_NOT_ACCEPTABLE: "not acceptable",
    _ERR_PARAMETER_NOT_FOUND: "parameter address not found",
}

# EQ containers per model: (path prefix, band count), as measured on the
# devices. tests/test_eq_layout.py holds the KH 750 measurement both this and
# eq_containers.py are checked against.
_EQ_NON_SUBWOOFER = (
    (("audio", "out", "eq2"), 10),
    (("audio", "out", "eq3"), 20),
)
_EQ_SUBWOOFER = (
    (("audio", "out", "eq2"), 10),
    (("audio", "out", "eq3"), 10),
    (("audio", "out1", "eq2"), 10),
    (("audio", "out1", "eq3"), 10),
    (("audio", "out2", "eq2"), 10),
    (("audio", "out2", "eq3"), 10),
)

# Read-only on every model: identity, live metering, derived counters.
_READ_ONLY_COMMON = frozenset(
    {
        ("device", "identity", "product"),
        ("device", "identity", "vendor"),
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
        # "device/save_settings" is deliberately absent here and from the
        # state: measured 404 on the KH 120 II, so the device does not have
        # the path at all rather than refusing to write it.
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
        # Modelled as sensors, so a write has to be refused here too -
        # otherwise a test could pass against the simulator that the hardware
        # answers with a 405.
        ("audio", "out1", "loudspeaker"),
        ("audio", "out2", "loudspeaker"),
        # Writable on the monitors, read-only here - which is why it is a
        # switch on one model and a binary sensor on the other. Accepting the
        # write would let a test pass that real hardware answers with a 405.
        ("device", "standby", "enabled"),
    }
)


def _eq_state(containers: tuple[tuple[tuple[str, ...], int], ...]) -> dict[str, Any]:
    """Build the EQ part of the state: one array per leaf and container.

    All six leaves a real container exposes, verified by reading them off a
    KH 120 II (firmware 1_7_3). Omitting frequency, Q and filter type would
    make a backup look complete in tests while missing what actually defines
    the filters.
    """
    state: dict[str, Any] = {}
    for path, band_count in containers:
        node = state
        for key in path[:-1]:
            node = node.setdefault(key, {})
        node[path[-1]] = {
            "enabled": [False] * band_count,
            "gain": [0.0] * band_count,
            "boost": [0.0] * band_count,
            "frequency": [100.0] * band_count,
            "q": [0.7] * band_count,
            "type": ["PARAMETRIC"] * band_count,
        }
    return state


def _crossover_state() -> dict[str, Any]:
    """KH 750 crossover: eq1/in1 and eq1/in2, two bands each, as read on 2_1_2.

    The main output low-passes, out1/out2 high-pass, all at 80 Hz. The
    integration does not expose it; the simulator has it because the device does.
    """
    audio: dict[str, Any] = {}
    for output, filter_type in (("out", "LOWPASS"), ("out1", "HIGHPASS"), ("out2", "HIGHPASS")):
        audio[output] = {
            "eq1": {
                sub: {
                    "enabled": [True, True],
                    "gain": [0.0, 0.0],
                    "boost": [0.0, 0.0],
                    "frequency": [80.0, 80.0],
                    "q": [0.7, 0.7],
                    "type": [filter_type, filter_type],
                }
                for sub in ("in1", "in2")
            }
        }
    return {"audio": audio}


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
    answers 404 for them - exactly like the real device ("audio/out/dimm" and
    "device/save_settings" exist on neither test model).

    The values are the ones measured off the hardware, types included. An
    invented format is worse than a wrong value: the integration decides per
    path whether it parses a number or passes text through, so a simulator
    answering "0 dB" where the device answers 0.0 makes a correct sensor look
    broken - and an incorrect one look fine.
    """
    is_subwoofer = model == MODEL_KH_750
    state: dict[str, Any] = {
        "device": {
            "identity": {
                "product": model,
                # Verified verbatim on both test devices.
                "vendor": "Georg Neumann GmbH",
                "serial": "SIM0001234" if not is_subwoofer else "SIM0007500",
                "version": "2_1_2" if is_subwoofer else "1_7_3",
                "hw_version": 1,
            },
            "name": f"Simulated {model}",
            "restore": "",
            "standby": {
                "enabled": True,
                "auto_standby_time": 60,
                "level": -65,
                "countdown": 0,
            },
            "identification": {"visual": False},
            # Paths the integration never reads, with the values measured on
            # both models; the MAC is a documentation-range placeholder.
            "auth": {"exclusive": ""},
            "system": "",
            "time": 0,
            "timeprecision": 0,
            "update": {"enable": False, "startover": False},
            "network": {"ether": {"macs": "00:00:5E:00:53:01"}},
        },
        "audio": {
            "in": {"interface": "ANALOG ONLY", "current_input": "ANALOG INPUT"},
            "out": {
                "level": 100.0,
                "delay": 0,
                "mute": False,
                "mute_persist": False,
                "mixer": {"levels": [0.0, -100.0]},
            },
        },
        "ui": {"control_mode": "NETWORK"},
        "m": {"in": {"level": [-40.0, -41.5], "clip": [False, False]}},
        # A device with nothing to report answers with this marker, not an
        # empty list.
        "warnings": ["NO_WARNING"],
    }

    if is_subwoofer:
        _merge(
            state,
            {
                "device": {"temperature": 310},
                "audio": {
                    "digital_bypass": True,
                    # No "dimm" here either: measured 404 on the KH 750 as well,
                    # so it exists on neither test model.
                    "out": {"label": "SUBWOOFER"},
                    "out1": {
                        "level": 100.0,
                        "delay": 0,
                        "mute": False,
                        "mute_persist": False,
                        "mixer": {"levels": [0.0, -100.0]},
                        "label": "OUT1",
                        "loudspeaker": "UNKNOWN",
                    },
                    "out2": {
                        "level": 100.0,
                        "delay": 0,
                        "mute": False,
                        "mute_persist": False,
                        "mixer": {"levels": [0.0, -100.0]},
                        "label": "OUT2",
                        "loudspeaker": "UNKNOWN",
                    },
                },
                "ui": {
                    "auto_standby": "ON",
                    "bass_management": "DISABLED",
                    "channel_b_input_mode": "Ext.BM LFE (fullrange)",
                    "subwoofer_input_gain": 2.0,
                    "subwoofer_low_cut": -0.1,
                    "subwoofer_output_level": "94",
                    "subwoofer_phase": "0",
                    "subwoofer_phase_inversion": "0",
                },
                # [A, B, subwoofer], as the schema describes and the devices answer.
                "m": {"out": {"level": [-35.0, -35.0, -35.0], "clip": [False, False, False]}},
            },
        )
        _merge(state, _eq_state(_EQ_SUBWOOFER))
        _merge(state, _crossover_state())
    else:
        _merge(
            state,
            {
                "audio": {"out": {"phaseinversion": False}},
                "ui": {
                    "logo": {"brightness": 30},
                    "input_gain": 0.0,
                    "input_select": "ANALOG",
                    "bass_gain": "0",
                    "mid_gain": "0",
                    "treble_gain": "0",
                    "output_level": "100",
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


# The osc container as the devices describe it (osc/schema walk recorded on a
# KH 120 II); its methods answer osc/limits with an empty description.
_OSC_TREE: dict[str, Any] = {
    "state": {
        "auth": {"access": None},
        "prettyprint": None,
        "subscribe": None,
        "subscribe_reserve": None,
    },
    "feature": {"timetag": None, "baseaddr": None, "subscription": None, "pattern": None},
    "limits": None,
    "schema": None,
    "version": None,
    "xid": None,
    "ping": None,
    "error": None,
}


# osc methods and their recorded answers (both models alike); xid is echoed.
_OSC_METHOD_ANSWERS: dict[str, Any] = {
    "version": "1.1",
    "ping": None,
    "feature": {"pattern": "*?", "subscription": True},
}


def _osc_method_answer(osc: dict[str, Any]) -> dict[str, Any] | None:
    """The answer to osc methods other than schema/limits, or None if unrecorded.

    Recorded are gets (null) of version, ping and single features, and the xid
    echo; a set, a container query or an empty request was never recorded.
    """
    if not osc:
        return None
    answer: dict[str, Any] = {}
    for key, value in osc.items():
        if key == "xid":
            answer[key] = value
        elif key == "feature":
            features = _OSC_METHOD_ANSWERS["feature"]
            asked = value if isinstance(value, dict) else {}
            if (
                not asked
                or set(asked) - set(features)
                or any(v is not None for v in asked.values())
            ):
                return None
            answer[key] = {name: features[name] for name in asked}
        elif key in ("version", "ping") and value is None:
            answer[key] = _OSC_METHOD_ANSWERS[key]
        else:
            return None
    return answer


def _limits_type(value: Any) -> str:
    """The type name osc/limits reports, as the devices spell it."""
    if isinstance(value, list):
        value = value[0] if value else None
    if isinstance(value, bool):
        return "Boolean"
    if isinstance(value, (int, float)):
        return "Number"
    return "String"


def _lookup(tree: dict[str, Any], path: tuple[str, ...]) -> tuple[bool, Any]:
    """Look a path up in a tree. Returns (found, value)."""
    node: Any = tree
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return False, None
        node = node[key]
    return True, node


def _osc_error(method: str, code: int) -> dict[str, Any]:
    """A refused introspection request: the error sits at osc/<method>, as recorded."""
    return {"osc": {"error": [_error_entry(("osc", method), code)]}}


def _introspection_path(value: Any, method: str) -> tuple[tuple[str, ...] | None, Any]:
    """The single address an osc/schema or osc/limits request asks about.

    Returns (path, None) or (None, error reply). Recorded: the argument has to
    be a list holding an address tree that ends in null - [null] or [{}] is a
    454, a tree ending in {} a 406.
    """
    if not isinstance(value, list) or not value or not isinstance(value[0], dict) or not value[0]:
        return None, _osc_error(method, _ERR_PARAMETER_NOT_FOUND)
    leaves = _collect_leaves(value[0])
    if len(leaves) != 1:
        return None, _error(_ERR_BAD_REQUEST)
    path, end = leaves[0]
    if end is not None:
        return None, _osc_error(method, _ERR_NOT_ACCEPTABLE)
    return path, None


def _error(code: int) -> dict[str, Any]:
    """A flat SSC error, for the cases whose real reply was never recorded (400)."""
    return {"osc": {"error": [code, {"desc": _ERR_DESCRIPTIONS[code]}]}}


def _error_entry(node: tuple[str, ...], code: int) -> dict[str, Any]:
    """One osc/error entry nested at `node`, the format recorded from the devices."""
    return _build_nested(node, [code, {"desc": _ERR_DESCRIPTIONS[code]}])


def _same_kind(current: Any, value: Any) -> bool:
    """Whether a set carries the kind of value the path holds (else 406)."""
    if isinstance(current, bool) or isinstance(value, bool):
        return isinstance(current, bool) and isinstance(value, bool)
    if isinstance(current, (int, float)):
        return isinstance(value, (int, float))
    if isinstance(current, list):
        return isinstance(value, list) and len(value) == len(current)
    return isinstance(value, type(current))


def _move_output_to_out5(state: dict[str, Any]) -> None:
    """KH 750 firmware 1.2.x: level and mute live in audio/out5, delay stays.

    As reported for firmware 1.2.4 - not measured by this project, whose KH 750
    runs 2_1_2.
    """
    out = state["audio"]["out"]
    state["audio"]["out5"] = {"level": out.pop("level"), "mute": out.pop("mute")}
    state["device"]["identity"]["version"] = "1_2_4"


class SSCSimulator:
    """Holds the state of one simulated speaker and answers SSC requests."""

    def __init__(
        self, model: str, enable_schema: bool = True, output_on_out5: bool = False
    ) -> None:
        self.model = model
        self.enable_schema = enable_schema
        self.state = _build_state(model)
        if output_on_out5:
            _move_output_to_out5(self.state)
        self.read_only = _read_only_paths(model)

    def _resolve(self, path: tuple[str, ...]) -> tuple[bool, Any]:
        """Look a path up in the state. Returns (found, value)."""
        return _lookup(self.state, path)

    def _first_missing(self, path: tuple[str, ...]) -> tuple[str, ...]:
        """The path down to the first node that does not exist."""
        node: Any = self.state
        for depth, key in enumerate(path):
            if not isinstance(node, dict) or key not in node:
                return path[: depth + 1]
            node = node[key]
        return path

    def _answer_leaf(
        self, path: tuple[str, ...], value: Any, bundled: bool
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        """One leaf of a request: (answer subtree, None) or (None, error entry)."""
        found, current = self._resolve(path)
        if not found or isinstance(current, dict):
            node = self._first_missing(path) if not found else path
            if bundled:
                # Recorded: inside a bundle the 404 moves up to the parent.
                node = node[:-1] or node
            return None, _error_entry(node, _ERR_NOT_FOUND)
        if value is None:
            return _build_nested(path, current), None
        if path in self.read_only:
            return None, _error_entry(path, _ERR_NOT_ALLOWED)
        if not _same_kind(current, value):
            return None, _error_entry(path, _ERR_NOT_ACCEPTABLE)
        self._apply_set(path, value)
        return _build_nested(path, value), None

    def _apply_set(self, path: tuple[str, ...], value: Any) -> None:
        node: Any = self.state
        for key in path[:-1]:
            node = node[key]
        node[path[-1]] = value

    @staticmethod
    def _schema_level(node: dict[str, Any]) -> dict[str, Any]:
        """One level of the address tree as osc/schema reports it.

        Containers are announced as an empty dict, leaves as null. Consumers
        walk the tree by requesting each container path in turn.
        """
        return {key: {} if isinstance(value, dict) else None for key, value in node.items()}

    def _address_tree(self) -> dict[str, Any]:
        """Everything osc/schema describes: the device state plus the osc container."""
        return {**self.state, "osc": _OSC_TREE}

    def _osc_schema(self, value: Any) -> dict[str, Any]:
        if value is None:
            return {"osc": {"schema": [self._schema_level(self._address_tree())]}}
        path, refusal = _introspection_path(value, "schema")
        if refusal is not None:
            return refusal
        found, node = _lookup(self._address_tree(), path)
        if not found:
            # Never recorded for an unknown address; the code of the malformed
            # requests is the closest measured answer.
            return _osc_error("schema", _ERR_PARAMETER_NOT_FOUND)
        if not isinstance(node, dict):
            # A leaf has no sub-tree of its own.
            return {"osc": {"schema": [_build_nested(path, None)]}}
        return {"osc": {"schema": [_build_nested(path, self._schema_level(node))]}}

    def _osc_limits(self, value: Any) -> dict[str, Any]:
        path, refusal = _introspection_path(value, "limits")
        if refusal is not None:
            return refusal
        found, node = _lookup(self._address_tree(), path)
        if not found or isinstance(node, dict):
            return _osc_error("limits", _ERR_PARAMETER_NOT_FOUND)
        # Only the type is reproduced; the devices' other fields (desc, units,
        # min, max, ...) are not, and none is invented in their place.
        description: dict[str, Any] = {}
        if path[0] != "osc":
            description["type"] = _limits_type(node)
        return {"osc": {"limits": [_build_nested(path, [description])]}}

    def handle(self, request: dict[str, Any]) -> dict[str, Any]:
        """Answer a single decoded SSC request."""
        # osc/schema and osc/limits are optional per the specification; both
        # tested firmwares answer them. Without them, the reply is unrecorded.
        if "osc" in request:
            osc = request["osc"]
            if not isinstance(osc, dict):
                return _error(_ERR_BAD_REQUEST)
            if "schema" in osc or "limits" in osc:
                if not self.enable_schema:
                    return _error(_ERR_BAD_REQUEST)
                if "schema" in osc:
                    return self._osc_schema(osc["schema"])
                return self._osc_limits(osc["limits"])
            methods = _osc_method_answer(osc)
            if methods is None:
                return _error(_ERR_BAD_REQUEST)
            values = {key: value for key, value in request.items() if key != "osc"}
            answer = self._answer_values(values) if values else {}
            _merge(answer, {"osc": methods})
            return answer
        return self._answer_values(request)

    def _answer_values(self, request: dict[str, Any]) -> dict[str, Any]:
        """Gets and sets of device values, single or bundled."""
        leaves = _collect_leaves(request)
        if not leaves:
            return _error(_ERR_BAD_REQUEST)
        answer: dict[str, Any] = {}
        errors: list[dict[str, Any]] = []
        for path, value in leaves:
            subtree, error = self._answer_leaf(path, value, bundled=len(leaves) > 1)
            if subtree is None:
                errors.append(error)
            else:
                _merge(answer, subtree)
        if errors:
            answer["osc"] = {"error": errors}
        return answer


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


async def run(model: str, host: str, port: int, enable_schema: bool, output_on_out5: bool) -> None:
    """Start the simulator and serve until interrupted."""
    simulator = SSCSimulator(model, enable_schema=enable_schema, output_on_out5=output_on_out5)

    async def client_connected(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
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
        "--disable-schema",
        action="store_true",
        help="reject osc/schema and osc/limits, like firmware without them",
    )
    parser.add_argument(
        "--output-on-out5",
        action="store_true",
        help="KH 750 firmware 1.2.x layout: output level and mute in audio/out5",
    )
    parser.add_argument("--verbose", action="store_true", help="log every request")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    try:
        asyncio.run(
            run(args.model, args.host, args.port, not args.disable_schema, args.output_on_out5)
        )
    except KeyboardInterrupt:
        _LOGGER.info("Shutting down")


if __name__ == "__main__":
    main()
