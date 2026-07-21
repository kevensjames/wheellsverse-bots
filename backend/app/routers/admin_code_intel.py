"""Operator code-intelligence admin: index / delete / search a repo.

Index + delete are governed: @audited(scope="code_intel.*", destructive=True) so
they require the scope opt-in (KAI_SCOPE_CODE_INTEL_*) + approved=True + land in
the audit log. Search is an admin read. Indexing runs into a target user_id's
space (single-operator => the operator's own id); that user's chat can then
code_search it. The model NEVER triggers indexing — this admin surface does.
"""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.admin import require_admin_token
from app.services.code_intel.pgvector_provider import PgVectorCodeSearchProvider
from app.services.code_intel.provider import RepoRef
from app.services.governance import PendingApproval, ScopeDenied, audited
from app.services.tools.base import ToolContext

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin/code-intel",
    tags=["admin"],
    dependencies=[Depends(require_admin_token)],
)


class IndexRequest(BaseModel):
    user_id: str
    repo_id: str
    roots: list[str]
    approved: bool = False


class DeleteRequest(BaseModel):
    user_id: str
    repo_id: str
    approved: bool = False


class SearchRequest(BaseModel):
    user_id: str
    query: str
    k: int = 8
    repo_id: str | None = None
    lang: str | None = None


def _uid(raw: str) -> uuid.UUID:
    try:
        return uuid.UUID(raw)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="user_id must be a UUID")


@audited(scope="code_intel.index", destructive=True)
def _do_index(*, ctx: ToolContext, repo: RepoRef):
    return PgVectorCodeSearchProvider().index_repo(ctx, repo)


@audited(scope="code_intel.delete", destructive=True)
def _do_delete(*, ctx: ToolContext, repo_id: str) -> int:
    return PgVectorCodeSearchProvider().delete_repo(ctx, repo_id)


@router.post("/index")
def index_repo(body: IndexRequest, db: Session = Depends(get_db)):
    ctx = ToolContext(user_id=_uid(body.user_id), session=db)
    try:
        res = _do_index(ctx=ctx, repo=RepoRef(repo_id=body.repo_id, roots=body.roots),
                        approved=body.approved)
    except ScopeDenied as e:
        raise HTTPException(status_code=403, detail=str(e))
    except PendingApproval as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception:
        logger.exception("code-intel index failed")
        raise HTTPException(status_code=503, detail="code indexing failed")
    return res.as_dict()


@router.post("/delete")
def delete_repo(body: DeleteRequest, db: Session = Depends(get_db)):
    ctx = ToolContext(user_id=_uid(body.user_id), session=db)
    try:
        n = _do_delete(ctx=ctx, repo_id=body.repo_id, approved=body.approved)
    except ScopeDenied as e:
        raise HTTPException(status_code=403, detail=str(e))
    except PendingApproval as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception:
        logger.exception("code-intel delete failed")
        raise HTTPException(status_code=503, detail="code delete failed")
    return {"deleted": n}


@router.post("/search")
def search_repo(body: SearchRequest, db: Session = Depends(get_db)):
    ctx = ToolContext(user_id=_uid(body.user_id), session=db)
    try:
        hits = PgVectorCodeSearchProvider().search(
            ctx, body.query, k=body.k, repo_id=body.repo_id, lang=body.lang)
    except Exception:
        logger.exception("code-intel search failed")
        raise HTTPException(status_code=503, detail="code search failed")
    return {
        "count": len(hits),
        "results": [
            {"path": h.path, "symbol": h.symbol, "lang": h.lang,
             "lines": f"{h.start_line}-{h.end_line}",
             "relevance": round(float(h.similarity), 3), "excerpt": h.content}
            for h in hits
        ],
    }
