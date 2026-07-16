"""tests/test_api_endpoints.py — API endpoint contract tests using FastAPI TestClient."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.conftest import (  # noqa: E402
    SAMPLE_COMPLETE_MYSTERY, MOCK_QC_PASS_RESPONSE, patch_claude,
)


_SAVED_API_KEY = None


def setUpModule():
    """Deny-by-default now enforces auth on non-public /api/ routes (and fails CLOSED
    when unset). Pin a server key so these endpoint CONTRACT tests exercise the
    handlers, not the auth layer; _get_client() sends the matching key by default."""
    global _SAVED_API_KEY
    import core.api
    _SAVED_API_KEY = core.api._API_KEY
    core.api._API_KEY = "test-key-123"


def tearDownModule():
    import core.api
    core.api._API_KEY = _SAVED_API_KEY


def _get_client():
    """Import app and return an authenticated TestClient (sends X-API-Key by default)."""
    from fastapi.testclient import TestClient
    from core.api import app
    return TestClient(app, headers={"X-API-Key": "test-key-123"}, raise_server_exceptions=False)


class TestPublisherEngineEndpoints(unittest.TestCase):
    def setUp(self):
        self.client = _get_client()

    def test_status_200(self):
        r = self.client.get("/api/publisher-engine/status")
        self.assertEqual(r.status_code, 200)

    def test_results_200(self):
        r = self.client.get("/api/publisher-engine/results")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("results", data)

    def test_run_requires_body(self):
        """POST without required fields → 422 Unprocessable Entity."""
        r = self.client.post("/api/publisher-engine/run", json={})
        self.assertIn(r.status_code, (400, 422))


class TestLiteraryQCEndpoints(unittest.TestCase):
    def setUp(self):
        self.client = _get_client()

    def test_results_200(self):
        r = self.client.get("/api/literary-qc/results")
        self.assertEqual(r.status_code, 200)

    def test_review_post(self):
        """POST /api/literary-qc/review with a sample manuscript."""
        with patch_claude({"score": MOCK_QC_PASS_RESPONSE}):
            r = self.client.post("/api/literary-qc/review", json={
                "manuscript": SAMPLE_COMPLETE_MYSTERY,
                "title": "API Test Book",
                "genre": "mystery",
            })
        self.assertIn(r.status_code, (200, 202))

    def test_full_analysis_post(self):
        """POST /api/literary-qc/full-analysis returns chapter_count."""
        with patch_claude({"score": MOCK_QC_PASS_RESPONSE}):
            r = self.client.post("/api/literary-qc/full-analysis", json={
                "manuscript": SAMPLE_COMPLETE_MYSTERY,
                "title": "Full Analysis Test",
                "genre": "mystery",
            })
        self.assertIn(r.status_code, (200, 202))
        if r.status_code == 200:
            data = r.json()
            self.assertIn("chapter_count", data)

    def test_rewrite_queue_200(self):
        """GET /api/literary-qc/rewrite-queue returns 200."""
        r = self.client.get("/api/literary-qc/rewrite-queue")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        # Should be a list (possibly empty)
        self.assertIsInstance(data.get("queue", data), list)


class TestVolumesEndpoints(unittest.TestCase):
    def setUp(self):
        self.client = _get_client()

    def test_status_200(self):
        r = self.client.get("/api/volumes/status")
        self.assertEqual(r.status_code, 200)

    def test_scan_200(self):
        r = self.client.get("/api/volumes/scan")
        self.assertIn(r.status_code, (200, 202))

    def test_complete_requires_body(self):
        """POST /api/volumes/complete without required params → 422."""
        r = self.client.post("/api/volumes/complete", json={})
        self.assertIn(r.status_code, (400, 422))


class TestContinuityEndpoints(unittest.TestCase):
    def setUp(self):
        self.client = _get_client()

    def test_extract_bible_missing_path(self):
        """POST /api/continuity/extract-bible with bad path → 422 or error dict."""
        r = self.client.post("/api/continuity/extract-bible", json={
            "manuscript_path": "/nonexistent/path/does_not_exist.md"
        })
        # Acceptable: 404, 422, 400, or 200 with error field
        self.assertIn(r.status_code, (200, 400, 404, 422, 500))
        if r.status_code == 200:
            data = r.json()
            # Should have an error indicator, not a valid bible
            self.assertTrue(
                "error" in data or data.get("characters") is None or data == {},
                f"Expected error for nonexistent path, got: {data}"
            )

    def test_check_requires_body(self):
        """POST /api/continuity/check without required fields → 422."""
        r = self.client.post("/api/continuity/check", json={})
        self.assertIn(r.status_code, (400, 422))


if __name__ == "__main__":
    unittest.main(verbosity=2)
