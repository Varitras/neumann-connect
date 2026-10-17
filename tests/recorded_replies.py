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
