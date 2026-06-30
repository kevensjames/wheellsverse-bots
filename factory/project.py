"""Factory project registry: the set of software products the daemon builds.
Stored as data/factory/projects.json. A project is 'active' while the daemon
should tick it; 'done' (roadmap complete), 'dormant' (paused), or 'blocked_red'
(too many consecutive failures — needs the operator)."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from factory import paths

VALID_PHASES = {"active", "done", "dormant", "blocked_red"}


@dataclass
class Project:
    slug: str
    name: str
    repo_url: str
    phase: str = "active"
    consecutive_failures: int = 0
    autonomy_overrides: dict = field(default_factory=dict)


def _registry_file():
    return paths.data_root() / "projects.json"


def list_projects() -> list[Project]:
    data = paths.load_json(_registry_file(), {"projects": []}) or {"projects": []}
    return [Project(**row) for row in data.get("projects", [])]


def _save(projects: list[Project]) -> None:
    paths.save_json_atomic(_registry_file(), {"projects": [asdict(p) for p in projects]})


def get_project(slug: str) -> Project | None:
    return next((p for p in list_projects() if p.slug == slug), None)


def upsert_project(p: Project) -> None:
    projects = [x for x in list_projects() if x.slug != p.slug]
    projects.append(p)
    _save(projects)


def list_active() -> list[Project]:
    return [p for p in list_projects() if p.phase == "active"]


def set_phase(slug: str, phase: str) -> None:
    if phase not in VALID_PHASES:
        raise ValueError(f"invalid phase: {phase!r}")
    projects = list_projects()
    for p in projects:
        if p.slug == slug:
            p.phase = phase
    _save(projects)


def bump_failure(slug: str, *, threshold: int = 3) -> int:
    projects = list_projects()
    count = 0
    for p in projects:
        if p.slug == slug:
            p.consecutive_failures += 1
            count = p.consecutive_failures
            if count >= threshold:
                p.phase = "blocked_red"
    _save(projects)
    return count


def reset_failure(slug: str) -> None:
    projects = list_projects()
    for p in projects:
        if p.slug == slug:
            p.consecutive_failures = 0
    _save(projects)
