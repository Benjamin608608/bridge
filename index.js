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
            const suitMapping = {
                '♣': '♣️', 'C': '♣️', 'CLUBS': '♣️', '梅花': '♣️',
                '♦': '♦️', 'D': '♦️', 'DIAMONDS': '♦️', '方塊': '♦️',
                '♥': '♥️', 'H': '♥️', 'HEARTS': '♥️', '紅心': '♥️',
                '♠': '♠️', 'S': '♠️', 'SPADES': '♠️', '黑桃': '♠️',
                'NT': 'NT', 'N': 'NT', 'NOTRUMP': 'NT', '無王': 'NT'
            };

            for (const [key, value] of Object.entries(suitMapping)) {
                if (suitStr.startsWith(key)) {
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
