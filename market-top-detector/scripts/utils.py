"""
Market Top Detector - Shared Utilities

Common helper functions used across multiple modules.
"""

from datetime import date, timedelta


def count_business_days(start_date: date, end_date: date) -> int:
    """Count weekdays between start (exclusive) and end (inclusive).

    Friday to Monday = 1 business day. NSE trading holidays are not
    subtracted, so the count can be a little high around holidays.
    Returns -1 if start_date > end_date (future date).
    """
    if start_date > end_date:
        return -1
    count = 0
    d = start_date
    while d < end_date:
        d += timedelta(days=1)
        if d.weekday() < 5:
            count += 1
    return count
