"""
Historical data loader for backtesting.

Sources:
  - yfinance: stock prices, dividends
  - VIX/VXN/RVX (also via yfinance): market vol calibration
"""
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
from typing import Optional, Tuple
import logging

logger = logging.getLogger(__name__)


# Map underlyings to their associated vol index (when available)
VOL_INDEX_MAP = {
    # Broad market
    "SPY": "^VIX", "VOO": "^VIX", "IVV": "^VIX",
    "QQQ": "^VXN", "QQQM": "^VXN",
    "IWM": "^RVX",
    "DIA": "^VXD",
    # Default: ^VIX (general market proxy)
}


def fetch_history(
    symbol: str,
    start: str,
    end: str,
) -> pd.DataFrame:
    """
    Fetch OHLC + dividends. Returns DataFrame with date index and columns:
    open, high, low, close, adj_close, volume, dividends
    """
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(start=start, end=end, auto_adjust=False)
        if df.empty:
            return pd.DataFrame()
        df.columns = [c.lower().replace(" ", "_") for c in df.columns]
        # Ensure timezone-naive index
        df.index = pd.to_datetime(df.index).tz_localize(None)
        return df
    except Exception as e:
        logger.error(f"Failed to fetch {symbol}: {e}")
        return pd.DataFrame()


def fetch_vol_index(symbol: str, start: str, end: str) -> pd.Series:
    """
    Fetch the appropriate vol index for the underlying.
    Returns pd.Series of vol index close prices (as decimal, e.g. 0.20 for VIX 20).
    """
    vol_symbol = VOL_INDEX_MAP.get(symbol.upper(), "^VIX")
    try:
        df = yf.Ticker(vol_symbol).history(start=start, end=end, auto_adjust=False)
        if df.empty:
            return pd.Series(dtype=float)
        series = df["Close"] / 100.0  # VIX is quoted as percentage
        series.index = pd.to_datetime(series.index).tz_localize(None)
        series.name = vol_symbol
        return series
    except Exception as e:
        logger.warning(f"Could not fetch vol index {vol_symbol}: {e}")
        return pd.Series(dtype=float)


def fetch_dividend_yield(symbol: str) -> float:
    """
    Approximate dividend yield as decimal (e.g., 0.015 for 1.5%).

    yfinance has inconsistent fields:
      - dividendYield: returned as percentage (1.03 = 1.03%)
      - trailingAnnualDividendYield: decimal (0.0103)
      - yield: decimal
    We prefer trailingAnnualDividendYield then yield.
    """
    try:
        info = yf.Ticker(symbol).info
        # Try decimal fields first
        for key in ("trailingAnnualDividendYield", "yield"):
            v = info.get(key)
            if v is not None and v > 0:
                return float(v)
        # Fallback: dividendYield is in percent → divide by 100
        v = info.get("dividendYield")
        if v is not None and v > 0:
            return float(v) / 100.0
        return 0.0
    except Exception:
        return 0.0


def get_risk_free_rate(date: pd.Timestamp = None) -> float:
    """
    Approximate risk-free rate. For simplicity uses a piecewise constant.
    For more accuracy, could fetch ^IRX (13-week T-Bill).
    """
    if date is None:
        return 0.045
    # Rough historical approximation
    year = date.year
    if year < 2008: return 0.045
    if year < 2016: return 0.005  # ZIRP era
    if year < 2020: return 0.020
    if year < 2022: return 0.001  # COVID emergency rates
    return 0.045  # 2022+ hiking cycle


def prepare_backtest_data(
    symbol: str,
    start: str,
    end: str,
) -> dict:
    """
    One-shot fetch for backtest: prices + vol index + metadata.
    Returns dict with keys: prices, vol_index, div_yield, symbol.
    """
    # Extend start by 60 days for vol warmup
    extended_start = (pd.Timestamp(start) - pd.Timedelta(days=60)).strftime("%Y-%m-%d")

    prices = fetch_history(symbol, extended_start, end)
    vol_idx = fetch_vol_index(symbol, extended_start, end)
    div_yield = fetch_dividend_yield(symbol)

    return {
        "symbol": symbol,
        "prices": prices,
        "vol_index": vol_idx,
        "div_yield": div_yield,
        "start": start,
        "end": end,
    }
