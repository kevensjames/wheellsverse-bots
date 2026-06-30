"""Spend tracking + soft-cap logic. Reads/writes `llm_call_log`."""
from __future__ import annotations

import json
import logging
import os
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.services.router.types import CompletionResult

logger = logging.getLogger(__name__)


DEFAULT_DAILY_CAP = float(os.environ.get("NAI_MAX_DAILY_SPEND_USD", "2.00"))
DEFAULT_MONTHLY_CAP = float(os.environ.get("NAI_MAX_MONTHLY_SPEND_USD", "60.00"))


def _json_dump(obj: Any) -> str:
    return json.dumps(obj, default=str)


class SpendTracker:
    def __init__(
        self,
        session: Session,
        daily_cap_usd: float = DEFAULT_DAILY_CAP,
        monthly_cap_usd: float = DEFAULT_MONTHLY_CAP,
    ):
        self.session = session
        self.daily_cap = daily_cap_usd
        self.monthly_cap = monthly_cap_usd

    def log_call(
        self,
        *,
        user_id: uuid.UUID,
        adapter: str,
        model: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cost_usd: float = 0.0,
        latency_ms: int | None = None,
        success: bool = True,
        error_message: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        # Durability (CORR-F5): write the spend row on a DEDICATED session and
        # commit immediately, so a later rollback/failure of the request
        # transaction can't lose it — the row also feeds the soft daily/monthly
        # caps, so dropping it would let a failed-but-charged call evade the cap.
        # Fail-soft: spend logging must never break a paid request. Reads (the
        # cap queries below) still use self.session and see the committed rows.
        params = {
            "user_id": str(user_id),
            "adapter": adapter,
            "model": model,
            "in_tok": input_tokens,
            "out_tok": output_tokens,
            "cost": cost_usd,
            "latency": latency_ms,
            "success": success,
            "error": error_message,
            "metadata": _json_dump(metadata or {}),
        }
        s = SessionLocal()
        try:
            s.execute(
                text(
                    """
                    INSERT INTO llm_call_log
                        (user_id, adapter, model, input_tokens, output_tokens,
                         cost_usd, latency_ms, success, error_message, metadata)
                    VALUES
                        (:user_id, :adapter, :model, :in_tok, :out_tok,
                         :cost, :latency, :success, :error, CAST(:metadata AS jsonb))
                    """
                ),
                params,
            )
            s.commit()
        except Exception as e:
            s.rollback()
            logger.warning("spend log_call failed for %s/%s: %s", adapter, model, e)
        finally:
            s.close()

    def log_result(self, user_id: uuid.UUID, result: CompletionResult) -> None:
        self.log_call(
            user_id=user_id,
            adapter=result.adapter,
            model=result.model,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            cost_usd=result.cost_usd,
            latency_ms=result.latency_ms,
            metadata=result.metadata,
        )

    def daily_spend(self, user_id: uuid.UUID) -> float:
        row = self.session.execute(
            text(
                """
                SELECT COALESCE(SUM(cost_usd), 0) AS total
                FROM llm_call_log
                WHERE user_id = :user_id
                  AND created_at >= NOW() - INTERVAL '24 hours'
                """
            ),
            {"user_id": str(user_id)},
        ).first()
        return float(row.total) if row else 0.0

    def monthly_spend(self, user_id: uuid.UUID) -> float:
        row = self.session.execute(
            text(
                """
                SELECT COALESCE(SUM(cost_usd), 0) AS total
                FROM llm_call_log
                WHERE user_id = :user_id
                  AND created_at >= DATE_TRUNC('month', NOW())
                """
            ),
            {"user_id": str(user_id)},
        ).first()
        return float(row.total) if row else 0.0

    def over_daily_cap(self, user_id: uuid.UUID) -> bool:
        return self.daily_spend(user_id) >= self.daily_cap

    def over_monthly_cap(self, user_id: uuid.UUID) -> bool:
        return self.monthly_spend(user_id) >= self.monthly_cap
