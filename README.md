# ScienceNet Article Bot

將科學網博客的「科普集錦」與「觀點評述」文章推送到原有 Telegram 頻道。非科學網官方服務。

GitHub Actions 每小時第 43 分鐘排程執行（UTC，GitHub 可能延遲）。沿用既有 `BOT_TOKEN`、`CHAT_ID` repository secrets 與 `previous_articles.json` 推送紀錄，無需重新設定機器人。

## 運行與驗證

需要 Python 3.13。Actions 固定使用 Ubuntu 24.04、Python 3.13，依賴及其間接依賴鎖定在 `requirements.txt`。

```sh
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python -m sciencenet_bot --dry-run
```

`--dry-run` 只抓取及預覽文章，不發訊息、不寫推送紀錄，也不需要 Telegram secrets。設定環境變數 `BOT_TOKEN`、`CHAT_ID` 後，加上 `--verify-telegram` 會以 `getMe`、`getChat`、`getChatMember` 檢查憑據和發文權限；單獨使用這個旗標也只會驗證。驗證模式的 API 客戶端會拒絕任何發送或修改操作。

```sh
python -m sciencenet_bot --dry-run --verify-telegram
```

在 Actions 頁面選 **Run workflow → mode: verify** 也是同樣的只讀檢查。**程式碼 push 只執行測試及只讀驗證**，不會向訂閱者發測試訊息。Pull request 只跑離線測試，不使用 secrets。

正常排程會推送真正尚未發送的文章；手動選 `mode: send` 或執行以下命令也會真的發文：

```sh
python -m sciencenet_bot --max-messages 5
```

每次最多發 5 篇，按照文章 ID 由舊到新排列，間隔至少 1.1 秒。積壓文章留待後續排程處理，避免恢復時大量刷屏。原來的 `python worm.py` 入口仍可使用。

## 推送紀錄與錯誤處理

- `previous_articles.json` 沿用原來的字串 ID 清單，保留完整歷史，不要刪除或清空；缺失、損壞或空白紀錄會停止執行，防止大量重播。
- 只將 Telegram 明確確認送達的文章寫入紀錄，每成功一篇即原子儲存。中途發送失敗會讓 Action 失敗，並提交此前已成功的紀錄；失敗文章會留待後續執行。
- 同一文章出現在兩個欄目時只發一次。爬蟲會往後翻頁，直到整頁皆為已推送文章，最多每欄目 20 頁；超出限制會明確失敗。這依賴科學網按發表時間排列的列表，並非完整歷史封存爬蟲。
- 來源請求有連線/讀取超時，並對暫時性 HTTP 錯誤重試。找不到文章表格、資料列或連結異常會報錯，不會偽裝成「沒有新文章」。
- Telegram 遇到明確的限流回應會遵守 `retry_after`；網路超時不會立即重送，因為 Telegram 可能已經收到訊息。Telegram API 沒有此用途的冪等鍵，因此網路超時或送達後儲存失敗仍可能讓下一次執行重送一篇。
- 工作流序列執行，不取消正在發文的任務。紀錄提交不觸發新一輪推送，Git push 失敗會明確報錯。Token 和含 Token 的請求 URL 不寫入日誌。

## 專案結構

```text
sciencenet_bot/
  crawler.py     # 來源抓取、GBK 中文解析、分頁與去重
  models.py      # 文章資料與原有訊息格式
  telegram.py    # Telegram API、只讀權限檢查及限流處理
  state.py       # 歷史紀錄校驗與原子儲存
  cli.py         # 預覽、限量推送及逐篇存檔
tests/           # 離線測試，全部使用模擬 Telegram
.github/workflows/crawler.yml
previous_articles.json
requirements.in # 直接依賴
requirements.txt # 完整鎖定依賴；以 uv pip compile 更新
worm.py          # 舊命令相容入口
```

## 2026-11 修復原因

最後一次成功排程為 2026-11-09 02:57 UTC。舊工作流使用 `ubuntu-latest` 與 Python 3.9；runner 升級到 Ubuntu 26.04 後，`actions/setup-python@v3` 報 `Version 3.9 with arch x64 not found`，爬蟲尚未啟動即失敗。修復改用受支援的 Python 及固定 OS，升級官方 Actions，並處理原程式發送失敗卻仍標記已推送的問題。
