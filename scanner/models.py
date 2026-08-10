"""Phase 2A core data models for the AI Flip Hunter engine.

These are plain dataclasses (not pydantic -- repo has zero extra
dependencies today and Phase 2 doesn't need to add one). Every field
maps directly to something the spec explicitly asks for so any of this
can be dumped straight into a report row or Telegram message.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ComparableEvidence:
    """One piece of evidence backing a resale valuation (spec section 24)."""

    product: str
    model: str
    condition: str
    price: float
    currency: str
    source: str
    url: str
    date_observed: str
    similarity_score: float  # 0.0-1.0
    is_sold: bool = False  # True = confirmed sale, False = asking price only
    evidence_type: str = "OTHER"  # SOLD / CURRENT_LISTING / RETAIL / OTHER (Phase 3)
    original_price: Optional[float] = None  # pre-currency-conversion price, if converted
    original_currency: Optional[str] = None  # currency of original_price, if converted


@dataclass
class BundleComponent:
    name: str
    quick_sale_value: Optional[float] = None
    normal_value: Optional[float] = None
    optimistic_value: Optional[float] = None
    confidence_pct: Optional[float] = None


@dataclass
class ProductIdentification:
    brand: Optional[str] = None
    model: Optional[str] = None
    is_bundle: bool = False
    components: list[BundleComponent] = field(default_factory=list)
    condition_risk_phrases: list[str] = field(default_factory=list)
    condition_risk_level: str = "unknown"  # low / medium / high / unknown
    model_identified_confidently: bool = False


@dataclass
class ResaleValuation:
    quick_sale_low: Optional[float] = None
    quick_sale_high: Optional[float] = None
    normal: Optional[float] = None
    optimistic: Optional[float] = None
    confidence_pct: float = 0.0
    evidence: list[ComparableEvidence] = field(default_factory=list)
    evidence_note: str = ""  # e.g. "Insufficient comparable evidence."

    @property
    def quick_sale_mid(self) -> Optional[float]:
        if self.quick_sale_low is None and self.quick_sale_high is None:
            return None
        vals = [v for v in (self.quick_sale_low, self.quick_sale_high) if v is not None]
        return sum(vals) / len(vals) if vals else None


@dataclass
class CostBreakdown:
    """Deterministic, Python-calculated costs (spec section 12). Never AI output."""

    purchase_price: float = 0.0
    buyer_premium: float = 0.0
    gst: float = 0.0
    selling_fees: float = 0.0
    payment_fees: float = 0.0
    shipping: float = 0.0
    packaging: float = 0.0
    repair_allowance: float = 0.0
    negotiation_allowance: float = 0.0
    other: float = 0.0

    @property
    def total_excluding_purchase(self) -> float:
        return round(
            self.buyer_premium + self.gst + self.selling_fees + self.payment_fees
            + self.shipping + self.packaging + self.repair_allowance
            + self.negotiation_allowance + self.other,
            2,
        )

    @property
    def total(self) -> float:
        return round(self.purchase_price + self.total_excluding_purchase, 2)


@dataclass
class Opportunity:
    """Full opportunity record -- one per listing, assembled by valuation.py."""

    title: str
    url: str
    source: str
    current_price: Optional[float]
    identification: ProductIdentification = field(default_factory=ProductIdentification)
    valuation: ResaleValuation = field(default_factory=ResaleValuation)
    costs: CostBreakdown = field(default_factory=CostBreakdown)

    expected_net_profit_low: Optional[float] = None
    expected_net_profit_high: Optional[float] = None
    roi_low_pct: Optional[float] = None
    roi_high_pct: Optional[float] = None

    max_buy_price: Optional[float] = None
    bidding_room: Optional[float] = None

    liquidity: str = "unknown"  # HIGH / MEDIUM / LOW / unknown
    expected_sale_time: str = "unknown"

    flip_score: Optional[int] = None
    flip_score_band: str = ""  # EXCELLENT / STRONG / WATCH / WEAK / PASS

    decision: str = "PASS"  # BUY / WATCH / PASS / PROFITABLE BUT CAPITAL RISK
    decision_reasons: list[str] = field(default_factory=list)

    capital_concentration_pct: Optional[float] = None
