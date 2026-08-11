"""Operator SWE-runtime admin: run a bounded command in the disposable sandbox.

Governed: @audited(scope="swe.run", destructive=True) + approved=true, gated by
KAI_SWE_RUNTIME_ENABLED (default off) and a source-dir allowlist. NEVER exposed as
an LLM tool. The sandbox has no network, no host mount, capability-stripped, and
is ephemeral — but it executes code, so it is operator-triggered + approval-gated
+ audited, and must run only on a NON-PRODUCTION runner.
"""
from __future__ import annotations

import logging
import os
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.dependencies.admin import require_admin_token
from app.services.governance import PendingApproval, ScopeDenied, audited
from app.services.swe_runtime.config import (default_policy, image_allowed,
                                             repo_allowed, runtime_enabled)
from app.services.swe_runtime.policy import PolicyDenied
from app.services.swe_runtime.runtime import SandboxCommandRuntime, SweTask

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin/swe",
    tags=["admin"],
    dependencies=[Depends(require_admin_token)],
)


class RunRequest(BaseModel):
    source_dir: str
    command: str
    image: str | None = None
    timeout_seconds: int | None = None
    approved: bool = False


@audited(scope="swe.run", destructive=True)
def _do_run(*, task: SweTask):
    return SandboxCommandRuntime().run_task(task)


@router.get("/status")
def status():
    return {"enabled": runtime_enabled()}


@router.post("/run")
def run(body: RunRequest):
    if not runtime_enabled():
        raise HTTPException(status_code=409,
                            detail="SWE runtime disabled (set KAI_SWE_RUNTIME_ENABLED=1 on a non-prod runner)")
    if not os.path.isdir(body.source_dir):
        raise HTTPException(status_code=400, detail="source_dir is not a directory")
    if not repo_allowed(body.source_dir):
        raise HTTPException(status_code=403, detail="source_dir is not under KAI_SWE_REPO_ALLOWLIST")
    policy = default_policy()
    if body.image:
        if not image_allowed(body.image):
            raise HTTPException(status_code=400, detail="image is not in KAI_SWE_IMAGE_ALLOWLIST")
        policy.image = body.image
    if body.timeout_seconds:
        policy.timeout_seconds = max(1, min(int(body.timeout_seconds), 900))
    task = SweTask(task_id=uuid.uuid4().hex[:12], source_dir=body.source_dir,
                   command=body.command, policy=policy)
    try:
        res = _do_run(task=task, approved=body.approved)
    except ScopeDenied as e:
        raise HTTPException(status_code=403, detail=str(e))
    except PendingApproval as e:
        raise HTTPException(status_code=409, detail=str(e))
    except PolicyDenied as e:
        raise HTTPException(status_code=400, detail=f"policy denied: {e}")
    except Exception:
        logger.exception("swe run failed")
        raise HTTPException(status_code=503, detail="swe run failed")
    return {"task_id": task.task_id, "result": res.as_dict()}
