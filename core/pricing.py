"""
Black-Scholes pricing & implied volatility modeling.

For backtesting CC strategies without paid options data, we synthesize
option premiums using:
  1. Real historical stock prices (yfinance)
  2. Realized volatility from price history
  3. IV/RV ratio adjustment (IV typically trades 15-25% above RV)
  4. VIX/VXN/RVX as market-wide vol calibrator
"""
import numpy as np
import pandas as pd
from scipy.stats import norm
from datetime import datetime, timedelta
from typing import Optional, Tuple


# ---------- Black-Scholes ----------

def bs_call_price(S: float, K: float, T: float, r: float, sigma: float, q: float = 0.0) -> float:
    """
    Black-Scholes call option price.
    S=spot, K=strike, T=years to expiry, r=risk-free, sigma=annualized vol, q=dividend yield
    """
    if T <= 0 or sigma <= 0 or S <= 0:
        return max(0.0, S - K)
    d1 = (np.log(S / K) + (r - q + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    return S * np.exp(-q * T) * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)


def bs_call_delta(S: float, K: float, T: float, r: float, sigma: float, q: float = 0.0) -> float:
    """Call option delta."""
    if T <= 0 or sigma <= 0 or S <= 0:
        return 1.0 if S > K else 0.0
    d1 = (np.log(S / K) + (r - q + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    return np.exp(-q * T) * norm.cdf(d1)


def strike_from_delta(
    S: float, target_delta: float, T: float, r: float, sigma: float, q: float = 0.0
) -> float:
    """
    Solve for the call strike that produces the given delta.
    Uses inverse normal CDF (closed-form for BS).
    """
    if T <= 0 or sigma <= 0:
        return S * 1.05  # fallback
    # delta = N(d1) for non-div stock => d1 = N^-1(delta)
    # but with dividend: delta = e^(-qT) * N(d1) => d1 = N^-1(delta * e^(qT))
    adjusted = min(0.999, max(0.001, target_delta * np.exp(q * T)))
    d1 = norm.ppf(adjusted)
    # d1 = (ln(S/K) + (r-q+sigma^2/2)T) / (sigma*sqrt(T))
    ln_S_K = d1 * sigma * np.sqrt(T) - (r - q + 0.5 * sigma ** 2) * T
    return S / np.exp(ln_S_K)


# ---------- Volatility Estimation ----------

def realized_volatility(prices: pd.Series, window: int = 30) -> pd.Series:
    """
    Rolling annualized realized volatility (close-to-close).
    Returns series aligned to prices.
    """
    log_returns = np.log(prices / prices.shift(1))
    return log_returns.rolling(window).std() * np.sqrt(252)


def implied_vol_estimate(
    realized_vol: pd.Series,
    market_vol: Optional[pd.Series] = None,
    iv_premium: float = 0.20,
) -> pd.Series:
    """
    Estimate IV from RV using empirical IV/RV ratio.

    Studies show IV trades ~10-30% above subsequent RV (volatility risk premium).
    When market vol index (VIX) is available, use it as a regime indicator.

    Args:
        realized_vol: stock's rolling RV
        market_vol: optional VIX-family index aligned to same dates
        iv_premium: baseline IV/RV premium (default 20%)
    """
    base_iv = realized_vol * (1 + iv_premium)

    if market_vol is not None and not market_vol.empty:
        # Blend: when VIX is high (regime shift), lean toward market signal
        # Normalize market vol around its own median
        aligned = market_vol.reindex(realized_vol.index, method="ffill")
        market_factor = aligned / aligned.rolling(252, min_periods=20).median()
        market_factor = market_factor.clip(0.7, 1.5).fillna(1.0)
        return base_iv * market_factor

    return base_iv
