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
    """橋牌遊戲類別（支援雙人/四人）"""
    
    def __init__(self, channel_id: int, players: List[discord.Member]):
        self.channel_id = channel_id
        self.players = players
        self.player_count = len(players)
        self.hands = {player.id: [] for player in players}
        self.current_player = 0
        self.trump_suit = None
        self.tricks = []  # 每一輪的牌
        self.current_trick = []
        self.scores = {player.id: 0 for player in players}
        self.game_phase = "bidding"  # bidding, playing, finished
        self.bids = []  # 所有叫牌記錄
        self.contract = None  # (level, suit, declarer)
        self.declarer = None
        self.lead_suit = None  # 本輪領出的花色
        self.bidding_player = 0  # 當前叫牌的玩家
        self.pass_count = 0  # 連續pass的次數
        
        # 四人橋牌特有屬性
        if self.player_count == 4:
            self.partnerships = {
                players[0].id: players[2].id,  # 南北搭檔
                players[1].id: players[3].id,  # 東西搭檔
                players[2].id: players[0].id,
                players[3].id: players[1].id
            }
            self.team_scores = {
                "NS": 0,  # 南北隊
                "EW": 0   # 東西隊
            }
            self.positions = {
                players[0].id: "南 (S)",
                players[1].id: "西 (W)", 
                players[2].id: "北 (N)",
                players[3].id: "東 (E)"
            }
        else:
            self.partnerships = None
            self.team_scores = None
            self.positions = None
        
    def create_deck(self) -> List[Card]:
        """創建一副牌"""
        deck = []
        for suit in Card.SUITS.keys():
            for value in Card.VALUES:
                deck.append(Card(suit, value))
        return deck
    
    def deal_cards(self):
        """發牌，雙人每人26張，四人每人13張"""
        deck = self.create_deck()
        random.shuffle(deck)
        
        if self.player_count == 2:
            # 雙人橋牌：每人26張
            for i, card in enumerate(deck):
                player_id = self.players[i % 2].id
                self.hands[player_id].append(card)
        else:
            # 四人橋牌：每人13張
            for i, card in enumerate(deck):
                player_id = self.players[i % 4].id
                self.hands[player_id].append(card)
        
        # 排序手牌
        for player_id in self.hands:
            self.hands[player_id].sort(key=lambda card: (
                -Card.SUIT_ORDER[card.suit], 
                -Card.VALUE_ORDER[card.value]
            ))
    
    def parse_bid(self, bid_str: str) -> Optional[Tuple[int, str]]:
        """解析叫牌輸入"""
        bid_str = bid_str.strip().upper()
        
        # Pass
        if bid_str in ['PASS', 'P', '過牌', '不叫']:
            return None
        
        # Double/Redouble (簡化版暫不實作)
        if bid_str in ['DOUBLE', 'DBL', 'X', 'REDOUBLE', 'RDBL', 'XX']:
            return None
        
        # 正常叫牌 (如 "1♠️", "2NT", "3C" 等)
        if len(bid_str) >= 2:
            try:
                level = int(bid_str[0])
                if level < 1 or level > 7:
                    return None
                
                suit_str = bid_str[1:].strip()
                
                # 花色對照
                suit_mapping = {
                    '♣': '♣️', 'C': '♣️', 'CLUBS': '♣️', '梅花': '♣️',
                    '♦': '♦️', 'D': '♦️', 'DIAMONDS': '♦️', '方塊': '♦️', 
                    '♥': '♥️', 'H': '♥️', 'HEARTS': '♥️', '紅心': '♥️',
                    '♠': '♠️', 'S': '♠️', 'SPADES': '♠️', '黑桃': '♠️',
                    'NT': 'NT', 'N': 'NT', 'NOTRUMP': 'NT', '無王': 'NT'
                }
                
                for key, value in suit_mapping.items():
                    if suit_str.startswith(key):
                        return (level, value)
                        
            except ValueError:
                pass
                
        return None
    
    def is_valid_bid(self, level: int, suit: str) -> bool:
        """檢查叫牌是否有效（必須比上一個叫牌更高）"""
        if not self.bids:
            return True
            
        # 找到最後一個非pass的叫牌
        last_valid_bid = None
        for bid in reversed(self.bids):
            if bid[1] is not None:  # 不是pass
                last_valid_bid = bid[1]
                break
        
        if last_valid_bid is None:
            return True
        
        last_level, last_suit = last_valid_bid
        
        # 花色等級：♣️ < ♦️ < ♥️ < ♠️ < NT
        suit_order = {'♣️': 1, '♦️': 2, '♥️': 3, '♠️': 4, 'NT': 5}
        
        if level > last_level:
            return True
        elif level == last_level:
            return suit_order.get(suit, 0) > suit_order.get(last_suit, 0)
        else:
            return False
    
    def make_bid(self, player_id: int, bid_str: str) -> Tuple[bool, str]:
        """玩家叫牌"""
        parsed_bid = self.parse_bid(bid_str)
        
        if bid_str.strip().upper() in ['PASS', 'P', '過牌', '不叫']:
            # Pass
            player = next(p for p in self.players if p.id == player_id)
            self.bids.append((player, None))
            self.pass_count += 1
            return True, "Pass"
        else:
            if parsed_bid is None:
                return False, "無效的叫牌格式！請使用如：1♠️, 2NT, 3♥️ 或 pass"
            
            level, suit = parsed_bid
            if not self.is_valid_bid(level, suit):
                return False, "叫牌必須比之前的叫牌更高！"
            
            player = next(p for p in self.players if p.id == player_id)
            self.bids.append((player, (level, suit)))
            self.pass_count = 0
            return True, f"{level}{suit}"
    
    def check_bidding_end(self) -> bool:
        """檢查叫牌是否結束"""
        if len(self.bids) < self.player_count:
            return False
        
        # 如果連續3個（雙人）或4個（四人）pass，或者連續3個pass且有人叫牌
        if self.player_count == 2:
            # 雙人橋牌：兩人都pass一輪後結束
            return self.pass_count >= 2
        else:
            # 四人橋牌：連續3個pass結束叫牌
            return self.pass_count >= 3
    
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
        if len(self.current_trick) != self.player_count:
            return None
        
        winning_player, winning_card = self.current_trick[0]
        
        # 比較所有牌找出最大的
        for player, card in self.current_trick[1:]:
            comparison = card.compare_value(winning_card, self.trump_suit)
            if comparison > 0:
                winning_player, winning_card = player, card
            elif comparison == 0 and card.suit == self.lead_suit and winning_card.suit != self.lead_suit:
                # 如果都不是王牌，跟牌者勝過非跟牌者
                winning_player, winning_card = player, card
        
        return winning_player
    
    def finish_trick(self) -> discord.Member:
        """結束當前trick並返回勝者"""
        winner = self.evaluate_trick()
        if winner:
            self.tricks.append((self.current_trick.copy(), winner))
            
            # 更新分數
            if self.player_count == 2:
                self.scores[winner.id] += 1
            else:
                # 四人橋牌：更新隊伍分數
                if winner.id in [self.players[0].id, self.players[2].id]:  # 南北隊
                    self.team_scores["NS"] += 1
                else:  # 東西隊
                    self.team_scores["EW"] += 1
                # 個人分數也要記錄
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
        
        if self.player_count == 2:
            # 雙人橋牌：個人最高分
            max_score = max(self.scores.values())
            winner_id = next(pid for pid, score in self.scores.items() if score == max_score)
            return next(p for p in self.players if p.id == winner_id)
        else:
            # 四人橋牌：隊伍最高分
            if self.team_scores["NS"] > self.team_scores["EW"]:
                return "NS"  # 南北隊勝利
            elif self.team_scores["EW"] > self.team_scores["NS"]:
                return "EW"  # 東西隊勝利
            else:
                return "平手"

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

@bot.tree.command(name='bridge', description='開始橋牌遊戲（2人或4人）')
@app_commands.describe(
    玩家1='第一位玩家',
    玩家2='第二位玩家（四人模式需要）',
    玩家3='第三位玩家（四人模式需要）'
)
async def slash_bridge(interaction: discord.Interaction, 玩家1: discord.Member, 玩家2: discord.Member = None, 玩家3: discord.Member = None):
    """開始橋牌遊戲（支援2-4人）"""
    # 收集玩家
    players = [玩家1]
    if 玩家2:
        players.append(玩家2)
    if 玩家3:
        players.append(玩家3)
    
    # 檢查玩家數量
    if len(players) not in [1, 3]:
        await interaction.response.send_message("橋牌遊戲支援2人或4人！\n• 雙人橋牌：只標記 玩家1\n• 四人橋牌：標記 玩家1, 玩家2, 玩家3", ephemeral=True)
        return
    
    # 檢查是否有機器人玩家
    if any(player.bot for player in players) and not TEST_MODE:
        await interaction.response.send_message("不能與機器人遊戲！\n💡 提示：使用 `/testmode enabled:True` 啟用測試模式", ephemeral=True)
        return
    
    # 檢查是否有重複玩家
    all_players = [interaction.user] + players
    if len(set(player.id for player in all_players)) != len(all_players):
        await interaction.response.send_message("不能有重複的玩家！", ephemeral=True)
        return
    
    if interaction.channel.id in games:
        await interaction.response.send_message("這個頻道已經有遊戲在進行中！", ephemeral=True)
        return
    
    # 創建新遊戲
    game = BridgeGame(interaction.channel.id, all_players)
    game.deal_cards()
    games[interaction.channel.id] = game
    
    # 發送遊戲開始訊息
    if game.player_count == 2:
        title = "🃏 雙人橋牌遊戲開始！"
        description = f"{all_players[0].mention} vs {all_players[1].mention}"
        game_rules = "• 每人26張牌\n• 先出完牌或贏得更多tricks獲勝"
    else:
        title = "🃏 四人橋牌遊戲開始！"
        partners = f"**南北搭檔：** {all_players[0].mention} & {all_players[2].mention}\n**東西搭檔：** {all_players[1].mention} & {all_players[3].mention}"
        description = partners
        game_rules = "• 每人13張牌\n• 搭檔合作，贏得更多tricks的隊伍獲勝"
        
        # 顯示座位安排
        positions = f"\n**座位安排：**\n{all_players[0].mention} - 南 (S)\n{all_players[1].mention} - 西 (W)\n{all_players[2].mention} - 北 (N)\n{all_players[3].mention} - 東 (E)"
        description += positions
    
    embed = discord.Embed(title=title, description=description, color=0x00ff00)
    embed.add_field(
        name="遊戲規則",
        value=game_rules,
        inline=False
    )
    embed.add_field(
        name="遊戲說明",
        value="• 遊戲將先進行叫牌階段\n• 使用 `/hand` 查看手牌（僅自己可見）\n• 叫牌格式：`1♠️`, `2NT`, `3♥️` 或 `pass`\n• 出牌格式：直接輸入牌面，如 `♠️A` 或 `♥️K`\n• 必須跟出相同花色（如果有的話）",
        inline=False
    )
    
    await interaction.response.send_message(embed=embed)
    
    # 通知玩家使用slash command查看手牌
    await interaction.followup.send("💡 **提示：使用 `/hand` 指令查看您的手牌（只有您能看到）**", ephemeral=True)
    
    # 開始叫牌階段
    current_bidder = game.players[game.bidding_player]
    await interaction.followup.send(f"🎯 **叫牌階段開始！**\n輪到 {current_bidder.mention} 叫牌\n\n叫牌格式：`1♠️`, `2NT`, `3♥️`, `pass`")

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

# @bot.command(name='sync')
@commands.has_permissions(administrator=True)
async def sync_commands(ctx):
    """同步slash commands（僅管理員）"""
    try:
        synced = await bot.tree.sync()
        await ctx.send(f"✅ 成功同步了 {len(synced)} 個slash commands")
        print(f"同步了 {len(synced)} 個commands: {[cmd.name for cmd in synced]}")
    except Exception as e:
        await ctx.send(f"❌ 同步失敗: {e}")
        print(f"同步失敗: {e}")

@sync_commands.error
async def sync_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ 只有管理員可以使用此指令")

# 測試模式：允許與機器人遊戲
TEST_MODE = os.getenv('TEST_MODE', 'false').lower() == 'true'

@bot.tree.command(name='testmode', description='切換測試模式（允許與機器人遊戲）')
@app_commands.describe(enabled='是否啟用測試模式')
async def toggle_test_mode(interaction: discord.Interaction, enabled: bool = None):
    """切換測試模式"""
    global TEST_MODE
    
    if enabled is None:
        # 顯示當前狀態
        status = "啟用" if TEST_MODE else "停用"
        await interaction.response.send_message(f"目前測試模式：**{status}**", ephemeral=True)
        return
    
    TEST_MODE = enabled
    status = "啟用" if TEST_MODE else "停用"
    await interaction.response.send_message(f"測試模式已{status}！{'(可與機器人遊戲)' if TEST_MODE else ''}", ephemeral=True)

# 為手機用戶提供備用的文字指令
@bot.tree.command(name='start', description='開始橋牌遊戲（手機版友好）')
@app_commands.describe(
    玩家們='標記要一起遊戲的玩家，用空格分隔（雙人模式1個，四人模式3個）'
)
async def slash_start(interaction: discord.Interaction, 玩家們: str):
    """備用的開始橋牌遊戲指令（適用於手機用戶）"""
    # 解析玩家提及
    import re
    mentions = re.findall(r'<@!?(\d+)>', 玩家們)
    
    if not mentions:
        await interaction.response.send_message("請在參數中標記其他玩家！\n• 雙人橋牌：標記1位玩家\n• 四人橋牌：標記3位玩家\n\n例如：`/start 玩家們:@朋友1 @朋友2 @朋友3`", ephemeral=True)
        return
    
    # 獲取玩家對象
    players = []
    for user_id in mentions:
        try:
            user = await bot.fetch_user(int(user_id))
            member = interaction.guild.get_member(user.id)
            if member:
                players.append(member)
        except:
            continue
    
    if len(players) not in [1, 3]:
        await interaction.response.send_message("橋牌遊戲支援2人或4人！\n• 雙人橋牌：標記1位玩家\n• 四人橋牌：標記3位玩家", ephemeral=True)
        return
    
    # 檢查是否有機器人玩家
    if any(player.bot for player in players) and not TEST_MODE:
        await interaction.response.send_message("不能與機器人遊戲！\n💡 提示：使用 `/testmode enabled:True` 啟用測試模式", ephemeral=True)
        return
    
    # 檢查是否有重複玩家
    all_players = [interaction.user] + players
    if len(set(player.id for player in all_players)) != len(all_players):
        await interaction.response.send_message("不能有重複的玩家！", ephemeral=True)
        return
    
    if interaction.channel.id in games:
        await interaction.response.send_message("這個頻道已經有遊戲在進行中！", ephemeral=True)
        return
    
    # 創建新遊戲
    game = BridgeGame(interaction.channel.id, all_players)
    game.deal_cards()
    games[interaction.channel.id] = game
    
    # 發送遊戲開始訊息
    if game.player_count == 2:
        title = "🃏 雙人橋牌遊戲開始！"
        description = f"{all_players[0].mention} vs {all_players[1].mention}"
        game_rules = "• 每人26張牌\n• 先出完牌或贏得更多tricks獲勝"
    else:
        title = "🃏 四人橋牌遊戲開始！"
        partners = f"**南北搭檔：** {all_players[0].mention} & {all_players[2].mention}\n**東西搭檔：** {all_players[1].mention} & {all_players[3].mention}"
        description = partners
        game_rules = "• 每人13張牌\n• 搭檔合作，贏得更多tricks的隊伍獲勝"
        
        # 顯示座位安排
        positions = f"\n**座位安排：**\n{all_players[0].mention} - 南 (S)\n{all_players[1].mention} - 西 (W)\n{all_players[2].mention} - 北 (N)\n{all_players[3].mention} - 東 (E)"
        description += positions
    
    embed = discord.Embed(title=title, description=description, color=0x00ff00)
    embed.add_field(
        name="遊戲規則",
        value=game_rules,
        inline=False
    )
    embed.add_field(
        name="遊戲說明",
        value="• 使用 `/hand` 查看手牌（僅自己可見）\n• 使用 `/gameinfo` 查看遊戲狀態\n• 出牌格式：直接輸入牌面，如 `♠️A` 或 `♥️K`\n• 必須跟出相同花色（如果有的話）",
        inline=False
    )
    
    await interaction.response.send_message(embed=embed)
    
    # 通知玩家使用slash command查看手牌
    await interaction.followup.send("💡 **提示：使用 `/hand` 指令查看您的手牌（只有您能看到）**", ephemeral=True)
    
    # 宣布第一位玩家
    current_player = game.players[game.current_player]
    await interaction.followup.send(f"輪到 {current_player.mention} 出牌！")
    
    # 設置遊戲階段
    game.game_phase = "playing"

@bot.event
async def on_message(message):
    """處理玩家叫牌和出牌"""
    if message.author.bot:
        return
    
    # 處理指令
    await bot.process_commands(message)
    
    # 檢查是否是遊戲頻道
    game = games.get(message.channel.id)
    if not game:
        return
    
    # 檢查是否是遊戲中的玩家
    if message.author.id not in [p.id for p in game.players]:
        return
    
    # 根據遊戲階段處理
    if game.game_phase == "bidding":
        # 叫牌階段
        current_bidder = game.players[game.bidding_player]
        if message.author.id != current_bidder.id:
            temp_msg = await message.channel.send(f"{message.author.mention} 還沒輪到您叫牌！", delete_after=3)
            return
        
        # 刪除玩家的叫牌訊息
        try:
            await message.delete()
        except:
            pass
        
        # 處理叫牌
        success, result = game.make_bid(message.author.id, message.content)
        if not success:
            await message.channel.send(f"{message.author.mention} {result}", delete_after=5)
            return
        
        # 宣布叫牌結果
        embed = discord.Embed(
            title="叫牌",
            description=f"{message.author.mention} 叫了 **{result}**",
            color=0x00bfff
        )
        
        # 顯示叫牌歷史
        if game.bids:
            bid_history = []
            for player, bid in game.bids[-4:]:  # 顯示最近4個叫牌
                bid_str = f"{bid[0]}{bid[1]}" if bid else "Pass"
                bid_history.append(f"{player.display_name}: {bid_str}")
            embed.add_field(name="叫牌歷史", value="\n".join(bid_history), inline=False)
        
        await message.channel.send(embed=embed)
        
        # 檢查叫牌是否結束
        if game.check_bidding_end():
            game.finalize_contract()
            game.game_phase = "playing"
            
            # 宣布最終合約
            contract_embed = discord.Embed(
                title="🎯 叫牌結束！",
                color=0x00ff00
            )
            
            if game.contract:
                level, suit, declarer = game.contract
                trump_info = f"王牌：{suit}" if suit != 'NT' else "無王"
                contract_embed.add_field(
                    name="最終合約",
                    value=f"**{level}{suit}** by {declarer.mention}\n{trump_info}",
                    inline=False
                )
            
            contract_embed.add_field(
                name="現在開始出牌！",
                value="請按順序出牌，必須跟出相同花色（如果有的話）",
                inline=False
            )
            
            await message.channel.send(embed=contract_embed)
            
            # 宣布第一位出牌者
            current_player = game.players[game.current_player]
            await message.channel.send(f"輪到 {current_player.mention} 出牌！")
        else:
            # 下一位玩家叫牌
            game.bidding_player = (game.bidding_player + 1) % game.player_count
            next_bidder = game.players[game.bidding_player]
            await message.channel.send(f"輪到 {next_bidder.mention} 叫牌！")
            
    elif game.game_phase == "playing":
        # 出牌階段
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
        
        # 顯示當前合約
        if game.contract:
            level, suit, declarer = game.contract
            trump_info = f"王牌：{suit}" if suit != 'NT' else "無王"
            embed.add_field(name="當前合約", value=f"{level}{suit} ({trump_info})", inline=True)
        
        # 顯示當前trick狀態
        trick_display = " → ".join([str(card) for _, card in game.current_trick])
        embed.add_field(name="當前Trick", value=trick_display, inline=False)
        
        if len(game.current_trick) < game.player_count:
            # 還沒滿一輪，切換到下一位玩家
            game.current_player = (game.current_player + 1) % game.player_count
            next_player = game.players[game.current_player]
            embed.add_field(name="下一位", value=f"{next_player.mention} 的回合", inline=False)
        else:
            # 一輪完成，評估trick勝者
            winner = game.finish_trick()
            embed.add_field(name="Trick勝者", value=f"{winner.mention} 獲勝！", inline=False)
            
            # 檢查遊戲是否結束
            if game.is_game_finished():
                await message.channel.send(embed=embed)
                
                # 創建最終結果嵌入
                final_embed = discord.Embed(title="🎉 遊戲結束！", color=0xff6b6b)
                
                if game.player_count == 2:
                    # 雙人橋牌結果
                    game_winner = game.get_winner()
                    score_text = f"**勝者：{game_winner.mention}**\n\n"
                    score_text += f"**最終得分：**\n"
                    for player in game.players:
                        score_text += f"{player.mention}: {game.scores[player.id]} tricks\n"
                else:
                    # 四人橋牌結果
                    winner_team = game.get_winner()
                    if winner_team == "NS":
                        score_text = f"**勝者：南北隊 🏆**\n{game.players[0].mention} & {game.players[2].mention}\n\n"
                    elif winner_team == "EW":
                        score_text = f"**勝者：東西隊 🏆**\n{game.players[1].mention} & {game.players[3].mention}\n\n"
                    else:
                        score_text = f"**平手！** 🤝\n\n"
                    
                    score_text += f"**隊伍得分：**\n"
                    score_text += f"南北隊: {game.team_scores['NS']} tricks\n"
                    score_text += f"東西隊: {game.team_scores['EW']} tricks\n\n"
                    score_text += f"**個人得分：**\n"
                    for player in game.players:
                        position = game.positions[player.id]
                        score_text += f"{player.mention} ({position}): {game.scores[player.id]} tricks\n"
                
                # 顯示合約完成情況
                if game.contract:
                    level, suit, declarer = game.contract
                    target = level + 6  # 基本6墩 + 叫牌墩數
                    if game.player_count == 4:
                        # 檢查合約方是否完成
                        if declarer.id in [game.players[0].id, game.players[2].id]:
                            made_tricks = game.team_scores["NS"]
                        else:
                            made_tricks = game.team_scores["EW"]
                    else:
                        made_tricks = game.scores[declarer.id]
                    
                    contract_result = "完成" if made_tricks >= target else "失敗"
                    score_text += f"\n**合約結果：**\n{level}{suit} - {contract_result} ({made_tricks}/{target})"
                
                final_embed.add_field(name="最終結果", value=score_text, inline=False)
                await message.channel.send(embed=final_embed)
                
                # 清理遊戲
                del games[message.channel.id]
                return
            else:
                # 設置下一輪的先手（trick勝者）
                game.current_player = game.players.index(winner)
                next_player = game.players[game.current_player]
                embed.add_field(name="下一輪先手", value=f"{next_player.mention} 先出牌", inline=False)
        
        await message.channel.send(embed=embed)                elif winner_team == "EW":
                    score_text = f"**勝者：東西隊 🏆**\n{game.players[1].mention} & {game.players[3].mention}\n\n"
                else:
                    score_text = f"**平手！** 🤝\n\n"
                
                score_text += f"**隊伍得分：**\n"
                score_text += f"南北隊: {game.team_scores['NS']} tricks\n"
                score_text += f"東西隊: {game.team_scores['EW']} tricks\n\n"
                score_text += f"**個人得分：**\n"
                for player in game.players:
                    position = game.positions[player.id]
                    score_text += f"{player.mention} ({position}): {game.scores[player.id]} tricks\n"
            
            # 顯示合約完成情況
            if game.contract:
                level, suit, declarer = game.contract
                target = level + 6  # 基本6墩 + 叫牌墩數
                if game.player_count == 4:
                    # 檢查合約方是否完成
                    if declarer.id in [game.players[0].id, game.players[2].id]:
                        made_tricks = game.team_scores["NS"]
                    else:
                        made_tricks = game.team_scores["EW"]
                else:
                    made_tricks = game.scores[declarer.id]
                
                contract_result = "完成" if made_tricks >= target else "失敗"
                score_text += f"\n**合約結果：**\n{level}{suit} - {contract_result} ({made_tricks}/{target})"
            
            final_embed.add_field(name="最終結果", value=score_text, inline=False)
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

@bot.tree.command(name='gameinfo', description='查看當前遊戲狀態')
async def slash_gameinfo(interaction: discord.Interaction):
    """顯示遊戲狀態"""
    game = games.get(interaction.channel.id)
    if not game:
        await interaction.response.send_message("目前沒有進行中的遊戲！", ephemeral=True)
        return
    
    embed = discord.Embed(title="🃏 遊戲狀態", color=0x00ff00)
    
    # 顯示玩家和模式
    if game.player_count == 2:
        players_str = f"**雙人橋牌**\n{game.players[0].mention} vs {game.players[1].mention}"
        embed.add_field(name="玩家", value=players_str, inline=False)
        
        # 顯示分數
        score_str = f"{game.players[0].mention}: {game.scores[game.players[0].id]}\n{game.players[1].mention}: {game.scores[game.players[1].id]}"
        embed.add_field(name="當前得分", value=score_str, inline=True)
    else:
        players_str = f"**四人橋牌**\n"
        players_str += f"**南北隊：** {game.players[0].mention} & {game.players[2].mention}\n"
        players_str += f"**東西隊：** {game.players[1].mention} & {game.players[3].mention}"
        embed.add_field(name="玩家", value=players_str, inline=False)
        
        # 顯示隊伍分數
        team_score_str = f"南北隊: {game.team_scores['NS']}\n東西隊: {game.team_scores['EW']}"
        embed.add_field(name="隊伍得分", value=team_score_str, inline=True)
        
        # 顯示個人分數
        individual_score_str = ""
        for player in game.players:
            position = game.positions[player.id]
            individual_score_str += f"{player.mention} ({position}): {game.scores[player.id]}\n"
        embed.add_field(name="個人得分", value=individual_score_str, inline=True)
    
    # 顯示當前回合
    if game.game_phase == "bidding":
        current_bidder = game.players[game.bidding_player]
        embed.add_field(name="當前叫牌者", value=current_bidder.mention, inline=True)
        
        # 顯示叫牌歷史
        if game.bids:
            bid_history = []
            for player, bid in game.bids[-4:]:  # 顯示最近4個叫牌
                bid_str = f"{bid[0]}{bid[1]}" if bid else "Pass"
                bid_history.append(f"{player.display_name}: {bid_str}")
            embed.add_field(name="叫牌歷史", value="\n".join(bid_history), inline=True)
    else:
        current_player = game.players[game.current_player]
        embed.add_field(name="當前回合", value=current_player.mention, inline=True)
        
        # 顯示當前合約
        if game.contract:
            level, suit, declarer = game.contract
            trump_info = f"王牌：{suit}" if suit != 'NT' else "無王"
            embed.add_field(name="當前合約", value=f"{level}{suit} by {declarer.display_name}\n{trump_info}", inline=True)
    
    # 顯示遊戲階段
    phase_text = "叫牌階段" if game.game_phase == "bidding" else "出牌階段"
    embed.add_field(name="遊戲階段", value=phase_text, inline=True)
    
    # 顯示當前trick
    if game.current_trick:
        trick_str = " → ".join([f"{player.display_name}: {card}" for player, card in game.current_trick])
        embed.add_field(name="當前Trick", value=trick_str, inline=False)
    
    # 顯示剩餘手牌數量
    cards_left = f"剩餘手牌：\n"
    for player in game.players:
        cards_left += f"{player.mention}: {len(game.hands[player.id])}張\n"
    embed.add_field(name="手牌狀況", value=cards_left, inline=True)
    
    await interaction.response.send_message(embed=embed)
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

@bot.tree.command(name='quit', description='退出當前遊戲')
async def slash_quit(interaction: discord.Interaction):
    """退出遊戲"""
    game = games.get(interaction.channel.id)
    if not game:
        await interaction.response.send_message("目前沒有進行中的遊戲！", ephemeral=True)
        return
    
    if interaction.user.id not in [p.id for p in game.players]:
        await interaction.response.send_message("您不在這場遊戲中！", ephemeral=True)
        return
    
    del games[interaction.channel.id]
    await interaction.response.send_message(f"{interaction.user.mention} 退出了遊戲。遊戲已結束。")

@bot.tree.command(name='help', description='顯示橋牌機器人使用說明')
async def slash_help(interaction: discord.Interaction):
    """顯示幫助信息"""
    embed = discord.Embed(
        title="🃏 橋牌機器人使用說明",
        description="歡迎使用Discord橋牌機器人！支援雙人和四人橋牌遊戲。",
        color=0x0099ff
    )
    
    embed.add_field(
        name="🎮 遊戲指令",
        value="**`/bridge`** - 開始新遊戲（桌面版推薦）\n• 雙人模式：只標記 玩家1\n• 四人模式：標記 玩家1, 玩家2, 玩家3\n\n**`/start`** - 開始新遊戲（手機版友好）\n• 在「玩家們」參數中標記所有玩家\n• 例如：`/start 玩家們:@朋友1 @朋友2`\n\n**`/hand`** - 查看手牌（僅自己可見）\n\n**`/gameinfo`** - 查看遊戲狀態\n\n**`/quit`** - 退出當前遊戲\n\n**🔧 測試指令**\n**`/testmode`** - 切換測試模式\n**`/createbots`** - 測試機器人創建指南",
        inline=False
    )
    
    embed.add_field(
        name="🎯 出牌方式",
        value="直接在聊天室輸入牌面：\n• `♠️A` - 黑桃A\n• `♥️K` - 紅心K\n• `♦️10` - 方塊10\n• `♣️J` - 梅花J",
        inline=False
    )
    
    embed.add_field(
        name="📋 遊戲規則",
        value="**雙人橋牌：**\n• 每人26張牌\n• 個人對戰\n\n**四人橋牌：**\n• 每人13張牌\n• 搭檔合作\n• 南北 vs 東西",
        inline=False
    )
    
    embed.add_field(
        name="🎲 橋牌規則",
        value="**叫牌階段：**\n• 格式：`1♠️`, `2NT`, `3♥️`, `pass`\n• 花色等級：♣️ < ♦️ < ♥️ < ♠️ < NT\n• 叫牌必須比前一個更高\n\n**出牌階段：**\n• 必須跟出相同花色（如果有的話）\n• 王牌可以吃其他花色\n• 花色等級：♠️ > ♥️ > ♦️ > ♣️\n• 牌值等級：A > K > Q > J > 10 > ... > 2",
        inline=False
    )
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

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
