#!/usr/bin/env python3
"""
core/project_manager.py
─────────────────────────────────────────────────────────────────────────────
Multi-Project / Client Mode.

Each project has:
  - projects/<name>/config.json  (project settings, model, API keys override)
  - projects/<name>/outputs/     (all bot outputs for this project)
  - projects/<name>/memory/      (project-scoped memory)
  - projects/<name>/.env         (optional per-project env overrides)

Usage:
  pm = get_project_manager()
  pm.create_project("client_1", {"brand": "Acme Corp"})
  pm.switch_project("client_1")
  # All bots now write to projects/client_1/outputs/
─────────────────────────────────────────────────────────────────────────────
"""

import json
import logging
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).parent.parent
PROJECTS_DIR = ROOT / "projects"

logger = logging.getLogger("project_manager")

DEFAULT_PROJECT_CONFIG = {
    "name": "New Project",
    "brand": "WheellsVerse",
    "owner": "Jhon Kevens D Wheeler",
    "niche": "AI automation and entrepreneurship",
    "goal": "Build automated income streams and a scalable business",
    "tone": "professional, engaging, bold",
    "model": "gpt-4o-mini",
    "enabled_categories": [
        "marketing", "business", "sales", "social_media",
        "writing", "specialized"
    ],
    "created_at": "",
    "active": True,
    "metadata": {},
}


class Project:
    """Represents a single project / client context."""

    def __init__(self, slug: str):
        self.slug = slug
        self.root = PROJECTS_DIR / slug
        self.config_path = self.root / "config.json"
        self.outputs_dir = self.root / "outputs"
        self.memory_dir = self.root / "memory"
        self.env_path = self.root / ".env"
        self.config: Dict[str, Any] = {}
        self._load()

    def _load(self):
        if self.config_path.exists():
            try:
                self.config = json.loads(self.config_path.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning(f"Could not load project config [{self.slug}]: {e}")
                self.config = dict(DEFAULT_PROJECT_CONFIG)
        else:
            self.config = dict(DEFAULT_PROJECT_CONFIG)

    def save(self):
        self.root.mkdir(parents=True, exist_ok=True)
        self.outputs_dir.mkdir(parents=True, exist_ok=True)
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(
            json.dumps(self.config, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )

    def update(self, updates: Dict):
        self.config.update(updates)
        self.config["updated_at"] = datetime.now().isoformat()
        self.save()

    def get_env_overrides(self) -> Dict[str, str]:
        """Load per-project .env overrides (if present)."""
        overrides = {}
        if self.env_path.exists():
            for line in self.env_path.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    overrides[k.strip()] = v.strip()
        return overrides

    def apply_env(self):
        """Apply this project's .env overrides to os.environ."""
        for k, v in self.get_env_overrides().items():
            os.environ[k] = v

    def get_output_dir(self, category: str = "", bot_name: str = "") -> Path:
        """Get the output directory for this project, optionally scoped."""
        base = self.outputs_dir
        if category:
            base = base / category
        if bot_name:
            base = base / bot_name
        base.mkdir(parents=True, exist_ok=True)
        return base

    def to_dict(self) -> Dict:
        # Count outputs
        output_count = 0
        if self.outputs_dir.exists():
            output_count = sum(1 for _ in self.outputs_dir.rglob("*") if _.is_file())

        return {
            "slug": self.slug,
            "name": self.config.get("name", self.slug),
            "brand": self.config.get("brand", ""),
            "niche": self.config.get("niche", ""),
            "goal": self.config.get("goal", ""),
            "model": self.config.get("model", "gpt-4o-mini"),
            "active": self.config.get("active", True),
            "created_at": self.config.get("created_at", ""),
            "output_count": output_count,
            "enabled_categories": self.config.get("enabled_categories", []),
            "metadata": self.config.get("metadata", {}),
        }


class ProjectManager:
    """
    Manages multiple projects.
    Tracks which project is currently active.
    """

    def __init__(self):
        self._projects: Dict[str, Project] = {}
        self._active_slug: str = "wheellsverse"
        self._load_all()

    def _load_all(self):
        PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
        for p in PROJECTS_DIR.iterdir():
            if p.is_dir() and (p / "config.json").exists():
                self._projects[p.name] = Project(p.name)

        # Always ensure default project exists
        if "wheellsverse" not in self._projects:
            self.create_project("wheellsverse", {
                "name": "WheellsVerse",
                "brand": "WheellsVerse / J.K. Blaze",
                "owner": "Jhon Kevens D Wheeler",
                "niche": "AI automation and entrepreneurship",
                "goal": "Build automated income streams and a scalable business",
            })

        logger.info(f"ProjectManager: {len(self._projects)} projects loaded")

    # ─── CRUD ─────────────────────────────────────────────────────────────────

    def create_project(self, slug: str, config: Optional[Dict] = None) -> Project:
        """Create a new project."""
        slug = slug.lower().replace(" ", "_").replace("-", "_")
        if slug in self._projects:
            raise ValueError(f"Project '{slug}' already exists")

        proj = Project(slug)
        proj.config = dict(DEFAULT_PROJECT_CONFIG)
        proj.config["name"] = slug.replace("_", " ").title()
        proj.config["created_at"] = datetime.now().isoformat()
        if config:
            proj.config.update(config)
        proj.save()

        self._projects[slug] = proj
        logger.info(f"Project created: {slug}")
        return proj

    def get_project(self, slug: str) -> Optional[Project]:
        return self._projects.get(slug)

    def update_project(self, slug: str, updates: Dict) -> Optional[Project]:
        proj = self._projects.get(slug)
        if not proj:
            return None
        proj.update(updates)
        return proj

    def delete_project(self, slug: str) -> bool:
        if slug == "wheellsverse":
            raise ValueError("Cannot delete the default project")
        if slug in self._projects:
            del self._projects[slug]
            project_path = PROJECTS_DIR / slug
            if project_path.exists():
                shutil.rmtree(project_path)
            logger.info(f"Project deleted: {slug}")
            return True
        return False

    # ─── Active project ───────────────────────────────────────────────────────

    def switch_project(self, slug: str) -> Project:
        if slug not in self._projects:
            raise ValueError(f"Project '{slug}' not found")
        self._active_slug = slug
        proj = self._projects[slug]
        proj.apply_env()  # Apply per-project env overrides
        logger.info(f"Switched to project: {slug}")
        return proj

    @property
    def active(self) -> Project:
        return self._projects.get(self._active_slug, self._projects["wheellsverse"])

    @property
    def active_slug(self) -> str:
        return self._active_slug

    # ─── Queries ──────────────────────────────────────────────────────────────

    def list_projects(self) -> List[Dict]:
        return [p.to_dict() for p in self._projects.values()]

    def get_active_context(self) -> Dict:
        """Returns the current project's context — injected into bot prompts."""
        proj = self.active
        return {
            "brand": proj.config.get("brand", "WheellsVerse"),
            "owner": proj.config.get("owner", "Jhon Kevens D Wheeler"),
            "niche": proj.config.get("niche", "AI automation"),
            "goal": proj.config.get("goal", "Build automated income"),
            "tone": proj.config.get("tone", "professional, engaging"),
            "project": proj.slug,
        }

    def get_output_dir(self, category: str = "", bot_name: str = "") -> Path:
        """Get output directory for the active project."""
        return self.active.get_output_dir(category, bot_name)

    def get_project_outputs(self, slug: str) -> Dict[str, List[Dict]]:
        """List all output files for a project, organized by category."""
        proj = self._projects.get(slug)
        if not proj or not proj.outputs_dir.exists():
            return {}

        result: Dict[str, List] = {}
        for cat_dir in sorted(proj.outputs_dir.iterdir()):
            if not cat_dir.is_dir():
                continue
            files = []
            for f in sorted(cat_dir.rglob("*"), key=lambda x: x.stat().st_mtime, reverse=True):
                if f.is_file():
                    files.append({
                        "file": f.name,
                        "path": str(f.relative_to(ROOT)),
                        "size": f.stat().st_size,
                        "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
                    })
            if files:
                result[cat_dir.name] = files[:20]  # limit per category

        return result


# ─── Singleton ────────────────────────────────────────────────────────────────

_pm: Optional[ProjectManager] = None


def get_project_manager() -> ProjectManager:
    global _pm
    if _pm is None:
        _pm = ProjectManager()
    return _pm
