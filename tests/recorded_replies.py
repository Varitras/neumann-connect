"""Reply lines recorded from real speakers, verbatim.

Read-only probe of 2026-10-17 against two KH 120 II (firmware 1_7_3) and two
KH 750 (firmware 2_1_2); every line below came back identically from both
models unless a model is named. They carry no identifiers.

The client parser and the simulator are both checked against these lines. The
simulator used to answer errors in a flat format of its own, the parser was
written against the simulator, and every test passed while the parser read no
error code from a real device at all.
"""

from __future__ import annotations

# (request, reply line) - get requests only.
NOT_FOUND_REPLIES = (
    (
        {"audio": {"out": {"dimm": None}}},
        '{"osc":{"error":[{"audio":{"out":{"dimm":[404,{"desc":"address not found"}]}}}]}}',
    ),
    (
        # The 404 sits at the first node that is missing, not at the leaf.
        {"audio": {"out5": {"level": None}}},
        '{"osc":{"error":[{"audio":{"out5":[404,{"desc":"address not found"}]}}]}}',
    ),
    (
        {"device": {"save_settings": None}},
        '{"osc":{"error":[{"device":{"save_settings":[404,{"desc":"address not found"}]}}]}}',
    ),
)

# KH 750 only; the KH 120 II answers this path with false.
KH_750_NOT_FOUND_REPLIES = (
    (
        {"audio": {"out": {"phaseinversion": None}}},
        '{"osc":{"error":[{"audio":{"out":{"phaseinversion":[404,{"desc":"address not found"}]}}}]}}',
    ),
)

# A container query is a 404 at the container.
CONTAINER_REPLY = (
    {"device": None},
    '{"osc":{"error":[{"device":[404,{"desc":"address not found"}]}]}}',
)

# A bundled get with one unknown leaf: the known value and the 404 in one line,
# the 404 attached to the parent of the unknown leaf.
BUNDLE_REPLY = (
    {"audio": {"out": {"level": None, "dimm": None}}},
    (
        '{"audio":{"out":{"level":100.0}},'
        '"osc":{"error":[{"audio":{"out":[404,{"desc":"address not found"}]}}]}}'
    ),
)

# Writes, recorded 2026-10-17 by writing back the value just read (nothing
# changed on the devices). The KH 120 II's ui/input_gain and the KH 750's
# ui/bass_management are read-only; both answered alike.
SET_REPLIES = (
    (
        {"audio": {"out": {"mute": False}}},
        '{"audio":{"out":{"mute":false}}}',
    ),
    (
        {"audio": {"out": {"dimm": 0}}},
        '{"osc":{"error":[{"audio":{"out":{"dimm":[404,{"desc":"address not found"}]}}}]}}',
    ),
    (
        # A value of the wrong type.
        {"audio": {"out": {"mute": "x"}}},
        '{"osc":{"error":[{"audio":{"out":{"mute":[406,{"desc":"not acceptable"}]}}}]}}',
    ),
    (
        {"audio": {"out": {"mute": False, "delay": 0}}},
        '{"audio":{"out":{"mute":false,"delay":0}}}',
    ),
    (
        # The valid leaf is written; the 404 sits at the missing leaf's parent.
        {"audio": {"out": {"mute": False, "dimm": 0}}},
        (
            '{"audio":{"out":{"mute":false}},'
            '"osc":{"error":[{"audio":{"out":[404,{"desc":"address not found"}]}}]}}'
        ),
    ),
    (
        {"audio": {"out": {"delay": None, "mute": False}}},
        '{"audio":{"out":{"mute":false,"delay":0}}}',
    ),
)

KH_120_II_READ_ONLY_SET_REPLIES = (
    (
        {"ui": {"input_gain": 0.0}},
        '{"osc":{"error":[{"ui":{"input_gain":[405,{"desc":"method not allowed"}]}}]}}',
    ),
    (
        # The valid leaf is written; the 405 sits at the read-only leaf itself.
        {"audio": {"out": {"mute": False}}, "ui": {"input_gain": 0.0}},
        (
            '{"audio":{"out":{"mute":false}},'
            '"osc":{"error":[{"ui":{"input_gain":[405,{"desc":"method not allowed"}]}}]}}'
        ),
    ),
)

# osc/schema and osc/limits - answered by both models in exactly the form the
# integration sends (an older note said 400; it is not).
SCHEMA_ROOT_REPLY = (
    {"osc": {"schema": None}},
    '{"osc":{"schema":[{"device":{},"osc":{},"audio":{},"m":{},"ui":{},"warnings":null}]}}',
)

# One level per model: containers as {}, leaves as null.
SCHEMA_AUDIO_REPLIES = {
    "KH 120 II": '{"osc":{"schema":[{"audio":{"in":{},"out":{}}}]}}',
    "KH 750": '{"osc":{"schema":[{"audio":{"in":{},"out":{},"out1":{},"out2":{},"digital_bypass":null}}]}}',
}
SCHEMA_AUDIO_REQUEST = {"osc": {"schema": [{"audio": None}]}}

# The leaf's limits come back as a list with one dict (shortened here to the
# fields every leaf carries).
LIMITS_LEVEL_REQUEST = {"osc": {"limits": [{"audio": {"out": {"level": None}}}]}}
LIMITS_LEVEL_TYPE = "Number"

# Malformed introspection requests, both models alike.
MALFORMED_OSC_REPLIES = (
    (
        {"osc": {"schema": [None]}},
        '{"osc":{"error":[{"osc":{"schema":[454,{"desc":"parameter address not found"}]}}]}}',
    ),
    (
        {"osc": {"schema": [{"audio": {}}]}},
        '{"osc":{"error":[{"osc":{"schema":[406,{"desc":"not acceptable"}]}}]}}',
    ),
    (
        {"osc": {"limits": {"audio": {"out": {"level": None}}}}},
        '{"osc":{"error":[{"osc":{"limits":[454,{"desc":"parameter address not found"}]}}]}}',
    ),
)
