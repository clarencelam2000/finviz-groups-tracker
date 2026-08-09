"""Tests for scripts/session_config.py — the single source of truth for the
session dimension (WS2, ADR-011 Option C)."""

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import session_config as sc

TIME_RE = re.compile(r"^\d{2}:\d{2}$")


def test_registry_keys_round_trip():
    for key in sc.SESSIONS:
        assert sc.is_valid_session(key)
    assert not sc.is_valid_session("afternoon")
    assert not sc.is_valid_session("")


def test_exactly_one_settled_session_is_eod():
    assert sc.settled_sessions() == ["eod"]


def test_provisional_sessions_order():
    assert sc.provisional_sessions() == ["morning", "pre_close"]


def test_is_provisional():
    assert sc.is_provisional("morning") is True
    assert sc.is_provisional("pre_close") is True
    assert sc.is_provisional("eod") is False
    assert sc.is_provisional("afternoon") is False


def test_default_session_is_eod():
    assert sc.DEFAULT_SESSION == sc.EOD == "eod"


def test_capture_et_format_and_values():
    expected = {"eod": "17:00", "morning": "10:05", "pre_close": "15:50"}
    for key, session in sc.SESSIONS.items():
        assert TIME_RE.match(session.capture_et), session.capture_et
        hour, minute = session.capture_et.split(":")
        assert 0 <= int(hour) <= 23
        assert 0 <= int(minute) <= 59
        assert session.capture_et == expected[key]


def test_keys_and_capture_times_unique():
    keys = [s.key for s in sc.SESSIONS.values()]
    times = [s.capture_et for s in sc.SESSIONS.values()]
    assert len(keys) == len(set(keys))
    assert len(times) == len(set(times))


def test_assert_provisional_ok_for_provisional_sessions():
    assert sc.assert_provisional("morning") is None
    assert sc.assert_provisional("pre_close") is None


def test_assert_provisional_raises_for_eod():
    with pytest.raises(ValueError):
        sc.assert_provisional("eod")


def test_assert_provisional_raises_for_unknown_key():
    with pytest.raises(ValueError):
        sc.assert_provisional("afternoon")


def test_registry_order_is_eod_morning_pre_close():
    assert list(sc.SESSIONS) == ["eod", "morning", "pre_close"]
