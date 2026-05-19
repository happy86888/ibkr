"""
操作手冊 / User Manual Page
==========================
詳細的策略解碼、IBKR 下單教學、常見問題。
"""
import streamlit as st


def render_manual_page():
    st.subheader("📖 操作手冊 / User Manual")
    st.caption("從零開始學會用這個系統做 Covered Call")

    # 目錄
    with st.container(border=True):
        st.markdown("""
**📑 目錄**

1. [策略名稱怎麼讀（命名規則）](#section-1)
2. [4 種策略各是什麼？](#section-2)
3. [關閉規則（Close Rule）是什麼？](#section-3)
4. [Delta、DTE、OTM 名詞解釋](#section-4)
5. [回測結果怎麼看？](#section-5)
6. [從回測結果到實際下單（IBKR 教學）](#section-6)
7. [常見問題 FAQ](#section-7)
8. [風險警告](#section-8)
        """)

    # ============================================================
    # Section 1: 策略命名規則
    # ============================================================
    st.markdown("---")
    st.markdown('<a name="section-1"></a>', unsafe_allow_html=True)
    st.markdown("## 1️⃣ 策略名稱怎麼讀（命名規則）")

    st.markdown("""
回測表格上會看到像 `CC_Δ0.20_45D_expiry` 這樣的名稱。拆解如下：
    """)

    st.code("""
CC_Δ0.20_45D_expiry
│   │     │   │
│   │     │   └── 關閉規則：expiry = 持有到到期日
│   │     └────── DTE：45 天後到期
│   └──────────── Delta：0.20（決定 strike 多 OTM）
└──────────────── 策略類型：CC (Covered Call)
    """, language="text")

    st.markdown("""
**其他策略命名範例：**

| 名稱 | 翻譯 |
|---|---|
| `CC_Δ0.25_30D_hybrid` | 賣 Call，Delta 0.25，30 天到期，混合關閉規則 |
| `CSP_Δ0.20_45D_expiry` | 賣 Put，Delta 0.20，45 天到期，持有到期 |
| `Wheel_P0.20_C0.25_hybrid` | 輪賣，Put Δ0.20 / Call Δ0.25，混合關閉 |
| `PMCC_L0.80_S0.25_hybrid` | 窮人 CC，LEAPS Δ0.80 / 短 Call Δ0.25 |
    """)

    # ============================================================
    # Section 2: 4 種策略
    # ============================================================
    st.markdown("---")
    st.markdown('<a name="section-2"></a>', unsafe_allow_html=True)
    st.markdown("## 2️⃣ 4 種策略各是什麼？")

    tab1, tab2, tab3, tab4 = st.tabs(["📈 CC", "📉 CSP", "🔄 Wheel", "💸 PMCC"])

    with tab1:
        st.markdown("""
### CC — Covered Call（備兌賣權）

**結構：**
- ✅ 你**持有 100 股**標的（例如 AAPL）
- ✅ 你**賣出 1 張 OTM Call**
- 💰 收到 premium（權利金）

**獲利情境：**
- 股票橫盤或微漲 → 賺 premium ✅
- 股票大跌 → premium 緩衝一點下跌（但股票還是虧）
- 股票暴漲超過 strike → 股票被收走（但仍是賺，只是少賺）

**何時用：**
- 看好標的但**預期不會大漲**
- 想用持股**生現金流**
- 願意以 strike 賣掉股票

**資金需求：**
- 標的價 × 100 股（例如 AAPL $300 → $30,000）

**最大風險：**
- 股票下跌（與直接持股相同的下跌風險，只是有一點 premium 緩衝）
        """)

    with tab2:
        st.markdown("""
### CSP — Cash-Secured Put（現金擔保賣權）

**結構：**
- ✅ 你**持有現金**（足以買 100 股）
- ✅ 你**賣出 1 張 OTM Put**
- 💰 收到 premium

**獲利情境：**
- 股票橫盤或上漲 → Put 失效，賺 premium ✅
- 股票跌破 strike → 被指派，用 strike 價買進 100 股

**何時用：**
- **想低接**標的，順便賺權利金
- 例如 AAPL 現在 $300，你想 $280 再買 → 賣 strike $280 的 Put
- 不管被不被指派都「贏」

**資金需求：**
- Strike × 100 股的現金（鎖定不能動）

**最大風險：**
- 股票暴跌 → 你被迫高價買進（但本來就想買，只是 strike 不夠低）
        """)

    with tab3:
        st.markdown("""
### Wheel — 輪賣策略

**結構（狀態機）：**
```
[手上有現金]
    ↓ 賣 Put
[CSP 進行中]
    ├── Put 失效 → 重新賣 Put
    └── Put 被指派 → 拿到 100 股
                       ↓
                   [手上有股票]
                       ↓ 賣 Call (= CC)
                   [CC 進行中]
                       ├── Call 失效 → 重新賣 Call
                       └── Call 被指派 → 股票被收走，拿到現金
                                          ↓
                                       回到最上面
```

**核心邏輯：**
- 沒股票時賣 Put（CSP），有股票時賣 Call（CC）
- 兩邊都收 premium
- 持續循環

**何時用：**
- **震盪市**最強
- 對標的有長期信心、願意「來回交易」

**最大風險：**
- 在牛市中錯失大漲（被 Call 收走 + 持續賣 Put 從未進場）
        """)

    with tab4:
        st.markdown("""
### PMCC — Poor Man's Covered Call（窮人版 CC）

**結構：**
- ✅ 買 **1 張 LEAPS 深 ITM Call**（取代股票）
  - 例如 AAPL $300，買 strike $200、1 年後到期、Delta 0.80 的 Call
  - 成本約 $11,000（vs 直接買股票 $30,000）
- ✅ 賣 **1 張短期 OTM Call**（賺 premium）
- 💰 用一半資金做出類似 CC 的效果

**何時用：**
- 看好標的但**資金有限**
- 想用槓桿做 CC

**資金需求：**
- LEAPS 價格 × 100 股（約是直接買股票的 40-60%）

**最大風險：**
- LEAPS 有 Theta（時間衰減）
- 標的暴跌時 LEAPS 虧損比股票大
- 短 Call 被指派時要處理（複雜）
        """)

    # ============================================================
    # Section 3: 關閉規則
    # ============================================================
    st.markdown("---")
    st.markdown('<a name="section-3"></a>', unsafe_allow_html=True)
    st.markdown("## 3️⃣ 關閉規則（Close Rule）是什麼？")

    st.markdown("""
賣出 Call/Put 之後，**什麼時候平倉？** 有 4 種規則：

| 規則 | 中文 | 邏輯 |
|---|---|---|
| **expiry** | 持有到期 | 不管中途發生什麼，等到到期日 |
| **profit_50** | 50% 獲利平倉 | 當 premium 賺到 50% 時主動買回平倉 |
| **dte_21** | 21 天剩餘平倉 | 距離到期還剩 21 天時就先平倉，避開 Gamma 風險 |
| **hybrid** | 混合（先到先用）| profit_50 和 dte_21 哪個先達到就觸發 |

**經典教科書建議：** 用 `profit_50` 或 `hybrid`，因為理論上「鎖定獲利」、「避開到期前波動」。

**但回測常常顯示：** 在牛市中 `expiry` 反而最好（懶人贏）。具體哪個好 **看標的、看市況**，這就是為什麼要回測。

⚠️ **重要：** 沒有「永遠最好」的規則，市況變了規則也該變。
    """)

    # ============================================================
    # Section 4: 名詞解釋
    # ============================================================
    st.markdown("---")
    st.markdown('<a name="section-4"></a>', unsafe_allow_html=True)
    st.markdown("## 4️⃣ Delta、DTE、OTM 名詞解釋")

    with st.container(border=True):
        st.markdown("""
### 🎯 Delta（Δ）

**白話：** 衡量「選擇權對股價變動的敏感度」，也可理解為「被指派的機率」。

| Delta | 意思 | 對 CC 影響 |
|---|---|---|
| 0.10 | 約 10% 機率被指派、深 OTM | premium 少、安全 |
| 0.20 | 約 20% 機率、中 OTM | premium 適中、平衡（常用）|
| 0.30 | 約 30% 機率、近 OTM | premium 高、容易被指派 |
| 0.50 | ATM（價平）| premium 最大，但有 50% 機率被指派 |

**經驗法則：** 賣 CC 通常選 Delta 0.20 ~ 0.30。
        """)

    with st.container(border=True):
        st.markdown("""
### 📅 DTE（Days to Expiration，到期天數）

**白話：** 從今天到選擇權到期還有幾天。

| DTE | 名稱 | 特性 | 適合誰 |
|---|---|---|---|
| **7 天** | **週選 Weekly** | 高 Theta、高週轉、年化 premium 高 | 有時間每週管理的人 |
| **14 天** | **雙週選 Bi-weekly** | 平衡點 | 半被動管理 |
| **21 天** | **月選短期** | tastytrade 學派的「Gamma 警戒線」 | 進階玩家 |
| **30 天** | **月選 Monthly** | 主流選擇、流動性最好 | 大多數人 |
| **45 天** | **45 DTE 經典** | theta 衰減最快、業界推薦 | ⭐ tastytrade 信徒 |
| 60 天 | 月選長期 | premium 多但週轉慢 | 想低管理頻率 |
| 90+ 天 | 季選 / LEAPS | 通常用在 PMCC 長腿 | PMCC 策略 |

**重要：沒有「最好的 DTE」，只有「最適合你的 DTE」**

- **資金少**：賣 7 天，週週收 premium，現金流快
- **時間少**：賣 45 天，一個月看一次就好
- **心臟弱**：賣 14-21 天，介於兩者之間
- **看漲**：賣短天期（少賣一些上漲）
- **看跌**：賣長天期（拿更多 premium）

**回測會告訴你哪個對你的標的最有效！**
        """)

    with st.container(border=True):
        st.markdown("""
### 🗓️ 回測期間（Backtest Period）為什麼重要？

**「3 年回測」 vs 「10 年回測」的差別：**

| 期間 | 包含的市場環境 | 結論可信度 |
|---|---|---|
| 1 年 | 主要當前市況 | ⚠️ 樣本太小 |
| 3 年 | 約 2-3 個事件 | 🟡 普通（牛市中可能高估）|
| **5 年** | **含 2022 熊市** | ⭐ **平衡** |
| 7 年 | 含 2018 Q4 熊市 + 2022 熊市 | 🟢 完整 |
| **10 年** | **含 2018、2020、2022 三次熊市** | 🟢 **最完整** |

**為什麼 3 年回測可能誤導？**

2023-2026 是**連續 3 年牛市**：
- 2023：SPY +24%
- 2024：SPY +25%
- 2025-2026：繼續漲

→ 在這種環境，**任何 CC 策略都會贏**，因為股票一直漲、CC 一直收 premium。

→ 但回測**沒告訴你**：2022 熊市時 CC 表現如何？2020 閃崩時呢？

**真實案例**：用 5-10 年資料回測，會發現：
- **45 DTE expiry** 在熊市時表現平庸
- **30 DTE hybrid** 在震盪市場更穩
- **PMCC** 在 2022 熊市虧得比 CC 多

**經驗法則：**
- 想知道「**這檔我能不能用 CC 賺錢**」→ 用 5 年或 10 年
- 想知道「**目前市況下最佳策略**」→ 用 1-3 年
- **理想做法**：兩個都跑，互相對照
        """)

    with st.container(border=True):
        st.markdown("""
### 📏 OTM、ATM、ITM

| 縮寫 | 全名 | 意思 |
|---|---|---|
| **OTM** | Out-of-The-Money | 價外（Call 的 strike > 現價）|
| **ATM** | At-The-Money | 價平（strike ≈ 現價）|
| **ITM** | In-The-Money | 價內（Call 的 strike < 現價）|

例：AAPL 現價 $300
- Call strike $320 → OTM 6.7%
- Call strike $300 → ATM
- Call strike $280 → ITM 6.7%

**CC 通常賣 OTM Call**（避免立刻被指派）。
        """)

    with st.container(border=True):
        st.markdown("""
### 🔍 IV（Implied Volatility，隱含波動率）

**白話：** 市場對未來波動的預期。IV 高 → premium 貴 → 賣方有利。

**IV Rank** = 當前 IV 在過去 52 週的相對位置（0-100）
- IV Rank > 50 → 賣選擇權的好時機
- IV Rank < 20 → 不太划算

**經驗法則：** 賣 CC 最好在 IV Rank > 30 時做。
        """)

    # ============================================================
    # Section 5: 回測結果怎麼看
    # ============================================================
    st.markdown("---")
    st.markdown('<a name="section-5"></a>', unsafe_allow_html=True)
    st.markdown("## 5️⃣ 回測結果怎麼看？")

    st.markdown("""
跑完回測後，**Results 表格**上的每個欄位意思如下：
    """)

    st.markdown("""
| 欄位 | 中文 | 越高越好？ | 說明 |
|---|---|---|---|
| **Strategy** | 策略名稱 | — | 看 Section 1 的命名規則 |
| **Symbol** | 標的 | — | AAPL、SPY 等 |
| **CAGR** | 年化報酬率 | ⬆️ 越高越好 | 把總報酬轉成「每年複利幾%」|
| **BH CAGR** | 持有不動年化 | — | 同期 Buy & Hold 的年化（基準）|
| **Excess** | 超額報酬 | ⬆️ 越高越好 | CAGR - BH CAGR，**這是關鍵指標** |
| **Sharpe** | 夏普值 | ⬆️ 越高越好 | 風險調整後報酬，>1 算優秀 |
| **Max DD** | 最大回撤 | ⬇️ 絕對值越小越好 | 歷史上最大跌幅 |
| **Trades** | 交易次數 | 中庸 | 太多 = 摩擦成本高，太少 = 樣本不足 |
| **Win Rate** | 勝率 | ⬆️ 越高越好 | 賺錢的交易 / 總交易 |
| **Assigned** | 被指派次數 | — | 中性指標，被指派不代表虧錢 |
| **Premium $** | 總收到權利金 | ⬆️ 越高越好 | 累計收到的 premium |
| **Final $** | 期末權益 | ⬆️ 越高越好 | 假設起始 $30,000 後變成多少 |
    """)

    st.info("""
**🏆 選最佳策略的口訣：**

1. **Sort by CAGR**（按年化排序，最大的在最上面）
2. 確認 **Excess > 0**（真的比持有不動好）
3. 看 **Win Rate** 是否合理（>60% 較穩）
4. **Trades 不要太誇張**（>200 次可能傭金吃光獲利）
    """)

    # ============================================================
    # Section 6: IBKR 下單教學
    # ============================================================
    st.markdown("---")
    st.markdown('<a name="section-6"></a>', unsafe_allow_html=True)
    st.markdown("## 6️⃣ 從回測結果到實際下單（IBKR 教學）")

    st.markdown("""
**情境：** 回測顯示 AAPL 最佳策略是 `CC_Δ0.20_45D_expiry`，今天是 2026/5/19，AAPL = $297.84。

### Step 1：確認你有 100 股 AAPL

打開 TWS → Portfolio 確認有 100 股。

⚠️ **沒有 100 股不能賣 CC**（裸賣 Call 風險無限大，絕對禁止）

### Step 2：計算到期日

```
今天 2026/5/19 + 45 天 = 2026/7/3（週五）
```

美股選擇權幾乎都週五到期，找最接近 45 天的週五。

### Step 3：開啟 Option Chain

1. TWS 頂部搜尋 `AAPL`
2. 右鍵 AAPL → **Option Chain**（快捷鍵 `Ctrl+Alt+O`）
3. 選到期日 **2026-07-03**

### Step 4：找 Delta ≈ 0.20 的 Strike

1. 在 Call 那一邊找 **Delta** 欄
   - 沒看到？右鍵 column header → **Insert Column** → 勾 Delta
2. 從上往下找 **Delta 介於 0.18 ~ 0.22** 的那一行
3. 看那一行的 **Strike**（AAPL 約落在 $315-$320）

### Step 5：檢查流動性

| 指標 | 標準 |
|---|---|
| Volume（成交量）| > 50 |
| Open Interest（未平倉）| > 200 |
| Bid-Ask Spread | < $0.20 |

❌ Spread $0.50 以上不要碰，會被吃滑價

### Step 6：建立賣單

1. 右鍵那個 Call 的價格 → **Sell**
2. 確認設定：
   - Action: `SELL` ✅
   - Quantity: `1`（1 contract = 100 股）
   - Order Type: `LMT`（限價單，**不要用市價單**）
   - Limit Price: 設在 **Mid 略偏上**
     - 例如 Bid $3.50 / Ask $3.70 → 掛 $3.65
   - Time in Force: `DAY`

### Step 7：最後檢查 ✅

確認三個關鍵：
- [ ] 是 **Sell** 不是 Buy
- [ ] 是 **Call** 不是 Put
- [ ] Quantity 是 **1** 不是 10 或 100

按 **Transmit** 送出

### Step 8：成交後

你的部位：
- ✅ 100 股 AAPL（持續持有）
- ✅ 帳戶多 +$365 現金（premium）
- ⚠️ 義務：到期日 AAPL > $315 時，股票會被以 $315 收走

### Step 9：等到期日（不要中途平倉！）

`expiry` 規則 = **持有到 7/3，中途什麼都不做**。

到期日下午 3:50 EST 看結果：
- AAPL **< $315** → Call 失效，premium 完全你的 ✅
- AAPL **> $315** → 股票被以 $315 收走，加上 premium 還是賺 ✅
    """)

    # ============================================================
    # Section 7: FAQ
    # ============================================================
    st.markdown("---")
    st.markdown('<a name="section-7"></a>', unsafe_allow_html=True)
    st.markdown("## 7️⃣ 常見問題 FAQ")

    with st.expander("Q1: 為什麼回測 CAGR 跟 BH CAGR 差不多？"):
        st.markdown("""
**A:** 不同市況下 CC 表現不同：
- **牛市**：CC ≈ BH 或略輸（賺 premium 但錯失上漲）
- **熊市**：CC > BH（premium 緩衝下跌）
- **橫盤**：CC >> BH（CC 賺，BH 不賺）

CC 的價值在於「**降低波動**」而非「**最大化報酬**」。
        """)

    with st.expander("Q2: 為什麼有些策略 Win Rate 100% 還是輸 BH？"):
        st.markdown("""
**A:** Win Rate 高不代表報酬高。例如：
- 每筆都賺 $300 premium，但被指派 5 次 → 錯失 $5000 的股票上漲
- 總體還是輸 BH

**Win Rate** 只看「每筆 premium 有沒有賺」，不看「整體報酬」。
        """)

    with st.expander("Q3: 回測說 expiry 最好，但很多書推薦 50% 平倉？"):
        st.markdown("""
**A:** 兩種說法都對，看市況：
- **牛市持續上漲**：expiry 贏（懶人贏）
- **震盪/熊市**：50% 平倉贏（鎖定獲利 + 避開 Gamma）

回測的好處：**用實際數據驗證**，而非聽信任何「金科玉律」。
        """)

    with st.expander("Q3b: 回測年數該選 3 年還是 10 年？"):
        st.markdown("""
**A:** 看你想回答什麼問題：

| 問題 | 建議年數 |
|---|---|
| 「**目前市況下哪個策略最好？**」 | 1-3 年（反映近期） |
| 「**長期下來這個策略穩不穩？**」 | 5-10 年（含多種市況） |
| 「**這個標的適不適合 CC？**」 | 10 年（看完整循環） |

**重要的真相**：3 年回測在 2026 年很可能「**只看到牛市**」，
任何策略都會看起來很賺。建議**至少 5 年**，並對照不同期間結果。

**理想做法**：
1. 跑 10 年 → 看「長期表現」
2. 跑 3 年 → 看「最近趨勢」
3. 跑 2022 熊市 → 看「最壞情境」
4. 三個都好 → 才能放心用
        """)

    with st.expander("Q3c: 我該賣 7 天還是 45 天的選擇權？"):
        st.markdown("""
**A:** 看你的條件：

| 你的狀況 | 建議 DTE |
|---|---|
| 每週有空管理 | **7 天**（年化 premium 最高）|
| 上班族沒空盯盤 | **30-45 天**（每月看一次）|
| 想學最快累積經驗 | **14 天**（樣本多但管理頻率合理）|
| tastytrade 信徒 | **45 天**（經典）|
| 想盡量降低週轉 | **60 天**（少做事）|

**回測結果通常**：
- 7 天年化 premium 可能比 45 天**高**（因為 Theta 衰減快）
- 但 7 天**頻繁開倉**會吃更多滑價、手續費
- 7 天需要**更多時間管理**

**沒有絕對答案**，跑回測看你的標的哪個贏！我把短天期 (7/14) 加入預設選項就是這個原因。
        """)

    with st.expander("Q4: yfinance 的 Screener 顯示 bid/ask 是 0？"):
        st.markdown("""
**A:** 兩個可能：
1. **美股盤後**（台灣時間早上 5 點後）→ 等盤中再看
2. **流動性差的合約** → 換更熱門的 strike 或到期日
        """)

    with st.expander("Q5: 我可以用回測結果保證未來賺錢嗎？"):
        st.markdown("""
**A:** **絕對不能！** 三個重要前提：
- 回測用 Black-Scholes 合成 premium，與真實市場有差距
- 過去表現不代表未來表現
- 突發事件（財報、聯準會、地緣政治）無法回測

把回測當「**規則檢驗工具**」，不是「**水晶球**」。
        """)

    with st.expander("Q6: 我該避免在什麼時候賣 CC？"):
        st.markdown("""
**A:** 避開以下時機：
- **財報前一週**（IV 暴漲後暴跌，賣方常被坑）
- **重大 Fed 會議前**（突發波動）
- **IV Rank < 20**（premium 太便宜，不划算）
- **流動性差的 strike**（會被滑價吃掉）
        """)

    with st.expander("Q7: 我要怎麼選 symbol？只有 AAPL 嗎？"):
        st.markdown("""
**A:** 適合做 CC 的標的特徵：
- ✅ **高流動性**（ETF: SPY/QQQ/IWM；大型股: AAPL/MSFT/GOOGL）
- ✅ **適中波動**（太低沒 premium，太高風險大）
- ✅ **你願意持有**（被指派也不痛）
- ❌ 避免迷因股（GME 等）、低成交量股票
        """)

    # ============================================================
    # Section 8: 風險警告
    # ============================================================
    st.markdown("---")
    st.markdown('<a name="section-8"></a>', unsafe_allow_html=True)
    st.markdown("## 8️⃣ ⚠️ 風險警告")

    st.error("""
**請務必閱讀並理解以下風險：**

1. **本工具僅供分析參考，不構成投資建議**
2. **選擇權交易風險高**，可能在短時間內損失全部投入資金
3. **回測結果是模型估算**，與真實交易會有差距（滑價、稅務、傭金）
4. **過去表現不代表未來表現**，市況變化會讓最佳策略失效
5. **第一次操作務必用 Paper Trading**（模擬帳戶），不要直接用真錢
6. **不要把全部資金壓在 CC 上**，建議單一部位不超過總資金的 20-30%
7. **被指派時要有心理準備**，CC 不適合長期看好且不願賣出的核心持股
8. **Tax implications（稅務）**：選擇權交易在美國/台灣稅務處理複雜，請諮詢會計師
    """)

    st.info("""
**📚 建議延伸學習：**
- Tastytrade 的 Option 教學（免費 YouTube 系列）
- 《Options as a Strategic Investment》by Lawrence McMillan
- CBOE 的 Options Institute 免費課程
- r/options Reddit 社群（注意篩選資訊品質）
    """)

    st.markdown("---")
    st.caption("📖 操作手冊版本 v1.0  ·  最後更新 2026-05-19  ·  如有問題請聯絡作者")
