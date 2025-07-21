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
    
    def finalize_contract(self):
        """確定最終合約"""
        # 找到最後一個有效叫牌
        for player, bid in reversed(self.bids):
            if bid is not None:
                level, suit = bid
                self.contract = (level, suit, player)
                self.declarer = player
                if suit != 'NT':
                    self.trump_suit = suit
                else:
                    self.trump_suit = None
                break
        
        if self.contract is None:
            # 所有人都pass，重新發牌（簡化版直接設定無王）
            self.trump_suit = None
            self.contract = (1, 'NT', self.players[0])
            self.declarer = self.players[0]
    
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

# 測試模式：允許與機器人遊戲
TEST_MODE = os.getenv('TEST_MODE', 'false').lower() == 'true'

@bot.event
async def on_ready():
    print(f'🎉 {bot.user} 橋牌機器人已上線！')
    print(f'機器人ID: {bot.user.id}')
    print(f'連接到 {len(bot.guilds)} 個伺服器')
    
    # 列出所有連接的伺服器
    for guild in bot.guilds:
        print(f'  - {guild.name} (成員數: {guild.member_count})')
    
    try:
        print("🔄 正在同步slash commands...")
        synced = await bot.tree.sync()
        print(f'✅ 成功同步了 {len(synced)} 個slash commands')
        
        # 列出同步的commands
        for cmd in synced:
            print(f'  - /{cmd.name}: {cmd.description}')
            
    except Exception as e:
        print(f'❌ 同步slash commands失敗: {e}')
        import traceback
        traceback.print_exc()

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
    
    # 開始叫牌階段
    current_bidder = game.players[game.bidding_player]
    await interaction.followup.send(f"🎯 **叫牌階段開始！**\n輪到 {current_bidder.mention} 叫牌\n\n叫牌格式：`1♠️`, `2NT`, `3♥️`, `pass`")
    
    # 設置遊戲階段
    game.game_phase = "bidding"

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

@bot.tree.command(name='gameinfo', description='查看當前遊戲狀態')
async def slash_gameinfo(interaction: discord.Interaction):
    """顯示遊戲狀態"""
    game = games.get(interaction.channel.id)
    if not game:
        await interaction
