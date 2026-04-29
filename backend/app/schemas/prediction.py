from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class PredictionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    asset_symbol: str
    signal: str
    confidence: float
    target_price: float | None = None
    stop_loss: float | None = None
    horizon_hours: int | None = None
    created_at: datetime


class SignalCounts(BaseModel):
    BUY: int = 0
    SELL: int = 0
    HOLD: int = 0


class PredictionStats(BaseModel):
    total_predictions: int
    by_signal: SignalCounts
    closed_predictions: int
    win_rate: float | None = None
    avg_confidence: float
