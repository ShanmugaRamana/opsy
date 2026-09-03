"""Tracks whichever turn is currently being processed, if any.

Single-process, in-memory state - not persisted, same pattern as `permissions.py`'s pending-request
table. Split out from `core.py` (which sets it) so `routers/sessions/router.py` (which reads it, to
guard against switching away from a running chat) doesn't have to import `core.py` and create an
import cycle, since `core.py` itself imports from `routers.sessions.queries`.
"""

_running_turn = None


def get_running_turn():
    return _running_turn


def set_running_turn(session_id, session_name):
    global _running_turn
    _running_turn = {"session_id": session_id, "session_name": session_name}


def clear_running_turn():
    global _running_turn
    _running_turn = None
