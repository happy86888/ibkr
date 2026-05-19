"""
Covered Call System - Cloud Edition
====================================
Backtest + Screener only (no IBKR connection needed).
Deployed to Streamlit Cloud / Hugging Face Spaces / any Python host.

Local run:
    streamlit run app.py
"""
import streamlit as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from ui.auth import check_password, logout_button
from ui.backtest_page import render_backtest_page
from ui.screener_page import render_screener_page


# ---------------- Page setup ----------------
st.set_page_config(
    page_title="Covered Call System",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
    .main > div { padding-top: 1rem; }
    [data-testid="stMetricValue"] { font-size: 1.4rem; }
    .stTabs [data-baseweb="tab-list"] { gap: 8px; }
    .stTabs [data-baseweb="tab"] {
        padding: 8px 16px;
        background-color: rgba(38, 39, 48, 0.4);
        border-radius: 4px 4px 0 0;
    }
    .stTabs [aria-selected="true"] {
        background-color: rgba(255, 75, 75, 0.15);
    }
    /* Hide deploy button when in cloud */
    .stDeployButton { display: none; }
    div[data-testid="stToolbar"] { display: none; }
</style>
""", unsafe_allow_html=True)

# ---------------- Auth ----------------
check_password()

# ---------------- Sidebar ----------------
with st.sidebar:
    st.markdown("### 📈 CC System")
    st.caption("Cloud Edition")
    st.divider()
    st.markdown("**Features**")
    st.caption(
        "✅ Multi-strategy backtest  \n"
        "✅ CC opportunity screener  \n"
        "❌ Live IBKR connection*  \n\n"
        "*IBKR requires local installation"
    )
    st.divider()
    logout_button()

# ---------------- Main ----------------
st.title("📈 Covered Call Trading System")
st.caption("Backtest 4 strategies (CC, CSP, Wheel, PMCC) + screen for opportunities")

tab_backtest, tab_screener, tab_about = st.tabs([
    "🧪 Backtest", "🔍 Screener", "ℹ️ About"
])

with tab_backtest:
    render_backtest_page()

with tab_screener:
    render_screener_page()

with tab_about:
    st.subheader("ℹ️ About this app")
    st.markdown("""
**支援的策略：**

- **CC (Covered Call)** — 備兌賣權，持有 100 股 + 賣 OTM Call
- **CSP (Cash-Secured Put)** — 現金擔保賣權，持有現金 + 賣 OTM Put
- **Wheel** — 輪賣策略，CSP ↔ CC 根據指派狀態自動切換
- **PMCC (Poor Man's CC)** — 用 LEAPS Deep ITM Call 取代股票，再賣短期 OTM Call

**Premium 合成模型：**

由於不訂閱付費歷史選擇權資料，採用以下方法估計 historical premium：
1. yfinance 抓取股價歷史與股息
2. 計算 30 天**滾動 Realized Volatility**
3. 套用 **IV Risk Premium**（IV ≈ RV × 1.20）
4. **VIX/VXN/RVX** 校準
5. **Black-Scholes** 計算 historical premium

**Screener 資料：**

yfinance 提供的選擇權 chain（免費但盤中可能延遲 15-20 分鐘）。Greeks 用 Black-Scholes 從 yfinance 的 IV 反算。

**⚠️ 重要免責聲明：**

- 本工具僅供分析參考，**不構成投資建議**
- 選擇權交易風險高，可能損失全部投入資金
- 回測結果是模型估算，**不代表未來真實表現**
- 實際交易要考慮稅務、傭金、市場衝擊等本工具未模擬的因素
- 使用前請確認自己理解策略的風險
""")
