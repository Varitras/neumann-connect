"""What a device says about itself, and whether that is the speaker we expect.

Four paths compare a stored serial with an answered one - relocate,
reconfigure, zeroconf and the regular setup. Each had its own hand-written
comparison until the setup turned out to have none at all. One owner, so the
next path cannot forget it either.
"""

from __future__ import annotations

from typing import Any


def as_identity_text(value: Any) -> str | None:
    """Coerce an identity field to text, or None if it carries nothing usable.

    SSC answers are plain JSON, so a field can arrive as a list, a number or a
    dict - from a firmware quirk or simply from a device that is not a Neumann
    speaker. Passing those on unchecked reaches code that assumes text: the
    vendor check calls .lower(), the serial becomes a unique ID and a dict key,
    and mask_serial() slices it. Coercing here keeps that guesswork out of
    every later caller.
    """
    if value is None or isinstance(value, (list, dict, bool)):
        return None
    text = str(value).strip()
    return text or None


def serial_matches(expected: Any, answered: Any) -> bool:
    """True only if the device answered exactly the serial we expect.

    Fail-closed: a device that answers nothing usable does not match. A known
    serial must be matched, not merely not contradicted - accepting silence
    would attach the entry, its history and its stored exports to whatever
    answered at the address.
    """
    expected_text = as_identity_text(expected)
    answered_text = as_identity_text(answered)
    return expected_text is not None and answered_text == expected_text
