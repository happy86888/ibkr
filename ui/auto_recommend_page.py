"""
🤖 智慧自動推薦頁 / Auto-Recommend Page
=========================================
不需要輸入標的！系統會自動掃描熱門清單，
找出「IV 高、價格沒大漲、流動性好、回測證明能賺」的標的。

新增功能：
  - IV Rank 歷史圖（按鈕觸發）
  - 多策略比較（CC / CSP / Wheel / PMCC）
"""
import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

from core.data_loader import prepare_backtest_data
from core.backtest import CCStrategy, CCBacktest
from core.backtest_csp_wheel import CSPStrategy, CSPBacktest, WheelStrategy, WheelBacktest
from core.backtest_pmcc import PMCCStrategy, PMCCBacktest
from core.pricing import realized_volatility
from config.watchlist import (
    DEFAULT_WATCHLIST, MEGA_CAP_TECH, LARGE_CAP, ETFS, WATCHLIST_CATEGORIES
)


# ============================================================
# 評分計算
# ============================================================

@st.cache_data(ttl=900, show_spinner=False)  # 15 分鐘 cache
def fetch_symbol_metrics(symbol: str) -> Optional[Dict]:
    """
    計算單一標的的多項指標：
      - 現價、近期漲跌
      - IV（用近 30 日 realized vol 估計）
      - IV Rank（過去 1 年的相對位置）
      - 平均日成交量（流動性）
      - 近期動能（30 天、90 天漲跌）
    """
    try:
        ticker = yf.Ticker(symbol)
        # 抓 1 年資料用於 IV Rank 計算
        hist = ticker.history(period="1y")
        if len(hist) < 60:  # 至少要 60 天資料
            return None

        # 現價
        spot = float(hist["Close"].iloc[-1])
        if spot <= 0:
            return None

        # 滾動 RV 序列（30 天）
        log_ret = np.log(hist["Close"] / hist["Close"].shift(1))
        rv_series = log_ret.rolling(30).std() * np.sqrt(252)
        rv_series = rv_series.dropna()

        if rv_series.empty:
            return None

        # 當前 IV 估計（RV × 1.20 的 IV premium）
        current_rv = float(rv_series.iloc[-1])
        current_iv = current_rv * 1.20

        # IV Rank：當前 IV 在過去 1 年的相對位置
        iv_history = rv_series * 1.20
        iv_min = iv_history.min()
        iv_max = iv_history.max()
        if iv_max > iv_min:
            iv_rank = (current_iv - iv_min) / (iv_max - iv_min) * 100
        else:
            iv_rank = 50.0

        # 近期動能
        if len(hist) >= 30:
            price_30d_ago = float(hist["Close"].iloc[-30])
            momentum_30d = (spot / price_30d_ago - 1) * 100
        else:
            momentum_30d = 0

        if len(hist) >= 90:
            price_90d_ago = float(hist["Close"].iloc[-90])
            momentum_90d = (spot / price_90d_ago - 1) * 100
        else:
            momentum_90d = momentum_30d

        # 流動性：平均日成交量 × 股價（dollar volume）
        avg_volume = float(hist["Volume"].tail(20).mean())
        dollar_volume = avg_volume * spot

        return {
            "symbol": symbol,
            "spot": spot,
            "iv": current_iv,
            "iv_rank": float(iv_rank),
            "momentum_30d": float(momentum_30d),
            "momentum_90d": float(momentum_90d),
            "avg_volume": avg_volume,
            "dollar_volume": dollar_volume,
        }
    except Exception:
        return None


@st.cache_data(ttl=3600, show_spinner=False)
def quick_backtest_score(symbol: str) -> Optional[Dict]:
    """快速回測單一策略（Delta 0.25 / 45 DTE / expiry），給推薦評分用。

    使用 5 年資料以涵蓋多種市場環境（含 2022 熊市）。"""
    try:
        end = datetime.now().strftime('%Y-%m-%d')
        start = (datetime.now() - timedelta(days=365 * 5)).strftime('%Y-%m-%d')
        data = prepare_backtest_data(symbol, start, end)

        if data["prices"].empty or len(data["prices"]) < 100:
            return None

        # 跑一個代表性策略
        strat = CCStrategy(name="standard",
                           target_delta=0.25, target_dte=45,
                           close_rule="expiry")
        result = CCBacktest(data, strat).run()

        if not result.metrics or result.metrics["n_trades"] < 3:
            return None

        return {
            "symbol": symbol,
            "cagr": result.metrics["cagr"],
            "bh_cagr": result.metrics["bh_cagr"],
            "excess": result.metrics["excess_return"],
            "win_rate": result.metrics["win_rate"],
            "n_trades": result.metrics["n_trades"],
            "max_dd": result.metrics["max_drawdown"],
        }
    except Exception:
        return None


# ============================================================
# IV Rank 歷史資料
# ============================================================

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_iv_history(symbol: str) -> Optional[pd.DataFrame]:
    """
    抓 1 年 IV 歷史用於繪圖。
    IV 估計 = 30 日 realized vol × 1.20
    """
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="1y")
        if len(hist) < 60:
            return None

        # 計算滾動 RV
        log_ret = np.log(hist["Close"] / hist["Close"].shift(1))
        rv_series = (log_ret.rolling(30).std() * np.sqrt(252)).dropna()

        if rv_series.empty:
            return None

        # 估計 IV
        iv_series = rv_series * 1.20

        # 計算 IV Rank 序列
        iv_min = iv_series.min()
        iv_max = iv_series.max()
        if iv_max > iv_min:
            iv_rank_series = (iv_series - iv_min) / (iv_max - iv_min) * 100
        else:
            iv_rank_series = pd.Series([50] * len(iv_series), index=iv_series.index)

        df = pd.DataFrame({
            "date": iv_series.index,
            "iv": iv_series.values * 100,  # 轉成百分比
            "iv_rank": iv_rank_series.values,
            "price": hist.loc[iv_series.index, "Close"].values,
        })
        df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
        df = df.set_index("date")

        return df
    except Exception:
        return None


# ============================================================
# 多策略比較
# ============================================================

@st.cache_data(ttl=3600, show_spinner=False)
def compare_all_strategies(symbol: str) -> Optional[Dict]:
    """對單一標的跑 CC / CSP / Wheel / PMCC 4 種策略比較（5 年資料）"""
    try:
        end = datetime.now().strftime('%Y-%m-%d')
        start = (datetime.now() - timedelta(days=365 * 5)).strftime('%Y-%m-%d')
        data = prepare_backtest_data(symbol, start, end)

        if data["prices"].empty or len(data["prices"]) < 100:
            return None

        results = {}

        # CC
        try:
            cc_strat = CCStrategy(name="CC", target_delta=0.25,
                                  target_dte=45, close_rule="expiry")
            r = CCBacktest(data, cc_strat).run()
            if r.metrics and r.metrics.get("n_trades", 0) > 0:
                results["CC"] = r.metrics
        except Exception:
            pass

        # CSP
        try:
            csp_strat = CSPStrategy(name="CSP", target_delta=0.20,
                                    target_dte=30, close_rule="hybrid")
            r = CSPBacktest(data, csp_strat).run()
            if r.metrics and r.metrics.get("n_trades", 0) > 0:
                results["CSP"] = r.metrics
        except Exception:
            pass

        # Wheel
        try:
            wheel_strat = WheelStrategy(name="Wheel", put_delta=0.20,
                                         call_delta=0.25,
                                         put_dte=30, call_dte=30,
                                         close_rule="hybrid")
            r = WheelBacktest(data, wheel_strat).run()
            if r.metrics and r.metrics.get("n_trades", 0) > 0:
                results["Wheel"] = r.metrics
        except Exception:
            pass

        # PMCC
        try:
            pmcc_strat = PMCCStrategy(name="PMCC", leaps_delta=0.80,
                                       short_delta=0.25,
                                       leaps_dte=365, short_dte=30,
                                       short_close_rule="hybrid")
            r = PMCCBacktest(data, pmcc_strat).run()
            if r.metrics and r.metrics.get("n_trades", 0) > 0:
                results["PMCC"] = r.metrics
        except Exception:
            pass

        if not results:
            return None
        return results
    except Exception:
        return None


def compute_recommendation_score(metrics: Dict, backtest: Optional[Dict]) -> Dict:
    """
    綜合評分（0-100），權重：
      - IV Rank: 25%（高 IV = 多 premium）
      - 近期沒大漲: 25%（避免追高）
      - 流動性: 20%（避免滑價）
      - 回測 CAGR: 30%（驗證能賺）
    """
    scores = {}

    # 1. IV Rank 分數（越高越好）
    iv_rank = metrics.get("iv_rank", 50)
    iv_score = min(100, iv_rank * 1.0)
    scores["iv_score"] = iv_score

    # 2. 「沒大漲」分數
    # 30 天漲幅 < 5% 加分，> 10% 扣分
    mom_30 = metrics.get("momentum_30d", 0)
    if mom_30 < 0:
        mom_score = 70  # 跌了反而還好
    elif mom_30 < 3:
        mom_score = 100  # 完美
    elif mom_30 < 7:
        mom_score = 80
    elif mom_30 < 12:
        mom_score = 50
    else:
        mom_score = 20  # 漲太多
    scores["momentum_score"] = mom_score

    # 3. 流動性分數（dollar volume）
    dv = metrics.get("dollar_volume", 0)
    if dv > 5_000_000_000:  # > 50 億美元/日
        liq_score = 100
    elif dv > 1_000_000_000:  # > 10 億美元/日
        liq_score = 80
    elif dv > 100_000_000:  # > 1 億美元/日
        liq_score = 60
    else:
        liq_score = 30
    scores["liquidity_score"] = liq_score

    # 4. 回測 CAGR 分數
    if backtest:
        cagr = backtest.get("cagr", 0)
        if cagr > 0.25:
            cagr_score = 100
        elif cagr > 0.15:
            cagr_score = 80
        elif cagr > 0.10:
            cagr_score = 60
        elif cagr > 0:
            cagr_score = 40
        else:
            cagr_score = 0
    else:
        cagr_score = 50  # 沒回測資料給中性分

    scores["cagr_score"] = cagr_score

    # 加權總分
    total = (
        iv_score * 0.25 +
        mom_score * 0.25 +
        liq_score * 0.20 +
        cagr_score * 0.30
    )
    scores["total_score"] = round(total, 1)

    return scores


# ============================================================
# 並行抓取（加速）
# ============================================================

def scan_symbols(symbols: List[str], progress_callback=None) -> pd.DataFrame:
    """並行掃描所有標的，回傳評分後的 DataFrame。"""
    rows = []
    total = len(symbols)
    completed = 0

    # 並行抓 yfinance 指標
    with ThreadPoolExecutor(max_workers=5) as pool:
        future_to_sym = {
            pool.submit(fetch_symbol_metrics, sym): sym for sym in symbols
        }

        for future in as_completed(future_to_sym):
            sym = future_to_sym[future]
            completed += 1
            if progress_callback:
                progress_callback(completed, total * 2, f"指標 {sym}")
            try:
                metrics = future.result()
                if metrics:
                    rows.append(metrics)
            except Exception:
                pass

    # 對候選做回測（只對指標通過的標的回測）
    metrics_df = pd.DataFrame(rows)
    if metrics_df.empty:
        return pd.DataFrame()

    # 先依基本指標過濾（避免回測太多浪費時間）
    candidates = metrics_df[
        (metrics_df["dollar_volume"] > 100_000_000)  # 至少 1 億美元/日
        & (metrics_df["momentum_30d"] < 20)  # 30 天沒漲超過 20%
    ]["symbol"].tolist()

    backtest_results = {}
    with ThreadPoolExecutor(max_workers=3) as pool:
        future_to_sym = {
            pool.submit(quick_backtest_score, sym): sym for sym in candidates
        }
        for future in as_completed(future_to_sym):
            sym = future_to_sym[future]
            completed += 1
            if progress_callback:
                progress_callback(completed, total * 2, f"回測 {sym}")
            try:
                bt = future.result()
                if bt:
                    backtest_results[sym] = bt
            except Exception:
                pass

    # 合併評分
    final_rows = []
    for _, m in metrics_df.iterrows():
        sym = m["symbol"]
        bt = backtest_results.get(sym)
        scores = compute_recommendation_score(m.to_dict(), bt)
        row = {
            **m.to_dict(),
            **(bt or {}),
            **scores,
        }
        final_rows.append(row)

    df = pd.DataFrame(final_rows)
    if not df.empty:
        df = df.sort_values("total_score", ascending=False)
    return df


# ============================================================
# 主頁面
# ============================================================

def render_auto_recommend_page():
    st.subheader("🤖 智慧推薦 / Smart Recommendation")
    st.caption(
        "自動掃描熱門標的，找出 **IV 高、價格沒大漲、流動性好、回測能賺** 的標的。"
        "不用自己想要選哪檔！"
    )

    # ---------- 選擇掃描範圍 ----------
    with st.container(border=True):
        c1, c2 = st.columns([2, 1])
        with c1:
            category = st.selectbox(
                "掃描範圍 / Scan Universe",
                list(WATCHLIST_CATEGORIES.keys()),
                index=3,  # 預設「全部」
                help="從預選的熱門標的中掃描",
            )
        with c2:
            top_n = st.number_input(
                "顯示前幾名",
                min_value=5, max_value=50,
                value=20, step=5,
            )

        symbols_to_scan = WATCHLIST_CATEGORIES[category]

        # 額外加入自訂
        with st.expander("➕ 加入自訂標的"):
            extra = st.text_input(
                "額外標的（逗號分隔，會加到預選清單）",
                value="",
                placeholder="例如：COIN, PLTR, SOFI",
            )
            if extra:
                extra_list = [s.strip().upper() for s in extra.split(",") if s.strip()]
                symbols_to_scan = list(set(symbols_to_scan + extra_list))

        st.info(
            f"📊 將掃描 **{len(symbols_to_scan)} 個標的**，"
            f"顯示前 **{top_n} 名**。\n\n"
            "預計時間：約 **30 秒 - 2 分鐘**（取決於資料量和快取狀態）"
        )

    # ---------- 開始掃描 ----------
    if st.button("🚀 開始智慧推薦 Smart Scan", type="primary"):
        progress = st.progress(0, "準備中...")
        status = st.empty()

        def update_progress(done, total, msg):
            progress.progress(min(done / total, 1.0), msg)
            status.text(f"⏳ {msg} ({done}/{total})")

        df = scan_symbols(symbols_to_scan, progress_callback=update_progress)
        progress.empty()
        status.empty()

        if df.empty:
            st.error("沒有抓到任何資料，請稍後再試")
            st.stop()

        st.session_state["smart_rec_df"] = df
        st.session_state["smart_rec_time"] = datetime.now()
        st.success(f"✅ 完成！共分析 {len(df)} 個標的")

    # ---------- 顯示結果 ----------
    if "smart_rec_df" not in st.session_state:
        st.info("👆 按「開始智慧推薦」掃描熱門標的")
        return

    df = st.session_state["smart_rec_df"]
    scan_time = st.session_state["smart_rec_time"]

    st.divider()
    st.markdown(f"### 🏆 推薦排行榜 / Top Recommendations")
    st.caption(f"掃描時間：{scan_time.strftime('%Y-%m-%d %H:%M:%S')}")

    # ---------- 顯示前 N 名 ----------
    top_df = df.head(top_n).copy()

    # 美化欄位
    display_df = pd.DataFrame({
        "排名": range(1, len(top_df) + 1),
        "標的": top_df["symbol"],
        "現價": top_df["spot"].apply(lambda x: f"${x:.2f}"),
        "30天漲跌": top_df["momentum_30d"].apply(lambda x: f"{x:+.1f}%"),
        "IV": top_df["iv"].apply(lambda x: f"{x*100:.1f}%"),
        "IV Rank": top_df["iv_rank"].apply(lambda x: f"{x:.0f}"),
        "成交量": top_df["dollar_volume"].apply(
            lambda x: f"${x/1e9:.1f}B" if x > 1e9 else f"${x/1e6:.0f}M"
        ),
        "回測 CAGR": top_df.get("cagr", pd.Series([None]*len(top_df))).apply(
            lambda x: f"{x:.1%}" if pd.notna(x) else "N/A"
        ),
        "vs BH": top_df.get("excess", pd.Series([None]*len(top_df))).apply(
            lambda x: f"{x:+.1%}" if pd.notna(x) else "N/A"
        ),
        "總分": top_df["total_score"].apply(lambda x: f"{x:.1f}"),
    })

    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "排名": st.column_config.NumberColumn(width="small"),
            "標的": st.column_config.TextColumn(width="small"),
            "總分": st.column_config.TextColumn(
                help="綜合評分（0-100）",
                width="small",
            ),
        },
    )

    # 🆕 快速查單一標的 IV / 策略
    st.markdown("---")
    st.markdown("##### 🔍 查單一標的詳情")
    lookup_c1, lookup_c2, lookup_c3 = st.columns([2, 1, 1])
    with lookup_c1:
        lookup_sym = st.selectbox(
            "從排行榜選一檔標的",
            options=top_df["symbol"].tolist(),
            key="lookup_sym",
        )
    with lookup_c2:
        lookup_iv = st.button("📊 IV 歷史圖", key="lookup_iv_btn",
                                use_container_width=True)
    with lookup_c3:
        lookup_strat = st.button("🔄 策略比較", key="lookup_strat_btn",
                                  use_container_width=True)

    if lookup_iv and lookup_sym:
        st.session_state["manual_iv_sym"] = lookup_sym
    if lookup_strat and lookup_sym:
        st.session_state["manual_strat_sym"] = lookup_sym

    # 顯示手動查詢的 IV 圖
    if st.session_state.get("manual_iv_sym"):
        sym = st.session_state["manual_iv_sym"]
        with st.expander(f"📊 {sym} IV Rank 歷史走勢", expanded=True):
            with st.spinner(f"抓取 {sym} 的 IV 歷史資料..."):
                iv_df = fetch_iv_history(sym)

            if iv_df is None or iv_df.empty:
                st.warning("無法抓取 IV 歷史資料")
            else:
                current_iv = iv_df["iv"].iloc[-1]
                current_iv_rank = iv_df["iv_rank"].iloc[-1]
                iv_52w_high = iv_df["iv"].max()
                iv_52w_low = iv_df["iv"].min()
                avg_iv = iv_df["iv"].mean()

                mc1, mc2, mc3, mc4 = st.columns(4)
                mc1.metric("當前 IV", f"{current_iv:.1f}%")
                mc2.metric("當前 IV Rank", f"{current_iv_rank:.0f}",
                            delta="高位（賣方有利）" if current_iv_rank > 60
                                  else "低位（不建議賣）" if current_iv_rank < 30
                                  else "中位",
                            delta_color="normal" if current_iv_rank > 60
                                        else "inverse" if current_iv_rank < 30
                                        else "off")
                mc3.metric("52 週高/低",
                           f"{iv_52w_high:.1f}% / {iv_52w_low:.1f}%")
                mc4.metric("過去 1 年平均", f"{avg_iv:.1f}%")

                st.markdown("##### IV 走勢")
                chart_iv = iv_df[["iv"]].copy()
                chart_iv.columns = [f"{sym} IV (%)"]
                st.line_chart(chart_iv, height=250)

                st.markdown("##### IV Rank 走勢")
                chart_rank = iv_df[["iv_rank"]].copy()
                chart_rank.columns = [f"{sym} IV Rank"]
                chart_rank["建議賣方門檻 (60)"] = 60
                chart_rank["低 IV 警告 (30)"] = 30
                st.line_chart(chart_rank, height=250)

                st.markdown("##### 股價走勢（對照）")
                chart_price = iv_df[["price"]].copy()
                chart_price.columns = [f"{sym} 股價 ($)"]
                st.line_chart(chart_price, height=250)

                if current_iv_rank > 70:
                    st.success(f"🟢 **適合賣 CC / CSP**：IV Rank {current_iv_rank:.0f}（高位）")
                elif current_iv_rank > 50:
                    st.info(f"🟡 **可考慮**：IV Rank {current_iv_rank:.0f}（中高位）")
                elif current_iv_rank > 30:
                    st.info(f"⚪ **觀望**：IV Rank {current_iv_rank:.0f}（中位）")
                else:
                    st.warning(f"🔴 **不建議賣方**：IV Rank {current_iv_rank:.0f}（低位）")

                if st.button("❌ 關閉", key="manual_iv_close"):
                    st.session_state.pop("manual_iv_sym", None)
                    st.rerun()

    # 顯示手動查詢的策略比較
    if st.session_state.get("manual_strat_sym"):
        sym = st.session_state["manual_strat_sym"]
        with st.expander(f"🔄 {sym} 4 種策略比較", expanded=True):
            with st.spinner(f"跑 {sym} 的 CC / CSP / Wheel / PMCC 回測（約 30-60 秒）..."):
                strat_results = compare_all_strategies(sym)

            if not strat_results:
                st.warning("無法跑回測（資料不足或計算錯誤）")
            else:
                strat_list = sorted(
                    strat_results.items(),
                    key=lambda x: x[1].get("cagr", -999),
                    reverse=True,
                )

                st.markdown("##### 各策略表現對比（過去 5 年）")
                comp_df = pd.DataFrame([{
                    "策略": name,
                    "CAGR": f"{m['cagr']:.2%}",
                    "vs BH": f"{m['excess_return']:+.2%}",
                    "Sharpe": f"{m['sharpe']:.2f}",
                    "Max DD": f"{m['max_drawdown']:.2%}",
                    "勝率": f"{m['win_rate']:.0%}",
                    "交易次數": m['n_trades'],
                    "被指派": m['n_assigned'],
                    "總 Premium": f"${m['total_premium_collected']:,.0f}",
                } for name, m in strat_list])
                st.dataframe(comp_df, use_container_width=True, hide_index=True)

                best_strat_name, best_strat = strat_list[0]
                st.success(
                    f"🏆 **最佳策略：{best_strat_name}**  \n"
                    f"CAGR **{best_strat['cagr']:.2%}**，"
                    f"超額 **{best_strat['excess_return']:+.2%}**，"
                    f"勝率 **{best_strat['win_rate']:.0%}**"
                )

                # 不同情境推薦
                st.markdown("##### 不同情境下哪個贏？")
                max_cagr_strat = max(strat_results.items(), key=lambda x: x[1]['cagr'])[0]
                max_sharpe_strat = max(strat_results.items(), key=lambda x: x[1]['sharpe'])[0]
                min_dd_strat = min(strat_results.items(), key=lambda x: abs(x[1]['max_drawdown']))[0]
                max_win_strat = max(strat_results.items(), key=lambda x: x[1]['win_rate'])[0]

                scenarios = pd.DataFrame([
                    {"看重": "🚀 最大收益", "推薦": max_cagr_strat,
                     "理由": f"CAGR {strat_results[max_cagr_strat]['cagr']:.1%}"},
                    {"看重": "⚖️ 最佳風險報酬比", "推薦": max_sharpe_strat,
                     "理由": f"Sharpe {strat_results[max_sharpe_strat]['sharpe']:.2f}"},
                    {"看重": "🛡️ 最低回撤", "推薦": min_dd_strat,
                     "理由": f"Max DD {strat_results[min_dd_strat]['max_drawdown']:.1%}"},
                    {"看重": "🎯 最高勝率", "推薦": max_win_strat,
                     "理由": f"勝率 {strat_results[max_win_strat]['win_rate']:.0%}"},
                ])
                st.dataframe(scenarios, use_container_width=True, hide_index=True)

                if st.button("❌ 關閉", key="manual_strat_close"):
                    st.session_state.pop("manual_strat_sym", None)
                    st.rerun()

    # ---------- Top 3 詳細 ----------
    st.divider()
    st.markdown("### ⭐ Top 3 詳細解讀")
    st.caption("點按鈕看更多分析（IV 歷史圖、多策略比較）")

    for i in range(min(3, len(top_df))):
        row = top_df.iloc[i]
        rank_emoji = ["🥇", "🥈", "🥉"][i]
        sym = row['symbol']

        with st.container(border=True):
            c1, c2 = st.columns([2, 3])
            with c1:
                st.markdown(f"### {rank_emoji} #{i+1}: {sym}")
                st.metric("總分", f"{row['total_score']:.1f}/100")

            with c2:
                st.markdown("**評分拆解**")
                subc1, subc2, subc3, subc4 = st.columns(4)
                subc1.metric("IV", f"{row['iv_score']:.0f}", delta="高 IV = 多 premium" if row['iv_score'] > 60 else None)
                subc2.metric("沒漲", f"{row['momentum_score']:.0f}", delta="價格穩" if row['momentum_score'] > 70 else None)
                subc3.metric("流動性", f"{row['liquidity_score']:.0f}")
                subc4.metric("回測", f"{row['cagr_score']:.0f}")

            # 詳細指標
            st.markdown("**關鍵指標**")
            d1, d2, d3, d4 = st.columns(4)
            d1.metric("現價", f"${row['spot']:.2f}")
            d2.metric("30 天漲跌", f"{row['momentum_30d']:+.1f}%")
            d3.metric("IV / IV Rank",
                      f"{row['iv']*100:.1f}% / {row['iv_rank']:.0f}")
            d4.metric("日均成交額",
                      f"${row['dollar_volume']/1e9:.1f}B" if row['dollar_volume'] > 1e9
                      else f"${row['dollar_volume']/1e6:.0f}M")

            if pd.notna(row.get("cagr")):
                e1, e2, e3 = st.columns(3)
                e1.metric("近 5 年 CC CAGR", f"{row['cagr']:.1%}")
                e2.metric("BH CAGR", f"{row['bh_cagr']:.1%}")
                e3.metric("超額報酬",
                          f"{row['excess']:+.1%}",
                          delta=f"勝率 {row.get('win_rate', 0):.0%}")

            # 🆕 兩個分析按鈕
            st.markdown("**🔬 進階分析**")
            btn_c1, btn_c2, btn_c3 = st.columns([1, 1, 2])
            with btn_c1:
                show_iv = st.button(
                    "📊 IV Rank 歷史圖",
                    key=f"btn_iv_{sym}_{i}",
                    help="看過去 1 年 IV 走勢，判斷現在是不是賣選擇權的好時機",
                    use_container_width=True,
                )
            with btn_c2:
                show_strat = st.button(
                    "🔄 比較 4 種策略",
                    key=f"btn_strat_{sym}_{i}",
                    help="對這檔股票跑 CC/CSP/Wheel/PMCC 看哪個最賺",
                    use_container_width=True,
                )

            # ----- IV Rank 歷史圖 -----
            iv_key = f"show_iv_{sym}_{i}"
            if show_iv:
                st.session_state[iv_key] = True

            if st.session_state.get(iv_key):
                with st.expander(f"📊 {sym} IV Rank 歷史走勢", expanded=True):
                    with st.spinner(f"抓取 {sym} 的 IV 歷史資料..."):
                        iv_df = fetch_iv_history(sym)

                    if iv_df is None or iv_df.empty:
                        st.warning("無法抓取 IV 歷史資料")
                    else:
                        # 摘要指標
                        current_iv = iv_df["iv"].iloc[-1]
                        current_iv_rank = iv_df["iv_rank"].iloc[-1]
                        iv_52w_high = iv_df["iv"].max()
                        iv_52w_low = iv_df["iv"].min()
                        avg_iv = iv_df["iv"].mean()

                        mc1, mc2, mc3, mc4 = st.columns(4)
                        mc1.metric("當前 IV", f"{current_iv:.1f}%")
                        mc2.metric("當前 IV Rank", f"{current_iv_rank:.0f}",
                                    delta="高位（賣方有利）" if current_iv_rank > 60
                                          else "低位（不建議賣）" if current_iv_rank < 30
                                          else "中位",
                                    delta_color="normal" if current_iv_rank > 60
                                                else "inverse" if current_iv_rank < 30
                                                else "off")
                        mc3.metric("52 週高/低",
                                   f"{iv_52w_high:.1f}% / {iv_52w_low:.1f}%")
                        mc4.metric("過去 1 年平均", f"{avg_iv:.1f}%")

                        # 雙軸圖：IV + 股價
                        st.markdown("##### IV 走勢")
                        chart_iv = iv_df[["iv"]].copy()
                        chart_iv.columns = [f"{sym} IV (%)"]
                        st.line_chart(chart_iv, height=250)

                        st.markdown("##### IV Rank 走勢（>60 適合賣方）")
                        chart_rank = iv_df[["iv_rank"]].copy()
                        chart_rank.columns = [f"{sym} IV Rank"]
                        # 加入閾值線（用兩條額外列）
                        chart_rank["建議賣方門檻 (60)"] = 60
                        chart_rank["低 IV 警告 (30)"] = 30
                        st.line_chart(chart_rank, height=250)

                        st.markdown("##### 股價走勢（對照用）")
                        chart_price = iv_df[["price"]].copy()
                        chart_price.columns = [f"{sym} 股價 ($)"]
                        st.line_chart(chart_price, height=250)

                        # 解讀
                        if current_iv_rank > 70:
                            st.success(
                                f"🟢 **適合賣 CC / CSP**：{sym} 的 IV 處於過去 1 年高位 "
                                f"(Rank {current_iv_rank:.0f})，premium 較貴。"
                            )
                        elif current_iv_rank > 50:
                            st.info(
                                f"🟡 **可考慮**：{sym} 的 IV 處於中高位 "
                                f"(Rank {current_iv_rank:.0f})，premium 合理。"
                            )
                        elif current_iv_rank > 30:
                            st.info(
                                f"⚪ **觀望**：{sym} 的 IV 處於中位 "
                                f"(Rank {current_iv_rank:.0f})，premium 普通。"
                            )
                        else:
                            st.warning(
                                f"🔴 **不建議賣方**：{sym} 的 IV 處於低位 "
                                f"(Rank {current_iv_rank:.0f})，premium 太便宜，"
                                f"不划算。等 IV 上升再考慮。"
                            )

                        if st.button("關閉圖表", key=f"close_iv_{sym}_{i}"):
                            st.session_state[iv_key] = False
                            st.rerun()

            # ----- 多策略比較 -----
            strat_key = f"show_strat_{sym}_{i}"
            if show_strat:
                st.session_state[strat_key] = True

            if st.session_state.get(strat_key):
                with st.expander(f"🔄 {sym} 4 種策略比較", expanded=True):
                    with st.spinner(f"跑 {sym} 的 CC / CSP / Wheel / PMCC 回測（約 30-60 秒）..."):
                        strat_results = compare_all_strategies(sym)

                    if not strat_results:
                        st.warning("無法跑回測（資料不足或計算錯誤）")
                    else:
                        # 排序：依 CAGR 排
                        strat_list = sorted(
                            strat_results.items(),
                            key=lambda x: x[1].get("cagr", -999),
                            reverse=True,
                        )

                        # 表格比較
                        st.markdown("##### 各策略表現對比（過去 5 年）")

                        comp_df = pd.DataFrame([{
                            "策略": name,
                            "CAGR": f"{m['cagr']:.2%}",
                            "vs BH": f"{m['excess_return']:+.2%}",
                            "Sharpe": f"{m['sharpe']:.2f}",
                            "Max DD": f"{m['max_drawdown']:.2%}",
                            "勝率": f"{m['win_rate']:.0%}",
                            "交易次數": m['n_trades'],
                            "被指派": m['n_assigned'],
                            "總 Premium": f"${m['total_premium_collected']:,.0f}",
                        } for name, m in strat_list])

                        st.dataframe(comp_df, use_container_width=True, hide_index=True)

                        # 找最佳
                        best_strat_name, best_strat = strat_list[0]
                        st.success(
                            f"🏆 **最佳策略：{best_strat_name}**  \n"
                            f"CAGR **{best_strat['cagr']:.2%}**，"
                            f"超額 **{best_strat['excess_return']:+.2%}**，"
                            f"勝率 **{best_strat['win_rate']:.0%}**"
                        )

                        # 策略選擇建議
                        st.markdown("##### 💡 策略選擇建議")
                        strat_advice = {
                            "CC": "✅ 你已經持有 100 股，賣 Call 收 premium",
                            "CSP": "✅ 你有現金，賣 Put 等低接 + 收 premium",
                            "Wheel": "✅ 你想長期持續玩，CSP ↔ CC 自動切換",
                            "PMCC": "✅ 資金有限，用 LEAPS 取代股票（資金效率高但風險大）",
                        }
                        st.markdown(strat_advice.get(best_strat_name, ""))

                        # 條件對比
                        st.markdown("##### 不同情境下哪個贏？")
                        max_cagr_strat = max(strat_results.items(), key=lambda x: x[1]['cagr'])[0]
                        max_sharpe_strat = max(strat_results.items(), key=lambda x: x[1]['sharpe'])[0]
                        min_dd_strat = min(strat_results.items(), key=lambda x: abs(x[1]['max_drawdown']))[0]
                        max_win_strat = max(strat_results.items(), key=lambda x: x[1]['win_rate'])[0]

                        scenarios = pd.DataFrame([
                            {"看重": "🚀 最大收益", "推薦": max_cagr_strat,
                             "理由": f"CAGR {strat_results[max_cagr_strat]['cagr']:.1%}"},
                            {"看重": "⚖️ 最佳風險報酬比", "推薦": max_sharpe_strat,
                             "理由": f"Sharpe {strat_results[max_sharpe_strat]['sharpe']:.2f}"},
                            {"看重": "🛡️ 最低回撤", "推薦": min_dd_strat,
                             "理由": f"Max DD {strat_results[min_dd_strat]['max_drawdown']:.1%}"},
                            {"看重": "🎯 最高勝率", "推薦": max_win_strat,
                             "理由": f"勝率 {strat_results[max_win_strat]['win_rate']:.0%}"},
                        ])
                        st.dataframe(scenarios, use_container_width=True, hide_index=True)

                        if st.button("關閉策略比較", key=f"close_strat_{sym}_{i}"):
                            st.session_state[strat_key] = False
                            st.rerun()

            # 建議行動
            st.info(
                f"💡 **建議行動**：到「🎯 立即建議」分頁輸入 **{sym}**，"
                "系統會給你具體的合約推薦。"
            )

    # ---------- 篩選與解釋 ----------
    st.divider()
    with st.expander("ℹ️ 評分方法說明", expanded=False):
        st.markdown("""
**總分 = IV (25%) + 沒大漲 (25%) + 流動性 (20%) + 回測 CAGR (30%)**

| 指標 | 為什麼重要 | 計算方式 |
|---|---|---|
| **IV 分數** | IV 高 → premium 多，賣方有利 | 用近 30 日 realized vol × 1.20 估計，看在過去 1 年中的相對位置 (IV Rank) |
| **沒大漲分數** | 避免追高，剛大漲的標的容易回調 | 30 天漲幅 < 3% 滿分，> 12% 扣分 |
| **流動性分數** | 流動性差會被滑價吃掉獲利 | 日均成交額（dollar volume）> 50 億滿分 |
| **回測 CAGR 分數** | 證明這檔股票真的能用 CC 賺到錢 | 用過去 5 年標準策略（Δ0.25, 45 DTE, expiry）回測 |

**評分閾值**：
- 80+ 分：🟢 強推
- 60-80 分：🟡 不錯
- 40-60 分：⚪ 普通
- < 40 分：🔴 不建議

**注意**：總分高 ≠ 一定賺錢，請務必到「🎯 立即建議」看具體合約，並考慮自己的風險偏好。
        """)

    # ---------- 警告 ----------
    st.warning("""
⚠️ **重要提醒**：

1. 評分基於**歷史資料**，過去表現不代表未來
2. IV 估計用 realized vol × 1.20，**不如真實 IV 精準**
3. **盤後/週末資料可能不準確**
4. 推薦的標的不代表「該買」，只是「適合做 CC」—— 你需要願意持有這檔股票
5. **務必避開財報前一週**
    """)
