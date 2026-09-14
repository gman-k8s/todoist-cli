import re

_DURATION_LABEL_RE = re.compile(r"^(\d+[mhd])+$")
_DURATION_UNIT_MINUTES = {"m": 1, "h": 60, "d": 1440}


def is_valid_duration_label(label: str) -> bool:
    """One or more <number><unit> groups (m/h/d), e.g. '30m', '2h30m', '1d2h30m'."""
    return bool(_DURATION_LABEL_RE.fullmatch(label))


def duration_minutes(label: str) -> int:
    return sum(
        int(n) * _DURATION_UNIT_MINUTES[unit]
        for n, unit in re.findall(r"(\d+)([mhd])", label)
    )
