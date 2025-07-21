#!/bin/bash
echo "🚀 Railway正在啟動Discord橋牌機器人..."
echo "📁 當前目錄內容："
ls -la
echo "🐍 Python版本："
python --version
echo "📦 安裝的包："
pip list
echo "🔑 環境變數檢查："
if [ -z "$DISCORD_TOKEN" ]; then
    echo "❌ DISCORD_TOKEN未設置"
else
    echo "✅ DISCORD_TOKEN已設置 (長度: ${#DISCORD_TOKEN})"
fi
echo "▶️ 啟動機器人..."
python bot.py
