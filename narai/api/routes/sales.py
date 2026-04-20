"""Sales/CRM API routes — lead scoring, outreach drafting, pipeline."""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from narai.api.auth import require_auth
from narai.core.sales import (
    Lead, OutreachBrief, Pipeline,
    draft_outreach, score_lead,
)
from narai.core.sales.lead import rank_leads
from narai.core.sales.pipeline import DealStage

rt = APIRouter(tags=["sales"])
_pipeline = Pipeline()


# ── Lead scoring ──────────────────────────────────────────────────────────────

class LeadRequest(BaseModel):
    email: str
    name: str = ""
    company: str = ""
    role: str = ""
    industry: str = ""
    company_size: str = ""
    signals: dict[str, bool] = {}


@rt.post("/sales/score")
async def sales_score(req: LeadRequest, _=Depends(require_auth)) -> dict:
    return {"ok": True, "result": score_lead(Lead(**req.model_dump()))}


class LeadBatchRequest(BaseModel):
    leads: list[LeadRequest]


@rt.post("/sales/score_batch")
async def sales_score_batch(req: LeadBatchRequest, _=Depends(require_auth)) -> dict:
    leads = [Lead(**l.model_dump()) for l in req.leads]
    return {"ok": True, "ranked": rank_leads(leads)}


# ── Outreach ──────────────────────────────────────────────────────────────────

class OutreachRequest(BaseModel):
    recipient_name: str
    recipient_role: str
    recipient_company: str
    value_prop: str
    pain_point: str = ""
    cta: str = "book a 15-min call"
    sender_name: str = "J.K. Blaze"
    hook: str = ""
    prior_context: str = ""
    template: str = "cold"


@rt.post("/sales/outreach")
async def sales_outreach(req: OutreachRequest, _=Depends(require_auth)) -> dict:
    try:
        result = await draft_outreach(OutreachBrief(**req.model_dump()))
        return {"ok": True, "email": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Pipeline ──────────────────────────────────────────────────────────────────

class DealCreateRequest(BaseModel):
    contact_email: str
    company: str = ""
    amount: float = 0.0
    source: str = ""
    notes: str = ""


class StageUpdateRequest(BaseModel):
    deal_id: int
    new_stage: str
    note: str = ""


class AmountUpdateRequest(BaseModel):
    deal_id: int
    amount: float


@rt.post("/sales/deals")
async def sales_create_deal(req: DealCreateRequest, _=Depends(require_auth)) -> dict:
    try:
        return {"ok": True, "deal": await _pipeline.create(**req.model_dump())}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@rt.patch("/sales/deals/stage")
async def sales_update_stage(req: StageUpdateRequest, _=Depends(require_auth)) -> dict:
    try:
        return {"ok": True, "deal": await _pipeline.update_stage(req.deal_id, req.new_stage, req.note)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@rt.patch("/sales/deals/amount")
async def sales_update_amount(req: AmountUpdateRequest, _=Depends(require_auth)) -> dict:
    try:
        return {"ok": True, "deal": await _pipeline.update_amount(req.deal_id, req.amount)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@rt.get("/sales/deals")
async def sales_list_deals(stage: Optional[str] = None, limit: int = 100,
                           _=Depends(require_auth)) -> dict:
    return {"ok": True, "deals": await _pipeline.list_by_stage(stage=stage, limit=limit)}


@rt.get("/sales/pipeline/summary")
async def sales_summary(_=Depends(require_auth)) -> dict:
    return {"ok": True, "summary": await _pipeline.summary()}


@rt.get("/sales/pipeline/stages")
async def sales_stages(_=Depends(require_auth)) -> dict:
    return {"ok": True, "stages": [s.value for s in DealStage]}
