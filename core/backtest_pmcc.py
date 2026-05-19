"""
Poor Man's Covered Call (PMCC) Backtest.

Structure:
  - LONG: Deep ITM LEAPS call (e.g., 180 DTE, delta 0.80) — acts as "stock replacement"
  - SHORT: OTM short-term call (e.g., 30 DTE, delta 0.25) — generates income

Capital efficient: LEAPS costs ~50% of stock, with similar upside.

Risks:
  - Short call strike MUST be > LEAPS strike + LEAPS cost basis to avoid loss if assigned
  - LEAPS theta decay slowly bleeds
  - Need to roll LEAPS before too much time decay (typically when 60-90 DTE remain)
"""
import pandas as pd
import numpy as np
from dataclasses import dataclass, asdict
from typing import List, Optional, Literal
from .pricing import bs_call_price, bs_call_delta, strike_from_delta, \
    realized_volatility, implied_vol_estimate
from .data_loader import get_risk_free_rate
from .backtest import Trade, BacktestResult


@dataclass
class PMCCStrategy:
    """Poor Man's Covered Call strategy."""
    name: str
    # LEAPS (long leg)
    leaps_delta: float = 0.80          # deep ITM
    leaps_dte: int = 365               # 1 year out
    leaps_roll_dte: int = 60           # roll LEAPS when this much time left

    # Short call
    short_delta: float = 0.25
    short_dte: int = 30
    short_close_rule: Literal["expiry", "profit_50", "dte_21", "hybrid"] = "hybrid"
    short_profit_take_pct: float = 0.50
    short_dte_close_threshold: int = 21

    # Costs
    bid_ask_spread_pct: float = 0.07   # LEAPS have wider spreads
    commission_per_contract: float = 0.65

    # Safety: short strike must be > leaps_strike + leaps_cost + buffer
    enforce_strike_above_cost_basis: bool = True

    def to_dict(self):
        return asdict(self)


def _snap_strike(spot, raw):
    if spot < 50: grid = 1.0
    elif spot < 200: grid = 2.5
    elif spot < 500: grid = 5.0
    else: grid = 10.0
    return round(raw / grid) * grid


def _next_friday(date, target_dte):
    target = date + pd.Timedelta(days=target_dte)
    weekday = target.weekday()
    days_to_friday = (4 - weekday) % 7
    if days_to_friday == 0 and target <= date:
        days_to_friday = 7
    return target + pd.Timedelta(days=days_to_friday)


class PMCCBacktest:
    """
    PMCC strategy backtest.
    Starts with cash, buys a LEAPS, then sells short-term calls against it.
    """

    def __init__(self, data: dict, strategy: PMCCStrategy, starting_cash: float = None):
        self.symbol = data["symbol"]
        self.prices = data["prices"]
        self.vol_index = data["vol_index"]
        self.div_yield = data["div_yield"]
        self.start_date = pd.Timestamp(data["start"])
        self.end_date = pd.Timestamp(data["end"])
        self.strategy = strategy

        # Default starting cash: enough for 1 LEAPS at ~50% of stock price
        if starting_cash is None:
            first_close = self.prices[self.prices.index >= self.start_date]
            if not first_close.empty:
                starting_cash = float(first_close.iloc[0]["close"]) * 60  # enough buffer for LEAPS
            else:
                starting_cash = 10000
        self.starting_cash = starting_cash

        rv = realized_volatility(self.prices["close"], window=30)
        self.iv_series = implied_vol_estimate(rv, self.vol_index)

    def _get_iv(self, date):
        if date in self.iv_series.index:
            iv = self.iv_series.loc[date]
        else:
            iv = self.iv_series.asof(date)
        if iv is None or np.isnan(iv) or iv <= 0:
            iv = 0.25
        return float(iv)

    def run(self) -> BacktestResult:
        cfg = self.strategy
        trades: List[Trade] = []
        prices = self.prices[
            (self.prices.index >= self.start_date) &
            (self.prices.index <= self.end_date)
        ]
        if prices.empty:
            return BacktestResult(cfg.name, self.symbol, [], pd.DataFrame(), {}, cfg)

        trading_days = prices.index
        cash = self.starting_cash
        equity_records = []

        # LEAPS state (long position)
        leaps_strike: Optional[float] = None
        leaps_expiry: Optional[pd.Timestamp] = None
        leaps_cost_basis: Optional[float] = None  # what we paid per share
        leaps_entry_date: Optional[pd.Timestamp] = None
        leaps_entry_spot: Optional[float] = None

        # Short call state
        short_strike: Optional[float] = None
        short_expiry: Optional[pd.Timestamp] = None
        short_entry_date: Optional[pd.Timestamp] = None
        short_entry_spot: Optional[float] = None
        short_premium: Optional[float] = None
        short_iv: Optional[float] = None
        short_delta: Optional[float] = None

        i = 0
        while i < len(trading_days):
            today = trading_days[i]
            spot = float(prices.loc[today, "close"])
            r = get_risk_free_rate(today)

            # ---- LEAPS management: buy initially or roll when expiring soon ----
            need_new_leaps = (leaps_strike is None) or \
                             ((leaps_expiry - today).days <= cfg.leaps_roll_dte)

            if need_new_leaps:
                # Close existing LEAPS first (if any)
                if leaps_strike is not None:
                    dte_leaps = max(1, (leaps_expiry - today).days)
                    T_leaps = dte_leaps / 365.0
                    iv = self._get_iv(today)
                    sell_price = bs_call_price(spot, leaps_strike, T_leaps, r, iv, self.div_yield)
                    sell_price *= (1 - cfg.bid_ask_spread_pct / 2)
                    cash += sell_price * 100
                    cash -= cfg.commission_per_contract

                # Open new LEAPS
                leaps_exp_new = _next_friday(today, cfg.leaps_dte)
                T_new = max((leaps_exp_new - today).days, 1) / 365.0
                iv = self._get_iv(today)
                leaps_strike_new = _snap_strike(spot, strike_from_delta(
                    spot, cfg.leaps_delta, T_new, r, iv, self.div_yield))
                # Deep ITM: strike should be BELOW spot for delta 0.80
                leaps_price = bs_call_price(spot, leaps_strike_new, T_new, r, iv, self.div_yield)
                buy_price = leaps_price * (1 + cfg.bid_ask_spread_pct / 2)

                if cash < buy_price * 100:
                    # Can't afford LEAPS, abort
                    print(f"Insufficient cash for LEAPS at {today}: need ${buy_price*100:.0f}, have ${cash:.0f}")
                    break

                cash -= buy_price * 100
                cash -= cfg.commission_per_contract

                leaps_strike = leaps_strike_new
                leaps_expiry = leaps_exp_new
                leaps_cost_basis = buy_price
                leaps_entry_date = today
                leaps_entry_spot = spot

            # ---- Open short call ----
            if short_strike is None and leaps_strike is not None:
                short_exp = _next_friday(today, cfg.short_dte)
                # Make sure short doesn't expire after LEAPS
                if short_exp >= leaps_expiry:
                    short_exp = leaps_expiry - pd.Timedelta(days=7)
                T_short = max((short_exp - today).days, 1) / 365.0
                iv = self._get_iv(today)
                short_strike_new = _snap_strike(spot, strike_from_delta(
                    spot, cfg.short_delta, T_short, r, iv, self.div_yield))

                # Safety: ensure short strike > leaps_strike + leaps_cost_basis
                # (so worst case = assigned, we deliver via LEAPS at profit)
                if cfg.enforce_strike_above_cost_basis:
                    min_safe_strike = leaps_strike + leaps_cost_basis
                    if short_strike_new < min_safe_strike:
                        short_strike_new = _snap_strike(spot, min_safe_strike * 1.01)

                premium = bs_call_price(spot, short_strike_new, T_short, r, iv, self.div_yield)
                premium_received = premium * (1 - cfg.bid_ask_spread_pct / 2)
                delta = bs_call_delta(spot, short_strike_new, T_short, r, iv, self.div_yield)

                cash += premium_received * 100
                cash -= cfg.commission_per_contract

                short_strike = short_strike_new
                short_expiry = short_exp
                short_entry_date = today
                short_entry_spot = spot
                short_premium = premium_received
                short_iv = iv
                short_delta = delta

            # ---- Check short close ----
            short_close_reason = None
            short_close_premium = 0.0
            if short_strike is not None:
                dte = (short_expiry - today).days
                if dte <= 0 or today >= short_expiry:
                    short_close_reason = "assigned" if spot > short_strike else "expired_otm"
                else:
                    T = dte / 365.0
                    iv = self._get_iv(today)
                    cur = bs_call_price(spot, short_strike, T, r, iv, self.div_yield)
                    cur *= (1 + cfg.bid_ask_spread_pct / 2)
                    pct = (short_premium - cur) / short_premium if short_premium > 0 else 0
                    if cfg.short_close_rule in ("profit_50", "hybrid") and pct >= cfg.short_profit_take_pct:
                        short_close_reason = "profit_50"
                        short_close_premium = cur
                    elif cfg.short_close_rule in ("dte_21", "hybrid") and dte <= cfg.short_dte_close_threshold:
                        short_close_reason = "dte_21"
                        short_close_premium = cur

            # ---- Execute short close ----
            if short_close_reason is not None:
                if short_close_reason == "assigned":
                    # We sold a call → assigned → need to deliver shares
                    # Without shares, we exercise our LEAPS to get them
                    # Net effect: receive (short_strike - leaps_strike) * 100 minus commissions
                    # AND we lose the LEAPS, so we need to buy a new one next iteration
                    cash += short_strike * 100  # receive from short call exercise
                    cash -= leaps_strike * 100  # pay strike to exercise LEAPS
                    cash -= cfg.commission_per_contract * 2

                    # Realized profit on LEAPS = (short_strike - leaps_strike) - leaps_cost_basis
                    leaps_pnl = (short_strike - leaps_strike - leaps_cost_basis) * 100

                    trades.append(Trade(
                        strategy=cfg.name, symbol=self.symbol,
                        entry_date=short_entry_date, exit_date=today,
                        entry_spot=short_entry_spot, exit_spot=spot,
                        strike=short_strike,
                        dte_at_entry=(short_expiry - short_entry_date).days,
                        dte_at_exit=max(0, (short_expiry - today).days),
                        premium_collected=short_premium,
                        premium_paid_to_close=0,
                        iv_at_entry=short_iv,
                        delta_at_entry=short_delta,
                        exit_reason="assigned",
                        premium_pnl=short_premium * 100,
                        stock_pnl_during_hold=leaps_pnl,
                        dividends_collected=0,
                        commissions=cfg.commission_per_contract * 2,
                    ))

                    # LEAPS is gone; force new LEAPS next iteration
                    leaps_strike = None
                    leaps_expiry = None
                    leaps_cost_basis = None
                else:
                    cash -= short_close_premium * 100
                    if short_close_premium > 0:
                        cash -= cfg.commission_per_contract

                    trades.append(Trade(
                        strategy=cfg.name, symbol=self.symbol,
                        entry_date=short_entry_date, exit_date=today,
                        entry_spot=short_entry_spot, exit_spot=spot,
                        strike=short_strike,
                        dte_at_entry=(short_expiry - short_entry_date).days,
                        dte_at_exit=max(0, (short_expiry - today).days),
                        premium_collected=short_premium,
                        premium_paid_to_close=short_close_premium,
                        iv_at_entry=short_iv,
                        delta_at_entry=short_delta,
                        exit_reason=short_close_reason,
                        premium_pnl=(short_premium - short_close_premium) * 100,
                        stock_pnl_during_hold=0,
                        dividends_collected=0,
                        commissions=cfg.commission_per_contract * (2 if short_close_premium > 0 else 1),
                    ))

                short_strike = None
                short_expiry = None
                short_entry_date = None

            # ---- Daily equity (MTM LEAPS + short call liability) ----
            leaps_value = 0.0
            if leaps_strike is not None:
                dte_leaps = max(1, (leaps_expiry - today).days)
                T_leaps = dte_leaps / 365.0
                iv = self._get_iv(today)
                leaps_value = bs_call_price(spot, leaps_strike, T_leaps, r, iv, self.div_yield) * 100

            short_liability = 0.0
            if short_strike is not None:
                dte_short = max(1, (short_expiry - today).days)
                T_short = dte_short / 365.0
                iv = self._get_iv(today)
                short_liability = bs_call_price(spot, short_strike, T_short, r, iv, self.div_yield) * 100

            equity = cash + leaps_value - short_liability
            equity_records.append({
                "date": today, "spot": spot, "cash": cash,
                "leaps_value": leaps_value, "short_liability": short_liability,
                "equity": equity, "leaps_strike": leaps_strike, "short_strike": short_strike,
            })
            i += 1

        equity_df = pd.DataFrame(equity_records).set_index("date")
        first_price = prices.iloc[0]["close"]
        initial_shares = self.starting_cash / first_price
        equity_df["bh_equity"] = initial_shares * prices["close"]

        metrics = self._compute_metrics(equity_df, trades)
        return BacktestResult(cfg.name, self.symbol, trades, equity_df, metrics, cfg)

    def _compute_metrics(self, equity, trades):
        if equity.empty:
            return {}
        eq, bh = equity["equity"], equity["bh_equity"]
        returns = eq.pct_change().dropna()
        years = max((equity.index[-1] - equity.index[0]).days / 365.25, 0.01)
        if eq.iloc[0] <= 0 or eq.iloc[-1] <= 0:
            cagr = -1.0
        else:
            cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / years) - 1
        bh_cagr = (bh.iloc[-1] / bh.iloc[0]) ** (1 / years) - 1
        sharpe = (returns.mean() * 252) / (returns.std() * np.sqrt(252)) if returns.std() > 0 else 0
        max_dd = ((eq - eq.cummax()) / eq.cummax()).min()
        return {
            "total_return": (eq.iloc[-1] / eq.iloc[0]) - 1, "cagr": cagr,
            "bh_total_return": (bh.iloc[-1] / bh.iloc[0]) - 1, "bh_cagr": bh_cagr,
            "excess_return": (eq.iloc[-1] / eq.iloc[0]) - (bh.iloc[-1] / bh.iloc[0]),
            "volatility": returns.std() * np.sqrt(252) if len(returns) > 1 else 0,
            "sharpe": sharpe, "max_drawdown": max_dd,
            "n_trades": len(trades),
            "win_rate": sum(1 for t in trades if t.premium_pnl > 0) / len(trades) if trades else 0,
            "n_assigned": sum(1 for t in trades if t.exit_reason == "assigned"),
            "total_premium_collected": sum(t.premium_pnl for t in trades),
            "total_dividends": 0.0,
            "avg_dte_held": np.mean([(t.exit_date - t.entry_date).days for t in trades]) if trades else 0,
            "final_equity": float(eq.iloc[-1]),
            "bh_final_equity": float(bh.iloc[-1]),
        }
