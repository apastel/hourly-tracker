"""Check GitHub for a newer published Hourly Tracker release."""

from __future__ import annotations

import json
import re
from urllib.request import Request, urlopen

GITHUB_RELEASES_API = (
    "https://api.github.com/repos/apastel/hourly-tracker/releases/latest"
)
RELEASE_PAGE = "https://github.com/apastel/hourly-tracker/releases/latest"
_CURRENT_VERSION = re.compile(
    r"^(?P<release>\d+\.\d+\.\d+)(?P<dev>\.dev\d+)?"
    r"(?:\+[A-Za-z0-9.-]+)?$"
)
_RELEASE_TAG = re.compile(r"^v?(?P<release>\d+\.\d+\.\d+)$")


class UpdateCheckError(Exception):
    """Raised when GitHub's latest release cannot be checked."""


def _version_key(version: str, pattern: re.Pattern[str]) -> tuple[int, ...]:
    match = pattern.fullmatch(version)
    if match is None:
        raise ValueError(f"Unsupported version format: {version}")
    return tuple(int(part) for part in match.group("release").split("."))


def check_for_update(current_version: str) -> str | None:
    """Return the latest release tag when it is newer than the installed version."""
    try:
        current = _CURRENT_VERSION.fullmatch(current_version)
        if current is None:
            raise ValueError(f"Unsupported version format: {current_version}")
        current_key = _version_key(current_version, _CURRENT_VERSION)

        request = Request(
            GITHUB_RELEASES_API,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": f"HourlyTracker/{current_version}",
            },
        )
        with urlopen(request, timeout=5) as response:
            release = json.loads(response.read())
    except (
        OSError,
        TimeoutError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValueError,
    ) as exc:
        raise UpdateCheckError(f"Could not check GitHub for updates: {exc}") from exc

    if not isinstance(release, dict):
        raise UpdateCheckError("GitHub returned an invalid latest-release response")
    tag = release.get("tag_name")
    if not isinstance(tag, str):
        raise UpdateCheckError("GitHub's latest-release response has no tag name")
    try:
        latest_key = _version_key(tag, _RELEASE_TAG)
    except ValueError as exc:
        raise UpdateCheckError(str(exc)) from exc

    is_dev_build = current.group("dev") is not None
    if latest_key > current_key or (latest_key == current_key and is_dev_build):
        return tag
    return None
