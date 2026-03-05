from __future__ import annotations

from pathlib import Path


DEFAULT_WINDOW_BYTES = 256 * 1024
MAX_WINDOW_BYTES = 1024 * 1024
DEFAULT_SEARCH_LIMIT = 20
MAX_SEARCH_LIMIT = 100
SEARCH_CHUNK_BYTES = 64 * 1024
PREVIEW_CONTEXT_BYTES = 80


def _clamp(value: int, min_value: int, max_value: int) -> int:
    return max(min_value, min(max_value, value))


def _normalize_limit(limit_bytes: int | None) -> int:
    if limit_bytes is None:
        return DEFAULT_WINDOW_BYTES
    return _clamp(int(limit_bytes), 1, MAX_WINDOW_BYTES)


def _normalize_search_limit(limit: int | None) -> int:
    if limit is None:
        return DEFAULT_SEARCH_LIMIT
    return _clamp(int(limit), 1, MAX_SEARCH_LIMIT)


def _get_file_size(log_path: Path) -> int:
    if not log_path.exists():
        return 0
    try:
        return log_path.stat().st_size
    except OSError:
        return 0


def read_window(
    log_path: Path,
    cursor: int | None = None,
    direction: str = "backward",
    limit_bytes: int | None = None,
) -> dict:
    file_size = _get_file_size(log_path)
    limit = _normalize_limit(limit_bytes)

    if file_size == 0:
        return {
            "file_size": 0,
            "window_start": 0,
            "window_end": 0,
            "next_backward_cursor": None,
            "next_forward_cursor": None,
            "has_more_backward": False,
            "has_more_forward": False,
            "text": "",
        }

    if direction not in {"backward", "forward"}:
        direction = "backward"

    if direction == "backward":
        end = file_size if cursor is None else _clamp(int(cursor), 0, file_size)
        start = max(0, end - limit)
    else:
        start = file_size if cursor is None else _clamp(int(cursor), 0, file_size)
        end = min(file_size, start + limit)

    if start > end:
        start = end

    text = ""
    if log_path.exists() and end > start:
        with log_path.open("rb") as fp:
            fp.seek(start)
            raw = fp.read(end - start)
            text = raw.decode("utf-8", errors="replace")

    has_more_backward = start > 0
    has_more_forward = end < file_size

    return {
        "file_size": file_size,
        "window_start": start,
        "window_end": end,
        "next_backward_cursor": start if has_more_backward else None,
        "next_forward_cursor": end if has_more_forward else None,
        "has_more_backward": has_more_backward,
        "has_more_forward": has_more_forward,
        "text": text,
    }


def _iter_match_offsets(fp, needle: bytes, start: int):
    fp.seek(start)
    overlap = b""
    chunk_start = start
    last_offset = -1

    while True:
        chunk = fp.read(SEARCH_CHUNK_BYTES)
        if not chunk:
            break

        data = overlap + chunk
        data_start = chunk_start - len(overlap)
        search_pos = 0

        while True:
            idx = data.find(needle, search_pos)
            if idx == -1:
                break

            absolute_offset = data_start + idx
            if absolute_offset >= start and absolute_offset != last_offset:
                yield absolute_offset
                last_offset = absolute_offset
            search_pos = idx + 1

        chunk_start += len(chunk)
        overlap = data[-(len(needle) - 1):] if len(needle) > 1 else b""


def _read_preview(fp, file_size: int, offset: int, needle_len: int) -> str:
    preview_start = max(0, offset - PREVIEW_CONTEXT_BYTES)
    preview_end = min(file_size, offset + needle_len + PREVIEW_CONTEXT_BYTES)
    fp.seek(preview_start)
    raw = fp.read(preview_end - preview_start)
    text = raw.decode("utf-8", errors="replace")
    prefix = "..." if preview_start > 0 else ""
    suffix = "..." if preview_end < file_size else ""
    return f"{prefix}{text}{suffix}"


def search_in_log(
    log_path: Path,
    query: str,
    cursor: int | None = None,
    limit: int | None = None,
) -> dict:
    file_size = _get_file_size(log_path)
    normalized_limit = _normalize_search_limit(limit)

    if file_size == 0:
        return {
            "file_size": 0,
            "hits": [],
            "next_cursor": None,
            "has_more": False,
        }

    query = (query or "").strip()
    if not query:
        return {
            "file_size": file_size,
            "hits": [],
            "next_cursor": None,
            "has_more": False,
        }

    needle = query.encode("utf-8", errors="ignore")
    if not needle:
        return {
            "file_size": file_size,
            "hits": [],
            "next_cursor": None,
            "has_more": False,
        }

    start = _clamp(int(cursor or 0), 0, file_size)
    offsets = []

    with log_path.open("rb") as fp:
        for offset in _iter_match_offsets(fp, needle, start):
            offsets.append(offset)
            if len(offsets) >= normalized_limit + 1:
                break

        has_more = len(offsets) > normalized_limit
        visible_offsets = offsets[:normalized_limit]
        next_cursor = offsets[normalized_limit] if has_more else None

        hits = []
        for offset in visible_offsets:
            hits.append(
                {
                    "offset": offset,
                    "preview": _read_preview(fp, file_size, offset, len(needle)),
                }
            )

    return {
        "file_size": file_size,
        "hits": hits,
        "next_cursor": next_cursor,
        "has_more": has_more,
    }
