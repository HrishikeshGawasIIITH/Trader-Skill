"""Load a script from a skill folder (the folder names have hyphens).

load(folder, name)          -> the script as it ships (NSE, IST, Rs).
load(folder, name, us=True) -> the same script with the US market settings
                               put back. The fixture-based tests use this mode,
                               because their fixtures are US sessions.
"""

import datetime
import importlib.util
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(ROOT, "tests", "fixtures")


def _nth_sunday(year, month, n):
    d = datetime.date(year, month, 1)
    d += datetime.timedelta(days=(6 - d.weekday()) % 7)
    return d + datetime.timedelta(weeks=n - 1)


def us_offset(utc):
    y = utc.year
    start = datetime.datetime.combine(_nth_sunday(y, 3, 2), datetime.time(7, 0))
    end = datetime.datetime.combine(_nth_sunday(y, 11, 1), datetime.time(6, 0))
    return -4 if start <= utc.replace(tzinfo=None) < end else -5


def us_to_local(utc):
    return utc.replace(tzinfo=None) + datetime.timedelta(hours=us_offset(utc))


def us_local_to_utc(local):
    for off in (-4, -5):
        utc = local - datetime.timedelta(hours=off)
        if us_offset(utc) == off:
            return utc
    return local + datetime.timedelta(hours=5)


US_HOLIDAYS = {
    "2026-01-01": "New Year's Day", "2026-01-19": "Martin Luther King, Jr. Day",
    "2026-02-16": "Washington's Birthday", "2026-04-03": "Good Friday",
    "2026-05-25": "Memorial Day", "2026-06-19": "Juneteenth National Independence Day",
    "2026-07-03": "Independence Day (observed)", "2026-09-07": "Labor Day",
    "2026-11-26": "Thanksgiving Day", "2026-12-25": "Christmas Day",
    "2027-01-01": "New Year's Day", "2027-01-18": "Martin Luther King, Jr. Day",
    "2027-02-15": "Washington's Birthday", "2027-03-26": "Good Friday",
    "2027-05-31": "Memorial Day", "2027-06-18": "Juneteenth National Independence Day (observed)",
    "2027-07-05": "Independence Day (observed)", "2027-09-06": "Labor Day",
    "2027-11-25": "Thanksgiving Day", "2027-12-24": "Christmas Day (observed)",
}
US_EARLY_CLOSE = {"2026-11-27": "day after Thanksgiving", "2026-12-24": "Christmas Eve",
                  "2027-11-26": "day after Thanksgiving"}

# Every script with a market clock uses these module-level names.
US = {
    "market_offset": us_offset, "to_local": us_to_local, "local_to_utc": us_local_to_utc,
    "OPEN": datetime.time(9, 30), "CLOSE": datetime.time(16, 0), "EARLY": datetime.time(13, 0),
    "HOLIDAYS": US_HOLIDAYS, "EARLY_CLOSE": US_EARLY_CLOSE, "CALENDAR_YEARS": (2026, 2027),
    "CUR": "$", "SUFFIX": "", "TZ_LABEL": "New York", "MARKET": "NYSE",
}


def us_market(mod):
    for k, v in US.items():
        if hasattr(mod, k):
            setattr(mod, k, v)
    return mod


def load(folder, name, us=False):
    path = os.path.join(ROOT, folder, name + ".py")
    spec = importlib.util.spec_from_file_location("trader_" + name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return us_market(mod) if us else mod
