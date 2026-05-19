"""
🎯 立即建議頁 / Recommendation Page
=================================
輸入標的，輸出：
  1. 基於歷史回測的建議參數
  2. 從 yfinance 即時抓的真實合約
  3. TWS 下單步驟
"""
import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
from typing import Optional, Dict, List

from core.data_loader import prepare_backtest_data
from core.backtest import CCStrategy, CCBacktest
from core.pricing import bs_call_delta


# ============================================================
# 即時資料 (yfinance)
# ============================================================

@st.cache_data(ttl=300, show_spinner=False)
def fetch_current_price(symbol: str) -> Optional[float]:
    """抓即時股價（yfinance，延遲 15-20 分）"""
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="5d")
        if not hist.empty:
            return float(hist["Close"].iloc[-1])
    except Exception:
        pass
    return None


@st.cache_data(ttl=600, show_spinner=False)
def fetch_expirations(symbol: str) -> List[str]:
    """抓所有到期日"""
    try:
        return list(yf.Ticker(symbol).options)
    except Exception:
        return []


@st.cache_data(ttl=300, show_spinner=False)
def fetch_call_chain(symbol: str, expiration: str) -> pd.DataFrame:
    """抓 call chain（含 yfinance 的 IV）"""
    try:
        chain = yf.Ticker(symbol).option_chain(expiration)
        calls = chain.calls.copy()
        if calls.empty:
            return pd.DataFrame()
        calls = calls.rename(columns={
            "strike": "strike", "bid": "bid", "ask": "ask",
            "lastPrice": "last", "volume": "volume",
            "openInterest": "open_interest", "impliedVolatility": "iv",
        })
        calls["mid"] = (calls["bid"] + calls["ask"]) / 2
        calls.loc[calls["mid"] <= 0, "mid"] = calls.loc[calls["mid"] <= 0, "last"]
        return calls[["strike", "bid", "ask", "mid", "last",
                      "volume", "open_interest", "iv"]]
    except Exception:
        return pd.DataFrame()


# ============================================================
# 回測「建議參數」
# ============================================================

@st.cache_data(ttl=3600, show_spinner=False)
def find_best_params(symbol: str, risk_preference: str,
                     backtest_years: int = 5,
                     include_short_dte: bool = True) -> Dict:
    """
    用過去 N 年資料找最佳 (delta, dte, close_rule) 組合。

    Args:
        backtest_years: 回測年數（預設 5 年）
        include_short_dte: 是否包含 7/14 天短天期策略（預設 True）
    """
    end = datetime.now().strftime('%Y-%m-%d')
    start = (datetime.now() - timedelta(days=365 * backtest_years)).strftime('%Y-%m-%d')
    data = prepare_backtest_data(symbol, start, end)

    if data["prices"].empty:
        return {}

    # 候選策略：含短天期
    if risk_preference == "保守":
        deltas = [0.15, 0.20]
        dtes = [14, 30, 45] if include_short_dte else [30, 45]
    elif risk_preference == "平衡":
        deltas = [0.20, 0.25]
        dtes = [7, 14, 30, 45] if include_short_dte else [30, 45]
    else:  # 積極
        deltas = [0.25, 0.30, 0.35]
        dtes = [7, 14, 21, 30, 45] if include_short_dte else [21, 30, 45]

    close_rules = ["expiry", "profit_50", "dte_21", "hybrid"]

    # 跑回測
    results = []
    for d in deltas:
        for dte in dtes:
            for cr in close_rules:
                s = CCStrategy(
                    name=f"Δ{d:.2f}_{dte}D_{cr}",
                    target_delta=d, target_dte=dte, close_rule=cr,
                )
                try:
                    r = CCBacktest(data, s).run()
                    if r.metrics and r.metrics.get("n_trades", 0) > 0:
                        results.append({
                            "delta": d, "dte": dte, "close_rule": cr,
                            "name": s.name,
                            "cagr": r.metrics["cagr"],
                            "bh_cagr": r.metrics["bh_cagr"],
                            "excess": r.metrics["excess_return"],
                            "sharpe": r.metrics["sharpe"],
                            "max_dd": r.metrics["max_drawdown"],
                            "win_rate": r.metrics["win_rate"],
                            "n_trades": r.metrics["n_trades"],
                            "n_assigned": r.metrics["n_assigned"],
                        })
                except Exception:
                    pass

    if not results:
        return {}

    # 排序：保守取勝率高、平衡取 Sharpe、積極取 CAGR
    if risk_preference == "保守":
        results.sort(key=lambda x: (x["win_rate"], -x["max_dd"], x["cagr"]), reverse=True)
    elif risk_preference == "平衡":
        results.sort(key=lambda x: x["sharpe"], reverse=True)
    else:
        results.sort(key=lambda x: x["cagr"], reverse=True)

    return {
        "best": results[0],
        "top3": results[:3],
        "spot_start": float(data["prices"].iloc[0]["close"]),
        "spot_today": float(data["prices"].iloc[-1]["close"]),
        "backtest_years": backtest_years,
        "n_strategies_tested": len(results),
    }


# ============================================================
# 從市場合約找匹配
# ============================================================

def find_matching_contracts(
    symbol: str,
    spot: float,
    target_delta: float,
    target_dte: int,
    delta_tolerance: float = 0.05,
    dte_tolerance: int = 7,
) -> pd.DataFrame:
    """
    找市場上符合 (delta, dte) 條件的真實合約。
    """
    expirations = fetch_expirations(symbol)
    if not expirations:
        return pd.DataFrame()

    today = datetime.now().date()
    candidate_exps = []
    for e in expirations:
        try:
            d = (datetime.strptime(e, "%Y-%m-%d").date() - today).days
            if abs(d - target_dte) <= dte_tolerance + 7:  # 寬鬆一點先抓
                candidate_exps.append((e, d))
        except ValueError:
            pass

    # 排序：越接近目標 DTE 越前面
    candidate_exps.sort(key=lambda x: abs(x[1] - target_dte))
    candidate_exps = candidate_exps[:3]

    if not candidate_exps:
        return pd.DataFrame()

    risk_free = 0.045
    all_rows = []
    for exp_str, dte in candidate_exps:
        chain = fetch_call_chain(symbol, exp_str)
        if chain.empty:
            continue

        # 只看 OTM
        chain = chain[chain["strike"] > spot]
        if chain.empty:
            continue

        # 計算 BS Delta（用 yfinance 的 IV）
        T = dte / 365.0
        chain = chain.copy()
        chain["delta"] = chain.apply(
            lambda r: bs_call_delta(spot, r["strike"], T, risk_free, r["iv"])
            if r["iv"] and r["iv"] > 0 else None,
            axis=1,
        )
        chain["dte"] = dte
        chain["expiration"] = exp_str
        chain["otm_pct"] = ((chain["strike"] - spot) / spot * 100).round(2)
        chain["delta_diff"] = (chain["delta"] - target_delta).abs()

        # 過濾接近目標 Delta 的合約
        chain = chain[chain["delta_diff"] <= delta_tolerance]
        if chain.empty:
            continue

        # 計算指標
        chain["premium_pct"] = (chain["mid"] / spot * 100).round(2)
        chain["annualized_return"] = (chain["premium_pct"] * 365 / dte).round(2)
        chain["expected_premium"] = (chain["mid"] * 100).round(2)
        chain["spread"] = (chain["ask"] - chain["bid"]).round(2)
        chain["spread_pct"] = ((chain["ask"] - chain["bid"]) / chain["mid"] * 100).round(1)

        all_rows.append(chain)

    if not all_rows:
        return pd.DataFrame()

    df = pd.concat(all_rows, ignore_index=True)

    # 流動性 + Delta 接近度綜合排序
    df["liquidity_score"] = (
        np.log1p(df["volume"].fillna(0)) +
        np.log1p(df["open_interest"].fillna(0)) * 0.5
    )
    df["total_score"] = (
        df["liquidity_score"] * 10
        - df["delta_diff"] * 100
        - df["spread_pct"].fillna(50)
    )
    df = df.sort_values("total_score", ascending=False)

    return df


# ============================================================
# 合約代碼產生（OCC 21 字元格式）
# ============================================================

def generate_occ_symbol(underlying: str, exp_str: str, strike: float, right: str = "C") -> str:
    """
    產生 OCC 標準合約代碼，例如：
    AAPL 2026-07-03 Call $315 → AAPL260703C00315000
    """
    try:
        exp = datetime.strptime(exp_str, "%Y-%m-%d")
        date_str = exp.strftime("%y%m%d")
        strike_int = int(strike * 1000)
        return f"{underlying}{date_str}{right}{strike_int:08d}"
    except Exception:
        return ""


# ============================================================
# 主頁面
# ============================================================

def render_recommendation_page():
    st.subheader("🎯 立即建議 / Get Recommendation")
    st.caption(
        "輸入標的，系統會：(1) 用歷史回測找最佳參數 (2) 抓即時合約給你具體標的 "
        "(3) 產生 TWS 下單步驟"
    )

    # ---------- 輸入區 ----------
    with st.container(border=True):
        c1, c2, c3 = st.columns([2, 2, 2])
        with c1:
            symbol = st.text_input(
                "標的代碼 Symbol",
                value="VOO",
                help="美股代號，例如 AAPL, MSFT, SPY, QQQ, VOO",
            ).strip().upper()

        with c2:
            risk_pref = st.selectbox(
                "風險偏好 Risk Preference",
                ["保守 Conservative", "平衡 Balanced", "積極 Aggressive"],
                index=1,
                help="保守=低 Delta 高勝率 / 平衡=Sharpe 最佳 / 積極=最大化 CAGR",
            )
            risk_key = risk_pref.split(" ")[0]

        with c3:
            shares = st.number_input(
                "持有股數 Shares",
                min_value=100, max_value=10000,
                value=100, step=100,
                help="必須是 100 的倍數（每 100 股 = 1 contract）",
            )

        # 🆕 新增：回測年數 + 短天期選項
        c4, c5 = st.columns(2)
        with c4:
            backtest_years_label = st.selectbox(
                "回測年數 Backtest Period",
                ["3 年（快速）", "5 年 ⭐ 推薦", "7 年（含 2018 熊市）",
                 "10 年（最完整，含 3 次熊市）"],
                index=1,
                help="越長越能反映完整市場循環，但耗時較久",
            )
            years_map = {"3": 3, "5": 5, "7": 7, "10": 10}
            backtest_years = years_map[backtest_years_label.split(" ")[0]]

        with c5:
            include_short_dte = st.checkbox(
                "包含短天期策略 (7/14 天) Include Weekly",
                value=True,
                help="勾選後也會測試週選和雙週選擇權（適合資金週轉快的策略）",
            )

        st.caption(
            "💡 yfinance 資料**盤中延遲 15-20 分鐘**。若是盤後或週末，會顯示前一個交易日收盤價。"
            + ("  \n⏱️ 回測 10 年 + 短天期約需 1-2 分鐘" if backtest_years >= 7 else "")
        )

    # ---------- 開始分析按鈕 ----------
    if st.button("🚀 開始分析 Analyze", type="primary", disabled=not symbol):
        if shares % 100 != 0:
            st.error("股數必須是 100 的倍數")
            st.stop()

        n_contracts = shares // 100

        # === Step 1: 抓即時股價 ===
        with st.spinner(f"📥 抓取 {symbol} 即時股價..."):
            spot = fetch_current_price(symbol)
            if not spot:
                st.error(f"找不到 {symbol} 的價格。請確認標的代碼正確。")
                st.stop()

        # === Step 2: 跑回測找最佳參數 ===
        bt_time_est = "1-2 分鐘" if backtest_years >= 7 else "30-60 秒"
        with st.spinner(f"🧪 跑 {symbol} 過去 {backtest_years} 年回測（約 {bt_time_est}）..."):
            backtest_result = find_best_params(
                symbol, risk_key,
                backtest_years=backtest_years,
                include_short_dte=include_short_dte,
            )
            if not backtest_result:
                st.error(f"無法回測 {symbol}。可能是新上市或資料不足。")
                st.stop()

        best = backtest_result["best"]

        # === Step 3: 找市場上的真實合約 ===
        with st.spinner(f"🛒 從市場抓符合條件的合約..."):
            contracts = find_matching_contracts(
                symbol, spot, best["delta"], best["dte"],
                delta_tolerance=0.05, dte_tolerance=7,
            )

        # 存進 session state
        st.session_state["rec_result"] = {
            "symbol": symbol, "spot": spot, "shares": shares,
            "n_contracts": n_contracts,
            "best": best, "top3": backtest_result["top3"],
            "contracts": contracts,
            "risk_key": risk_key,
            "spot_start": backtest_result["spot_start"],
            "spot_today": backtest_result["spot_today"],
            "backtest_years": backtest_result["backtest_years"],
            "n_strategies_tested": backtest_result["n_strategies_tested"],
            "analysis_time": datetime.now(),
        }

    # ---------- 顯示結果 ----------
    if "rec_result" not in st.session_state:
        st.info("👆 輸入標的後按「開始分析」")
        return

    r = st.session_state["rec_result"]

    st.divider()

    # ===========================================
    # 區塊 A: 當前狀態
    # ===========================================
    st.markdown("### 📊 當前狀態 / Current Status")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric(f"{r['symbol']} 現價", f"${r['spot']:.2f}")
    c2.metric(f"過去 {r['backtest_years']} 年漲幅",
              f"{(r['spot_today']/r['spot_start']-1)*100:+.1f}%")
    c3.metric("你的持股", f"{r['shares']} 股")
    c4.metric("可賣合約數", f"{r['n_contracts']} 張")

    st.caption(
        f"💼 你的部位價值：${r['spot'] * r['shares']:,.0f}  ·  "
        f"風險偏好：{r['risk_key']}  ·  "
        f"回測年數：{r['backtest_years']} 年  ·  "
        f"測試了 {r['n_strategies_tested']} 種策略組合  ·  "
        f"分析時間：{r['analysis_time'].strftime('%H:%M:%S')}"
    )

    # ===========================================
    # 區塊 B: 建議參數
    # ===========================================
    st.divider()
    st.markdown("### 🎯 建議參數 / Recommended Parameters")
    st.caption(f"基於 **過去 {r['backtest_years']} 年回測** 在你的風險偏好下表現最好的組合")

    best = r["best"]
    target_exp_date = datetime.now() + timedelta(days=best["dte"])
    # 找最近的週五
    days_to_fri = (4 - target_exp_date.weekday()) % 7
    if days_to_fri == 0 and target_exp_date <= datetime.now():
        days_to_fri = 7
    target_friday = target_exp_date + timedelta(days=days_to_fri)

    with st.container(border=True):
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("策略 Strategy", "CC")
        c2.metric("Delta 目標", f"{best['delta']:.2f}")
        c3.metric("DTE 到期天數", f"{best['dte']} 天")
        c4.metric("關閉規則", best["close_rule"])

        st.markdown(f"""
**📅 目標到期日：約 `{target_friday.strftime('%Y-%m-%d')}（週五）`**

**💰 預期表現（回測值）：**
- 年化報酬：**{best['cagr']:.1%}**（vs 持有不動 {best['bh_cagr']:.1%}）
- 超額報酬：**{best['excess']:+.1%}**
- 歷史勝率：**{best['win_rate']:.0%}**（{best['n_trades']} 筆中）
- {r['backtest_years']} 年內被指派：**{best['n_assigned']}** 次
- 夏普值：{best['sharpe']:.2f}
- 最大回撤：{best['max_dd']:.1%}
        """)

        with st.expander("📊 看 Top 3 候選策略"):
            top3_df = pd.DataFrame(r["top3"])
            top3_df["cagr"] = top3_df["cagr"].apply(lambda x: f"{x:.2%}")
            top3_df["excess"] = top3_df["excess"].apply(lambda x: f"{x:+.2%}")
            top3_df["win_rate"] = top3_df["win_rate"].apply(lambda x: f"{x:.0%}")
            top3_df["max_dd"] = top3_df["max_dd"].apply(lambda x: f"{x:.2%}")
            top3_df["sharpe"] = top3_df["sharpe"].apply(lambda x: f"{x:.2f}")
            display_cols = ["name", "cagr", "excess", "sharpe", "win_rate",
                           "max_dd", "n_trades", "n_assigned"]
            st.dataframe(top3_df[display_cols], hide_index=True,
                         use_container_width=True)

    # ===========================================
    # 區塊 C: 市場上的真實合約
    # ===========================================
    st.divider()
    st.markdown("### 🛒 市場合約推薦 / Real Contracts")
    st.caption("以下合約**真的存在於市場上**，可以直接在 TWS 下單")

    contracts = r["contracts"]
    if contracts.empty:
        st.warning(
            f"😢 找不到符合 Delta ≈ {best['delta']:.2f}、DTE ≈ {best['dte']} 天的合約。\n\n"
            "可能的原因：\n"
            "- 該標的選擇權流動性差\n"
            "- 現在是盤後/週末，資料不完整\n"
            "- 標的 IV 異常導致 Delta 計算失準\n\n"
            "建議：到 TWS Option Chain 手動找最接近的 strike。"
        )
    else:
        st.success(f"✅ 找到 {len(contracts)} 張符合條件的合約")

        for i, (idx, row) in enumerate(contracts.head(3).iterrows()):
            is_top = i == 0
            badge = "⭐ 最推薦" if is_top else f"備選 #{i}"
            with st.container(border=True):
                # 標題行
                col_a, col_b = st.columns([3, 1])
                with col_a:
                    st.markdown(f"### {badge}：{r['symbol']} {row['expiration']} ${row['strike']:.2f} Call")
                with col_b:
                    occ = generate_occ_symbol(r['symbol'], row['expiration'], row['strike'])
                    st.caption(f"`{occ}`")

                # 關鍵指標
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Strike", f"${row['strike']:.2f}",
                          delta=f"+{row['otm_pct']:.1f}% OTM")
                m2.metric("Delta",
                          f"{row['delta']:.3f}" if pd.notna(row['delta']) else "N/A")
                m3.metric("DTE", f"{row['dte']} 天")
                m4.metric("IV",
                          f"{row['iv']*100:.1f}%" if pd.notna(row['iv']) else "N/A")

                # 價格資訊
                p1, p2, p3, p4 = st.columns(4)
                p1.metric("Bid",
                          f"${row['bid']:.2f}" if pd.notna(row['bid']) else "N/A")
                p2.metric("Ask",
                          f"${row['ask']:.2f}" if pd.notna(row['ask']) else "N/A")
                p3.metric("Mid", f"${row['mid']:.2f}")
                p4.metric("Spread",
                          f"${row['spread']:.2f}",
                          delta=f"{row['spread_pct']:.1f}%" if pd.notna(row['spread_pct']) else None,
                          delta_color="inverse")

                # 預期收益
                e1, e2, e3 = st.columns(3)
                total_premium = row['expected_premium'] * r['n_contracts']
                e1.metric("單張 Premium", f"${row['expected_premium']:.0f}")
                e2.metric(f"{r['n_contracts']} 張總收入", f"${total_premium:.0f}")
                e3.metric("年化報酬", f"{row['annualized_return']:.1f}%")

                # 流動性
                l1, l2 = st.columns(2)
                l1.metric("Volume", f"{int(row['volume']):,}" if pd.notna(row['volume']) else "0")
                l2.metric("Open Interest", f"{int(row['open_interest']):,}" if pd.notna(row['open_interest']) else "0")

                # 流動性警示
                vol = row['volume'] if pd.notna(row['volume']) else 0
                oi = row['open_interest'] if pd.notna(row['open_interest']) else 0
                spread_pct = row['spread_pct'] if pd.notna(row['spread_pct']) else 100

                if vol < 10 or oi < 100 or spread_pct > 15:
                    st.warning(
                        "⚠️ **流動性偏弱**："
                        + ("成交量低 · " if vol < 10 else "")
                        + ("未平倉低 · " if oi < 100 else "")
                        + ("價差過大 · " if spread_pct > 15 else "")
                        + "實際成交可能比 Mid 差。"
                    )

                if is_top:
                    # TWS 下單步驟
                    with st.expander("📝 TWS 下單步驟", expanded=True):
                        limit_price = row['mid']
                        st.markdown(f"""
1. **打開 TWS** → 頂部搜尋欄輸入 **`{r['symbol']}`**
2. 右鍵 {r['symbol']} → **Option Chain**（或快捷鍵 `Ctrl+Alt+O`）
3. 選到期日 **{row['expiration']}**
4. 找 Call 那一邊，**Strike = ${row['strike']:.2f}** 的那一行
5. 右鍵點 **Bid 價格** → **Sell**
6. 在下單視窗確認：
   - **Action**: `SELL` ✅
   - **Quantity**: `{r['n_contracts']}`（{r['shares']} 股 ÷ 100）
   - **Order Type**: `LMT`（限價單）
   - **Limit Price**: 建議 **`${limit_price:.2f}`**（Mid 價）
   - **Time in Force**: `DAY`
7. **檢查三項**：
   - [ ] 是 **Sell** 不是 Buy
   - [ ] 是 **Call** 不是 Put
   - [ ] **Quantity 是 {r['n_contracts']}** 不是其他
8. 按 **Transmit** 送單

成交後：
- ✅ 帳戶會多 ${total_premium:.0f} 現金（premium）
- ⚠️ 義務：若 {row['expiration']} 時 {r['symbol']} > ${row['strike']:.2f}，你的 {r['shares']} 股會被以 ${row['strike']:.2f} 賣掉
- 🎯 根據 **{best['close_rule']}** 規則：**{'持有到期，中途什麼都不做' if best['close_rule'] == 'expiry' else '達到目標獲利或剩 21 天時平倉'}**
                        """)
                st.markdown("")  # spacing

    # ===========================================
    # 區塊 D: 風險警告
    # ===========================================
    st.divider()
    st.warning("""
⚠️ **重要提醒：**

1. **以上建議基於歷史回測**，不保證未來表現
2. **yfinance 資料延遲 15-20 分鐘**，下單前請在 TWS 確認最新報價
3. **盤後/週末資料可能不準確**（bid/ask = 0 是正常的）
4. **第一次下單請用 Paper Account**（模擬帳號）測試
5. 建議**避開財報前一週**（IV 暴漲後暴跌，賣方常被坑）
6. 本工具**僅供參考**，不構成投資建議
    """)
