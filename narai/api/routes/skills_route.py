"""Skill management routes."""
from fastapi import APIRouter, Depends, HTTPException

from narai.api.auth import require_auth
from infra.brain.interface import BrainClient

_brain = BrainClient(user_id="owner", mode="narai")

rt = APIRouter(prefix="/skills", tags=["skills"])


@rt.get("")
def list_skills(_: str = Depends(require_auth)) -> dict:
    return {"available": _brain.skills.available(), "active": _brain.skills._ACTIVE_SKILL}


@rt.post("/activate/{name}")
def activate_skill(name: str, _: str = Depends(require_auth)) -> dict:
    try:
        _brain.skills.activate(name)
        return {"activated": name}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Skill '{name}' not found")


@rt.post("/deactivate")
def deactivate_skill(_: str = Depends(require_auth)) -> dict:
    _brain.skills.deactivate()
    return {"active": None}
