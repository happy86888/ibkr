"""
Cash-Secured Put (CSP) and Wheel Strategy Backtest.

CSP:
  - Hold cash equal to (strike × 100)
  - Sell OTM put
  - If expired worthless: keep premium, repeat
  - If assigned: buy 100 shares at strike

Wheel:
  - Start as CSP
  - If assigned (own stock): switch to CC
  - If CC called away (cash again): switch back to CSP
"""
import pandas as pd
import numpy as np
from dataclasses import dataclass, asdict
from typing import List, Optional, Literal
from .pricing import bs_call_price, bs_call_delta, strike_from_delta, \
    realized_volatility, implied_vol_estimate
from .pricing_extended import bs_put_price, bs_put_delta, strike_from_put_delta
from .data_loader import get_risk_free_rate
from .backtest import Trade, BacktestResult


@dataclass
class CSPStrategy:
    """Cash-Secured Put strategy."""
    name: str
    target_delta: float = 0.20         # put delta target (positive value, will sell -0.20)
    target_otm_pct: float = 5.0        # alternative: % below spot
    strike_method: Literal["delta", "otm_pct"] = "delta"
    target_dte: int = 30
    close_rule: Literal["expiry", "profit_50", "dte_21", "hybrid"] = "hybrid"
    profit_take_pct: float = 0.50
    dte_close_threshold: int = 21
    bid_ask_spread_pct: float = 0.05
    commission_per_contract: float = 0.65

    def to_dict(self):
        return asdict(self)


@dataclass
class WheelStrategy:
    """The Wheel: CSP → (if assigned) CC → (if called away) CSP → ..."""
    name: str
    # Put side
    put_delta: float = 0.20
    put_dte: int = 30
    # Call side
    call_delta: float = 0.25
    call_dte: int = 30
    # Common
    close_rule: Literal["expiry", "profit_50", "dte_21", "hybrid"] = "hybrid"
    profit_take_pct: float = 0.50
    dte_close_threshold: int = 21
    bid_ask_spread_pct: float = 0.05
    commission_per_contract: float = 0.65

    def to_dict(self):
        return asdict(self)


# ============================================================================
# Common helpers
# ============================================================================

def _snap_strike(spot: float, raw: float) -> float:
    """Snap to typical strike grid."""
    if spot < 50:
        grid = 1.0
    elif spot < 200:
        grid = 2.5
    elif spot < 500:
        grid = 5.0
    else:
        grid = 10.0
    return round(raw / grid) * grid


def _next_friday(date: pd.Timestamp, target_dte: int) -> pd.Timestamp:
    target = date + pd.Timedelta(days=target_dte)
    weekday = target.weekday()
    days_to_friday = (4 - weekday) % 7
    if days_to_friday == 0 and target <= date:
        days_to_friday = 7
    return target + pd.Timedelta(days=days_to_friday)


# ============================================================================
# CSP Backtest
# ============================================================================

class CSPBacktest:
    """
    Cash-Secured Put backtest.
    Starts with cash, sells puts, and may end up owning shares (which are then
    held until end of backtest - or in Wheel, switched to CCs).
    """

    def __init__(self, data: dict, strategy: CSPStrategy, starting_cash: float = None):
        self.symbol = data["symbol"]
        self.prices = data["prices"]
        self.vol_index = data["vol_index"]
        self.div_yield = data["div_yield"]
        self.start_date = pd.Timestamp(data["start"])
        self.end_date = pd.Timestamp(data["end"])
        self.strategy = strategy

        # Default: enough cash for 1 contract worth at first close
        if starting_cash is None:
            first_close = self.prices[self.prices.index >= self.start_date]
            if not first_close.empty:
                starting_cash = float(first_close.iloc[0]["close"]) * 100
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

    def _select_put_strike(self, spot, T, iv, r):
        cfg = self.strategy
        if cfg.strike_method == "delta":
            raw = strike_from_put_delta(spot, cfg.target_delta, T, r, iv, self.div_yield)
        else:
            raw = spot * (1 - cfg.target_otm_pct / 100)
        return _snap_strike(spot, raw)

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
        shares = 0       # CSP doesn't hold shares unless assigned
        equity_records = []

        # Active put state
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

            # Open new put when no active position and no shares yet
            # (Pure CSP: stop selling after first assignment; resulting shares held to end)
            if active_strike is None and shares == 0:
                expiry = _next_friday(today, cfg.target_dte)
                T = max((expiry - today).days, 1) / 365.0
                iv = self._get_iv(today)
                strike = self._select_put_strike(spot, T, iv, r)
                # Check we have enough cash (strike * 100 reserved)
                required_cash = strike * 100
                if cash < required_cash:
                    # Not enough cash; skip and wait for assignment to release positions
                    pass
                else:
                    premium = bs_put_price(spot, strike, T, r, iv, self.div_yield)
                    premium_received = premium * (1 - cfg.bid_ask_spread_pct / 2)
                    delta = bs_put_delta(spot, strike, T, r, iv, self.div_yield)

                    cash += premium_received * 100
                    cash -= cfg.commission_per_contract

                    active_strike = strike
                    active_expiry = expiry
                    active_entry_date = today
                    active_entry_spot = spot
                    active_premium = premium_received
                    active_iv = iv
                    active_delta = delta

            # Check close conditions
            close_reason = None
            close_premium = 0.0

            if active_strike is not None:
                dte = (active_expiry - today).days
                if dte <= 0 or today >= active_expiry:
                    if spot < active_strike:
                        close_reason = "assigned"  # put assigned, we buy shares
                    else:
                        close_reason = "expired_otm"
                else:
                    T = dte / 365.0
                    iv = self._get_iv(today)
                    cur_price = bs_put_price(spot, active_strike, T, r, iv, self.div_yield)
                    cur_price *= (1 + cfg.bid_ask_spread_pct / 2)
                    profit_pct = (
                        (active_premium - cur_price) / active_premium
                        if active_premium > 0 else 0
                    )
                    if cfg.close_rule in ("profit_50", "hybrid") and profit_pct >= cfg.profit_take_pct:
                        close_reason = "profit_50"
                        close_premium = cur_price
                    elif cfg.close_rule in ("dte_21", "hybrid") and dte <= cfg.dte_close_threshold:
                        close_reason = "dte_21"
                        close_premium = cur_price

            # Execute close
            if close_reason is not None:
                if close_reason == "assigned":
                    # Buy 100 shares at strike
                    cash -= active_strike * 100
                    shares += 100
                    stock_pnl = 0  # at moment of assignment, basis = strike
                    premium_pnl = active_premium * 100
                else:
                    cash -= close_premium * 100
                    if close_premium > 0:
                        cash -= cfg.commission_per_contract
                    premium_pnl = (active_premium - close_premium) * 100
                    stock_pnl = 0

                trades.append(Trade(
                    strategy=cfg.name, symbol=self.symbol,
                    entry_date=active_entry_date, exit_date=today,
                    entry_spot=active_entry_spot, exit_spot=spot,
                    strike=active_strike,
                    dte_at_entry=(active_expiry - active_entry_date).days,
                    dte_at_exit=max(0, (active_expiry - today).days),
                    premium_collected=active_premium,
                    premium_paid_to_close=close_premium,
                    iv_at_entry=active_iv,
                    delta_at_entry=active_delta,
                    exit_reason=close_reason,
                    premium_pnl=premium_pnl,
                    stock_pnl_during_hold=stock_pnl,
                    dividends_collected=0.0,
                    commissions=cfg.commission_per_contract * (2 if close_premium > 0 else 1),
                ))
                active_strike = None
                active_expiry = None
                active_entry_date = None
                active_entry_spot = None
                active_premium = None

            # Daily equity
            option_liability = 0.0
            if active_strike is not None:
                dte = max(1, (active_expiry - today).days)
                T = dte / 365.0
                iv = self._get_iv(today)
                option_liability = bs_put_price(spot, active_strike, T, r, iv, self.div_yield) * 100

            stock_value = shares * spot
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
        # BH benchmark: invest starting cash in stock at day 1
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
        days = (equity.index[-1] - equity.index[0]).days
        years = max(days / 365.25, 0.01)
        total_return = (eq.iloc[-1] / eq.iloc[0]) - 1
        cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / years) - 1
        bh_total = (bh.iloc[-1] / bh.iloc[0]) - 1
        bh_cagr = (bh.iloc[-1] / bh.iloc[0]) ** (1 / years) - 1
        sharpe = (returns.mean() * 252) / (returns.std() * np.sqrt(252)) if returns.std() > 0 else 0
        cummax = eq.cummax()
        drawdown = (eq - cummax) / cummax
        max_dd = drawdown.min()
        n_trades = len(trades)
        wins = [t for t in trades if t.premium_pnl > 0]
        win_rate = len(wins) / n_trades if n_trades > 0 else 0
        n_assigned = sum(1 for t in trades if t.exit_reason == "assigned")
        return {
            "total_return": total_return, "cagr": cagr,
            "bh_total_return": bh_total, "bh_cagr": bh_cagr,
            "excess_return": total_return - bh_total,
            "volatility": returns.std() * np.sqrt(252) if len(returns) > 1 else 0,
            "sharpe": sharpe, "max_drawdown": max_dd,
            "n_trades": n_trades, "win_rate": win_rate, "n_assigned": n_assigned,
            "total_premium_collected": sum(t.premium_pnl for t in trades),
            "total_dividends": 0.0,
            "avg_dte_held": np.mean([(t.exit_date - t.entry_date).days for t in trades]) if trades else 0,
            "final_equity": float(eq.iloc[-1]),
            "bh_final_equity": float(bh.iloc[-1]),
        }


# ============================================================================
# Wheel Backtest
# ============================================================================

class WheelBacktest:
    """
    The Wheel: alternates between CSP and CC depending on assignment state.

    State machine:
      STATE_CSP:  no shares, selling puts
        → on put assignment → STATE_CC (now own 100 shares)
      STATE_CC:   own 100 shares, selling calls
        → on call assignment → STATE_CSP (back to cash)
    """

    def __init__(self, data: dict, strategy: WheelStrategy, starting_cash: float = None):
        self.symbol = data["symbol"]
        self.prices = data["prices"]
        self.vol_index = data["vol_index"]
        self.div_yield = data["div_yield"]
        self.start_date = pd.Timestamp(data["start"])
        self.end_date = pd.Timestamp(data["end"])
        self.strategy = strategy

        if starting_cash is None:
            first_close = self.prices[self.prices.index >= self.start_date]
            starting_cash = float(first_close.iloc[0]["close"]) * 100 if not first_close.empty else 10000
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

    def _dividends_between(self, start, end):
        if "dividends" not in self.prices.columns:
            return 0.0
        mask = (self.prices.index > start) & (self.prices.index <= end)
        return float(self.prices.loc[mask, "dividends"].sum())

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
        shares = 0
        equity_records = []

        # Active option state (could be put or call)
        active_right: Optional[str] = None  # 'P' or 'C'
        active_strike = None
        active_expiry = None
        active_entry_date = None
        active_entry_spot = None
        active_premium = None
        active_iv = None
        active_delta = None

        i = 0
        while i < len(trading_days):
            today = trading_days[i]
            spot = float(prices.loc[today, "close"])
            r = get_risk_free_rate(today)

            # ---- Open new position when none active ----
            if active_strike is None:
                if shares == 0:
                    # CSP state
                    target_dte = cfg.put_dte
                    expiry = _next_friday(today, target_dte)
                    T = max((expiry - today).days, 1) / 365.0
                    iv = self._get_iv(today)
                    strike = _snap_strike(spot, strike_from_put_delta(
                        spot, cfg.put_delta, T, r, iv, self.div_yield))
                    required_cash = strike * 100
                    if cash >= required_cash:
                        premium = bs_put_price(spot, strike, T, r, iv, self.div_yield)
                        premium_received = premium * (1 - cfg.bid_ask_spread_pct / 2)
                        delta = bs_put_delta(spot, strike, T, r, iv, self.div_yield)
                        cash += premium_received * 100
                        cash -= cfg.commission_per_contract
                        active_right = "P"
                        active_strike = strike
                        active_expiry = expiry
                        active_entry_date = today
                        active_entry_spot = spot
                        active_premium = premium_received
                        active_iv = iv
                        active_delta = delta
                else:
                    # CC state (have shares)
                    target_dte = cfg.call_dte
                    expiry = _next_friday(today, target_dte)
                    T = max((expiry - today).days, 1) / 365.0
                    iv = self._get_iv(today)
                    strike = _snap_strike(spot, strike_from_delta(
                        spot, cfg.call_delta, T, r, iv, self.div_yield))
                    premium = bs_call_price(spot, strike, T, r, iv, self.div_yield)
                    premium_received = premium * (1 - cfg.bid_ask_spread_pct / 2)
                    delta = bs_call_delta(spot, strike, T, r, iv, self.div_yield)
                    cash += premium_received * 100
                    cash -= cfg.commission_per_contract
                    active_right = "C"
                    active_strike = strike
                    active_expiry = expiry
                    active_entry_date = today
                    active_entry_spot = spot
                    active_premium = premium_received
                    active_iv = iv
                    active_delta = delta

            # ---- Check close conditions ----
            close_reason = None
            close_premium = 0.0
            if active_strike is not None:
                dte = (active_expiry - today).days
                if dte <= 0 or today >= active_expiry:
                    if active_right == "P":
                        close_reason = "assigned" if spot < active_strike else "expired_otm"
                    else:  # call
                        close_reason = "assigned" if spot > active_strike else "expired_otm"
                else:
                    T = dte / 365.0
                    iv = self._get_iv(today)
                    if active_right == "P":
                        cur = bs_put_price(spot, active_strike, T, r, iv, self.div_yield)
                    else:
                        cur = bs_call_price(spot, active_strike, T, r, iv, self.div_yield)
                    cur *= (1 + cfg.bid_ask_spread_pct / 2)
                    profit_pct = (active_premium - cur) / active_premium if active_premium > 0 else 0
                    if cfg.close_rule in ("profit_50", "hybrid") and profit_pct >= cfg.profit_take_pct:
                        close_reason = "profit_50"
                        close_premium = cur
                    elif cfg.close_rule in ("dte_21", "hybrid") and dte <= cfg.dte_close_threshold:
                        close_reason = "dte_21"
                        close_premium = cur

            # ---- Execute close ----
            if close_reason is not None:
                divs = 0.0
                stock_pnl = 0.0
                if active_right == "P":
                    if close_reason == "assigned":
                        cash -= active_strike * 100
                        shares += 100  # transition to CC state
                        premium_pnl = active_premium * 100
                    else:
                        cash -= close_premium * 100
                        if close_premium > 0:
                            cash -= cfg.commission_per_contract
                        premium_pnl = (active_premium - close_premium) * 100
                else:  # active_right == "C"
                    divs = self._dividends_between(active_entry_date, today) * shares
                    cash += divs
                    if close_reason == "assigned":
                        cash += active_strike * 100  # shares called away
                        stock_pnl = (active_strike - active_entry_spot) * shares
                        shares = 0  # back to CSP state
                        premium_pnl = active_premium * 100
                    else:
                        cash -= close_premium * 100
                        if close_premium > 0:
                            cash -= cfg.commission_per_contract
                        premium_pnl = (active_premium - close_premium) * 100
                        stock_pnl = (spot - active_entry_spot) * shares

                trades.append(Trade(
                    strategy=cfg.name, symbol=self.symbol,
                    entry_date=active_entry_date, exit_date=today,
                    entry_spot=active_entry_spot, exit_spot=spot,
                    strike=active_strike,
                    dte_at_entry=(active_expiry - active_entry_date).days,
                    dte_at_exit=max(0, (active_expiry - today).days),
                    premium_collected=active_premium,
                    premium_paid_to_close=close_premium,
                    iv_at_entry=active_iv,
                    delta_at_entry=active_delta,
                    exit_reason=f"{active_right}_{close_reason}",
                    premium_pnl=premium_pnl,
                    stock_pnl_during_hold=stock_pnl,
                    dividends_collected=divs,
                    commissions=cfg.commission_per_contract * (2 if close_premium > 0 else 1),
                ))
                active_right = None
                active_strike = None
                active_expiry = None
                active_entry_date = None
                active_entry_spot = None
                active_premium = None

            # ---- Daily equity ----
            opt_liability = 0.0
            if active_strike is not None:
                dte = max(1, (active_expiry - today).days)
                T = dte / 365.0
                iv = self._get_iv(today)
                if active_right == "P":
                    opt_liability = bs_put_price(spot, active_strike, T, r, iv, self.div_yield) * 100
                else:
                    opt_liability = bs_call_price(spot, active_strike, T, r, iv, self.div_yield) * 100
            stock_value = shares * spot
            equity = stock_value + cash - opt_liability
            equity_records.append({
                "date": today, "spot": spot, "stock_value": stock_value, "cash": cash,
                "option_liability": opt_liability, "equity": equity, "shares": shares,
                "active_strike": active_strike, "active_right": active_right,
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
        cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / years) - 1
        bh_cagr = (bh.iloc[-1] / bh.iloc[0]) ** (1 / years) - 1
        sharpe = (returns.mean() * 252) / (returns.std() * np.sqrt(252)) if returns.std() > 0 else 0
        max_dd = ((eq - eq.cummax()) / eq.cummax()).min()
        n_assigned = sum(1 for t in trades if "assigned" in t.exit_reason)
        n_put_trades = sum(1 for t in trades if t.exit_reason.startswith("P_"))
        n_call_trades = sum(1 for t in trades if t.exit_reason.startswith("C_"))
        return {
            "total_return": (eq.iloc[-1] / eq.iloc[0]) - 1, "cagr": cagr,
            "bh_total_return": (bh.iloc[-1] / bh.iloc[0]) - 1, "bh_cagr": bh_cagr,
            "excess_return": (eq.iloc[-1] / eq.iloc[0]) - (bh.iloc[-1] / bh.iloc[0]),
            "volatility": returns.std() * np.sqrt(252) if len(returns) > 1 else 0,
            "sharpe": sharpe, "max_drawdown": max_dd,
            "n_trades": len(trades),
            "win_rate": sum(1 for t in trades if t.premium_pnl > 0) / len(trades) if trades else 0,
            "n_assigned": n_assigned,
            "n_put_trades": n_put_trades,
            "n_call_trades": n_call_trades,
            "total_premium_collected": sum(t.premium_pnl for t in trades),
            "total_dividends": sum(t.dividends_collected for t in trades),
            "avg_dte_held": np.mean([(t.exit_date - t.entry_date).days for t in trades]) if trades else 0,
            "final_equity": float(eq.iloc[-1]),
            "bh_final_equity": float(bh.iloc[-1]),
        }
