"""Resolve sniff's own version, and warn when a newer release is on PyPI.

`get_version()` answers "what version is this" from whatever source is
available: the installed package's metadata first, the source checkout's
pyproject.toml second, and 'unknown' only if neither exists. The PyPI check
below is a separate concern layered on top of that: `_upgrade_available_caveat`
tells `prime` when the installed version has fallen behind the latest release,
consulting a 4-hour on-disk cache before ever touching the network so a
session-start check stays cheap and, on a slow or offline network, silent.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.request

from sniff import discovery

# Repo root, one level above skills/ (discovery.SKILLS_ROOT is skills/).
# Only present in a source checkout; an installed package has neither file,
# so version/consistency checks fall back to package metadata or skip.
_REPO_ROOT = os.path.dirname(discovery.SKILLS_ROOT)


def _pyproject_version() -> str | None:
    """Read [project] version from pyproject.toml, or None if not a source checkout."""
    path = os.path.join(_REPO_ROOT, "pyproject.toml")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return None
    match = re.search(r'(?m)^version\s*=\s*"([^"]+)"', text)
    return match.group(1) if match else None


def _installed_package_version() -> str | None:
    """Version reported by importlib.metadata for the installed distribution
    (`sniff-smells`, or the legacy `sniff` name), or None."""
    try:
        from importlib.metadata import PackageNotFoundError, version as pkg_version
        for dist in ("sniff-smells", "sniff"):
            try:
                return pkg_version(dist)
            except PackageNotFoundError:
                continue
        return None
    except ImportError:
        return None


def get_version() -> str:
    """Installed package version if `sniff` is installed, else the source checkout's
    pyproject.toml version. Falls back to 'unknown' rather than crashing."""
    return _installed_package_version() or _pyproject_version() or "unknown"


# The published package is the only thing a user can upgrade to, so the release
# check asks PyPI directly. `prime` runs at session start, so the call is bounded
# by a short timeout and every failure is silent: a slow or offline network must
# cost a bounded wait, never a stalled session or an error the user has to read.
_PYPI_RELEASE_URL = "https://pypi.org/pypi/sniff-smells/json"
_PYPI_TIMEOUT_SECONDS = 1.5

# Escape hatch for offline machines, sandboxed CI, and the test suite, which must
# never depend on network reachability.
_SKIP_CHECK_ENV_VAR = "SNIFF_NO_VERSION_CHECK"

# `prime` runs at every agent session start, so a naive implementation would hit
# PyPI once per session. An on-disk cache turns that into at most once per 4
# hours per machine, which is frequent enough to announce a release promptly and
# rare enough that a busy day of sessions costs one request, not dozens.
_CACHE_TTL_SECONDS = 4 * 60 * 60
_CACHE_FILENAME = "version-cache.json"

# Sentinel distinguishing "cache read, but stale or absent" from a cached value of
# None (a prior check that genuinely found PyPI unreachable). A bare None cannot
# serve as the miss marker because None is itself a valid cached answer.
_CACHE_MISS = object()


def _version_cache_path() -> str:
    """Where the cached PyPI answer lives, one file per machine.

    Windows has no XDG convention, so it gets its own branch pointed at
    `%LOCALAPPDATA%`; everywhere else follows the XDG cache directory spec,
    defaulting to `~/.cache` when `XDG_CACHE_HOME` is unset. A seam (rather than
    a hardcoded path) so tests can redirect it into a temp directory instead of
    touching the real machine cache."""
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    else:
        base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return os.path.join(base, "sniff", _CACHE_FILENAME)


def _cached_latest_version() -> object:
    """The cached latest-version answer if it's still fresh, else `_CACHE_MISS`.

    Any failure while reading (missing file, malformed JSON, missing keys) is
    treated as a miss rather than an error: a corrupt cache must fall through to
    the network, the same silent-failure posture the network call itself has. A
    `latest` value that survived JSON parsing but isn't a string or None (for
    example a hand-edited or half-written cache file) is corruption of the same
    kind, so it is rejected the same way rather than handed to callers that
    expect one of those two types."""
    try:
        with open(_version_cache_path(), encoding="utf-8") as fh:
            cache = json.load(fh)
        age_seconds = time.time() - cache["checked_at"]
        if age_seconds >= _CACHE_TTL_SECONDS:
            return _CACHE_MISS
        latest = cache["latest"]
        return latest if isinstance(latest, (str, type(None))) else _CACHE_MISS
    except Exception:
        return _CACHE_MISS


def _write_cached_latest_version(latest: str | None) -> None:
    """Persist `latest` as this machine's answer, timestamped now.

    Errors (read-only filesystem, missing permissions, races) are swallowed: the
    cache is a pure optimization, so failing to write it must never surface as an
    error the user has to read."""
    try:
        path = _version_cache_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"checked_at": time.time(), "latest": latest}, fh)
    except Exception:
        pass


def _version_key(version: str) -> tuple[int, ...] | None:
    """Leading numeric release segments of `version`, for ordering.

    Compares as ints, not strings, so 0.9.0 sorts below 0.13.0. Returns None when
    the string has no numeric prefix at all, which keeps an unparseable version
    'unknown' instead of silently comparing as 0."""
    match = re.match(r"(\d+(?:\.\d+)*)", version.strip())
    if not match:
        return None
    return tuple(int(part) for part in match.group(1).split("."))


def _latest_released_version() -> str | None:
    """Newest sniff-smells version on PyPI, or None if it can't be determined.

    Consults the on-disk cache first: a fresh answer (checked within the last 4
    hours) is returned without touching the network at all. Only a stale or
    missing cache reaches PyPI, and that fresh answer is written back afterward
    so the next call within the window is free again."""
    if os.environ.get(_SKIP_CHECK_ENV_VAR):
        return None

    cached = _cached_latest_version()
    if cached is not _CACHE_MISS:
        return cached

    # PyPI serves this endpoint through a CDN that can keep answering with the
    # previous release for a while after an upload. Revalidating costs nothing at
    # one call per 4-hour window and is the difference between warning right
    # after a release and staying silent through it.
    request = urllib.request.Request(_PYPI_RELEASE_URL, headers={"Cache-Control": "no-cache"})
    try:
        with urllib.request.urlopen(request, timeout=_PYPI_TIMEOUT_SECONDS) as response:
            payload = json.load(response)
        latest = payload["info"]["version"]
        latest = latest if isinstance(latest, str) else None
    except Exception:
        # Deliberately broad: unreachable host, TLS failure, timeout, HTTP error,
        # malformed JSON and missing keys are all the same non-event here. An
        # optional courtesy check must never be able to break `sniff prime`.
        latest = None

    _write_cached_latest_version(latest)
    return latest


def _upgrade_available_caveat(installed: str | None) -> str | None:
    """Caveat naming a newer published release, or None when the installed version
    is current, unknown, or PyPI could not be reached."""
    if not installed:
        return None

    installed_key = _version_key(installed)
    if installed_key is None:
        return None

    latest = _latest_released_version()
    if latest is None:
        return None

    latest_key = _version_key(latest)
    if latest_key is None or latest_key <= installed_key:
        return None

    return (
        f"sniff {latest} is available (installed: {installed}); "
        "upgrade with `uv tool upgrade sniff-smells` (or `pip install -U sniff-smells`)"
    )
