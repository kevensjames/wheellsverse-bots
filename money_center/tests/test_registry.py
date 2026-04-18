#!/usr/bin/env python3
"""
money_center/tests/test_registry.py
─────────────────────────────────────────────────────────────────────────────
One unit test per public registry.py function.
Run with: python -m pytest money_center/tests/ -v
─────────────────────────────────────────────────────────────────────────────
"""

import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

# Add project root to path
ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))


# ─── Test helpers ─────────────────────────────────────────────────────────────

def _make_asset(**kwargs) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    base = {
        "id": "test_asset",
        "name": "Test Asset",
        "category": "service",
        "description": "A test asset.",
        "revenue_model": "consulting",
        "monthly_estimate_usd": {"low": 100, "mid": 500, "high": 1000},
        "time_to_first_revenue_days": 7,
        "status": "idle",
        "last_run": None,
        "last_stop": None,
        "last_revenue_check": None,
        "total_revenue_usd": 0,
        "run_command": "echo start",
        "stop_command": "echo stop",
        "working_dir": "/tmp",
        "tags": ["test"],
        "notes": "",
        "created_at": now,
        "updated_at": now,
    }
    base.update(kwargs)
    return base


# ─── Tests ────────────────────────────────────────────────────────────────────

class TestValidate(unittest.TestCase):
    def setUp(self):
        from money_center import registry as reg
        self.reg = reg

    def test_valid_asset_returns_no_errors(self):
        errors = self.reg.validate(_make_asset())
        self.assertEqual(errors, [])

    def test_missing_required_field(self):
        a = _make_asset()
        del a["name"]
        errors = self.reg.validate(a)
        self.assertTrue(any("name" in e for e in errors))

    def test_invalid_category(self):
        errors = self.reg.validate(_make_asset(category="banana"))
        self.assertTrue(any("category" in e for e in errors))

    def test_invalid_status(self):
        errors = self.reg.validate(_make_asset(status="unknown"))
        self.assertTrue(any("status" in e for e in errors))

    def test_invalid_monthly_estimate_missing_keys(self):
        a = _make_asset()
        a["monthly_estimate_usd"] = {"low": 0}  # missing mid, high
        errors = self.reg.validate(a)
        self.assertTrue(any("monthly_estimate_usd" in e for e in errors))


class TestLoadSave(unittest.TestCase):
    def setUp(self):
        from money_center import registry as reg
        self.reg = reg

    def _patch_paths(self, tmp_dir: Path):
        assets_file = tmp_dir / "assets.json"
        backup_file = tmp_dir / "assets.backup.json"
        return (
            patch.object(self.reg, "ASSETS_FILE", assets_file),
            patch.object(self.reg, "BACKUP_FILE", backup_file),
            patch.object(self.reg, "check_ssd", return_value=True),
        )

    def test_save_and_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            assets_file = tmp_path / "assets.json"
            backup_file = tmp_path / "assets.backup.json"

            with (patch.object(self.reg, "ASSETS_FILE", assets_file),
                  patch.object(self.reg, "BACKUP_FILE", backup_file),
                  patch.object(self.reg, "check_ssd", return_value=True),
                  patch.object(self.reg, "require_ssd")):

                assets = [_make_asset()]
                self.reg.save(assets)
                self.assertTrue(assets_file.exists())

                loaded = self.reg.load()
                self.assertEqual(len(loaded), 1)
                self.assertEqual(loaded[0]["id"], "test_asset")

    def test_save_creates_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            assets_file = tmp_path / "assets.json"
            backup_file = tmp_path / "assets.backup.json"
            # Pre-write something to backup
            assets_file.write_text(json.dumps([_make_asset()]))

            with (patch.object(self.reg, "ASSETS_FILE", assets_file),
                  patch.object(self.reg, "BACKUP_FILE", backup_file),
                  patch.object(self.reg, "check_ssd", return_value=True),
                  patch.object(self.reg, "require_ssd")):

                self.reg.save([_make_asset(id="test_asset2", name="Asset 2")])
                self.assertTrue(backup_file.exists())


class TestBackup(unittest.TestCase):
    def setUp(self):
        from money_center import registry as reg
        self.reg = reg

    def test_backup_copies_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            assets_file = tmp_path / "assets.json"
            backup_file = tmp_path / "assets.backup.json"
            assets_file.write_text(json.dumps([_make_asset()]))

            with (patch.object(self.reg, "ASSETS_FILE", assets_file),
                  patch.object(self.reg, "BACKUP_FILE", backup_file)):
                self.reg.backup()
                self.assertTrue(backup_file.exists())
                self.assertEqual(
                    json.loads(backup_file.read_text())[0]["id"], "test_asset"
                )


class TestGet(unittest.TestCase):
    def setUp(self):
        from money_center import registry as reg
        self.reg = reg

    def test_get_returns_asset(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            assets_file = tmp_path / "assets.json"
            assets_file.write_text(json.dumps([_make_asset()]))

            with (patch.object(self.reg, "ASSETS_FILE", assets_file),
                  patch.object(self.reg, "check_ssd", return_value=True),
                  patch.object(self.reg, "require_ssd")):
                a = self.reg.get("test_asset")
                self.assertIsNotNone(a)
                self.assertEqual(a["id"], "test_asset")

    def test_get_returns_none_for_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            assets_file = tmp_path / "assets.json"
            assets_file.write_text(json.dumps([_make_asset()]))

            with (patch.object(self.reg, "ASSETS_FILE", assets_file),
                  patch.object(self.reg, "check_ssd", return_value=True),
                  patch.object(self.reg, "require_ssd")):
                self.assertIsNone(self.reg.get("nonexistent"))


class TestExists(unittest.TestCase):
    def setUp(self):
        from money_center import registry as reg
        self.reg = reg

    def test_exists_true_for_known_asset(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            assets_file = tmp_path / "assets.json"
            assets_file.write_text(json.dumps([_make_asset()]))

            with (patch.object(self.reg, "ASSETS_FILE", assets_file),
                  patch.object(self.reg, "check_ssd", return_value=True),
                  patch.object(self.reg, "require_ssd")):
                self.assertTrue(self.reg.exists("test_asset"))

    def test_exists_false_for_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            assets_file = tmp_path / "assets.json"
            assets_file.write_text(json.dumps([_make_asset()]))

            with (patch.object(self.reg, "ASSETS_FILE", assets_file),
                  patch.object(self.reg, "check_ssd", return_value=True),
                  patch.object(self.reg, "require_ssd")):
                self.assertFalse(self.reg.exists("ghost"))


class TestUpsert(unittest.TestCase):
    def setUp(self):
        from money_center import registry as reg
        self.reg = reg

    def test_upsert_inserts_new(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            assets_file = tmp_path / "assets.json"
            backup_file = tmp_path / "assets.backup.json"
            assets_file.write_text("[]")

            with (patch.object(self.reg, "ASSETS_FILE", assets_file),
                  patch.object(self.reg, "BACKUP_FILE", backup_file),
                  patch.object(self.reg, "check_ssd", return_value=True),
                  patch.object(self.reg, "require_ssd")):
                self.reg.upsert(_make_asset())
                assets = json.loads(assets_file.read_text())
                self.assertEqual(len(assets), 1)

    def test_upsert_updates_existing(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            assets_file = tmp_path / "assets.json"
            backup_file = tmp_path / "assets.backup.json"
            assets_file.write_text(json.dumps([_make_asset()]))

            with (patch.object(self.reg, "ASSETS_FILE", assets_file),
                  patch.object(self.reg, "BACKUP_FILE", backup_file),
                  patch.object(self.reg, "check_ssd", return_value=True),
                  patch.object(self.reg, "require_ssd")):
                updated = _make_asset(name="Updated Name")
                self.reg.upsert(updated)
                assets = json.loads(assets_file.read_text())
                self.assertEqual(len(assets), 1)
                self.assertEqual(assets[0]["name"], "Updated Name")


class TestRemove(unittest.TestCase):
    def setUp(self):
        from money_center import registry as reg
        self.reg = reg

    def test_remove_existing_asset(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            assets_file = tmp_path / "assets.json"
            backup_file = tmp_path / "assets.backup.json"
            assets_file.write_text(json.dumps([_make_asset()]))

            with (patch.object(self.reg, "ASSETS_FILE", assets_file),
                  patch.object(self.reg, "BACKUP_FILE", backup_file),
                  patch.object(self.reg, "check_ssd", return_value=True),
                  patch.object(self.reg, "require_ssd")):
                result = self.reg.remove("test_asset")
                self.assertTrue(result)
                assets = json.loads(assets_file.read_text())
                self.assertEqual(assets, [])

    def test_remove_nonexistent_returns_false(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            assets_file = tmp_path / "assets.json"
            backup_file = tmp_path / "assets.backup.json"
            assets_file.write_text("[]")

            with (patch.object(self.reg, "ASSETS_FILE", assets_file),
                  patch.object(self.reg, "BACKUP_FILE", backup_file),
                  patch.object(self.reg, "check_ssd", return_value=True),
                  patch.object(self.reg, "require_ssd")):
                self.assertFalse(self.reg.remove("ghost"))


class TestRevenueSummary(unittest.TestCase):
    def setUp(self):
        from money_center import registry as reg
        self.reg = reg

    def test_totals_sum_correctly(self):
        assets = [
            _make_asset(id="a1", category="service",
                        monthly_estimate_usd={"low": 100, "mid": 500, "high": 1000}),
            _make_asset(id="a2", category="content",
                        monthly_estimate_usd={"low": 50, "mid": 200, "high": 800}),
        ]
        summary = self.reg.revenue_summary(assets)
        self.assertAlmostEqual(summary["total"]["mid"], 700)
        self.assertAlmostEqual(summary["total"]["low"], 150)
        self.assertAlmostEqual(summary["total"]["high"], 1800)

    def test_grouped_by_category(self):
        assets = [
            _make_asset(id="a1", category="service",
                        monthly_estimate_usd={"low": 100, "mid": 500, "high": 1000}),
            _make_asset(id="a2", category="service",
                        monthly_estimate_usd={"low": 50, "mid": 200, "high": 800}),
        ]
        summary = self.reg.revenue_summary(assets)
        self.assertAlmostEqual(summary["by_category"]["service"]["mid"], 700)


class TestCheckSsd(unittest.TestCase):
    def setUp(self):
        from money_center import registry as reg
        self.reg = reg

    def test_check_ssd_true_when_mounted(self):
        with patch.object(self.reg, "_cfg", {"ssd_volume": "/tmp"}):
            self.assertTrue(self.reg.check_ssd())

    def test_check_ssd_false_when_not_mounted(self):
        with patch.object(self.reg, "_cfg", {"ssd_volume": "/nonexistent_volume_xyz"}):
            self.assertFalse(self.reg.check_ssd())


class TestNewAssetTemplate(unittest.TestCase):
    def setUp(self):
        from money_center import registry as reg
        self.reg = reg

    def test_template_passes_validation(self):
        tmpl = self.reg.new_asset_template()
        tmpl["id"] = "template_test"
        tmpl["name"] = "Template Test"
        # Template has empty run/stop commands — fill them for validation
        tmpl["run_command"] = "echo run"
        tmpl["stop_command"] = "echo stop"
        errors = self.reg.validate(tmpl)
        self.assertEqual(errors, [], msg=f"Template validation errors: {errors}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
