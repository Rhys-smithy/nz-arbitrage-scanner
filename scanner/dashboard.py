"""Phase 2J: dashboard data builder.

The existing repo has no frontend yet -- .github/workflows/scan.yml
already builds reports/index.json "so the dashboard can find reports",
implying one was planned but never built. This module adds the
*data* a dashboard needs (bankroll summary + top opportunity) without
touching the existing report/index.json generation, so it's additive
and doesn't risk the existing CI step.
"""
from __future__ import annotations

from scanner.bankroll import BankrollState
from scanner.models import Opportunity


def build_dashboard_summary(bankroll: BankrollState, opportunities: list[Opportunity]) -> dict:
    active = [o for o in opportunities if o.decision in ("BUY", "WATCH", "PROFITABLE BUT CAPITAL RISK")]
    top = max(opportunities, key=lambda o: o.flip_score or 0, default=None)

    return {
        "bankroll": {
            "starting": bankroll.starting_bankroll,
            "target": bankroll.target_bankroll,
            "available_cash": bankroll.available_cash,
            "inventory_value": bankroll.inventory_value,
            "realised_profit": bankroll.realised_profit,
            "progress_pct": bankroll.progress_pct,
        },
        "active_opportunities": len(active),
        "top_opportunity": (
            None
            if top is None
            else {
                "title": top.title,
                "flip_score": top.flip_score,
                "decision": top.decision,
                "url": top.url,
            }
        ),
    }
