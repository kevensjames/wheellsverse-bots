import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, Integer, Numeric, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base


class Prediction(Base):
    __tablename__ = "predictions"
    __table_args__ = (
        Index("idx_pred_asset_created", "asset_id", "created_at"),
        Index("idx_pred_signal", "signal", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"), nullable=False)
    signal: Mapped[str] = mapped_column(String(10), nullable=False)
    confidence: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    target_price: Mapped[float | None] = mapped_column(Numeric(18, 6), nullable=True)
    stop_loss: Mapped[float | None] = mapped_column(Numeric(18, 6), nullable=True)
    horizon_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    model_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    features_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    actual_outcome: Mapped[str | None] = mapped_column(String(10), nullable=True)
    actual_return_pct: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(nullable=True)
