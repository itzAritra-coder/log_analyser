"""Log analyzer.

Everything here works on *streams*: lines are consumed one at a time and never
stored, so memory use depends on the number of distinct services, not on the
size of the log.
"""
import codecs
import re
from collections import Counter
from datetime import datetime
from typing import Iterable, Iterator, Optional

LEVELS = ("DEBUG", "INFO", "WARN", "ERROR", "FATAL")
ERROR_LEVELS = {"ERROR"}          # add "FATAL" here to count it as an error too
MAX_LINE_CHARS = 64 * 1024        # longer lines are counted as unparseable
OVERLONG = "<line exceeded maximum length>"

_LINE_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2}) (%s) (\S+) (.+)$" % "|".join(LEVELS)
)


def parse_line(line: str) -> Optional[dict]:
    """Return parsed fields, or None if the line doesn't match the format."""
    m = _LINE_RE.match(line.lstrip("\ufeff").strip())  # tolerate BOM / CRLF
    if not m:
        return None
    date, time, level, service, message = m.groups()
    try:  # reject impossible timestamps such as 2026-09-99 or 25:00:00
        datetime.fromisoformat(f"{date} {time}")
    except ValueError:
        return None
    return {"level": level, "service": service, "message": message}


def analyze(lines: Iterable[str]) -> dict:
    """Summarise any iterable of log lines (list, open file, generator...).

    Blank lines are ignored entirely.
    """
    errors = Counter()
    services = set()
    total = unparseable = 0

    for raw in lines:
        if not raw.strip():
            continue
        total += 1
        entry = parse_line(raw)
        if entry is None:
            unparseable += 1
            continue
        services.add(entry["service"])
        if entry["level"] in ERROR_LEVELS:
            errors[entry["service"]] += 1

    # Include zero-error services; sort by count desc, then name.
    per_service = {s: errors.get(s, 0) for s in services}
    per_service = dict(sorted(per_service.items(), key=lambda kv: (-kv[1], kv[0])))
    top = next(iter(per_service)) if per_service and max(per_service.values()) > 0 else None

    return {
        "lines_processed": total,
        "unparseable_lines": unparseable,
        "errors_by_service": per_service,
        "top_offender": top,
    }


def iter_lines(chunks: Iterable[bytes], max_line_chars: int = MAX_LINE_CHARS) -> Iterator[str]:
    """Turn a stream of byte chunks (any size) into text lines.

    Handles lines and multi-byte UTF-8 characters split across chunk boundaries.
    A line longer than `max_line_chars` is yielded once as OVERLONG (which the
    parser rejects) and the rest of that line is discarded, so a hostile input
    with no newlines cannot exhaust memory.
    """
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    buf = ""
    skipping = False  # True while discarding the tail of an overlong line

    for chunk in chunks:
        text = decoder.decode(chunk)
        if skipping:
            nl = text.find("\n")
            if nl == -1:
                continue
            text, skipping = text[nl + 1:], False
        buf += text
        *complete, buf = buf.split("\n")
        for line in complete:
            yield line if len(line) <= max_line_chars else OVERLONG
        if len(buf) > max_line_chars:
            yield OVERLONG
            buf, skipping = "", True

    buf += decoder.decode(b"", final=True)
    if buf and not skipping:
        yield buf if len(buf) <= max_line_chars else OVERLONG