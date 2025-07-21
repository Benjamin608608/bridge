# Discord橋牌機器人 - Railway部署指南

## 📁 項目結構
```
discord-bridge-bot/
├── bot.py                 # 主程式
├── requirements.txt       # Python依賴
├── runtime.txt           # Python版本
├── .env.example          # 環境變數範例
├── .gitignore            # Git忽略文件
├── README.md             # 說明文檔
└── railway.json          # Railway配置（可選）
```

## 🚀 部署步驟

### 1. 準備GitHub倉庫
1. 在GitHub創建新倉庫 `discord-bridge-bot`
2. 將所有文件上傳到倉庫

### 2. 設置Discord機器人
1. 前往 [Discord Developer Portal](https://discord.com/developers/applications)
2. 創建新應用程式
3. 在Bot頁面創建機器人並複製Token
4. 在OAuth2 > URL Generator選擇：
   - Scope: `bot`, `applications.commands`
   - Bot Permissions: `Send Messages`, `Use Slash Commands`, `Read Message History`, `Manage Messages`

### 3. Railway部署
1. 前往 [Railway](https://railway.app)
2. 連接GitHub帳號
3. 選擇 "Deploy from GitHub repo"
4. 選擇您的 `discord-bridge-bot` 倉庫
5. 在Variables頁面設置環境變數：
   - `DISCORD_TOKEN`: 您的Discord機器人Token

### 4. 邀請機器人到伺服器
使用生成的OAuth2 URL邀請機器人到您的Discord伺服器

## 🔧 本地開發

1. 克隆倉庫：
```bash
git clone https://github.com/yourusername/discord-bridge-bot.git
cd discord-bridge-bot
```

2. 安裝依賴：
```bash
pip install -r requirements.txt
```

3. 設置環境變數：
```bash
cp .env.example .env
# 編輯.env文件，填入您的DISCORD_TOKEN
```

4. 運行機器人：
```bash
python bot.py
```

## 🎮 使用指令

- `/bridge` - 開始橋牌遊戲（雙人或四人）
  - 雙人：`/bridge 玩家1:@朋友`
  - 四人：`/bridge 玩家1:@朋友1 玩家2:@朋友2 玩家3:@朋友3`
- `/hand` - 查看手牌（僅自己可見）
- `/gameinfo` - 查看遊戲狀態
- `/quit` - 退出遊戲
- `/help` - 顯示使用說明
- 直接輸入牌面出牌：`♠️A`, `♥️K`, `♦️10`, `♣️J`

## 📝 遊戲規則

- 每位玩家26張牌
- 必須跟出相同花色（如果手中有）
- 花色等級：黑桃 > 紅心 > 方塊 > 梅花
- 牌值等級：A > K > Q > J > 10 > 9 > ... > 2

## 🔒 隱私保護

- 使用ephemeral訊息保護手牌隱私
- 出牌訊息自動刪除
- 所有遊戲狀態僅在記憶體中存儲

## ⚠️ 注意事項

- 機器人重啟會清除所有進行中的遊戲
- 建議在私人伺服器或專門的遊戲頻道使用
- 確保機器人有足夠的權限執行slash commands
