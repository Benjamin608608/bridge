import discord
from discord.ext import commands
from discord import app_commands
import random
import asyncio
import os
from typing import Dict, List, Optional, Tuple

# Bot設置
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

class Card:
    """牌的類別"""
    SUITS = {'♠️': 'spades', '♥️': 'hearts', '♦️': 'diamonds', '♣️': 'clubs'}
    SUIT_ORDER = {'♠️': 4, '♥️': 3, '♦️': 2, '♣️': 1}  # 花色等級（黑桃最大）
    VALUES = ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A']
    VALUE_ORDER = {v: i for i, v in enumerate(VALUES)}
    
    def __init__(self, suit: str, value: str):
        self.suit = suit
        self.value = value
        self.suit_name = self.SUITS[suit]
    
    def __str__(self):
        return f"{self.suit}{self.value}"
    
    def __repr__(self):
        return str(self)
    
    def __eq__(self, other):
        return self.suit == other.suit and self.value == other.value
    
    def compare_value(self, other, trump_suit=None):
        """比較牌的大小，考慮王牌"""
        # 如果有王牌且其中一張是王牌
        if trump_suit:
            self_is_trump = self.suit == trump_suit
            other_is_trump = other.suit == trump_suit
            
            if self_is_trump and not other_is_trump:
                return 1
            elif not self_is_trump and other_is_trump:
                return -1
            elif self_is_trump and other_is_trump:
                return self.VALUE_ORDER[self.value] - self.VALUE_ORDER[other.value]
        
        # 同花色比較
        if self.suit == other.suit:
            return self.VALUE_ORDER[self.value] - self.VALUE_ORDER[other.value]
        
        # 不同花色且無王牌，無法比較
        return 0

class BridgeGame:
    """雙人橋牌遊戲類別"""
    
    def __init__(self, channel_id: int, player1: discord.Member, player2: discord.Member):
        self.channel_id = channel_id
        self.players = [player1, player2]
        self.hands = {player1.id: [], player2.id: []}
        self.current_player = 0
        self.trump_suit = None
        self.tricks = []  # 每一輪的牌
        self.current_trick = []
        self.scores = {player1.id: 0, player2.id: 0}
        self.game_phase = "bidding"  # bidding, playing, finished
        self.bids = []
        self.contract = None  # (level, suit, declarer)
        self.declarer = None
        self.lead_suit = None  # 本輪領出的花色
        
    def create_deck(self) -> List[Card]:
        """創建一副牌"""
        deck = []
        for suit in Card.SUITS.keys():
            for value in Card.VALUES:
                deck.append(Card(suit, value))
        return deck
    
    def deal_cards(self):
        """發牌，每人26張"""
        deck = self.create_deck()
        random.shuffle(deck)
        
        for i, card in enumerate(deck):
            player_id = self.players[i % 2].id
            self.hands[player_id].append(card)
        
        # 排序手牌
        for player_id in self.hands:
            self.hands[player_id].sort(key=lambda card: (
                -Card.SUIT_ORDER[card.suit], 
                -Card.VALUE_ORDER[card.value]
            ))
    
    def get_hand_string(self, player_id: int) -> str:
        """獲取玩家手牌的字符串表示"""
        hand = self.hands[player_id]
        suits_cards = {'♠️': [], '♥️': [], '♦️': [], '♣️': []}
        
        for card in hand:
            suits_cards[card.suit].append(card.value)
        
        result = "**您的手牌：**\n"
        for suit in ['♠️', '♥️', '♦️', '♣️']:
            if suits_cards[suit]:
                cards_str = ' '.join(suits_cards[suit])
                result += f"{suit}: {cards_str}\n"
        
        return result
    
    def parse_card_input(self, input_str: str) -> Optional[Card]:
        """解析玩家輸入的牌"""
        input_str = input_str.strip()
        
        # 嘗試找到花色符號
        suit = None
        for s in Card.SUITS.keys():
            if s in input_str:
                suit = s
                break
        
        if not suit:
            return None
        
        # 提取牌值
        value_str = input_str.replace(suit, '').strip()
        
        # 處理不同的輸入格式
        if value_str.upper() in ['J', 'Q', 'K', 'A']:
            value = value_str.upper()
        elif value_str in Card.VALUES:
            value = value_str
        else:
            return None
        
        return Card(suit, value)
    
    def can_play_card(self, player_id: int, card: Card) -> Tuple[bool, str]:
        """檢查玩家是否可以出這張牌"""
        if card not in self.hands[player_id]:
            return False, "您沒有這張牌！"
        
        # 如果是第一張牌，可以出任何牌
        if not self.current_trick:
            return True, ""
        
        # 如果不是第一張牌，需要跟牌
        lead_suit = self.current_trick[0][1].suit
        has_lead_suit = any(c.suit == lead_suit for c in self.hands[player_id])
        
        if card.suit != lead_suit and has_lead_suit:
            return False, f"您必須跟出 {lead_suit} 花色的牌！"
        
        return True, ""
    
    def play_card(self, player_id: int, card: Card) -> bool:
        """玩家出牌"""
        can_play, reason = self.can_play_card(player_id, card)
        if not can_play:
            return False
        
        # 移除手牌中的這張牌
        self.hands[player_id].remove(card)
        
        # 添加到當前trick
        player = next(p for p in self.players if p.id == player_id)
        self.current_trick.append((player, card))
        
        # 設置領出花色
        if len(self.current_trick) == 1:
            self.lead_suit = card.suit
        
        return True
    
    def evaluate_trick(self) -> discord.Member:
        """評估當前trick的勝者"""
        if len(self.current_trick) != 2:
            return None
        
        player1, card1 = self.current_trick[0]
        player2, card2 = self.current_trick[1]
        
        # 比較牌的大小
        comparison = card1.compare_value(card2, self.trump_suit)
        
        if comparison > 0:
            winner = player1
        elif comparison < 0:
            winner = player2
        else:
            # 如果是不同花色且沒有王牌，第一張牌獲勝
            winner = player1
        
        return winner
    
    def finish_trick(self) -> discord.Member:
        """結束當前trick並返回勝者"""
        winner = self.evaluate_trick()
        if winner:
            self.tricks.append((self.current_trick.copy(), winner))
            self.scores[winner.id] += 1
            self.current_trick = []
            self.lead_suit = None
            
            # 勝者成為下一輪的先手
            self.current_player = self.players.index(winner)
        
        return winner
    
    def is_game_finished(self) -> bool:
        """檢查遊戲是否結束"""
        return all(len(hand) == 0 for hand in self.hands.values())
    
    def get_winner(self) -> Optional[discord.Member]:
        """獲取遊戲勝者"""
        if not self.is_game_finished():
            return None
        
        max_score = max(self.scores.values())
        winner_id = next(pid for pid, score in self.scores.items() if score == max_score)
        return next(p for p in self.players if p.id == winner_id)

# 全局遊戲狀態
games: Dict[int, BridgeGame] = {}

@bot.event
async def on_ready():
    print(f'{bot.user} 橋牌機器人已上線！')
    try:
        synced = await bot.tree.sync()
        print(f'同步了 {len(synced)} 個slash commands')
    except Exception as e:
        print(f'同步slash commands失敗: {e}')

@bot.command(name='bridge')
async def start_bridge(ctx, opponent: discord.Member = None):
    """開始雙人橋牌遊戲"""
    if opponent is None:
        await ctx.send("請標記一位玩家來開始遊戲！例如：`!bridge @玩家名`")
        return
    
    if opponent.bot:
        await ctx.send("不能與機器人遊戲！")
        return
    
    if opponent.id == ctx.author.id:
        await ctx.send("不能與自己遊戲！")
        return
    
    if ctx.channel.id in games:
        await ctx.send("這個頻道已經有遊戲在進行中！")
        return
    
    # 創建新遊戲
    game = BridgeGame(ctx.channel.id, ctx.author, opponent)
    game.deal_cards()
    games[ctx.channel.id] = game
    
    # 發送遊戲開始訊息
    embed = discord.Embed(
        title="🃏 雙人橋牌遊戲開始！",
        description=f"{ctx.author.mention} vs {opponent.mention}",
        color=0x00ff00
    )
    embed.add_field(
        name="遊戲說明",
        value="• 使用 `/hand` 查看手牌（僅自己可見）\n• 出牌格式：直接輸入牌面，如 `♠️A` 或 `♥️K`\n• 必須跟出相同花色（如果有的話）",
        inline=False
    )
    
    await ctx.send(embed=embed)
    
    # 通知玩家使用slash command查看手牌
    info_msg = await ctx.send("💡 **提示：使用 `/hand` 指令查看您的手牌（只有您能看到）**", delete_after=10)
    
    # 宣布第一位玩家
    current_player = game.players[game.current_player]
    await ctx.send(f"輪到 {current_player.mention} 出牌！")

@bot.tree.command(name='hand', description='查看您的手牌（僅您可見）')
async def slash_hand(interaction: discord.Interaction):
    """顯示玩家手牌（ephemeral）"""
    game = games.get(interaction.channel.id)
    if not game:
        await interaction.response.send_message("目前沒有進行中的遊戲！", ephemeral=True)
        return
    
    if interaction.user.id not in game.hands:
        await interaction.response.send_message("您不在這場遊戲中！", ephemeral=True)
        return
    
    hand_str = game.get_hand_string(interaction.user.id)
    
    embed = discord.Embed(title="您的手牌", description=hand_str, color=0x0099ff)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.command(name='hand')
async def show_hand(ctx):
    """顯示玩家手牌（舊版指令，建議使用 /hand）"""
    await ctx.send("請使用 `/hand` 指令來查看手牌（只有您能看到）！", delete_after=5)
    try:
        await ctx.message.delete()
    except:
        pass

@bot.event
async def on_message(message):
    """處理玩家出牌"""
    if message.author.bot:
        return
    
    # 處理指令
    await bot.process_commands(message)
    
    # 檢查是否是遊戲頻道
    game = games.get(message.channel.id)
    if not game or game.game_phase != "playing":
        return
    
    # 檢查是否是遊戲中的玩家
    if message.author.id not in game.hands:
        return
    
    # 檢查是否輪到這位玩家
    current_player = game.players[game.current_player]
    if message.author.id != current_player.id:
        temp_msg = await message.channel.send(f"{message.author.mention} 還沒輪到您出牌！", delete_after=3)
        return
    
    # 嘗試解析出牌
    card = game.parse_card_input(message.content)
    if not card:
        return  # 不是有效的出牌格式，忽略
    
    # 刪除玩家的出牌訊息以保持隱私
    try:
        await message.delete()
    except:
        pass
    
    # 嘗試出牌
    if not game.play_card(message.author.id, card):
        can_play, reason = game.can_play_card(message.author.id, card)
        await message.channel.send(f"{message.author.mention} {reason}", delete_after=5)
        return
    
    # 宣布出牌
    embed = discord.Embed(
        title="出牌",
        description=f"{message.author.mention} 出了 {card}",
        color=0xffd700
    )
    
    if len(game.current_trick) == 1:
        embed.add_field(name="當前trick", value=f"{card}", inline=False)
        
        # 切換到下一位玩家
        game.current_player = 1 - game.current_player
        next_player = game.players[game.current_player]
        embed.add_field(name="下一位", value=f"{next_player.mention} 的回合", inline=False)
        
    elif len(game.current_trick) == 2:
        trick_str = f"{game.current_trick[0][1]} vs {game.current_trick[1][1]}"
        embed.add_field(name="當前trick", value=trick_str, inline=False)
        
        # 評估trick勝者
        winner = game.finish_trick()
        embed.add_field(name="Trick勝者", value=f"{winner.mention} 獲勝！", inline=False)
        
        # 檢查遊戲是否結束
        if game.is_game_finished():
            game_winner = game.get_winner()
            final_embed = discord.Embed(
                title="🎉 遊戲結束！",
                color=0xff6b6b
            )
            final_embed.add_field(
                name="最終結果", 
                value=f"**勝者：{game_winner.mention}**\n\n得分：\n{game.players[0].mention}: {game.scores[game.players[0].id]}\n{game.players[1].mention}: {game.scores[game.players[1].id]}", 
                inline=False
            )
            
            await message.channel.send(embed=embed)
            await message.channel.send(embed=final_embed)
            
            # 清理遊戲
            del games[message.channel.id]
            return
        else:
            # 設置下一輪的先手（trick勝者）
            game.current_player = game.players.index(winner)
            next_player = game.players[game.current_player]
            embed.add_field(name="下一輪先手", value=f"{next_player.mention} 先出牌", inline=False)
    
    await message.channel.send(embed=embed)

@bot.command(name='gameinfo')
async def game_info(ctx):
    """顯示遊戲狀態"""
    game = games.get(ctx.channel.id)
    if not game:
        await ctx.send("目前沒有進行中的遊戲！")
        return
    
    embed = discord.Embed(title="🃏 遊戲狀態", color=0x00ff00)
    
    # 顯示玩家
    players_str = f"{game.players[0].mention} vs {game.players[1].mention}"
    embed.add_field(name="玩家", value=players_str, inline=False)
    
    # 顯示分數
    score_str = f"{game.players[0].mention}: {game.scores[game.players[0].id]}\n{game.players[1].mention}: {game.scores[game.players[1].id]}"
    embed.add_field(name="當前得分", value=score_str, inline=True)
    
    # 顯示當前回合
    current_player = game.players[game.current_player]
    embed.add_field(name="當前回合", value=current_player.mention, inline=True)
    
    # 顯示當前trick
    if game.current_trick:
        trick_str = " vs ".join([str(card) for _, card in game.current_trick])
        embed.add_field(name="當前Trick", value=trick_str, inline=False)
    
    await ctx.send(embed=embed)

@bot.command(name='quit')
async def quit_game(ctx):
    """退出遊戲"""
    game = games.get(ctx.channel.id)
    if not game:
        await ctx.send("目前沒有進行中的遊戲！")
        return
    
    if ctx.author.id not in [p.id for p in game.players]:
        await ctx.send("您不在這場遊戲中！")
        return
    
    del games[ctx.channel.id]
    await ctx.send(f"{ctx.author.mention} 退出了遊戲。遊戲已結束。")

# 啟動遊戲時自動進入遊戲階段
@bot.event
async def on_command_completion(ctx):
    if ctx.command.name == 'bridge':
        game = games.get(ctx.channel.id)
        if game:
            game.game_phase = "playing"

# 運行機器人
if __name__ == "__main__":
    # 從環境變數獲取Token
    token = os.getenv('DISCORD_TOKEN')
    if not token:
        print("錯誤：請設置DISCORD_TOKEN環境變數")
        print("在Railway中設置環境變數，或在本地創建.env文件")
        exit(1)
    
    print("正在啟動Discord橋牌機器人...")
    bot.run(token)
