"""
Covered Call Screener
Combines high-premium (IV Rank) and Delta-range strategies.
"""
import pandas as pd
import numpy as np
from datetime import datetime
from typing import List, Dict, Optional
from dataclasses import dataclass


@dataclass
class ScreenerConfig:
    """User-configurable screening parameters."""
    # Delta strategy
    min_delta: float = 0.15
    max_delta: float = 0.35

    # Premium / yield
    min_premium_pct: float = 0.5      # min premium as % of stock price
    min_annualized_return: float = 12.0  # %

    # IV Rank
    min_iv_rank: float = 30.0          # only consider when IV is elevated

    # Expiration window (DTE = days to expiration)
    min_dte: int = 21
    max_dte: int = 50

    # Liquidity
    min_volume: int = 10
    min_open_interest: int = 100
    max_bid_ask_spread_pct: float = 10.0  # (ask-bid)/mid

    # Capital protection
    min_otm_pct: float = 2.0           # strike must be at least X% above spot


def calculate_iv_rank(current_iv: float, iv_history: pd.Series) -> Optional[float]:
    """
    IV Rank = (current_iv - 52w_low) / (52w_high - 52w_low) * 100
    Higher = IV is rich relative to its history = better time to sell options.
    """
    if iv_history is None or len(iv_history) < 20 or current_iv is None:
        return None
    iv_history = iv_history.dropna()
    if iv_history.empty:
        return None
    lo, hi = iv_history.min(), iv_history.max()
    if hi <= lo:
        return None
    return float(np.clip((current_iv - lo) / (hi - lo) * 100, 0, 100))


def calculate_metrics(row: pd.Series, spot: float, dte: int) -> Dict:
    """Compute derived metrics for a single option row."""
    mid = row.get("mid")
    strike = row["strike"]

    if mid is None or mid <= 0 or spot <= 0 or dte <= 0:
        return {
            "premium_pct": None,
            "annualized_return": None,
            "static_return": None,
            "if_called_return": None,
            "downside_protection": None,
            "spread_pct": None,
        }

    # Premium as % of current stock price
    premium_pct = (mid / spot) * 100

    # Static return: if stock stays flat, premium captured / capital
    static_return = (mid / spot) * 100
    static_annualized = static_return * (365 / dte)

    # If-called return: premium + capital gain if assigned
    if_called = ((mid + max(0, strike - spot)) / spot) * 100
    if_called_annualized = if_called * (365 / dte)

    # Downside protection: how far stock can drop before losing money
    downside_protection = (mid / spot) * 100

    # Bid-ask spread quality
    bid, ask = row.get("bid"), row.get("ask")
    spread_pct = None
    if bid and ask and mid > 0:
        spread_pct = ((ask - bid) / mid) * 100

    return {
        "premium_pct": round(premium_pct, 2),
        "annualized_return": round(static_annualized, 2),
        "if_called_return": round(if_called, 2),
        "if_called_annualized": round(if_called_annualized, 2),
        "downside_protection": round(downside_protection, 2),
        "spread_pct": round(spread_pct, 2) if spread_pct else None,
    }


def score_candidate(row: pd.Series, cfg: ScreenerConfig) -> float:
    """
    Composite score (0-100) ranking attractiveness.
    Weights: annualized return (40%), IV rank (30%), liquidity (15%),
             delta sweet-spot (15%).
    """
    score = 0.0

    # 1. Annualized return component
    ann = row.get("annualized_return") or 0
    score += min(40, ann / 30 * 40)  # 30% annualized = full marks

    # 2. IV Rank component
    ivr = row.get("iv_rank") or 0
    score += (ivr / 100) * 30

    # 3. Liquidity (volume + open interest)
    vol = row.get("volume") or 0
    oi = row.get("open_interest") or 0
    liq_score = min(1.0, np.log1p(vol + oi) / np.log1p(2000))
    score += liq_score * 15

    # 4. Delta sweet spot (peaks at midpoint of user range)
    delta = abs(row.get("delta") or 0)
    target = (cfg.min_delta + cfg.max_delta) / 2
    width = (cfg.max_delta - cfg.min_delta) / 2
    if width > 0:
        delta_score = max(0, 1 - abs(delta - target) / width)
        score += delta_score * 15

    return round(score, 1)


def filter_candidates(df: pd.DataFrame, cfg: ScreenerConfig) -> pd.DataFrame:
    """Apply hard filters from config."""
    if df.empty:
        return df

    mask = pd.Series(True, index=df.index)

    if "delta" in df.columns:
        mask &= df["delta"].between(cfg.min_delta, cfg.max_delta, inclusive="both")

    if "annualized_return" in df.columns:
        mask &= df["annualized_return"] >= cfg.min_annualized_return

    if "premium_pct" in df.columns:
        mask &= df["premium_pct"] >= cfg.min_premium_pct

    if "iv_rank" in df.columns:
        # Allow null IV rank to pass (history not always available)
        mask &= (df["iv_rank"].isna() | (df["iv_rank"] >= cfg.min_iv_rank))

    if "dte" in df.columns:
        mask &= df["dte"].between(cfg.min_dte, cfg.max_dte)

    if "volume" in df.columns:
        mask &= (df["volume"].fillna(0) >= cfg.min_volume)

    if "open_interest" in df.columns:
        mask &= (df["open_interest"].fillna(0) >= cfg.min_open_interest)

    if "spread_pct" in df.columns:
        mask &= (df["spread_pct"].isna() | (df["spread_pct"] <= cfg.max_bid_ask_spread_pct))

    if "otm_pct" in df.columns:
        mask &= df["otm_pct"] >= cfg.min_otm_pct

    return df[mask].copy()


def screen_symbol(
    symbol: str,
    spot: float,
    options_df: pd.DataFrame,
    iv_rank: Optional[float],
    cfg: ScreenerConfig,
) -> pd.DataFrame:
    """
    Run full screening pipeline for one underlying.

    Args:
        symbol: ticker
        spot: current stock price
        options_df: DataFrame from IBKRClient.get_call_options_data()
        iv_rank: current IV rank for the underlying
        cfg: screening config
    """
    if options_df.empty:
        return pd.DataFrame()

    df = options_df.copy()
    df["spot"] = spot
    df["iv_rank"] = iv_rank
    df["otm_pct"] = ((df["strike"] - spot) / spot * 100).round(2)

    # Days to expiration
    today = datetime.now().date()
    df["dte"] = df["expiration"].apply(
        lambda e: (datetime.strptime(e, "%Y%m%d").date() - today).days
    )

    # Compute per-row metrics
    metrics = df.apply(lambda r: calculate_metrics(r, spot, r["dte"]), axis=1)
    metrics_df = pd.DataFrame(list(metrics))
    df = pd.concat([df.reset_index(drop=True), metrics_df.reset_index(drop=True)], axis=1)

    # Apply filters
    filtered = filter_candidates(df, cfg)

    # Score & sort
    if not filtered.empty:
        filtered["score"] = filtered.apply(lambda r: score_candidate(r, cfg), axis=1)
        filtered = filtered.sort_values("score", ascending=False)

    return filtered
