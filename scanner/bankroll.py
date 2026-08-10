"""Phase 2H: bankroll / challenge mode and capital-concentration checks."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BankrollState:
    starting_bankroll: float
    target_bankroll: float
    available_cash: float
    inventory_value: float = 0.0
    realised_profit: float = 0.0

    @property
    def progress_pct(self) -> float:
        if self.target_bankroll <= self.starting_bankroll:
            return 0.0
        total_value = self.available_cash + self.inventory_value
        span = self.target_bankroll - self.starting_bankroll
        return round(max(0.0, min(100.0, (total_value - self.starting_bankroll) / span * 100)), 1)


def capital_concentration_pct(purchase_price: float, available_cash: float) -> float:
    """% of currently-available cash a purchase would consume. 0 cash -> 100% (max risk)."""
    if available_cash <= 0:
        return 100.0
    return round(min(100.0, (purchase_price / available_cash) * 100), 1)


def exceeds_concentration_limit(purchase_price: float, available_cash: float, bankroll_cfg: dict) -> bool:
    limit = bankroll_cfg.get("maximum_single_purchase_percent", 100)
    return capital_concentration_pct(purchase_price, available_cash) > limit
