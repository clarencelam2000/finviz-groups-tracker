"""
session_config.py — Single source of truth for the "session" dimension (WS2, ADR-011 Option C).

The daily pipeline (`collect.py` / `compute_deltas.py`) writes one settled end-of-day
observation per (date, name) into `data/{sectors,industries}/*.csv`. ADR-011 introduces
a "session" concept so provisional intraday readings (a morning check-in, a pre-close
snapshot) can coexist without ever contaminating that settled data.

ADR-011 chose **Option C**: the existing files stay byte-identical — they simply ARE
the `eod` session, unchanged, with no `session` column added and no migration. Data for
provisional sessions (`morning`, `pre_close`) will later live in physically-separate,
session-keyed stores (built in WS3/WS5, not by this module) that the settled pipeline
never reads.

This module is the SSOT for session identity only: the enum of known sessions, their
canonical capture times, and which ones are "settled" vs "provisional". It defines no
store, no path, and no writer — that is deliberately out of scope for this module.

Designed for N sessions, not hardcoded to two — `SESSIONS` is an ordered dict and every
helper below iterates it generically, so adding a fourth session later is a one-entry change.
"""

from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Session identity
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Session:
    key: str          # canonical id stored in a future `session` column
    label: str        # human-readable label
    capture_et: str   # canonical target capture time, "HH:MM" 24-hour Eastern
    settled: bool     # True only for eod (the settled close); provisional otherwise


# String key constants — use these instead of literal strings when referencing a session.
EOD = "eod"
MORNING = "morning"
PRE_CLOSE = "pre_close"

# Ordered registry: insertion order is display order (eod, morning, pre_close).
# Capture times here are the canonical config for future collection jobs — this dict
# is the "3 places" configurable constant (see CLAUDE.md § Code quality standards);
# also documented in README.md § Configurable parameters and CLAUDE.md § Automation.
SESSIONS: dict[str, Session] = {
    # 17:00 ET matches the existing collect_eod cron target (CLAUDE.md § Automation).
    # This is the settled, existing pipeline — unchanged by ADR-011.
    EOD: Session(key=EOD, label="End of day", capture_et="17:00", settled=True),
    # 09:45 ET per ADR-011 — a provisional morning check-in, no existing cron yet.
    MORNING: Session(key=MORNING, label="Morning", capture_et="09:45", settled=False),
    # 15:50 ET matches the existing collect_preclose cron target (CLAUDE.md § Automation).
    PRE_CLOSE: Session(key=PRE_CLOSE, label="Pre-close", capture_et="15:50", settled=False),
}

# The existing snapshots/deltas/picks files carry eod semantics unchanged — Option C:
# no migration, no `session` column added to them. Any caller that doesn't yet think
# in terms of multiple sessions should default to this.
DEFAULT_SESSION = EOD


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def is_valid_session(key: str) -> bool:
    """Return True if key is a known session key in SESSIONS."""
    return key in SESSIONS


def is_provisional(key: str) -> bool:
    """Return True if key is a known, non-settled session. Unknown keys return False."""
    session = SESSIONS.get(key)
    return session is not None and not session.settled


def settled_sessions() -> list[str]:
    """Return keys of all settled sessions, in registry order (currently just eod)."""
    return [key for key, session in SESSIONS.items() if session.settled]


def provisional_sessions() -> list[str]:
    """Return keys of all provisional (non-settled) sessions, in registry order."""
    return [key for key, session in SESSIONS.items() if not session.settled]


def assert_provisional(key: str) -> None:
    """Raise ValueError unless key names a provisional session.

    This is the structural guard for ADR-011 Option C: only provisional sessions may
    be written to the future session-keyed provisional stores (WS3/WS5). eod must stay
    exclusively in the existing settled files. Call this at the write boundary of any
    future provisional-store writer to make the "provisional never contaminates
    settled" invariant enforceable in code, not just convention.
    """
    if not is_valid_session(key):
        raise ValueError(f"unknown session key: {key!r}")
    if SESSIONS[key].settled:
        raise ValueError(
            f"session {key!r} is settled (eod) and must not be written to a "
            "provisional store — it belongs exclusively in the existing settled files"
        )


# ---------------------------------------------------------------------------
# Future provisional store key convention (documentation only — no I/O here)
# ---------------------------------------------------------------------------

# The physically-separate provisional stores (created later by WS3/WS5, not by this
# module) are append-only and keyed (date, session, <entity>) — e.g. (date, session,
# name) for group snapshots, (date, session, ticker) for ticker quotes. eod is NOT
# stored here; it stays in the existing files. The exact store location/backend
# (CSV vs Cloudflare D1) for ticker quotes is deferred to WS5's design doc.
PROVISIONAL_KEY_PREFIX = ("date", "session")
