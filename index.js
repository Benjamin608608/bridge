// 處理訊息（叫牌和出牌）
client.on('messageCreate', async message => {
    if (message.author.bot) return;

    const game = games.get(message.channelId);
    if (!game) return;

    if (!game.players.some(p => p.id === message.author.id)) return;

    console.log(`收到訊息: "${message.content}" 來自 ${message.author.tag}, 遊戲階段: ${game.gamePhase}`);

    if (game.gamePhase === "bidding") {
        // 叫牌階段
        const currentBidder = game.players[game.biddingPlayer];
        if (message.author.id !== currentBidder.id) {
            const temp = await message.channel.send(`${message.author} 還沒輪到您叫牌！`);
            setTimeout(() => temp.delete().catch(() => {}), 3000);
            return;
        }

        try {
            await message.delete();
        } catch {}

        const bidResult = game.makeBid(message.author.id, message.content);
        if (!bidResult.success) {
            const temp = await message.channel.send(`${message.author} ${bidResult.result}`);
            setTimeout(() => temp.delete().catch(() => {}), 5000);
            return;
        }

        const embed = new EmbedBuilder()
            .setTitle('叫牌')
            .setDescription(`${message.author} 叫了 **${bidResult.result}**`)
            .setColor(0x00bfff);

        // 顯示叫牌歷史
        if (game.bids.length > 0) {
            const bidHistory = game.bids.slice(-4).map(bid => {
                const bidStr = bid.bid ? `${bid.bid[0]}${bid.bid[1]}` : "Pass";
                return `${bid.player.username}: ${bidStr}`;
            });
            embed.addFields({ name: '叫牌歷史', value: bidHistory.join('\n'), inline: false });
        }

        await message.channel.send({ embeds: [embed] });

        if (game.checkBiddingEnd()) {
            game.finalizeContract();
            game.gamePhase = "playing";

            const contractEmbed = new EmbedBuilder()
                .setTitle('🎯 叫牌結束！')
                .setColor(0x00ff00);

            if (game.contract) {
                const [level, suit, declarer] = game.contract;
                const trumpInfo = suit !== 'NT' ? `王牌：${suit}` : '無王';
                contractEmbed.addFields({
                    name: '最終合約',
                    value: `**${level}${suit}** by ${declarer.username}\n${trumpInfo}`,
                    inline: false
                });
            }

            contractEmbed.addFields({
                name: '現在開始出牌！',
                value: '請按順序出牌，必須跟出相同花色（如果有的話）',
                inline: false
            });

            await message.channel.send({ embeds: [contractEmbed] });

            const currentPlayer = game.players[game.currentPlayer];
            await message.channel.send(`輪到 ${currentPlayer} 出牌！`);
        } else {
            game.biddingPlayer = (game.biddingPlayer + 1) % game.playerCount;
            const nextBidder = game.players[game.biddingPlayer];
            await message.channel.send(`輪到 ${nextBidder} 叫牌！`);
        }
    
    } else if (game.gamePhase === "playing") {
        // 出牌階段
        console.log(`出牌階段 - 當前玩家: ${game.players[game.currentPlayer].tag}, 訊息作者: ${message.author.tag}`);
        
        const currentPlayer = game.players[game.currentPlayer];
        if (message.author.id !== currentPlayer.id) {
            const temp = await message.channel.send(`${message.author} 還沒輪到您出牌！`);
            setTimeout(() => temp.delete().catch(() => {}), 3000);
            return;
        }

        // 嘗試解析出牌
        console.log(`嘗試解析出牌: "${message.content}"`);
        const card = game.parseCardInput(message.content);
        console.log(`解析結果:`, card);
        
        if (!card) {
            console.log(`無法解析出牌，忽略訊息`);
            return; // 不是有效的出牌格式，忽略
        }

        try {
            await message.delete();
        } catch {}

        // 嘗試出牌
        const playResult = game.playCard(message.author.id, card);
        console.log(`出牌結果:`, playResult);
        
        if (!playResult.canPlay) {
            const temp = await message.channel.send(`${message.author} ${playResult.reason}`);
            setTimeout(() => temp.delete().catch(() => {}), 5000);
            return;
        }

        // 宣布出牌
        const embed = new EmbedBuilder()
            .setTitle('🃏 出牌')
            .setDescription(`${message.author} 出了 **${card}**`)
            .setColor(0xffd700);

        // 顯示當前合約
        if (game.contract) {
            const [level, suit, declarer] = game.contract;
            const trumpInfo = suit !== 'NT' ? `王牌：${suit}` : '無王';
            embed.addFields({ name: '當前合約', value: `${level}${suit} by ${declarer.username}\n${trumpInfo}`, inline: true });
        }

        // 顯示當前trick狀態
        const trickDisplay = game.currentTrick.map((t, index) => {
            const playerName = t.player.username;
            const cardStr = `${t.card}`;
            const isLeader = index === 0 ? ' (領牌)' : '';
            return `${playerName}: ${cardStr}${isLeader}`;
        }).join('\n');
        
        embed.addFields({ name: '當前Trick', value: trickDisplay, inline: false });

        // 顯示出牌規則提示
        if (game.currentTrick.length === 1) {
            const leadSuit = game.currentTrick[0].card.suit;
            embed.addFields({ 
                name: '出牌規則', 
                value: `必須跟出 ${leadSuit} 花色（如果有的話）${game.trumpSuit ? `\n王牌 ${game.trumpSuit} 可以吃其他花色` : ''}`, 
                inline: false 
            });
        }

        if (game.currentTrick.length < game.playerCount) {
            // 還沒滿一輪，切換到下一位玩家
            game.currentPlayer = (game.currentPlayer + 1) % game.playerCount;
            const nextPlayer = game.players[game.currentPlayer];
            embed.addFields({ name: '⏭️ 下一位出牌', value: `輪到 ${nextPlayer} 出牌`, inline: false });
            
            // 顯示剩餘玩家數
            const remaining = game.playerCount - game.currentTrick.length;
            embed.addFields({ name: '本輪狀態', value: `還需要 ${remaining} 位玩家出牌`, inline: true });
        } else {
            // 一輪完成，評估trick勝者
            const winner = game.finishTrick();
            embed.addFields({ name: '🏆 Trick勝者', value: `${winner} 獲勝！`, inline: false });
            
            // 顯示勝牌原因
            const winningTrick = game.tricks[game.tricks.length - 1];
            const winningCard = winningTrick.trick.find(t => t.player.id === winner.id).card;
            let winReason = '';
            
            if (game.trumpSuit && winningCard.suit === game.trumpSuit) {
                winReason = `(${winningCard} 是王牌)`;
            } else if (winningCard.suit === game.leadSuit) {
                winReason = `(${winningCard} 是最大的${game.leadSuit})`;
            } else {
                winReason = `(${winningCard} 獲勝)`;
            }
            
            embed.addFields({ name: '勝牌原因', value: winReason, inline: true });

            // 顯示當前得分
            if (game.playerCount === 2) {
                const scoreStr = `${game.players[0]}: ${game.scores[game.players[0].id]} tricks\n${game.players[1]}: ${game.scores[game.players[1].id]} tricks`;
                embed.addFields({ name: '當前得分', value: scoreStr, inline: true });
            } else {
                const teamScoreStr = `南北隊: ${game.teamScores['NS']} tricks\n東西隊: ${game.teamScores['EW']} tricks`;
                embed.addFields({ name: '隊伍得分', value: teamScoreStr, inline: true });
            }

            // 檢查遊戲是否結束
            if (game.isGameFinished()) {
                await message.channel.send({ embeds: [embed] });

                // 創建最終結果
                const finalEmbed = new EmbedBuilder()
                    .setTitle('🎉 遊戲結束！')
                    .setColor(0xff6b6b);

                let scoreText = "";
                if (game.playerCount === 2) {
                    const gameWinner = game.getWinner();
                    scoreText = `**勝者：${gameWinner}**\n\n**最終得分：**\n`;
                    for (const player of game.players) {
                        scoreText += `${player}: ${game.scores[player.id]} tricks\n`;
                    }
                } else {
                    const winnerTeam = game.getWinner();
                    if (winnerTeam === "NS") {
                        scoreText = `**勝者：南北隊 🏆**\n${game.players[0]} & ${game.players[2]}\n\n`;
                    } else if (winnerTeam === "EW") {
                        scoreText = `**勝者：東西隊 🏆**\n${game.players[1]} & ${game.players[3]}\n\n`;
                    } else {
                        scoreText = `**平手！** 🤝\n\n`;
                    }
                    
                    scoreText += `**隊伍得分：**\n南北隊: ${game.teamScores['NS']} tricks\n東西隊: ${game.teamScores['EW']} tricks\n\n`;
                    scoreText += `**個人得分：**\n`;
                    for (const player of game.players) {
                        const position = game.positions[player.id];
                        scoreText += `${player} (${position}): ${game.scores[player.id]} tricks\n`;
                    }
                }

                // 顯示合約完成情況
                if (game.contract) {
                    const [level, suit, declarer] = game.contract;
                    const target = level + 6; // 基本6墩 + 叫牌墩數
                    let madeTricks;
                    
                    if (game.playerCount === 4) {
                        if ([game.players[0].id, game.players[2].id].includes(declarer.id)) {
                            madeTricks = game.teamScores["NS"];
                        } else {
                            madeTricks = game.teamScores["EW"];
                        }
                    } else {
                        madeTricks = game.scores[declarer.id];
                    }
                    
                    const contractResult = madeTricks >= target ? "✅ 完成" : "❌ 失敗";
                    scoreText += `\n**合約結果：**\n${level}${suit} - ${contractResult} (${madeTricks}/${target})`;
                }

                finalEmbed.addFields({ name: '最終結果', value: scoreText, inline: false });
                await message.channel.send({ embeds: [finalEmbed] });

                // 清理遊戲
                games.delete(message.channelId);
                return;
            } else {
                // 設置下一輪的先手（trick勝者）
                game.currentPlayer = game.players.findIndex(p => p.id === winner.id);
                const nextPlayer = game.players[game.currentPlayer];
                embed.addFields({ name: '🎯 下一輪先手', value: `${nextPlayer} 先出牌（贏得了上一trick）`, inline: false });
                
                // 顯示剩餘手牌信息
                const remainingCards = Object.values(game.hands).reduce((sum, hand) => sum + hand.length, 0);
                const tricksPlayed = game.tricks.length;
                const totalTricks = game.playerCount === 2 ? 26 : 13;
                embed.addFields({ name: '遊戲進度', value: `已完成 ${tricksPlayed}/${totalTricks} tricks`, inline: true });
            }
        }

        await message.channel.send({ embeds: [embed] });
    }
});
                const { Client, GatewayIntentBits, SlashCommandBuilder, EmbedBuilder, Collection } = require('discord.js');

// 機器人設置
const client = new Client({
    intents: [
        GatewayIntentBits.Guilds,
        GatewayIntentBits.GuildMessages,
        GatewayIntentBits.MessageContent
    ]
});

// 全局遊戲狀態
const games = new Map();
let TEST_MODE = process.env.TEST_MODE === 'true';

// 牌的類別
class Card {
    static SUITS = { '♠️': 'spades', '♥️': 'hearts', '♦️': 'diamonds', '♣️': 'clubs' };
    static SUIT_ORDER = { '♠️': 4, '♥️': 3, '♦️': 2, '♣️': 1 };
    static VALUES = ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A'];
    static VALUE_ORDER = Object.fromEntries(Card.VALUES.map((v, i) => [v, i]));

    constructor(suit, value) {
        this.suit = suit;
        this.value = value;
        this.suitName = Card.SUITS[suit];
    }

    toString() {
        return `${this.suit}${this.value}`;
    }

    compareValue(other, trumpSuit = null) {
        // 王牌比較
        if (trumpSuit) {
            const selfIsTrump = this.suit === trumpSuit;
            const otherIsTrump = other.suit === trumpSuit;
            
            if (selfIsTrump && !otherIsTrump) return 1;
            if (!selfIsTrump && otherIsTrump) return -1;
            if (selfIsTrump && otherIsTrump) {
                return Card.VALUE_ORDER[this.value] - Card.VALUE_ORDER[other.value];
            }
        }

        // 同花色比較
        if (this.suit === other.suit) {
            return Card.VALUE_ORDER[this.value] - Card.VALUE_ORDER[other.value];
        }

        return 0; // 不同花色且無王牌
    }
}

// 橋牌遊戲類別
class BridgeGame {
    constructor(channelId, players) {
        this.channelId = channelId;
        this.players = players;
        this.playerCount = players.length;
        this.hands = {};
        this.currentPlayer = 0;
        this.trumpSuit = null;
        this.tricks = [];
        this.currentTrick = [];
        this.scores = {};
        this.gamePhase = "bidding";
        this.bids = [];
        this.contract = null;
        this.declarer = null;
        this.leadSuit = null;
        this.biddingPlayer = 0;
        this.passCount = 0;

        // 初始化手牌和分數
        players.forEach(player => {
            this.hands[player.id] = [];
            this.scores[player.id] = 0;
        });

        // 四人橋牌特有屬性
        if (this.playerCount === 4) {
            this.partnerships = {
                [players[0].id]: players[2].id,
                [players[1].id]: players[3].id,
                [players[2].id]: players[0].id,
                [players[3].id]: players[1].id
            };
            this.teamScores = { "NS": 0, "EW": 0 };
            this.positions = {
                [players[0].id]: "南 (S)",
                [players[1].id]: "西 (W)",
                [players[2].id]: "北 (N)",
                [players[3].id]: "東 (E)"
            };
        }
    }

    createDeck() {
        const deck = [];
        for (const suit of Object.keys(Card.SUITS)) {
            for (const value of Card.VALUES) {
                deck.push(new Card(suit, value));
            }
        }
        return deck;
    }

    dealCards() {
        const deck = this.createDeck();
        // 洗牌
        for (let i = deck.length - 1; i > 0; i--) {
            const j = Math.floor(Math.random() * (i + 1));
            [deck[i], deck[j]] = [deck[j], deck[i]];
        }

        if (this.playerCount === 2) {
            // 雙人：每人26張
            deck.forEach((card, i) => {
                const playerId = this.players[i % 2].id;
                this.hands[playerId].push(card);
            });
        } else {
            // 四人：每人13張
            deck.forEach((card, i) => {
                const playerId = this.players[i % 4].id;
                this.hands[playerId].push(card);
            });
        }

        // 排序手牌
        Object.keys(this.hands).forEach(playerId => {
            this.hands[playerId].sort((a, b) => {
                if (Card.SUIT_ORDER[a.suit] !== Card.SUIT_ORDER[b.suit]) {
                    return Card.SUIT_ORDER[b.suit] - Card.SUIT_ORDER[a.suit];
                }
                return Card.VALUE_ORDER[b.value] - Card.VALUE_ORDER[a.value];
            });
        });
    }

    getHandString(playerId) {
        const hand = this.hands[playerId];
        const suitsCards = { '♠️': [], '♥️': [], '♦️': [], '♣️': [] };
        
        hand.forEach(card => {
            suitsCards[card.suit].push(card.value);
        });

        let result = "**您的手牌：**\n";
        ['♠️', '♥️', '♦️', '♣️'].forEach(suit => {
            if (suitsCards[suit].length > 0) {
                result += `${suit}: ${suitsCards[suit].join(' ')}\n`;
            }
        });

        return result;
    }

    parseCardInput(inputStr) {
        inputStr = inputStr.trim();
        
        // 找花色
        let suit = null;
        for (const s of Object.keys(Card.SUITS)) {
            if (inputStr.includes(s)) {
                suit = s;
                break;
            }
        }

        if (!suit) return null;

        // 提取牌值
        const valueStr = inputStr.replace(suit, '').trim();
        
        if (['J', 'Q', 'K', 'A'].includes(valueStr.toUpperCase())) {
            return new Card(suit, valueStr.toUpperCase());
        } else if (Card.VALUES.includes(valueStr)) {
            return new Card(suit, valueStr);
        }

        return null;
    }

    parseBid(bidStr) {
        bidStr = bidStr.trim().toUpperCase();
        
        // Pass
        if (['PASS', 'P', '過牌', '不叫'].includes(bidStr)) {
            return null;
        }

        // 正常叫牌
        if (bidStr.length >= 2) {
            const level = parseInt(bidStr[0]);
            if (level < 1 || level > 7) return null;

            const suitStr = bidStr.slice(1).trim();
            
            // 擴展花色對照 - 支援更多輸入格式
            const suitMapping = {
                // 梅花
                '♣️': '♣️', '♣': '♣️', 'C': '♣️', 'CLUBS': '♣️', 'CLUB': '♣️', '梅花': '♣️', '草花': '♣️',
                // 方塊  
                '♦️': '♦️', '♦': '♦️', 'D': '♦️', 'DIAMONDS': '♦️', 'DIAMOND': '♦️', '方塊': '♦️', '鑽石': '♦️',
                // 紅心
                '♥️': '♥️', '♥': '♥️', 'H': '♥️', 'HEARTS': '♥️', 'HEART': '♥️', '紅心': '♥️', '愛心': '♥️',
                // 黑桃
                '♠️': '♠️', '♠': '♠️', 'S': '♠️', 'SPADES': '♠️', 'SPADE': '♠️', '黑桃': '♠️', '刀片': '♠️',
                // 無王
                'NT': 'NT', 'N': 'NT', 'NOTRUMP': 'NT', 'NO-TRUMP': 'NT', '無王': 'NT', '無主': 'NT'
            };

            // 直接匹配完整字符串
            if (suitMapping[suitStr]) {
                return [level, suitMapping[suitStr]];
            }

            // 部分匹配 - 檢查是否以某個key開頭
            for (const [key, value] of Object.entries(suitMapping)) {
                if (suitStr.startsWith(key) || key.startsWith(suitStr)) {
                    return [level, value];
                }
            }
        }

        return null;
    }

    isValidBid(level, suit) {
        if (this.bids.length === 0) return true;

        // 找最後一個有效叫牌
        let lastValidBid = null;
        for (let i = this.bids.length - 1; i >= 0; i--) {
            if (this.bids[i].bid !== null) {
                lastValidBid = this.bids[i].bid;
                break;
            }
        }

        if (!lastValidBid) return true;

        const [lastLevel, lastSuit] = lastValidBid;
        const suitOrder = { '♣️': 1, '♦️': 2, '♥️': 3, '♠️': 4, 'NT': 5 };

        if (level > lastLevel) return true;
        if (level === lastLevel) {
            return suitOrder[suit] > suitOrder[lastSuit];
        }
        
        return false;
    }

    makeBid(playerId, bidStr) {
        const player = this.players.find(p => p.id === playerId);
        
        if (['PASS', 'P', '過牌', '不叫'].includes(bidStr.trim().toUpperCase())) {
            this.bids.push({ player, bid: null });
            this.passCount++;
            return { success: true, result: "Pass" };
        }

        const parsedBid = this.parseBid(bidStr);
        if (!parsedBid) {
            return { success: false, result: "無效的叫牌格式！請使用如：1♠️, 2NT, 3♥️ 或 pass" };
        }

        const [level, suit] = parsedBid;
        if (!this.isValidBid(level, suit)) {
            return { success: false, result: "叫牌必須比之前的叫牌更高！" };
        }

        this.bids.push({ player, bid: [level, suit] });
        this.passCount = 0;
        return { success: true, result: `${level}${suit}` };
    }

    checkBiddingEnd() {
        if (this.bids.length < this.playerCount) return false;
        
        if (this.playerCount === 2) {
            return this.passCount >= 2;
        } else {
            return this.passCount >= 3;
        }
    }

    canPlayCard(playerId, card) {
        // 檢查玩家是否有這張牌
        const hasCard = this.hands[playerId].some(c => c.suit === card.suit && c.value === card.value);
        if (!hasCard) {
            return { canPlay: false, reason: "您沒有這張牌！" };
        }

        // 如果是第一張牌，可以出任何牌
        if (this.currentTrick.length === 0) {
            return { canPlay: true, reason: "" };
        }

        // 需要跟牌
        const leadSuit = this.currentTrick[0].card.suit;
        const hasLeadSuit = this.hands[playerId].some(c => c.suit === leadSuit);

        if (card.suit !== leadSuit && hasLeadSuit) {
            return { canPlay: false, reason: `您必須跟出 ${leadSuit} 花色的牌！` };
        }

        return { canPlay: true, reason: "" };
    }

    playCard(playerId, card) {
        const checkResult = this.canPlayCard(playerId, card);
        if (!checkResult.canPlay) {
            return checkResult;
        }

        // 移除手牌中的這張牌
        const handIndex = this.hands[playerId].findIndex(c => c.suit === card.suit && c.value === card.value);
        if (handIndex !== -1) {
            this.hands[playerId].splice(handIndex, 1);
        }

        // 添加到當前trick
        const player = this.players.find(p => p.id === playerId);
        this.currentTrick.push({ player, card });

        // 設置領出花色
        if (this.currentTrick.length === 1) {
            this.leadSuit = card.suit;
        }

        return { canPlay: true, reason: "" };
    }

    evaluateTrick() {
        if (this.currentTrick.length !== this.playerCount) {
            return null;
        }

        let winningPlayer = this.currentTrick[0].player;
        let winningCard = this.currentTrick[0].card;

        // 比較所有牌找出最大的
        for (let i = 1; i < this.currentTrick.length; i++) {
            const { player, card } = this.currentTrick[i];
            const comparison = card.compareValue(winningCard, this.trumpSuit);
            
            if (comparison > 0) {
                winningPlayer = player;
                winningCard = card;
            } else if (comparison === 0 && card.suit === this.leadSuit && winningCard.suit !== this.leadSuit) {
                // 如果都不是王牌，跟牌者勝過非跟牌者
                winningPlayer = player;
                winningCard = card;
            }
        }

        return winningPlayer;
    }

    finishTrick() {
        const winner = this.evaluateTrick();
        if (winner) {
            this.tricks.push({ trick: [...this.currentTrick], winner });
            
            // 更新分數
            if (this.playerCount === 2) {
                this.scores[winner.id] += 1;
            } else {
                // 四人橋牌：更新隊伍分數
                if ([this.players[0].id, this.players[2].id].includes(winner.id)) {
                    this.teamScores["NS"] += 1;
                } else {
                    this.teamScores["EW"] += 1;
                }
                this.scores[winner.id] += 1;
            }
            
            this.currentTrick = [];
            this.leadSuit = null;
            
            // 勝者成為下一輪的先手
            this.currentPlayer = this.players.findIndex(p => p.id === winner.id);
        }
        
        return winner;
    }

    isGameFinished() {
        return Object.values(this.hands).every(hand => hand.length === 0);
    }

    finalizeContract() {
        // 找最後一個有效叫牌
        for (let i = this.bids.length - 1; i >= 0; i--) {
            if (this.bids[i].bid !== null) {
                const [level, suit] = this.bids[i].bid;
                this.contract = [level, suit, this.bids[i].player];
                this.declarer = this.bids[i].player;
                this.trumpSuit = suit !== 'NT' ? suit : null;
                return;
            }
        }

        // 全部pass
        this.trumpSuit = null;
        this.contract = [1, 'NT', this.players[0]];
        this.declarer = this.players[0];
    }
}

// 註冊slash commands
const commands = [
    new SlashCommandBuilder()
        .setName('bridge')
        .setDescription('開始橋牌遊戲（2人或4人）')
        .addUserOption(option => 
            option.setName('玩家1')
                .setDescription('第一位玩家')
                .setRequired(true))
        .addUserOption(option => 
            option.setName('玩家2')
                .setDescription('第二位玩家（四人模式需要）')
                .setRequired(false))
        .addUserOption(option => 
            option.setName('玩家3')
                .setDescription('第三位玩家（四人模式需要）')
                .setRequired(false)),

    new SlashCommandBuilder()
        .setName('hand')
        .setDescription('查看您的手牌（僅您可見）'),

    new SlashCommandBuilder()
        .setName('gameinfo')
        .setDescription('查看當前遊戲狀態'),

    new SlashCommandBuilder()
        .setName('quit')
        .setDescription('退出當前遊戲'),

    new SlashCommandBuilder()
        .setName('testmode')
        .setDescription('切換測試模式（允許與機器人遊戲）')
        .addBooleanOption(option =>
            option.setName('enabled')
                .setDescription('是否啟用測試模式')
                .setRequired(false)),

    new SlashCommandBuilder()
        .setName('help')
        .setDescription('顯示橋牌機器人使用說明')
];

// 機器人事件
client.once('ready', async () => {
    console.log(`🎉 ${client.user.tag} 橋牌機器人已上線！`);
    console.log(`機器人ID: ${client.user.id}`);
    console.log(`連接到 ${client.guilds.cache.size} 個伺服器`);

    try {
        console.log('🔄 正在註冊slash commands...');
        await client.application.commands.set(commands);
        console.log('✅ 成功註冊所有slash commands');
    } catch (error) {
        console.error('❌ 註冊slash commands失敗:', error);
    }
});

// 處理slash commands
client.on('interactionCreate', async interaction => {
    if (!interaction.isChatInputCommand()) return;

    const { commandName } = interaction;

    try {
        if (commandName === 'bridge') {
            const player1 = interaction.options.getUser('玩家1');
            const player2 = interaction.options.getUser('玩家2');
            const player3 = interaction.options.getUser('玩家3');

            const players = [player1, player2, player3].filter(p => p !== null);
            
            if (![1, 3].includes(players.length)) {
                return interaction.reply({
                    content: "橋牌遊戲支援2人或4人！\n• 雙人橋牌：只標記 玩家1\n• 四人橋牌：標記 玩家1, 玩家2, 玩家3",
                    ephemeral: true
                });
            }

            if (players.some(p => p.bot) && !TEST_MODE) {
                return interaction.reply({
                    content: "不能與機器人遊戲！\n💡 提示：使用 `/testmode enabled:True` 啟用測試模式",
                    ephemeral: true
                });
            }

            const allPlayers = [interaction.user, ...players];
            if (new Set(allPlayers.map(p => p.id)).size !== allPlayers.length) {
                return interaction.reply({
                    content: "不能有重複的玩家！",
                    ephemeral: true
                });
            }

            if (games.has(interaction.channelId)) {
                return interaction.reply({
                    content: "這個頻道已經有遊戲在進行中！",
                    ephemeral: true
                });
            }

            // 創建新遊戲
            const game = new BridgeGame(interaction.channelId, allPlayers);
            game.dealCards();
            games.set(interaction.channelId, game);

            const embed = new EmbedBuilder()
                .setTitle('🃏 橋牌遊戲開始！')
                .setColor(0x00ff00)
                .addFields(
                    {
                        name: '遊戲說明',
                        value: '• 遊戲將先進行叫牌階段\n• 使用 `/hand` 查看手牌（僅自己可見）\n• 叫牌格式：`1♠️`, `2NT`, `3♥️` 或 `pass`\n• 出牌格式：直接輸入牌面，如 `♠️A` 或 `♥️K`',
                        inline: false
                    }
                );

            await interaction.reply({ embeds: [embed] });

            // 自動給每位玩家發送手牌
            for (const player of allPlayers) {
                try {
                    const handStr = game.getHandString(player.id);
                    const handEmbed = new EmbedBuilder()
                        .setTitle('您的手牌')
                        .setDescription(handStr)
                        .setColor(0x0099ff);
                    
                    await player.send({ embeds: [handEmbed] });
                } catch (error) {
                    console.log(`無法私訊 ${player.tag}，可能關閉了私訊功能`);
                }
            }

            const currentBidder = game.players[game.biddingPlayer];
            await interaction.followUp(`🎯 **叫牌階段開始！**\n輪到 ${currentBidder} 叫牌\n\n叫牌格式：\`1♠️\`, \`2NT\`, \`3♥️\`, \`pass\``);

        } else if (commandName === 'hand') {
            const game = games.get(interaction.channelId);
            if (!game) {
                return interaction.reply({ content: "目前沒有進行中的遊戲！", ephemeral: true });
            }

            if (!(interaction.user.id in game.hands)) {
                return interaction.reply({ content: "您不在這場遊戲中！", ephemeral: true });
            }

            const handStr = game.getHandString(interaction.user.id);
            const embed = new EmbedBuilder()
                .setTitle('您的手牌')
                .setDescription(handStr)
                .setColor(0x0099ff);

            await interaction.reply({ embeds: [embed], ephemeral: true });

        } else if (commandName === 'quit') {
            const game = games.get(interaction.channelId);
            if (!game) {
                return interaction.reply({
                    content: "目前沒有進行中的遊戲！",
                    flags: 64 // EPHEMERAL flag
                });
            }

            if (!game.players.some(p => p.id === interaction.user.id)) {
                return interaction.reply({
                    content: "您不在這場遊戲中！",
                    flags: 64 // EPHEMERAL flag
                });
            }

            games.delete(interaction.channelId);
            await interaction.reply(`${interaction.user} 退出了遊戲。遊戲已結束。`);

        } else if (commandName === 'gameinfo') {
            const game = games.get(interaction.channelId);
            if (!game) {
                return interaction.reply({
                    content: "目前沒有進行中的遊戲！",
                    flags: 64 // EPHEMERAL flag
                });
            }

            const embed = new EmbedBuilder()
                .setTitle('🃏 遊戲狀態')
                .setColor(0x00ff00);

            // 顯示玩家和模式
            if (game.playerCount === 2) {
                const playersStr = `**雙人橋牌**\n${game.players[0]} vs ${game.players[1]}`;
                embed.addFields({ name: '玩家', value: playersStr, inline: false });
                
                const scoreStr = `${game.players[0]}: ${game.scores[game.players[0].id]}\n${game.players[1]}: ${game.scores[game.players[1].id]}`;
                embed.addFields({ name: '當前得分', value: scoreStr, inline: true });
            } else {
                const playersStr = `**四人橋牌**\n**南北隊：** ${game.players[0]} & ${game.players[2]}\n**東西隊：** ${game.players[1]} & ${game.players[3]}`;
                embed.addFields({ name: '玩家', value: playersStr, inline: false });
                
                const teamScoreStr = `南北隊: ${game.teamScores['NS']}\n東西隊: ${game.teamScores['EW']}`;
                embed.addFields({ name: '隊伍得分', value: teamScoreStr, inline: true });
            }

            // 顯示遊戲階段
            const phaseText = game.gamePhase === "bidding" ? "叫牌階段" : "出牌階段";
            embed.addFields({ name: '遊戲階段', value: phaseText, inline: true });

            // 顯示當前回合
            if (game.gamePhase === "bidding") {
                const currentBidder = game.players[game.biddingPlayer];
                embed.addFields({ name: '當前叫牌者', value: currentBidder.toString(), inline: true });
            } else {
                const currentPlayer = game.players[game.currentPlayer];
                embed.addFields({ name: '當前回合', value: currentPlayer.toString(), inline: true });
            }

            await interaction.reply({ embeds: [embed] });

        } else if (commandName === 'testmode') {
            const enabled = interaction.options.getBoolean('enabled');
            
            if (enabled === null) {
                const status = TEST_MODE ? "啟用" : "停用";
                return interaction.reply({ content: `目前測試模式：**${status}**`, ephemeral: true });
            }

            TEST_MODE = enabled;
            const status = TEST_MODE ? "啟用" : "停用";
            await interaction.reply({ content: `測試模式已${status}！${TEST_MODE ? '(可與機器人遊戲)' : ''}`, ephemeral: true });

        } else if (commandName === 'help') {
            const embed = new EmbedBuilder()
                .setTitle('🃏 橋牌機器人使用說明')
                .setDescription('歡迎使用Discord橋牌機器人！支援雙人和四人橋牌遊戲。')
                .setColor(0x0099ff)
                .addFields(
                    {
                        name: '🎮 遊戲指令',
                        value: '**`/bridge`** - 開始新遊戲\n**`/hand`** - 查看手牌（僅自己可見）\n**`/gameinfo`** - 查看遊戲狀態\n**`/quit`** - 退出當前遊戲\n**`/testmode`** - 切換測試模式',
                        inline: false
                    },
                    {
                        name: '🎯 出牌方式',
                        value: '直接在聊天室輸入牌面：\n• `♠️A` - 黑桃A\n• `♥️K` - 紅心K\n• `♦️10` - 方塊10\n• `♣️J` - 梅花J',
                        inline: false
                    }
                );

            await interaction.reply({ embeds: [embed], ephemeral: true });
        }

    } catch (error) {
        console.error('處理slash command時發生錯誤:', error);
        if (!interaction.replied) {
            await interaction.reply({ content: '發生錯誤，請稍後再試！', ephemeral: true });
        }
    }
});

// 處理訊息（叫牌和出牌）
client.on('messageCreate', async message => {
    if (message.author.bot) return;

    const game = games.get(message.channelId);
    if (!game) return;

    if (!game.players.some(p => p.id === message.author.id)) return;

    if (game.gamePhase === "bidding") {
        // 叫牌階段
        const currentBidder = game.players[game.biddingPlayer];
        if (message.author.id !== currentBidder.id) {
            const temp = await message.channel.send(`${message.author} 還沒輪到您叫牌！`);
            setTimeout(() => temp.delete().catch(() => {}), 3000);
            return;
        }

        try {
            await message.delete();
        } catch {}

        const bidResult = game.makeBid(message.author.id, message.content);
        if (!bidResult.success) {
            const temp = await message.channel.send(`${message.author} ${bidResult.result}`);
            setTimeout(() => temp.delete().catch(() => {}), 5000);
            return;
        }

        const embed = new EmbedBuilder()
            .setTitle('叫牌')
            .setDescription(`${message.author} 叫了 **${bidResult.result}**`)
            .setColor(0x00bfff);

        await message.channel.send({ embeds: [embed] });

        if (game.checkBiddingEnd()) {
            game.finalizeContract();
            game.gamePhase = "playing";

            const contractEmbed = new EmbedBuilder()
                .setTitle('🎯 叫牌結束！')
                .setColor(0x00ff00)
                .addFields({
                    name: '現在開始出牌！',
                    value: '請按順序出牌，必須跟出相同花色（如果有的話）',
                    inline: false
                });

            await message.channel.send({ embeds: [contractEmbed] });

            const currentPlayer = game.players[game.currentPlayer];
            await message.channel.send(`輪到 ${currentPlayer} 出牌！`);
        } else {
            game.biddingPlayer = (game.biddingPlayer + 1) % game.playerCount;
            const nextBidder = game.players[game.biddingPlayer];
            await message.channel.send(`輪到 ${nextBidder} 叫牌！`);
        }
    
    } else if (game.gamePhase === "playing") {
        // 出牌階段
        const currentPlayer = game.players[game.currentPlayer];
        if (message.author.id !== currentPlayer.id) {
            const temp = await message.channel.send(`${message.author} 還沒輪到您出牌！`);
            setTimeout(() => temp.delete().catch(() => {}), 3000);
            return;
        }

        // 嘗試解析出牌
        const card = game.parseCardInput(message.content);
        if (!card) {
            return; // 不是有效的出牌格式，忽略
        }

        try {
            await message.delete();
        } catch {}

        // 嘗試出牌
        const playResult = game.playCard(message.author.id, card);
        if (!playResult.canPlay) {
            const temp = await message.channel.send(`${message.author} ${playResult.reason}`);
            setTimeout(() => temp.delete().catch(() => {}), 5000);
            return;
        }

        // 宣布出牌
        const embed = new EmbedBuilder()
            .setTitle('🃏 出牌')
            .setDescription(`${message.author} 出了 **${card}**`)
            .setColor(0xffd700);

        // 顯示當前合約
        if (game.contract) {
            const [level, suit, declarer] = game.contract;
            const trumpInfo = suit !== 'NT' ? `王牌：${suit}` : '無王';
            embed.addFields({ name: '當前合約', value: `${level}${suit} by ${declarer.username}\n${trumpInfo}`, inline: true });
        }

        // 顯示當前trick狀態
        const trickDisplay = game.currentTrick.map((t, index) => {
            const playerName = t.player.username;
            const cardStr = `${t.card}`;
            const isLeader = index === 0 ? ' (領牌)' : '';
            return `${playerName}: ${cardStr}${isLeader}`;
        }).join('\n');
        
        embed.addFields({ name: '當前Trick', value: trickDisplay, inline: false });

        // 顯示出牌規則提示
        if (game.currentTrick.length === 1) {
            const leadSuit = game.currentTrick[0].card.suit;
            embed.addFields({ 
                name: '出牌規則', 
                value: `必須跟出 ${leadSuit} 花色（如果有的話）${game.trumpSuit ? `\n王牌 ${game.trumpSuit} 可以吃其他花色` : ''}`, 
                inline: false 
            });
        }

        if (game.currentTrick.length < game.playerCount) {
            // 還沒滿一輪，切換到下一位玩家
            game.currentPlayer = (game.currentPlayer + 1) % game.playerCount;
            const nextPlayer = game.players[game.currentPlayer];
            embed.addFields({ name: '⏭️ 下一位出牌', value: `輪到 ${nextPlayer} 出牌`, inline: false });
            
            // 顯示剩餘玩家數
            const remaining = game.playerCount - game.currentTrick.length;
            embed.addFields({ name: '本輪狀態', value: `還需要 ${remaining} 位玩家出牌`, inline: true });
        } else {
            // 一輪完成，評估trick勝者
            const winner = game.finishTrick();
            embed.addFields({ name: '🏆 Trick勝者', value: `${winner} 獲勝！`, inline: false });
            
            // 顯示勝牌原因
            const winningTrick = game.tricks[game.tricks.length - 1];
            const winningCard = winningTrick.trick.find(t => t.player.id === winner.id).card;
            let winReason = '';
            
            if (game.trumpSuit && winningCard.suit === game.trumpSuit) {
                winReason = `(${winningCard} 是王牌)`;
            } else if (winningCard.suit === game.leadSuit) {
                winReason = `(${winningCard} 是最大的${game.leadSuit})`;
            } else {
                winReason = `(${winningCard} 獲勝)`;
            }
            
            embed.addFields({ name: '勝牌原因', value: winReason, inline: true });

            // 顯示當前得分
            if (game.playerCount === 2) {
                const scoreStr = `${game.players[0]}: ${game.scores[game.players[0].id]} tricks\n${game.players[1]}: ${game.scores[game.players[1].id]} tricks`;
                embed.addFields({ name: '當前得分', value: scoreStr, inline: true });
            } else {
                const teamScoreStr = `南北隊: ${game.teamScores['NS']} tricks\n東西隊: ${game.teamScores['EW']} tricks`;
                embed.addFields({ name: '隊伍得分', value: teamScoreStr, inline: true });
            }

            // 檢查遊戲是否結束
            if (game.isGameFinished()) {
                await message.channel.send({ embeds: [embed] });

                // 創建最終結果
                const finalEmbed = new EmbedBuilder()
                    .setTitle('🎉 遊戲結束！')
                    .setColor(0xff6b6b);

                let scoreText = "";
                if (game.playerCount === 2) {
                    const gameWinner = game.getWinner();
                    scoreText = `**勝者：${gameWinner}**\n\n**最終得分：**\n`;
                    for (const player of game.players) {
                        scoreText += `${player}: ${game.scores[player.id]} tricks\n`;
                    }
                } else {
                    const winnerTeam = game.getWinner();
                    if (winnerTeam === "NS") {
                        scoreText = `**勝者：南北隊 🏆**\n${game.players[0]} & ${game.players[2]}\n\n`;
                    } else if (winnerTeam === "EW") {
                        scoreText = `**勝者：東西隊 🏆**\n${game.players[1]} & ${game.players[3]}\n\n`;
                    } else {
                        scoreText = `**平手！** 🤝\n\n`;
                    }
                    
                    scoreText += `**隊伍得分：**\n南北隊: ${game.teamScores['NS']} tricks\n東西隊: ${game.teamScores['EW']} tricks\n\n`;
                    scoreText += `**個人得分：**\n`;
                    for (const player of game.players) {
                        const position = game.positions[player.id];
                        scoreText += `${player} (${position}): ${game.scores[player.id]} tricks\n`;
                    }
                }

                // 顯示合約完成情況
                if (game.contract) {
                    const [level, suit, declarer] = game.contract;
                    const target = level + 6; // 基本6墩 + 叫牌墩數
                    let madeTricks;
                    
                    if (game.playerCount === 4) {
                        if ([game.players[0].id, game.players[2].id].includes(declarer.id)) {
                            madeTricks = game.teamScores["NS"];
                        } else {
                            madeTricks = game.teamScores["EW"];
                        }
                    } else {
                        madeTricks = game.scores[declarer.id];
                    }
                    
                    const contractResult = madeTricks >= target ? "✅ 完成" : "❌ 失敗";
                    scoreText += `\n**合約結果：**\n${level}${suit} - ${contractResult} (${madeTricks}/${target})`;
                }

                finalEmbed.addFields({ name: '最終結果', value: scoreText, inline: false });
                await message.channel.send({ embeds: [finalEmbed] });

                // 清理遊戲
                games.delete(message.channelId);
                return;
            } else {
                // 設置下一輪的先手（trick勝者）
                game.currentPlayer = game.players.findIndex(p => p.id === winner.id);
                const nextPlayer = game.players[game.currentPlayer];
                embed.addFields({ name: '🎯 下一輪先手', value: `${nextPlayer} 先出牌（贏得了上一trick）`, inline: false });
                
                // 顯示剩餘手牌信息
                const remainingCards = Object.values(game.hands).reduce((sum, hand) => sum + hand.length, 0);
                const tricksPlayed = game.tricks.length;
                const totalTricks = game.playerCount === 2 ? 26 : 13;
                embed.addFields({ name: '遊戲進度', value: `已完成 ${tricksPlayed}/${totalTricks} tricks`, inline: true });
            }
        }

        await message.channel.send({ embeds: [embed] });
    }
});

// 錯誤處理
client.on('error', console.error);

// 啟動機器人
const token = process.env.DISCORD_TOKEN;
if (!token) {
    console.error('❌ 錯誤：找不到DISCORD_TOKEN環境變數');
    process.exit(1);
}

console.log('🚀 正在啟動Discord橋牌機器人...');
console.log(`Token前綴: ${token.substring(0, 20)}...`);

client.login(token).catch(error => {
    console.error('❌ 機器人登入失敗:', error);
    process.exit(1);
});
