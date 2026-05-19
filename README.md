# Covered Call System — Cloud Edition 🌐

精簡版的 Covered Call 工具，可直接部署到 **Streamlit Community Cloud**（免費）。

**包含功能：**
- 🧪 多策略回測（CC / CSP / Wheel / PMCC）
- 🔍 CC 機會篩選（用 yfinance 免費資料）
- 🔐 密碼登入保護（多人共用安全）

**不包含：**
- ❌ IBKR 連接（需本機 TWS，雲端跑不了）

---

## 🚀 5 分鐘部署到 Streamlit Cloud

### Step 1：準備 GitHub 帳號

如果還沒有：
1. 到 https://github.com/signup 註冊（免費）
2. 驗證信箱

### Step 2：在 GitHub 建立 Repository

1. 登入 GitHub → 右上角 `+` → **New repository**
2. 設定：
   - Repository name: `cc-system`（或你喜歡的名字）
   - **Private**（建議勾私密，避免別人看到你的 source code）
   - 不要勾選 Add README / Add .gitignore（我們本地已經有了）
3. 按 **Create repository**

### Step 3：上傳檔案到 GitHub

**方法 A：用網頁拖曳上傳（最簡單）**

1. 在新建的 repo 頁面點 **uploading an existing file**
2. 把 `cc_cloud` 資料夾**內**的所有檔案（不要連資料夾本身）拖到上傳區
   - ⚠️ 注意：`.streamlit/secrets.toml.example` 也要傳，但**不要**有 `secrets.toml`
3. 下方填寫 "Initial commit"
4. 按 **Commit changes**

**方法 B：用 Git 指令（如果你會）**

```bash
cd cc_cloud
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/你的帳號/cc-system.git
git push -u origin main
```

### Step 4：部署到 Streamlit Cloud

1. 開 https://share.streamlit.io
2. 點 **Continue with GitHub** → 授權
3. 點 **Create app** → **Deploy a public app from GitHub**
4. 填寫：
   - Repository: `你的帳號/cc-system`
   - Branch: `main`
   - Main file path: `app.py`
   - App URL（最下方）：自己取個名字，例如 `my-cc-system`
     - 你的網址會是 `https://my-cc-system.streamlit.app`
5. **先別按 Deploy**！先點下方 **Advanced settings**

### Step 5：設定密碼（重要！）

在 Advanced settings 的 **Secrets** 框框內貼上：

```toml
passwords = ["你的密碼", "朋友1密碼", "朋友2密碼"]
```

⚠️ **密碼建議：**
- 至少 12 字元
- 大小寫 + 數字 + 符號混合
- 不要用你其他網站用過的密碼
- 範例（不要直接用這個）：`Wh3el!Trading2025`

設定好後按 **Save** → **Deploy!**

### Step 6：等待部署完成

- 第一次部署需要 2-5 分鐘（要安裝 numpy、pandas、yfinance 等套件）
- 部署過程會顯示 log，如果有錯誤可以看訊息
- 成功後會自動跳到你的 app

### Step 7：測試

1. 打開你的 app URL（例如 `https://my-cc-system.streamlit.app`）
2. 看到密碼登入畫面 → 輸入你剛剛設的密碼
3. 進入主畫面 → 試試回測（先用 SPY 一年）

---

## 🔐 之後加新朋友怎麼辦？

1. 到 https://share.streamlit.io
2. 點你的 app → 右上角三點 → **Settings**
3. 進到 **Secrets** 頁
4. 在 passwords 加入新密碼：
   ```toml
   passwords = ["你的密碼", "朋友1密碼", "朋友2密碼", "新朋友密碼"]
   ```
5. **Save** → app 會自動重啟

---

## ✏️ 修改程式碼後怎麼更新？

只要 push 到 GitHub，Streamlit Cloud 會自動偵測並重新部署：

**網頁上修改：**
1. GitHub repo → 找到要改的檔案 → 點鉛筆 ✏️
2. 改完按下面 **Commit changes**
3. 等 1-2 分鐘 → app 自動重新部署

**用 Git 指令：**
```bash
git add .
git commit -m "更新某某功能"
git push
```

---

## 💰 Streamlit Cloud 的限制

免費版的限制（個人專案綽綽有餘）：
- ✅ 1 個 private app（再多就要付費）
- ✅ 1GB RAM
- ✅ 不會休眠（個人專案層級）
- ⚠️ Repository **必須是 GitHub**
- ⚠️ 如果你 repo 是 public，source code 會公開（但 secrets 不會）

---

## 🐛 常見問題

**Q: 部署失敗，log 顯示 ModuleNotFoundError**

A: 檢查 `requirements.txt` 是否有上傳，且模組名稱拼對。可以到 Streamlit Cloud → app → **Manage** → **Reboot app**。

**Q: app 顯示「⚠️ 此 app 部署在雲端但未設定密碼」**

A: Secrets 沒設好。到 app settings → Secrets，貼上 `passwords = ["..."]` 後 Save。

**Q: 回測按下去後跑了很久卡住**

A: yfinance 第一次抓資料較慢，特別是多標的 × 多年期間。先用 1 個標的 + 1 年試。如果還是卡，可能是 Streamlit Cloud 的 RAM 限制——降低策略數量。

**Q: Screener 顯示 0 candidates**

A: yfinance 的 IV 可能有空值或極端值。試試把 Min Volume 降到 0、Max DTE 拉大、放寬 Delta 範圍。

**Q: 朋友的密碼也想自訂？**

A: 直接把所有密碼都放在 secrets 的 passwords 陣列即可。誰用哪個密碼登入就誰負責記。

**Q: 想加 SSL/HTTPS？**

A: Streamlit Cloud 預設就有 HTTPS（`https://xxx.streamlit.app`），不用自己設定。

**Q: 想用自訂域名（例如 cc.yourname.com）？**

A: 免費版不支援。要付費升級到 Teams 方案（$250/月 起，不划算）。可以用 Cloudflare 做免費的 redirect/CNAME。

---

## 📁 專案結構

```
cc_cloud/
├── app.py                          # 主程式
├── requirements.txt                # Python 套件
├── .gitignore                      # 排除敏感檔案
├── .streamlit/
│   ├── config.toml                 # 主題設定
│   └── secrets.toml.example        # 密碼範例（真的密碼放 Streamlit Cloud）
├── core/                           # 回測引擎
│   ├── pricing.py
│   ├── pricing_extended.py
│   ├── data_loader.py
│   ├── screener.py
│   ├── backtest.py
│   ├── backtest_csp_wheel.py
│   └── backtest_pmcc.py
├── ui/
│   ├── auth.py                     # 密碼登入
│   ├── backtest_page.py            # 回測 UI
│   └── screener_page.py            # 篩選 UI
└── config/
    └── settings.py
```

---

## 🔄 之後想加 IBKR 怎麼辦？

雲端版本**沒辦法**加 IBKR（前面解釋過了）。

要連 IBKR 的兩個選項：

1. **本機跑完整版**：用之前給你的 `cc_system.zip`，在自己電腦跑，朋友也各自跑
2. **租 VPS**：$5/月 租一台 Linux 伺服器，裝 IB Gateway + 完整版 app

要的話再跟我說，我幫你準備 VPS 部署腳本。

---

## ⚠️ 重要免責聲明

- 本工具僅供分析參考，**不構成投資建議**
- 選擇權交易風險高，可能損失全部投入資金
- 回測結果是模型估算，**不代表未來真實表現**
- 實際交易要考慮稅務、傭金、滑價等本工具未模擬的因素
