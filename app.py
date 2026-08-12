import base64
import io
import json
import hashlib
import hmac
import math
import os
import random
import re
import secrets
import sqlite3
import time
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import streamlit as st
import streamlit.components.v1 as components
from PIL import Image

try:
    import psycopg
    from psycopg_pool import ConnectionPool
    from psycopg.rows import dict_row
except ImportError:
    psycopg = None
    ConnectionPool = None


st.set_page_config(page_title="數學冒險", page_icon="⚔️", layout="wide")

# Streamlit新版會把上一頁的頁籤列暫時黏在畫面上方，切換到商店等頁面時
# 可能看見「目前裝備／背包／圖鑑收集」殘留；取消頁籤列的 sticky 定位。
st.markdown(
    """
    <style>
    div[data-baseweb="tab-list"],
    div[data-testid="stTabs"] div[role="tablist"] {
        position: static !important;
        top: auto !important;
    }
    div[data-testid="stTabs"] {
        position: static !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

MAX_QUESTIONS = 20
BOSS_CONFIGS = {
    "1_normal": {"name": "負數魔獸", "hp": 600, "damage": 30, "interval": 3.0, "exp": 100},
    "1_elite": {"name": "整數霸主", "hp": 900, "damage": 45, "interval": 2.5, "exp": 150},
    "2_normal": {"name": "乘除巨像", "hp": 800, "damage": 36, "interval": 3.0, "exp": 150},
    "2_elite": {"name": "乘除霸主", "hp": 1200, "damage": 54, "interval": 2.5, "exp": 200},
    "3_normal": {"name": "小數暴擊獸", "hp": 1050, "damage": 45, "interval": 3.0, "exp": 200, "critical_rate": 0.20},
    "3_elite": {"name": "烈焰小數龍", "hp": 1550, "damage": 62, "interval": 2.5, "exp": 250, "skill": "火龍斬", "skill_interval": 5.0, "true_damage": 20},
}
BOSS_MAX_HP = 400
BOSS_DAMAGE = 30
BOSS_ATTACK_INTERVAL = 3.0
BOSS_EXP = 100
DB_FILE = Path("game.db")


def secret_value(key):
    if os.environ.get(key):
        return os.environ[key]
    try:
        return st.secrets.get(key)
    except FileNotFoundError:
        return None


DATABASE_URL = secret_value("DATABASE_URL")
ADMIN_PIN_SECRET = secret_value("ADMIN_PIN")
USE_POSTGRES = bool(DATABASE_URL)
TAIPEI_TZ = ZoneInfo("Asia/Taipei")
EXP_BY_STARS = {0: 0, 1: 20, 2: 40, 3: 60}

BLOCKED_NAME_WORDS = {
    "fuck", "shit", "bitch", "asshole", "dick", "penis", "pussy", "sex",
    "幹你", "幹您", "幹林", "操你", "操妳", "媽的", "馬的", "靠北", "靠杯",
    "白癡", "智障", "低能", "垃圾", "去死", "雞掰", "機掰", "懶叫", "覽叫",
    "陰莖", "陰道", "性交", "色情",
}


def database_timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def taipei_time_text(value):
    if not value:
        return ""
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        # 公開版早期紀錄由 UTC 伺服器寫入，但當時未附時區。
        parsed = parsed.replace(tzinfo=timezone.utc if USE_POSTGRES else TAIPEI_TZ)
    return parsed.astimezone(TAIPEI_TZ).strftime("%Y-%m-%d %H:%M:%S")


def normalized_hero_name(name):
    return name.casefold()


def validate_hero_name(name):
    if not name:
        return "請輸入勇者名稱。"
    if not re.fullmatch(r"[A-Za-z0-9\u3400-\u4DBF\u4E00-\u9FFF]+", name):
        return "勇者名稱只能使用中文、英文字母與數字，不能包含空格或符號。"
    normalized = normalized_hero_name(name)
    if any(word in normalized for word in BLOCKED_NAME_WORDS):
        return "此勇者名稱含有不適合公開顯示的文字，請更換名稱。"
    return None

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
    "1": {"number": "第一章", "name": "整數加減法", "multiplier": 1.00},
    "2": {"number": "第二章", "name": "整數的乘除法", "multiplier": 1.15},
    "3": {"number": "第三章", "name": "小數的加減法", "multiplier": 1.30},
}

UNITS = {
    "1-1": {
        "name": "二位數加減一位數",
        "slots": ["helmet", "armor", "boots"],
        "description": "例如：46＋7、52－8",
    },
    "1-2": {
        "name": "二位數加減二位數",
        "slots": ["gloves", "weapon", "necklace"],
        "description": "例如：46＋27、82－35",
    },
    "1-3": {
        "name": "三位數加減二位數",
        "slots": ["ring", "belt", "shield"],
        "description": "例如：426＋37、582－46",
    },
    "2-1": {
        "name": "二位數乘以一位數",
        "slots": ["helmet", "gloves", "weapon"],
        "description": "例如：24×3、56×7",
    },
    "2-2": {
        "name": "二位數除以一位數（整除）",
        "slots": ["armor", "boots"],
        "description": "例如：84÷7、96÷8",
    },
    "2-3": {
        "name": "三位數乘以一位數",
        "slots": ["necklace", "ring"],
        "description": "例如：126×4、315×3",
    },
    "2-4": {
        "name": "三位數除以一位數（整除）",
        "slots": ["belt", "shield"],
        "description": "例如：864÷8、735÷7",
    },
    "3-1": {
        "name": "一位小數加減一位小數",
        "slots": ["helmet", "armor", "gloves", "weapon", "boots"],
        "description": "例如：8.7－0.6、12.4＋3.5",
    },
    "3-2": {
        "name": "一位小數加減二位小數",
        "slots": ["necklace", "ring", "belt", "shield"],
        "description": "例如：12.6＋3.56、18.4－2.75",
    },
}


def chapter_unit_ids(chapter_id):
    return [unit_id for unit_id in UNITS if unit_id.startswith(f"{chapter_id}-")]

FIXED_STATS = {
    "helmet": ("hp", {1: 8, 2: 14, 3: 20, 4: 25}),
    "armor": ("defense", {1: 2, 2: 4, 3: 6, 4: 8}),
    "gloves": ("attack", {1: 1, 2: 2, 3: 4, 4: 6}),
    "weapon": ("attack", {1: 2, 2: 4, 3: 6, 4: 8}),
    "boots": ("attack_speed", {1: 0.03, 2: 0.06, 3: 0.10, 4: 0.13}),
    "necklace": ("boss_hp_reduction", {1: 0.03, 2: 0.06, 3: 0.10, 4: 0.13}),
    "ring": ("first_hit_percent", {1: 0.03, 2: 0.06, 3: 0.10, 4: 0.13}),
    "belt": ("hp", {1: 6, 2: 11, 3: 16, 4: 20}),
    "shield": ("defense", {1: 1, 2: 3, 3: 5, 4: 7}),
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

DEFAULT_STATE = {
    "screen": "bootstrap",
    "active_player": None,
    "admin_authenticated": False,
    "created_account": None,
    "selected_unit": None,
    "selected_chapter": "1",
    "deadline": None,
    "quiz_started_at": None,
    "quiz_elapsed": 0.0,
    "question": None,
    "answer_input": None,
    "correct": 0,
    "attempts": 0,
    "combo": 0,
    "max_combo": 0,
    "message": "",
    "stars": 0,
    "result_processed": False,
    "pending_item_uid": None,
    "drop_exhausted": False,
    "earned_exp": 0,
    "level_up_to": None,
    "chapter_reward_new": False,
    "collection_reward_new": False,
    "collection_level_up_to": None,
    "extra_reward_messages": [],
    "battle_events": None,
    "battle_started_at": None,
    "battle_result": None,
    "battle_recorded": False,
    "selected_boss_type": "normal",
    "answer_history": [],
    "shop_purchase_uid": None,
    "forge_result_uid": None,
    "economy_tab": "shop",
    "economy_mode": "shop",
    "scroll_economy_to_top": False,
    "scroll_inventory_to_top": False,
    "scroll_ranking_to_top": False,
    "scroll_boss_to_top": False,
    "sweep_result_uid": None,
    "inventory_default_tab": "目前裝備",
    "inventory_tab_version": 0,
}

for key, value in DEFAULT_STATE.items():
    if key not in st.session_state:
        st.session_state[key] = value


@st.cache_resource(show_spinner=False)
def postgres_pool():
    if ConnectionPool is None:
        raise RuntimeError("公開版需要安裝 psycopg[pool]。")
    return ConnectionPool(
        conninfo=DATABASE_URL,
        min_size=1,
        max_size=10,
        timeout=15,
        max_lifetime=300,
        max_idle=60,
        reconnect_timeout=30,
        check=ConnectionPool.check_connection,
        kwargs={"row_factory": dict_row},
    )


class DatabaseConnection:
    def _open_postgres_connection(self):
        self.pool_context = postgres_pool().connection()
        self.connection = self.pool_context.__enter__()

    def __enter__(self):
        if USE_POSTGRES:
            self._open_postgres_connection()
        else:
            self.connection = sqlite3.connect(DB_FILE, timeout=10)
            self.connection.row_factory = sqlite3.Row
            self.connection.execute("PRAGMA journal_mode=WAL")
            self.connection.execute("PRAGMA foreign_keys=ON")
        return self

    def __exit__(self, error_type, error, traceback):
        if USE_POSTGRES:
            return self.pool_context.__exit__(error_type, error, traceback)
        if error_type:
            self.connection.rollback()
        else:
            self.connection.commit()
        self.connection.close()

    def execute(self, sql, parameters=()):
        if USE_POSTGRES:
            if sql == "BEGIN IMMEDIATE":
                return self.connection.execute("BEGIN")
            sql = sql.replace("INSERT OR IGNORE INTO", "INSERT INTO")
            if "INSERT INTO settings" in sql and "registration_enabled" in sql and "ON CONFLICT" not in sql:
                sql += " ON CONFLICT(key) DO NOTHING"
            sql = sql.replace("?", "%s")
            try:
                return self.connection.execute(sql, parameters)
            except psycopg.OperationalError:
                # Neon 免費方案喚醒或重啟時可能終止既有連線；唯讀查詢可安全重連一次。
                if not sql.lstrip().upper().startswith("SELECT"):
                    raise
                self.pool_context.__exit__(*__import__("sys").exc_info())
                self._open_postgres_connection()
                return self.connection.execute(sql, parameters)
        return self.connection.execute(sql, parameters)

    def executescript(self, script):
        if USE_POSTGRES:
            for statement in script.split(";"):
                if statement.strip():
                    self.connection.execute(statement)
        else:
            self.connection.executescript(script)


def db_connection():
    return DatabaseConnection()


@st.cache_resource(show_spinner=False)
def init_db():
    with db_connection() as db:
        db.executescript(
            f"""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS players (
                student_code TEXT PRIMARY KEY,
                hero_name TEXT NOT NULL,
                real_name TEXT NOT NULL DEFAULT '',
                pin_salt TEXT NOT NULL,
                pin_hash TEXT NOT NULL,
                profile_json TEXT NOT NULL,
                failed_attempts INTEGER NOT NULL DEFAULT 0,
                locked_until REAL NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS rankings (
                student_code TEXT PRIMARY KEY,
                hero_name TEXT NOT NULL,
                level INTEGER NOT NULL,
                clear_time REAL NOT NULL,
                achieved_at TEXT NOT NULL,
                FOREIGN KEY(student_code) REFERENCES players(student_code) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS elite_rankings (
                student_code TEXT PRIMARY KEY,
                hero_name TEXT NOT NULL,
                level INTEGER NOT NULL,
                clear_time REAL NOT NULL,
                achieved_at TEXT NOT NULL,
                FOREIGN KEY(student_code) REFERENCES players(student_code) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS chapter2_rankings (
                student_code TEXT PRIMARY KEY, hero_name TEXT NOT NULL, level INTEGER NOT NULL,
                clear_time REAL NOT NULL, achieved_at TEXT NOT NULL,
                FOREIGN KEY(student_code) REFERENCES players(student_code) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS chapter2_elite_rankings (
                student_code TEXT PRIMARY KEY, hero_name TEXT NOT NULL, level INTEGER NOT NULL,
                clear_time REAL NOT NULL, achieved_at TEXT NOT NULL,
                FOREIGN KEY(student_code) REFERENCES players(student_code) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS chapter3_rankings (
                student_code TEXT PRIMARY KEY, hero_name TEXT NOT NULL, level INTEGER NOT NULL,
                clear_time REAL NOT NULL, achieved_at TEXT NOT NULL,
                FOREIGN KEY(student_code) REFERENCES players(student_code) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS chapter3_elite_rankings (
                student_code TEXT PRIMARY KEY, hero_name TEXT NOT NULL, level INTEGER NOT NULL,
                clear_time REAL NOT NULL, achieved_at TEXT NOT NULL,
                FOREIGN KEY(student_code) REFERENCES players(student_code) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS attempts (
                id {"BIGSERIAL PRIMARY KEY" if USE_POSTGRES else "INTEGER PRIMARY KEY AUTOINCREMENT"},
                student_code TEXT NOT NULL,
                unit_id TEXT NOT NULL,
                stars INTEGER NOT NULL,
                max_combo INTEGER NOT NULL,
                correct_count INTEGER NOT NULL,
                elapsed_seconds REAL NOT NULL DEFAULT 0,
                average_seconds REAL NOT NULL DEFAULT 0,
                finished_at TEXT NOT NULL,
                FOREIGN KEY(student_code) REFERENCES players(student_code) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS question_logs (
                id {"BIGSERIAL PRIMARY KEY" if USE_POSTGRES else "INTEGER PRIMARY KEY AUTOINCREMENT"},
                student_code TEXT NOT NULL,
                unit_id TEXT NOT NULL,
                question_text TEXT NOT NULL,
                submitted_answer REAL NOT NULL,
                correct_answer REAL NOT NULL,
                is_correct INTEGER NOT NULL,
                combo_after INTEGER NOT NULL,
                elapsed_seconds REAL NOT NULL DEFAULT 0,
                answered_at TEXT NOT NULL,
                FOREIGN KEY(student_code) REFERENCES players(student_code) ON DELETE CASCADE
            );
            """
        )
        db.execute("INSERT OR IGNORE INTO settings(key, value) VALUES('registration_enabled', '1')")
        if USE_POSTGRES:
            db.execute("ALTER TABLE attempts ADD COLUMN IF NOT EXISTS elapsed_seconds REAL NOT NULL DEFAULT 0")
            db.execute("ALTER TABLE attempts ADD COLUMN IF NOT EXISTS average_seconds REAL NOT NULL DEFAULT 0")
            db.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS real_name TEXT NOT NULL DEFAULT ''")
            db.execute("ALTER TABLE question_logs ALTER COLUMN submitted_answer TYPE DOUBLE PRECISION USING submitted_answer::DOUBLE PRECISION")
            db.execute("ALTER TABLE question_logs ALTER COLUMN correct_answer TYPE DOUBLE PRECISION USING correct_answer::DOUBLE PRECISION")
        else:
            attempt_columns = {
                row["name"] for row in db.execute("PRAGMA table_info(attempts)").fetchall()
            }
            if "elapsed_seconds" not in attempt_columns:
                db.execute("ALTER TABLE attempts ADD COLUMN elapsed_seconds REAL NOT NULL DEFAULT 0")
            if "average_seconds" not in attempt_columns:
                db.execute("ALTER TABLE attempts ADD COLUMN average_seconds REAL NOT NULL DEFAULT 0")
            player_columns = {
                row["name"] for row in db.execute("PRAGMA table_info(players)").fetchall()
            }
            if "real_name" not in player_columns:
                db.execute("ALTER TABLE players ADD COLUMN real_name TEXT NOT NULL DEFAULT ''")
    return True


def setting_get(key):
    with db_connection() as db:
        row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else None


def setting_set(key, value):
    with db_connection() as db:
        db.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )


def pin_digest(pin, salt_hex):
    return hashlib.scrypt(
        pin.encode("utf-8"), salt=bytes.fromhex(salt_hex), n=2**14, r=8, p=1
    ).hex()


def make_pin_hash(pin):
    salt = secrets.token_bytes(16).hex()
    return salt, pin_digest(pin, salt)


def set_admin_pin(pin):
    salt, digest = make_pin_hash(pin)
    setting_set("admin_pin_salt", salt)
    setting_set("admin_pin_hash", digest)


def verify_admin_pin(pin):
    if ADMIN_PIN_SECRET:
        return hmac.compare_digest(pin, str(ADMIN_PIN_SECRET))
    salt = setting_get("admin_pin_salt")
    expected = setting_get("admin_pin_hash")
    return bool(salt and expected and hmac.compare_digest(pin_digest(pin, salt), expected))


def new_profile(name):
    return {
        "data_version": 2,
        "name": name,
        "avatar_data": None,
        "level": 1,
        "exp": 0,
        "coins": 0,
        "smelting_stones": 0,
        "slot_smelting_stones": 0,
        "basic_affix_smelting_stones": 0,
        "advanced_affix_smelting_stones": 0,
        "sweep_tickets": 0,
        "ticket_rewarded_units": [],
        "titles": [],
        "equipped_title": None,
        "retro_reward_notice": [],
        "daily_login_period": None,
        "daily_login_claimed": False,
        "daily_practice_period": None,
        "daily_practice_count": 0,
        "daily_practice_claimed": False,
        "claimed_permanent_tasks": [],
        "claimed_special_tasks": [],
        "task_rewards_initialized": False,
        "elite_special_tasks_migrated": False,
        "boss_best_times": {},
        "shop": {"generated_at": None, "items": []},
        "inventory": [],
        "collection_catalog": [],
        "equipment": {slot: None for slot in SLOT_NAMES},
        "unit_best_stars": {unit_id: 0 for unit_id in UNITS},
        "chapter_reward_claimed": False,
        "collection_reward_claimed": False,
        "collection_item_claimed": False,
        "boss_exp_claimed": False,
        "boss_wins": 0,
        "elite_boss_exp_claimed": False,
        "elite_boss_wins": 0,
        "elite_reward_claimed": False,
        "chapter2_reward_claimed": False,
        "chapter2_collection_reward_claimed": False,
        "chapter2_boss_exp_claimed": False,
        "chapter2_boss_wins": 0,
        "chapter2_elite_boss_exp_claimed": False,
        "chapter2_elite_boss_wins": 0,
        "chapter2_elite_reward_claimed": False,
        "chapter3_boss_exp_claimed": False,
        "chapter3_boss_wins": 0,
        "chapter3_elite_boss_exp_claimed": False,
        "chapter3_elite_boss_wins": 0,
    }


def normalize_profile(profile, name):
    template = new_profile(name)
    if profile.get("data_version") != 2:
        # 舊版裝備是固定ID，無法保留新版的隨機詞條；保留人物成長資料。
        return {
            **template,
            "level": profile.get("level", 1),
            "exp": profile.get("exp", 0),
            "boss_exp_claimed": profile.get("boss_exp_claimed", False),
            "boss_wins": profile.get("boss_wins", 0),
        }
    for key, value in template.items():
        profile.setdefault(key, value)
    for slot in SLOT_NAMES:
        profile["equipment"].setdefault(slot, None)
    for unit_id in UNITS:
        profile["unit_best_stars"].setdefault(unit_id, 0)
    # 圖鑑記錄「曾經取得」，即使日後分解、融煉或販售也不會倒退。
    catalog = set(profile.get("collection_catalog", []))
    for item in profile["inventory"]:
        if not item.get("achievement"):
            chapter_id = item_chapter_id(item)
            if chapter_id:
                catalog.add(f"{chapter_id}:{item.get('stars', 0)}:{item['slot']}")
    profile["collection_catalog"] = sorted(catalog)
    # 依歷史通關資料補發每個單元一張擊殺券。
    rewarded_units = set(profile.get("ticket_rewarded_units", []))
    passed_units = {
        unit_id for unit_id, stars in profile["unit_best_stars"].items() if stars > 0
    }
    missing_units = sorted(passed_units - rewarded_units)
    if missing_units:
        profile["sweep_tickets"] += len(missing_units)
        profile["ticket_rewarded_units"] = sorted(rewarded_units | set(missing_units))
        profile["retro_reward_notice"].append(
            f"依歷史通關紀錄補發 {len(missing_units)} 張擊殺券"
        )
    title_rewards = [
        ("elite_boss_wins", "好像有點勇哦"),
        ("chapter2_elite_boss_wins", "別小看我！"),
    ]
    for wins_key, title in title_rewards:
        if profile.get(wins_key, 0) > 0 and title not in profile["titles"]:
            profile["titles"].append(title)
            profile["retro_reward_notice"].append(f"補發成就稱號「{title}」")
    return profile


def sequential_student_code(number):
    group = (number - 1) // 999
    if group >= 26:
        raise ValueError("學生編號已超過 A001～Z999 的容量")
    letter = chr(ord("A") + group)
    sequence = (number - 1) % 999 + 1
    return f"{letter}{sequence:03d}"


def create_student(real_name, hero_name, pin):
    validation_error = validate_hero_name(hero_name)
    if validation_error:
        raise ValueError(validation_error)
    salt, digest = make_pin_hash(pin)
    with db_connection() as db:
        db.execute("BEGIN IMMEDIATE")
        if USE_POSTGRES:
            db.execute(
                "INSERT INTO settings(key, value) VALUES('student_counter', '0') "
                "ON CONFLICT(key) DO NOTHING"
            )
        lock_suffix = " FOR UPDATE" if USE_POSTGRES else ""
        row = db.execute(f"SELECT value FROM settings WHERE key='student_counter'{lock_suffix}").fetchone()
        duplicate = db.execute(
            "SELECT 1 FROM players WHERE LOWER(hero_name)=LOWER(?) AND student_code <> '__TEACHER__' LIMIT 1",
            (hero_name,),
        ).fetchone()
        if duplicate:
            raise ValueError("這個勇者名稱已經有人使用，請換一個名稱。")
        number = int(row["value"]) + 1 if row else 1
        code = sequential_student_code(number)
        profile = new_profile(hero_name)
        profile["task_rewards_initialized"] = True
        profile["elite_special_tasks_migrated"] = True
        db.execute(
            "INSERT INTO players(student_code, hero_name, real_name, pin_salt, pin_hash, profile_json, created_at) "
            "VALUES(?, ?, ?, ?, ?, ?, ?)",
            (code, hero_name, real_name, salt, digest, json.dumps(profile, ensure_ascii=False), database_timestamp()),
        )
        db.execute(
            "INSERT INTO settings(key, value) VALUES('student_counter', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(number),),
        )
    return {"student_code": code, "pin": pin, "hero_name": hero_name, "real_name": real_name}


def ensure_teacher_profile(hero_name="老師測試勇者"):
    code = "__TEACHER__"
    with db_connection() as db:
        row = db.execute("SELECT profile_json FROM players WHERE student_code=?", (code,)).fetchone()
        if row:
            profile = normalize_profile(json.loads(row["profile_json"]), hero_name)
            profile["name"] = hero_name
            db.execute(
                "UPDATE players SET hero_name=?, profile_json=? WHERE student_code=?",
                (hero_name, json.dumps(profile, ensure_ascii=False), code),
            )
        else:
            salt, digest = make_pin_hash(secrets.token_hex(16))
            profile = new_profile(hero_name)
            profile["task_rewards_initialized"] = True
            profile["elite_special_tasks_migrated"] = True
            db.execute(
                "INSERT INTO players(student_code, hero_name, pin_salt, pin_hash, profile_json, created_at) "
                "VALUES(?, ?, ?, ?, ?, ?)",
                (code, hero_name, salt, digest, json.dumps(profile, ensure_ascii=False),
                 database_timestamp()),
            )
    return code


def verify_student(code, pin):
    code = code.strip().upper()
    now = time.time()
    with db_connection() as db:
        row = db.execute("SELECT * FROM players WHERE student_code=?", (code,)).fetchone()
        if not row:
            return False, "學生代碼或PIN錯誤"
        if row["locked_until"] > now:
            wait_seconds = math.ceil(row["locked_until"] - now)
            return False, f"登入暫時鎖定，請等待{wait_seconds}秒"
        valid = hmac.compare_digest(pin_digest(pin, row["pin_salt"]), row["pin_hash"])
        if valid:
            db.execute("UPDATE players SET failed_attempts=0, locked_until=0 WHERE student_code=?", (code,))
            return True, code
        failed = row["failed_attempts"] + 1
        locked_until = now + 300 if failed >= 5 else 0
        db.execute(
            "UPDATE players SET failed_attempts=?, locked_until=? WHERE student_code=?",
            (0 if locked_until else failed, locked_until, code),
        )
        return False, "學生代碼或PIN錯誤；連續錯誤5次會鎖定5分鐘"


def get_profile():
    code = st.session_state.active_player
    with db_connection() as db:
        row = db.execute("SELECT hero_name, profile_json FROM players WHERE student_code=?", (code,)).fetchone()
    if not row:
        st.session_state.active_player = None
        st.session_state.screen = "login"
        st.rerun()
    raw_profile = json.loads(row["profile_json"])
    original_profile_json = json.dumps(raw_profile, ensure_ascii=False, sort_keys=True)
    profile = normalize_profile(raw_profile, row["hero_name"])
    retroactively_grant_tasks(profile, code)
    normalized_changed = (
        json.dumps(profile, ensure_ascii=False, sort_keys=True) != original_profile_json
    )
    if profile.get("collection_reward_claimed") and not achievement_item(profile, "chapter-1-collection"):
        profile["inventory"].append(make_collection_reward())
        profile["collection_item_claimed"] = True
        save_profile(profile)
    migrated = False
    for unit_key, maker in (
        ("chapter-1", make_chapter_reward),
        ("chapter-1-collection", make_collection_reward),
        ("chapter-1-elite", make_elite_reward),
        ("chapter-2", make_chapter2_reward),
        ("chapter-2-collection", make_chapter2_collection_reward),
        ("chapter-2-elite", make_chapter2_elite_reward),
    ):
        migrated = sync_achievement_item(profile, unit_key, maker) or migrated
    if migrated or normalized_changed:
        save_profile(profile)
    return profile


def save_profile(profile):
    with db_connection() as db:
        db.execute(
            "UPDATE players SET hero_name=?, profile_json=? WHERE student_code=?",
            (profile["name"], json.dumps(profile, ensure_ascii=False), st.session_state.active_player),
        )


def avatar_from_upload(uploaded_file):
    if uploaded_file.size > 2 * 1024 * 1024:
        raise ValueError("圖片不可超過2MB。")
    image = Image.open(uploaded_file)
    image.thumbnail((256, 256))
    if image.mode not in ("RGB", "RGBA"):
        image = image.convert("RGBA")
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(output.getvalue()).decode("ascii")


def render_avatar_editor(profile):
    avatar_col, upload_col = st.columns([1, 5])
    if profile.get("avatar_data"):
        avatar_col.image(profile["avatar_data"], width=96)
    else:
        avatar_col.markdown("## 🧙")
    uploaded = upload_col.file_uploader(
        "上傳或更換大頭貼", type=["png", "jpg", "jpeg", "webp"],
        key="avatar_upload", help="圖片只會公開作為遊戲大頭貼；正式姓名不會顯示在排行榜。",
    )
    if uploaded and upload_col.button("儲存大頭貼", type="primary"):
        try:
            profile["avatar_data"] = avatar_from_upload(uploaded)
            save_profile(profile)
            st.success("大頭貼已更新。")
            st.rerun()
        except Exception as error:
            st.error(f"無法處理圖片：{error}")


def log_attempt(unit_id):
    if st.session_state.active_player == "__TEACHER__":
        return
    with db_connection() as db:
        db.execute(
            "INSERT INTO attempts(student_code, unit_id, stars, max_combo, correct_count, "
            "elapsed_seconds, average_seconds, finished_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
            (st.session_state.active_player, unit_id, st.session_state.stars,
             st.session_state.max_combo, st.session_state.correct, st.session_state.quiz_elapsed,
             st.session_state.quiz_elapsed / st.session_state.attempts if st.session_state.attempts else 0,
             database_timestamp()),
        )
        for answer_row in st.session_state.answer_history:
            db.execute(
                "INSERT INTO question_logs(student_code, unit_id, question_text, submitted_answer, "
                "correct_answer, is_correct, combo_after, elapsed_seconds, answered_at) "
                "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (st.session_state.active_player, unit_id, answer_row["question_text"],
                 answer_row["submitted_answer"], answer_row["correct_answer"],
                 1 if answer_row["is_correct"] else 0, answer_row["combo_after"],
                 answer_row["elapsed_seconds"], answer_row["answered_at"]),
            )


def save_best_ranking(profile, clear_time, boss_type="normal", chapter_id="1"):
    code = st.session_state.active_player
    if code == "__TEACHER__":
        return
    now = database_timestamp()
    table = {
        ("1", "normal"): "rankings", ("1", "elite"): "elite_rankings",
        ("2", "normal"): "chapter2_rankings", ("2", "elite"): "chapter2_elite_rankings",
        ("3", "normal"): "chapter3_rankings", ("3", "elite"): "chapter3_elite_rankings",
    }[(chapter_id, boss_type)]
    with db_connection() as db:
        row = db.execute(f"SELECT clear_time FROM {table} WHERE student_code=?", (code,)).fetchone()
        if not row or clear_time < row["clear_time"]:
            db.execute(
                f"INSERT INTO {table}(student_code, hero_name, level, clear_time, achieved_at) "
                "VALUES(?, ?, ?, ?, ?) ON CONFLICT(student_code) DO UPDATE SET "
                "hero_name=excluded.hero_name, level=excluded.level, "
                "clear_time=excluded.clear_time, achieved_at=excluded.achieved_at",
                (code, profile["name"], profile["level"], round(clear_time, 2), now),
            )


def ranking_rows(boss_type="normal", chapter_id="1", include_private_identity=False):
    table = {
        ("1", "normal"): "rankings", ("1", "elite"): "elite_rankings",
        ("2", "normal"): "chapter2_rankings", ("2", "elite"): "chapter2_elite_rankings",
        ("3", "normal"): "chapter3_rankings", ("3", "elite"): "chapter3_elite_rankings",
    }[(chapter_id, boss_type)]
    with db_connection() as db:
        rows = db.execute(
            "SELECT r.student_code AS 學生代碼, p.real_name AS 正式姓名, "
            "r.hero_name AS 玩家, r.level AS 等級, r.clear_time AS 通關秒數, "
            f"r.achieved_at AS 日期, p.profile_json FROM {table} r "
            "JOIN players p ON p.student_code=r.student_code ORDER BY r.clear_time ASC"
        ).fetchall()
    result = []
    for rank, row in enumerate(rows, 1):
        profile = json.loads(row["profile_json"])
        public_name = row["玩家"]
        if profile.get("equipped_title"):
            public_name = f"「{profile['equipped_title']}」{public_name}"
        ranking_row = {
            "名次": rank,
            "自己": "👤 你" if row["學生代碼"] == st.session_state.active_player else "",
            "頭像": profile.get("avatar_data"), "玩家": public_name, "等級": row["等級"],
            "通關秒數": row["通關秒數"], "日期": taipei_time_text(row["日期"]),
        }
        if include_private_identity:
            ranking_row.pop("自己", None)
            ranking_row = {
                "學生代碼": row["學生代碼"], "正式姓名": row["正式姓名"], **ranking_row
            }
        result.append(ranking_row)
    return result


def render_ranking(rows):
    st.dataframe(
        rows,
        hide_index=True, use_container_width=True,
        column_config={"頭像": st.column_config.ImageColumn("頭像", width="small")},
    )


def student_ranking_rows(rows, limit=10):
    """學生看前10名；若本人不在前10名，於下方額外保留本人實際名次。"""
    top_rows = rows[:limit]
    own_row = next((row for row in rows if row.get("自己")), None)
    if own_row and own_row not in top_rows:
        return [*top_rows, own_row]
    return top_rows


def character_ranking_rows(ranking_type):
    """公開角色能力排行榜；不包含老師角色與正式姓名。"""
    with db_connection() as db:
        rows = db.execute(
            "SELECT student_code, hero_name, profile_json FROM players "
            "WHERE student_code <> '__TEACHER__'"
        ).fetchall()
    prepared = []
    for row in rows:
        profile = normalize_profile(json.loads(row["profile_json"]), row["hero_name"])
        stats = player_stats(profile)
        public_name = profile["name"]
        if profile.get("equipped_title"):
            public_name = f"「{profile['equipped_title']}」{public_name}"
        base = {
            "_student_code": row["student_code"],
            "自己": "👤 你" if row["student_code"] == st.session_state.active_player else "",
            "頭像": profile.get("avatar_data"), "玩家": public_name,
            "等級": profile["level"], "EXP": profile["exp"],
            "攻擊": round(stats["attack"], 1),
            "防禦": round(stats["defense"], 1),
            "攻速／秒": round(stats["attack_speed"], 2),
        }
        prepared.append(base)
    sort_keys = {
        "level": lambda row: (-row["等級"], -row["EXP"], row["玩家"]),
        "attack": lambda row: (-row["攻擊"], -row["等級"], row["玩家"]),
        "defense": lambda row: (-row["防禦"], -row["等級"], row["玩家"]),
        "speed": lambda row: (-row["攻速／秒"], -row["等級"], row["玩家"]),
    }
    prepared.sort(key=sort_keys[ranking_type])
    visible_columns = {
        "level": ("頭像", "玩家", "等級", "EXP"),
        "attack": ("頭像", "玩家", "等級", "攻擊"),
        "defense": ("頭像", "玩家", "等級", "防禦"),
        "speed": ("頭像", "玩家", "等級", "攻速／秒"),
    }[ranking_type]
    result = []
    for rank, row in enumerate(prepared, 1):
        result.append({
            "名次": rank, "自己": row["自己"],
            **{column: row[column] for column in visible_columns},
        })
    return result


def student_rows():
    with db_connection() as db:
        rows = [dict(row) for row in db.execute(
            "SELECT student_code AS 學生代碼, real_name AS 正式姓名, hero_name AS 勇者名稱, created_at AS 建立時間 "
            "FROM players WHERE student_code <> '__TEACHER__' ORDER BY created_at"
        ).fetchall()]
    for row in rows:
        row["建立時間"] = taipei_time_text(row["建立時間"])
    return rows


def reset_student_pin(code):
    pin = f"{secrets.randbelow(1000000):06d}"
    salt, digest = make_pin_hash(pin)
    with db_connection() as db:
        db.execute("UPDATE players SET pin_salt=?, pin_hash=?, failed_attempts=0, locked_until=0 WHERE student_code=?", (salt, digest, code))
    return pin


def update_student_real_name(code, real_name):
    with db_connection() as db:
        db.execute("UPDATE players SET real_name=? WHERE student_code=?", (real_name, code))


def student_learning_detail(code):
    with db_connection() as db:
        row = db.execute(
            "SELECT hero_name, real_name, profile_json FROM players WHERE student_code=?", (code,)
        ).fetchone()
    if not row:
        return None
    return normalize_profile(json.loads(row["profile_json"]), row["hero_name"])


def student_question_rows(code, errors_only=False, limit=200):
    condition = "AND is_correct=0" if errors_only else ""
    with db_connection() as db:
        rows = [dict(row) for row in db.execute(
            "SELECT unit_id AS 單元, question_text AS 題目, submitted_answer AS 學生答案, "
            "correct_answer AS 正確答案, is_correct AS 是否答對, combo_after AS 作答後連擊, "
            f"elapsed_seconds AS 回合累計秒數, answered_at AS 作答時間 FROM question_logs "
            f"WHERE student_code=? {condition} ORDER BY id DESC LIMIT {int(limit)}",
            (code,),
        ).fetchall()]
    for row in rows:
        row["是否答對"] = "✅" if row["是否答對"] else "❌"
        row["作答時間"] = taipei_time_text(row["作答時間"])
    return rows


def delete_student(code):
    with db_connection() as db:
        db.execute("DELETE FROM players WHERE student_code=?", (code,))


def add_exp(profile, amount):
    profile["exp"] += amount
    gained = 0
    while profile["level"] < 20 and profile["exp"] >= profile["level"] * 100:
        profile["exp"] -= profile["level"] * 100
        profile["level"] += 1
        gained += 1
    return gained


def current_daily_period():
    now = datetime.now(TAIPEI_TZ)
    if now.hour < 8:
        now -= timedelta(days=1)
    return now.strftime("%Y-%m-%d")


def current_midnight_period():
    return datetime.now(TAIPEI_TZ).strftime("%Y-%m-%d")


def highest_unlocked_chapter(profile):
    if profile.get("chapter2_boss_wins", 0) > 0:
        return "3"
    if profile.get("boss_wins", 0) > 0:
        return "2"
    return "1"


def sync_daily_tasks(profile):
    changed = False
    period = current_daily_period()
    if profile.get("daily_login_period") != period:
        profile["daily_login_period"] = period
        profile["daily_login_claimed"] = False
        changed = True
    practice_period = current_midnight_period()
    if profile.get("daily_practice_period") != practice_period:
        profile["daily_practice_period"] = practice_period
        profile["daily_practice_count"] = 0
        profile["daily_practice_claimed"] = False
        changed = True
    return changed


def award_unit_ticket(profile, unit_id):
    if unit_id not in profile["ticket_rewarded_units"]:
        profile["ticket_rewarded_units"].append(unit_id)
        profile["sweep_tickets"] += 1
        return True
    return False


def permanent_task_definitions():
    tasks = []
    boss_keys = {
        "1": ("boss_wins", "elite_boss_wins"),
        "2": ("chapter2_boss_wins", "chapter2_elite_boss_wins"),
        "3": ("chapter3_boss_wins", "chapter3_elite_boss_wins"),
    }
    for chapter_id in CHAPTERS:
        for unit_id in chapter_unit_ids(chapter_id):
            tasks.append({
                "id": f"unit_{unit_id}", "chapter": chapter_id,
                "task_type": "unit", "target_unit": unit_id,
                "name": f"通過{unit_id}單元：{UNITS[unit_id]['name']}",
                "reward_text": "100金幣", "coins": 100,
                "complete": lambda profile, uid=unit_id: profile["unit_best_stars"].get(uid, 0) > 0,
            })
        normal_key, elite_key = boss_keys[chapter_id]
        tasks.extend([
            {
                "id": f"boss_{chapter_id}_normal", "chapter": chapter_id,
                "task_type": "boss", "boss_type": "normal",
                "name": f"通過{CHAPTERS[chapter_id]['number']}普通BOSS",
                "reward_text": "300金幣＋1顆部位融煉石", "coins": 300,
                "stone_key": "slot_smelting_stones",
                "complete": lambda profile, key=normal_key: profile.get(key, 0) > 0,
            },
            {
                "id": f"boss_{chapter_id}_elite", "chapter": chapter_id,
                "task_type": "boss", "boss_type": "elite",
                "name": f"通過{CHAPTERS[chapter_id]['number']}菁英BOSS",
                "reward_text": "300金幣＋1顆基礎詞條融煉石", "coins": 300,
                "stone_key": "basic_affix_smelting_stones",
                "complete": lambda profile, key=elite_key: profile.get(key, 0) > 0,
            },
        ])
    return tasks


def special_task_definitions(code, profile=None):
    table_by_chapter = {
        "1": ("rankings", "elite_rankings"),
        "2": ("chapter2_rankings", "chapter2_elite_rankings"),
        "3": ("chapter3_rankings", "chapter3_elite_rankings"),
    }
    clear_times = {}
    with db_connection() as db:
        for chapter_id, (normal_table, elite_table) in table_by_chapter.items():
            for boss_type, table in (("normal", normal_table), ("elite", elite_table)):
                row = db.execute(
                    f"SELECT clear_time FROM {table} WHERE student_code=?", (code,)
                ).fetchone()
                ranking_time = row["clear_time"] if row else None
                profile_time = (
                    profile.get("boss_best_times", {}).get(f"{chapter_id}_{boss_type}")
                    if profile else None
                )
                available_times = [value for value in (ranking_time, profile_time) if value is not None]
                clear_times[(chapter_id, boss_type)] = min(available_times) if available_times else None
    tasks = []
    for chapter_id in CHAPTERS:
        for boss_type, boss_label in (("normal", "普通BOSS"), ("elite", "菁英BOSS")):
            clear_time = clear_times[(chapter_id, boss_type)]
            tasks.append({
                "id": f"speed_{chapter_id}_{boss_type}", "chapter": chapter_id,
                "boss_type": boss_type,
                "name": f"10秒內通過{CHAPTERS[chapter_id]['number']}{boss_label}",
                "reward_text": "300金幣＋1顆進階詞條融煉石", "coins": 300,
                "stone_key": "advanced_affix_smelting_stones",
                "complete": clear_time is not None and clear_time <= 10,
            })
    return tasks


def grant_task_reward(profile, task):
    profile["coins"] += task.get("coins", 0)
    if task.get("stone_key"):
        profile[task["stone_key"]] += 1


def visible_permanent_tasks(profile):
    claimed = set(profile["claimed_permanent_tasks"])
    all_tasks = permanent_task_definitions()
    visible = []
    for chapter_id in CHAPTERS:
        if int(chapter_id) > 1:
            previous = str(int(chapter_id) - 1)
            previous_ids = {task["id"] for task in all_tasks if task["chapter"] == previous}
            if not previous_ids.issubset(claimed):
                break
        visible.extend(task for task in all_tasks if task["chapter"] == chapter_id)
    return visible


def visible_special_tasks(profile, code):
    claimed = set(profile["claimed_special_tasks"])
    result = []
    for task in special_task_definitions(code, profile):
        chapter_id = task["chapter"]
        if task["boss_type"] == "elite" and f"speed_{chapter_id}_normal" not in claimed:
            continue
        if int(chapter_id) > 1 and f"speed_{int(chapter_id) - 1}_elite" not in claimed:
            break
        result.append(task)
    return result


def retroactively_grant_tasks(profile, code):
    messages = []
    # 相容上一版普通BOSS特殊任務ID，避免更新後被要求重領。
    claimed_special = set(profile["claimed_special_tasks"])
    for chapter_id in CHAPTERS:
        legacy_id = f"speed_{chapter_id}"
        if legacy_id in claimed_special:
            claimed_special.remove(legacy_id)
            claimed_special.add(f"speed_{chapter_id}_normal")
    profile["claimed_special_tasks"] = sorted(claimed_special)

    if not profile.get("task_rewards_initialized"):
        for task in permanent_task_definitions():
            if task["complete"](profile) and task["id"] not in profile["claimed_permanent_tasks"]:
                grant_task_reward(profile, task)
                profile["claimed_permanent_tasks"].append(task["id"])
                messages.append(f"{task['name']}：{task['reward_text']}")
        for task in special_task_definitions(code, profile):
            if task["complete"] and task["id"] not in profile["claimed_special_tasks"]:
                grant_task_reward(profile, task)
                profile["claimed_special_tasks"].append(task["id"])
                messages.append(f"{task['name']}：{task['reward_text']}")
        profile["task_rewards_initialized"] = True
        profile["elite_special_tasks_migrated"] = True
    elif not profile.get("elite_special_tasks_migrated"):
        # 已使用舊版任務系統的玩家，只補發新增的菁英BOSS特殊任務。
        for task in special_task_definitions(code, profile):
            if (
                task["boss_type"] == "elite" and task["complete"]
                and task["id"] not in profile["claimed_special_tasks"]
            ):
                grant_task_reward(profile, task)
                profile["claimed_special_tasks"].append(task["id"])
                messages.append(f"{task['name']}：{task['reward_text']}")
        profile["elite_special_tasks_migrated"] = True
    if messages:
        profile["retro_reward_notice"].append("任務補發獎勵｜" + "；".join(messages))
    return messages


def boss_is_unlocked(profile, chapter_id, boss_type):
    if boss_type == "normal":
        return all(
            profile["unit_best_stars"].get(unit_id, 0) == 3
            for unit_id in chapter_unit_ids(chapter_id)
        )
    normal_wins_key = {
        "1": "boss_wins", "2": "chapter2_boss_wins", "3": "chapter3_boss_wins",
    }[chapter_id]
    return profile.get(normal_wins_key, 0) > 0


def go_to_boss(chapter_id, boss_type):
    st.session_state.selected_chapter = chapter_id
    st.session_state.selected_boss_type = boss_type
    st.session_state.scroll_boss_to_top = True
    st.session_state.screen = "boss_ready"


def item_signature(item):
    return (item["unit"], item["slot"], item["stars"], item["affix_stat"], item["affix_value"])


def make_random_item(profile, unit_id, stars):
    if stars == 0:
        return None
    owned = {item_signature(item) for item in profile["inventory"] if not item.get("achievement")}
    unit_slots = UNITS[unit_id]["slots"]
    owned_same_star_slots = {
        item["slot"] for item in profile["inventory"]
        if not item.get("achievement") and item["unit"] == unit_id and item["stars"] == stars
    }
    missing_slots = [slot for slot in unit_slots if slot not in owned_same_star_slots]
    candidate_slots = missing_slots if missing_slots else unit_slots
    combinations = []
    for slot in candidate_slots:
        for affix_stat in AFFIX_NAMES:
            value_pool = AFFIX_VALUES.get(affix_stat, AFFIX_VALUES["default"])
            for affix_value in value_pool[stars]:
                signature = (unit_id, slot, stars, affix_stat, affix_value)
                if signature not in owned:
                    combinations.append((slot, affix_stat, affix_value))
    if not combinations:
        return None
    slot, affix_stat, affix_value = random.choice(combinations)
    fixed_stat, values = FIXED_STATS[slot]
    chapter_id = unit_id.split("-")[0]
    raw_fixed_value = values[stars] * CHAPTERS[chapter_id]["multiplier"]
    if fixed_stat in ("hp", "attack", "defense"):
        fixed_value = round(raw_fixed_value)
    else:
        fixed_value = round(raw_fixed_value, 3)
    return {
        "uid": uuid.uuid4().hex,
        "unit": unit_id,
        "chapter": chapter_id,
        "slot": slot,
        "stars": stars,
        "name": GEAR_NAMES[stars][slot],
        "fixed_stat": fixed_stat,
        "fixed_value": fixed_value,
        "affix_stat": affix_stat,
        "affix_value": affix_value,
        "achievement": False,
    }


def highest_shop_chapter(profile):
    """商店依已經實際通關過的最高章節提供裝備。"""
    completed = [
        chapter_id for chapter_id in CHAPTERS
        if any(profile["unit_best_stars"].get(uid, 0) > 0 for uid in chapter_unit_ids(chapter_id))
    ]
    return completed[-1] if completed else "1"


def make_shop_item(profile, chapter_id=None):
    chapter_id = chapter_id or highest_shop_chapter(profile)
    unit_id = random.choice(chapter_unit_ids(chapter_id))
    slot = random.choice(list(SLOT_NAMES))
    affix_stat = random.choice(list(AFFIX_NAMES))
    value_pool = AFFIX_VALUES.get(affix_stat, AFFIX_VALUES["default"])[3]
    affix_value = random.choice(value_pool)
    fixed_stat, values = FIXED_STATS[slot]
    raw_value = values[3] * CHAPTERS[chapter_id]["multiplier"]
    fixed_value = round(raw_value) if fixed_stat in ("hp", "attack", "defense") else round(raw_value, 3)
    return {
        "shop_id": uuid.uuid4().hex,
        "sold": False,
        "item": {
            "uid": uuid.uuid4().hex, "unit": unit_id, "chapter": chapter_id,
            "slot": slot, "stars": 3, "name": GEAR_NAMES[3][slot],
            "fixed_stat": fixed_stat, "fixed_value": fixed_value,
            "affix_stat": affix_stat, "affix_value": affix_value,
            "achievement": False, "source": "shop",
        },
    }


def refresh_shop(profile, paid=False):
    if paid:
        if profile["coins"] < 100:
            return False
        profile["coins"] -= 100
    chapter_id = highest_shop_chapter(profile)
    profile["shop"] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "items": [make_shop_item(profile, chapter_id) for _ in range(6)],
    }
    return True


def ensure_shop(profile):
    shop = profile.get("shop") or {"generated_at": None, "items": []}
    needs_refresh = not shop.get("items") or not shop.get("generated_at")
    if not needs_refresh:
        try:
            generated = datetime.fromisoformat(shop["generated_at"].replace("Z", "+00:00"))
            needs_refresh = datetime.now(timezone.utc) >= generated + timedelta(hours=24)
        except (TypeError, ValueError):
            needs_refresh = True
    if needs_refresh:
        refresh_shop(profile)
        return True
    return False


def remove_inventory_items(profile, uids):
    uid_set = set(uids)
    for slot, uid in profile["equipment"].items():
        if uid in uid_set:
            profile["equipment"][slot] = None
    profile["inventory"] = [item for item in profile["inventory"] if item["uid"] not in uid_set]


def make_forged_item(profile, source_stars, chapter_id, selected_slot=None, selected_affix=None):
    target_stars = source_stars + 1
    if selected_slot:
        unit_id = next(
            uid for uid in chapter_unit_ids(chapter_id)
            if selected_slot in UNITS[uid]["slots"]
        )
    else:
        unit_id = random.choice(chapter_unit_ids(chapter_id))
    # 使用空白暫存，讓既有裝備不會阻止融煉結果生成。
    item = make_random_item({"inventory": []}, unit_id, target_stars)
    if selected_slot:
        item["slot"] = selected_slot
        item["name"] = GEAR_NAMES[target_stars][selected_slot]
        fixed_stat, values = FIXED_STATS[selected_slot]
        raw_value = values[target_stars] * CHAPTERS[chapter_id]["multiplier"]
        item["fixed_stat"] = fixed_stat
        item["fixed_value"] = (
            round(raw_value) if fixed_stat in ("hp", "attack", "defense")
            else round(raw_value, 3)
        )
    if selected_affix:
        item["affix_stat"] = selected_affix
        item["affix_value"] = random.choice(
            AFFIX_VALUES.get(selected_affix, AFFIX_VALUES["default"])[target_stars]
        )
    item["source"] = "forge"
    return item


def make_chapter_reward():
    return {
        "uid": uuid.uuid4().hex,
        "unit": "chapter-1",
        "slot": "weapon",
        "stars": 4,
        "name": "整數勇者之劍",
        "fixed_stat": "attack",
        "fixed_value": 8,
        "affix_stat": "attack_pct",
        "affix_value": 0.25,
        "achievement": True,
    }


def make_elite_reward():
    return {
        "uid": uuid.uuid4().hex,
        "unit": "chapter-1-elite",
        "slot": "helmet",
        "stars": 4,
        "name": "收藏家王冠",
        "fixed_stat": "hp",
        "fixed_value": 25,
        "affix_stat": "defense_pct",
        "affix_value": 0.25,
        "achievement": True,
    }


def make_collection_reward():
    return {
        "uid": uuid.uuid4().hex, "unit": "chapter-1-collection", "slot": "necklace",
        "stars": 4, "name": "九星守護項鍊", "fixed_stat": "boss_hp_reduction",
        "fixed_value": 0.13, "affix_stat": "hp_pct", "affix_value": 0.25,
        "achievement": True,
    }


def make_chapter2_reward():
    return {
        "uid": uuid.uuid4().hex, "unit": "chapter-2", "slot": "gloves",
        "stars": 4, "name": "乘除勇者手甲", "fixed_stat": "attack",
        "fixed_value": 6, "affix_stat": "attack_pct", "affix_value": 0.25,
        "achievement": True,
    }


def make_chapter2_collection_reward():
    return {
        "uid": uuid.uuid4().hex, "unit": "chapter-2-collection", "slot": "boots",
        "stars": 4, "name": "乘除疾風戰靴", "fixed_stat": "attack_speed",
        "fixed_value": 0.13, "affix_stat": "speed_pct", "affix_value": 0.25,
        "achievement": True,
    }


def make_chapter2_elite_reward():
    return {
        "uid": uuid.uuid4().hex, "unit": "chapter-2-elite", "slot": "shield",
        "stars": 4, "name": "乘除霸主盾", "fixed_stat": "defense",
        "fixed_value": 7, "affix_stat": "hp_pct", "affix_value": 0.25,
        "achievement": True,
    }


def item_chapter_id(item):
    if item.get("chapter"):
        return str(item["chapter"])
    unit = str(item.get("unit", ""))
    return unit.split("-")[0] if unit and unit[0].isdigit() else None


def collected_three_star_slots(profile, chapter_id="1"):
    prefix = f"{chapter_id}:3:"
    recorded = {
        entry[len(prefix):] for entry in profile.get("collection_catalog", [])
        if entry.startswith(prefix)
    }
    currently_owned = {
        item["slot"] for item in profile["inventory"]
        if item.get("stars") == 3 and not item.get("achievement")
        and item_chapter_id(item) == chapter_id
    }
    return recorded | currently_owned


def has_full_three_star_set(profile, chapter_id="1"):
    return set(SLOT_NAMES).issubset(collected_three_star_slots(profile, chapter_id))


def find_item(profile, uid):
    return next((item for item in profile["inventory"] if item["uid"] == uid), None)


def achievement_item(profile, unit_key):
    return next((item for item in profile["inventory"] if item.get("unit") == unit_key), None)


def collected_achievement_slots(profile, stars=4):
    return {
        item["slot"] for item in profile["inventory"]
        if item.get("achievement") and item.get("stars") == stars
    }


def sync_achievement_item(profile, unit_key, maker):
    """讓舊存檔中的成就裝備跟隨新版部位與固定數值，且不遺失穿戴狀態。"""
    item = achievement_item(profile, unit_key)
    if not item:
        return False
    expected = maker()
    old_slot = item["slot"]
    was_equipped = profile["equipment"].get(old_slot) == item["uid"]
    synced_keys = ("slot", "stars", "name", "fixed_stat", "fixed_value", "affix_stat", "affix_value", "achievement")
    changed = any(item.get(key) != expected[key] for key in synced_keys)
    if not changed:
        return False
    for key in synced_keys:
        item[key] = expected[key]
    if old_slot != item["slot"] and was_equipped:
        profile["equipment"][old_slot] = None
        if not profile["equipment"].get(item["slot"]):
            profile["equipment"][item["slot"]] = item["uid"]
    return changed


def fixed_text(item):
    names = {
        "hp": "HP", "attack": "攻擊力", "defense": "防禦力",
        "attack_speed": "攻擊速度", "boss_hp_reduction": "菁英BOSS初始血量降低",
        "first_hit_percent": "第一擊額外扣除菁英BOSS血量",
    }
    value = item["fixed_value"]
    if item["fixed_stat"] in ("boss_hp_reduction", "first_hit_percent"):
        value_text = f"{value:.0%}"
    elif item["fixed_stat"] == "attack_speed":
        value_text = f"{value:.2f}/秒"
    else:
        value_text = f"{value:g}"
    return f"{names[item['fixed_stat']]} +{value_text}"


def item_text(item):
    chapter_id = item.get("chapter")
    if not chapter_id and str(item.get("unit", "")).startswith(("1-", "2-")):
        chapter_id = str(item["unit"]).split("-")[0]
    chapter_label = f"{CHAPTERS[chapter_id]['number']}・" if chapter_id in CHAPTERS else ""
    return f"{SLOT_ICONS[item['slot']]} {chapter_label}{item['name']} {'⭐' * item['stars']}｜固定：{fixed_text(item)}｜詞條：{AFFIX_NAMES[item['affix_stat']]} +{item['affix_value']:.0%}"


def render_item_comparison(profile, new_item):
    current = find_item(profile, profile["equipment"].get(new_item["slot"]))
    left, right = st.columns(2)
    left.info(f"**準備更換**\n\n{item_text(new_item)}")
    if current:
        right.warning(f"**目前穿戴**\n\n{item_text(current)}")
    else:
        right.success(f"**目前穿戴**\n\n{SLOT_ICONS[new_item['slot']]} {SLOT_NAMES[new_item['slot']]}尚未裝備")
    before = player_stats(profile)
    preview = json.loads(json.dumps(profile, ensure_ascii=False))
    preview["equipment"][new_item["slot"]] = new_item["uid"]
    after = player_stats(preview)
    stat_specs = [
        ("HP", "hp", "number"), ("攻擊", "attack", "number"),
        ("防禦", "defense", "number"), ("攻速／秒", "attack_speed", "speed"),
        ("菁英BOSS初始血量降低", "boss_hp_reduction", "percent"),
        ("第一擊額外扣除菁英BOSS血量", "first_hit_percent", "percent"),
        ("對菁英BOSS傷害", "boss_damage_pct", "percent"),
        ("受到傷害降低", "damage_reduction_pct", "percent"),
        ("暴擊率", "critical_rate", "percent"),
        ("暴擊傷害", "critical_damage", "percent"),
        ("開場護盾", "shield_pct", "percent"),
        ("菁英BOSS攻速降低", "boss_attack_slow_pct", "percent"),
    ]

    def display_value(value, kind, signed=False):
        if kind == "percent":
            return f"{value:+.0%}" if signed else f"{value:.0%}"
        digits = 2 if kind == "speed" else 1
        return f"{value:+.{digits}f}" if signed else f"{value:.{digits}f}"

    comparison_rows = []
    for label, key, kind in stat_specs:
        difference = after[key] - before[key]
        comparison_rows.append({
            "人物能力": label,
            "目前": display_value(before[key], kind),
            "更換後": display_value(after[key], kind),
            "增減": ("—" if abs(difference) < 1e-9 else display_value(difference, kind, signed=True)),
        })
    st.write("**人物完整能力前後對照**")
    st.dataframe(comparison_rows, hide_index=True, use_container_width=True)


def equipped_items(profile):
    items = []
    for uid in profile["equipment"].values():
        item = find_item(profile, uid) if uid else None
        if item:
            items.append(item)
    return items


def player_stats(profile):
    level_factor = 1 + 0.10 * (profile["level"] - 1)
    base = {"hp": 100 * level_factor, "attack": 20 * level_factor, "defense": 10 * level_factor, "attack_speed": 1.0}
    flat = {"hp": 0.0, "attack": 0.0, "defense": 0.0, "attack_speed": 0.0}
    pct = {"hp_pct": 0.0, "attack_pct": 0.0, "defense_pct": 0.0, "speed_pct": 0.0}
    combat = {
        "boss_damage_pct": 0.0, "damage_reduction_pct": 0.0,
        "critical_rate": 0.0, "critical_damage": 0.0,
        "shield_pct": 0.0, "boss_attack_slow_pct": 0.0,
    }
    boss_reduction = 0.0
    first_hit = 0.0
    for item in equipped_items(profile):
        if item["fixed_stat"] in flat:
            flat[item["fixed_stat"]] += item["fixed_value"]
        elif item["fixed_stat"] == "boss_hp_reduction":
            boss_reduction += item["fixed_value"]
        elif item["fixed_stat"] == "first_hit_percent":
            first_hit += item["fixed_value"]
        if item["affix_stat"] in pct:
            pct[item["affix_stat"]] += item["affix_value"]
        elif item["affix_stat"] in combat:
            combat[item["affix_stat"]] += item["affix_value"]
    final_stats = {
        "hp": (base["hp"] + flat["hp"]) * (1 + pct["hp_pct"]),
        "attack": (base["attack"] + flat["attack"]) * (1 + pct["attack_pct"]),
        "defense": (base["defense"] + flat["defense"]) * (1 + pct["defense_pct"]),
        "attack_speed": (base["attack_speed"] + flat["attack_speed"]) * (1 + pct["speed_pct"]),
        "boss_hp_reduction": min(boss_reduction, 0.50),
        "first_hit_percent": min(first_hit, 0.50),
        "boss_damage_pct": min(combat["boss_damage_pct"], 1.00),
        "damage_reduction_pct": min(combat["damage_reduction_pct"], 0.40),
        "critical_rate": min(combat["critical_rate"], 0.50),
        "critical_damage": min(combat["critical_damage"], 1.00),
        "shield_pct": min(combat["shield_pct"], 0.50),
        "boss_attack_slow_pct": min(combat["boss_attack_slow_pct"], 0.40),
    }
    final_stats["breakdown"] = {"base": base, "flat": flat, "pct": pct}
    return final_stats


def unit_unlocked(profile, unit_id):
    chapter_id = unit_id.split("-")[0]
    if chapter_id == "2" and profile.get("boss_wins", 0) <= 0 and st.session_state.active_player != "__TEACHER__":
        return False
    if chapter_id == "3" and profile.get("chapter2_boss_wins", 0) <= 0 and st.session_state.active_player != "__TEACHER__":
        return False
    order = chapter_unit_ids(chapter_id)
    index = order.index(unit_id)
    return index == 0 or profile["unit_best_stars"][order[index - 1]] > 0


def make_question(unit_id):
    if unit_id in ("3-1", "3-2"):
        add = random.choice([True, False])
        a = random.randint(10, 199) / 10
        b = random.randint(1, 99) / 10 if unit_id == "3-1" else random.randint(1, 999) / 100
        if not add and b > a:
            a, b = b, a
        answer = a + b if add else a - b
        symbol = "＋" if add else "－"
        a_text = f"{a:.1f}"
        b_text = f"{b:.1f}" if unit_id == "3-1" else f"{b:.2f}"
        return {"text": f"{a_text} {symbol} {b_text} ＝ ?", "answer": round(answer, 2)}
    if unit_id == "2-1":
        a, b = random.randint(10, 99), random.randint(2, 9)
        return {"text": f"{a} × {b} ＝ ?", "answer": a * b}
    if unit_id == "2-2":
        divisor = random.randint(2, 9)
        quotient = random.randint(math.ceil(10 / divisor), math.floor(99 / divisor))
        dividend = divisor * quotient
        return {"text": f"{dividend} ÷ {divisor} ＝ ?", "answer": quotient}
    if unit_id == "2-3":
        a, b = random.randint(100, 999), random.randint(2, 9)
        return {"text": f"{a} × {b} ＝ ?", "answer": a * b}
    if unit_id == "2-4":
        divisor = random.randint(2, 9)
        quotient = random.randint(math.ceil(100 / divisor), math.floor(999 / divisor))
        dividend = divisor * quotient
        return {"text": f"{dividend} ÷ {divisor} ＝ ?", "answer": quotient}
    add = random.choice([True, False])
    if unit_id == "1-1":
        a, b = random.randint(10, 99), random.randint(1, 9)
    elif unit_id == "1-2":
        a, b = random.randint(10, 99), random.randint(10, 99)
    else:
        a, b = random.randint(100, 999), random.randint(10, 99)
    if add:
        return {"text": f"{a} ＋ {b} ＝ ?", "answer": a + b}
    a, b = max(a, b), min(a, b)
    return {"text": f"{a} － {b} ＝ ?", "answer": a - b}


def focus_answer_input():
    components.html(
        """
        <script>
        const focusAnswer = () => {
            const doc = parent.window.document;
            const answer = doc.querySelector('input[aria-label="你的答案"]')
                || doc.querySelector('input[placeholder="輸入後按 Enter"]');
            if (answer) {
                answer.focus({preventScroll: true});
                answer.click();
                if (answer.select) answer.select();
            }
        };
        [50, 150, 300, 600, 1000].forEach(delay => setTimeout(focusAnswer, delay));
        </script>
        """,
        height=0,
        scrolling=False,
    )


def scroll_page_to_top(state_key):
    """只在剛切換頁面時，把 Streamlit 主畫面可靠地捲到頂端。"""
    if not st.session_state.get(state_key):
        return
    components.html(
        """
        <script>
        const scrollTop = () => {
            const doc = parent.window.document;
            const main = doc.querySelector('.stMain')
                || doc.querySelector('[data-testid="stMain"]')
                || doc.querySelector('[data-testid="stAppViewContainer"]');
            if (main) main.scrollTo({top: 0, left: 0, behavior: 'auto'});
            doc.documentElement.scrollTop = 0;
            doc.body.scrollTop = 0;
            parent.window.scrollTo(0, 0);
            if (window.frameElement) {
                window.frameElement.scrollIntoView({block: 'start', behavior: 'auto'});
            }
        };
        [0, 50, 150, 300, 600].forEach(delay => setTimeout(scrollTop, delay));
        </script>
        """,
        height=0,
    )
    st.session_state[state_key] = False


def stars_for_combo(combo):
    if combo >= 10:
        return 3
    if combo >= 5:
        return 2
    if combo >= 1:
        return 1
    return 0


def start_quiz(unit_id):
    st.session_state.selected_unit = unit_id
    st.session_state.selected_chapter = unit_id.split("-")[0]
    st.session_state.deadline = None
    st.session_state.quiz_started_at = time.time()
    st.session_state.quiz_elapsed = 0.0
    st.session_state.question = make_question(unit_id)
    st.session_state.answer_input = None
    st.session_state.correct = 0
    st.session_state.attempts = 0
    st.session_state.combo = 0
    st.session_state.max_combo = 0
    st.session_state.message = ""
    st.session_state.stars = 0
    st.session_state.result_processed = False
    st.session_state.pending_item_uid = None
    st.session_state.drop_exhausted = False
    st.session_state.earned_exp = 0
    st.session_state.level_up_to = None
    st.session_state.chapter_reward_new = False
    st.session_state.collection_reward_new = False
    st.session_state.collection_level_up_to = None
    st.session_state.extra_reward_messages = []
    st.session_state.answer_history = []
    st.session_state.screen = "quiz"


def finish_quiz():
    st.session_state.stars = stars_for_combo(st.session_state.max_combo)
    if st.session_state.quiz_started_at:
        st.session_state.quiz_elapsed = time.time() - st.session_state.quiz_started_at
    st.session_state.deadline = None
    st.session_state.screen = "quiz_result"


def submit_quiz_answer():
    if st.session_state.screen != "quiz" or st.session_state.attempts >= MAX_QUESTIONS:
        return
    answer = st.session_state.answer_input
    if answer is None:
        return
    question_text = st.session_state.question["text"]
    correct_answer = st.session_state.question["answer"]
    submitted_answer = float(answer)
    st.session_state.attempts += 1
    is_correct = math.isclose(submitted_answer, float(correct_answer), abs_tol=1e-9)
    if is_correct:
        st.session_state.correct += 1
        st.session_state.combo += 1
        st.session_state.max_combo = max(st.session_state.max_combo, st.session_state.combo)
        st.session_state.message = f"✅ 連擊{st.session_state.combo}！"
    else:
        st.session_state.message = f"❌ 答案是{st.session_state.question['answer']}，連擊中斷。"
        st.session_state.combo = 0
    st.session_state.answer_history.append({
        "question_text": question_text,
        "submitted_answer": submitted_answer,
        "correct_answer": correct_answer,
        "is_correct": is_correct,
        "combo_after": st.session_state.combo,
        "elapsed_seconds": round(time.time() - st.session_state.quiz_started_at, 2),
        "answered_at": database_timestamp(),
    })
    st.session_state.answer_input = None
    if st.session_state.max_combo >= 10 or st.session_state.attempts >= MAX_QUESTIONS:
        finish_quiz()
    else:
        st.session_state.question = make_question(st.session_state.selected_unit)


def process_rewards():
    if st.session_state.result_processed:
        return
    profile = get_profile()
    sync_daily_tasks(profile)
    unit_id = st.session_state.selected_unit
    if unit_id.startswith(f"{highest_unlocked_chapter(profile)}-"):
        profile["daily_practice_count"] = min(2, profile.get("daily_practice_count", 0) + 1)
    old_best = profile["unit_best_stars"][unit_id]
    new_best = max(old_best, st.session_state.stars)
    exp_gain = EXP_BY_STARS[new_best] - EXP_BY_STARS[old_best]
    levels_gained = add_exp(profile, exp_gain) if exp_gain else 0
    if levels_gained:
        st.session_state.level_up_to = profile["level"]
    profile["unit_best_stars"][unit_id] = new_best
    if old_best == 0 and new_best > 0 and award_unit_ticket(profile, unit_id):
        st.session_state.extra_reward_messages.append("首次通過新單元，獲得1張擊殺券！")
    item = make_random_item(profile, unit_id, st.session_state.stars)
    if item:
        profile["inventory"].append(item)
        st.session_state.pending_item_uid = item["uid"]
    elif st.session_state.stars > 0:
        st.session_state.drop_exhausted = True
    if (
        all(profile["unit_best_stars"][unit_id] == 3 for unit_id in chapter_unit_ids("1"))
        and not profile["chapter_reward_claimed"]
    ):
        reward = make_chapter_reward()
        profile["inventory"].append(reward)
        profile["chapter_reward_claimed"] = True
        st.session_state.chapter_reward_new = True
    if has_full_three_star_set(profile, "1") and not profile["collection_reward_claimed"]:
        collection_levels = add_exp(profile, 100)
        profile["collection_reward_claimed"] = True
        st.session_state.collection_reward_new = True
        if collection_levels:
            st.session_state.collection_level_up_to = profile["level"]
    if has_full_three_star_set(profile, "1") and not achievement_item(profile, "chapter-1-collection"):
        reward = make_collection_reward()
        profile["inventory"].append(reward)
        profile["collection_item_claimed"] = True
        st.session_state.extra_reward_messages.append(f"第一章九部位收藏獎勵：{item_text(reward)}")
    if (
        all(profile["unit_best_stars"][uid] == 3 for uid in chapter_unit_ids("2"))
        and not profile["chapter2_reward_claimed"]
    ):
        reward = make_chapter2_reward()
        profile["inventory"].append(reward)
        profile["chapter2_reward_claimed"] = True
        st.session_state.extra_reward_messages.append(f"第二章滿星獎勵：{item_text(reward)}")
    if has_full_three_star_set(profile, "2") and not profile["chapter2_collection_reward_claimed"]:
        collection_levels = add_exp(profile, 100)
        reward = make_chapter2_collection_reward()
        profile["inventory"].append(reward)
        profile["chapter2_collection_reward_claimed"] = True
        if collection_levels:
            st.session_state.collection_level_up_to = profile["level"]
        st.session_state.extra_reward_messages.append(
            f"第二章九部位收藏完成，獲得100 EXP與：{item_text(reward)}"
        )
    st.session_state.earned_exp = exp_gain
    st.session_state.result_processed = True
    save_profile(profile)
    log_attempt(unit_id)


def simulate_battle(stats, boss_type="normal"):
    chapter_id = st.session_state.selected_chapter
    config = BOSS_CONFIGS[f"{chapter_id}_{boss_type}"]
    elite_boss_reduction = stats["boss_hp_reduction"] if boss_type == "elite" else 0.0
    elite_boss_damage = stats["boss_damage_pct"] if boss_type == "elite" else 0.0
    elite_boss_slow = stats["boss_attack_slow_pct"] if boss_type == "elite" else 0.0
    elite_first_hit = stats["first_hit_percent"] if boss_type == "elite" else 0.0
    boss_max = config["hp"] * (1 - elite_boss_reduction)
    boss_hp = boss_max
    core_hp = stats["hp"]
    shield_hp = stats["hp"] * stats["shield_pct"]
    player_hp = core_hp + shield_hp
    hero_interval = 1 / stats["attack_speed"]
    boss_interval = config["interval"] * (1 + elite_boss_slow)
    received = (
        config["damage"] * 100 / (100 + stats["defense"])
        * (1 - stats["damage_reduction_pct"])
    )
    critical_every = round(1 / stats["critical_rate"]) if stats["critical_rate"] > 0 else None
    skill_interval = config.get("skill_interval")
    next_skill = skill_interval if skill_interval else float("inf")
    next_hero, next_boss = 0.0, boss_interval
    hero_hits = boss_hits = 0
    events = [{"time": 0.0, "boss_hp": boss_hp, "player_hp": player_hp, "text": "戰鬥開始"}]
    for _ in range(10000):
        if next_hero <= next_boss and next_hero <= next_skill:
            now = next_hero
            hero_hits += 1
            is_critical = bool(critical_every and hero_hits % critical_every == 0)
            normal_damage = stats["attack"] * (1 + elite_boss_damage)
            if is_critical:
                normal_damage *= 1.5 + stats["critical_damage"]
            damage = normal_damage + (boss_max * elite_first_hit if hero_hits == 1 else 0)
            boss_hp = max(0.0, boss_hp - damage)
            critical_text = "，暴擊！" if is_critical else ""
            events.append({"time": now, "boss_hp": boss_hp, "player_hp": player_hp, "text": f"勇者第{hero_hits}擊{critical_text}造成{damage:.1f}傷害"})
            if boss_hp <= 0:
                return {"victory": True, "duration": now, "events": events}
            next_hero += hero_interval
        elif next_boss <= next_skill:
            now = next_boss
            boss_hits += 1
            boss_critical = bool(config.get("critical_rate") and boss_hits % round(1 / config["critical_rate"]) == 0)
            hit_damage = received * (1.5 if boss_critical else 1.0)
            shield_absorbed = min(shield_hp, hit_damage)
            shield_hp -= shield_absorbed
            core_hp = max(0.0, core_hp - (hit_damage - shield_absorbed))
            player_hp = core_hp + shield_hp
            critical_text = "，暴擊！" if boss_critical else ""
            events.append({"time": now, "boss_hp": boss_hp, "player_hp": player_hp, "text": f"BOSS第{boss_hits}擊{critical_text}造成{hit_damage:.1f}傷害"})
            if core_hp <= 0:
                return {"victory": False, "duration": now, "events": events}
            next_boss += boss_interval
        else:
            now = next_skill
            true_damage = config.get("true_damage", 0)
            core_hp = max(0.0, core_hp - true_damage)
            player_hp = core_hp + shield_hp
            events.append({
                "time": now, "boss_hp": boss_hp, "player_hp": player_hp,
                "text": f"BOSS施放技能「{config.get('skill')}」，造成{true_damage:g}真實傷害！",
            })
            if core_hp <= 0:
                return {"victory": False, "duration": now, "events": events}
            next_skill += skill_interval
    raise RuntimeError("戰鬥計算超出限制")


def finish_battle(result):
    if st.session_state.battle_recorded:
        return
    profile = get_profile()
    exp_gain = 0
    level_up_to = None
    reward_item_uid = None
    boss_type = st.session_state.selected_boss_type
    chapter_id = st.session_state.selected_chapter
    config = BOSS_CONFIGS[f"{chapter_id}_{boss_type}"]
    if result["victory"]:
        key_map = {
            ("1", "normal"): ("boss_wins", "boss_exp_claimed"),
            ("1", "elite"): ("elite_boss_wins", "elite_boss_exp_claimed"),
            ("2", "normal"): ("chapter2_boss_wins", "chapter2_boss_exp_claimed"),
            ("2", "elite"): ("chapter2_elite_boss_wins", "chapter2_elite_boss_exp_claimed"),
            ("3", "normal"): ("chapter3_boss_wins", "chapter3_boss_exp_claimed"),
            ("3", "elite"): ("chapter3_elite_boss_wins", "chapter3_elite_boss_exp_claimed"),
        }
        wins_key, exp_key = key_map[(chapter_id, boss_type)]
        profile[wins_key] += 1
        if not profile[exp_key]:
            exp_gain = config["exp"]
            levels_gained = add_exp(profile, exp_gain)
            if levels_gained:
                level_up_to = profile["level"]
            profile[exp_key] = True
        reward_claimed_key = {"1": "elite_reward_claimed", "2": "chapter2_elite_reward_claimed"}.get(chapter_id)
        if boss_type == "elite" and reward_claimed_key and not profile[reward_claimed_key]:
            reward = make_elite_reward() if chapter_id == "1" else make_chapter2_elite_reward()
            profile["inventory"].append(reward)
            profile[reward_claimed_key] = True
            reward_item_uid = reward["uid"]
        if boss_type == "elite" and chapter_id in ("1", "2"):
            earned_title = "好像有點勇哦" if chapter_id == "1" else "別小看我！"
            if earned_title not in profile["titles"]:
                profile["titles"].append(earned_title)
                result["earned_title"] = earned_title
        best_time_key = f"{chapter_id}_{boss_type}"
        previous_best = profile["boss_best_times"].get(best_time_key)
        if previous_best is None or result["duration"] < previous_best:
            profile["boss_best_times"][best_time_key] = round(result["duration"], 2)
        save_best_ranking(profile, result["duration"], boss_type, chapter_id)
    save_profile(profile)
    result["exp_gain"] = exp_gain
    result["level_up_to"] = level_up_to
    result["reward_item_uid"] = reward_item_uid
    result["boss_type"] = boss_type
    result["chapter_id"] = chapter_id
    st.session_state.battle_result = result
    st.session_state.battle_recorded = True
    st.session_state.screen = "boss_result"


def render_stats(profile):
    stats = player_stats(profile)
    breakdown = stats["breakdown"]
    base = breakdown["base"]
    flat = breakdown["flat"]
    pct = breakdown["pct"]

    def formula_help(stat_key, pct_key, final_value, unit=""):
        multiplier = 1 + pct[pct_key]
        return (
            f"計算：({base[stat_key]:.2f} + {flat[stat_key]:.2f}) "
            f"× {multiplier:.2f} = {final_value:.2f}{unit}\n\n"
            f"等級基礎值：{base[stat_key]:.2f}{unit}\n\n"
            f"裝備固定值：+{flat[stat_key]:.2f}{unit}\n\n"
            f"附加詞條：+{pct[pct_key]:.0%}"
        )

    cols = st.columns(5)
    cols[0].metric(
        "等級",
        f"Lv{profile['level']}",
        help="每升一級，HP、攻擊力與防禦力的等級基礎值增加10%。",
    )
    cols[1].metric(
        "HP", f"{stats['hp']:.1f}",
        help=formula_help("hp", "hp_pct", stats["hp"]),
    )
    cols[2].metric(
        "攻擊", f"{stats['attack']:.1f}",
        help=formula_help("attack", "attack_pct", stats["attack"]),
    )
    cols[3].metric(
        "防禦", f"{stats['defense']:.1f}",
        help=formula_help("defense", "defense_pct", stats["defense"]),
    )
    cols[4].metric(
        "攻速", f"{stats['attack_speed']:.2f}/秒",
        help=formula_help("attack_speed", "speed_pct", stats["attack_speed"], "/秒"),
    )
    special_effects = [
        ("菁英BOSS初始血量降低", stats["boss_hp_reduction"]),
        ("第一擊額外扣除菁英BOSS血量", stats["first_hit_percent"]),
        ("對菁英BOSS傷害", stats["boss_damage_pct"]),
        ("傷害減免", stats["damage_reduction_pct"]),
        ("暴擊率", stats["critical_rate"]),
        ("暴擊傷害", stats["critical_damage"]),
        ("開場護盾", stats["shield_pct"]),
        ("菁英BOSS攻速降低", stats["boss_attack_slow_pct"]),
    ]
    active_effects = [f"{name} +{value:.0%}" for name, value in special_effects if value]
    if active_effects:
        st.caption("附屬能力：" + "｜".join(active_effects))
    else:
        st.caption("附屬能力：目前無")
    if stats["critical_rate"]:
        critical_every = round(1 / stats["critical_rate"])
        st.caption(f"排行榜採固定暴擊：目前每第 {critical_every} 擊必定暴擊，不使用隨機判定。")
    elif stats["critical_damage"]:
        st.caption("目前暴擊率為0%，因此暴擊傷害詞條暫時不會生效；需要先取得暴擊率。")
    if profile["level"] < 20:
        st.progress(profile["exp"] / (profile["level"] * 100))
        st.caption(f"EXP：{profile['exp']} / {profile['level'] * 100}")
    else:
        st.caption("已達最高等級 Lv20")


def render_health_bar(label, current, maximum, color):
    ratio = max(0.0, min(1.0, current / maximum if maximum else 0.0))
    label_col, bar_col = st.columns([1.3, 8.7], vertical_alignment="center")
    label_col.markdown(f"**{label}**  \n{current:.1f} / {maximum:.1f}")
    bar_col.markdown(
        f"""
        <div style="width:100%;height:24px;background:#e9edf2;border-radius:12px;overflow:hidden;">
          <div style="width:{ratio * 100:.2f}%;height:100%;background:{color};border-radius:12px;"></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


BOSS_WIN_KEYS = {
    ("1", "normal"): "boss_wins",
    ("1", "elite"): "elite_boss_wins",
    ("2", "normal"): "chapter2_boss_wins",
    ("2", "elite"): "chapter2_elite_boss_wins",
    ("3", "normal"): "chapter3_boss_wins",
    ("3", "elite"): "chapter3_elite_boss_wins",
}
SKILL_CINEMATIC_SECONDS = 1.5


def boss_has_been_cleared(profile, chapter_id, boss_type):
    """是否曾經成功擊敗這一章、這一類 BOSS。"""
    return int(profile.get(BOSS_WIN_KEYS[(chapter_id, boss_type)], 0) or 0) > 0


def battle_presentation_state(result, real_elapsed):
    """把技能演出插入戰鬥時間軸；演出期間模擬時間暫停。"""
    skill_events = [event for event in result["events"] if "施放技能" in event["text"]]
    paused_seconds = 0.0
    active_skill = None
    simulated_elapsed = real_elapsed
    for event in skill_events:
        cinematic_start = event["time"] + paused_seconds
        if real_elapsed < cinematic_start:
            break
        if real_elapsed < cinematic_start + SKILL_CINEMATIC_SECONDS:
            active_skill = event
            simulated_elapsed = event["time"]
            break
        paused_seconds += SKILL_CINEMATIC_SECONDS
        simulated_elapsed = real_elapsed - paused_seconds
    presentation_duration = result["duration"] + len(skill_events) * SKILL_CINEMATIC_SECONDS
    return simulated_elapsed, active_skill, presentation_duration


def render_battle_scene(event, boss_type, active_skill=None):
    hero_attacking = event["text"].startswith("勇者") and active_skill is None
    boss_attacking = ("BOSS第" in event["text"] or "BOSS發動" in event["text"]) and active_skill is None
    hero_class = "fighter hero hero-attack" if hero_attacking else "fighter hero"
    boss_class = "fighter boss boss-attack" if boss_attacking else "fighter boss"
    boss_icon = "🐉" if boss_type == "elite" else "👹"
    skill_overlay = ""
    if active_skill:
        skill_overlay = (
            '<div class="skill-cinematic"><div class="skill-flame">🔥</div>'
            f'<strong>{active_skill["text"]}</strong><div>戰鬥計時暫停</div></div>'
        )
    st.markdown(
        f"""
        <style>
        .battle-arena {{position:relative;height:250px;margin:14px 0 18px;padding:24px;
          overflow:hidden;border-radius:22px;background:linear-gradient(#dff3ff 0 62%,#c7e5ad 62%);
          border:2px solid #d8e1ea;display:flex;align-items:flex-end;justify-content:space-between;}}
        .fighter {{font-size:88px;line-height:1;text-align:center;filter:drop-shadow(0 8px 5px #0003);}}
        .fighter span {{display:block;margin-top:10px;font-size:20px;font-weight:700;color:#313442;}}
        .hero-attack {{animation:heroStrike .5s ease-in-out;}}
        .boss-attack {{animation:bossStrike .5s ease-in-out;}}
        .skill-cinematic {{position:absolute;inset:0;z-index:5;display:flex;flex-direction:column;
          align-items:center;justify-content:center;color:white;font-size:26px;text-align:center;
          background:radial-gradient(circle,#ff7a18dd,#8b0000ee);animation:skillFlash .55s ease-in-out infinite alternate;}}
        .skill-flame {{font-size:82px;animation:flameGrow .5s ease-in-out infinite alternate;}}
        @keyframes heroStrike {{50%{{transform:translateX(110px) rotate(-8deg) scale(1.12);}}}}
        @keyframes bossStrike {{50%{{transform:translateX(-110px) rotate(8deg) scale(1.12);}}}}
        @keyframes skillFlash {{to{{filter:brightness(1.35);}}}}
        @keyframes flameGrow {{to{{transform:scale(1.35) rotate(8deg);}}}}
        </style>
        <div class="battle-arena">
          <div class="{hero_class}">🦸<span>勇者</span></div>
          <div class="{boss_class}">{boss_icon}<span>{'菁英 BOSS' if boss_type == 'elite' else '一般 BOSS'}</span></div>
          {skill_overlay}
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_chapter_boss_card(chapter_id, boss_type, unlocked):
    """在章節單元下方顯示 BOSS 能力與挑戰入口。"""
    config = BOSS_CONFIGS[f"{chapter_id}_{boss_type}"]
    is_elite = boss_type == "elite"
    label = "菁英 BOSS" if is_elite else "一般 BOSS"
    with st.container(border=True):
        info_col, button_col = st.columns([4, 1.35], vertical_alignment="center")
        info_col.markdown(f"### {'🐲' if is_elite else '🐉'} {label}｜{config['name']}")
        info_col.write(
            f"**HP：{config['hp']}**　｜　"
            f"**攻擊：每 {config['interval']:g} 秒造成 {config['damage']} 傷害**"
        )
        abilities = []
        if config.get("critical_rate"):
            abilities.append(
                f"暴擊率 {config['critical_rate']:.0%}（每第 5 次攻擊必定暴擊，造成 1.5 倍傷害）"
            )
        if config.get("skill"):
            abilities.append(
                f"技能「{config['skill']}」：每 {config['skill_interval']:g} 秒造成 "
                f"{config['true_damage']:g} 真實傷害"
            )
        info_col.write("**能力／技能：**" + ("；".join(abilities) if abilities else "無"))
        if button_col.button(
            "開始挑戰" if unlocked else "尚未解鎖",
            key=f"chapter_boss_{chapter_id}_{boss_type}",
            disabled=not unlocked,
            type="primary" if unlocked else "secondary",
            use_container_width=True,
        ):
            st.session_state.selected_boss_type = boss_type
            st.session_state.scroll_boss_to_top = True
            st.session_state.screen = "boss_ready"
            st.rerun()


init_db()
if USE_POSTGRES and not ADMIN_PIN_SECRET:
    st.error("公開版尚未設定 ADMIN_PIN，已停止登入以保護老師後台。")
    st.info("請到 Streamlit App settings → Secrets 設定 ADMIN_PIN 與 DATABASE_URL。")
    st.stop()
if not ADMIN_PIN_SECRET and setting_get("admin_pin_hash") is None:
    st.session_state.screen = "bootstrap"
elif st.session_state.screen == "bootstrap":
    st.session_state.screen = "login"

active_chapter_id = st.session_state.get("selected_chapter", "1")
if active_chapter_id not in CHAPTERS:
    active_chapter_id = "1"
if st.session_state.screen in {"menu", "quiz", "quiz_result", "boss_ready", "boss_watch", "boss_result"}:
    active_chapter = CHAPTERS[active_chapter_id]
    st.title(f"⚔️ 數學冒險：{active_chapter['number']}－{active_chapter['name']}")
else:
    st.title("⚔️ 數學冒險")

home_return_screens = {
    "character_stats", "menu", "inventory", "rankings", "economy", "daily_tasks",
    "quiz", "quiz_result", "sweep_result", "boss_ready", "boss_result",
}
if st.session_state.get("active_player") and st.session_state.screen in home_return_screens:
    if st.button("← 回到首頁", key=f"home_return_{st.session_state.screen}"):
        st.session_state.shop_purchase_uid = None
        st.session_state.forge_result_uid = None
        st.session_state.screen = "home"
        st.rerun()

if st.session_state.screen == "bootstrap":
    st.subheader("首次設定：建立老師管理PIN")
    st.info("管理PIN用來建立、重設或刪除學生帳號，請妥善保存。")
    admin_pin = st.text_input("設定管理PIN（至少6位）", type="password")
    admin_pin_again = st.text_input("再次輸入管理PIN", type="password")
    if st.button("完成首次設定", type="primary", use_container_width=True):
        if len(admin_pin) < 6:
            st.warning("管理PIN至少需要6位。")
        elif admin_pin != admin_pin_again:
            st.warning("兩次輸入的管理PIN不一致。")
        else:
            set_admin_pin(admin_pin)
            st.session_state.screen = "login"
            st.success("管理PIN設定完成。")
            st.rerun()

elif st.session_state.screen == "login":
    role = st.radio("登入身分", ["學生", "老師"], horizontal=True)
    if role == "學生":
        login_tab, register_tab = st.tabs(["登入", "建立新勇者"])
        with login_tab:
            code = st.text_input("學生代碼", placeholder="例如 A001").strip().upper()
            pin = st.text_input("6位PIN", type="password", max_chars=6, key="login_pin")
            if st.button("學生登入", type="primary", use_container_width=True):
                valid, result = verify_student(code, pin)
                if valid:
                    st.session_state.active_player = result
                    st.session_state.screen = "home"
                    st.rerun()
                else:
                    st.error(result)
        with register_tab:
            if setting_get("registration_enabled") == "1":
                real_name = st.text_input("正式姓名（僅老師後台可見）", max_chars=30, key="register_real_name").strip()
                hero_name = st.text_input("設定勇者名稱", max_chars=12, key="register_hero").strip()
                new_pin = st.text_input("設定6位數字PIN", type="password", max_chars=6, key="register_pin")
                new_pin_again = st.text_input("再次輸入PIN", type="password", max_chars=6, key="register_pin_again")
                if st.button("建立新勇者", type="primary", use_container_width=True):
                    name_error = validate_hero_name(hero_name)
                    if not real_name:
                        st.warning("請輸入正式姓名，方便老師辨識身分。")
                    elif name_error:
                        st.warning(name_error)
                    elif len(new_pin) != 6 or not new_pin.isdigit():
                        st.warning("PIN必須是6位數字。")
                    elif new_pin != new_pin_again:
                        st.warning("兩次輸入的PIN不一致。")
                    else:
                        try:
                            st.session_state.created_account = create_student(real_name, hero_name, new_pin)
                        except ValueError as error:
                            st.warning(str(error))
                if st.session_state.created_account:
                    account = st.session_state.created_account
                    st.success("建立完成！請截圖或抄下學生代碼，之後登入會使用它。")
                    st.code(f"正式姓名：{account['real_name']}\n勇者名稱：{account['hero_name']}\n學生代碼：{account['student_code']}")
                    st.caption("排行榜只會顯示勇者名稱與大頭貼，不會公開正式姓名。")
            else:
                st.info("老師目前已關閉新學生註冊。")
    else:
        admin_pin = st.text_input("老師管理PIN", type="password")
        if st.button("進入管理後台", type="primary", use_container_width=True):
            if verify_admin_pin(admin_pin):
                st.session_state.admin_authenticated = True
                st.session_state.screen = "admin_panel"
                st.rerun()
            else:
                st.error("管理PIN錯誤。")

elif st.session_state.screen == "admin_panel":
    if not st.session_state.admin_authenticated:
        st.session_state.screen = "login"
        st.rerun()
    st.subheader("🧑‍🏫 老師管理後台")
    with db_connection() as db:
        teacher_row = db.execute(
            "SELECT hero_name FROM players WHERE student_code='__TEACHER__'"
        ).fetchone()
    teacher_default_name = teacher_row["hero_name"] if teacher_row else "老師測試勇者"
    teacher_col1, teacher_col2 = st.columns([2, 1])
    teacher_hero_name = teacher_col1.text_input(
        "老師測試角色名稱", value=teacher_default_name, max_chars=12
    ).strip()
    if teacher_col2.button("進入老師測試角色", type="primary", use_container_width=True):
        teacher_name_error = validate_hero_name(teacher_hero_name)
        if not teacher_name_error:
            st.session_state.active_player = ensure_teacher_profile(teacher_hero_name)
            st.session_state.screen = "home"
            st.rerun()
        else:
            st.warning(teacher_name_error)
    st.caption("老師測試角色不需要學生代碼或額外PIN，也不會占用學生編號或學生排名。")
    st.divider()
    create_tab, manage_tab, progress_tab = st.tabs(["建立學生", "帳號管理", "測試進度"])
    with create_tab:
        registration_enabled = setting_get("registration_enabled") == "1"
        new_registration_state = st.toggle("允許學生自行註冊", value=registration_enabled)
        if new_registration_state != registration_enabled:
            setting_set("registration_enabled", "1" if new_registration_state else "0")
            st.rerun()
        st.divider()
        st.caption("老師也可以代替學生建立帳號；系統會產生一次性顯示的PIN。")
        real_name = st.text_input("學生正式姓名", max_chars=30, key="new_real_name").strip()
        hero_name = st.text_input("勇者名稱", max_chars=12, key="new_hero_name").strip()
        if st.button("產生學生代碼與PIN", type="primary"):
            name_error = validate_hero_name(hero_name)
            if not real_name:
                st.warning("請輸入學生正式姓名。")
            elif name_error:
                st.warning(name_error)
            else:
                generated_pin = f"{secrets.randbelow(1000000):06d}"
                try:
                    st.session_state.created_account = create_student(real_name, hero_name, generated_pin)
                except ValueError as error:
                    st.warning(str(error))
        if st.session_state.created_account:
            account = st.session_state.created_account
            st.success("帳號已建立，PIN只會在這裡顯示，請交給學生保存。")
            st.code(f"正式姓名：{account['real_name']}\n勇者名稱：{account['hero_name']}\n學生代碼：{account['student_code']}\nPIN：{account['pin']}")
    with manage_tab:
        students = student_rows()
        if students:
            st.dataframe(students, hide_index=True, use_container_width=True)
            choices = {f"{row['學生代碼']}｜{row['勇者名稱']}": row["學生代碼"] for row in students}
            selected_label = st.selectbox("選擇學生", choices)
            selected_code = choices[selected_label]
            selected_row = next(row for row in students if row["學生代碼"] == selected_code)
            corrected_name = st.text_input(
                "正式姓名（僅老師可見）", value=selected_row["正式姓名"],
                max_chars=30, key=f"real_name_{selected_code}",
            ).strip()
            save_name_col, confirm_col, delete_col = st.columns([1.25, 1.35, 1])
            if save_name_col.button("儲存正式姓名", disabled=not corrected_name, use_container_width=True):
                update_student_real_name(selected_code, corrected_name)
                st.success("正式姓名已更新。")
                st.rerun()
            confirm_delete = confirm_col.checkbox(
                "確認刪除人物與紀錄", key=f"confirm_delete_{selected_code}"
            )
            if delete_col.button(
                "刪除學生", disabled=not confirm_delete, use_container_width=True,
                key=f"delete_student_{selected_code}",
            ):
                delete_student(selected_code)
                st.success(f"已刪除 {selected_code}。")
                st.rerun()
            detail_profile = student_learning_detail(selected_code)
            if detail_profile:
                detail_stats = player_stats(detail_profile)
                st.write("### 角色等級與能力值")
                stat_cols = st.columns(6)
                stat_cols[0].metric("等級", f"Lv{detail_profile['level']}")
                next_exp = detail_profile["level"] * 100 if detail_profile["level"] < 20 else None
                stat_cols[1].metric(
                    "EXP", f"{detail_profile['exp']} / {next_exp}" if next_exp else "MAX"
                )
                stat_cols[2].metric("HP", f"{detail_stats['hp']:.1f}")
                stat_cols[3].metric("攻擊", f"{detail_stats['attack']:.1f}")
                stat_cols[4].metric("防禦", f"{detail_stats['defense']:.1f}")
                stat_cols[5].metric("攻速", f"{detail_stats['attack_speed']:.2f}/秒")
                special_stats = [
                    ("菁英BOSS初始血量降低", detail_stats["boss_hp_reduction"]),
                    ("第一擊額外扣除菁英BOSS血量", detail_stats["first_hit_percent"]),
                    ("對菁英BOSS傷害", detail_stats["boss_damage_pct"]),
                    ("傷害減免", detail_stats["damage_reduction_pct"]),
                    ("暴擊率", detail_stats["critical_rate"]),
                    ("暴擊傷害", detail_stats["critical_damage"]),
                    ("開場護盾", detail_stats["shield_pct"]),
                    ("菁英BOSS攻速降低", detail_stats["boss_attack_slow_pct"]),
                ]
                active_specials = [f"{name} {value:.0%}" for name, value in special_stats if value]
                st.caption("特殊能力：" + ("｜".join(active_specials) if active_specials else "目前無"))
                st.caption(
                    f"🪙 金幣：{detail_profile.get('coins', 0)}｜"
                    f"💎 融煉石：{detail_profile.get('smelting_stones', 0)}｜"
                    f"部位石：{detail_profile.get('slot_smelting_stones', 0)}｜"
                    f"基礎詞條石：{detail_profile.get('basic_affix_smelting_stones', 0)}｜"
                    f"進階詞條石：{detail_profile.get('advanced_affix_smelting_stones', 0)}"
                )
                st.caption(
                    f"🎫 擊殺券：{detail_profile.get('sweep_tickets', 0)}｜"
                    f"目前稱號：{detail_profile.get('equipped_title') or '未佩戴'}｜"
                    f"已解鎖稱號：{'、'.join(detail_profile.get('titles', [])) or '無'}"
                )

                st.write("### 學習與通關進度")
                progress_rows = []
                for unit_id, unit in UNITS.items():
                    stars = detail_profile["unit_best_stars"].get(unit_id, 0)
                    progress_rows.append({
                        "單元": unit_id, "名稱": unit["name"],
                        "最高星級": "⭐" * stars if stars else "尚未通關",
                    })
                st.dataframe(progress_rows, hide_index=True, use_container_width=True)
                boss_progress = [
                    f"第一章一般BOSS：{detail_profile.get('boss_wins', 0)}次",
                    f"第一章菁英BOSS：{detail_profile.get('elite_boss_wins', 0)}次",
                    f"第二章一般BOSS：{detail_profile.get('chapter2_boss_wins', 0)}次",
                    f"第二章菁英BOSS：{detail_profile.get('chapter2_elite_boss_wins', 0)}次",
                    f"第三章一般BOSS：{detail_profile.get('chapter3_boss_wins', 0)}次",
                    f"第三章菁英BOSS：{detail_profile.get('chapter3_elite_boss_wins', 0)}次",
                ]
                st.caption("｜".join(boss_progress))

                st.write("### 目前穿戴裝備")
                equipment_rows = []
                for slot, slot_name in SLOT_NAMES.items():
                    uid = detail_profile["equipment"].get(slot)
                    equipped = find_item(detail_profile, uid) if uid else None
                    equipment_rows.append({
                        "部位": f"{SLOT_ICONS[slot]} {slot_name}",
                        "裝備": item_text(equipped) if equipped else "尚未裝備",
                    })
                st.dataframe(equipment_rows, hide_index=True, use_container_width=True)

                st.write(f"### 完整物品欄（{len(detail_profile['inventory'])}件）")
                star_counts = {
                    stars: sum(1 for item in detail_profile["inventory"] if item.get("stars") == stars)
                    for stars in range(1, 6)
                }
                st.caption("｜".join(
                    f"{'⭐' * stars}：{count}件" for stars, count in star_counts.items() if count
                ) or "目前沒有物品")
                inventory_rows = []
                sorted_inventory = sorted(
                    detail_profile["inventory"],
                    key=lambda item: (-item.get("stars", 0), list(SLOT_NAMES).index(item["slot"])),
                )
                for item in sorted_inventory:
                    source_id = item_chapter_id(item)
                    source = CHAPTERS[source_id]["number"] if source_id in CHAPTERS else "成就／BOSS"
                    inventory_rows.append({
                        "穿戴": "✅" if detail_profile["equipment"].get(item["slot"]) == item["uid"] else "",
                        "部位": f"{SLOT_ICONS[item['slot']]} {SLOT_NAMES[item['slot']]}",
                        "裝備名稱": item["name"],
                        "星級": "⭐" * item["stars"],
                        "固定能力": fixed_text(item),
                        "附屬能力": f"{AFFIX_NAMES[item['affix_stat']]} +{item['affix_value']:.0%}",
                        "來源": source,
                    })
                if inventory_rows:
                    st.dataframe(inventory_rows, hide_index=True, use_container_width=True)
                else:
                    st.info("目前物品欄是空的。")

                st.write("### 作答明細")
                errors_only = st.toggle("只顯示答錯題目", value=True, key=f"errors_{selected_code}")
                question_rows = student_question_rows(selected_code, errors_only=errors_only)
                if question_rows:
                    st.dataframe(question_rows, hide_index=True, use_container_width=True)
                else:
                    st.info("目前沒有符合條件的題目紀錄；新版上線前的作答無法回溯題目與答案。")
            if st.button("重設為新的6位PIN", use_container_width=True):
                new_pin = reset_student_pin(selected_code)
                st.success(f"{selected_code} 的新PIN：{new_pin}（請立即記下）")
        else:
            st.info("目前尚未建立學生帳號。")
    with progress_tab:
        rows = ranking_rows("normal", include_private_identity=True)
        st.write("### 第一章一般BOSS最佳排名")
        if rows:
            render_ranking(rows)
        else:
            st.info("目前尚無BOSS通關紀錄。")
        elite_rows = ranking_rows("elite", include_private_identity=True)
        st.write("### 第一章菁英BOSS最佳排名")
        if elite_rows:
            render_ranking(elite_rows)
        else:
            st.info("目前尚無菁英BOSS通關紀錄。")
        chapter2_rows = ranking_rows("normal", "2", include_private_identity=True)
        st.write("### 第二章一般BOSS最佳排名")
        if chapter2_rows:
            render_ranking(chapter2_rows)
        else:
            st.info("目前尚無第二章一般BOSS通關紀錄。")
        chapter2_elite_rows = ranking_rows("elite", "2", include_private_identity=True)
        st.write("### 第二章菁英BOSS最佳排名")
        if chapter2_elite_rows:
            render_ranking(chapter2_elite_rows)
        else:
            st.info("目前尚無第二章菁英BOSS通關紀錄。")
        chapter3_rows = ranking_rows("normal", "3", include_private_identity=True)
        st.write("### 第三章一般BOSS最佳排名")
        if chapter3_rows:
            render_ranking(chapter3_rows)
        else:
            st.info("目前尚無第三章一般BOSS通關紀錄。")
        chapter3_elite_rows = ranking_rows("elite", "3", include_private_identity=True)
        st.write("### 第三章菁英BOSS最佳排名")
        if chapter3_elite_rows:
            render_ranking(chapter3_elite_rows)
        else:
            st.info("目前尚無第三章菁英BOSS通關紀錄。")
        with db_connection() as db:
            attempts = [dict(row) for row in db.execute(
                "SELECT p.student_code AS 學生代碼, p.real_name AS 正式姓名, "
                "p.hero_name AS 勇者, a.unit_id AS 單元, a.stars AS 星級, "
                "a.max_combo AS 最高連擊, a.correct_count AS 答對題數, "
                "ROUND(CAST(a.average_seconds AS NUMERIC), 1) AS 平均每題秒數, a.finished_at AS 完成時間 "
                "FROM attempts a JOIN players p ON p.student_code=a.student_code ORDER BY a.id DESC LIMIT 200"
            ).fetchall()]
        for attempt in attempts:
            attempt["完成時間"] = taipei_time_text(attempt["完成時間"])
        st.write("### 最近200筆答題紀錄")
        if attempts:
            st.dataframe(attempts, hide_index=True, use_container_width=True)
    if st.button("登出管理後台"):
        st.session_state.admin_authenticated = False
        st.session_state.created_account = None
        st.session_state.screen = "login"
        st.rerun()

elif st.session_state.screen == "home":
    profile = get_profile()
    if sync_daily_tasks(profile):
        save_profile(profile)
    if profile.get("retro_reward_notice"):
        st.success("🎁 補發獎勵：" + "；".join(profile["retro_reward_notice"]) + "。可到背包查看。")
        profile["retro_reward_notice"] = []
        save_profile(profile)

    name_col, money_col = st.columns([4, 2], vertical_alignment="center")
    title_prefix = f"「{profile['equipped_title']}」" if profile.get("equipped_title") else ""
    name_col.subheader(f"{title_prefix}{profile['name']}")
    money_col.markdown(f"### 金幣 🪙 {profile.get('coins', 0)}")
    render_avatar_editor(profile)

    st.markdown(
        """
        <style>
        @media (max-width: 640px) {
          .st-key-home_nav_row_1 [data-testid="stHorizontalBlock"],
          .st-key-home_nav_row_2 [data-testid="stHorizontalBlock"] {display:flex !important;flex-wrap:nowrap !important;gap:.25rem !important;}
          .st-key-home_nav_row_1 [data-testid="column"],
          .st-key-home_nav_row_2 [data-testid="column"] {min-width:0 !important;width:25% !important;flex:1 1 25% !important;}
          .st-key-home_nav_row_1 button,
          .st-key-home_nav_row_2 button {padding:.45rem .12rem !important;font-size:.78rem !important;white-space:normal !important;min-height:3.2rem;}
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    with st.container(key="home_nav_row_1"):
        nav1 = st.columns(4)
    with st.container(key="home_nav_row_2"):
        nav2 = st.columns(4)

    if nav1[0].button("🧙 角色能力", use_container_width=True):
        st.session_state.screen = "character_stats"
        st.rerun()
    if nav1[1].button("🗺️ 關卡", use_container_width=True):
        st.session_state.screen = "menu"
        st.rerun()
    if nav1[2].button("🎒 背包", use_container_width=True):
        st.session_state.inventory_view = "backpack"
        st.session_state.inventory_default_tab = "背包"
        st.session_state.inventory_tab_version += 1
        st.session_state.scroll_inventory_to_top = True
        st.session_state.screen = "inventory"
        st.rerun()
    if nav1[3].button("📖 圖鑑", use_container_width=True):
        st.session_state.inventory_view = "gallery"
        st.session_state.inventory_default_tab = "圖鑑收集"
        st.session_state.inventory_tab_version += 1
        st.session_state.scroll_inventory_to_top = True
        st.session_state.screen = "inventory"
        st.rerun()
    if nav2[0].button("🏪 商店", use_container_width=True):
        st.session_state.economy_mode = "shop"
        st.session_state.scroll_economy_to_top = True
        st.session_state.screen = "economy"
        st.rerun()
    if nav2[1].button("🔥 融煉", use_container_width=True):
        st.session_state.economy_mode = "forge"
        st.session_state.scroll_economy_to_top = True
        st.session_state.screen = "economy"
        st.rerun()
    if nav2[2].button("🏆 排行榜", use_container_width=True):
        st.session_state.scroll_ranking_to_top = True
        st.session_state.screen = "rankings"
        st.rerun()
    if nav2[3].button("📋 任務", use_container_width=True):
        st.session_state.screen = "daily_tasks"
        st.rerun()

    if st.session_state.active_player == "__TEACHER__":
        if st.button("返回老師管理後台"):
            st.session_state.active_player = None
            st.session_state.screen = "admin_panel"
            st.rerun()
    elif st.button("登出學生帳號"):
        st.session_state.active_player = None
        st.session_state.screen = "login"
        st.rerun()

elif st.session_state.screen == "character_stats":
    profile = get_profile()
    st.subheader("🧙 角色能力")
    render_stats(profile)
    st.divider()
    st.subheader("⚔️ 目前裝備")
    for slot, label in SLOT_NAMES.items():
        uid = profile["equipment"].get(slot)
        item = find_item(profile, uid) if uid else None
        cols = st.columns([2, 6, 1])
        cols[0].write(f"**{SLOT_ICONS[slot]} {label}**")
        cols[1].write(item_text(item) if item else "— 尚未裝備 —")
        if item and cols[2].button("卸下", key=f"stats_off_{slot}"):
            profile["equipment"][slot] = None
            save_profile(profile)
            st.rerun()

elif st.session_state.screen == "menu":
    profile = get_profile()
    if sync_daily_tasks(profile):
        save_profile(profile)
    if profile.get("retro_reward_notice"):
        st.success("🎁 補發獎勵：" + "；".join(profile["retro_reward_notice"]) + "。可到背包的消耗道具與成就稱號查看。")
        profile["retro_reward_notice"] = []
        save_profile(profile)
    chapter_id = st.selectbox(
        "選擇章節",
        options=list(CHAPTERS),
        index=list(CHAPTERS).index(st.session_state.selected_chapter),
        format_func=lambda cid: f"{CHAPTERS[cid]['number']}｜{CHAPTERS[cid]['name']}",
    )
    if chapter_id != st.session_state.selected_chapter:
        st.session_state.selected_chapter = chapter_id
        st.rerun()
    current_unit_ids = chapter_unit_ids(chapter_id)
    total_stars = sum(profile["unit_best_stars"][unit_id] for unit_id in current_unit_ids)
    max_stars = len(current_unit_ids) * 3
    st.write(f"{CHAPTERS[chapter_id]['number']}星級：**{total_stars}／{max_stars}** {'⭐' * total_stars}")
    st.subheader("選擇單元")
    for unit_id in current_unit_ids:
        unit = UNITS[unit_id]
        unlocked = unit_unlocked(profile, unit_id)
        cols = st.columns([1, 4, 1, 1])
        cols[0].write(f"### {unit_id}")
        cols[1].write(f"**{unit['name']}**｜{unit['description']}  \n掉落：{'、'.join(SLOT_NAMES[s] for s in unit['slots'])}")
        stars = profile["unit_best_stars"][unit_id]
        if unlocked:
            if cols[2].button(f"{'⭐' * stars or '未通關'}｜開始", key=f"start_{unit_id}", use_container_width=True):
                start_quiz(unit_id)
                st.rerun()
            if cols[3].button(
                f"🎫 擊殺券 ×{profile['sweep_tickets']}", key=f"sweep_{unit_id}",
                disabled=stars <= 0 or profile["sweep_tickets"] <= 0, use_container_width=True,
                help="直接依本單元最高星級取得一次裝備，不獲得經驗值。",
            ):
                item = make_random_item(profile, unit_id, stars)
                profile["sweep_tickets"] -= 1
                if item:
                    profile["inventory"].append(item)
                    st.session_state.sweep_result_uid = item["uid"]
                else:
                    st.session_state.sweep_result_uid = "none"
                save_profile(profile)
                st.session_state.screen = "sweep_result"
                st.rerun()
        else:
            cols[2].button("🔒 尚未解鎖", disabled=True, key=f"locked_{unit_id}", use_container_width=True)
            cols[3].button("🎫 尚未通關", disabled=True, key=f"sweep_locked_{unit_id}", use_container_width=True)
    boss_unlocked = all(profile["unit_best_stars"][uid] == 3 for uid in current_unit_ids)
    normal_win_keys = {"1": "boss_wins", "2": "chapter2_boss_wins", "3": "chapter3_boss_wins"}
    elite_unlocked = profile.get(normal_win_keys[chapter_id], 0) > 0
    st.write("### 章節 BOSS")
    render_chapter_boss_card(chapter_id, "normal", boss_unlocked)
    if not boss_unlocked:
        st.caption("本章所有單元都達成三星後，解鎖一般 BOSS。")
    render_chapter_boss_card(chapter_id, "elite", elite_unlocked)
    if not elite_unlocked:
        st.caption("首次擊敗本章一般 BOSS 後，解鎖菁英 BOSS；挑戰失敗時可以繼續刷單元強化裝備。")
    if chapter_id == "1":
        if profile["chapter_reward_claimed"]:
            st.success("第一章滿星成就已完成：★★★★ 整數勇者之劍｜固定：攻擊力 +8｜詞條：攻擊力 +25%")
        if profile["collection_reward_claimed"]:
            st.success("三星全裝收藏家已完成：100 EXP＋★★★★ 九星守護項鍊｜菁英BOSS血量降低13%｜HP +25%")
        if profile["elite_reward_claimed"]:
            st.success("菁英征服成就已完成：★★★★ 收藏家王冠｜固定：HP +25｜詞條：防禦力 +25%")
    elif chapter_id == "2":
        if profile["chapter2_reward_claimed"]:
            st.success("第二章滿星成就已完成：★★★★ 乘除勇者手甲｜固定：攻擊力 +6｜詞條：攻擊力 +25%")
        if profile["chapter2_collection_reward_claimed"]:
            st.success("第二章三星全裝收藏已完成：★★★★ 乘除疾風戰靴｜固定：攻擊速度 +0.13/秒｜詞條：攻擊速度 +25%")
        if profile["chapter2_elite_reward_claimed"]:
            st.success("第二章菁英征服已完成：★★★★ 乘除霸主盾｜固定：防禦力 +7｜詞條：HP +25%")
    else:
        pass
    if st.session_state.active_player == "__TEACHER__":
        if st.button("返回老師管理後台"):
            st.session_state.active_player = None
            st.session_state.screen = "admin_panel"
            st.rerun()
    elif st.button("登出學生帳號"):
        st.session_state.active_player = None
        st.session_state.screen = "login"
        st.rerun()

elif st.session_state.screen == "sweep_result":
    profile = get_profile()
    st.subheader("🎫 擊殺券快速通關")
    item = find_item(profile, st.session_state.sweep_result_uid)
    if item:
        st.success("快速通關完成！本次不獲得經驗值，裝備已放入背包。")
        render_item_comparison(profile, item)
        equip_col, keep_col = st.columns(2)
        if equip_col.button("立即裝備", type="primary", use_container_width=True):
            profile["equipment"][item["slot"]] = item["uid"]
            save_profile(profile)
            st.session_state.sweep_result_uid = None
            st.session_state.screen = "menu"
            st.rerun()
        if keep_col.button("放入背包並返回章節", use_container_width=True):
            st.session_state.sweep_result_uid = None
            st.session_state.screen = "menu"
            st.rerun()
    else:
        st.info("此單元目前沒有新的詞條組合，但擊殺券已完成一次快速練習結算。")
        if st.button("返回章節", use_container_width=True):
            st.session_state.sweep_result_uid = None
            st.session_state.screen = "menu"
            st.rerun()

elif st.session_state.screen == "daily_tasks":
    profile = get_profile()
    if sync_daily_tasks(profile):
        save_profile(profile)
    st.subheader("📋 任務列表")
    permanent_tasks = visible_permanent_tasks(profile)
    special_tasks = visible_special_tasks(profile, st.session_state.active_player)
    claimable_permanent = [
        task for task in permanent_tasks
        if task["complete"](profile) and task["id"] not in profile["claimed_permanent_tasks"]
    ]
    claimable_special = [
        task for task in special_tasks
        if task["complete"] and task["id"] not in profile["claimed_special_tasks"]
    ]
    has_any_claimable = (
        not profile.get("daily_login_claimed")
        or (profile.get("daily_practice_count", 0) >= 2 and not profile.get("daily_practice_claimed"))
        or claimable_permanent or claimable_special
    )
    if st.button("🎁 一鍵領取所有已完成任務", type="primary", disabled=not has_any_claimable, use_container_width=True):
        if not profile.get("daily_login_claimed"):
            profile["coins"] += 200
            profile["daily_login_claimed"] = True
        if profile.get("daily_practice_count", 0) >= 2 and not profile.get("daily_practice_claimed"):
            profile["sweep_tickets"] += 3
            profile["daily_practice_claimed"] = True
        for task in claimable_permanent:
            grant_task_reward(profile, task)
            profile["claimed_permanent_tasks"].append(task["id"])
        for task in claimable_special:
            grant_task_reward(profile, task)
            profile["claimed_special_tasks"].append(task["id"])
        save_profile(profile)
        st.rerun()

    daily_tab, permanent_tab, special_tab = st.tabs(
        ["📅 每日任務", "🏆 永久任務", "✨ 特殊任務"],
        key="mission_tabs", default="📅 每日任務",
    )
    with daily_tab:
        st.caption("每日登入於台灣時間上午8:00重置；單元練習任務於每日凌晨0:00重置。")
        task_left, task_right = st.columns([3, 2])
        task_left.write("**每日登入一次**")
        task_left.caption("獎勵：200金幣")
        if profile.get("daily_login_claimed"):
            task_right.success("✅ 已完成並領取")
        elif task_right.button("領取200金幣", type="primary", use_container_width=True):
            profile["coins"] += 200
            profile["daily_login_claimed"] = True
            save_profile(profile)
            st.rerun()

        practice_chapter = highest_unlocked_chapter(profile)
        practice_count = min(2, profile.get("daily_practice_count", 0))
        practice_left, practice_right = st.columns([3, 2])
        practice_left.write(
            f"**完成目前最高進度章節任意單元2次（{CHAPTERS[practice_chapter]['number']}）**"
        )
        practice_left.caption(f"目前進度：{practice_count}/2｜獎勵：3張擊殺券")
        if profile.get("daily_practice_claimed"):
            practice_right.success("✅ 已完成並領取")
        elif practice_count >= 2:
            if practice_right.button("領取3張擊殺券", type="primary", use_container_width=True):
                profile["sweep_tickets"] += 3
                profile["daily_practice_claimed"] = True
                save_profile(profile)
                st.rerun()
        else:
            target_unit = next(
                (uid for uid in chapter_unit_ids(practice_chapter) if unit_unlocked(profile, uid)),
                chapter_unit_ids(practice_chapter)[0],
            )
            if practice_right.button("進行中｜前往挑戰", use_container_width=True):
                start_quiz(target_unit)
                st.rerun()

    with permanent_tab:
        claimed = set(profile["claimed_permanent_tasks"])
        ordered = sorted(
            permanent_tasks,
            key=lambda task: (task["id"] in claimed, int(task["chapter"])),
        )
        for task in ordered:
            completed = task["complete"](profile)
            is_claimed = task["id"] in claimed
            left, right = st.columns([3, 2])
            left.write(f"**{task['name']}**")
            left.caption(f"獎勵：{task['reward_text']}")
            if is_claimed:
                right.success("✅ 已完成並領取")
            elif completed:
                if right.button("領取獎勵", key=f"claim_perm_{task['id']}", type="primary", use_container_width=True):
                    grant_task_reward(profile, task)
                    profile["claimed_permanent_tasks"].append(task["id"])
                    save_profile(profile)
                    st.rerun()
            else:
                if task["task_type"] == "unit":
                    target_unit = task["target_unit"]
                    unlocked = unit_unlocked(profile, target_unit)
                    if right.button(
                        "進行中｜前往挑戰" if unlocked else "🔒 尚未解鎖",
                        key=f"go_perm_{task['id']}", disabled=not unlocked,
                        use_container_width=True,
                    ):
                        start_quiz(target_unit)
                        st.rerun()
                else:
                    unlocked = boss_is_unlocked(profile, task["chapter"], task["boss_type"])
                    if right.button(
                        "進行中｜前往挑戰" if unlocked else "🔒 尚未解鎖",
                        key=f"go_perm_{task['id']}", disabled=not unlocked,
                        use_container_width=True,
                    ):
                        go_to_boss(task["chapter"], task["boss_type"])
                        st.rerun()
        highest_visible = max((int(task["chapter"]) for task in permanent_tasks), default=1)
        if highest_visible < len(CHAPTERS):
            st.caption("完成並領取本章全部永久任務後，才會顯示下一章永久任務。")

    with special_tab:
        claimed = set(profile["claimed_special_tasks"])
        ordered = sorted(special_tasks, key=lambda task: task["id"] in claimed)
        for task in ordered:
            is_claimed = task["id"] in claimed
            left, right = st.columns([3, 2])
            left.write(f"**{task['name']}**")
            left.caption(f"獎勵：{task['reward_text']}")
            if is_claimed:
                right.success("✅ 已完成並領取")
            elif task["complete"]:
                if right.button("領取獎勵", key=f"claim_special_{task['id']}", type="primary", use_container_width=True):
                    grant_task_reward(profile, task)
                    profile["claimed_special_tasks"].append(task["id"])
                    save_profile(profile)
                    st.rerun()
            else:
                unlocked = boss_is_unlocked(profile, task["chapter"], task["boss_type"])
                if right.button(
                    "進行中｜前往挑戰" if unlocked else "🔒 尚未解鎖",
                    key=f"go_special_{task['id']}", disabled=not unlocked,
                    use_container_width=True,
                ):
                    go_to_boss(task["chapter"], task["boss_type"])
                    st.rerun()
        if len(special_tasks) < len(CHAPTERS):
            st.caption("完成並領取目前章節的特殊任務後，才會顯示下一章特殊任務。")

elif st.session_state.screen == "rankings":
    scroll_page_to_top("scroll_ranking_to_top")
    st.subheader("🏆 勇者排行榜")
    boss_tab, level_tab, attack_tab, defense_tab, speed_tab = st.tabs(
        ["🐉 BOSS排行", "⭐ 等級排行", "⚔️ 攻擊排行", "🛡️ 防禦排行", "💨 攻速排行"],
        key="student_ranking_tabs", default="🐉 BOSS排行",
    )
    with boss_tab:
        boss_options = [
            (chapter_id, boss_type) for chapter_id in CHAPTERS
            for boss_type in ("normal", "elite")
        ]
        selected_boss = st.selectbox(
            "選擇章節BOSS", boss_options,
            index=boss_options.index((st.session_state.selected_chapter, "normal")),
            format_func=lambda value: (
                f"{CHAPTERS[value[0]]['number']}｜"
                f"{'一般BOSS' if value[1] == 'normal' else '菁英BOSS'}"
            ),
        )
        boss_rows = ranking_rows(selected_boss[1], selected_boss[0])
        if boss_rows:
            render_ranking(student_ranking_rows(boss_rows))
        else:
            st.info("目前還沒有勇者完成這個BOSS。")
    ranking_specs = [
        (level_tab, "level", "等級相同時，以目前EXP較多者優先。"),
        (attack_tab, "attack", "依目前穿戴裝備計算攻擊力。"),
        (defense_tab, "defense", "依目前穿戴裝備計算防禦力。"),
        (speed_tab, "speed", "依目前穿戴裝備計算每秒攻擊次數。"),
    ]
    for tab, ranking_type, description in ranking_specs:
        with tab:
            st.caption(description)
            render_ranking(student_ranking_rows(character_ranking_rows(ranking_type)))
    st.caption(
        "各榜顯示前10名；若自己不在前10名，會額外顯示自己的實際名次。"
        "排行榜只公開大頭貼、勇者名稱、稱號與遊戲數值，不顯示正式姓名或學生代碼。"
    )

elif st.session_state.screen == "economy":
    scroll_page_to_top("scroll_economy_to_top")
    profile = get_profile()
    changed = ensure_shop(profile)
    if changed:
        save_profile(profile)
    title_col, resource_col = st.columns([3, 2])
    title_col.subheader("🏪 商店與融煉工坊")
    resource_col.markdown(
        f"### 🪙 {profile.get('coins', 0)}　💎 {profile.get('smelting_stones', 0)}"
    )
    mode = st.radio(
        "選擇功能", ["shop", "forge"], horizontal=True,
        format_func=lambda value: "🏪 商店兌換" if value == "shop" else "🔥 裝備融煉",
        label_visibility="collapsed", key="economy_mode",
    )
    st.session_state.economy_tab = mode

    acquired_uid = (
        st.session_state.shop_purchase_uid if mode == "shop"
        else st.session_state.forge_result_uid
    )
    acquired_item = find_item(profile, acquired_uid) if acquired_uid else None
    if acquired_item:
        st.success("裝備已放入物品欄！請比較後選擇是否立即裝備。")
        render_item_comparison(profile, acquired_item)
        equip_col, keep_col = st.columns(2)
        if equip_col.button("立即裝備", type="primary", use_container_width=True, key=f"econ_equip_{acquired_uid}"):
            profile["equipment"][acquired_item["slot"]] = acquired_item["uid"]
            save_profile(profile)
            st.session_state.shop_purchase_uid = None
            st.session_state.forge_result_uid = None
            st.rerun()
        if keep_col.button("保留在物品欄", use_container_width=True, key=f"econ_keep_{acquired_uid}"):
            st.session_state.shop_purchase_uid = None
            st.session_state.forge_result_uid = None
            st.rerun()
        st.divider()

    if mode == "shop":
        generated = datetime.fromisoformat(profile["shop"]["generated_at"].replace("Z", "+00:00"))
        next_refresh = generated + timedelta(hours=24)
        remaining = max(0, int((next_refresh - datetime.now(timezone.utc)).total_seconds()))
        hours, remainder = divmod(remaining, 3600)
        minutes = remainder // 60
        info_col, refresh_col = st.columns([4, 1])
        info_col.info(
            f"目前提供{CHAPTERS[highest_shop_chapter(profile)]['number']}強度的三星裝備；"
            f"每件500金幣。自動刷新剩餘約 {hours}小時{minutes}分。"
        )
        if refresh_col.button("花100金幣強制刷新", disabled=profile["coins"] < 100, use_container_width=True):
            refresh_shop(profile, paid=True)
            save_profile(profile)
            st.session_state.shop_purchase_uid = None
            st.rerun()
        shop_entries = profile["shop"]["items"]
        for row_start in (0, 3):
            columns = st.columns(3)
            for col, entry in zip(columns, shop_entries[row_start:row_start + 3]):
                item = entry["item"]
                with col.container(border=True):
                    st.markdown(f"#### {SLOT_ICONS[item['slot']]} {item['name']}")
                    st.write(f"{'⭐' * item['stars']}｜{fixed_text(item)}")
                    st.write(f"詞條：{AFFIX_NAMES[item['affix_stat']]} +{item['affix_value']:.0%}")
                    current = find_item(profile, profile["equipment"].get(item["slot"]))
                    st.caption(f"目前穿戴：{item_text(current) if current else '此部位尚未裝備'}")
                    if entry.get("sold"):
                        st.button("已售完", disabled=True, key=f"sold_{entry['shop_id']}", use_container_width=True)
                    elif st.button(
                        "🪙 500｜購買", disabled=profile["coins"] < 500,
                        key=f"buy_{entry['shop_id']}", use_container_width=True,
                    ):
                        profile["coins"] -= 500
                        entry["sold"] = True
                        profile["inventory"].append(item)
                        save_profile(profile)
                        st.session_state.shop_purchase_uid = item["uid"]
                        st.rerun()
    else:
        st.info(
            "選擇三件同章節、同星級裝備：3件一星→同章節1件二星；"
            "3件二星＋1顆融煉石→同章節1件三星。產出裝備沿用材料章節的基礎值；"
            "未放入特殊融煉石時，部位與詞條維持隨機。四星裝備不能分解或投入融煉。"
        )
        st.write("### 特殊融煉石合成")
        stone_cols = st.columns(3)
        special_stones = [
            ("slot_smelting_stones", "🧭 部位融煉石", "融煉時指定九個部位之一"),
            ("basic_affix_smelting_stones", "🔷 基礎詞條融煉石", "指定HP、攻擊、防禦或攻速"),
            ("advanced_affix_smelting_stones", "🔶 進階詞條融煉石", "指定其餘戰鬥詞條"),
        ]
        for col, (key, label, description) in zip(stone_cols, special_stones):
            with col.container(border=True):
                st.markdown(f"#### {label} × {profile.get(key, 0)}")
                st.caption(description)
                if st.button(
                    "用5顆融煉石合成", key=f"craft_{key}",
                    disabled=profile["smelting_stones"] < 5, use_container_width=True,
                ):
                    profile["smelting_stones"] -= 5
                    profile[key] += 1
                    save_profile(profile)
                    st.rerun()
        st.caption(
            f"目前普通融煉石：💎 {profile['smelting_stones']}｜"
            f"部位石 {profile['slot_smelting_stones']}｜"
            f"基礎詞條石 {profile['basic_affix_smelting_stones']}｜"
            f"進階詞條石 {profile['advanced_affix_smelting_stones']}"
        )
        st.divider()
        st.write("### 裝備融煉")
        eligible = [
            item for item in profile["inventory"]
            if item["stars"] in (1, 2)
            and profile["equipment"].get(item["slot"]) != item["uid"]
            and not item.get("achievement")
        ]
        item_by_uid = {item["uid"]: item for item in eligible}
        selected = st.multiselect(
            "選擇要投入的三件裝備（已穿戴裝備不會出現在清單）",
            options=list(item_by_uid), max_selections=3,
            format_func=lambda uid: item_text(item_by_uid[uid]),
        )
        selected_items = [item_by_uid[uid] for uid in selected]
        same_star = len(selected_items) == 3 and len({item["stars"] for item in selected_items}) == 1
        selected_chapters = {item_chapter_id(item) for item in selected_items}
        same_chapter = len(selected_items) == 3 and len(selected_chapters) == 1 and None not in selected_chapters
        valid_materials = same_star and same_chapter
        source_stars = selected_items[0]["stars"] if valid_materials else None
        source_chapter = item_chapter_id(selected_items[0]) if valid_materials else None
        enough_stone = source_stars != 2 or profile["smelting_stones"] >= 1

        use_slot_stone = st.checkbox(
            "放入1顆部位融煉石", disabled=profile["slot_smelting_stones"] <= 0,
            help="放入後可指定融煉結果的裝備部位。",
        ) and profile["slot_smelting_stones"] > 0
        selected_slot = st.selectbox(
            "指定部位", list(SLOT_NAMES), format_func=lambda slot: f"{SLOT_ICONS[slot]} {SLOT_NAMES[slot]}",
            disabled=not use_slot_stone,
        ) if use_slot_stone else None

        available_affix_stones = ["不使用"]
        if profile["basic_affix_smelting_stones"] > 0:
            available_affix_stones.append("基礎詞條融煉石")
        if profile["advanced_affix_smelting_stones"] > 0:
            available_affix_stones.append("進階詞條融煉石")
        affix_stone_type = st.radio("詞條融煉石", available_affix_stones, horizontal=True)
        basic_affixes = ["hp_pct", "attack_pct", "defense_pct", "speed_pct"]
        advanced_affixes = [key for key in AFFIX_NAMES if key not in basic_affixes]
        selected_affix = None
        if affix_stone_type == "基礎詞條融煉石":
            selected_affix = st.selectbox(
                "指定基礎詞條", basic_affixes, format_func=lambda key: AFFIX_NAMES[key]
            )
        elif affix_stone_type == "進階詞條融煉石":
            selected_affix = st.selectbox(
                "指定進階詞條", advanced_affixes, format_func=lambda key: AFFIX_NAMES[key]
            )
        if len(selected_items) == 3 and not same_star:
            st.warning("三件裝備必須是相同星級。")
        elif len(selected_items) == 3 and not same_chapter:
            st.warning("三件裝備必須來自同一章節；不同章節的基礎值不同，不能混合融煉。")
        elif valid_materials:
            st.success(
                f"材料確認：{CHAPTERS[source_chapter]['number']}・{'⭐' * source_stars}，"
                f"產出使用{CHAPTERS[source_chapter]['number']}裝備基礎值。"
            )
        if source_stars == 2 and not enough_stone:
            st.warning("二星升三星需要1顆融煉石，目前數量不足。")
        if st.button(
            "開始融煉", type="primary", use_container_width=True,
            disabled=not valid_materials or not enough_stone,
        ):
            result_item = make_forged_item(
                profile, source_stars, source_chapter, selected_slot=selected_slot,
                selected_affix=selected_affix,
            )
            remove_inventory_items(profile, selected)
            if source_stars == 2:
                profile["smelting_stones"] -= 1
            if use_slot_stone:
                profile["slot_smelting_stones"] -= 1
            if affix_stone_type == "基礎詞條融煉石":
                profile["basic_affix_smelting_stones"] -= 1
            elif affix_stone_type == "進階詞條融煉石":
                profile["advanced_affix_smelting_stones"] -= 1
            profile["inventory"].append(result_item)
            save_profile(profile)
            st.session_state.forge_result_uid = result_item["uid"]
            st.rerun()

elif st.session_state.screen == "inventory":
    scroll_page_to_top("scroll_inventory_to_top")
    profile = get_profile()
    inventory_view = st.session_state.get("inventory_view", "backpack")
    st.subheader("🎒 背包" if inventory_view == "backpack" else "📖 圖鑑收集")
    if inventory_view == "equipment":
        for slot, label in SLOT_NAMES.items():
            uid = profile["equipment"].get(slot)
            item = find_item(profile, uid) if uid else None
            cols = st.columns([2, 6, 1])
            cols[0].write(f"**{label}**")
            cols[1].write(item_text(item) if item else "— 尚未裝備 —")
            if item and cols[2].button("卸下", key=f"off_{slot}"):
                profile["equipment"][slot] = None
                save_profile(profile)
                st.rerun()
    if inventory_view == "backpack":
        gear_tab, consumable_tab, title_tab, future_tab = st.tabs(
            ["⚔️ 裝備", "🧪 消耗道具", "🏅 成就稱號", "🔒 待開放"],
            key="backpack_tabs", default="⚔️ 裝備",
        )
        with gear_tab:
            equipped_uids = {uid for uid in profile["equipment"].values() if uid}
            backpack_items = [
                item for item in profile["inventory"] if item["uid"] not in equipped_uids
            ]
            st.write(f"### 未裝備物品（{len(backpack_items)}件）")
            st.caption("背包只顯示未穿戴裝備；點擊格子可查看、裝備或分解。每列5格，超過25件可繼續往下瀏覽。")
            sorted_items = sorted(backpack_items, key=lambda x: (-x["stars"], list(SLOT_NAMES).index(x["slot"])))
            if not sorted_items:
                st.info("完成單元後可以取得裝備。")
            for start in range(0, len(sorted_items), 5):
                grid_cols = st.columns(5)
                for col, item in zip(grid_cols, sorted_items[start:start + 5]):
                    equipped = profile["equipment"].get(item["slot"]) == item["uid"]
                    label = f"{SLOT_ICONS[item['slot']]} {item['name']}\n{'⭐' * item['stars']}　×1"
                    with col.popover(label, use_container_width=True):
                        render_item_comparison(profile, item)
                        if equipped:
                            st.success("目前使用中")
                            if st.button("卸下", key=f"grid_off_{item['uid']}", use_container_width=True):
                                profile["equipment"][item["slot"]] = None
                                save_profile(profile)
                                st.session_state.inventory_default_tab = "背包"
                                st.session_state.inventory_tab_version += 1
                                st.rerun()
                        else:
                            if st.button("裝備", key=f"grid_equip_{item['uid']}", use_container_width=True):
                                profile["equipment"][item["slot"]] = item["uid"]
                                save_profile(profile)
                                st.session_state.inventory_default_tab = "背包"
                                st.session_state.inventory_tab_version += 1
                                st.rerun()
                        if item["stars"] in (1, 2, 3) and not equipped:
                            coin_gain = item["stars"] * 100
                            stone_text = "＋1顆融煉石" if item["stars"] == 3 else ""
                            st.warning(f"分解不可復原：{coin_gain}金幣{stone_text}")
                            if st.button("確認分解", key=f"grid_break_{item['uid']}", use_container_width=True):
                                profile["coins"] += coin_gain
                                profile["smelting_stones"] += 1 if item["stars"] == 3 else 0
                                remove_inventory_items(profile, [item["uid"]])
                                save_profile(profile)
                                st.session_state.inventory_default_tab = "背包"
                                st.session_state.inventory_tab_version += 1
                                st.rerun()
                        elif item["stars"] >= 4:
                            st.caption("四星以上裝備目前不能分解。")
        with consumable_tab:
            consumables = [
                ("🎫", "擊殺券", profile["sweep_tickets"]),
                ("💎", "融煉石", profile["smelting_stones"]),
                ("🧭", "部位融煉石", profile["slot_smelting_stones"]),
                ("🔷", "基礎詞條融煉石", profile["basic_affix_smelting_stones"]),
                ("🔶", "進階詞條融煉石", profile["advanced_affix_smelting_stones"]),
            ]
            cols = st.columns(5)
            for col, (icon, name, count) in zip(cols, consumables):
                col.metric(f"{icon} {name}", count)
            st.caption("擊殺券請在章節單元旁使用；融煉石請前往裝備融煉工坊使用。")
        with title_tab:
            if not profile["titles"]:
                st.info("擊敗各章菁英BOSS可以解鎖成就稱號。")
            for title in profile["titles"]:
                cols = st.columns([4, 1])
                cols[0].write(f"🏅 **「{title}」**")
                if profile.get("equipped_title") == title:
                    if cols[1].button("卸下稱號", key=f"title_off_{title}", use_container_width=True):
                        profile["equipped_title"] = None
                        save_profile(profile)
                        st.rerun()
                elif cols[1].button("佩戴", key=f"title_on_{title}", use_container_width=True):
                    profile["equipped_title"] = title
                    save_profile(profile)
                    st.rerun()
            st.caption("佩戴後會顯示在角色名稱前方，其他學生也能在排行榜看到。")
        with future_tab:
            st.info("此分類保留給後續開放的道具與功能。")
    if inventory_view == "gallery":
        gallery_chapter = st.selectbox(
            "選擇圖鑑章節", list(CHAPTERS),
            format_func=lambda cid: f"{CHAPTERS[cid]['number']}：{CHAPTERS[cid]['name']}",
            key="gallery_chapter",
        )
        star_filter = st.selectbox("星級篩選", ["全部", "三星", "四星"], key="gallery_star_filter")
        chapter = CHAPTERS[gallery_chapter]
        collected_slots = collected_three_star_slots(profile, gallery_chapter)
        st.write(f"### {chapter['number']}：{chapter['name']}")

        if star_filter in ("全部", "三星"):
            st.write(f"#### 三星部位 {len(collected_slots)}/9")
            st.progress(len(collected_slots) / len(SLOT_NAMES))
            for unit_id in chapter_unit_ids(gallery_chapter):
                unit = UNITS[unit_id]
                st.write(f"**單元{unit_id}：{unit['name']}**")
                cols = st.columns(len(unit["slots"]))
                for col, slot in zip(cols, unit["slots"]):
                    if slot in collected_slots:
                        col.success(f"✅ {SLOT_ICONS[slot]} {SLOT_NAMES[slot]}｜三星已收藏")
                    elif col.button(
                        f"⬜ {SLOT_ICONS[slot]} {SLOT_NAMES[slot]}｜尚未收藏・前往挑戰",
                        key=f"gallery_go_{unit_id}_{slot}", disabled=not unit_unlocked(profile, unit_id),
                        use_container_width=True,
                    ):
                        start_quiz(unit_id)
                        st.rerun()
            st.caption("任何章節的單元最高只掉落三星；後續章節只提高一至三星裝備的固定數值。")

        if star_filter in ("全部", "四星"):
            four_star_specs = {
                "1": [
                    ("chapter-1", "整數勇者之劍", "weapon", "完成第一章所有三星單元", "unit"),
                    ("chapter-1-collection", "九星守護項鍊", "necklace", "收集第一章九部位三星", "collection"),
                    ("chapter-1-elite", "收藏家王冠", "helmet", "首次擊敗第一章菁英BOSS", "elite"),
                ],
                "2": [
                    ("chapter-2", "乘除勇者手甲", "gloves", "完成第二章所有三星單元", "unit"),
                    ("chapter-2-collection", "乘除疾風戰靴", "boots", "收集第二章九部位三星", "collection"),
                    ("chapter-2-elite", "乘除霸主盾", "shield", "首次擊敗第二章菁英BOSS", "elite"),
                ],
                "3": [],
            }
            owned_four_slots = collected_achievement_slots(profile, 4)
            st.write(f"#### 全系列四星部位 {len(owned_four_slots)}/9")
            st.progress(len(owned_four_slots) / len(SLOT_NAMES))
            missing = [SLOT_NAMES[slot] for slot in SLOT_NAMES if slot not in owned_four_slots]
            if missing:
                st.caption(f"尚缺部位：{'、'.join(missing)}。四星九部位集滿前，成就裝備不會重複部位。")
            else:
                st.success("四星九部位已全部收藏！下一件成就裝備開始進入五星輪替。")
            if not four_star_specs[gallery_chapter]:
                st.info("第三章四星成就裝備尚未開放；目前可先收集九部位三星裝備並測試BOSS難度。")
            reward_cols = st.columns(3)
            for col, (unit_key, name, slot, requirement, action) in zip(reward_cols, four_star_specs[gallery_chapter]):
                owned_item = achievement_item(profile, unit_key)
                if owned_item:
                    col.success(f"✅ ★★★★ {SLOT_ICONS[slot]} {name}｜已收藏\n\n{fixed_text(owned_item)}")
                    continue
                col.info(f"⬜ ★★★★ {SLOT_ICONS[slot]} {name}\n\n取得方式：{requirement}")
                if action in ("unit", "collection"):
                    target = next(
                        (uid for uid in chapter_unit_ids(gallery_chapter) if profile["unit_best_stars"][uid] < 3),
                        chapter_unit_ids(gallery_chapter)[0],
                    )
                    if col.button("前往單元", key=f"four_go_{unit_key}", disabled=not unit_unlocked(profile, target), use_container_width=True):
                        start_quiz(target)
                        st.rerun()
                else:
                    elite_ready = (
                        profile.get("boss_wins", 0) > 0
                        if gallery_chapter == "1"
                        else profile.get("chapter2_boss_wins", 0) > 0
                    )
                    if col.button("前往菁英BOSS", key=f"elite_go_{unit_key}", disabled=not elite_ready, use_container_width=True):
                        st.session_state.selected_chapter = gallery_chapter
                        st.session_state.selected_boss_type = "elite"
                        st.session_state.scroll_boss_to_top = True
                        st.session_state.screen = "boss_ready"
                        st.rerun()
            st.caption("四星固定值不隨章節倍率變動，但都高於首次登場章節可掉落的同部位三星固定值。")

elif st.session_state.screen == "quiz":
    unit = UNITS[st.session_state.selected_unit]
    st.subheader(f"單元{st.session_state.selected_unit}：{unit['name']}")
    st.caption("星級規則：最高連擊1～4為一星、5～9為二星；達成10連擊立即三星通關。最多作答20題。")
    @st.fragment
    def quiz_panel():
        if st.session_state.screen != "quiz":
            st.rerun(scope="app")
        cols = st.columns(4)
        cols[0].metric("作答進度", f"{st.session_state.attempts}/{MAX_QUESTIONS}題")
        cols[1].metric("目前連擊", st.session_state.combo)
        cols[2].metric("最高連擊", st.session_state.max_combo)
        cols[3].metric("答對", st.session_state.correct)
        st.progress(min(1.0, st.session_state.attempts / MAX_QUESTIONS))
        st.markdown(f"## {st.session_state.question['text']}")
        with st.form("answer_form"):
            st.number_input(
                "你的答案", value=None,
                step=0.01 if st.session_state.selected_unit.startswith("3-") else 1.0,
                format="%.2f" if st.session_state.selected_unit.startswith("3-") else "%.0f",
                key="answer_input",
                placeholder="輸入後按 Enter",
            )
            st.form_submit_button(
                "送出", type="primary", on_click=submit_quiz_answer
            )
        focus_answer_input()
        if st.session_state.screen != "quiz":
            st.rerun(scope="app")
        if st.session_state.message:
            st.write(st.session_state.message)
    quiz_panel()

elif st.session_state.screen == "quiz_result":
    process_rewards()
    profile = get_profile()
    st.subheader(f"單元{st.session_state.selected_unit}完成")
    st.markdown(f"## {'⭐' * st.session_state.stars or '未取得星星'}")
    st.write(f"最高連擊 **{st.session_state.max_combo}**，共答對 **{st.session_state.correct}題**。")
    average_seconds = (
        st.session_state.quiz_elapsed / st.session_state.attempts
        if st.session_state.attempts else 0
    )
    st.caption(
        f"共作答 {st.session_state.attempts}題｜總時間 {st.session_state.quiz_elapsed:.1f}秒｜"
        f"平均每題 {average_seconds:.1f}秒"
    )
    if st.session_state.stars == 0:
        st.warning("本回合尚未答對任何題目，因此不獲得星星、經驗值或裝備。")
    elif st.session_state.earned_exp:
        level_message = (
            f" 已升級到 Lv{st.session_state.level_up_to}！"
            if st.session_state.level_up_to else ""
        )
        st.success(f"刷新單元成績，獲得 {st.session_state.earned_exp} EXP！{level_message}")
    else:
        st.info("經驗值不重複領取；重刷仍可取得新詞條裝備。")
    item = find_item(profile, st.session_state.pending_item_uid) if st.session_state.pending_item_uid else None
    if item:
        st.write("### 本次掉落")
        render_item_comparison(profile, item)
        x, y = st.columns(2)
        if x.button("立即裝備", type="primary", use_container_width=True):
            profile["equipment"][item["slot"]] = item["uid"]
            save_profile(profile)
            st.session_state.pending_item_uid = None
            st.rerun()
        if y.button("放入物品欄", use_container_width=True):
            st.session_state.pending_item_uid = None
            st.rerun()
    elif st.session_state.drop_exhausted:
        st.info("本次沒有出現新的詞條組合；你仍可重複挑戰，練習並刷新關卡成績。")
    if st.session_state.chapter_reward_new:
        reward = next((i for i in profile["inventory"] if i.get("achievement")), None)
        st.success(f"🏆 第一章9星達成！免費獲得：{item_text(reward)}")
    if st.session_state.collection_reward_new:
        level_message = (
            f" 已升級到 Lv{st.session_state.collection_level_up_to}！"
            if st.session_state.collection_level_up_to else ""
        )
        st.success(f"🏆 九部位三星收集完成！獲得「三星全裝收藏家」成就與100 EXP！{level_message}")
        st.success("九部位收藏獎勵已完成；菁英BOSS則在擊敗一般BOSS後解鎖。")
    for reward_message in st.session_state.extra_reward_messages:
        st.success(f"🏆 {reward_message}")
    if st.session_state.pending_item_uid is None:
        st.info("若要重複刷取不同部位或附加能力，請點選下方「重複刷取」。")
        back_col, repeat_col = st.columns(2)
        if back_col.button("返回章節", use_container_width=True):
            st.session_state.screen = "menu"
            st.rerun()
        if repeat_col.button("重複刷取", type="primary", use_container_width=True):
            start_quiz(st.session_state.selected_unit)
            st.rerun()

elif st.session_state.screen == "boss_ready":
    scroll_page_to_top("scroll_boss_to_top")
    profile = get_profile()
    stats = player_stats(profile)
    boss_type = st.session_state.selected_boss_type
    chapter_id = st.session_state.selected_chapter
    config = BOSS_CONFIGS[f"{chapter_id}_{boss_type}"]
    result = simulate_battle(stats, boss_type)
    has_cleared = boss_has_been_cleared(profile, chapter_id, boss_type)
    boss_label = "菁英BOSS" if boss_type == "elite" else "一般BOSS"
    st.subheader(f"🐉 {CHAPTERS[chapter_id]['number']}{boss_label}：{config['name']}")
    render_stats(profile)
    st.write(f"BOSS HP：{config['hp']}｜每{config['interval']:g}秒攻擊{config['damage']}")
    if config.get("critical_rate"):
        st.warning(f"⚠️ BOSS特殊能力：暴擊率 {config['critical_rate']:.0%}；每第5次攻擊必定暴擊，造成1.5倍傷害。")
    if config.get("skill"):
        st.error(
            f"🔥 BOSS技能「{config['skill']}」：每{config['skill_interval']:g}秒造成"
            f"{config['true_damage']:g}真實傷害，無法被防禦或減傷詞條抵消。"
        )
    if has_cleared:
        st.info(f"預估{'獲勝' if result['victory'] else '失敗'}，約 {result['duration']:.2f} 秒結束。")
    else:
        st.info("🔒 首次通關前不顯示勝負與通關時間。請根據雙方能力自行估算；本次必須完整觀看戰鬥。")
    if has_cleared and boss_type == "elite" and not result["victory"]:
        collected_count = len(collected_three_star_slots(profile, chapter_id))
        st.warning(f"目前本章三星部位 {collected_count}/9。建議回單元補齊缺少部位、改善詞條或提升等級後再挑戰。")
    x, y = st.columns(2)
    if x.button("觀看戰鬥", type="primary", use_container_width=True):
        st.session_state.battle_events = result
        st.session_state.battle_started_at = time.time()
        st.session_state.battle_recorded = False
        st.session_state.screen = "boss_watch"
        st.rerun()
    if has_cleared:
        if y.button("略過並立即結算", use_container_width=True):
            st.session_state.battle_recorded = False
            finish_battle(result)
            st.rerun()
    else:
        y.button("首次通關前不可略過", disabled=True, use_container_width=True)
    if st.button("返回章節"):
        st.session_state.screen = "menu"
        st.rerun()

elif st.session_state.screen == "boss_watch":
    @st.fragment(run_every=0.25)
    def battle_panel():
        result = st.session_state.battle_events
        elapsed = time.time() - st.session_state.battle_started_at
        simulated_elapsed, active_skill, presentation_duration = battle_presentation_state(result, elapsed)
        visible = [e for e in result["events"] if e["time"] <= simulated_elapsed]
        event = visible[-1]
        st.subheader("⚔️ 戰鬥進行中")
        a, b = st.columns(2)
        a.metric("勇者HP", f"{event['player_hp']:.1f}")
        b.metric("BOSS HP", f"{event['boss_hp']:.1f}")
        render_health_bar(
            "勇者 HP", event["player_hp"], result["events"][0]["player_hp"], "#2185d0"
        )
        render_health_bar(
            "BOSS HP", event["boss_hp"], result["events"][0]["boss_hp"], "#e53935"
        )
        render_battle_scene(event, st.session_state.selected_boss_type, active_skill)
        if active_skill:
            st.error(f"🔥 {active_skill['text']}（技能演出期間計時暫停）")
        else:
            st.write(event["text"])
        st.caption(f"戰鬥時間：{min(simulated_elapsed, result['duration']):.2f} 秒")
        if elapsed >= presentation_duration:
            finish_battle(result)
            st.rerun()
    battle_panel()

elif st.session_state.screen == "boss_result":
    result = st.session_state.battle_result
    boss_type = result.get("boss_type", "normal")
    boss_label = "菁英BOSS" if boss_type == "elite" else "一般BOSS"
    if result["victory"]:
        st.success(f"🎉 擊敗{boss_label}！通關時間 {result['duration']:.2f}秒")
        if result.get("exp_gain"):
            level_message = (
                f" 已升級到 Lv{result['level_up_to']}！"
                if result.get("level_up_to") else ""
            )
            st.success(f"首次通關獲得 {result['exp_gain']} EXP！{level_message}")
        else:
            st.info("本關BOSS經驗值已領取，這次只更新排名。")
        if result.get("reward_item_uid"):
            profile = get_profile()
            reward = find_item(profile, result["reward_item_uid"])
            st.success(f"🏆 首次擊敗菁英BOSS，獲得：{item_text(reward)}")
        if result.get("earned_title"):
            st.success(f"🏅 解鎖成就稱號「{result['earned_title']}」！可到背包的成就稱號欄佩戴。")
    else:
        st.error(f"勇者在 {result['duration']:.2f}秒後被擊敗，請調整裝備再挑戰。")
    ranking = ranking_rows(boss_type, result.get("chapter_id", "1"))
    if ranking:
        st.write(f"### {boss_label}最佳排名")
        render_ranking(student_ranking_rows(ranking))
    if st.button("返回章節", type="primary"):
        st.session_state.screen = "menu"
        st.rerun()
