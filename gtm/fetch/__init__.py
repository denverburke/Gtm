"""Read-only data pulls from ad platform APIs into clients/<slug>/data/.

Files are written with the same names and headers as the manual exports, so the analysis
modules can't tell (and don't care) whether a human or the API produced them.

Read-only is enforced in four layers. Only the first is a hard guarantee; the rest stop an
agent or a code change from even trying:
  1. The credentials belong to a user with Read only (Google) / Viewer (Microsoft) access.
     The platforms reject any change from that user server-side.
  2. Before every pull, `verify_*_readonly` proves layer 1 holds and refuses to run otherwise.
  3. These modules only ever call reporting/search endpoints (GAQL SELECT, report downloads).
     tests/test_fetch_readonly.py fails the build if a write call is introduced.
  4. .claude/settings.json makes any edit to gtm/fetch/ ask a human first.
"""
import datetime as dt


class NotReadOnlyError(RuntimeError):
    """Raised when credentials can make changes, or read-only status couldn't be proven."""


def periods(days: int, end: dt.date | None = None) -> dict[str, tuple[dt.date, dt.date]]:
    """Current = the last `days` complete days (ending yesterday); previous = the block before it."""
    end = end or dt.date.today() - dt.timedelta(days=1)
    start = end - dt.timedelta(days=days - 1)
    p_end = start - dt.timedelta(days=1)
    return {"current": (start, end), "previous": (p_end - dt.timedelta(days=days - 1), p_end)}
