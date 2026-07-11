"""Tests für _util: build_nested, deep_merge, extract."""

from custom_components.neumann_kh._util import build_nested, deep_merge, extract


def test_build_nested_single_level():
    assert build_nested(("device",), 5) == {"device": 5}


def test_build_nested_deep():
    assert build_nested(("audio", "out", "mute"), True) == {
        "audio": {"out": {"mute": True}}
    }


def test_extract_roundtrip():
    data = build_nested(("a", "b", "c"), 42)
    assert extract(data, ("a", "b", "c")) == 42


def test_extract_missing_path_returns_none():
    assert extract({"a": {"b": 1}}, ("a", "x")) is None
    assert extract({}, ("a",)) is None


def test_extract_non_dict_intermediate_returns_none():
    # Zwischenknoten ist kein Dict - darf nicht crashen.
    assert extract({"a": 5}, ("a", "b")) is None


def test_deep_merge_source_wins():
    target = {"a": {"b": 1, "c": 2}}
    deep_merge(target, {"a": {"b": 9}})
    assert target == {"a": {"b": 9, "c": 2}}


def test_deep_merge_disjoint_keys():
    target = {"a": 1}
    deep_merge(target, {"b": 2})
    assert target == {"a": 1, "b": 2}


def test_deep_merge_dict_replaces_scalar():
    target = {"a": 1}
    deep_merge(target, {"a": {"b": 2}})
    assert target == {"a": {"b": 2}}
