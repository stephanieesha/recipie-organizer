"""
Safety limits for a deployment that anyone with the link can reach. All three
are OFF unless their environment variable is set, so local runs and tests
are never throttled:

  WRITE_LIMIT_PER_MINUTE  max changes (POST/PUT/PATCH/DELETE) per visitor per minute
  DAILY_AI_LIMIT          max automatic recipe extractions per day, across all visitors
  MAX_BULK_LINKS          max links accepted in one bulk import
"""

import os
import time
from collections import defaultdict, deque
from datetime import datetime, timezone


def _int_setting(name: str) -> int:
    try:
        return int(os.environ.get(name, "0"))
    except ValueError:
        return 0


_recent_requests = defaultdict(deque)


def client_ip(request) -> str:
    # Behind Render's proxy the last X-Forwarded-For entry is the address that reached the
    # proxy; earlier entries can be forged by the visitor.
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[-1].strip()
    return request.remote_addr or "unknown"


def too_many_requests(ip: str, now: float = None) -> bool:
    limit = _int_setting("WRITE_LIMIT_PER_MINUTE")
    if limit <= 0:
        return False
    now = time.time() if now is None else now
    window = _recent_requests[ip]
    while window and now - window[0] > 60:
        window.popleft()
    if len(window) >= limit:
        return True
    window.append(now)
    return False


def max_bulk_links() -> int:
    return _int_setting("MAX_BULK_LINKS")


def use_ai_call(conn) -> bool:
    """Counts one automatic extraction against today's cap. False means the cap is used up."""
    limit = _int_setting("DAILY_AI_LIMIT")
    if limit <= 0:
        return True
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    conn.execute(
        "INSERT INTO usage_counters (day, kind, count) VALUES (?, 'ai', 0) ON CONFLICT (day, kind) DO NOTHING",
        (day,),
    )
    cursor = conn.execute(
        "UPDATE usage_counters SET count = count + 1 WHERE day = ? AND kind = 'ai' AND count < ?",
        (day, limit),
    )
    conn.commit()
    return cursor.rowcount == 1
