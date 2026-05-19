"""
Cloud Screener Page - uses yfinance for option chain data (no IBKR needed).

yfinance's option chain support is limited (no Greeks, sometimes stale data),
so we compute our own Greeks via Black-Scholes from the IV that yfinance provides.
"""
import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
from typing import List, Dict

from core.pricing import bs_call_delta, realized_volatility
from core.screener import ScreenerConfig, filter_candidates, score_candidate
from config.settings import DEFAULT_CONFIG, DEFAULT_WATCHLIST


@st.cache_data(ttl=300, show_spinner=False)
def fetch_stock_price(symbol: str) -> float:
    """Get latest stock price via yfinance. Cached 5 minutes."""
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="5d")
        if not hist.empty:
            return float(hist["Close"].iloc[-1])
    except Exception:
        pass
    return None


@st.cache_data(ttl=600, show_spinner=False)
def fetch_option_expirations(symbol: str) -> List[str]:
    """Get available expiration dates. Cached 10 minutes."""
    try:
        ticker = yf.Ticker(symbol)
        return list(ticker.options)
    except Exception:
        return []


@st.cache_data(ttl=300, show_spinner=False)
def fetch_call_chain(symbol: str, expiration: str) -> pd.DataFrame:
    """
    Get call option chain from yfinance.
    Returns DataFrame with: strike, bid, ask, last, volume, openInterest, impliedVolatility
    """
    try:
        ticker = yf.Ticker(symbol)
        chain = ticker.option_chain(expiration)
        calls = chain.calls.copy()
        if calls.empty:
            return pd.DataFrame()
        # Standardize column names
        calls = calls.rename(columns={
            "strike": "strike",
            "bid": "bid",
            "ask": "ask",
            "lastPrice": "last",
            "volume": "volume",
            "openInterest": "open_interest",
            "impliedVolatility": "iv",
        })
        # Compute mid
        calls["mid"] = (calls["bid"] + calls["ask"]) / 2
        # Replace mid=0 with last if bid/ask both zero (illiquid)
        calls.loc[calls["mid"] <= 0, "mid"] = calls.loc[calls["mid"] <= 0, "last"]
        return calls[["strike", "bid", "ask", "mid", "last",
                      "volume", "open_interest", "iv"]]
    except Exception as e:
        st.warning(f"Failed to fetch chain for {symbol} {expiration}: {e}")
        return pd.DataFrame()


def calculate_metrics_row(row, spot, dte):
    """Compute return / yield metrics for one option row."""
    mid = row.get("mid")
    strike = row["strike"]
    if not mid or mid <= 0 or spot <= 0 or dte <= 0:
        return {}
    premium_pct = (mid / spot) * 100
    static_annualized = premium_pct * (365 / dte)
    if_called = ((mid + max(0, strike - spot)) / spot) * 100
    if_called_annualized = if_called * (365 / dte)
    bid, ask = row.get("bid"), row.get("ask")
    spread_pct = ((ask - bid) / mid) * 100 if (bid and ask and mid > 0) else None
    return {
        "premium_pct": round(premium_pct, 2),
        "annualized_return": round(static_annualized, 2),
        "if_called_return": round(if_called, 2),
        "if_called_annualized": round(if_called_annualized, 2),
        "spread_pct": round(spread_pct, 2) if spread_pct else None,
    }


def screen_one_symbol(symbol: str, cfg: ScreenerConfig, max_expirations: int = 3) -> pd.DataFrame:
    """Run screen for a single symbol."""
    spot = fetch_stock_price(symbol)
    if not spot:
        return pd.DataFrame()

    expirations = fetch_option_expirations(symbol)
    if not expirations:
        return pd.DataFrame()

    # Filter expirations within DTE window
    today = datetime.now().date()
    valid_exps = []
    for e in expirations:
        try:
            d = (datetime.strptime(e, "%Y-%m-%d").date() - today).days
            if cfg.min_dte <= d <= cfg.max_dte:
                valid_exps.append((e, d))
        except ValueError:
            pass
    valid_exps = valid_exps[:max_expirations]

    if not valid_exps:
        return pd.DataFrame()

    all_rows = []
    risk_free = 0.045  # current approximation

    for exp_str, dte in valid_exps:
        chain = fetch_call_chain(symbol, exp_str)
        if chain.empty:
            continue

        # Filter strikes: OTM only
        chain = chain[chain["strike"] > spot * (1 + cfg.min_otm_pct / 100)]
        if chain.empty:
            continue

        chain = chain.copy()
        chain["symbol"] = symbol
        chain["expiration"] = exp_str
        chain["spot"] = spot
        chain["dte"] = dte
        chain["otm_pct"] = ((chain["strike"] - spot) / spot * 100).round(2)

        # Compute Black-Scholes delta from yfinance IV
        T = dte / 365.0
        chain["delta"] = chain.apply(
            lambda r: bs_call_delta(spot, r["strike"], T, risk_free, r["iv"])
            if r["iv"] and r["iv"] > 0 else None,
            axis=1,
        )

        # Compute metrics
        metrics = chain.apply(
            lambda r: calculate_metrics_row(r, spot, dte), axis=1
        )
        metrics_df = pd.DataFrame(list(metrics))
        chain = pd.concat(
            [chain.reset_index(drop=True), metrics_df.reset_index(drop=True)],
            axis=1,
        )
        all_rows.append(chain)

    if not all_rows:
        return pd.DataFrame()

    df = pd.concat(all_rows, ignore_index=True)
    # No IV rank without history (would need extra fetching) — use neutral 50
    df["iv_rank"] = 50.0

    # Apply filters
    filtered = filter_candidates(df, cfg)

    if not filtered.empty:
        filtered["score"] = filtered.apply(lambda r: score_candidate(r, cfg), axis=1)
        filtered = filtered.sort_values("score", ascending=False)

    return filtered


def render_screener_page():
    st.subheader("🔍 CC 機會篩選器 / Screener")
    st.caption(
        "使用免費的 yfinance 選擇權資料找適合賣 CC 的機會。"
        "Greeks 由 Black-Scholes 從 yfinance IV 反算。"
    )

    # ---------- Config ----------
    with st.expander("⚙️ 篩選參數 / Screening Parameters", expanded=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown("**Delta 範圍 / Delta Range**")
            min_delta = st.slider("最小 Delta", 0.05, 0.50, DEFAULT_CONFIG["min_delta"], 0.05, key="scr_mind")
            max_delta = st.slider("最大 Delta", 0.10, 0.60, DEFAULT_CONFIG["max_delta"], 0.05, key="scr_maxd")
            st.markdown("**DTE 範圍**")
            min_dte = st.number_input("最小 DTE", 1, 180, DEFAULT_CONFIG["min_dte"], key="scr_mindte")
            max_dte = st.number_input("最大 DTE", 5, 365, DEFAULT_CONFIG["max_dte"], key="scr_maxdte")
        with c2:
            st.markdown("**報酬要求 / Return Requirements**")
            min_premium_pct = st.number_input(
                "最低 Premium %（佔股價）", 0.0, 20.0,
                DEFAULT_CONFIG["min_premium_pct"], 0.1, key="scr_minprem")
            min_annualized = st.number_input(
                "最低年化報酬 %", 0.0, 200.0,
                DEFAULT_CONFIG["min_annualized_return"], 1.0, key="scr_minann")
            min_otm = st.number_input(
                "最低 OTM %", 0.0, 30.0,
                DEFAULT_CONFIG["min_otm_pct"], 0.5, key="scr_minotm",
                help="strike 至少要比現價高多少 %")
        with c3:
            st.markdown("**流動性 / Liquidity**")
            min_volume = st.number_input("最低成交量 Volume", 0, 10000,
                                          DEFAULT_CONFIG["min_volume"], key="scr_minvol")
            min_oi = st.number_input("最低未平倉 OI", 0, 50000,
                                      DEFAULT_CONFIG["min_open_interest"], key="scr_minoi")
            max_spread = st.number_input(
                "最大買賣價差 %", 0.0, 50.0,
                DEFAULT_CONFIG["max_bid_ask_spread_pct"], 1.0, key="scr_maxspread")

    # ---------- Symbols ----------
    st.markdown("**要掃描的標的 / Symbols to Scan**")
    symbols_input = st.text_input(
        "Tickers（逗號分隔）",
        value=",".join(DEFAULT_WATCHLIST[:8]),
        help="可以是個股或 ETF，例如 AAPL, MSFT, SPY",
    )
    symbols = [s.strip().upper() for s in symbols_input.split(",") if s.strip()]

    st.caption(
        "💡 yfinance 資料**免費**但：(1) 盤中可能延遲 15-20 分鐘，"
        "(2) 不含 Greeks（我們用 Black-Scholes 計算），"
        "(3) 流動性差的 strike 可能 bid/ask = 0。"
    )

    # ---------- Run ----------
    if st.button("🚀 開始篩選 Run Screen", type="primary", disabled=not symbols):
        cfg = ScreenerConfig(
            min_delta=min_delta, max_delta=max_delta,
            min_premium_pct=min_premium_pct,
            min_annualized_return=min_annualized,
            min_iv_rank=0,  # disabled in cloud version
            min_dte=min_dte, max_dte=max_dte,
            min_volume=min_volume,
            min_open_interest=min_oi,
            max_bid_ask_spread_pct=max_spread,
            min_otm_pct=min_otm,
        )

        all_results = []
        progress = st.progress(0, "Starting...")
        for i, sym in enumerate(symbols):
            progress.progress((i + 1) / len(symbols), f"Scanning {sym}...")
            try:
                result = screen_one_symbol(sym, cfg)
                if not result.empty:
                    all_results.append(result)
            except Exception as e:
                st.warning(f"{sym}: {e}")
        progress.empty()

        if all_results:
            final = pd.concat(all_results, ignore_index=True)
            final = final.sort_values("score", ascending=False)
            st.session_state["screen_results"] = final
            st.session_state["screen_time"] = datetime.now()
            st.success(f"✅ 找到 {len(final)} 個候選 / Found {len(final)} candidates")
        else:
            st.warning("無符合條件的候選。試著放寬篩選條件。")
            st.session_state["screen_results"] = pd.DataFrame()

    # ---------- Display ----------
    if st.session_state.get("screen_results") is not None and not st.session_state["screen_results"].empty:
        results = st.session_state["screen_results"]
        st.caption(f"上次掃描時間 / Last scan: {st.session_state['screen_time'].strftime('%H:%M:%S')}")

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("候選總數", len(results))
        c2.metric("平均年化 %", f"{results['annualized_return'].mean():.1f}")
        c3.metric("最高分數", f"{results['score'].max():.1f}")
        c4.metric("獨特標的數", results["symbol"].nunique())

        display_cols = [
            "symbol", "expiration", "dte", "strike", "spot",
            "otm_pct", "mid", "delta", "iv",
            "premium_pct", "annualized_return", "if_called_annualized",
            "volume", "open_interest", "spread_pct", "score",
        ]
        display_cols = [c for c in display_cols if c in results.columns]

        st.dataframe(
            results[display_cols],
            use_container_width=True,
            hide_index=True,
            column_config={
                "score": st.column_config.ProgressColumn(
                    "Score", min_value=0, max_value=100, format="%.1f"),
                "delta": st.column_config.NumberColumn("Δ", format="%.3f"),
                "iv": st.column_config.NumberColumn("IV", format="%.3f"),
                "annualized_return": st.column_config.NumberColumn("Ann %", format="%.2f"),
                "premium_pct": st.column_config.NumberColumn("Prem %", format="%.2f"),
                "spot": st.column_config.NumberColumn("Spot", format="$%.2f"),
                "strike": st.column_config.NumberColumn("Strike", format="$%.2f"),
                "mid": st.column_config.NumberColumn("Mid", format="$%.2f"),
            },
        )

        csv = results.to_csv(index=False).encode("utf-8")
        st.download_button("📥 下載 CSV / Download", csv, "cc_screen.csv", "text/csv")
