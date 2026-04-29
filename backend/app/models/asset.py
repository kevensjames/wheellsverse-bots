from datetime import datetime

from sqlalchemy import BigInteger, Boolean, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    asset_type: Mapped[str] = mapped_column(String(20), nullable=False)
    exchange: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))


class PriceHistory(Base):
    __tablename__ = "price_history"
    __table_args__ = (
        UniqueConstraint("asset_id", "timestamp", name="uq_price_asset_ts"),
        Index("idx_price_asset_time", "asset_id", "timestamp"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(nullable=False)
    open: Mapped[float | None] = mapped_column(Numeric(18, 6), nullable=True)
    high: Mapped[float | None] = mapped_column(Numeric(18, 6), nullable=True)
    low: Mapped[float | None] = mapped_column(Numeric(18, 6), nullable=True)
    close: Mapped[float | None] = mapped_column(Numeric(18, 6), nullable=True)
    volume: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
