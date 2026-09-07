from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from youtube_pipeline.api import create_app, paths
from youtube_pipeline.api.auth import AuthSettings


class ApiAuthTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.paths = mock.patch.object(paths, "_BACKEND_ROOT", self.root)
        self.paths.start()
        self.app = create_app(auth_settings=AuthSettings(
            required=True,
            tokens={"alice-token": "alice", "bob-token": "bob"},
            trusted_header=None,
            allow_query_token=False,
        ))
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        self.paths.stop()
        self.tmp.cleanup()

    def test_missing_credentials_are_unauthorized(self) -> None:
        response = self.client.get("/api/channels")
        self.assertEqual(response.status_code, 401)

    def test_wrong_user_is_forbidden(self) -> None:
        response = self.client.get(
            "/api/channels", params={"user_id": "bob"},
            headers={"Authorization": "Bearer alice-token"},
        )
        self.assertEqual(response.status_code, 403)

    def test_allowed_user_is_server_derived_and_can_register_and_list(self) -> None:
        response = self.client.post(
            "/api/channels",
            json={"channel_id": "main", "youtube_channel_id": "UCmain", "title": "Main"},
            headers={"Authorization": "Bearer alice-token"},
        )
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["channel"]["user_id"], "alice")

        response = self.client.get(
            "/api/channels", headers={"Authorization": "Bearer alice-token"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual([c["user_id"] for c in response.json()["channels"]], ["alice"])

    def test_unscoped_legacy_operations_are_disabled(self) -> None:
        headers = {"Authorization": "Bearer alice-token"}
        self.assertEqual(self.client.get("/api/config", headers=headers).status_code, 400)
        self.assertEqual(self.client.get("/api/runs", headers=headers).status_code, 400)
        self.assertEqual(self.client.post("/api/platform/reindex", headers=headers).status_code, 403)

    def test_health_remains_public(self) -> None:
        self.assertEqual(self.client.get("/api/health").status_code, 200)


if __name__ == "__main__":
    unittest.main()
