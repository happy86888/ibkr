"""
Covered Call Backtest Engine.

Supports a matrix of strategies:
  - Strike selection: fixed_delta / fixed_otm_pct / fixed_strike_method
  - DTE selection: e.g., 30, 45 days
  - Close rule: hold_to_expiry / profit_50 / dte_21 / hybrid

Models:
  - Premium: Black-Scholes with IV calibrated from realized vol + VIX
  - Assignment: triggered when stock > strike at expiry
  - Dividends: collected while holding stock
  - Slippage: configurable bid-ask haircut on premium
"""
import pandas as pd
import numpy as np
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Literal
from .pricing import bs_call_price, bs_call_delta, strike_from_delta, \
    realized_volatility, implied_vol_estimate
from .data_loader import get_risk_free_rate


# ============================================================================
# Strategy Configuration
# ============================================================================

@dataclass
class CCStrategy:
    """Single CC strategy definition."""
    name: str

    # Strike selection
    strike_method: Literal["delta", "otm_pct"] = "delta"
    target_delta: float = 0.25            # used if strike_method == "delta"
    target_otm_pct: float = 5.0           # used if strike_method == "otm_pct"

    # DTE at entry
    target_dte: int = 30

    # Close rule
    close_rule: Literal["expiry", "profit_50", "dte_21", "hybrid"] = "expiry"
    profit_take_pct: float = 0.50         # close when 50% premium captured
    dte_close_threshold: int = 21         # close when DTE <= this

    # Slippage / costs
    bid_ask_spread_pct: float = 0.05      # 5% of mid as round-trip cost
    commission_per_contract: float = 0.65

    def to_dict(self) -> dict:
        return asdict(self)


# ============================================================================
# Trade & Result objects
# ============================================================================

@dataclass
class Trade:
    """Records a single CC trade lifecycle."""
    strategy: str
    symbol: str
    entry_date: pd.Timestamp
    exit_date: pd.Timestamp
    entry_spot: float
    exit_spot: float
    strike: float
    dte_at_entry: int
    dte_at_exit: int
    premium_collected: float    # per share
    premium_paid_to_close: float  # per share (0 if expired worthless or assigned)
    iv_at_entry: float
    delta_at_entry: float
    exit_reason: str             # "expired_otm" / "assigned" / "profit_50" / "dte_21" / "hybrid"
    premium_pnl: float           # net premium $ (per contract = 100 shares)
    stock_pnl_during_hold: float # MTM stock change while position open
    dividends_collected: float
    commissions: float


@dataclass
class BacktestResult:
    strategy_name: str
    symbol: str
    trades: List[Trade]
    equity_curve: pd.DataFrame   # daily equity, columns: date, equity, cc_value, stock_value
    metrics: Dict
    config: CCStrategy


# ============================================================================
# Backtest Engine
# ============================================================================

class CCBacktest:
    """
    Backtests a single CC strategy on a single underlying.

    Assumes: start with 100 shares (1 contract) at first day's open price.
    Holds the shares throughout (unless assigned, then re-buys to maintain CC).
    Each "cycle" = enter short call → close → re-enter.
    """

    def __init__(
        self,
        data: dict,                  # output of data_loader.prepare_backtest_data()
        strategy: CCStrategy,
        starting_shares: int = 100,
    ):
        self.symbol = data["symbol"]
        self.prices = data["prices"]
        self.vol_index = data["vol_index"]
        self.div_yield = data["div_yield"]
        self.start_date = pd.Timestamp(data["start"])
        self.end_date = pd.Timestamp(data["end"])
        self.strategy = strategy
        self.starting_shares = starting_shares

        # Pre-compute IV series
        rv = realized_volatility(self.prices["close"], window=30)
        self.iv_series = implied_vol_estimate(rv, self.vol_index)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_iv(self, date: pd.Timestamp) -> float:
        """Get IV for date, falling back to recent value if missing."""
        if date in self.iv_series.index:
            iv = self.iv_series.loc[date]
        else:
            iv = self.iv_series.asof(date)
        if iv is None or np.isnan(iv) or iv <= 0:
            iv = 0.25  # fallback
        return float(iv)

    def _get_price(self, date: pd.Timestamp) -> Optional[float]:
        """Get close price on date (or as-of)."""
        if date in self.prices.index:
            return float(self.prices.loc[date, "close"])
        try:
            return float(self.prices["close"].asof(date))
        except Exception:
            return None

    def _select_strike(self, spot: float, T: float, iv: float, r: float) -> float:
        """Pick strike based on strategy method, rounded to $0.50/$1 grid."""
        cfg = self.strategy
        if cfg.strike_method == "delta":
            raw = strike_from_delta(spot, cfg.target_delta, T, r, iv, self.div_yield)
        else:  # otm_pct
            raw = spot * (1 + cfg.target_otm_pct / 100)

        # Snap to typical strike grid: $1 if price<50, $2.50 if <200, $5 if <500, else $10
        if spot < 50:
            grid = 1.0
        elif spot < 200:
            grid = 2.5
        elif spot < 500:
            grid = 5.0
        else:
            grid = 10.0
        return round(raw / grid) * grid

    def _find_next_expiry(self, current_date: pd.Timestamp, target_dte: int) -> pd.Timestamp:
        """
        Find a Friday roughly target_dte days away (US monthly/weekly expiries are Fridays).
        We use simple Friday-snap; close enough for backtest.
        """
        target_date = current_date + pd.Timedelta(days=target_dte)
        # Snap to nearest Friday
        weekday = target_date.weekday()  # Monday=0 ... Friday=4
        days_to_friday = (4 - weekday) % 7
        if days_to_friday == 0 and target_date <= current_date:
            days_to_friday = 7
        return target_date + pd.Timedelta(days=days_to_friday)

    def _dividends_between(self, start: pd.Timestamp, end: pd.Timestamp) -> float:
        """Sum dividends paid in (start, end] window."""
        if "dividends" not in self.prices.columns:
            return 0.0
        mask = (self.prices.index > start) & (self.prices.index <= end)
        return float(self.prices.loc[mask, "dividends"].sum())

    # ------------------------------------------------------------------
    # Core loop
    # ------------------------------------------------------------------

    def run(self) -> BacktestResult:
        cfg = self.strategy
        trades: List[Trade] = []

        # Restrict to backtest window
        prices = self.prices[
            (self.prices.index >= self.start_date) &
            (self.prices.index <= self.end_date)
        ]
        if prices.empty:
            return BacktestResult(cfg.name, self.symbol, [], pd.DataFrame(), {}, cfg)

        trading_days = prices.index
        equity_records = []

        # Initial state
        shares = self.starting_shares
        contracts = shares // 100
        initial_spot = float(prices.iloc[0]["close"])
        cost_basis = initial_spot
        cash = 0.0   # premium collected, dividends, etc.

        # Active CC state
        active_strike: Optional[float] = None
        active_expiry: Optional[pd.Timestamp] = None
        active_entry_date: Optional[pd.Timestamp] = None
        active_entry_spot: Optional[float] = None
        active_premium: Optional[float] = None
        active_iv: Optional[float] = None
        active_delta: Optional[float] = None

        i = 0
        while i < len(trading_days):
            today = trading_days[i]
            spot = float(prices.loc[today, "close"])
            r = get_risk_free_rate(today)

            # --------------------------------------------------------
            # If no active CC, open one
            # --------------------------------------------------------
            if active_strike is None and contracts > 0:
                expiry = self._find_next_expiry(today, cfg.target_dte)
                T = max((expiry - today).days, 1) / 365.0
                iv = self._get_iv(today)

                strike = self._select_strike(spot, T, iv, r)
                premium = bs_call_price(spot, strike, T, r, iv, self.div_yield)
                # Apply bid-ask haircut (we sell at bid ≈ mid * (1 - spread/2))
                premium_received = premium * (1 - cfg.bid_ask_spread_pct / 2)
                delta = bs_call_delta(spot, strike, T, r, iv, self.div_yield)

                # Collect premium
                cash += premium_received * 100 * contracts
                cash -= cfg.commission_per_contract * contracts

                active_strike = strike
                active_expiry = expiry
                active_entry_date = today
                active_entry_spot = spot
                active_premium = premium_received
                active_iv = iv
                active_delta = delta

            # --------------------------------------------------------
            # Check close conditions
            # --------------------------------------------------------
            close_reason = None
            close_premium = 0.0

            if active_strike is not None:
                dte = (active_expiry - today).days

                # 1. Expiry today (or past)
                if dte <= 0 or today >= active_expiry:
                    if spot > active_strike:
                        # Assigned: stock called away at strike
                        close_reason = "assigned"
                        close_premium = 0.0
                    else:
                        close_reason = "expired_otm"
                        close_premium = 0.0

                else:
                    T = dte / 365.0
                    iv = self._get_iv(today)
                    current_call_price = bs_call_price(
                        spot, active_strike, T, r, iv, self.div_yield
                    )
                    current_call_price *= (1 + cfg.bid_ask_spread_pct / 2)  # buy at ask

                    profit_pct = (
                        (active_premium - current_call_price) / active_premium
                        if active_premium > 0 else 0
                    )

                    # 2. Profit target
                    if cfg.close_rule in ("profit_50", "hybrid") and profit_pct >= cfg.profit_take_pct:
                        close_reason = "profit_50"
                        close_premium = current_call_price
                    # 3. DTE-based close
                    elif cfg.close_rule in ("dte_21", "hybrid") and dte <= cfg.dte_close_threshold:
                        close_reason = "dte_21"
                        close_premium = current_call_price

            # --------------------------------------------------------
            # Execute close
            # --------------------------------------------------------
            if close_reason is not None:
                divs = self._dividends_between(active_entry_date, today) * shares
                cash += divs

                if close_reason == "assigned":
                    # Stock called away at strike, then re-buy at next day's open
                    stock_pnl_during_hold = (active_strike - active_entry_spot) * shares
                    cash += shares * active_strike  # receive strike for shares
                    shares = 0
                    contracts = 0

                    # Re-buy shares next trading day to keep CC going
                    if i + 1 < len(trading_days):
                        next_day = trading_days[i + 1]
                        rebuy_price = float(prices.loc[next_day, "open"]
                                          if "open" in prices.columns
                                          else prices.loc[next_day, "close"])
                        # How many shares can we afford to maintain ~same contract count?
                        # Simplification: always rebuy starting_shares (assume capital available)
                        cost = self.starting_shares * rebuy_price
                        cash -= cost
                        shares = self.starting_shares
                        contracts = shares // 100
                        cost_basis = rebuy_price
                else:
                    # Closed via buy-back or expired worthless
                    cash -= close_premium * 100 * contracts
                    cash -= cfg.commission_per_contract * contracts if close_premium > 0 else 0
                    stock_pnl_during_hold = (spot - active_entry_spot) * shares

                premium_pnl = (active_premium - close_premium) * 100 * contracts

                trades.append(Trade(
                    strategy=cfg.name,
                    symbol=self.symbol,
                    entry_date=active_entry_date,
                    exit_date=today,
                    entry_spot=active_entry_spot,
                    exit_spot=spot,
                    strike=active_strike,
                    dte_at_entry=(active_expiry - active_entry_date).days,
                    dte_at_exit=max(0, (active_expiry - today).days),
                    premium_collected=active_premium,
                    premium_paid_to_close=close_premium,
                    iv_at_entry=active_iv,
                    delta_at_entry=active_delta,
                    exit_reason=close_reason,
                    premium_pnl=premium_pnl,
                    stock_pnl_during_hold=stock_pnl_during_hold,
                    dividends_collected=divs,
                    commissions=cfg.commission_per_contract * contracts * (2 if close_premium > 0 else 1),
                ))

                # Reset active position
                active_strike = None
                active_expiry = None
                active_entry_date = None
                active_entry_spot = None
                active_premium = None
                active_iv = None
                active_delta = None

            # --------------------------------------------------------
            # Daily equity snapshot
            # --------------------------------------------------------
            # Mark-to-market option liability
            option_mtm = 0.0
            if active_strike is not None:
                dte = max(1, (active_expiry - today).days)
                T = dte / 365.0
                iv = self._get_iv(today)
                option_mtm = bs_call_price(spot, active_strike, T, r, iv, self.div_yield)

            stock_value = shares * spot
            # Short option = liability (we owe to close)
            option_liability = option_mtm * 100 * contracts
            equity = stock_value + cash - option_liability

            equity_records.append({
                "date": today,
                "spot": spot,
                "stock_value": stock_value,
                "cash": cash,
                "option_liability": option_liability,
                "equity": equity,
                "shares": shares,
                "active_strike": active_strike,
            })

            i += 1

        equity_df = pd.DataFrame(equity_records).set_index("date")

        # Buy-and-hold benchmark
        equity_df["bh_equity"] = self.starting_shares * prices["close"]

        metrics = self._compute_metrics(equity_df, trades)

        return BacktestResult(
            strategy_name=cfg.name,
            symbol=self.symbol,
            trades=trades,
            equity_curve=equity_df,
            metrics=metrics,
            config=cfg,
        )

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    def _compute_metrics(self, equity: pd.DataFrame, trades: List[Trade]) -> Dict:
        if equity.empty:
            return {}

        eq = equity["equity"]
        bh = equity["bh_equity"]
        returns = eq.pct_change().dropna()

        days = (equity.index[-1] - equity.index[0]).days
        years = max(days / 365.25, 0.01)

        total_return = (eq.iloc[-1] / eq.iloc[0]) - 1
        cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / years) - 1
        bh_total = (bh.iloc[-1] / bh.iloc[0]) - 1
        bh_cagr = (bh.iloc[-1] / bh.iloc[0]) ** (1 / years) - 1

        vol_annual = returns.std() * np.sqrt(252) if len(returns) > 1 else 0
        sharpe = (returns.mean() * 252) / (returns.std() * np.sqrt(252)) if returns.std() > 0 else 0

        # Max drawdown
        cummax = eq.cummax()
        drawdown = (eq - cummax) / cummax
        max_dd = drawdown.min()

        # Trade stats
        n_trades = len(trades)
        wins = [t for t in trades if t.premium_pnl > 0]
        win_rate = len(wins) / n_trades if n_trades > 0 else 0
        total_premium = sum(t.premium_pnl for t in trades)
        total_divs = sum(t.dividends_collected for t in trades)
        n_assigned = sum(1 for t in trades if t.exit_reason == "assigned")
        avg_dte_held = np.mean([
            (t.exit_date - t.entry_date).days for t in trades
        ]) if trades else 0

        return {
            "total_return": total_return,
            "cagr": cagr,
            "bh_total_return": bh_total,
            "bh_cagr": bh_cagr,
            "excess_return": total_return - bh_total,
            "volatility": vol_annual,
            "sharpe": sharpe,
            "max_drawdown": max_dd,
            "n_trades": n_trades,
            "win_rate": win_rate,
            "n_assigned": n_assigned,
            "total_premium_collected": total_premium,
            "total_dividends": total_divs,
            "avg_dte_held": avg_dte_held,
            "final_equity": float(eq.iloc[-1]),
            "bh_final_equity": float(bh.iloc[-1]),
        }


# ============================================================================
# Strategy Matrix Runner
# ============================================================================

def build_strategy_matrix(
    strike_methods: List[Dict],
    dtes: List[int],
    close_rules: List[str],
) -> List[CCStrategy]:
    """
    Cross-product of strategy parameters → list of CCStrategy objects.

    strike_methods: e.g., [{"method":"delta","value":0.25}, {"method":"otm_pct","value":5}]
    dtes: e.g., [30, 45]
    close_rules: e.g., ["expiry", "profit_50", "dte_21", "hybrid"]
    """
    strategies = []
    for sm in strike_methods:
        for dte in dtes:
            for cr in close_rules:
                if sm["method"] == "delta":
                    name = f"Δ{sm['value']:.2f}_{dte}DTE_{cr}"
                    s = CCStrategy(
                        name=name,
                        strike_method="delta",
                        target_delta=sm["value"],
                        target_dte=dte,
                        close_rule=cr,
                    )
                else:
                    name = f"OTM{sm['value']:.1f}%_{dte}DTE_{cr}"
                    s = CCStrategy(
                        name=name,
                        strike_method="otm_pct",
                        target_otm_pct=sm["value"],
                        target_dte=dte,
                        close_rule=cr,
                    )
                strategies.append(s)
    return strategies


def run_matrix(
    data: dict,
    strategies: List[CCStrategy],
    progress_callback=None,
) -> List[BacktestResult]:
    """Run all strategies on a single underlying and return results."""
    results = []
    for i, strat in enumerate(strategies):
        if progress_callback:
            progress_callback(i, len(strategies), strat.name)
        bt = CCBacktest(data, strat)
        results.append(bt.run())
    return results
