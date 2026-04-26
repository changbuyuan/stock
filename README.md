# 0050/0056 投資部位追蹤器（UI 版）

這是一個獨立於 `pqa` 的本地工具，位置在 `/home/pegaai/stock_portfolio_app`。

## 功能
- 即時抓取 0050 / 0056 股價（yfinance）
- 新增交易（支援用金額或股數）
- 自動計算總市值、總損益、報酬率
- 套用策略：每月投入、年終投入、加碼、再平衡、風控提醒

## 啟動
```bash
cd /home/pegaai/stock_portfolio_app
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

## 資料儲存
- 交易紀錄會寫入同目錄 `stock_portfolio_data.json`

## 備註
- yfinance 為近即時行情來源，可能有數分鐘延遲。
