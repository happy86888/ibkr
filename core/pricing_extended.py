"""
Extended pricing: Puts and additional Greeks for CSP/Wheel/PMCC strategies.
"""
import numpy as np
from scipy.stats import norm


def bs_put_price(S: float, K: float, T: float, r: float, sigma: float, q: float = 0.0) -> float:
    """Black-Scholes put option price."""
    if T <= 0 or sigma <= 0 or S <= 0:
        return max(0.0, K - S)
    d1 = (np.log(S / K) + (r - q + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    return K * np.exp(-r * T) * norm.cdf(-d2) - S * np.exp(-q * T) * norm.cdf(-d1)


def bs_put_delta(S: float, K: float, T: float, r: float, sigma: float, q: float = 0.0) -> float:
    """Put option delta (negative value)."""
    if T <= 0 or sigma <= 0 or S <= 0:
        return -1.0 if S < K else 0.0
    d1 = (np.log(S / K) + (r - q + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    return np.exp(-q * T) * (norm.cdf(d1) - 1)


def strike_from_put_delta(
    S: float, target_delta: float, T: float, r: float, sigma: float, q: float = 0.0
) -> float:
    """
    Solve for the put strike that produces the given delta.
    target_delta should be POSITIVE (e.g., 0.20 for -0.20 put delta).
    """
    if T <= 0 or sigma <= 0:
        return S * 0.95  # fallback (OTM put)
    # put_delta = e^(-qT) * (N(d1) - 1)
    # so N(d1) = 1 + put_delta * e^(qT) where put_delta is negative
    # using |target_delta|: N(d1) = 1 - |target_delta| * e^(qT)
    adjusted = 1 - min(0.999, max(0.001, target_delta * np.exp(q * T)))
    d1 = norm.ppf(adjusted)
    ln_S_K = d1 * sigma * np.sqrt(T) - (r - q + 0.5 * sigma ** 2) * T
    return S / np.exp(ln_S_K)
