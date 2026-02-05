"""
Unified time utilities for consistent timezone handling.
Always use these functions instead of raw datetime operations.
"""
import zoneinfo
from datetime import datetime, timedelta
from typing import Optional
from django.utils import timezone
from django.conf import settings


def get_local_timezone() -> zoneinfo.ZoneInfo:
    """Get the configured local timezone."""
    return zoneinfo.ZoneInfo(settings.TIME_ZONE)


def now() -> datetime:
    """Get current timezone-aware datetime."""
    return timezone.now()


def localtime(dt: Optional[datetime] = None) -> datetime:
    """Convert datetime to local timezone. If no dt provided, returns current local time."""
    if dt is None:
        dt = timezone.now()
    return timezone.localtime(dt)


def format_datetime(dt: datetime, fmt: str = '%Y-%m-%d %H:%M:%S') -> str:
    """Format datetime to string in local timezone."""
    local_dt = localtime(dt)
    return local_dt.strftime(fmt)


def format_local_now(fmt: str = '%Y-%m-%d %H:%M:%S') -> str:
    """Format current local time to string."""
    return format_datetime(timezone.now(), fmt)


def parse_datetime(dt_str: str, fmt: str = '%Y-%m-%d %H:%M:%S') -> datetime:
    """
    Parse string to timezone-aware datetime in local timezone.
    The input string is assumed to be in local timezone.
    """
    naive_dt = datetime.strptime(dt_str, fmt)
    tz = get_local_timezone()
    return naive_dt.replace(tzinfo=tz)


def is_weekend(dt: Optional[datetime] = None) -> bool:
    """Check if the given datetime is a weekend."""
    if dt is None:
        dt = localtime()
    return dt.weekday() >= 5


def get_date_string(dt: Optional[datetime] = None, fmt: str = '%Y%m%d') -> str:
    """Get date string in specified format, defaults to YYYYMMDD."""
    if dt is None:
        dt = localtime()
    return dt.strftime(fmt)
