# 重置 Therapy

[English](README.md) · **繁體中文**

給活在 AI 額度上限裡的人的視覺化療癒裝置。

**專案介紹頁：** https://teddashh.github.io/reset-therapy/?lang=zh-TW

**線上玩：** https://teddashh.github.io/reset-therapy/play/?lang=zh

**全站共用次數版：** https://www.ted-h.com/zh_TW/reset-therapy（同一個玩具，掛上選配的統計模組）

四個精心仿造的用量面板（ChatGPT / Codex、Claude、Gemini、Grok）就在你眼前即時燃燒額度。數字一直爬，重置日永遠等不到。在這裡不用等星期一：按下按鈕，被鎖鏈綁住的黃金龍掙脫，額度條回滿，世界和平。

![Reset Therapy 桌面版畫面，還沒重置](docs/screenshot-desktop.png)

## 功能

- 仿照四家用量頁做的設定面板。還沒重置的那幾家，數字每 0.9 秒往上爬一點，爬到快滿才停。
- 每家一顆重置鈕（直接點龍也可以），再加一顆大大的「全部重置吧」。在這裡重置永遠有效，跟現實不一樣。
- 四條被鎖鏈綁住的黃金龍。重置之後鎖鏈噹啷斷開、彩帶噴出，重獲自由的龍會用漫畫對話框慶祝。
- 四家都重置之後，按「哭啊, 又全部燒光了」就全部鎖回去。
- 第一次重置後會出現本週療癒排行榜，四家的欄位照本週名次排列。
- 排行榜的數字是用固定公式、依目前日期與時間算出來的假基準值，再加上真實的重置次數：連得到選配 API 時用全站的次數，連不到就用這個瀏覽器的次數。
- 「本週」對每個訪客都一樣，不管人在哪裡：以台北時間（UTC+8）週一 00:00 到週日 23:59 為一週，跟 API 計算的週完全一致。
- 你自己的療癒次數存在 localStorage。
- 雙語：English 與台灣正體，右上角可以切換。
- 支援 prefers-reduced-motion：系統開啟「減少動態效果」時，不播動畫、彩帶和閃屏。
- 不用建置、沒有相依套件：只有一個自包含的 `index.html`（約 558 KB，美術以 data URI 內嵌，字型來自 Google Fonts）。

## 執行

線上玩：<https://teddashh.github.io/reset-therapy/play/?lang=zh>（英文版：<https://teddashh.github.io/reset-therapy/play/>）。

想自己跑一份，用瀏覽器打開 `index.html` 就是全部了。任何靜態主機都能放。語言用 `?lang=zh` / `?lang=en`，或右上角的切換按鈕。

沒有後端也完全能玩：只是改用基準值加上你本機的次數。放在 GitHub Pages 上就是這種情況。[ted-h.com 上的版本](https://www.ted-h.com/zh_TW/reset-therapy)掛著下面的統計模組，排行榜會累計所有訪客的次數。

## 選配後端：全站共用的次數

為了讓每個訪客看到同一份「本週人類療癒了 Claude 幾次」，頁面會呼叫同網域、固定路徑下的兩個端點（拿不到就自動降級）：

```
GET  /reset-therapy/api/stats
     -> {"weekIdx": N,
         "week": {"claude": 0, "codex": 0, "gemini": 0, "grok": 0},
         "all":  {"claude": 0, "codex": 0, "gemini": 0, "grok": 0}}

POST /reset-therapy/api/heal
     {"providers": ["claude", "gemini"]}
     -> fresh stats payload (each listed provider +1 this week)
     -> 400 {"error": "..."} when the body is malformed
     -> 429 {"error": "rate limited"} plus Retry-After when over the limit
```

`server/reset_therapy_stats/` 是參考實作：一個 Odoo 19 模組，把次數存在 Odoo 資料目錄裡的一個 SQLite 檔（每家每週一列，週一起算，固定用 UTC+8 台北時間）。兩個端點都是公開的，不需要驗證。用任何框架寫個小伺服器，都能實作同樣的介面。

heal 端點有自己的防護：

- **格式不對就回 400。** 內容必須是不超過 4 KB 的 UTF-8 JSON：一個物件，其中 `providers` 是字串清單，而且至少要有一個認得的服務名稱。其他情況（JSON 壞掉、結構不對、內容太大）一律回 400，附上一段簡短訊息，例如 `{"error": "bad json"}`。不認得的名稱會被忽略，同一家列兩次也只算一次，所以一個請求每家最多 +1（合計最多 4）。
- **超過速率限制就回 429。** 每個用戶端在任何 60 秒內，最多有 30 個 heal 請求會被接受。超過就回 429 `{"error": "rate limited"}`，附上以秒為單位的 `Retry-After` 標頭，而且什麼都不會計入。被拒絕的請求不算在這 30 次裡。頁面遇到被拒絕的 heal 會直接略過。
- **怎麼認定用戶端。** 有 `CF-Connecting-IP` 標頭就用它，沒有就用 `X-Forwarded-For` 的第一個位址，再沒有就用連線本身的位址。IPv6 位址以 /64 為一組。這些標頭會直接採信，所以伺服器只能透過 Cloudflare 或你的反向代理對外開放。
- **所有 worker 共用。** 速率限制的狀態存在同一個 SQLite 檔裡（用戶端位址的雜湊值加上時間戳記，超過一分鐘的紀錄會在下一次 heal 時刪掉），所以 Odoo 開多個 worker 行程時，限制一樣有效。

stats 端點沒有限制。模組的邏輯寫在純 Python 的 `core.py`，單元測試不需要 Odoo：`python3 -m unittest discover -s server/tests -v`（每個 pull request 也會自動跑）。

## 美術流程

四條龍是 gpt-image-2 生成的圖，後製成 600x750 的 WebP 再內嵌進頁面：

```
cd art
OPENAI_API_KEY=sk-... python3 gen_dragons.py   # 4 張 PNG（1024x1536）存到 art/out/
python3 drg_post.py                            # 裁切、轉 WebP、寫進 ../index.html
```

`drg_post.py` 需要 Pillow。它會產生 `art/drg_*.webp`，再把 `../index.html` 裡的 `__DRG_CODEX__`、`__DRG_CLAUDE__`、`__DRG_GEMINI__`、`__DRG_GROK__` 預留標記換成圖片。repo 裡的 `index.html` 已經內嵌好圖，沒有這些標記了，所以要重畫的話得自備範本。

## GitHub Pages 怎麼發佈

`.github/workflows/pages.yml` 會把 `site/`（專案介紹頁）發佈到 <https://teddashh.github.io/reset-therapy/>，並把 `index.html` 複製成 `play/index.html`，所以玩具在 <https://teddashh.github.io/reset-therapy/play/>。`main` 分支上的 `site/`、`index.html` 或 workflow 有變動時就會執行。

## 檔案

```
index.html                    玩具本體，自包含
site/                         專案介紹頁（GitHub Pages）
.github/workflows/pages.yml   部署 site/，並把玩具放在 play/
.github/workflows/tests.yml   執行單元測試
server/reset_therapy_stats/   選配的 Odoo 19 統計模組（LGPL-3）
server/tests/                 模組核心的單元測試（純 Python）
art/                          龍的美術腳本與四張 WebP
docs/                         截圖
```

## 免責聲明

這是惡搞玩具。面板外觀是為了笑點而模仿真實產品，本專案與 OpenAI、Anthropic、Google、xAI 都沒有關係。這些數字都是演出來的：額度面板是動畫，排行榜是假的基準值加上訪客真實按下的次數。不會讀取任何真實帳號，在這裡按重置也很遺憾地不會重置任何真實額度。

## 授權

頁面與腳本採用 MIT 授權（見 `LICENSE`）。`server/` 底下的選配 Odoo 模組依 Odoo 慣例採用 LGPL-3（寫在它的 manifest 裡）。
