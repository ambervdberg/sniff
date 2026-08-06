#!/usr/bin/env python3
"""Unit tests for sniff.versioning: get_version() and the on-disk PyPI cache.

test_cli.py's SniffUpgradeCaveatTest already exercises _latest_released_version
and _upgrade_available_caveat end to end (fresh cache, stale cache, network
failure, env-var opt-out). This file covers what that one doesn't touch:
get_version() itself and its two sources (_installed_package_version,
_pyproject_version), _version_key's parsing, _version_cache_path's four
cross-platform branches, and the cache read/write helpers
(_cached_latest_version / _write_cached_latest_version) in isolation, including
the corrupt-cache guard.

No test here ever reaches the network: every case that could touches only a
tempdir cache file, never urllib.

Run: python -m pytest tests/test_versioning.py -q
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from unittest import mock

from sniff import versioning


class GetVersionTest(unittest.TestCase):
    """get_version(): installed package first, pyproject.toml second, else
    'unknown'. Never raises."""

    def _get_version(self, installed, pyproject):
        with mock.patch.object(versioning, "_installed_package_version", return_value=installed), \
                mock.patch.object(versioning, "_pyproject_version", return_value=pyproject):
            return versioning.get_version()

    def test_prefers_the_installed_package_version(self):
        self.assertEqual(self._get_version("1.2.3", "9.9.9"), "1.2.3")

    def test_falls_back_to_pyproject_when_no_package_is_installed(self):
        self.assertEqual(self._get_version(None, "1.2.3"), "1.2.3")

    def test_falls_back_to_unknown_when_neither_source_has_an_answer(self):
        self.assertEqual(self._get_version(None, None), "unknown")


class InstalledPackageVersionTest(unittest.TestCase):
    """_installed_package_version(): reads importlib.metadata, trying the
    current distribution name before the legacy one."""

    def test_returns_the_new_distribution_name_version(self):
        with mock.patch("importlib.metadata.version", return_value="1.2.3") as pkg_version:
            self.assertEqual(versioning._installed_package_version(), "1.2.3")
        pkg_version.assert_called_with("sniff-smells")

    def test_falls_back_to_the_legacy_distribution_name(self):
        from importlib.metadata import PackageNotFoundError

        def fake_version(dist):
            if dist == "sniff-smells":
                raise PackageNotFoundError(dist)
            return "0.9.0"

        with mock.patch("importlib.metadata.version", side_effect=fake_version):
            self.assertEqual(versioning._installed_package_version(), "0.9.0")

    def test_returns_none_when_neither_distribution_is_installed(self):
        from importlib.metadata import PackageNotFoundError

        with mock.patch("importlib.metadata.version", side_effect=PackageNotFoundError()):
            self.assertIsNone(versioning._installed_package_version())


class PyprojectVersionTest(unittest.TestCase):
    """_pyproject_version(): reads [project] version from a source checkout's
    pyproject.toml, or None when this isn't one."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._patch = mock.patch.object(versioning, "_REPO_ROOT", self.tmp.name)
        self._patch.start()
        self.addCleanup(self._patch.stop)

    def _write_pyproject(self, text):
        path = os.path.join(self.tmp.name, "pyproject.toml")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)

    def test_reads_the_version_line(self):
        self._write_pyproject('[project]\nname = "sniff-smells"\nversion = "0.13.0"\n')
        self.assertEqual(versioning._pyproject_version(), "0.13.0")

    def test_returns_none_when_pyproject_toml_is_missing(self):
        # No file written: this is not a source checkout at all.
        self.assertIsNone(versioning._pyproject_version())

    def test_returns_none_when_the_file_has_no_version_line(self):
        self._write_pyproject('[project]\nname = "sniff-smells"\n')
        self.assertIsNone(versioning._pyproject_version())

    def test_does_not_match_a_version_key_that_is_not_at_the_start_of_its_line(self):
        # `(?m)^version\s*=` is anchored to column 0 so it targets [project]'s own
        # version, not some nested table's `other_version = "..."` line.
        self._write_pyproject('[project]\nname = "x"\nother_version = "9.9.9"\n')
        self.assertIsNone(versioning._pyproject_version())


class VersionKeyTest(unittest.TestCase):
    """_version_key(): the numeric tuple used to compare versions as numbers,
    not strings, so 0.9.0 < 0.13.0."""

    def test_parses_a_plain_semver_string(self):
        self.assertEqual(versioning._version_key("0.13.0"), (0, 13, 0))

    def test_numeric_comparison_beats_lexical_comparison(self):
        self.assertLess(versioning._version_key("0.9.0"), versioning._version_key("0.13.0"))

    def test_ignores_a_trailing_prerelease_suffix(self):
        self.assertEqual(versioning._version_key("0.13.0rc1"), (0, 13, 0))

    def test_returns_none_for_a_string_with_no_numeric_prefix(self):
        self.assertIsNone(versioning._version_key("unknown"))


class VersionCachePathTest(unittest.TestCase):
    """_version_cache_path(): the one cross-platform branch in this module.

    Every other test in this file (and in test_cli.py) patches this function
    away entirely, so a swapped branch or a dropped 'sniff' path segment would
    ship green on every OS's CI run without this class. `os.name` is patched
    directly rather than relying on the host's actual platform, so all four
    branches run on whichever OS this suite happens to execute on."""

    def _cache_path(self, *, nt, env):
        with mock.patch.object(versioning.os, "name", "nt" if nt else "posix"), \
                mock.patch.dict(os.environ, env, clear=False):
            for stale_key in ("LOCALAPPDATA", "XDG_CACHE_HOME"):
                if stale_key not in env:
                    os.environ.pop(stale_key, None)
            return versioning._version_cache_path()

    def test_windows_uses_localappdata_when_set(self):
        path = self._cache_path(nt=True, env={"LOCALAPPDATA": "C:\\Users\\amber\\AppData\\Local"})
        self.assertEqual(path, os.path.join("C:\\Users\\amber\\AppData\\Local", "sniff", "version-cache.json"))

    def test_windows_falls_back_to_home_when_localappdata_is_unset(self):
        with mock.patch.object(versioning.os.path, "expanduser", return_value="C:\\Users\\amber"):
            path = self._cache_path(nt=True, env={})
        self.assertEqual(path, os.path.join("C:\\Users\\amber", "sniff", "version-cache.json"))

    def test_posix_uses_xdg_cache_home_when_set(self):
        path = self._cache_path(nt=False, env={"XDG_CACHE_HOME": "/custom/cache"})
        self.assertEqual(path, os.path.join("/custom/cache", "sniff", "version-cache.json"))

    def test_posix_falls_back_to_dot_cache_when_xdg_cache_home_is_unset(self):
        with mock.patch.object(versioning.os.path, "expanduser", return_value="/home/amber/.cache"):
            path = self._cache_path(nt=False, env={})
        self.assertEqual(path, os.path.join("/home/amber/.cache", "sniff", "version-cache.json"))


class CachedLatestVersionTest(unittest.TestCase):
    """_cached_latest_version(): read side of the on-disk PyPI cache, including
    the corrupt-cache guard that must fall through to a network retry."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cache_path = os.path.join(self.tmp.name, "version-cache.json")
        self._patch = mock.patch.object(versioning, "_version_cache_path", return_value=self.cache_path)
        self._patch.start()
        self.addCleanup(self._patch.stop)

    def _write_cache(self, payload):
        with open(self.cache_path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)

    def test_missing_cache_file_is_a_miss(self):
        self.assertIs(versioning._cached_latest_version(), versioning._CACHE_MISS)

    def test_fresh_cache_returns_the_stored_value(self):
        self._write_cache({"checked_at": time.time(), "latest": "0.13.0"})
        self.assertEqual(versioning._cached_latest_version(), "0.13.0")

    def test_fresh_cache_can_store_a_null_latest(self):
        # A prior check that genuinely found PyPI unreachable is a valid cached
        # answer, distinct from "no cache at all".
        self._write_cache({"checked_at": time.time(), "latest": None})
        self.assertIsNone(versioning._cached_latest_version())

    def test_stale_cache_is_a_miss(self):
        expired = time.time() - versioning._CACHE_TTL_SECONDS - 1
        self._write_cache({"checked_at": expired, "latest": "0.13.0"})
        self.assertIs(versioning._cached_latest_version(), versioning._CACHE_MISS)

    def test_malformed_json_is_a_miss(self):
        with open(self.cache_path, "w", encoding="utf-8") as fh:
            fh.write("{not json")
        self.assertIs(versioning._cached_latest_version(), versioning._CACHE_MISS)

    def test_non_string_non_null_latest_is_a_miss(self):
        # A hand-edited or half-written cache file: `latest` survived JSON
        # parsing but is neither a version string nor the null "checked, PyPI
        # was unreachable" sentinel, so it must not be handed to callers as if
        # it were one of those two valid types.
        self._write_cache({"checked_at": time.time(), "latest": 123})
        self.assertIs(versioning._cached_latest_version(), versioning._CACHE_MISS)

    def test_missing_keys_are_a_miss_not_a_crash(self):
        self._write_cache({"checked_at": time.time()})  # no "latest" key
        self.assertIs(versioning._cached_latest_version(), versioning._CACHE_MISS)


class WriteCachedLatestVersionTest(unittest.TestCase):
    """_write_cached_latest_version(): write side of the on-disk PyPI cache."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_write_then_read_round_trips_through_cached_latest_version(self):
        cache_path = os.path.join(self.tmp.name, "sniff", "version-cache.json")
        with mock.patch.object(versioning, "_version_cache_path", return_value=cache_path):
            versioning._write_cached_latest_version("0.13.0")
            self.assertEqual(versioning._cached_latest_version(), "0.13.0")

    def test_creates_missing_parent_directories(self):
        # The real cache path is `<cache root>/sniff/version-cache.json`; the
        # `sniff` directory does not exist yet on a machine's first run.
        cache_path = os.path.join(self.tmp.name, "sniff", "version-cache.json")
        with mock.patch.object(versioning, "_version_cache_path", return_value=cache_path):
            versioning._write_cached_latest_version("0.13.0")
        self.assertTrue(os.path.exists(cache_path))

    def test_write_swallows_errors_instead_of_raising(self):
        # The cache is a pure optimization: a read-only filesystem or a
        # permissions error must never surface as an error the caller has to
        # handle, since prime's version check must stay silent on failure.
        cache_path = os.path.join(self.tmp.name, "sniff", "version-cache.json")
        with mock.patch.object(versioning, "_version_cache_path", return_value=cache_path), \
                mock.patch.object(versioning.os, "makedirs", side_effect=OSError("read-only fs")):
            versioning._write_cached_latest_version("0.13.0")  # must not raise
        self.assertFalse(os.path.exists(cache_path))


if __name__ == "__main__":
    unittest.main(verbosity=2)
