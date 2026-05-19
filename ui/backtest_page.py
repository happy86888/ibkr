"""
Backtest UI Page - Multi-Strategy Matrix Comparison
====================================================
Supports CC, CSP, Wheel, and PMCC strategies side-by-side.
"""
import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from core.data_loader import prepare_backtest_data
from core.backtest import CCStrategy, CCBacktest
from core.backtest_csp_wheel import CSPStrategy, CSPBacktest, WheelStrategy, WheelBacktest
from core.backtest_pmcc import PMCCStrategy, PMCCBacktest


def format_pct(x):
    return f"{x:.2%}" if pd.notna(x) else "—"


def metrics_summary_table(results) -> pd.DataFrame:
    rows = []
    for r in results:
        m = r.metrics
        if not m:
            continue
        rows.append({
            "Strategy": r.strategy_name,
            "Symbol": r.symbol,
            "CAGR": m["cagr"],
            "BH CAGR": m["bh_cagr"],
            "Excess": m["excess_return"],
            "Sharpe": m["sharpe"],
            "Max DD": m["max_drawdown"],
            "Trades": m["n_trades"],
            "Win Rate": m["win_rate"],
            "Assigned": m["n_assigned"],
            "Premium $": m["total_premium_collected"],
            "Final $": m["final_equity"],
        })
    return pd.DataFrame(rows)


def render_backtest_page():
    st.subheader("🧪 多策略回測 Multi-Strategy Backtest")
    st.caption(
        "比較 CC、CSP、Wheel、PMCC 4 種策略的歷史表現。"
        "Premium 使用 Black-Scholes + VIX 校準 IV 合成。"
    )

    # ---------- Universe & Period ----------
    with st.container(border=True):
        st.markdown("##### 1️⃣ 標的與期間 / Universe & Period")
        c1, c2 = st.columns([2, 1])
        with c1:
            symbols_input = st.text_input(
                "標的代碼 Symbols（逗號分隔）",
                value="SPY, QQQ, AAPL",
                help="可以是個股或 ETF，例如 AAPL, MSFT, SPY",
            )
        with c2:
            preset = st.selectbox(
                "期間預設 Period preset",
                ["自訂 Custom", "近 1 年 Last 1 year", "近 3 年 Last 3 years",
                 "近 5 年 Last 5 years", "2022 熊市 (bear)", "2023 牛市 (bull)",
                 "2020-2023 完整循環 (full cycle)"],
                index=2,
            )

        today = datetime.now().date()
        default_start = today - timedelta(days=365 * 3)
        default_end = today
        if "Last 1" in preset or "近 1" in preset:
            default_start = today - timedelta(days=365)
        elif "Last 3" in preset or "近 3" in preset:
            default_start = today - timedelta(days=365 * 3)
        elif "Last 5" in preset or "近 5" in preset:
            default_start = today - timedelta(days=365 * 5)
        elif "2022" in preset:
            default_start, default_end = datetime(2022, 1, 1).date(), datetime(2022, 12, 31).date()
        elif "2023" in preset:
            default_start, default_end = datetime(2023, 1, 1).date(), datetime(2023, 12, 31).date()
        elif "2020-2023" in preset:
            default_start, default_end = datetime(2020, 1, 1).date(), datetime(2023, 12, 31).date()

        c3, c4 = st.columns(2)
        with c3:
            start_date = st.date_input("起始日 Start", default_start)
        with c4:
            end_date = st.date_input("結束日 End", default_end)

    # ---------- Strategy selection ----------
    with st.container(border=True):
        st.markdown("##### 2️⃣ 策略選擇 / Strategies to Compare")
        st.caption("啟用策略並設定參數，所有勾選的組合都會跑")

        strategy_tabs = st.tabs(["📈 CC 備兌賣權", "📉 CSP 現金擔保賣權", "🔄 Wheel 輪賣", "💸 PMCC 窮人版"])

        # CC
        with strategy_tabs[0]:
            cc_enabled = st.checkbox("啟用 Covered Call", value=True, key="cc_en")
            cc_delta_values = []
            cc_dte_values = []
            cc_close_rules = []
            if cc_enabled:
                c1, c2, c3 = st.columns(3)
                with c1:
                    cc_delta_values = st.multiselect(
                        "Delta 目標", [0.15, 0.20, 0.25, 0.30, 0.35],
                        default=[0.25], key="cc_delta",
                        help="Delta 越低 = 越 OTM = 越安全但 premium 少")
                with c2:
                    cc_dte_values = st.multiselect(
                        "DTE 到期天數", [7, 14, 21, 30, 45, 60],
                        default=[30], key="cc_dte",
                        help="距離到期日剩幾天，常用 30-45")
                with c3:
                    cc_close_rules = st.multiselect(
                        "Close Rule 關閉規則", ["expiry", "profit_50", "dte_21", "hybrid"],
                        default=["hybrid"], key="cc_close",
                        help="expiry=持有到期 / profit_50=50%獲利平倉 / dte_21=21天剩餘平倉 / hybrid=混合")

        # CSP
        with strategy_tabs[1]:
            st.caption(
                "**CSP 現金擔保賣權**：持有現金，賣 OTM Put。"
                "若被指派，會以 strike 價買進股票（之後持有到回測結束）。"
            )
            csp_enabled = st.checkbox("啟用 CSP", value=True, key="csp_en")
            csp_delta_values = []
            csp_dte_values = []
            csp_close_rules = []
            if csp_enabled:
                c1, c2, c3 = st.columns(3)
                with c1:
                    csp_delta_values = st.multiselect(
                        "Put Delta（絕對值）", [0.10, 0.15, 0.20, 0.25, 0.30, 0.35],
                        default=[0.20], key="csp_delta")
                with c2:
                    csp_dte_values = st.multiselect(
                        "DTE 到期天數", [7, 14, 21, 30, 45, 60],
                        default=[30], key="csp_dte")
                with c3:
                    csp_close_rules = st.multiselect(
                        "Close Rule 關閉規則", ["expiry", "profit_50", "dte_21", "hybrid"],
                        default=["hybrid"], key="csp_close")

        # Wheel
        with strategy_tabs[2]:
            st.caption(
                "**輪賣策略 Wheel**：CSP → (被指派) → CC → (被收走) → CSP → ...\n"
                "根據持股狀態在 Put 與 Call 之間自動切換。"
            )
            wheel_enabled = st.checkbox("啟用 Wheel", value=True, key="wheel_en")
            wheel_put_deltas = []
            wheel_call_deltas = []
            wheel_close_rules = []
            wheel_put_dte = 30
            wheel_call_dte = 30
            if wheel_enabled:
                c1, c2 = st.columns(2)
                with c1:
                    st.markdown("**Put 賣方（沒持股時）**")
                    wheel_put_deltas = st.multiselect(
                        "Put Delta", [0.15, 0.20, 0.25, 0.30],
                        default=[0.20], key="wheel_pd")
                    wheel_put_dte = st.selectbox("Put DTE", [21, 30, 45], index=1, key="wheel_pdte")
                with c2:
                    st.markdown("**Call 賣方（有持股時）**")
                    wheel_call_deltas = st.multiselect(
                        "Call Delta", [0.15, 0.20, 0.25, 0.30, 0.35],
                        default=[0.25], key="wheel_cd")
                    wheel_call_dte = st.selectbox("Call DTE", [21, 30, 45], index=1, key="wheel_cdte")
                wheel_close_rules = st.multiselect(
                    "Close Rule 關閉規則", ["expiry", "profit_50", "dte_21", "hybrid"],
                    default=["hybrid"], key="wheel_close")

        # PMCC
        with strategy_tabs[3]:
            st.caption(
                "**PMCC 窮人版 CC**：買深 ITM LEAPS（取代股票），賣短期 OTM Call。"
                "使用約 50% 資金做出類似 CC 的效果。"
            )
            pmcc_enabled = st.checkbox("啟用 PMCC", value=False, key="pmcc_en",
                                        help="PMCC 資金效率高但有 LEAPS theta + IV 風險")
            pmcc_leaps_deltas = []
            pmcc_short_deltas = []
            pmcc_close_rules = []
            pmcc_leaps_dte = 365
            pmcc_leaps_roll = 60
            pmcc_short_dte = 30
            if pmcc_enabled:
                c1, c2 = st.columns(2)
                with c1:
                    st.markdown("**LEAPS（長腿，買進的）**")
                    pmcc_leaps_deltas = st.multiselect(
                        "LEAPS Delta（深 ITM）", [0.70, 0.75, 0.80, 0.85],
                        default=[0.80], key="pmcc_ld")
                    pmcc_leaps_dte = st.selectbox(
                        "LEAPS 開倉 DTE", [180, 270, 365, 540, 720], index=2, key="pmcc_ldte")
                    pmcc_leaps_roll = st.number_input(
                        "LEAPS Roll 時機（DTE <）", 30, 180, 60, key="pmcc_lroll")
                with c2:
                    st.markdown("**Short Call（短腿，賣出的）**")
                    pmcc_short_deltas = st.multiselect(
                        "Short Call Delta", [0.15, 0.20, 0.25, 0.30],
                        default=[0.25], key="pmcc_sd")
                    pmcc_short_dte = st.selectbox("Short DTE", [21, 30, 45], index=1, key="pmcc_sdte")
                pmcc_close_rules = st.multiselect(
                    "Close Rule（短 Call）", ["expiry", "profit_50", "dte_21", "hybrid"],
                    default=["hybrid"], key="pmcc_close")

        # Count strategies
        n_cc = (len(cc_delta_values) * len(cc_dte_values) * len(cc_close_rules)) if cc_enabled else 0
        n_csp = (len(csp_delta_values) * len(csp_dte_values) * len(csp_close_rules)) if csp_enabled else 0
        n_wheel = (len(wheel_put_deltas) * len(wheel_call_deltas) * len(wheel_close_rules)) if wheel_enabled else 0
        n_pmcc = (len(pmcc_leaps_deltas) * len(pmcc_short_deltas) * len(pmcc_close_rules)) if pmcc_enabled else 0
        total_strats = n_cc + n_csp + n_wheel + n_pmcc

        symbols = [s.strip().upper() for s in symbols_input.split(",") if s.strip()]
        total_runs = total_strats * len(symbols)

        st.info(
            f"📊 **{len(symbols)} 個標的 × {total_strats} 個策略 = {total_runs} 次回測**  \n"
            f"CC: {n_cc} • CSP: {n_csp} • Wheel: {n_wheel} • PMCC: {n_pmcc}"
        )

    # ---------- Advanced ----------
    with st.expander("⚙️ 進階設定 / Advanced（滑價、傭金）"):
        c1, c2 = st.columns(2)
        spread_pct = c1.slider("買賣價差 % Bid-ask spread", 0.0, 20.0, 5.0, 1.0,
                                help="模擬實際成交比 mid 差多少") / 100
        commission = c2.number_input("每張傭金 $ Commission", 0.0, 5.0, 0.65, 0.05)

    # ---------- Run ----------
    run_btn = st.button("▶️ 開始回測 Run Backtest", type="primary",
                         disabled=(total_runs == 0 or not symbols))

    if run_btn:
        all_results = []
        progress = st.progress(0, "Loading data...")
        status = st.empty()
        run_count = 0

        for sym_idx, symbol in enumerate(symbols):
            status.text(f"📥 Loading {symbol}...")
            try:
                data = prepare_backtest_data(
                    symbol, start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d")
                )
                if data["prices"].empty:
                    st.warning(f"{symbol}: no price data")
                    continue
            except Exception as e:
                st.error(f"{symbol}: {e}")
                continue

            if cc_enabled:
                for d in cc_delta_values:
                    for dte in cc_dte_values:
                        for cr in cc_close_rules:
                            run_count += 1
                            progress.progress(run_count / total_runs, f"{symbol} • CC Δ{d:.2f} {dte}D {cr}")
                            try:
                                s = CCStrategy(
                                    name=f"CC_Δ{d:.2f}_{dte}D_{cr}",
                                    target_delta=d, target_dte=dte, close_rule=cr,
                                    bid_ask_spread_pct=spread_pct, commission_per_contract=commission)
                                all_results.append(CCBacktest(data, s).run())
                            except Exception as e:
                                st.warning(f"CC failed: {e}")

            if csp_enabled:
                for d in csp_delta_values:
                    for dte in csp_dte_values:
                        for cr in csp_close_rules:
                            run_count += 1
                            progress.progress(run_count / total_runs, f"{symbol} • CSP Δ{d:.2f} {dte}D {cr}")
                            try:
                                s = CSPStrategy(
                                    name=f"CSP_Δ{d:.2f}_{dte}D_{cr}",
                                    target_delta=d, target_dte=dte, close_rule=cr,
                                    bid_ask_spread_pct=spread_pct, commission_per_contract=commission)
                                all_results.append(CSPBacktest(data, s).run())
                            except Exception as e:
                                st.warning(f"CSP failed: {e}")

            if wheel_enabled:
                for pd_ in wheel_put_deltas:
                    for cd in wheel_call_deltas:
                        for cr in wheel_close_rules:
                            run_count += 1
                            progress.progress(run_count / total_runs, f"{symbol} • Wheel P{pd_:.2f}/C{cd:.2f} {cr}")
                            try:
                                s = WheelStrategy(
                                    name=f"Wheel_P{pd_:.2f}_C{cd:.2f}_{cr}",
                                    put_delta=pd_, call_delta=cd,
                                    put_dte=wheel_put_dte, call_dte=wheel_call_dte,
                                    close_rule=cr,
                                    bid_ask_spread_pct=spread_pct, commission_per_contract=commission)
                                all_results.append(WheelBacktest(data, s).run())
                            except Exception as e:
                                st.warning(f"Wheel failed: {e}")

            if pmcc_enabled:
                for ld in pmcc_leaps_deltas:
                    for sd in pmcc_short_deltas:
                        for cr in pmcc_close_rules:
                            run_count += 1
                            progress.progress(run_count / total_runs, f"{symbol} • PMCC L{ld:.2f}/S{sd:.2f} {cr}")
                            try:
                                s = PMCCStrategy(
                                    name=f"PMCC_L{ld:.2f}_S{sd:.2f}_{cr}",
                                    leaps_delta=ld, short_delta=sd,
                                    leaps_dte=pmcc_leaps_dte, leaps_roll_dte=pmcc_leaps_roll,
                                    short_dte=pmcc_short_dte, short_close_rule=cr,
                                    bid_ask_spread_pct=spread_pct, commission_per_contract=commission)
                                all_results.append(PMCCBacktest(data, s).run())
                            except Exception as e:
                                st.warning(f"PMCC failed: {e}")

        progress.empty()
        status.empty()

        if all_results:
            st.session_state["backtest_results"] = all_results
            st.success(f"✅ 完成 {len(all_results)} 次回測 / Completed {len(all_results)} backtests")
        else:
            st.error("無結果 / No results")

    # ---------- Display ----------
    if "backtest_results" in st.session_state and st.session_state["backtest_results"]:
        results = st.session_state["backtest_results"]
        st.divider()
        st.markdown("### 📈 回測結果 Results")

        summary = metrics_summary_table(results)
        if not summary.empty:
            c1, c2, c3, c4 = st.columns(4)
            best_cagr = summary.loc[summary["CAGR"].idxmax()]
            best_excess = summary.loc[summary["Excess"].idxmax()]
            best_sharpe = summary.loc[summary["Sharpe"].idxmax()]
            c1.metric("最高 CAGR / Best CAGR", f"{best_cagr['CAGR']:.2%}",
                      delta=f"{best_cagr['Strategy'][:30]}")
            c2.metric("最大超額報酬 / Best vs BH", f"{best_excess['Excess']:+.2%}",
                      delta=f"{best_excess['Strategy'][:30]}")
            c3.metric("最佳夏普 / Best Sharpe", f"{best_sharpe['Sharpe']:.2f}",
                      delta=f"{best_sharpe['Strategy'][:30]}")
            c4.metric("回測總數 / Total", len(results))

        # Filters
        c1, c2 = st.columns([1, 3])
        with c1:
            filter_type = st.selectbox("篩選 Filter", ["全部 All", "CC", "CSP", "Wheel", "PMCC"])
        with c2:
            sort_by = st.selectbox("排序 Sort by",
                                    ["CAGR", "Excess", "Sharpe", "Max DD"], index=0)

        filtered = summary.copy()
        if filter_type != "全部 All" and filter_type != "All":
            filtered = filtered[filtered["Strategy"].str.startswith(filter_type)]
        filtered = filtered.sort_values(sort_by, ascending=(sort_by == "Max DD"))

        display = filtered.copy()
        for col in ["CAGR", "BH CAGR", "Excess", "Max DD", "Win Rate"]:
            display[col] = display[col].apply(format_pct)
        display["Sharpe"] = display["Sharpe"].apply(lambda x: f"{x:.2f}")
        display["Premium $"] = display["Premium $"].apply(lambda x: f"${x:,.0f}")
        display["Final $"] = display["Final $"].apply(lambda x: f"${x:,.0f}")

        st.dataframe(display, use_container_width=True, hide_index=True)
        csv = filtered.to_csv(index=False).encode("utf-8")
        st.download_button("📥 下載 CSV / Download", csv, "backtest_results.csv", "text/csv")

        # Equity curves
        st.markdown("#### 權益曲線 Equity Curves")
        symbols_list = sorted(set(r.symbol for r in results))
        sel_sym = st.selectbox("選擇標的 Symbol", symbols_list)
        sym_results = [r for r in results if r.symbol == sel_sym]
        all_names = [r.strategy_name for r in sym_results]
        sel_names = st.multiselect(
            "選擇要繪製的策略（建議 ≤ 8 條）",
            all_names, default=all_names[:6])

        if sel_names:
            chart_data = pd.DataFrame()
            for r in sym_results:
                if r.strategy_name in sel_names:
                    curve = r.equity_curve["equity"] / r.equity_curve["equity"].iloc[0]
                    curve.name = r.strategy_name
                    chart_data = pd.concat([chart_data, curve], axis=1)
            if sym_results:
                bh = (sym_results[0].equity_curve["bh_equity"] /
                      sym_results[0].equity_curve["bh_equity"].iloc[0])
                bh.name = f"BuyHold {sel_sym}"
                chart_data = pd.concat([chart_data, bh], axis=1)
            st.line_chart(chart_data, height=400)

        # Trade detail
        st.markdown("#### 交易明細 Trade Detail")
        sel_strat = st.selectbox("策略 Strategy", all_names)
        sel_r = next((r for r in sym_results if r.strategy_name == sel_strat), None)
        if sel_r and sel_r.trades:
            tdf = pd.DataFrame([{
                "進場日": t.entry_date.date(),
                "出場日": t.exit_date.date(),
                "持有天數": (t.exit_date - t.entry_date).days,
                "進場價": round(t.entry_spot, 2),
                "出場價": round(t.exit_spot, 2),
                "Strike": t.strike,
                "Δ": round(t.delta_at_entry, 3) if t.delta_at_entry else None,
                "IV": round(t.iv_at_entry, 3) if t.iv_at_entry else None,
                "收到 Premium": round(t.premium_collected, 2),
                "平倉 Premium": round(t.premium_paid_to_close, 2),
                "出場原因": t.exit_reason,
                "Premium P&L": round(t.premium_pnl, 2),
                "Stock P&L": round(t.stock_pnl_during_hold, 2),
            } for t in sel_r.trades])
            st.dataframe(tdf, use_container_width=True, hide_index=True)
        else:
            st.info("無交易紀錄")
