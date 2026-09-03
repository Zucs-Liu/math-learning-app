"""Centralized, behavior-free configuration for the math adventure game.

Keep only static values in this module. Database access, Streamlit widgets and
gameplay functions remain in ``app.py`` so this file is safe to import locally
and on Streamlit Community Cloud.
"""

MAX_QUESTIONS = 20
PROFILE_CACHE_SECONDS = 300
SHORT_LOGIN_SECONDS = 300

BOSS_CONFIGS = {
    "1_normal": {"name": "荒野魔狼", "element": "dark", "image": "wild-wolf.webp", "hp": 300, "damage": 10, "interval": 2.0, "exp": 100},
    "1_elite": {"name": "血月狼人", "element": "dark", "image": "blood-moon-werewolf.webp", "hp": 400, "damage": 30, "interval": 1.5, "exp": 150},
    "2_normal": {"name": "刺甲蜘蛛", "element": "earth", "image": "thorn-armor-spider.webp", "hp": 600, "damage": 20, "interval": 2.0, "exp": 150},
    "2_elite": {"name": "魅惑影蛛", "element": "dark", "image": "charming-shadow-spider.webp", "hp": 800, "damage": 60, "interval": 1.5, "exp": 200},
    "3_normal": {"name": "深淵魔龍", "element": "wood", "image": "abyss-dragon.webp", "hp": 900, "damage": 30, "interval": 2.0, "exp": 200, "critical_rate": 0.50},
    "3_elite": {"name": "烈焰龍王", "element": "fire", "image": "flame-dragon-king.webp", "hp": 1200, "damage": 90, "interval": 1.5, "exp": 250, "skill": "火龍斬", "skill_interval": 5.0, "true_damage": 50},
    "4_normal": {"name": "六尾雷狐", "element": "light", "image": "six-tail-thunder-fox.webp", "hp": 1200, "damage": 40, "interval": 2.0, "exp": 250, "defense_reduction": 20},
    "4_elite": {"name": "九尾天狐", "element": "light", "image": "nine-tail-celestial-fox.webp", "hp": 1600, "damage": 120, "interval": 1.5, "exp": 300, "skill": "天降雷劫", "skill_hp_threshold": 0.5, "true_damage": 70},
    "5_normal": {"name": "寒冰巨鯰", "element": "water", "image": "ice-giant-catfish.webp", "hp": 1500, "damage": 50, "interval": 2.0, "exp": 300, "hero_speed_reduction": 0.4},
    "5_elite": {"name": "暴風熊王", "element": "water", "image": "storm-bear-king.webp", "hp": 2000, "damage": 150, "interval": 1.5, "exp": 350, "skill": "狂風驟雨", "hero_damage_reduction": 0.40, "skill_at_start": True},
    "6_normal": {"name": "巨爪鼠", "element": "earth", "image": "giant-claw-rat.webp", "hp": 1800, "damage": 60, "interval": 2.0, "exp": 350, "hero_damage_reduction": 0.25, "passive": "戰鬥即發動，勇者造成的傷害降低25%，直到戰鬥結束。", "skill_at_start": True},
    "6_elite": {"name": "鬼火王", "element": "fire", "image": "ghost-flame-king.webp", "hp": 2400, "damage": 180, "interval": 1.5, "exp": 400, "skill": "烈鬼焚身", "skill_interval": 1.0, "true_damage": 30, "true_damage_below_half": 50, "skill_at_start": True},
}

BOSS_MAX_HP = 400
BOSS_DAMAGE = 30
BOSS_ATTACK_INTERVAL = 2.0
BOSS_EXP = 100
EXP_BY_STARS = {0: 0, 1: 20, 2: 40, 3: 60}

BLOCKED_NAME_WORDS = {
    "fuck", "shit", "bitch", "asshole", "dick", "penis", "pussy", "sex",
    "幹你", "幹您", "幹林", "操你", "操妳", "媽的", "馬的", "靠北", "靠杯",
    "白癡", "智障", "低能", "垃圾", "去死", "雞掰", "機掰", "懶叫", "覽叫",
    "陰莖", "陰道", "性交", "色情",
}

SLOT_NAMES = {
    "helmet": "頭盔",
    "armor": "護甲",
    "gloves": "手套",
    "weapon": "武器",
    "boots": "靴子",
    "necklace": "護身符／項鍊",
    "ring": "戒指",
    "belt": "腰帶",
    "shield": "盾牌",
}

SLOT_ICONS = {
    "helmet": "🪖", "armor": "🥋", "gloves": "🧤", "weapon": "⚔️",
    "boots": "🥾", "necklace": "🧿", "ring": "💍", "belt": "🪢", "shield": "🛡️",
}

CHAPTERS = {
    "1": {"number": "第一章", "name": "整數加減法"},
    "2": {"number": "第二章", "name": "整數的乘除法"},
    "3": {"number": "第三章", "name": "小數的加減法"},
    "4": {"number": "第四章", "name": "小數乘除法"},
    "5": {"number": "第五章", "name": "因倍數與分數"},
    "6": {"number": "第六章", "name": "比與比值"},
}

UNITS = {
    "1-1": {"name": "二位數加減一位數", "slots": ["helmet", "armor", "boots"], "description": "例如：46＋7、52－8"},
    "1-2": {"name": "二位數加減二位數", "slots": ["gloves", "weapon", "necklace"], "description": "例如：46＋27、82－35"},
    "1-3": {"name": "三位數加減二位數", "slots": ["ring", "belt", "shield"], "description": "例如：426＋37、582－46"},
    "2-1": {"name": "二位數乘以一位數", "slots": ["helmet", "gloves", "weapon"], "description": "例如：24×3、56×7"},
    "2-2": {"name": "二位數除以一位數（整除）", "slots": ["armor", "boots"], "description": "例如：84÷7、96÷8"},
    "2-3": {"name": "三位數乘以一位數", "slots": ["necklace", "ring"], "description": "例如：126×4、315×3"},
    "2-4": {"name": "三位數除以一位數（整除）", "slots": ["belt", "shield"], "description": "例如：864÷8、735÷7"},
    "3-1": {"name": "一位小數加減一位小數", "slots": ["helmet", "armor", "gloves", "weapon", "boots"], "description": "例如：8.7－0.6、12.4＋3.5"},
    "3-2": {"name": "一位小數加減二位小數", "slots": ["necklace", "ring", "belt", "shield"], "description": "例如：12.6＋3.56、18.4－2.75"},
    "4-1": {"name": "一位小數乘以一位整數", "slots": ["helmet", "armor"], "description": "例如：1.2×7"},
    "4-2": {"name": "一位小數乘以一位小數", "slots": ["gloves", "weapon"], "description": "例如：1.2×0.3（乘數個位數為0）"},
    "4-3": {"name": "一位小數除以一位整數（整除）", "slots": ["boots", "necklace"], "description": "例如：1.2÷4"},
    "4-4": {"name": "一位小數除以一位小數（整除）", "slots": ["ring", "belt", "shield"], "description": "例如：1.2÷0.3（除數個位數為0）"},
    "5-1": {"name": "最大公因數", "slots": ["helmet", "armor", "gloves"], "description": "例如：（15，20）的最大公因數＝5"},
    "5-2": {"name": "最小公倍數", "slots": ["weapon", "boots", "necklace"], "description": "例如：（4，9）的最小公倍數＝36"},
    "5-3": {"name": "最簡分數", "slots": ["ring", "belt", "shield"], "description": "例如：78／65＝6／5"},
    "6-1": {"name": "最簡整數比", "slots": ["helmet", "armor", "gloves"], "description": "例如：8：6＝4：3、0.4：5＝2：25"},
    "6-2": {"name": "計算比值", "slots": ["weapon", "boots", "necklace"], "description": "例如：20：50的比值＝2／5"},
    "6-3": {"name": "比例式的計算", "slots": ["ring", "belt", "shield"], "description": "例如：2：7＝（　）：14"},
}

FIXED_STATS = {
    "helmet": ("hp", {1: 8, 2: 14, 3: 20, 4: 25}),
    "armor": ("defense", {1: 2, 2: 4, 3: 6, 4: 8}),
    "gloves": ("attack", {1: 1, 2: 2, 3: 3, 4: 6}),
    "weapon": ("attack", {1: 2, 2: 4, 3: 6, 4: 8}),
    "boots": ("attack_speed", {1: 0.10, 2: 0.12, 3: 0.13, 4: 0.23}),
    "necklace": ("boss_hp_reduction", {1: 0.03, 2: 0.06, 3: 0.10, 4: 0.13}),
    "ring": ("first_hit_percent", {1: 0.03, 2: 0.06, 3: 0.10, 4: 0.13}),
    "belt": ("hp", {1: 6, 2: 11, 3: 16, 4: 20}),
    "shield": ("defense", {1: 1, 2: 3, 3: 5, 4: 7}),
}

CHAPTER_FIXED_INCREMENTS = {
    "helmet": 4, "armor": 3, "gloves": 2, "weapon": 3,
    "boots": 0.05, "necklace": 0.02, "ring": 0.02,
    "belt": 3, "shield": 2,
}

AFFIX_NAMES = {
    "attack_pct": "攻擊力",
    "speed_pct": "攻擊速度",
    "hp_pct": "HP",
    "defense_pct": "防禦力",
    "boss_damage_pct": "對菁英BOSS傷害",
    "damage_reduction_pct": "受到傷害降低",
    "critical_rate": "暴擊率",
    "critical_damage": "暴擊傷害",
    "shield_pct": "開場護盾",
    "boss_attack_slow_pct": "菁英BOSS攻擊速度降低",
}

AFFIX_VALUES = {
    "default": {1: [0.05, 0.10], 2: [0.05, 0.10, 0.15], 3: [0.10, 0.15, 0.20]},
    "boss_damage_pct": {1: [0.05, 0.08], 2: [0.08, 0.12], 3: [0.12, 0.18]},
    "damage_reduction_pct": {1: [0.03, 0.05], 2: [0.05, 0.08], 3: [0.08, 0.12]},
    "critical_rate": {1: [0.05, 0.08], 2: [0.08, 0.10], 3: [0.10, 0.15]},
    "critical_damage": {1: [0.15, 0.20], 2: [0.20, 0.30], 3: [0.30, 0.40]},
    "shield_pct": {1: [0.05, 0.10], 2: [0.10, 0.15], 3: [0.15, 0.20]},
    "boss_attack_slow_pct": {1: [0.03, 0.05], 2: [0.05, 0.08], 3: [0.08, 0.12]},
}

GEAR_NAMES = {
    1: {"helmet": "皮革頭盔", "armor": "旅行護甲", "gloves": "靈巧手套", "weapon": "見習短劍", "boots": "輕風鞋", "necklace": "虛弱護符", "ring": "火花戒指", "belt": "皮革腰帶", "shield": "木製盾牌"},
    2: {"helmet": "精鋼頭盔", "armor": "騎士護甲", "gloves": "戰鬥手套", "weapon": "精鋼長劍", "boots": "疾風戰靴", "necklace": "破甲護符", "ring": "烈焰戒指", "belt": "鬥士腰帶", "shield": "精鋼盾牌"},
    3: {"helmet": "英雄頭盔", "armor": "勇者鎧甲", "gloves": "英雄手套", "weapon": "勇者聖劍", "boots": "暴風之翼", "necklace": "魔王剋星", "ring": "隕星戒指", "belt": "巨人腰帶", "shield": "英雄盾牌"},
}
