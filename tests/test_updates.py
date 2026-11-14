from __future__ import annotations

import io
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hourly_tracker.updates import UpdateCheckError, check_for_update


class UpdateCheckTest(unittest.TestCase):
    def test_returns_a_newer_release_for_stable_and_development_builds(self):
        for current_version in ("1.2.0", "1.3.0.dev4+gabcdef"):
            with self.subTest(current_version=current_version):
                response = io.BytesIO(
                    json.dumps({"tag_name": "v1.3.0"}).encode("utf-8")
                )
                with mock.patch(
                    "hourly_tracker.updates.urlopen",
                    return_value=response,
                ) as urlopen:
                    self.assertEqual(check_for_update(current_version), "v1.3.0")
                urlopen.assert_called_once()

    def test_does_not_report_same_or_older_releases(self):
        for current_version, tag in (
            ("1.3.0", "v1.3.0"),
            ("1.3.1.dev4+gabcdef", "v1.3.0"),
        ):
            with self.subTest(current_version=current_version, tag=tag):
                response = io.BytesIO(json.dumps({"tag_name": tag}).encode("utf-8"))
                with mock.patch(
                    "hourly_tracker.updates.urlopen",
                    return_value=response,
                ):
                    self.assertIsNone(check_for_update(current_version))

    def test_rejects_unexpected_release_tag(self):
        response = io.BytesIO(
            json.dumps({"tag_name": "hourly-tracker-next"}).encode("utf-8")
        )
        with mock.patch("hourly_tracker.updates.urlopen", return_value=response):
            with self.assertRaises(UpdateCheckError):
                check_for_update("1.2.0")
