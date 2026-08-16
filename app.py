import base64
import html
import io
import json
import hashlib
import hmac
import math
import os
import random
import re
import secrets
import time
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import streamlit as st
import streamlit.components.v1 as components
from PIL import Image

from data_access.database import DatabaseConnection

from game_data.config import (
    AFFIX_NAMES,
    AFFIX_VALUES,
    BLOCKED_NAME_WORDS,
    BOSS_ATTACK_INTERVAL,
    BOSS_CONFIGS,
    BOSS_DAMAGE,
    BOSS_EXP,
    BOSS_MAX_HP,
    CHAPTERS,
    EXP_BY_STARS,
    FIXED_STATS,
    GEAR_NAMES,
    MAX_QUESTIONS,
    PROFILE_CACHE_SECONDS,
    SHORT_LOGIN_SECONDS,
    SLOT_ICONS,
    SLOT_NAMES,
    UNITS,
)
from game_logic.questions import make_question
from game_logic.combat import simulate_battle
from game_logic.equipment import (
    fixed_text,
    fixed_value_for,
    four_star_item_name,
    item_chapter_id,
    item_text,
    player_stats,
)

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
    /* 手機直立時，所有一般功能頁緊接在 Streamlit 工具列下方。 */
    @media (max-width: 900px) and (orientation: portrait) {
        [data-testid="stMainBlockContainer"],
        .stMainBlockContainer,
        .block-container {
            padding-top: 0.25rem !important;
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

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

def chapter_unit_ids(chapter_id):
    return [unit_id for unit_id in UNITS if unit_id.startswith(f"{chapter_id}-")]

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
    "answer_numerator": None,
    "answer_denominator": None,
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
    "scroll_battle_to_top": False,
    "sweep_result_uid": None,
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
        max_lifetime=900,
        max_idle=300,
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
            CREATE TABLE IF NOT EXISTS chapter4_rankings (
                student_code TEXT PRIMARY KEY, hero_name TEXT NOT NULL, level INTEGER NOT NULL,
                clear_time REAL NOT NULL, achieved_at TEXT NOT NULL,
                FOREIGN KEY(student_code) REFERENCES players(student_code) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS chapter4_elite_rankings (
                student_code TEXT PRIMARY KEY, hero_name TEXT NOT NULL, level INTEGER NOT NULL,
                clear_time REAL NOT NULL, achieved_at TEXT NOT NULL,
                FOREIGN KEY(student_code) REFERENCES players(student_code) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS chapter5_rankings (
                student_code TEXT PRIMARY KEY, hero_name TEXT NOT NULL, level INTEGER NOT NULL,
                clear_time REAL NOT NULL, achieved_at TEXT NOT NULL,
                FOREIGN KEY(student_code) REFERENCES players(student_code) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS chapter5_elite_rankings (
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
            CREATE TABLE IF NOT EXISTS game_feedback (
                id {"BIGSERIAL PRIMARY KEY" if USE_POSTGRES else "INTEGER PRIMARY KEY AUTOINCREMENT"},
                student_code TEXT NOT NULL,
                category TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL,
                replied_at TEXT,
                FOREIGN KEY(student_code) REFERENCES players(student_code) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS mailbox (
                id {"BIGSERIAL PRIMARY KEY" if USE_POSTGRES else "INTEGER PRIMARY KEY AUTOINCREMENT"},
                student_code TEXT NOT NULL,
                subject TEXT NOT NULL,
                message TEXT NOT NULL,
                reward_json TEXT,
                is_read INTEGER NOT NULL DEFAULT 0,
                is_claimed INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY(student_code) REFERENCES players(student_code) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS announcements (
                id {"BIGSERIAL PRIMARY KEY" if USE_POSTGRES else "INTEGER PRIMARY KEY AUTOINCREMENT"},
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );
            """
        )
        db.execute("INSERT OR IGNORE INTO settings(key, value) VALUES('registration_enabled', '1')")
        if USE_POSTGRES:
            db.execute("ALTER TABLE attempts ADD COLUMN IF NOT EXISTS elapsed_seconds REAL NOT NULL DEFAULT 0")
            db.execute("ALTER TABLE attempts ADD COLUMN IF NOT EXISTS average_seconds REAL NOT NULL DEFAULT 0")
            db.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS real_name TEXT NOT NULL DEFAULT ''")
            db.execute("ALTER TABLE game_feedback ADD COLUMN IF NOT EXISTS replied_at TEXT")
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
            feedback_columns = {
                row["name"] for row in db.execute("PRAGMA table_info(game_feedback)").fetchall()
            }
            if "replied_at" not in feedback_columns:
                db.execute("ALTER TABLE game_feedback ADD COLUMN replied_at TEXT")
    return True


@st.cache_data(ttl=10, show_spinner=False)
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
    setting_get.clear()


def short_login_secret():
    """Use an existing server-only secret; never store or expose the student's PIN."""
    return str(ADMIN_PIN_SECRET or DATABASE_URL or setting_get("admin_pin_hash") or "local-math-adventure")


def make_short_login_token(student_code):
    expires_at = int(time.time()) + SHORT_LOGIN_SECONDS
    payload = f"{student_code}.{expires_at}"
    signature = hmac.new(
        short_login_secret().encode("utf-8"), payload.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return f"{payload}.{signature}"


def verify_short_login_token(token):
    try:
        student_code, expires_text, signature = token.rsplit(".", 2)
        payload = f"{student_code}.{expires_text}"
        expected = hmac.new(
            short_login_secret().encode("utf-8"), payload.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(signature, expected) or int(expires_text) < int(time.time()):
            return None
        if student_code == "__TEACHER__":
            return None
        with db_connection() as db:
            exists = db.execute(
                "SELECT 1 FROM players WHERE student_code=?", (student_code,)
            ).fetchone()
        return student_code if exists else None
    except (TypeError, ValueError):
        return None


def student_login_is_open(now=None):
    """學生可於台灣時間08:00（含）至22:00前登入。"""
    current = now or datetime.now(TAIPEI_TZ)
    return 8 <= current.hour < 22


def student_login_closed_message():
    return "🌙 每日晚上10點至隔日上午8點為休息時間，暫停學生登入與建立新勇者。"


def render_student_login_closed_notice():
    st.markdown(
        f"""
        <div style="
            color:#111827;
            background:rgba(255,255,255,.94);
            border:1px solid rgba(17,24,39,.18);
            border-radius:12px;
            padding:.85rem 1rem;
            margin:.5rem 0 1rem;
            font-weight:600;
            line-height:1.6;
            box-shadow:0 3px 12px rgba(0,0,0,.18);
        ">{student_login_closed_message()}</div>
        """,
        unsafe_allow_html=True,
    )


def remember_short_login(student_code):
    st.query_params["resume"] = make_short_login_token(student_code)


def clear_short_login():
    if "resume" in st.query_params:
        del st.query_params["resume"]


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
        "gender": None,
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
        "shop": {"generated_at": None, "items": [], "paid_refresh_count": 0},
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
        "chapter3_reward_claimed": False,
        "chapter3_collection_reward_claimed": False,
        "chapter3_elite_reward_claimed": False,
        "chapter4_boss_exp_claimed": False,
        "chapter4_boss_wins": 0,
        "chapter4_elite_boss_exp_claimed": False,
        "chapter4_elite_boss_wins": 0,
        "chapter4_reward_claimed": False,
        "chapter4_collection_reward_claimed": False,
        "chapter4_elite_reward_claimed": False,
        "chapter5_boss_exp_claimed": False,
        "chapter5_boss_wins": 0,
        "chapter5_elite_boss_exp_claimed": False,
        "chapter5_elite_boss_wins": 0,
        "chapter5_reward_claimed": False,
        "chapter5_collection_reward_claimed": False,
        "chapter5_elite_reward_claimed": False,
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
    sync_collection_catalog(profile)
    # 已取得九部位收藏獎勵者，代表當時確實集滿該章三星，補齊舊存檔紀錄。
    catalog = set(profile.get("collection_catalog", []))
    if profile.get("collection_reward_claimed"):
        catalog.update(f"1:3:{slot}" for slot in SLOT_NAMES)
    if profile.get("chapter2_collection_reward_claimed"):
        catalog.update(f"2:3:{slot}" for slot in SLOT_NAMES)
    if profile.get("chapter3_collection_reward_claimed"):
        catalog.update(f"3:3:{slot}" for slot in SLOT_NAMES)
    if profile.get("chapter4_collection_reward_claimed"):
        catalog.update(f"4:3:{slot}" for slot in SLOT_NAMES)
    if profile.get("chapter5_collection_reward_claimed"):
        catalog.update(f"5:3:{slot}" for slot in SLOT_NAMES)
    achievement_history = (
        ("chapter_reward_claimed", "chapter-1", "weapon"),
        ("collection_item_claimed", "chapter-1-collection", "necklace"),
        ("elite_reward_claimed", "chapter-1-elite", "helmet"),
        ("chapter2_reward_claimed", "chapter-2", "gloves"),
        ("chapter2_collection_reward_claimed", "chapter-2-collection", "boots"),
        ("chapter2_elite_reward_claimed", "chapter-2-elite", "shield"),
        ("chapter3_reward_claimed", "chapter-3", "armor"),
        ("chapter3_collection_reward_claimed", "chapter-3-collection", "belt"),
        ("chapter3_elite_reward_claimed", "chapter-3-elite", "ring"),
        ("chapter4_reward_claimed", "chapter-4", "helmet"),
        ("chapter4_collection_reward_claimed", "chapter-4-collection", "boots"),
        ("chapter4_elite_reward_claimed", "chapter-4-elite", "weapon"),
        ("chapter5_reward_claimed", "chapter-5", "armor"),
        ("chapter5_collection_reward_claimed", "chapter-5-collection", "necklace"),
        ("chapter5_elite_reward_claimed", "chapter-5-elite", "shield"),
    )
    for claimed_key, unit_key, slot in achievement_history:
        if profile.get(claimed_key):
            catalog.add(f"achievement:4:{unit_key}:{slot}")
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
        ("chapter3_elite_boss_wins", "一刀斬龍"),
        ("chapter4_elite_boss_wins", "渡雷劫方可成仙"),
        ("chapter5_elite_boss_wins", "魚與熊掌我都要"),
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


def teacher_four_star_reward_makers():
    """Return every currently implemented four-star chapter reward maker.

    The naming convention also lets future chapters join the teacher test grant
    automatically as soon as their three reward maker functions are added.
    """
    makers = []
    for chapter_id in CHAPTERS:
        if chapter_id == "1":
            names = ("make_chapter_reward", "make_collection_reward", "make_elite_reward")
        else:
            names = (
                f"make_chapter{chapter_id}_reward",
                f"make_chapter{chapter_id}_collection_reward",
                f"make_chapter{chapter_id}_elite_reward",
            )
        for name in names:
            maker = globals().get(name)
            if callable(maker):
                makers.append(maker)
    return makers


def teacher_maximum_progress_exp():
    unit_exp = len(UNITS) * EXP_BY_STARS[3]
    boss_exp = sum(
        int(config.get("exp", 0))
        for key, config in BOSS_CONFIGS.items()
        if key.split("_", 1)[0] in CHAPTERS
    )
    full_collection_exp = len(CHAPTERS) * 100
    return unit_exp + boss_exp + full_collection_exp


def level_and_exp_from_total(total_exp):
    level = 1
    remaining = max(0, int(total_exp))
    while level < 20 and remaining >= level * 100:
        remaining -= level * 100
        level += 1
    return level, remaining


def profile_total_exp(profile):
    level = max(1, int(profile.get("level", 1)))
    return sum(current_level * 100 for current_level in range(1, level)) + int(profile.get("exp", 0))


def sync_teacher_test_profile(profile):
    """Bring the teacher-only character up to the current testing baseline."""
    changed = False
    notices = []

    owned_units = {
        item.get("unit") for item in profile.get("inventory", [])
        if int(item.get("stars", 0) or 0) == 4
    }
    granted_items = []
    for maker in teacher_four_star_reward_makers():
        preview = maker()
        if preview.get("unit") in owned_units:
            continue
        profile["inventory"].append(preview)
        owned_units.add(preview.get("unit"))
        granted_items.append(preview.get("name", preview.get("unit", "四星裝備")))
        changed = True
    if granted_items:
        notices.append(f"老師測試裝備補發：{'、'.join(granted_items)}")

    if not profile.get("teacher_test_resources_granted_v1"):
        profile["coins"] = int(profile.get("coins", 0)) + 10000
        profile["slot_smelting_stones"] = int(profile.get("slot_smelting_stones", 0)) + 100
        profile["basic_affix_smelting_stones"] = int(profile.get("basic_affix_smelting_stones", 0)) + 100
        profile["advanced_affix_smelting_stones"] = int(profile.get("advanced_affix_smelting_stones", 0)) + 100
        profile["teacher_test_resources_granted_v1"] = True
        notices.append("老師測試資源補發：10000 金幣及三種特殊熔煉石各 100 顆")
        changed = True

    # The testing character represents maximum currently obtainable progress.
    for unit_id in UNITS:
        if profile["unit_best_stars"].get(unit_id, 0) < 3:
            profile["unit_best_stars"][unit_id] = 3
            changed = True
    for chapter_id in CHAPTERS:
        prefix = "" if chapter_id == "1" else f"chapter{chapter_id}_"
        for boss_type in ("boss", "elite_boss"):
            wins_key = f"{prefix}{boss_type}_wins"
            exp_key = f"{prefix}{boss_type}_exp_claimed"
            if int(profile.get(wins_key, 0) or 0) < 1:
                profile[wins_key] = 1
                changed = True
            if not profile.get(exp_key):
                profile[exp_key] = True
                changed = True

    claim_keys = {
        "1": ("chapter_reward_claimed", "collection_reward_claimed", "elite_reward_claimed"),
    }
    for chapter_id in CHAPTERS:
        keys = claim_keys.get(
            chapter_id,
            (
                f"chapter{chapter_id}_reward_claimed",
                f"chapter{chapter_id}_collection_reward_claimed",
                f"chapter{chapter_id}_elite_reward_claimed",
            ),
        )
        for key in keys:
            if not profile.get(key):
                profile[key] = True
                changed = True
    if not profile.get("collection_item_claimed"):
        profile["collection_item_claimed"] = True
        changed = True

    target_total = teacher_maximum_progress_exp()
    if profile_total_exp(profile) != target_total:
        profile["level"], profile["exp"] = level_and_exp_from_total(target_total)
        notices.append(f"老師測試等級已同步至 Lv{profile['level']}（EXP {profile['exp']}）")
        changed = True

    if notices:
        profile.setdefault("retro_reward_notice", []).extend(notices)
    sync_collection_catalog(profile)
    return changed


def ensure_teacher_profile(hero_name="老師測試勇者"):
    code = "__TEACHER__"
    with db_connection() as db:
        row = db.execute("SELECT profile_json FROM players WHERE student_code=?", (code,)).fetchone()
        if row:
            profile = normalize_profile(json.loads(row["profile_json"]), hero_name)
            profile["name"] = hero_name
            sync_teacher_test_profile(profile)
            db.execute(
                "UPDATE players SET hero_name=?, profile_json=? WHERE student_code=?",
                (hero_name, json.dumps(profile, ensure_ascii=False), code),
            )
        else:
            salt, digest = make_pin_hash(secrets.token_hex(16))
            profile = new_profile(hero_name)
            profile["task_rewards_initialized"] = True
            profile["elite_special_tasks_migrated"] = True
            sync_teacher_test_profile(profile)
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
    cached = st.session_state.get("_profile_cache")
    if (
        cached and cached.get("code") == code
        and time.time() - cached.get("loaded_at", 0) < PROFILE_CACHE_SECONDS
    ):
        cached_profile = cached["profile"]
        if any(key not in cached_profile for key in new_profile(cached_profile.get("name", "勇者"))):
            cached_profile = normalize_profile(cached_profile, cached_profile.get("name", "勇者"))
            retroactively_grant_chapter3_rewards(cached_profile)
            save_profile(cached_profile)
        if code == "__TEACHER__" and sync_teacher_test_profile(cached_profile):
            save_profile(cached_profile)
        return cached_profile
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
    retroactively_grant_chapter3_rewards(profile)
    teacher_synced = code == "__TEACHER__" and sync_teacher_test_profile(profile)
    normalized_changed = (
        json.dumps(profile, ensure_ascii=False, sort_keys=True) != original_profile_json
    ) or teacher_synced
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
        ("chapter-3", make_chapter3_reward),
        ("chapter-3-collection", make_chapter3_collection_reward),
        ("chapter-3-elite", make_chapter3_elite_reward),
        ("chapter-4", make_chapter4_reward),
        ("chapter-4-collection", make_chapter4_collection_reward),
        ("chapter-4-elite", make_chapter4_elite_reward),
        ("chapter-5", make_chapter5_reward),
        ("chapter-5-collection", make_chapter5_collection_reward),
        ("chapter-5-elite", make_chapter5_elite_reward),
    ):
        migrated = sync_achievement_item(profile, unit_key, maker) or migrated
    if migrated or normalized_changed:
        save_profile(profile)
    st.session_state._profile_cache = {
        "code": code, "profile": profile, "loaded_at": time.time(),
    }
    return profile


def save_profile(profile):
    # 任何來源取得裝備後，在寫入存檔前立即登錄永久圖鑑。
    sync_collection_catalog(profile)
    with db_connection() as db:
        db.execute(
            "UPDATE players SET hero_name=?, profile_json=? WHERE student_code=?",
            (profile["name"], json.dumps(profile, ensure_ascii=False), st.session_state.active_player),
        )
    st.session_state._profile_cache = {
        "code": st.session_state.active_player,
        "profile": profile,
        "loaded_at": time.time(),
    }


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


@st.cache_data(show_spinner=False)
def built_in_avatar_data(index):
    image_path = Path(__file__).parent / "assets" / "avatars" / f"avatar-{index:02d}.webp"
    if not image_path.exists():
        return None
    return "data:image/webp;base64," + base64.b64encode(image_path.read_bytes()).decode("ascii")


@st.cache_data(show_spinner=False)
def _login_background_data_uri(filename, modified_ns):
    """modified_ns is part of the cache key so replaced artwork reloads immediately."""
    image_path = Path(__file__).parent / "assets" / "login" / filename
    if not image_path.exists():
        return ""
    return "data:image/webp;base64," + base64.b64encode(image_path.read_bytes()).decode("ascii")


def login_background_data_uri(animated=True):
    filename = "heroes-vs-demon-animated-v2.webp" if animated else "heroes-vs-demon-v2.webp"
    image_path = Path(__file__).parent / "assets" / "login" / filename
    if not image_path.exists():
        return ""
    return _login_background_data_uri(filename, image_path.stat().st_mtime_ns)


def login_landscape_background_data_uri():
    filename = "heroes-vs-demon-landscape-animated-v4.webp"
    image_path = Path(__file__).parent / "assets" / "login" / filename
    if not image_path.exists():
        return ""
    return _login_background_data_uri(filename, image_path.stat().st_mtime_ns)


def login_landscape_static_background_data_uri():
    filename = "heroes-vs-demon-landscape-v4.webp"
    image_path = Path(__file__).parent / "assets" / "login" / filename
    if not image_path.exists():
        return ""
    return _login_background_data_uri(filename, image_path.stat().st_mtime_ns)


@st.cache_data(show_spinner=False)
def _login_background_video_data_uri(filename, modified_ns):
    """Cache the MP4 data URI; modified_ns refreshes it when the file is replaced."""
    video_path = Path(__file__).parent / "assets" / "login" / filename
    if not video_path.exists():
        return ""
    return "data:video/mp4;base64," + base64.b64encode(video_path.read_bytes()).decode("ascii")


def login_background_video_data_uri():
    filename = "heroes-vs-demon-idle.mp4"
    video_path = Path(__file__).parent / "assets" / "login" / filename
    if not video_path.exists():
        return ""
    return _login_background_video_data_uri(filename, video_path.stat().st_mtime_ns)


def apply_login_background():
    static_background = login_background_data_uri(animated=False)
    landscape_background = login_landscape_background_data_uri()
    landscape_static_background = login_landscape_static_background_data_uri()
    video_background = login_background_video_data_uri()
    background = static_background or login_background_data_uri(animated=True)
    if not background and not video_background:
        return
    video_html = ""
    if video_background:
        video_html = f"""
        <video class="login-video-background" autoplay muted loop playsinline preload="auto"
               poster="{background}" aria-hidden="true">
            <source src="{video_background}" type="video/mp4">
        </video>
        """
    st.markdown(
        f"""
        {video_html}
        <div class="login-landscape-background" aria-hidden="true"></div>
        <style>
        .stApp {{
            background: #090a18;
            isolation: isolate;
        }}
        .login-video-background {{
            position: fixed;
            inset: 0;
            width: 100vw;
            height: 100vh;
            z-index: 0;
            pointer-events: none;
            object-fit: contain;
            object-position: center top;
            background: #090a18;
        }}
        .login-landscape-background {{
            display: none;
            position: fixed;
            inset: 0;
            width: 100vw;
            height: 100vh;
            z-index: 0;
            pointer-events: none;
            background: #090a18 url('{landscape_background or landscape_static_background or static_background or background}') center center / cover no-repeat;
        }}
        .stApp::before {{
            content: "";
            position: fixed;
            inset: 0;
            z-index: 1;
            pointer-events: none;
            background:
                linear-gradient(rgba(7, 10, 25, .10), rgba(7, 10, 25, .24));
        }}
        .stApp > header,
        .stApp [data-testid="stAppViewContainer"],
        .stApp [data-testid="stMain"] {{
            position: relative;
            z-index: 2;
            background: transparent !important;
        }}
        .stMainBlockContainer, [data-testid="stMainBlockContainer"] {{
            width: min(560px, calc(100% - 32px));
            max-width: 560px;
            margin: 92px auto 30px !important;
            padding: 1rem 1.25rem 2rem !important;
            border: 0 !important;
            border-radius: 0 !important;
            background: transparent !important;
            box-shadow: none !important;
        }}
        .stMainBlockContainer h1, [data-testid="stMainBlockContainer"] h1 {{
            position: fixed;
            z-index: 10;
            top: 4.15rem;
            left: .8rem;
            margin: 0 !important;
            padding: .15rem .3rem !important;
            color: white !important;
            text-shadow: 0 3px 12px rgba(0,0,0,.9);
        }}
        [data-testid="stRadio"] > div,
        [data-testid="stCheckbox"],
        [data-testid="stTextInput"] input,
        [data-testid="stButton"] button {{
            border-radius: 14px !important;
        }}
        [data-testid="stRadio"] > div,
        [data-testid="stCheckbox"] {{
            width: fit-content;
            padding: .45rem .8rem;
            background: rgba(255,255,255,.88);
            border: 1px solid rgba(255,255,255,.78);
            box-shadow: 0 5px 18px rgba(0,0,0,.18);
            color: #171717 !important;
        }}
        [data-testid="stRadio"] > div label,
        [data-testid="stRadio"] > div label p,
        [data-testid="stRadio"] > div label span,
        [data-testid="stCheckbox"] label,
        [data-testid="stCheckbox"] label p,
        [data-testid="stCheckbox"] label span,
        [data-testid="stTabs"] [role="tab"] {{
            color: #171717 !important;
        }}
        [data-testid="stRadio"] > div label:has(input:checked),
        [data-testid="stCheckbox"] label:has(input:checked),
        [data-testid="stTabs"] [role="tab"][aria-selected="true"] {{
            color: #ff4b4b !important;
        }}
        [data-testid="stRadio"] {{
            width: fit-content !important;
            margin-left: 0 !important;
            margin-right: auto !important;
        }}
        [data-testid="stCheckbox"] {{
            width: fit-content !important;
            margin-left: auto !important;
            margin-right: auto !important;
        }}
        div[data-testid="stElementContainer"]:has(> [data-testid="stCheckbox"]),
        div[data-testid="stElementContainer"]:has([data-testid="stCheckbox"]) {{
            width: fit-content !important;
            max-width: max-content !important;
            margin-left: auto !important;
            margin-right: auto !important;
        }}
        [data-testid="stRadio"] > label {{
            width: 100%;
            text-align: left;
            justify-content: flex-start;
        }}
        [data-testid="stTextInput"] {{
            width: min(320px, 100%) !important;
            margin-left: auto !important;
            margin-right: auto !important;
        }}
        [data-testid="stTextInput"] input,
        [data-testid="stTextInput"] input::placeholder {{
            color: #171717 !important;
            opacity: 1 !important;
            -webkit-text-fill-color: #171717 !important;
        }}
        [data-testid="stTextInput"] label,
        [data-testid="stRadio"] label,
        [data-testid="stCheckbox"] label,
        [data-testid="stTabs"] button {{
            font-weight: 700 !important;
        }}
        [data-testid="stTextInput"] > label,
        [data-testid="stRadio"] > label {{
            color: white !important;
            text-shadow: 0 2px 7px rgba(0,0,0,.95);
        }}
        [data-testid="stTabs"] [role="tablist"] {{
            width: min(320px, 100%);
            margin-left: auto;
            margin-right: auto;
            padding: .18rem .45rem;
            border-radius: 14px;
            background: rgba(255,255,255,.88);
            box-shadow: 0 5px 18px rgba(0,0,0,.18);
        }}
        [data-testid="stTabs"] [role="tab"] {{
            flex: 1 1 50%;
            justify-content: center;
        }}
        .st-key-login_fields_row [data-testid="stHorizontalBlock"],
        .st-key-login_actions_row [data-testid="stHorizontalBlock"] {{
            display: flex !important;
            flex-direction: row !important;
            flex-wrap: nowrap !important;
            gap: .55rem !important;
            align-items: end !important;
        }}
        .st-key-login_fields_row [data-testid="stColumn"],
        .st-key-login_actions_row [data-testid="stColumn"] {{
            min-width: 0 !important;
            width: 50% !important;
            flex: 1 1 50% !important;
        }}
        .st-key-login_fields_row [data-testid="stTextInput"] {{
            width: 100% !important;
        }}
        .st-key-login_actions_row [data-testid="stCheckbox"],
        .st-key-login_actions_row [data-testid="stButton"] {{
            margin-left: auto !important;
            margin-right: auto !important;
        }}
        [data-testid="stButton"] {{
            width: fit-content !important;
            margin-left: auto !important;
            margin-right: auto !important;
        }}
        [data-testid="stButton"] button {{
            width: auto !important;
            min-width: max-content !important;
            padding-left: 1.2rem !important;
            padding-right: 1.2rem !important;
        }}
        @media (max-width: 600px) {{
            .stApp::before {{
                background: linear-gradient(rgba(7,10,25,.08), rgba(7,10,25,.24));
            }}
            .login-video-background {{
                object-fit: cover;
                object-position: center top;
            }}
            .stMainBlockContainer, [data-testid="stMainBlockContainer"] {{
                width: min(88vw, 430px);
                margin: 58px auto 24px !important;
                padding: .5rem 0 1.25rem !important;
            }}
            .stMainBlockContainer h1, [data-testid="stMainBlockContainer"] h1 {{
                font-size: 2rem !important;
                top: 4.05rem;
                left: .35rem;
            }}
            [data-testid="stRadio"], [data-testid="stTabs"],
            [data-testid="stCheckbox"] {{
                max-width: 390px;
                margin-left: auto;
                margin-right: auto;
            }}
            [data-testid="stCheckbox"] {{
                max-width: max-content;
                padding: .38rem .7rem;
            }}
            [data-testid="stTextInput"] {{
                width: min(125px, 42vw) !important;
            }}
            [data-testid="stTabs"] [role="tablist"] {{
                width: min(250px, 76vw);
            }}
            [data-testid="stTextInput"] input {{
                background: rgba(255,255,255,.90) !important;
                border: 1px solid rgba(255,255,255,.82) !important;
                box-shadow: 0 5px 18px rgba(0,0,0,.20);
            }}
        }}
        @media (orientation: landscape) {{
            .login-video-background {{
                display: none !important;
            }}
            .login-landscape-background {{
                display: block !important;
                inset: 3.6rem 0 0 !important;
                height: calc(100vh - 3.6rem) !important;
                background-position: center top !important;
            }}
            .stMainBlockContainer, [data-testid="stMainBlockContainer"] {{
                width: min(340px, 42vw);
                max-width: 340px;
                margin: 104px auto 24px 4vw !important;
                padding: .75rem 1rem 1.25rem !important;
            }}
            .stMainBlockContainer h1, [data-testid="stMainBlockContainer"] h1 {{
                top: 4.75rem;
                left: 1.1rem;
                font-size: 2.35rem !important;
            }}
            .stApp::before {{
                background: linear-gradient(90deg, rgba(7,10,25,.32) 0%, rgba(7,10,25,.14) 48%, rgba(7,10,25,.04) 100%);
            }}
            [data-testid="stRadio"],
            [data-testid="stTabs"],
            [data-testid="stTextInput"],
            [data-testid="stCheckbox"],
            [data-testid="stButton"] {{
                margin-left: 0 !important;
                margin-right: auto !important;
            }}
            [data-testid="stTabs"] [role="tablist"] {{
                width: 280px !important;
                min-width: 0 !important;
                max-width: 100% !important;
                margin-left: 0 !important;
                margin-right: auto !important;
            }}
            [data-testid="stTabs"] [role="tab"] {{
                flex: 0 0 auto !important;
                padding-left: 1rem !important;
                padding-right: 1rem !important;
            }}
            [data-testid="stTextInput"] {{
                width: min(280px, 100%) !important;
            }}
            .st-key-login_fields_row [data-testid="stTextInput"] {{
                width: min(280px, 100%) !important;
            }}
            .st-key-login_fields_row [data-testid="stHorizontalBlock"],
            .st-key-login_actions_row [data-testid="stHorizontalBlock"] {{
                display: flex !important;
                flex-direction: column !important;
                flex-wrap: nowrap !important;
                gap: .35rem !important;
                align-items: flex-start !important;
            }}
            .st-key-login_fields_row [data-testid="stColumn"],
            .st-key-login_actions_row [data-testid="stColumn"] {{
                min-width: 0 !important;
                width: 100% !important;
                max-width: 100% !important;
                flex: 0 0 auto !important;
            }}
            .st-key-login_actions_row {{
                width: min(280px, 100%) !important;
                max-width: 280px !important;
            }}
            .st-key-login_actions_row [data-testid="stHorizontalBlock"] {{
                flex-direction: row !important;
                align-items: center !important;
                gap: .35rem !important;
            }}
            .st-key-login_actions_row [data-testid="stColumn"]:first-child {{
                width: 58% !important;
                max-width: 58% !important;
                flex: 0 0 58% !important;
            }}
            .st-key-login_actions_row [data-testid="stColumn"]:last-child {{
                width: 42% !important;
                max-width: 42% !important;
                flex: 0 0 42% !important;
            }}
            .st-key-login_actions_row [data-testid="stCheckbox"],
            .st-key-login_actions_row [data-testid="stButton"] {{
                margin-left: 0 !important;
                margin-right: auto !important;
            }}
        }}
        @media (prefers-reduced-motion: reduce) {{
            .login-video-background {{
                display: none;
            }}
            .login-landscape-background {{
                background-image: url('{landscape_static_background or landscape_background}') !important;
            }}
            .stApp::before {{
                background:
                    linear-gradient(rgba(7,10,25,.10), rgba(7,10,25,.26)),
                    url('{static_background or background}') center top / contain no-repeat,
                    #090a18 !important;
            }}
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_avatar_editor(profile):
    avatar_col, gender_col, upload_col = st.columns([1, 2, 4], vertical_alignment="top")
    if profile.get("avatar_data"):
        avatar_col.image(profile["avatar_data"], width=96)
    else:
        avatar_col.markdown("## 🧙")
    if profile.get("gender") in {"male", "female"}:
        gender_col.write(f"**角色性別：{'男性' if profile['gender'] == 'male' else '女性'}**")
    else:
        gender_col.warning("性別只能設定一次，並會決定後續 BOSS 戰鬥中的勇者圖片。")
        selected_gender = gender_col.radio(
            "選擇角色性別", ["male", "female"], horizontal=True,
            format_func=lambda value: "男性" if value == "male" else "女性",
            key="one_time_gender",
        )
        if gender_col.button("確認性別（設定後不能更改）", type="primary", use_container_width=True):
            profile["gender"] = selected_gender
            save_profile(profile)
            st.success("角色性別已設定，後續 BOSS 戰鬥會使用對應的勇者圖片。")
            st.rerun()
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
    if "show_builtin_avatar_picker" not in st.session_state:
        st.session_state.show_builtin_avatar_picker = False
    if not st.session_state.show_builtin_avatar_picker:
        if st.button("選擇內建 Q 版大頭貼（20款）", key="open_builtin_avatar_picker", use_container_width=True):
            st.session_state.show_builtin_avatar_picker = True
            st.rerun()
    else:
        picker_header, picker_close = st.columns([5, 1], vertical_alignment="center")
        picker_header.markdown("#### 選擇內建 Q 版大頭貼（20款）")
        if picker_close.button("關閉", key="close_builtin_avatar_picker", use_container_width=True):
            st.session_state.show_builtin_avatar_picker = False
            st.rerun()
        st.caption("內建大頭貼可以隨時更換，也可以改用自己上傳的圖片。")
        st.markdown(
            """
            <style>
            @media (max-width:768px) and (orientation:portrait) {
              [class*="st-key-avatar_picker_row_"] [data-testid="stHorizontalBlock"] {
                display:flex !important;flex-direction:row !important;flex-wrap:nowrap !important;
                gap:.18rem !important;width:100% !important;
              }
              [class*="st-key-avatar_picker_row_"] [data-testid="stColumn"] {
                min-width:0 !important;width:calc(25% - .14rem) !important;
                max-width:calc(25% - .14rem) !important;flex:0 0 calc(25% - .14rem) !important;
                padding:0 !important;
              }
              [class*="st-key-avatar_picker_row_"] [data-testid="stImage"] img {
                width:100% !important;height:auto !important;border-radius:8px !important;
              }
              [class*="st-key-avatar_picker_row_"] button {
                min-height:1.9rem !important;padding:.15rem .05rem !important;
                font-size:.72rem !important;
              }
            }
            </style>
            """,
            unsafe_allow_html=True,
        )
        for row_number, row_start in enumerate(range(1, 21, 4), 1):
            with st.container(key=f"avatar_picker_row_{row_number}"):
                columns = st.columns(4, gap="small")
                for column, index in zip(columns, range(row_start, row_start + 4)):
                    avatar_data = built_in_avatar_data(index)
                    if avatar_data:
                        column.image(avatar_data, use_container_width=True)
                    if column.button("使用", key=f"use_builtin_avatar_{index}", use_container_width=True):
                        profile["avatar_data"] = avatar_data
                        save_profile(profile)
                        st.session_state.show_builtin_avatar_picker = False
                        st.session_state.scroll_home_after_avatar = True
                        st.rerun()


def render_compact_avatar_editor(profile):
    with st.container(key="home_avatar_summary"):
        avatar_col, gender_col, notice_col = st.columns([1.2, 2.2, 2], vertical_alignment="top")
    if profile.get("avatar_data"):
        avatar_col.image(profile["avatar_data"], width=96)
    else:
        avatar_col.markdown("## 🧙")
    if avatar_col.button("點擊頭像更換", key="toggle_avatar_editor", use_container_width=True):
        st.session_state.show_avatar_editor = not st.session_state.get("show_avatar_editor", False)
        st.rerun()

    if profile.get("gender") in {"male", "female"}:
        gender_col.write(f"**角色性別：{'男性' if profile['gender'] == 'male' else '女性'}**")
    else:
        gender_col.warning("性別只能設定一次，並會影響後續 BOSS 戰鬥中的勇者圖片。")
        selected_gender = gender_col.radio(
            "選擇角色性別", ["male", "female"], horizontal=True,
            format_func=lambda value: "男性" if value == "male" else "女性",
            key="one_time_gender",
        )
        if gender_col.button("確認性別（設定後不能更改）", type="primary", use_container_width=True):
            profile["gender"] = selected_gender
            save_profile(profile)
            st.rerun()

    if notice_col.button("📢 公告事項", key="open_announcements", type="primary", use_container_width=True):
        st.session_state.scroll_announcements_to_top = True
        st.session_state.screen = "announcements"
        st.rerun()

    if not st.session_state.get("show_avatar_editor", False):
        return
    st.divider()
    editor_header, editor_close = st.columns([5, 1], vertical_alignment="center")
    editor_header.markdown("#### 更換大頭貼")
    if editor_close.button("關閉", key="close_avatar_editor", use_container_width=True):
        st.session_state.show_avatar_editor = False
        st.rerun()
    avatar_source = st.radio(
        "選擇更換方式", ["內建Q版大頭貼", "自行上傳大頭貼"],
        horizontal=True, key="avatar_source",
    )
    if avatar_source == "自行上傳大頭貼":
        uploaded = st.file_uploader(
            "選擇圖片", type=["png", "jpg", "jpeg", "webp"], key="compact_avatar_upload",
            help="圖片上限2MB，會自動縮小；只顯示於角色與排行榜。",
        )
        if uploaded and st.button("儲存大頭貼", type="primary", use_container_width=True):
            try:
                profile["avatar_data"] = avatar_from_upload(uploaded)
                save_profile(profile)
                st.session_state.show_avatar_editor = False
                st.session_state.scroll_home_after_avatar = True
                st.rerun()
            except Exception as error:
                st.error(f"無法處理圖片：{error}")
        return

    st.caption("選擇一張內建Q版大頭貼；選定後會自動收起選單並回到人物區。")
    st.markdown(
        """
        <style>
        @media (max-width:768px) and (orientation:portrait) {
          [class*="st-key-compact_avatar_row_"] [data-testid="stHorizontalBlock"] {display:flex !important;flex-direction:row !important;flex-wrap:nowrap !important;gap:.18rem !important;width:100% !important;}
          [class*="st-key-compact_avatar_row_"] [data-testid="stColumn"] {min-width:0 !important;width:calc(25% - .14rem) !important;max-width:calc(25% - .14rem) !important;flex:0 0 calc(25% - .14rem) !important;padding:0 !important;}
          [class*="st-key-compact_avatar_row_"] [data-testid="stImage"] img {width:100% !important;height:auto !important;border-radius:8px !important;}
          [class*="st-key-compact_avatar_row_"] button {min-height:1.9rem !important;padding:.15rem .05rem !important;font-size:.72rem !important;}
        }
        </style>
        """, unsafe_allow_html=True,
    )
    for row_number, row_start in enumerate(range(1, 21, 4), 1):
        with st.container(key=f"compact_avatar_row_{row_number}"):
            columns = st.columns(4, gap="small")
            for column, index in zip(columns, range(row_start, row_start + 4)):
                avatar_data = built_in_avatar_data(index)
                if avatar_data:
                    column.image(avatar_data, use_container_width=True)
                if column.button("使用", key=f"compact_avatar_{index}", use_container_width=True):
                    profile["avatar_data"] = avatar_data
                    save_profile(profile)
                    st.session_state.show_avatar_editor = False
                    st.session_state.scroll_home_after_avatar = True
                    st.rerun()


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


def log_question_answer(unit_id, answer_row):
    """每答完一題立即保存，避免中途離開、斷線或部署更新造成紀錄遺失。"""
    if st.session_state.active_player == "__TEACHER__":
        return
    with db_connection() as db:
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
        ("4", "normal"): "chapter4_rankings", ("4", "elite"): "chapter4_elite_rankings",
        ("5", "normal"): "chapter5_rankings", ("5", "elite"): "chapter5_elite_rankings",
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
        ("4", "normal"): "chapter4_rankings", ("4", "elite"): "chapter4_elite_rankings",
        ("5", "normal"): "chapter5_rankings", ("5", "elite"): "chapter5_elite_rankings",
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


def character_ranking_tables():
    """一次讀取與計算全部學生能力，再建立各項角色能力排序。"""
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
            "HP": round(stats["hp"], 1),
            "攻擊": round(stats["attack"], 1),
            "防禦": round(stats["defense"], 1),
            "攻速／秒": round(stats["attack_speed"], 2),
        }
        prepared.append(base)
    sort_keys = {
        "level": lambda row: (-row["等級"], -row["EXP"], row["玩家"]),
        "hp": lambda row: (-row["HP"], -row["等級"], -row["EXP"], row["玩家"]),
        "attack": lambda row: (-row["攻擊"], -row["等級"], row["玩家"]),
        "defense": lambda row: (-row["防禦"], -row["等級"], row["玩家"]),
        "speed": lambda row: (-row["攻速／秒"], -row["等級"], row["玩家"]),
    }
    visible_columns = {
        "level": ("頭像", "玩家", "等級", "EXP"),
        "hp": ("頭像", "玩家", "等級", "HP"),
        "attack": ("頭像", "玩家", "等級", "攻擊"),
        "defense": ("頭像", "玩家", "等級", "防禦"),
        "speed": ("頭像", "玩家", "等級", "攻速／秒"),
    }
    tables = {}
    for ranking_type, sort_key in sort_keys.items():
        ordered = sorted(prepared, key=sort_key)
        columns = visible_columns[ranking_type]
        tables[ranking_type] = [
            {
                "名次": rank, "自己": row["自己"],
                **{column: row[column] for column in columns},
            }
            for rank, row in enumerate(ordered, 1)
        ]
    return tables


def student_rows():
    with db_connection() as db:
        rows = [dict(row) for row in db.execute(
            "SELECT student_code AS 學生代碼, real_name AS 正式姓名, hero_name AS 勇者名稱, created_at AS 建立時間 "
            "FROM players WHERE student_code <> '__TEACHER__' ORDER BY created_at"
        ).fetchall()]
    for row in rows:
        row["建立時間"] = taipei_time_text(row["建立時間"])
    return rows


def toggle_admin_progress_chapter(chapter_id):
    """老師後台章節排名手風琴；交由按鈕回呼避免額外重跑一次。"""
    current = st.session_state.get("admin_progress_chapter")
    st.session_state.admin_progress_chapter = None if current == chapter_id else chapter_id


def submit_game_feedback(student_code, category, message):
    with db_connection() as db:
        db.execute(
            "INSERT INTO game_feedback(student_code, category, message, created_at) "
            "VALUES(?, ?, ?, ?)",
            (student_code, category, message.strip(), database_timestamp()),
        )


def send_mail(student_code, subject, message, reward=None, claimed=False):
    reward_json = json.dumps(reward, ensure_ascii=False) if reward else None
    with db_connection() as db:
        db.execute(
            "INSERT INTO mailbox(student_code, subject, message, reward_json, is_read, is_claimed, created_at) "
            "VALUES(?, ?, ?, ?, 0, ?, ?)",
            (student_code, subject, message.strip(), reward_json, 1 if claimed else 0,
             database_timestamp()),
        )


def mailbox_rows(student_code):
    with db_connection() as db:
        rows = [dict(row) for row in db.execute(
            "SELECT id, subject, message, reward_json, is_read, is_claimed, created_at "
            "FROM mailbox WHERE student_code=? "
            "ORDER BY is_read ASC, is_claimed ASC, id DESC",
            (student_code,),
        ).fetchall()]
    for row in rows:
        row["reward"] = json.loads(row.pop("reward_json")) if row.get("reward_json") else None
        row["created_at"] = taipei_time_text(row["created_at"])
    return rows


def unread_mail_count(student_code):
    with db_connection() as db:
        row = db.execute(
            "SELECT COUNT(*) AS count FROM mailbox WHERE student_code=? AND is_read=0",
            (student_code,),
        ).fetchone()
    return int(row["count"] or 0)


def mark_mail_read(mail_id, student_code):
    with db_connection() as db:
        db.execute(
            "UPDATE mailbox SET is_read=1 WHERE id=? AND student_code=?",
            (mail_id, student_code),
        )


def mark_all_mail_read(student_code):
    """將指定勇者的所有未讀信件標為已讀，不變更附件領取狀態。"""
    with db_connection() as db:
        result = db.execute(
            "UPDATE mailbox SET is_read=1 WHERE student_code=? AND is_read=0",
            (student_code,),
        )
        return max(0, int(result.rowcount or 0))


def claim_mail_reward(mail_id, student_code):
    with db_connection() as db:
        row = db.execute(
            "SELECT reward_json, is_claimed FROM mailbox WHERE id=? AND student_code=?",
            (mail_id, student_code),
        ).fetchone()
    if not row or row["is_claimed"] or not row["reward_json"]:
        return False
    reward = json.loads(row["reward_json"])
    profile = get_profile()
    profile["coins"] += int(reward.get("coins", 0))
    profile["sweep_tickets"] += int(reward.get("sweep_tickets", 0))
    profile["smelting_stones"] += int(reward.get("smelting_stones", 0))
    save_profile(profile)
    with db_connection() as db:
        db.execute(
            "UPDATE mailbox SET is_read=1, is_claimed=1 WHERE id=? AND student_code=?",
            (mail_id, student_code),
        )
    return True


def game_feedback_rows():
    with db_connection() as db:
        rows = [dict(row) for row in db.execute(
            "SELECT f.id AS 編號, f.student_code AS 學生代碼, p.real_name AS 正式姓名, p.hero_name AS 勇者名稱, "
            "f.category AS 問題分類, f.message AS 回饋內容, f.created_at AS 送出時間, "
            "f.replied_at AS 回覆時間 "
            "FROM game_feedback f JOIN players p ON p.student_code=f.student_code "
            "ORDER BY f.id DESC"
        ).fetchall()]
    for row in rows:
        row["送出時間"] = taipei_time_text(row["送出時間"])[:-3]
        if row["回覆時間"]:
            row["回覆時間"] = taipei_time_text(row["回覆時間"])[:-3]
            row["回覆狀態"] = "✅ 已回覆"
        else:
            row["回覆時間"] = "—"
            row["回覆狀態"] = "⏳ 未回覆"
    return rows


def mark_feedback_replied(feedback_id):
    with db_connection() as db:
        db.execute(
            "UPDATE game_feedback SET replied_at=? WHERE id=?",
            (database_timestamp(), feedback_id),
        )


def announcement_rows(active_only=False):
    sql = "SELECT id, title, content, is_active, created_at FROM announcements"
    if active_only:
        sql += " WHERE is_active=1"
    sql += " ORDER BY id DESC"
    with db_connection() as db:
        rows = [dict(row) for row in db.execute(sql).fetchall()]
    for row in rows:
        row["created_at_text"] = taipei_time_text(row["created_at"])
    return rows


def create_announcement(title, content):
    with db_connection() as db:
        db.execute(
            "INSERT INTO announcements(title, content, is_active, created_at) VALUES(?, ?, 1, ?)",
            (title.strip(), content.strip(), database_timestamp()),
        )


def set_announcement_active(announcement_id, is_active):
    with db_connection() as db:
        db.execute(
            "UPDATE announcements SET is_active=? WHERE id=?",
            (1 if is_active else 0, announcement_id),
        )


def update_and_activate_announcement(announcement_id, title, content):
    """儲存舊公告的修改內容、更新發布時間並立即重新啟用。"""
    with db_connection() as db:
        db.execute(
            "UPDATE announcements SET title=?, content=?, is_active=1, created_at=? WHERE id=?",
            (title.strip(), content.strip(), database_timestamp(), announcement_id),
        )


def delete_announcement(announcement_id):
    with db_connection() as db:
        db.execute("DELETE FROM announcements WHERE id=?", (announcement_id,))


def render_announcement_content(content):
    """保留公告換行，並把編號行轉成醒目的分隔項目。"""
    lines = [line.strip() for line in str(content).splitlines() if line.strip()]
    items = []
    for line in lines:
        numbered = re.match(r"^\s*(\d+)\s*[\.、\)）]\s*(.+)$", line)
        if numbered:
            badge = html.escape(numbered.group(1))
            text = html.escape(numbered.group(2))
        else:
            badge = "◆"
            text = html.escape(line)
        items.append(
            '<div class="announcement-item">'
            f'<div class="announcement-badge">{badge}</div>'
            f'<div class="announcement-text">{text}</div>'
            '</div>'
        )
    st.markdown(
        """
        <style>
        .announcement-list {margin:.4rem 0 .2rem;}
        .announcement-item {display:flex;align-items:flex-start;gap:.8rem;padding:.85rem .2rem;
          border-bottom:1px solid #dfe3ea;}
        .announcement-item:last-child {border-bottom:0;}
        .announcement-badge {display:flex;align-items:center;justify-content:center;flex:0 0 2rem;
          min-width:2rem;height:2rem;border-radius:50%;background:#ff4b4b;color:#fff;
          font-size:1.05rem;font-weight:900;line-height:1;box-shadow:0 2px 7px #ff4b4b44;}
        .announcement-text {padding-top:.15rem;font-size:1.05rem;line-height:1.65;
          overflow-wrap:anywhere;white-space:pre-wrap;}
        @media (max-width:600px) {
          .announcement-item {gap:.55rem;padding:.7rem .05rem;}
          .announcement-badge {flex-basis:1.75rem;min-width:1.75rem;height:1.75rem;font-size:.95rem;}
          .announcement-text {font-size:.96rem;line-height:1.55;}
        }
        </style>
        <div class="announcement-list">"""
        + "".join(items)
        + "</div>",
        unsafe_allow_html=True,
    )


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
    if profile.get("chapter4_boss_wins", 0) > 0:
        return "5"
    if profile.get("chapter3_boss_wins", 0) > 0:
        return "4"
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
        "4": ("chapter4_boss_wins", "chapter4_elite_boss_wins"),
        "5": ("chapter5_boss_wins", "chapter5_elite_boss_wins"),
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
        "4": ("chapter4_rankings", "chapter4_elite_rankings"),
        "5": ("chapter5_rankings", "chapter5_elite_rankings"),
    }
    clear_times = {}
    union_parts = []
    parameters = []
    for chapter_id, (normal_table, elite_table) in table_by_chapter.items():
        for boss_type, table in (("normal", normal_table), ("elite", elite_table)):
            union_parts.append(
                f"SELECT '{chapter_id}' AS chapter_id, '{boss_type}' AS boss_type, "
                f"clear_time FROM {table} WHERE student_code=?"
            )
            parameters.append(code)
    with db_connection() as db:
        ranking_rows_result = db.execute(
            " UNION ALL ".join(union_parts), tuple(parameters)
        ).fetchall()
    ranking_times = {
        (str(row["chapter_id"]), row["boss_type"]): row["clear_time"]
        for row in ranking_rows_result
    }
    for chapter_id in CHAPTERS:
        for boss_type in ("normal", "elite"):
            ranking_time = ranking_times.get((chapter_id, boss_type))
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
        "1": "boss_wins", "2": "chapter2_boss_wins", "3": "chapter3_boss_wins", "4": "chapter4_boss_wins",
        "5": "chapter5_boss_wins",
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
    chapter_id = unit_id.split("-")[0]
    fixed_stat, fixed_value = fixed_value_for(chapter_id, slot, stars)
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
    fixed_stat, fixed_value = fixed_value_for(chapter_id, slot, 3)
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


def shop_paid_refresh_cost(profile):
    """每五次強制刷新費用加倍：1～5次100、6～10次200，依此類推。"""
    refresh_count = int((profile.get("shop") or {}).get("paid_refresh_count", 0) or 0)
    return 100 * (2 ** (refresh_count // 5))


def refresh_shop(profile, paid=False):
    paid_refresh_count = int(
        (profile.get("shop") or {}).get("paid_refresh_count", 0) or 0
    )
    if paid:
        refresh_cost = shop_paid_refresh_cost(profile)
        if profile["coins"] < refresh_cost:
            return False
        profile["coins"] -= refresh_cost
        paid_refresh_count += 1
    else:
        # 每24小時的免費自動刷新會開始新一輪強制刷新計數。
        paid_refresh_count = 0
    chapter_id = highest_shop_chapter(profile)
    profile["shop"] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "items": [make_shop_item(profile, chapter_id) for _ in range(6)],
        "paid_refresh_count": paid_refresh_count,
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
        fixed_stat, fixed_value = fixed_value_for(chapter_id, selected_slot, target_stars)
        item["fixed_stat"] = fixed_stat
        item["fixed_value"] = fixed_value
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
        "name": four_star_item_name("1", "整數勇者之劍"),
        "fixed_stat": "attack",
        "fixed_value": fixed_value_for("1", "weapon", 4)[1],
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
        "name": four_star_item_name("1", "收藏家王冠"),
        "fixed_stat": "hp",
        "fixed_value": fixed_value_for("1", "helmet", 4)[1],
        "affix_stat": "defense_pct",
        "affix_value": 0.25,
        "achievement": True,
    }


def make_collection_reward():
    return {
        "uid": uuid.uuid4().hex, "unit": "chapter-1-collection", "slot": "necklace",
        "stars": 4, "name": four_star_item_name("1", "九星守護項鍊"), "fixed_stat": "boss_hp_reduction",
        "fixed_value": fixed_value_for("1", "necklace", 4)[1], "affix_stat": "hp_pct", "affix_value": 0.25,
        "achievement": True,
    }


def make_chapter2_reward():
    return {
        "uid": uuid.uuid4().hex, "unit": "chapter-2", "slot": "gloves",
        "stars": 4, "name": four_star_item_name("2", "乘除勇者手甲"), "fixed_stat": "attack",
        "fixed_value": fixed_value_for("2", "gloves", 4)[1], "affix_stat": "attack_pct", "affix_value": 0.25,
        "achievement": True,
    }


def make_chapter2_collection_reward():
    return {
        "uid": uuid.uuid4().hex, "unit": "chapter-2-collection", "slot": "boots",
        "stars": 4, "name": four_star_item_name("2", "乘除疾風戰靴"), "fixed_stat": "attack_speed",
        "fixed_value": fixed_value_for("2", "boots", 4)[1], "affix_stat": "speed_pct", "affix_value": 0.25,
        "achievement": True,
    }


def make_chapter2_elite_reward():
    return {
        "uid": uuid.uuid4().hex, "unit": "chapter-2-elite", "slot": "shield",
        "stars": 4, "name": four_star_item_name("2", "乘除霸主盾"), "fixed_stat": "defense",
        "fixed_value": fixed_value_for("2", "shield", 4)[1], "affix_stat": "hp_pct", "affix_value": 0.25,
        "achievement": True,
    }


def make_chapter3_reward():
    return {
        "uid": uuid.uuid4().hex, "unit": "chapter-3", "slot": "armor",
        "stars": 4, "name": four_star_item_name("3", "龍鱗守護鎧"), "fixed_stat": "defense",
        "fixed_value": fixed_value_for("3", "armor", 4)[1],
        "affix_stat": "defense_pct", "affix_value": 0.25,
        "achievement": True,
    }


def make_chapter3_collection_reward():
    return {
        "uid": uuid.uuid4().hex, "unit": "chapter-3-collection", "slot": "belt",
        "stars": 4, "name": four_star_item_name("3", "龍心腰帶"), "fixed_stat": "hp",
        "fixed_value": fixed_value_for("3", "belt", 4)[1],
        "affix_stat": "hp_pct", "affix_value": 0.25,
        "achievement": True,
    }


def make_chapter3_elite_reward():
    return {
        "uid": uuid.uuid4().hex, "unit": "chapter-3-elite", "slot": "ring",
        "stars": 4, "name": four_star_item_name("3", "烈焰龍王戒"), "fixed_stat": "first_hit_percent",
        "fixed_value": fixed_value_for("3", "ring", 4)[1],
        "affix_stat": "boss_damage_pct", "affix_value": 0.25,
        "achievement": True,
    }


def make_chapter4_reward():
    return {
        "uid": uuid.uuid4().hex, "unit": "chapter-4", "slot": "helmet",
        "stars": 4, "name": four_star_item_name("4", "雷狐靈冠"), "fixed_stat": "hp",
        "fixed_value": fixed_value_for("4", "helmet", 4)[1],
        "affix_stat": "hp_pct", "affix_value": 0.25, "achievement": True,
    }


def make_chapter4_collection_reward():
    return {
        "uid": uuid.uuid4().hex, "unit": "chapter-4-collection", "slot": "boots",
        "stars": 4, "name": four_star_item_name("4", "紫電踏雲靴"), "fixed_stat": "attack_speed",
        "fixed_value": fixed_value_for("4", "boots", 4)[1],
        "affix_stat": "speed_pct", "affix_value": 0.25, "achievement": True,
    }


def make_chapter4_elite_reward():
    return {
        "uid": uuid.uuid4().hex, "unit": "chapter-4-elite", "slot": "weapon",
        "stars": 4, "name": four_star_item_name("4", "九尾天雷刃"), "fixed_stat": "attack",
        "fixed_value": fixed_value_for("4", "weapon", 4)[1],
        "affix_stat": "critical_rate", "affix_value": 0.25, "achievement": True,
    }


def make_chapter5_reward():
    return {
        "uid": uuid.uuid4().hex, "unit": "chapter-5", "chapter": "5", "slot": "armor",
        "stars": 4, "name": four_star_item_name("5", "冰河守護鎧"), "fixed_stat": "defense",
        "fixed_value": fixed_value_for("5", "armor", 4)[1],
        "affix_stat": "defense_pct", "affix_value": 0.25, "achievement": True,
    }


def make_chapter5_collection_reward():
    return {
        "uid": uuid.uuid4().hex, "unit": "chapter-5-collection", "chapter": "5", "slot": "necklace",
        "stars": 4, "name": four_star_item_name("5", "極寒潮汐項鍊"), "fixed_stat": "boss_hp_reduction",
        "fixed_value": fixed_value_for("5", "necklace", 4)[1],
        "affix_stat": "damage_reduction_pct", "affix_value": 0.25, "achievement": True,
    }


def make_chapter5_elite_reward():
    return {
        "uid": uuid.uuid4().hex, "unit": "chapter-5-elite", "chapter": "5", "slot": "shield",
        "stars": 4, "name": four_star_item_name("5", "暴風王盾"), "fixed_stat": "defense",
        "fixed_value": fixed_value_for("5", "shield", 4)[1],
        "affix_stat": "boss_damage_pct", "affix_value": 0.25, "achievement": True,
    }


def retroactively_grant_chapter3_rewards(profile):
    """依既有第三章進度補發新開放的三件四星裝備。"""
    changed = False
    if (
        all(profile["unit_best_stars"].get(uid, 0) == 3 for uid in chapter_unit_ids("3"))
        and not profile.get("chapter3_reward_claimed")
    ):
        reward = make_chapter3_reward()
        profile["inventory"].append(reward)
        profile["chapter3_reward_claimed"] = True
        profile["retro_reward_notice"].append(f"第三章滿星補發：{item_text(reward)}")
        changed = True
    if (
        has_full_three_star_set(profile, "3")
        and not profile.get("chapter3_collection_reward_claimed")
    ):
        reward = make_chapter3_collection_reward()
        profile["inventory"].append(reward)
        profile["chapter3_collection_reward_claimed"] = True
        add_exp(profile, 100)
        profile["retro_reward_notice"].append(
            f"第三章九部位收藏補發100 EXP與：{item_text(reward)}"
        )
        changed = True
    if (
        profile.get("chapter3_elite_boss_wins", 0) > 0
        and not profile.get("chapter3_elite_reward_claimed")
    ):
        reward = make_chapter3_elite_reward()
        profile["inventory"].append(reward)
        profile["chapter3_elite_reward_claimed"] = True
        profile["retro_reward_notice"].append(f"第三章菁英BOSS補發：{item_text(reward)}")
        changed = True
    return changed


def sync_item_four_star_name(item):
    """補齊四星裝備名稱的章節前綴，已正確命名者不重複添加。"""
    if int(item.get("stars", 0) or 0) != 4:
        return False
    chapter_id = item_chapter_id(item)
    if chapter_id not in CHAPTERS or not item.get("name"):
        return False
    expected_name = four_star_item_name(chapter_id, item["name"])
    if item["name"] == expected_name:
        return False
    item["name"] = expected_name
    item.setdefault("chapter", chapter_id)
    return True


def sync_collection_catalog(profile):
    """把目前物品登錄為永久收藏；只增加紀錄，永不因移除物品而倒退。"""
    catalog = set(profile.get("collection_catalog", []))
    for item in profile.get("inventory", []):
        stars = int(item.get("stars", 0) or 0)
        slot = item.get("slot")
        if not stars or not slot:
            continue
        if item.get("achievement"):
            unit_key = str(item.get("unit", "achievement"))
            catalog.add(f"achievement:{stars}:{unit_key}:{slot}")
        else:
            chapter_id = item_chapter_id(item)
            if chapter_id:
                catalog.add(f"{chapter_id}:{stars}:{slot}")
    profile["collection_catalog"] = sorted(catalog)


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


def achievement_was_collected(profile, unit_key, stars=4):
    prefix = f"achievement:{stars}:{unit_key}:"
    return any(
        entry.startswith(prefix) for entry in profile.get("collection_catalog", [])
    ) or achievement_item(profile, unit_key) is not None


def collected_achievement_slots(profile, stars=4):
    owned = {
        item["slot"] for item in profile["inventory"]
        if item.get("achievement") and item.get("stars") == stars
    }
    prefix = f"achievement:{stars}:"
    recorded = {
        entry.rsplit(":", 1)[-1]
        for entry in profile.get("collection_catalog", [])
        if entry.startswith(prefix)
    }
    return owned | recorded


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


def sync_item_fixed_value(item):
    """依新版章節差值表同步一至四星裝備，回傳是否有修改。"""
    chapter_id = item_chapter_id(item)
    slot = item.get("slot")
    stars = int(item.get("stars", 0) or 0)
    if chapter_id not in CHAPTERS or slot not in FIXED_STATS or stars not in (1, 2, 3, 4):
        return False
    fixed_stat, fixed_value = fixed_value_for(chapter_id, slot, stars)
    changed = item.get("fixed_stat") != fixed_stat or item.get("fixed_value") != fixed_value
    item["fixed_stat"] = fixed_stat
    item["fixed_value"] = fixed_value
    item.setdefault("chapter", chapter_id)
    return changed


@st.cache_resource(show_spinner=False)
def migrate_all_profiles_fixed_values():
    """一次性更新資料庫內所有玩家已裝備、未裝備與商店裝備。"""
    migration_key = "fixed_values_chapter_steps_v1"
    with db_connection() as db:
        done = db.execute("SELECT value FROM settings WHERE key=?", (migration_key,)).fetchone()
        if done and done["value"] == "1":
            return
        rows = db.execute("SELECT student_code, profile_json FROM players").fetchall()
        for row in rows:
            profile = json.loads(row["profile_json"])
            changed = False
            for item in profile.get("inventory", []):
                changed = sync_item_fixed_value(item) or changed
            for shop_entry in (profile.get("shop") or {}).get("items", []):
                shop_item = shop_entry.get("item")
                if shop_item:
                    changed = sync_item_fixed_value(shop_item) or changed
            if profile.get("chapter3_elite_boss_wins", 0) > 0 and "一刀斬龍" not in profile.get("titles", []):
                profile.setdefault("titles", []).append("一刀斬龍")
                profile.setdefault("retro_reward_notice", []).append("補發成就稱號「一刀斬龍」")
                changed = True
            if changed:
                db.execute(
                    "UPDATE players SET profile_json=? WHERE student_code=?",
                    (json.dumps(profile, ensure_ascii=False), row["student_code"]),
                )
        db.execute(
            "INSERT INTO settings(key, value) VALUES(?, '1') "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (migration_key,),
        )


@st.cache_resource(show_spinner=False)
def migrate_all_profiles_four_star_names():
    """一次性補正所有玩家既有四星裝備的章節名稱。"""
    migration_key = "four_star_chapter_name_prefix_v1"
    with db_connection() as db:
        done = db.execute("SELECT value FROM settings WHERE key=?", (migration_key,)).fetchone()
        if done and done["value"] == "1":
            return
        rows = db.execute("SELECT student_code, profile_json FROM players").fetchall()
        for row in rows:
            profile = json.loads(row["profile_json"])
            changed = False
            for item in profile.get("inventory", []):
                changed = sync_item_four_star_name(item) or changed
            for shop_entry in (profile.get("shop") or {}).get("items", []):
                shop_item = shop_entry.get("item")
                if shop_item:
                    changed = sync_item_four_star_name(shop_item) or changed
            if changed:
                db.execute(
                    "UPDATE players SET profile_json=? WHERE student_code=?",
                    (json.dumps(profile, ensure_ascii=False), row["student_code"]),
                )
        db.execute(
            "INSERT INTO settings(key, value) VALUES(?, '1') "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (migration_key,),
        )


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
        if abs(difference) < 1e-9:
            continue
        comparison_rows.append({
            "人物能力": label,
            "目前": display_value(before[key], kind),
            "更換後": display_value(after[key], kind),
            "增減": display_value(difference, kind, signed=True),
        })
    st.write("**能力變動對照**")
    if comparison_rows:
        st.dataframe(comparison_rows, hide_index=True, use_container_width=True)
    else:
        st.caption("更換後人物能力沒有變動。")


def dismiss_forge_result_dialog():
    """關閉熔煉結果視窗等同保留裝備於背包。"""
    st.session_state.forge_result_uid = None


@st.dialog("🔥 熔煉完成", dismissible=True, on_dismiss=dismiss_forge_result_dialog)
def render_forge_result_dialog(profile, forged_item):
    st.success("成功合成以下裝備！")
    st.markdown(f"### {item_text(forged_item)}")
    render_item_comparison(profile, forged_item)
    equip_col, keep_col = st.columns(2)
    if equip_col.button(
        "立即裝備", type="primary", use_container_width=True,
        key=f"forge_dialog_equip_{forged_item['uid']}",
    ):
        profile["equipment"][forged_item["slot"]] = forged_item["uid"]
        save_profile(profile)
        st.session_state.forge_result_uid = None
        st.rerun()
    if keep_col.button(
        "放入物品欄", use_container_width=True,
        key=f"forge_dialog_keep_{forged_item['uid']}",
    ):
        st.session_state.forge_result_uid = None
        st.rerun()


def unit_unlocked(profile, unit_id):
    chapter_id = unit_id.split("-")[0]
    if chapter_id == "2" and profile.get("boss_wins", 0) <= 0 and st.session_state.active_player != "__TEACHER__":
        return False
    if chapter_id == "3" and profile.get("chapter2_boss_wins", 0) <= 0 and st.session_state.active_player != "__TEACHER__":
        return False
    if chapter_id == "4" and profile.get("chapter3_boss_wins", 0) <= 0 and st.session_state.active_player != "__TEACHER__":
        return False
    if chapter_id == "5" and profile.get("chapter4_boss_wins", 0) <= 0 and st.session_state.active_player != "__TEACHER__":
        return False
    order = chapter_unit_ids(chapter_id)
    index = order.index(unit_id)
    return index == 0 or profile["unit_best_stars"][order[index - 1]] > 0


def focus_answer_input():
    components.html(
        """
        <script>
        const focusAnswer = () => {
            const doc = parent.window.document;
            const answer = doc.querySelector('input[aria-label="你的答案"]')
                || doc.querySelector('input[placeholder="輸入後按 Enter"]')
                || doc.querySelector('input[aria-label="分子"]')
                || doc.querySelector('input[placeholder="分子"]');
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
    """只在剛切換頁面的第一個繪製週期回頂端，不干擾之後的手動捲動。"""
    if not st.session_state.get(state_key):
        return
    components.html(
        """
        <script>
        const scrollTop = () => {
            const doc = parent.window.document;
            const selectors = [
                '.stMain',
                'section.main',
                '[data-testid="stMain"]',
                '[data-testid="stAppViewContainer"]',
                '[data-testid="stApp"]',
                '.main'
            ];
            selectors.forEach(selector => {
                doc.querySelectorAll(selector).forEach(node => {
                    node.scrollTop = 0;
                    node.scrollLeft = 0;
                    if (node.scrollTo) node.scrollTo({top: 0, left: 0, behavior: 'instant'});
                });
            });
            doc.documentElement.scrollTop = 0;
            doc.documentElement.scrollLeft = 0;
            doc.body.scrollTop = 0;
            doc.body.scrollLeft = 0;
            parent.window.scrollTo(0, 0);
        };
        scrollTop();
        requestAnimationFrame(() => requestAnimationFrame(scrollTop));
        </script>
        """,
        height=1,
        scrolling=False,
    )
    st.session_state[state_key] = False


def remove_stale_elements_before(marker_id):
    """清除 Streamlit 換頁時偶爾殘留在新頁內容上方的舊按鈕列與分頁列。"""
    st.markdown(f'<div id="{marker_id}"></div>', unsafe_allow_html=True)
    components.html(
        f"""
        <script>
        const clearStaleElements = () => {{
            const doc = parent.document;
            const marker = doc.getElementById('{marker_id}');
            if (!marker) return;
            const markerTop = marker.getBoundingClientRect().top;

            doc.querySelectorAll('[data-testid="stTabs"]').forEach(tabs => {{
                const rect = tabs.getBoundingClientRect();
                if (rect.bottom > 0 && rect.top < markerTop - 2) tabs.remove();
            }});

            doc.querySelectorAll('button').forEach(button => {{
                if (button.closest('header[data-testid="stHeader"]')) return;
                const rect = button.getBoundingClientRect();
                if (rect.bottom <= 0 || rect.top >= markerTop - 2) return;
                const row = button.closest('[data-testid="stHorizontalBlock"]');
                const element = row || button.closest('[data-testid="stElementContainer"]');
                if (element) element.remove();
            }});
        }};
        [0, 40, 100, 220, 450, 800, 1300].forEach(
            delay => setTimeout(clearStaleElements, delay)
        );
        </script>
        """,
        height=0,
        scrolling=False,
    )


def force_top_before_navigation():
    """在按鈕切換 screen 前立即重設手機瀏覽器的捲動位置。"""
    components.html(
        """
        <script>
        const doc = parent.window.document;
        doc.querySelectorAll('.stMain, section.main, [data-testid="stMain"], [data-testid="stAppViewContainer"]')
          .forEach(node => { node.scrollTop = 0; node.scrollLeft = 0; });
        doc.documentElement.scrollTop = 0;
        doc.body.scrollTop = 0;
        parent.window.scrollTo(0, 0);
        </script>
        """,
        height=1,
        scrolling=False,
    )


def uses_advanced_combo_rules(unit_id=None):
    """Chapter 5 onward uses the shorter combo thresholds."""
    unit_id = unit_id or st.session_state.get("selected_unit", "1-1")
    try:
        return int(str(unit_id).split("-", 1)[0]) >= 5
    except (TypeError, ValueError):
        return False


def combo_auto_clear_target(unit_id=None):
    return 8 if uses_advanced_combo_rules(unit_id) else 10


def stars_for_combo(combo, unit_id=None):
    if uses_advanced_combo_rules(unit_id):
        if combo >= 7:
            return 3
        if combo >= 4:
            return 2
        if combo >= 1:
            return 1
        return 0
    if combo >= 10:
        return 3
    if combo >= 5:
        return 2
    if combo >= 1:
        return 1
    return 0


def start_quiz(unit_id):
    if st.session_state.active_player != "__TEACHER__":
        profile = get_profile()
        if not unit_unlocked(profile, unit_id):
            st.session_state.selected_chapter = highest_unlocked_chapter(profile)
            st.session_state.screen = "menu"
            st.toast("請先通過前一章普通 BOSS，才能進入這個章節。", icon="🔒")
            return False
    st.session_state.selected_unit = unit_id
    st.session_state.selected_chapter = unit_id.split("-")[0]
    st.session_state.deadline = None
    st.session_state.quiz_started_at = time.time()
    st.session_state.quiz_elapsed = 0.0
    st.session_state.question = make_question(unit_id)
    st.session_state.answer_input = None
    st.session_state.answer_numerator = None
    st.session_state.answer_denominator = None
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
    return True


def finish_quiz():
    st.session_state.stars = stars_for_combo(
        st.session_state.max_combo,
        st.session_state.selected_unit,
    )
    if st.session_state.quiz_started_at:
        st.session_state.quiz_elapsed = time.time() - st.session_state.quiz_started_at
    st.session_state.deadline = None
    st.session_state.screen = "quiz_result"


def leave_quiz():
    """Leave an unfinished quiz without saving a result or granting rewards."""
    st.session_state.deadline = None
    st.session_state.quiz_started_at = None
    st.session_state.message = ""
    st.session_state.screen = "menu"


def submit_quiz_answer():
    if st.session_state.screen != "quiz" or st.session_state.attempts >= MAX_QUESTIONS:
        return
    question_text = st.session_state.question["text"]
    correct_answer = st.session_state.question["answer"]
    if st.session_state.question.get("fraction"):
        numerator = st.session_state.answer_numerator
        denominator = st.session_state.answer_denominator
        if numerator is None or denominator in (None, 0):
            return
        submitted_answer = float(numerator) / float(denominator)
        submitted_text = f"{int(numerator)}/{int(denominator)}"
        correct_text = (
            f"{st.session_state.question['answer_numerator']}/"
            f"{st.session_state.question['answer_denominator']}"
        )
    else:
        answer = st.session_state.answer_input
        if answer is None:
            return
        submitted_answer = float(answer)
        submitted_text = submitted_answer
        correct_text = correct_answer
    st.session_state.attempts += 1
    if st.session_state.question.get("fraction"):
        # 最簡分數必須分子、分母皆完全正確；等值但未約分的答案不算答對。
        is_correct = (
            int(numerator) == st.session_state.question["answer_numerator"]
            and int(denominator) == st.session_state.question["answer_denominator"]
        )
    else:
        is_correct = math.isclose(submitted_answer, float(correct_answer), abs_tol=1e-9)
    if is_correct:
        st.session_state.correct += 1
        st.session_state.combo += 1
        st.session_state.max_combo = max(st.session_state.max_combo, st.session_state.combo)
        st.session_state.message = f"✅ 連擊{st.session_state.combo}！"
    else:
        st.session_state.message = f"❌ 答案是{correct_text}，連擊中斷。"
        st.session_state.combo = 0
    answer_row = {
        "question_text": (
            f"{question_text}（學生填答：{submitted_text}）"
            if st.session_state.question.get("fraction") else question_text
        ),
        "submitted_answer": submitted_answer,
        "correct_answer": correct_answer,
        "is_correct": is_correct,
        "combo_after": st.session_state.combo,
        "elapsed_seconds": round(time.time() - st.session_state.quiz_started_at, 2),
        "answered_at": database_timestamp(),
    }
    st.session_state.answer_history.append(answer_row)
    log_question_answer(st.session_state.selected_unit, answer_row)
    st.session_state.answer_input = None
    st.session_state.answer_numerator = None
    st.session_state.answer_denominator = None
    if (
        st.session_state.max_combo >= combo_auto_clear_target(st.session_state.selected_unit)
        or st.session_state.attempts >= MAX_QUESTIONS
    ):
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
    if (
        all(profile["unit_best_stars"][uid] == 3 for uid in chapter_unit_ids("3"))
        and not profile["chapter3_reward_claimed"]
    ):
        reward = make_chapter3_reward()
        profile["inventory"].append(reward)
        profile["chapter3_reward_claimed"] = True
        st.session_state.extra_reward_messages.append(f"第三章滿星獎勵：{item_text(reward)}")
    if has_full_three_star_set(profile, "3") and not profile["chapter3_collection_reward_claimed"]:
        collection_levels = add_exp(profile, 100)
        reward = make_chapter3_collection_reward()
        profile["inventory"].append(reward)
        profile["chapter3_collection_reward_claimed"] = True
        if collection_levels:
            st.session_state.collection_level_up_to = profile["level"]
        st.session_state.extra_reward_messages.append(
            f"第三章九部位收藏完成，獲得100 EXP與：{item_text(reward)}"
        )
    if (
        all(profile["unit_best_stars"][uid] == 3 for uid in chapter_unit_ids("4"))
        and not profile["chapter4_reward_claimed"]
    ):
        reward = make_chapter4_reward()
        profile["inventory"].append(reward)
        profile["chapter4_reward_claimed"] = True
        st.session_state.extra_reward_messages.append(f"第四章滿星獎勵：{item_text(reward)}")
    if has_full_three_star_set(profile, "4") and not profile["chapter4_collection_reward_claimed"]:
        collection_levels = add_exp(profile, 100)
        reward = make_chapter4_collection_reward()
        profile["inventory"].append(reward)
        profile["chapter4_collection_reward_claimed"] = True
        if collection_levels:
            st.session_state.collection_level_up_to = profile["level"]
        st.session_state.extra_reward_messages.append(
            f"第四章九部位收藏完成，獲得100 EXP與：{item_text(reward)}"
        )
    if (
        all(profile["unit_best_stars"][uid] == 3 for uid in chapter_unit_ids("5"))
        and not profile["chapter5_reward_claimed"]
    ):
        reward = make_chapter5_reward()
        profile["inventory"].append(reward)
        profile["chapter5_reward_claimed"] = True
        st.session_state.extra_reward_messages.append(f"第五章滿星獎勵：{item_text(reward)}")
    if has_full_three_star_set(profile, "5") and not profile["chapter5_collection_reward_claimed"]:
        collection_levels = add_exp(profile, 100)
        reward = make_chapter5_collection_reward()
        profile["inventory"].append(reward)
        profile["chapter5_collection_reward_claimed"] = True
        if collection_levels:
            st.session_state.collection_level_up_to = profile["level"]
        st.session_state.extra_reward_messages.append(
            f"第五章九部位收藏完成，獲得100 EXP與：{item_text(reward)}"
        )
    st.session_state.earned_exp = exp_gain
    st.session_state.result_processed = True
    save_profile(profile)
    log_attempt(unit_id)


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
            ("4", "normal"): ("chapter4_boss_wins", "chapter4_boss_exp_claimed"),
            ("4", "elite"): ("chapter4_elite_boss_wins", "chapter4_elite_boss_exp_claimed"),
            ("5", "normal"): ("chapter5_boss_wins", "chapter5_boss_exp_claimed"),
            ("5", "elite"): ("chapter5_elite_boss_wins", "chapter5_elite_boss_exp_claimed"),
        }
        wins_key, exp_key = key_map[(chapter_id, boss_type)]
        profile[wins_key] += 1
        if not profile[exp_key]:
            exp_gain = config["exp"]
            levels_gained = add_exp(profile, exp_gain)
            if levels_gained:
                level_up_to = profile["level"]
            profile[exp_key] = True
        reward_claimed_key = {
            "1": "elite_reward_claimed",
            "2": "chapter2_elite_reward_claimed",
            "3": "chapter3_elite_reward_claimed",
            "4": "chapter4_elite_reward_claimed",
            "5": "chapter5_elite_reward_claimed",
        }.get(chapter_id)
        if boss_type == "elite" and reward_claimed_key and not profile[reward_claimed_key]:
            reward = {
                "1": make_elite_reward,
                "2": make_chapter2_elite_reward,
                "3": make_chapter3_elite_reward,
                "4": make_chapter4_elite_reward,
                "5": make_chapter5_elite_reward,
            }[chapter_id]()
            profile["inventory"].append(reward)
            profile[reward_claimed_key] = True
            reward_item_uid = reward["uid"]
        if boss_type == "elite" and chapter_id in ("1", "2", "3", "4", "5"):
            earned_title = {
                "1": "好像有點勇哦",
                "2": "別小看我！",
                "3": "一刀斬龍",
                "4": "渡雷劫方可成仙",
                "5": "魚與熊掌我都要",
            }[chapter_id]
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


def render_stats(profile, show_exp=True):
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
    if show_exp:
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


def render_bottom_home_button(key):
    """長頁面底部的首頁捷徑，避免手機使用者再捲回頁首。"""
    st.divider()
    if st.button("← 回到首頁", key=f"bottom_home_{key}", use_container_width=True):
        st.session_state.shop_purchase_uid = None
        st.session_state.forge_result_uid = None
        st.session_state.screen = "home"
        st.rerun()


BOSS_WIN_KEYS = {
    ("1", "normal"): "boss_wins",
    ("1", "elite"): "elite_boss_wins",
    ("2", "normal"): "chapter2_boss_wins",
    ("2", "elite"): "chapter2_elite_boss_wins",
    ("3", "normal"): "chapter3_boss_wins",
    ("3", "elite"): "chapter3_elite_boss_wins",
    ("4", "normal"): "chapter4_boss_wins",
    ("4", "elite"): "chapter4_elite_boss_wins",
    ("5", "normal"): "chapter5_boss_wins",
    ("5", "elite"): "chapter5_elite_boss_wins",
}
SKILL_CINEMATIC_SECONDS = 1.5
SKILL_DRAGON_FLIGHT_SECONDS = 2.0
SKILL_IMPACT_SECONDS = 1.0


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
            active_skill = {**event, "presentation_phase": "announcement"}
            simulated_elapsed = max(0.0, event["time"] - 0.001)
            break
        flight_start = cinematic_start + SKILL_CINEMATIC_SECONDS
        if real_elapsed < flight_start + SKILL_DRAGON_FLIGHT_SECONDS:
            active_skill = {**event, "presentation_phase": "dragon_flight"}
            simulated_elapsed = max(0.0, event["time"] - 0.001)
            break
        impact_start = flight_start + SKILL_DRAGON_FLIGHT_SECONDS
        if real_elapsed < impact_start + SKILL_IMPACT_SECONDS:
            active_skill = {**event, "presentation_phase": "aftermath"}
            simulated_elapsed = event["time"]
            break
        paused_seconds += (
            SKILL_CINEMATIC_SECONDS + SKILL_DRAGON_FLIGHT_SECONDS + SKILL_IMPACT_SECONDS
        )
        simulated_elapsed = real_elapsed - paused_seconds
    presentation_duration = result["duration"] + len(skill_events) * (
        SKILL_CINEMATIC_SECONDS + SKILL_DRAGON_FLIGHT_SECONDS + SKILL_IMPACT_SECONDS
    )
    return simulated_elapsed, active_skill, presentation_duration


@st.cache_data(show_spinner=False)
def boss_image_data_uri(filename):
    image_path = Path(__file__).parent / "assets" / "bosses" / filename
    if not image_path.exists():
        return ""
    return "data:image/webp;base64," + base64.b64encode(image_path.read_bytes()).decode("ascii")


@st.cache_data(show_spinner=False)
def effect_image_data_uri(filename):
    image_path = Path(__file__).parent / "assets" / "effects" / filename
    if not image_path.exists():
        return ""
    return "data:image/webp;base64," + base64.b64encode(image_path.read_bytes()).decode("ascii")


@st.cache_data(show_spinner=False)
def hero_image_data_uri(gender="male"):
    filename = "blue-silver-hero-female.webp" if gender == "female" else "blue-silver-hero.webp"
    image_path = Path(__file__).parent / "assets" / "heroes" / filename
    if not image_path.exists():
        return ""
    return "data:image/webp;base64," + base64.b64encode(image_path.read_bytes()).decode("ascii")


def render_battle_scene(event, chapter_id, boss_type, event_sequence, active_skill=None, gender="male"):
    skill_phase = active_skill.get("presentation_phase") if active_skill else None
    skill_flight = skill_phase == "dragon_flight"
    skill_impact = skill_phase == "aftermath"
    active_skill_text = active_skill.get("text", "") if active_skill else ""
    is_lightning_skill = "天降雷劫" in active_skill_text
    is_wind_skill = "狂風驟雨" in active_skill_text
    hero_attacking = event["text"].startswith("勇者") and active_skill is None
    boss_attacking = ("BOSS第" in event["text"] or "BOSS發動" in event["text"]) and active_skill is None
    critical_hit = "暴擊" in event["text"]
    hero_defeated = event.get("player_hp", 1) <= 0
    boss_defeated = event.get("boss_hp", 1) <= 0
    hero_class = "fighter hero hero-attack" if hero_attacking else "fighter hero"
    boss_class = "fighter boss boss-attack" if boss_attacking else "fighter boss"
    # 模擬器在0秒同時建立「戰鬥開始」與勇者第一擊，因此前兩筆才是入場畫面。
    if event_sequence <= 2:
        hero_class += " enter-battle hero-enter"
        boss_class += " enter-battle boss-enter"
    if hero_defeated:
        hero_class += " defeated"
    if boss_defeated:
        boss_class += " defeated"
    hero_hit = boss_attacking or (skill_impact and not is_wind_skill)
    boss_hit = hero_attacking
    if hero_hit and not hero_defeated:
        hero_class += " hit-shake"
    if boss_hit and not boss_defeated:
        boss_class += " hit-shake"
    hero_claws = '<div class="claw-hit hero-claw"><i></i><i></i><i></i></div>' if hero_hit else ""
    boss_claws = '<div class="claw-hit boss-claw"><i></i><i></i><i></i></div>' if boss_hit else ""
    sword_slash = '<div class="sword-slash"></div>' if hero_attacking else ""
    damage_match = re.search(r"造成\s*([0-9.]+)", event["text"])
    damage_text = damage_match.group(1) if damage_match else ""
    damage_overlay = ""
    if damage_text and active_skill is None:
        target_class = "damage-on-boss" if hero_attacking else "damage-on-hero"
        critical_class = " critical-number" if critical_hit else ""
        prefix = "暴擊 " if critical_hit else "-"
        damage_overlay = f'<div class="damage-number {target_class}{critical_class}">{prefix}{damage_text}</div>'
    boss_config = BOSS_CONFIGS[f"{chapter_id}_{boss_type}"]
    boss_image = boss_image_data_uri(boss_config["image"])
    hero_image = hero_image_data_uri(gender)
    hero_visual = (
        f'<img class="hero-portrait" src="{hero_image}" alt="勇者">'
        if hero_image else '<div class="hero-fallback">🦸</div>'
    )
    boss_visual = (
        f'<img class="boss-portrait" src="{boss_image}" alt="{boss_config["name"]}">'
        if boss_image else '<div class="boss-fallback">🐉</div>'
    )
    skill_overlay = ""
    if skill_phase == "announcement":
        cinematic_class = (
            "lightning-cinematic" if is_lightning_skill
            else "wind-cinematic" if is_wind_skill else ""
        )
        skill_icon = "⚡" if is_lightning_skill else "🌪️" if is_wind_skill else "🔥"
        skill_overlay = (
            f'<div class="skill-cinematic {cinematic_class}"><div class="skill-flame">{skill_icon}</div>'
            f'<strong>{active_skill["text"]}</strong><div>戰鬥計時暫停</div></div>'
        )
    elif skill_impact:
        if is_wind_skill:
            impact_text = "勇者造成傷害 -40%"
        else:
            skill_damage = re.search(r"造成\s*([0-9.]+)", active_skill["text"])
            skill_damage_text = skill_damage.group(1) if skill_damage else ""
            impact_text = (
                f"{'雷劫傷害' if is_lightning_skill else '真實傷害'} -{skill_damage_text}"
            )
        skill_overlay = (
            '<div class="skill-aftermath-layer">'
            f'<div class="true-damage-number">{impact_text}</div>'
            '</div>'
        )
    elif skill_flight:
        if is_lightning_skill:
            skill_overlay = (
                '<div class="dragon-skill-layer lightning-skill-layer">'
                '<div class="storm-cloud cloud-left"></div>'
                '<div class="storm-cloud cloud-right"></div>'
                '<svg class="lightning-svg" viewBox="0 0 1000 1000" preserveAspectRatio="none">'
                '<defs><filter id="lightning-glow"><feGaussianBlur stdDeviation="8" result="blur"/>'
                '<feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge></filter></defs>'
                '<path class="lightning-path main-lightning" pathLength="1" d="M535,-30 L470,155 L545,230 L420,390 L505,470 L350,650 L455,705 L315,1010"/>'
                '<path class="lightning-path lightning-branch branch-one" pathLength="1" d="M474,156 L335,260 L245,390"/>'
                '<path class="lightning-path lightning-branch branch-two" pathLength="1" d="M424,390 L620,455 L710,590"/>'
                '<path class="lightning-path lightning-branch branch-three" pathLength="1" d="M353,650 L190,720 L105,870"/>'
                '<path class="lightning-path lightning-branch branch-four" pathLength="1" d="M456,705 L650,760 L785,930"/>'
                '</svg>'
                '<div class="lightning-screen-flash"></div>'
                '<div class="lightning-impact-glow"></div></div>'
            )
        elif is_wind_skill:
            skill_overlay = (
                '<div class="dragon-skill-layer wind-skill-layer">'
                '<div class="wind-cloud wind-cloud-one"></div>'
                '<div class="wind-cloud wind-cloud-two"></div>'
                '<div class="wind-rain-curtain"></div>'
                '<div class="wind-streak streak-one"></div>'
                '<div class="wind-streak streak-two"></div>'
                '<div class="wind-streak streak-three"></div>'
                '<div class="tornado-stage">'
                '<div class="tornado-backwash"></div>'
                '<svg class="tornado-svg" viewBox="0 0 700 1000" preserveAspectRatio="xMidYMid meet">'
                '<defs>'
                '<linearGradient id="windBodyGradient" x1="0" y1="0" x2="1" y2="1">'
                '<stop offset="0" stop-color="#dff9ff" stop-opacity=".88"/>'
                '<stop offset=".28" stop-color="#7899a5" stop-opacity=".75"/>'
                '<stop offset=".60" stop-color="#263c47" stop-opacity=".9"/>'
                '<stop offset="1" stop-color="#bdebf2" stop-opacity=".68"/>'
                '</linearGradient>'
                '<filter id="windRough" x="-30%" y="-20%" width="160%" height="150%">'
                '<feTurbulence type="fractalNoise" baseFrequency=".012 .035" numOctaves="3" seed="8" result="noise">'
                '<animate attributeName="baseFrequency" dur=".65s" values=".012 .035;.020 .055;.012 .035" repeatCount="indefinite"/>'
                '</feTurbulence>'
                '<feDisplacementMap in="SourceGraphic" in2="noise" scale="34" xChannelSelector="R" yChannelSelector="B"/>'
                '</filter>'
                '</defs>'
                '<path class="tornado-body" filter="url(#windRough)" fill="url(#windBodyGradient)" '
                'd="M60 82 C155 14 545 14 640 82 C620 170 565 225 550 325 '
                'C530 440 475 500 454 610 C435 720 400 810 371 938 '
                'C363 976 337 976 329 938 C300 810 265 720 246 610 '
                'C225 500 170 440 150 325 C135 225 80 170 60 82 Z"/>'
                '<g class="tornado-ribbons">'
                '<path d="M72 112 C210 38 525 40 628 125 C518 205 205 215 100 151"/>'
                '<path d="M122 245 C240 181 495 188 566 263 C474 330 225 338 155 285"/>'
                '<path d="M158 378 C252 325 459 330 520 398 C432 460 250 462 190 419"/>'
                '<path d="M207 515 C280 471 425 477 470 535 C399 585 284 590 231 552"/>'
                '<path d="M245 646 C302 612 397 615 431 663 C381 704 300 709 263 680"/>'
                '<path d="M282 770 C318 745 379 748 402 785 C369 817 315 821 294 798"/>'
                '<path d="M314 884 C335 868 371 871 383 897 C362 918 332 920 320 905"/>'
                '</g></svg>'
                '<div class="tornado-ground-shadow"></div>'
                '<div class="tornado-dust dust-far"></div>'
                '<div class="tornado-dust dust-near"></div>'
                '<div class="wind-debris debris-one">◆</div>'
                '<div class="wind-debris debris-two">●</div>'
                '<div class="wind-debris debris-three">▲</div>'
                '<div class="wind-debris debris-four">▰</div>'
                '<div class="wind-debris debris-five">◆</div>'
                '</div><div class="wind-vignette"></div>'
                '</div>'
            )
        else:
            fire_dragon_image = effect_image_data_uri("fire-dragon-strike.webp")
            dragon_visual = (
                f'<img class="eastern-fire-dragon" src="{fire_dragon_image}" alt="火龍斬">'
                if fire_dragon_image else '<div class="fire-dragon-fallback">🐉</div>'
            )
            skill_overlay = f'<div class="dragon-skill-layer">{dragon_visual}</div>'
    if skill_flight:
        arena_class = "battle-arena skill-flight-arena"
    elif skill_impact and not is_wind_skill:
        arena_class = "battle-arena skill-impact-arena"
    else:
        arena_class = "battle-arena"
    st.markdown(
        f"""
        <style>
        .battle-arena {{position:relative;height:270px;margin:14px 0 18px;padding:24px;
          overflow:hidden;border-radius:22px;background:radial-gradient(circle at 50% 20%,#fff9 0 8%,transparent 36%),linear-gradient(#ccecff 0 60%,#8fc96f 60% 66%,#628f48 66%);
          border:2px solid #d8e1ea;display:flex;align-items:flex-end;justify-content:space-between;perspective:900px;isolation:isolate;}}
        .battle-arena:after {{content:"";position:absolute;left:7%;right:7%;bottom:22px;height:34px;background:#18320d33;border-radius:50%;filter:blur(8px);z-index:-1;}}
        .fighter {{position:relative;font-size:88px;line-height:1;text-align:center;transform-style:preserve-3d;filter:drop-shadow(0 12px 7px #0005);animation:idleFloat 1.35s ease-in-out infinite alternate;will-change:transform;}}
        .boss-portrait,.hero-portrait {{width:168px;height:168px;object-fit:cover;border:0;border-radius:0;
          mix-blend-mode:multiply;-webkit-mask-image:radial-gradient(ellipse 52% 58% at 50% 48%,#000 58%,#000d 72%,transparent 100%);
          mask-image:radial-gradient(ellipse 52% 58% at 50% 48%,#000 58%,#000d 72%,transparent 100%);}}
        .boss-fallback {{font-size:100px;line-height:150px;}}
        .hero-fallback {{font-size:100px;line-height:150px;}}
        .fighter span {{display:block;margin-top:10px;font-size:20px;font-weight:700;color:#313442;}}
        .hero-attack {{z-index:3;animation:heroStrike{event_sequence} .62s cubic-bezier(.2,.8,.2,1);}}
        .boss-attack {{z-index:3;animation:bossStrike{event_sequence} .62s cubic-bezier(.2,.8,.2,1);}}
        .hero-attack .hero-portrait,.boss-attack .boss-portrait {{filter:brightness(1.12) saturate(1.18);}}
        .hit-shake .hero-portrait,.hit-shake .boss-portrait {{animation:hitShake{event_sequence} .52s ease-out;}}
        .sword-slash {{position:absolute;z-index:6;right:-105px;top:18px;width:125px;height:125px;border-radius:50%;border-right:12px solid #fff;border-top:7px solid #6de7ff;filter:drop-shadow(0 0 8px #2ecbff);transform:rotate(28deg);animation:swordArc{event_sequence} .55s ease-out forwards;}}
        .claw-hit {{position:absolute;z-index:4;inset:8px 12px 34px;pointer-events:none;
          animation:clawFlash{event_sequence} .65s ease-out forwards;}}
        .claw-hit i {{position:absolute;left:48%;top:8%;width:8px;height:82%;border-radius:8px;
          background:linear-gradient(90deg,#fff,#ff304f 35%,#8b0016);box-shadow:0 0 12px #ff173c;
          transform:rotate(32deg);}}
        .claw-hit i:nth-child(1) {{margin-left:-30px;}}
        .claw-hit i:nth-child(2) {{margin-left:0;}}
        .claw-hit i:nth-child(3) {{margin-left:30px;}}
        .skill-cinematic {{position:absolute;inset:0;z-index:5;display:flex;flex-direction:column;
          align-items:center;justify-content:center;color:white;font-size:26px;text-align:center;
          background:radial-gradient(circle,#ff7a18dd,#8b0000ee);animation:skillFlash .55s ease-in-out infinite alternate;}}
        .skill-flame {{font-size:82px;animation:flameGrow .5s ease-in-out infinite alternate;}}
        .lightning-cinematic {{background:radial-gradient(circle,#8a5cffdd,#17002fee);}}
        .wind-cinematic {{background:radial-gradient(circle at 50% 45%,#55758ddd,#07131fee 72%);}}
        .skill-flight-arena {{background:#000;border-color:#000;box-shadow:none;overflow:visible;perspective:none;}}
        .skill-flight-arena:after {{display:none;}}
        .skill-flight-arena > .fighter {{visibility:hidden;}}
        .dragon-skill-layer {{position:fixed;inset:0;z-index:999999;pointer-events:none;overflow:hidden;background:#000;}}
        .eastern-fire-dragon {{position:absolute;left:100%;top:-42%;width:min(760px,92vw);height:auto;
          max-width:none;filter:drop-shadow(0 0 14px #ff2400) drop-shadow(0 0 36px #ff8500);
          transform-origin:center;animation:dragonRush{event_sequence} 2s linear forwards;will-change:transform,opacity;}}
        .fire-dragon-fallback {{position:absolute;left:100%;top:-20%;font-size:150px;
          animation:dragonRush{event_sequence} 2s linear forwards;}}
        .lightning-skill-layer {{background:#000;}}
        .lightning-svg {{position:absolute;inset:-2% 0 0;width:100%;height:104%;overflow:visible;
          filter:drop-shadow(0 0 7px #fff) drop-shadow(0 0 22px #8a46ff);}}
        .lightning-path {{fill:none;stroke:#f8f3ff;stroke-linecap:round;stroke-linejoin:round;
          filter:url(#lightning-glow);stroke-dasharray:1;stroke-dashoffset:1;
          animation:lightningTrace{event_sequence} 2s cubic-bezier(.12,.72,.25,1) forwards;}}
        .main-lightning {{stroke-width:18;}}
        .lightning-branch {{stroke:#cdafff;stroke-width:8;}}
        .branch-one {{animation-delay:.18s;}} .branch-two {{animation-delay:.32s;}}
        .branch-three {{animation-delay:.46s;}} .branch-four {{animation-delay:.58s;}}
        .storm-cloud {{position:absolute;top:-8%;width:62%;height:30%;border-radius:50%;
          background:radial-gradient(ellipse at center,#695088 0 18%,#291b45 48%,transparent 72%);
          filter:blur(16px);opacity:0;animation:stormCloudIn{event_sequence} 2s ease-out forwards;}}
        .cloud-left {{left:-8%;}} .cloud-right {{right:-8%;animation-delay:.12s;}}
        .lightning-screen-flash {{position:absolute;inset:0;background:#e8dcff;opacity:0;
          animation:lightningScreenFlash{event_sequence} 2s steps(1,end) forwards;}}
        .lightning-bolt {{position:absolute;top:-15%;left:50%;width:18px;height:125%;
          background:linear-gradient(90deg,#6f2cff,#fff 42%,#d7b8ff 62%,#7028ff);
          box-shadow:0 0 18px #9d55ff,0 0 50px #6e20ff,0 0 90px #b279ff;
          clip-path:polygon(38% 0,100% 0,62% 28%,95% 28%,38% 60%,70% 60%,0 100%,28% 65%,0 65%,42% 34%,10% 34%);
          transform-origin:top center;opacity:0;animation:lightningDrop{event_sequence} 2s ease-in forwards;}}
        .side-bolt {{width:9px;filter:blur(.3px);opacity:0;}}
        .left-bolt {{left:37%;transform:rotate(-8deg);animation-delay:.12s;}}
        .right-bolt {{left:63%;transform:rotate(9deg);animation-delay:.22s;}}
        .lightning-impact-glow {{position:absolute;left:50%;bottom:-12%;width:42vw;height:25vh;
          transform:translateX(-50%);border-radius:50%;background:radial-gradient(ellipse,#fff 0 5%,#a55cffaa 22%,transparent 70%);
          opacity:0;animation:lightningGlow{event_sequence} 2s ease-out forwards;}}
        .wind-skill-layer {{background:radial-gradient(circle at 50% 42%,#274957 0,#0d1b24 45%,#020508 88%);}}
        .wind-cloud {{position:absolute;width:75vw;height:35vh;border-radius:50%;filter:blur(24px);
          background:radial-gradient(ellipse,#b4cbd0aa 0 12%,#47657299 35%,transparent 72%);
          opacity:0;animation:windCloudSweep{event_sequence} 2s ease-in-out forwards;}}
        .wind-cloud-one {{left:-55vw;top:5vh;}} .wind-cloud-two {{right:-55vw;bottom:4vh;animation-delay:.16s;}}
        .wind-rain-curtain {{position:absolute;inset:-30% -20%;opacity:0;
          background:repeating-linear-gradient(111deg,transparent 0 24px,#c8f7ff99 25px 27px,transparent 29px 52px);
          filter:blur(.5px);animation:windRain{event_sequence} .32s linear infinite,
          windRainIn{event_sequence} 2s ease-in-out forwards;}}
        .wind-streak {{position:absolute;left:-35%;width:52%;height:8px;border-radius:50%;
          background:linear-gradient(90deg,transparent,#d9fbff,#7cdcec88,transparent);
          box-shadow:0 0 15px #bff8ff;transform:skewX(-28deg);opacity:0;
          animation:windStreakRush{event_sequence} .62s linear infinite;}}
        .streak-one {{top:25%;}} .streak-two {{top:52%;animation-delay:.18s;}}
        .streak-three {{top:76%;animation-delay:.36s;}}
        .tornado-stage {{position:absolute;left:50%;top:1vh;width:min(72vw,650px);height:98vh;
          transform:translateX(-50%);transform-origin:50% 88%;opacity:0;
          animation:tornadoStageIn{event_sequence} 2s ease-in-out forwards;}}
        .tornado-backwash {{position:absolute;left:50%;top:1%;width:105%;height:30%;transform:translateX(-50%);
          border-radius:50%;background:repeating-radial-gradient(ellipse at center,transparent 0 8%,#bfeaf277 10% 12%,transparent 15% 20%);
          filter:blur(5px);animation:backwashSpin{event_sequence} .7s linear infinite;}}
        .tornado-svg {{position:absolute;inset:0;width:100%;height:100%;overflow:visible;
          filter:drop-shadow(0 0 12px #c9f8ff) drop-shadow(0 0 36px #4a8798);}}
        .tornado-body {{opacity:.88;transform-origin:center;animation:tornadoBodyPulse{event_sequence} .42s ease-in-out infinite alternate;}}
        .tornado-ribbons path {{fill:none;stroke:#e8fdff;stroke-linecap:round;stroke-width:24;
          stroke-dasharray:115 42;filter:drop-shadow(0 0 7px #a9efff);opacity:.92;
          transform-box:fill-box;transform-origin:center;animation:tornadoRibbon{event_sequence} .42s linear infinite;}}
        .tornado-ribbons path:nth-child(even) {{stroke:#6fa9b8;stroke-dasharray:76 31;
          animation-direction:reverse;animation-duration:.34s;}}
        .tornado-ribbons path:nth-child(3),.tornado-ribbons path:nth-child(4) {{stroke-width:20;}}
        .tornado-ribbons path:nth-child(5) {{stroke-width:17;}}
        .tornado-ribbons path:nth-child(6) {{stroke-width:14;}}
        .tornado-ribbons path:nth-child(7) {{stroke-width:11;}}
        .tornado-ground-shadow {{position:absolute;left:50%;bottom:0;width:34%;height:5%;transform:translateX(-50%);
          border-radius:50%;background:#000;box-shadow:0 0 28px 16px #7cd7e066;filter:blur(5px);}}
        .tornado-dust {{position:absolute;left:50%;bottom:-1%;height:12%;border:6px solid #b7d4d6;
          border-left-color:transparent;border-right-color:transparent;border-radius:50%;opacity:0;}}
        .dust-far {{width:56%;animation:dustRing{event_sequence} .62s linear infinite;}}
        .dust-near {{width:82%;animation:dustRing{event_sequence} .62s .22s linear infinite reverse;}}
        .wind-debris {{position:absolute;left:50%;top:48%;color:#d7f7ef;font-size:22px;opacity:0;
          text-shadow:0 0 7px #baf8ff;animation:debrisSpiral{event_sequence} .92s linear infinite;}}
        .debris-one {{--rx:230px;--ry:-210px;}} .debris-two {{--rx:-255px;--ry:-70px;animation-delay:.17s;}}
        .debris-three {{--rx:205px;--ry:155px;animation-delay:.34s;}}
        .debris-four {{--rx:-185px;--ry:245px;animation-delay:.51s;}}
        .debris-five {{--rx:280px;--ry:30px;animation-delay:.68s;}}
        .wind-vignette {{position:absolute;inset:0;background:radial-gradient(circle at 50% 50%,transparent 32%,#000b 100%);
          box-shadow:inset 0 0 100px #000;animation:windVignette{event_sequence} 2s ease-in-out forwards;}}
        .skill-aftermath-layer {{position:absolute;inset:0;z-index:10;pointer-events:none;}}
        .true-damage-number {{position:absolute;left:10%;top:20%;font-size:30px;font-weight:900;color:#fff3a0;
          text-shadow:0 2px 2px #500,0 0 10px #ff2700;opacity:0;animation:trueDamage{event_sequence} 1s ease-out forwards;}}
        .skill-impact-arena {{animation:arenaImpact{event_sequence} 1s ease-in-out;}}
        .damage-number {{position:absolute;z-index:8;top:38px;font-size:28px;font-weight:900;color:#fff;text-shadow:0 2px 2px #000,0 0 8px #e00000;animation:damageRise{event_sequence} .85s ease-out forwards;}}
        .damage-on-hero {{left:18%;}} .damage-on-boss {{right:18%;}}
        .critical-number {{font-size:34px;color:#ffe33b;text-shadow:0 2px 2px #5b1800,0 0 12px #ff8a00;}}
        .defeated {{animation:defeatFall{event_sequence} .9s ease-in forwards !important;transform-origin:bottom center;}}
        .hero-enter {{animation:heroEnter{event_sequence} .72s cubic-bezier(.18,.85,.28,1.15) both;}}
        .boss-enter {{animation:bossEnter{event_sequence} .72s cubic-bezier(.18,.85,.28,1.15) both;}}
        @keyframes idleFloat {{from{{transform:translateY(0) rotateX(1deg);}}to{{transform:translateY(-7px) rotateX(-2deg);}}}}
        @keyframes heroEnter{event_sequence} {{0%{{opacity:0;transform:translateX(-95px) translateY(35px) scale(.42) rotateY(55deg);}}65%{{opacity:1;transform:translateX(18px) translateY(-16px) scale(1.12) rotateY(-8deg);}}100%{{transform:translateX(0) translateY(0) scale(1) rotateY(0);}}}}
        @keyframes bossEnter{event_sequence} {{0%{{opacity:0;transform:translateX(95px) translateY(35px) scale(.42) rotateY(-55deg);}}65%{{opacity:1;transform:translateX(-18px) translateY(-16px) scale(1.12) rotateY(8deg);}}100%{{transform:translateX(0) translateY(0) scale(1) rotateY(0);}}}}
        @keyframes heroStrike{event_sequence} {{0%{{transform:translateX(0) rotate(0) scale(1);}}42%{{transform:translateX(145px) translateY(-12px) rotate(-9deg) scale(1.13);}}62%{{transform:translateX(125px) rotate(5deg) scale(1.08);}}100%{{transform:translateX(0);}}}}
        @keyframes bossStrike{event_sequence} {{0%{{transform:translateX(0) rotate(0) scale(1);}}42%{{transform:translateX(-145px) translateY(-18px) rotate(9deg) scale(1.15);}}62%{{transform:translateX(-120px) rotate(-5deg) scale(1.08);}}100%{{transform:translateX(0);}}}}
        @keyframes swordArc{event_sequence} {{0%{{opacity:0;transform:rotate(-30deg) scale(.35);}}35%{{opacity:1;transform:rotate(35deg) scale(1.2);}}100%{{opacity:0;transform:rotate(95deg) scale(1.45);}}}}
        @keyframes damageRise{event_sequence} {{0%{{opacity:0;transform:translateY(35px) scale(.5);}}25%{{opacity:1;transform:translateY(0) scale(1.2);}}100%{{opacity:0;transform:translateY(-50px) scale(.9);}}}}
        @keyframes hitShake{event_sequence} {{0%,100%{{transform:translateX(0);filter:none;}}18%{{transform:translateX(-11px);filter:sepia(1) saturate(8) hue-rotate(315deg) brightness(1.35);}}38%{{transform:translateX(9px);}}58%{{transform:translateX(-6px);filter:sepia(1) saturate(8) hue-rotate(315deg);}}78%{{transform:translateX(4px);}}}}
        @keyframes defeatFall{event_sequence} {{to{{transform:translateY(35px) rotate(78deg) scale(.82);opacity:.35;filter:grayscale(1);}}}}
        @keyframes clawFlash{event_sequence} {{0%{{opacity:0;transform:scale(1.7);}}25%{{opacity:1;transform:scale(1);}}100%{{opacity:0;transform:scale(.92);}}}}
        @keyframes skillFlash {{to{{filter:brightness(1.35);}}}}
        @keyframes flameGrow {{to{{transform:scale(1.35) rotate(8deg);}}}}
        @keyframes dragonRush{event_sequence} {{0%{{opacity:0;transform:translate(10%,-12%) scale(.58) rotate(-8deg);}}8%{{opacity:1;}}48%{{opacity:1;transform:translate(-105%,58%) scale(1.05) rotate(-8deg);}}88%{{opacity:1;transform:translate(-205%,138%) scale(1.22) rotate(-8deg);}}100%{{opacity:0;transform:translate(-235%,158%) scale(1.3) rotate(-8deg);}}}}
        @keyframes lightningDrop{event_sequence} {{0%{{opacity:0;transform:translateY(-105%) scaleY(.25);}}12%{{opacity:1;}}48%{{opacity:1;transform:translateY(0) scaleY(1);}}62%{{opacity:.35;}}70%{{opacity:1;filter:brightness(1.8);}}100%{{opacity:0;transform:translateY(8%) scaleY(1.04);}}}}
        @keyframes lightningTrace{event_sequence} {{0%{{stroke-dashoffset:1;opacity:0;}}12%{{opacity:1;}}52%{{stroke-dashoffset:0;opacity:1;}}68%{{opacity:.35;}}76%{{opacity:1;stroke-width:24;}}100%{{stroke-dashoffset:0;opacity:0;}}}}
        @keyframes stormCloudIn{event_sequence} {{0%{{opacity:0;transform:translateY(-35%) scale(.7);}}25%{{opacity:.8;}}72%{{opacity:1;transform:translateY(10%) scale(1.25);}}100%{{opacity:0;transform:translateY(18%) scale(1.4);}}}}
        @keyframes lightningScreenFlash{event_sequence} {{0%,43%,55%,72%,100%{{opacity:0;}}45%,57%,74%{{opacity:.52;}}}}
        @keyframes lightningGlow{event_sequence} {{0%,35%{{opacity:0;transform:translateX(-50%) scale(.2);}}52%{{opacity:1;transform:translateX(-50%) scale(1.4);}}100%{{opacity:0;transform:translateX(-50%) scale(2);}}}}
        @keyframes windCloudSweep{event_sequence} {{0%{{opacity:0;transform:translateX(0) scale(.6);}}18%{{opacity:.85;}}70%{{opacity:1;transform:translateX(70vw) scale(1.25);}}100%{{opacity:0;transform:translateX(115vw) scale(1.45);}}}}
        @keyframes windRain{event_sequence} {{from{{transform:translate(0,-5%);}}to{{transform:translate(-80px,14%);}}}}
        @keyframes windRainIn{event_sequence} {{0%,100%{{opacity:0;}}15%,80%{{opacity:.5;}}}}
        @keyframes windStreakRush{event_sequence} {{0%{{left:-45%;opacity:0;}}15%{{opacity:1;}}100%{{left:115%;opacity:0;}}}}
        @keyframes tornadoStageIn{event_sequence} {{0%{{opacity:0;transform:translateX(-50%) scale(.45,.15) rotate(-4deg);}}18%{{opacity:.9;}}55%{{opacity:1;transform:translateX(-50%) scale(1.04,1) rotate(2deg);}}82%{{opacity:1;transform:translateX(-50%) scale(.98,1.03) rotate(-1deg);}}100%{{opacity:0;transform:translateX(-50%) scale(1.16,1.08) rotate(3deg);}}}}
        @keyframes backwashSpin{event_sequence} {{from{{transform:translateX(-50%) rotate(0deg) scaleX(1);}}to{{transform:translateX(-50%) rotate(360deg) scaleX(1.08);}}}}
        @keyframes tornadoBodyPulse{event_sequence} {{from{{transform:skewX(-1.5deg) scaleX(.97);filter:brightness(.9);}}to{{transform:skewX(2deg) scaleX(1.04);filter:brightness(1.2);}}}}
        @keyframes tornadoRibbon{event_sequence} {{from{{stroke-dashoffset:0;transform:translateX(-8px);}}to{{stroke-dashoffset:-157;transform:translateX(8px);}}}}
        @keyframes dustRing{event_sequence} {{0%{{opacity:0;transform:translateX(-50%) scale(.35) rotate(0);}}20%{{opacity:.85;}}100%{{opacity:0;transform:translateX(-50%) scale(1.5) rotate(360deg);}}}}
        @keyframes debrisSpiral{event_sequence} {{0%{{opacity:0;transform:translate(-50%,-50%) rotate(0) translate(12px,0) scale(.35);}}18%{{opacity:1;}}68%{{opacity:1;transform:translate(-50%,-50%) rotate(470deg) translate(var(--rx),var(--ry)) scale(1.15);}}100%{{opacity:0;transform:translate(-50%,-50%) rotate(720deg) translate(var(--rx),var(--ry)) scale(.65);}}}}
        @keyframes windVignette{event_sequence} {{0%,100%{{opacity:0;}}22%,78%{{opacity:1;}}}}
        @keyframes trueDamage{event_sequence} {{0%{{opacity:0;transform:translateY(25px) scale(.5);}}18%{{opacity:1;transform:translateY(0) scale(1.25);}}100%{{opacity:0;transform:translateY(-38px) scale(.95);}}}}
        @keyframes arenaImpact{event_sequence} {{0%,100%{{transform:translate(0,0);filter:none;}}8%{{transform:translate(-12px,6px);filter:brightness(1.5);}}18%{{transform:translate(12px,-6px);}}30%{{transform:translate(-9px,-5px);}}44%{{transform:translate(8px,5px);}}62%{{transform:translate(-5px,0);filter:brightness(1.15);}}}}
        @media (max-width:600px) {{
          .battle-arena {{height:250px;padding:14px;}}
          .eastern-fire-dragon {{width:165vw;left:105%;top:-35%;}}
          .true-damage-number {{left:5%;top:14%;font-size:25px;}}
          .tornado-stage {{width:96vw;height:94vh;top:3vh;}}
          .tornado-ribbons path {{stroke-width:18;}}
        }}
        </style>
        <div class="{arena_class}">
          <div class="{hero_class}">{hero_visual}{hero_claws}{sword_slash}<span>勇者</span></div>
          <div class="{boss_class}">{boss_visual}{boss_claws}<span>{boss_config['name']}</span></div>
          {damage_overlay}
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
        image_col, info_col, button_col = st.columns([0.75, 4, 1.35], vertical_alignment="center")
        image_path = Path(__file__).parent / "assets" / "bosses" / config["image"]
        if image_path.exists():
            image_col.image(image_path, width=72)
        else:
            image_col.markdown("## 🐉")
        info_col.markdown(f"### {label}｜{config['name']}")
        info_col.write(
            f"**HP：{config['hp']}**　｜　"
            f"**攻擊：每 {config['interval']:g} 秒造成 {config['damage']} 傷害**"
        )
        abilities = []
        if config.get("critical_rate"):
            abilities.append(
                f"暴擊率 {config['critical_rate']:.0%}（每第 5 次攻擊必定暴擊，造成 1.5 倍傷害）"
            )
        if config.get("defense_reduction"):
            abilities.append(
                f"被動：戰鬥期間勇者防禦降低 {config['defense_reduction']}（最低為0；傷害減免仍有效）"
            )
        if config.get("hero_speed_reduction"):
            abilities.append(
                f"被動：戰鬥期間勇者攻擊速度降低 {config['hero_speed_reduction']:.3f} 次／秒（最低保留0.100次／秒）"
            )
        if config.get("hero_damage_reduction"):
            abilities.append(
                f"技能「{config['skill']}」：戰鬥開始立即發動，勇者造成的傷害降低 "
                f"{config['hero_damage_reduction']:.0%}；可與對菁英BOSS傷害加成互相抵銷"
            )
        if config.get("skill"):
            if config.get("skill_at_start"):
                pass
            elif config.get("skill_hp_threshold") is not None:
                threshold_damage = config.get("true_damage", config.get("skill_damage", 0))
                abilities.append(
                    f"技能「{config['skill']}」：血量首次低於 {config['skill_hp_threshold']:.0%} 時，"
                    f"造成 {threshold_damage:g} {'真實傷害（無視防禦與傷害減免）' if config.get('true_damage') is not None else '傷害（可被傷害減免抵銷）'}"
                )
            else:
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
            force_top_before_navigation()
            st.session_state.selected_boss_type = boss_type
            st.session_state.scroll_boss_to_top = True
            st.session_state.screen = "boss_ready"
            st.rerun()


init_db()
migrate_all_profiles_fixed_values()
migrate_all_profiles_four_star_names()
if not st.session_state.get("active_player") and st.query_params.get("resume"):
    if student_login_is_open():
        resumed_player = verify_short_login_token(st.query_params.get("resume"))
        if resumed_player:
            st.session_state.active_player = resumed_player
            st.session_state.screen = "home"
        else:
            clear_short_login()
    else:
        # 休息時段不可透過5分鐘登入憑證繞過限制。
        clear_short_login()
if USE_POSTGRES and not ADMIN_PIN_SECRET:
    st.error("公開版尚未設定 ADMIN_PIN，已停止登入以保護老師後台。")
    st.info("請到 Streamlit App settings → Secrets 設定 ADMIN_PIN 與 DATABASE_URL。")
    st.stop()
if not ADMIN_PIN_SECRET and setting_get("admin_pin_hash") is None:
    st.session_state.screen = "bootstrap"
elif st.session_state.screen == "bootstrap":
    st.session_state.screen = "login"
if st.session_state.screen == "inventory":
    st.session_state.screen = (
        "gallery" if st.session_state.get("inventory_view") == "gallery" else "backpack"
    )

# 手機直立版只微調功能頁的大標題；transform 不會推動下方其他內容。
if st.session_state.screen not in {"login", "bootstrap", "boss_watch"}:
    st.markdown(
        """
        <style>
        /* 橫屏與電腦版：移除 Streamlit 預設的大段頂部留白，
           只把整個內容區上移，不改變各元件彼此的相對位置。 */
        @media (min-width: 901px), (orientation: landscape) {
            [data-testid="stMainBlockContainer"],
            .stMainBlockContainer,
            .block-container {
                padding-top: 0.35rem !important;
            }
        }
        @media (max-width: 900px) and (orientation: portrait) {
            [data-testid="stMainBlockContainer"] h1:first-of-type,
            .stMainBlockContainer h1:first-of-type,
            .block-container h1:first-of-type {
                font-size: 2.55rem !important;
                transform: translateY(0.45rem);
                transform-origin: left top;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

# Streamlit 的 keyed tabs 在切換獨立頁面時，偶爾會短暫沿用上一頁的分頁列。
# 僅在真正需要分頁的畫面顯示 tabs，避免背包分類殘留在首頁或其他功能頁。
tab_screens = {"login", "backpack", "daily_tasks", "rankings"}
if st.session_state.screen not in tab_screens:
    st.markdown(
        """
        <style>
        [data-testid="stTabs"] { display: none !important; }
        </style>
        """,
        unsafe_allow_html=True,
    )

active_chapter_id = st.session_state.get("selected_chapter", "1")
if active_chapter_id not in CHAPTERS:
    active_chapter_id = "1"
if st.session_state.screen not in {"boss_ready", "boss_watch"}:
    if st.session_state.screen in {"menu", "quiz", "quiz_result", "boss_result"}:
        active_chapter = CHAPTERS[active_chapter_id]
        st.title(f"⚔️ 數學冒險：{active_chapter['number']}－{active_chapter['name']}")
    else:
        st.title("⚔️ 數學冒險")

home_return_screens = {
    "character_stats", "menu", "backpack", "gallery", "rankings", "economy", "daily_tasks",
    "announcements", "feedback", "quiz", "quiz_result", "sweep_result", "boss_ready", "boss_result",
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
    apply_login_background()
    role = st.radio("登入身分", ["學生", "老師"], horizontal=True)
    if role == "學生":
        login_open = student_login_is_open()
        if not login_open:
            render_student_login_closed_notice()
        login_tab, register_tab = st.tabs(["登入", "建立新勇者"])
        with login_tab:
            with st.container(key="login_fields_row"):
                code_col, pin_col = st.columns(2, vertical_alignment="bottom")
                code = code_col.text_input("學生代碼", placeholder="例如 A001").strip().upper()
                pin = pin_col.text_input("6位PIN", type="password", max_chars=6, key="login_pin")
            with st.container(key="login_actions_row"):
                remember_col, login_col = st.columns(2, vertical_alignment="center")
                keep_signed_in = remember_col.checkbox(
                    "5分鐘保持登入", value=True, key="keep_student_signed_in"
                )
                login_pressed = login_col.button(
                    "學生登入", type="primary", disabled=not login_open
                )
            if login_pressed:
                if not student_login_is_open():
                    render_student_login_closed_notice()
                else:
                    valid, result = verify_student(code, pin)
                    if valid:
                        st.session_state.active_player = result
                        if keep_signed_in:
                            remember_short_login(result)
                        else:
                            clear_short_login()
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
                if st.button(
                    "建立新勇者", type="primary", use_container_width=True,
                    disabled=not login_open,
                ):
                    if not student_login_is_open():
                        render_student_login_closed_notice()
                        st.stop()
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
    st.session_state.pop("teacher_admin_target", None)
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
    admin_section = st.selectbox(
        "選擇管理功能",
        ["建立學生", "帳號管理", "測試進度", "答題紀錄", "戰鬥模擬器", "公告管理", "遊戲反饋"],
        key="admin_section",
    )
    if admin_section == "建立學生":
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
    if admin_section == "帳號管理":
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
                    f"第四章一般BOSS：{detail_profile.get('chapter4_boss_wins', 0)}次",
                    f"第四章菁英BOSS：{detail_profile.get('chapter4_elite_boss_wins', 0)}次",
                    f"第五章一般BOSS：{detail_profile.get('chapter5_boss_wins', 0)}次",
                    f"第五章菁英BOSS：{detail_profile.get('chapter5_elite_boss_wins', 0)}次",
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
                    unit_key = str(item.get("unit", ""))
                    if item.get("achievement"):
                        if unit_key.endswith("-elite") and source_id in CHAPTERS:
                            source = f"成就／{CHAPTERS[source_id]['number']}菁英BOSS"
                        elif source_id in CHAPTERS:
                            source = f"成就／{CHAPTERS[source_id]['number']}"
                        else:
                            source = "成就"
                    else:
                        source = CHAPTERS[source_id]["number"] if source_id in CHAPTERS else "其他"
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
    if admin_section == "測試進度":
        st.write("### BOSS通關進度")
        st.caption("點擊章節名稱展開該章BOSS排名，再點一次即可收合。")
        opened_chapter = st.session_state.get("admin_progress_chapter")
        for chapter_id, chapter in CHAPTERS.items():
            is_open = opened_chapter == chapter_id
            chapter_label = f"{'▼' if is_open else '▶'} {chapter['number']}｜{chapter['name']} BOSS"
            st.button(
                chapter_label,
                key=f"admin_progress_toggle_{chapter_id}",
                use_container_width=True,
                on_click=toggle_admin_progress_chapter,
                args=(chapter_id,),
            )
            if is_open:
                for boss_type, boss_label in (("normal", "一般BOSS"), ("elite", "菁英BOSS")):
                    boss_name = BOSS_CONFIGS[f"{chapter_id}_{boss_type}"]["name"]
                    st.write(f"#### {boss_label}｜{boss_name} 最佳排名")
                    boss_rows = ranking_rows(
                        boss_type, chapter_id, include_private_identity=True
                    )
                    if boss_rows:
                        render_ranking(boss_rows)
                    else:
                        st.info(f"目前尚無{boss_label}通關紀錄。")

    if admin_section == "答題紀錄":
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
        else:
            st.info("目前尚無答題紀錄。")
    if admin_section == "公告管理":
        st.write("### 📢 公告管理")
        if st.session_state.get("admin_announcement_notice"):
            st.success(st.session_state.pop("admin_announcement_notice"))
        with st.form("create_announcement_form", clear_on_submit=True):
            announcement_title = st.text_input("公告標題", max_chars=80)
            announcement_content = st.text_area(
                "公告內容", height=220, max_chars=3000,
                placeholder="輸入要讓所有學生看到的公告內容……",
            )
            announcement_submitted = st.form_submit_button(
                "發布公告", type="primary", use_container_width=True
            )
        if announcement_submitted:
            if not announcement_title.strip() or not announcement_content.strip():
                st.warning("公告標題與內容都必須填寫。")
            else:
                create_announcement(announcement_title, announcement_content)
                st.success("公告已發布。")
                st.rerun()
        announcements = announcement_rows()
        if announcements:
            st.write("### 已建立的公告")
            for announcement in announcements:
                status = "發布中" if announcement["is_active"] else "已停用"
                with st.expander(
                    f"{announcement['title']}｜{status}｜{announcement['created_at_text']}"
                ):
                    render_announcement_content(announcement["content"])
                    st.divider()
                    st.write("#### 編輯這則公告")
                    with st.form(f"edit_announcement_{announcement['id']}"):
                        edited_title = st.text_input(
                            "公告標題", value=announcement["title"], max_chars=80,
                            key=f"edit_announcement_title_{announcement['id']}",
                        )
                        edited_content = st.text_area(
                            "公告內容", value=announcement["content"], height=220,
                            max_chars=3000,
                            key=f"edit_announcement_content_{announcement['id']}",
                        )
                        save_announcement_edit = st.form_submit_button(
                            "儲存修改並啟用", type="primary", use_container_width=True
                        )
                    if save_announcement_edit:
                        if not edited_title.strip() or not edited_content.strip():
                            st.warning("公告標題與內容都必須填寫。")
                        else:
                            update_and_activate_announcement(
                                announcement["id"], edited_title, edited_content
                            )
                            st.session_state.admin_announcement_notice = (
                                f"公告「{edited_title.strip()}」已更新並重新啟用。"
                            )
                            st.rerun()
                    action_col, confirm_col, delete_col = st.columns([1, 1.2, 1])
                    if action_col.button(
                        "停用" if announcement["is_active"] else "重新發布",
                        key=f"toggle_announcement_{announcement['id']}",
                        use_container_width=True,
                    ):
                        set_announcement_active(
                            announcement["id"], not bool(announcement["is_active"])
                        )
                        st.rerun()
                    confirm_delete = confirm_col.checkbox(
                        "確認永久刪除", key=f"confirm_announcement_{announcement['id']}"
                    )
                    if delete_col.button(
                        "刪除", key=f"delete_announcement_{announcement['id']}",
                        disabled=not confirm_delete, use_container_width=True,
                    ):
                        delete_announcement(announcement["id"])
                        st.rerun()
        else:
            st.info("目前尚未建立公告。")
    if admin_section == "戰鬥模擬器":
        st.write("### ⚔️ 學生戰鬥模擬器")
        st.info("此功能只讀取學生目前的等級與已穿戴裝備；不會修改通關紀錄、排名、經驗值、獎勵或學生資料。")
        simulator_students = student_rows()
        if not simulator_students:
            st.warning("目前沒有可供模擬的學生帳號。")
        else:
            student_options = {
                f"{row['學生代碼']}｜{row['正式姓名']}｜{row['勇者名稱']}": row["學生代碼"]
                for row in simulator_students
            }
            simulator_student_label = st.selectbox(
                "選擇學生",
                list(student_options),
                key="battle_simulator_student",
            )
            simulator_chapter = st.selectbox(
                "選擇章節",
                list(CHAPTERS),
                format_func=lambda chapter_id: (
                    f"{CHAPTERS[chapter_id]['number']}｜{CHAPTERS[chapter_id]['name']}"
                ),
                key="battle_simulator_chapter",
            )
            simulator_boss_type = st.radio(
                "選擇 BOSS",
                ["normal", "elite"],
                format_func=lambda boss_type: (
                    f"{'普通' if boss_type == 'normal' else '菁英'} BOSS｜"
                    f"{BOSS_CONFIGS[f'{simulator_chapter}_{boss_type}']['name']}"
                ),
                horizontal=True,
                key="battle_simulator_boss_type",
            )
            if st.button("開始唯讀模擬", type="primary", use_container_width=True):
                simulator_code = student_options[simulator_student_label]
                simulator_profile = student_learning_detail(simulator_code)
                if simulator_profile is None:
                    st.error("找不到這位學生的資料，請重新整理後再試一次。")
                else:
                    simulator_stats = player_stats(simulator_profile)
                    simulator_config = BOSS_CONFIGS[
                        f"{simulator_chapter}_{simulator_boss_type}"
                    ]
                    try:
                        simulator_result = simulate_battle(
                            simulator_stats,
                            simulator_boss_type,
                            simulator_chapter,
                        )
                    except RuntimeError as error:
                        st.error(f"模擬失敗：{error}")
                    else:
                        st.write("#### 學生目前能力")
                        stat_columns = st.columns(5)
                        stat_columns[0].metric("等級", f"Lv{simulator_profile['level']}")
                        stat_columns[1].metric("HP", f"{simulator_stats['hp']:.1f}")
                        stat_columns[2].metric("攻擊", f"{simulator_stats['attack']:.1f}")
                        stat_columns[3].metric("防禦", f"{simulator_stats['defense']:.1f}")
                        stat_columns[4].metric("攻速", f"{simulator_stats['attack_speed']:.2f}/秒")
                        special_parts = []
                        special_labels = {
                            "boss_hp_reduction": "菁英BOSS初始血量降低",
                            "first_hit_percent": "第一擊額外扣除菁英BOSS血量",
                            "boss_damage_pct": "對菁英BOSS傷害",
                            "damage_reduction_pct": "受到傷害降低",
                            "critical_rate": "暴擊率",
                            "critical_damage": "暴擊傷害加成",
                            "shield_pct": "開場護盾",
                            "boss_attack_slow_pct": "菁英BOSS攻擊減速",
                        }
                        for stat_key, label in special_labels.items():
                            if simulator_stats[stat_key] > 0:
                                special_parts.append(
                                    f"{label} {simulator_stats[stat_key] * 100:.0f}%"
                                )
                        st.caption(
                            "特殊能力：" + ("｜".join(special_parts) if special_parts else "無")
                        )

                        simulator_events = simulator_result["events"]
                        first_event = simulator_events[0]
                        last_event = simulator_events[-1]
                        hero_hits = sum(
                            event["text"].startswith("勇者第") for event in simulator_events
                        )
                        boss_hits = sum(
                            event["text"].startswith("BOSS第") for event in simulator_events
                        )
                        skill_hits = sum(
                            event["text"].startswith("BOSS施放技能")
                            for event in simulator_events
                        )
                        st.write("#### 模擬結果")
                        if simulator_result["victory"]:
                            st.success(f"模擬獲勝，戰鬥時間 {simulator_result['duration']:.2f} 秒。")
                        else:
                            st.error(f"模擬戰敗，戰鬥時間 {simulator_result['duration']:.2f} 秒。")
                        result_columns = st.columns(4)
                        result_columns[0].metric(
                            "勇者剩餘 HP",
                            f"{last_event['player_hp']:.1f} / {first_event['player_hp']:.1f}",
                        )
                        result_columns[1].metric(
                            "BOSS 剩餘 HP",
                            f"{last_event['boss_hp']:.1f} / {first_event['boss_hp']:.1f}",
                        )
                        result_columns[2].metric("勇者攻擊次數", hero_hits)
                        result_columns[3].metric("BOSS攻擊／技能", f"{boss_hits}／{skill_hits}")
                        st.caption(
                            f"{simulator_config['name']}：原始 HP {simulator_config['hp']}、"
                            f"攻擊 {simulator_config['damage']}、每 {simulator_config['interval']:g} 秒攻擊一次。"
                        )
                        st.write("#### 完整戰鬥明細")
                        st.dataframe(
                            [
                                {
                                    "時間": f"{event['time']:.2f} 秒",
                                    "事件": event["text"],
                                    "勇者 HP": round(event["player_hp"], 1),
                                    "BOSS HP": round(event["boss_hp"], 1),
                                }
                                for event in simulator_events
                            ],
                            hide_index=True,
                            use_container_width=True,
                        )

    if admin_section == "遊戲反饋":
        st.write("### 學生遊戲反饋")
        if st.session_state.get("admin_reply_notice"):
            st.success(st.session_state.pop("admin_reply_notice"))
        feedback_rows = game_feedback_rows()
        if feedback_rows:
            feedback_counts = {}
            for feedback_row in feedback_rows:
                category = feedback_row["問題分類"]
                feedback_counts[category] = feedback_counts.get(category, 0) + 1
            st.write("#### 問題分類統計")
            st.dataframe(
                [
                    {"問題分類": category, "回饋數量": count}
                    for category, count in sorted(
                        feedback_counts.items(), key=lambda item: (-item[1], item[0])
                    )
                ],
                hide_index=True,
                use_container_width=True,
            )
            category_options = ["全部"] + sorted({row["問題分類"] for row in feedback_rows})
            selected_feedback_category = st.selectbox(
                "問題分類篩選", category_options, key="admin_feedback_category"
            )
            visible_feedback = feedback_rows
            if selected_feedback_category != "全部":
                visible_feedback = [
                    row for row in feedback_rows
                    if row["問題分類"] == selected_feedback_category
                ]
            st.caption(f"目前顯示 {len(visible_feedback)} 則回饋，最新回饋排在最上方。")
            st.dataframe(visible_feedback, hide_index=True, use_container_width=True)
            feedback_choices = {
                f"#{row['編號']}｜{row['正式姓名']}｜{row['問題分類']}｜{row['回覆狀態']}": row
                for row in visible_feedback
            }
            selected_feedback_label = st.selectbox(
                "選擇要回覆的反饋", list(feedback_choices), key="admin_feedback_reply_target"
            )
            selected_feedback = feedback_choices[selected_feedback_label]
            st.caption("學生問題：" + selected_feedback["回饋內容"])
            with st.form("admin_feedback_reply_form", clear_on_submit=True):
                reply_message = st.text_area(
                    "老師回覆", placeholder="輸入要寄到勇者信箱的內容……", max_chars=2000
                )
                st.caption("如需補發獎勵，可填寫附件；沒有則保持為0。")
                reward_cols = st.columns(3)
                reward_coins = reward_cols[0].number_input("金幣", min_value=0, step=100)
                reward_tickets = reward_cols[1].number_input("擊殺券", min_value=0, step=1)
                reward_stones = reward_cols[2].number_input("融煉石", min_value=0, step=1)
                reply_submitted = st.form_submit_button(
                    "寄出回覆", type="primary", use_container_width=True
                )
            if reply_submitted:
                if not reply_message.strip():
                    st.warning("請先輸入回覆內容。")
                else:
                    reward = {
                        "coins": int(reward_coins),
                        "sweep_tickets": int(reward_tickets),
                        "smelting_stones": int(reward_stones),
                    }
                    reward = {key: value for key, value in reward.items() if value > 0}
                    send_mail(
                        selected_feedback["學生代碼"],
                        f"老師回覆｜{selected_feedback['問題分類']}",
                        reply_message,
                        reward or None,
                    )
                    mark_feedback_replied(selected_feedback["編號"])
                    st.session_state.admin_reply_notice = "回覆已寄到學生的勇者信箱，該筆反饋已標示為已回覆。"
                    st.rerun()
        else:
            st.info("目前還沒有學生送出遊戲反饋。")
    if st.button("登出管理後台"):
        st.session_state.admin_authenticated = False
        st.session_state.created_account = None
        st.session_state.screen = "login"
        st.rerun()

elif st.session_state.screen == "home":
    scroll_page_to_top("scroll_home_after_avatar")
    st.markdown('<div id="home-profile-start"></div>', unsafe_allow_html=True)
    components.html(
        """
        <script>
        const removeStaleHomeButtons = () => {
            const doc = parent.document;
            const marker = doc.getElementById('home-profile-start');
            if (!marker) return;
            const markerTop = marker.getBoundingClientRect().top;
            doc.querySelectorAll('button').forEach(button => {
                const rect = button.getBoundingClientRect();
                if (rect.bottom > 0 && rect.top < markerTop - 2) {
                    const row = button.closest('[data-testid="stHorizontalBlock"]');
                    const element = row || button.closest('[data-testid="stElementContainer"]');
                    if (element && !button.closest('header[data-testid="stHeader"]')) element.remove();
                }
            });
        };
        [0, 40, 100, 220, 450, 800, 1300].forEach(delay => setTimeout(removeStaleHomeButtons, delay));
        </script>
        """,
        height=0,
        scrolling=False,
    )
    profile = get_profile()
    if sync_daily_tasks(profile):
        save_profile(profile)
    if profile.get("retro_reward_notice"):
        for notice in profile["retro_reward_notice"]:
            send_mail(
                st.session_state.active_player, "系統補發通知", notice,
                claimed=True,
            )
        st.success("📬 系統補發內容已收進勇者信箱；獎勵先前已直接入帳。")
        profile["retro_reward_notice"] = []
        save_profile(profile)

    with st.container(key="home_name_money"):
        name_col, money_col = st.columns([4, 2], vertical_alignment="center")
        title_prefix = f"「{profile['equipped_title']}」" if profile.get("equipped_title") else ""
        name_col.subheader(f"{title_prefix}{profile['name']}")
        money_col.markdown(f"### 金幣 🪙 {profile.get('coins', 0)}")
    render_compact_avatar_editor(profile)

    st.markdown(
        """
        <style>
        @media (max-width: 768px) and (orientation: portrait) {
          .st-key-home_name_money [data-testid="stHorizontalBlock"] {display:flex !important;flex-direction:row !important;flex-wrap:nowrap !important;gap:.3rem !important;}
          .st-key-home_name_money [data-testid="stColumn"]:first-child {min-width:0 !important;width:65% !important;max-width:65% !important;flex:0 0 65% !important;}
          .st-key-home_name_money [data-testid="stColumn"]:last-child {min-width:0 !important;width:35% !important;max-width:35% !important;flex:0 0 35% !important;}
          .st-key-home_name_money h3 {font-size:1.15rem !important;white-space:normal !important;}
          .st-key-home_avatar_summary [data-testid="stHorizontalBlock"] {display:flex !important;flex-direction:row !important;flex-wrap:nowrap !important;gap:.25rem !important;align-items:flex-start !important;}
          .st-key-home_avatar_summary [data-testid="stColumn"] {min-width:0 !important;padding:0 !important;}
          .st-key-home_avatar_summary [data-testid="stColumn"]:nth-child(1) {width:28% !important;max-width:28% !important;flex:0 0 28% !important;}
          .st-key-home_avatar_summary [data-testid="stColumn"]:nth-child(2) {width:37% !important;max-width:37% !important;flex:0 0 37% !important;}
          .st-key-home_avatar_summary [data-testid="stColumn"]:nth-child(3) {width:35% !important;max-width:35% !important;flex:0 0 35% !important;}
          .st-key-home_avatar_summary button {padding:.3rem .08rem !important;font-size:.7rem !important;white-space:normal !important;}
          .st-key-home_avatar_summary p {font-size:.72rem !important;line-height:1.2 !important;}
          .st-key-home_nav_row_1,
          .st-key-home_nav_row_2,
          .st-key-home_nav_row_3 {width:100% !important;max-width:100% !important;overflow:hidden !important;}
          .st-key-home_nav_row_1 [data-testid="stHorizontalBlock"],
          .st-key-home_nav_row_2 [data-testid="stHorizontalBlock"],
          .st-key-home_nav_row_3 [data-testid="stHorizontalBlock"] {
            display:flex !important;flex-direction:row !important;flex-wrap:nowrap !important;
            width:100% !important;max-width:100% !important;gap:.2rem !important;
          }
          .st-key-home_nav_row_1 [data-testid="stColumn"],
          .st-key-home_nav_row_2 [data-testid="stColumn"],
          .st-key-home_nav_row_3 [data-testid="stColumn"] {
            min-width:0 !important;width:calc(25% - .15rem) !important;
            max-width:calc(25% - .15rem) !important;flex:0 0 calc(25% - .15rem) !important;
            padding:0 !important;
          }
          .st-key-home_nav_row_1 button,
          .st-key-home_nav_row_2 button,
          .st-key-home_nav_row_3 button {
            width:100% !important;padding:.35rem .05rem !important;font-size:.72rem !important;
            line-height:1.15 !important;white-space:normal !important;min-height:2.8rem !important;
          }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    with st.container(key="home_nav_row_1"):
        nav1 = st.columns(4)
    with st.container(key="home_nav_row_2"):
        nav2 = st.columns(4)
    with st.container(key="home_nav_row_3"):
        nav3 = st.columns(4)

    if nav1[0].button("🧙 角色能力", use_container_width=True):
        st.session_state.screen = "character_stats"
        st.rerun()
    if nav1[1].button("🗺️ 關卡", use_container_width=True):
        st.session_state.scroll_menu_to_top = True
        st.session_state.screen = "menu"
        st.rerun()
    if nav1[2].button("🎒 背包", use_container_width=True):
        st.session_state.scroll_inventory_to_top = True
        st.session_state.screen = "backpack"
        st.rerun()
    if nav1[3].button("📖 圖鑑", use_container_width=True):
        st.session_state.scroll_inventory_to_top = True
        st.session_state.screen = "gallery"
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
    nav3[0].button("🥚 寵物召喚｜尚未開放", disabled=True, use_container_width=True)
    if nav3[1].button("💬 問題回報", use_container_width=True):
        st.session_state.scroll_feedback_to_top = True
        st.session_state.screen = "feedback"
        st.rerun()
    mail_count = unread_mail_count(st.session_state.active_player)
    mail_label = f"📬 勇者信箱（{mail_count}）" if mail_count else "📭 勇者信箱"
    if nav3[2].button(mail_label, use_container_width=True):
        st.session_state.scroll_mailbox_to_top = True
        st.session_state.screen = "mailbox"
        st.rerun()

    if st.session_state.active_player == "__TEACHER__":
        teacher_admin_target = st.selectbox(
            "返回老師管理後台",
            ["建立學生", "帳號管理", "測試進度", "答題紀錄", "戰鬥模擬器", "公告管理", "遊戲反饋"],
            index=None,
            placeholder="返回老師管理後台",
            key="teacher_admin_target",
            label_visibility="collapsed",
        )
        if teacher_admin_target:
            st.session_state.active_player = None
            st.session_state.admin_section = teacher_admin_target
            st.session_state.screen = "admin_panel"
            st.rerun()
    elif st.button("登出學生帳號"):
        clear_short_login()
        st.session_state.active_player = None
        st.session_state.screen = "login"
        st.rerun()

elif st.session_state.screen == "announcements":
    scroll_page_to_top("scroll_announcements_to_top")
    st.subheader("📢 公告事項")
    announcements = announcement_rows(active_only=True)
    if announcements:
        for announcement in announcements:
            with st.container(border=True):
                st.write(f"### {announcement['title']}")
                st.caption(f"發布時間：{announcement['created_at_text']}")
                render_announcement_content(announcement["content"])
    else:
        st.info("目前沒有新的公告事項。")
    render_bottom_home_button("announcements")

elif st.session_state.screen == "feedback":
    scroll_page_to_top("scroll_feedback_to_top")
    st.subheader("💬 遊戲反饋")
    st.info("你的回饋會直接送到老師後台，幫助老師判斷接下來要優先改善哪一部分。")
    with st.form("game_feedback_form", clear_on_submit=True):
        st.write("**請問勇者是在什麼情況下遇到問題？**")
        feedback_category = st.selectbox(
            "問題分類",
            ["能力", "裝備", "商店", "熔煉", "關卡", "任務", "戰鬥", "延遲", "人物", "其他"],
        )
        feedback_message = st.text_area(
            "請詳細描述遇到的問題",
            placeholder="例如：在哪個畫面、按了什麼按鈕、畫面出現什麼狀況……",
            height=220,
            max_chars=2000,
        )
        feedback_submitted = st.form_submit_button(
            "送出遊戲反饋", type="primary", use_container_width=True
        )
    if feedback_submitted:
        cleaned_feedback = feedback_message.strip()
        if len(cleaned_feedback) < 5:
            st.warning("請至少輸入5個字，讓老師能了解發生了什麼問題。")
        else:
            submit_game_feedback(
                st.session_state.active_player, feedback_category, cleaned_feedback
            )
            st.success("回饋已送給老師，謝謝你幫忙改善遊戲！")
    render_bottom_home_button("feedback")

elif st.session_state.screen == "mailbox":
    scroll_page_to_top("scroll_mailbox_to_top")
    remove_stale_elements_before("mailbox-page-start")
    st.subheader("📬 勇者信箱")
    mails = mailbox_rows(st.session_state.active_player)
    mailbox_filter = st.radio(
        "信件分類", ["未閱讀", "已閱讀"], horizontal=True, key="mailbox_filter"
    )
    unread_count = sum(1 for mail in mails if not mail["is_read"])
    if st.button(
        f"✅ 一鍵全部已讀（{unread_count}）",
        key="mailbox_mark_all_read",
        disabled=unread_count == 0,
        use_container_width=True,
    ):
        marked_count = mark_all_mail_read(st.session_state.active_player)
        st.session_state.mailbox_notice = f"已將 {marked_count} 封信件標示為已讀。"
        st.rerun()
    mailbox_notice = st.session_state.pop("mailbox_notice", None)
    if mailbox_notice:
        st.success(mailbox_notice)
    visible_mails = [
        mail for mail in mails
        if bool(mail["is_read"]) == (mailbox_filter == "已閱讀")
    ]
    if not visible_mails:
        st.info(f"目前沒有{mailbox_filter}信件。")
    for mail in visible_mails:
        reward = mail.get("reward") or {}
        reward_parts = []
        if reward.get("coins"):
            reward_parts.append(f"🪙 金幣 ×{reward['coins']}")
        if reward.get("sweep_tickets"):
            reward_parts.append(f"🎫 擊殺券 ×{reward['sweep_tickets']}")
        if reward.get("smelting_stones"):
            reward_parts.append(f"💎 融煉石 ×{reward['smelting_stones']}")
        claimed_label = "｜✅ 已領取" if mail["is_claimed"] else ""
        with st.expander(f"{mail['subject']}｜{mail['created_at']}{claimed_label}"):
            st.write(mail["message"])
            if reward_parts:
                st.info("附件獎勵：" + "、".join(reward_parts))
            if reward_parts and not mail["is_claimed"]:
                if st.button(
                    "領取獎勵", key=f"claim_mail_{mail['id']}",
                    type="primary", use_container_width=True,
                ):
                    if claim_mail_reward(mail["id"], st.session_state.active_player):
                        st.success("獎勵已領取！")
                    st.rerun()
            elif not mail["is_read"]:
                if st.button(
                    "標示為已閱讀", key=f"read_mail_{mail['id']}",
                    use_container_width=True,
                ):
                    mark_mail_read(mail["id"], st.session_state.active_player)
                    st.rerun()
    st.caption("已閱讀或已領取的信件會移至已閱讀清單；已領取信件排列在較下方。")
    render_bottom_home_button("mailbox")

elif st.session_state.screen == "character_stats":
    profile = get_profile()
    st.subheader("🧙 角色能力")
    st.markdown(
        """
        <style>
        /* 角色能力是獨立頁面，不顯示切頁時殘留的背包分頁與格子。 */
        [data-testid="stTabs"],
        [class*="st-key-gear_grid_"],
        .st-key-mobile_consumables { display:none !important; }
        @media (max-width:768px) and (orientation:portrait) {
          .st-key-mobile_stats [data-testid="stHorizontalBlock"] {display:flex !important;flex-wrap:nowrap !important;gap:.15rem !important;}
          .st-key-mobile_stats [data-testid="stColumn"] {min-width:0 !important;width:20% !important;max-width:20% !important;flex:0 0 20% !important;padding:0 !important;}
          .st-key-mobile_stats [data-testid="stMetricLabel"] {font-size:.68rem !important;}
          .st-key-mobile_stats [data-testid="stMetricValue"] {font-size:1.05rem !important;line-height:1.2 !important;white-space:nowrap !important;}
          .st-key-mobile_equipment [data-testid="stHorizontalBlock"] {display:flex !important;flex-wrap:nowrap !important;gap:.2rem !important;align-items:center !important;}
          .st-key-mobile_equipment [data-testid="stColumn"] {min-width:0 !important;padding:0 !important;}
          .st-key-mobile_equipment [data-testid="stColumn"]:nth-child(1) {flex:1 1 auto !important;width:auto !important;}
          .st-key-mobile_equipment [data-testid="stColumn"]:nth-child(2) {flex:0 0 24% !important;width:24% !important;}
          .st-key-mobile_equipment button {padding:.25rem .1rem !important;font-size:.72rem !important;min-height:2rem !important;}
          .st-key-mobile_equipment p {font-size:.72rem !important;line-height:1.15 !important;}
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    components.html(
        """
        <script>
        const removeInventoryResidue = () => {
            const doc = parent.document;
            doc.querySelectorAll(
                '[data-testid="stTabs"], [class*="st-key-gear_grid_"], .st-key-mobile_consumables'
            ).forEach(node => node.remove());
        };
        [0, 50, 120, 250, 500, 900, 1400].forEach(delay => setTimeout(removeInventoryResidue, delay));
        </script>
        """,
        height=0,
        scrolling=False,
    )
    with st.container(key="mobile_stats"):
        render_stats(profile)
    st.divider()
    st.subheader("⚔️ 目前裝備")
    with st.container(key="mobile_equipment"):
        for slot, label in SLOT_NAMES.items():
            uid = profile["equipment"].get(slot)
            item = find_item(profile, uid) if uid else None
            cols = st.columns([5, 1], vertical_alignment="center")
            cols[0].write(f"**{SLOT_ICONS[slot]} {label}**")
            if item and cols[1].button("卸下", key=f"stats_off_{slot}", use_container_width=True):
                profile["equipment"][slot] = None
                save_profile(profile)
                st.rerun()
            st.write(item_text(item) if item else "— 尚未裝備 —")
            st.divider()
    render_bottom_home_button("character_stats")

elif st.session_state.screen == "menu":
    scroll_page_to_top("scroll_menu_to_top")
    st.markdown(
        """
        <style>
        /* 關卡頁本身沒有分頁；隱藏切頁時可能短暫殘留的背包 tabs。 */
        [data-testid="stTabs"] { display:none !important; }
        </style>
        """,
        unsafe_allow_html=True,
    )
    profile = get_profile()
    if sync_daily_tasks(profile):
        save_profile(profile)
    if profile.get("retro_reward_notice"):
        for notice in profile["retro_reward_notice"]:
            send_mail(
                st.session_state.active_player, "系統補發通知", notice,
                claimed=True,
            )
        st.success("📬 系統補發內容已收進勇者信箱；獎勵先前已直接入帳。")
        profile["retro_reward_notice"] = []
        save_profile(profile)
    if st.session_state.active_player == "__TEACHER__":
        available_chapters = list(CHAPTERS)
    else:
        highest_chapter = int(highest_unlocked_chapter(profile))
        available_chapters = [cid for cid in CHAPTERS if int(cid) <= highest_chapter]
    if st.session_state.selected_chapter not in available_chapters:
        st.session_state.selected_chapter = available_chapters[-1]
    chapter_id = st.selectbox(
        "選擇章節",
        options=available_chapters,
        index=available_chapters.index(st.session_state.selected_chapter),
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
    normal_win_keys = {
        "1": "boss_wins", "2": "chapter2_boss_wins", "3": "chapter3_boss_wins",
        "4": "chapter4_boss_wins", "5": "chapter5_boss_wins",
    }
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
            st.success("第一章滿星成就已完成：★★★★ 第一章・整數勇者之劍｜固定：攻擊力 +8｜詞條：攻擊力 +25%")
        if profile["collection_reward_claimed"]:
            st.success("三星全裝收藏家已完成：100 EXP＋★★★★ 第一章・九星守護項鍊｜菁英BOSS血量降低13%｜HP +25%")
        if profile["elite_reward_claimed"]:
            st.success("菁英征服成就已完成：★★★★ 第一章・收藏家王冠｜固定：HP +25｜詞條：防禦力 +25%")
    elif chapter_id == "2":
        if profile["chapter2_reward_claimed"]:
            st.success("第二章滿星成就已完成：★★★★ 第二章・乘除勇者手甲｜固定：攻擊力 +6｜詞條：攻擊力 +25%")
        if profile["chapter2_collection_reward_claimed"]:
            st.success("第二章三星全裝收藏已完成：★★★★ 第二章・乘除疾風戰靴｜固定：攻擊速度 +0.13/秒｜詞條：攻擊速度 +25%")
        if profile["chapter2_elite_reward_claimed"]:
            st.success("第二章菁英征服已完成：★★★★ 第二章・乘除霸主盾｜固定：防禦力 +7｜詞條：HP +25%")
    elif chapter_id == "3":
        if profile["chapter3_reward_claimed"]:
            st.success("第三章滿星成就已完成：★★★★ 第三章・龍鱗守護鎧｜固定：防禦力 +15｜詞條：防禦力 +25%")
        if profile["chapter3_collection_reward_claimed"]:
            st.success("第三章三星全裝收藏已完成：100 EXP＋★★★★ 第三章・龍心腰帶｜固定：HP +25｜詞條：HP +25%")
        if profile["chapter3_elite_reward_claimed"]:
            st.success("第三章菁英征服已完成：★★★★ 第三章・烈焰龍王戒｜第一擊額外扣除菁英BOSS血量17%｜對菁英BOSS傷害 +25%")
    elif chapter_id == "4":
        if profile["chapter4_reward_claimed"]:
            st.success(f"第四章滿星成就已完成：★★★★ 第四章・雷狐靈冠｜固定：HP +{fixed_value_for('4', 'helmet', 4)[1]:g}｜詞條：HP +25%")
        if profile["chapter4_collection_reward_claimed"]:
            st.success(f"第四章三星全裝收藏已完成：100 EXP＋★★★★ 第四章・紫電踏雲靴｜固定：攻擊速度 +{fixed_value_for('4', 'boots', 4)[1]:.2f}/秒｜詞條：攻擊速度 +25%")
        if profile["chapter4_elite_reward_claimed"]:
            st.success(f"第四章菁英征服已完成：★★★★ 第四章・九尾天雷刃｜固定：攻擊力 +{fixed_value_for('4', 'weapon', 4)[1]:g}｜詞條：暴擊率 +25%")
    elif chapter_id == "5":
        if profile["chapter5_reward_claimed"]:
            st.success(f"第五章滿星成就已完成：★★★★ 第五章・冰河守護鎧｜固定：防禦力 +{fixed_value_for('5', 'armor', 4)[1]:g}｜詞條：防禦力 +25%")
        if profile["chapter5_collection_reward_claimed"]:
            st.success(f"第五章三星全裝收藏已完成：100 EXP＋★★★★ 第五章・極寒潮汐項鍊｜固定：菁英BOSS初始血量降低 {fixed_value_for('5', 'necklace', 4)[1]:.0%}｜詞條：受到傷害降低 +25%")
        if profile["chapter5_elite_reward_claimed"]:
            st.success(f"第五章菁英征服已完成：★★★★ 第五章・暴風王盾｜固定：防禦力 +{fixed_value_for('5', 'shield', 4)[1]:g}｜詞條：對菁英BOSS傷害 +25%")
    if st.session_state.active_player == "__TEACHER__":
        if st.button("返回老師管理後台"):
            st.session_state.active_player = None
            st.session_state.screen = "admin_panel"
            st.rerun()
    elif st.button("登出學生帳號"):
        clear_short_login()
        st.session_state.active_player = None
        st.session_state.screen = "login"
        st.rerun()
    render_bottom_home_button("stages")

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
    render_bottom_home_button("tasks")

elif st.session_state.screen == "rankings":
    scroll_page_to_top("scroll_ranking_to_top")
    st.subheader("🏆 勇者排行榜")
    boss_tab, level_tab, hp_tab, attack_tab, defense_tab, speed_tab = st.tabs(
        ["🐉 BOSS排行", "⭐ 等級排行", "❤️ HP排行", "⚔️ 攻擊排行", "🛡️ 防禦排行", "💨 攻速排行"],
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
        (hp_tab, "hp", "依目前等級與穿戴裝備計算HP；同值時以等級與EXP排序。"),
        (attack_tab, "attack", "依目前穿戴裝備計算攻擊力。"),
        (defense_tab, "defense", "依目前穿戴裝備計算防禦力。"),
        (speed_tab, "speed", "依目前穿戴裝備計算每秒攻擊次數。"),
    ]
    character_tables = character_ranking_tables()
    for tab, ranking_type, description in ranking_specs:
        with tab:
            st.caption(description)
            render_ranking(student_ranking_rows(character_tables[ranking_type]))
    st.caption(
        "各榜顯示前10名；若自己不在前10名，會額外顯示自己的實際名次。"
        "排行榜只公開大頭貼、勇者名稱、稱號與遊戲數值，不顯示正式姓名或學生代碼。"
    )
    render_bottom_home_button("rankings")

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
    if acquired_item and mode == "forge":
        render_forge_result_dialog(profile, acquired_item)
    elif acquired_item:
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
        refresh_cost = shop_paid_refresh_cost(profile)
        paid_refresh_count = int(profile["shop"].get("paid_refresh_count", 0) or 0)
        if refresh_col.button(
            f"花{refresh_cost}金幣強制刷新",
            disabled=profile["coins"] < refresh_cost,
            use_container_width=True,
        ):
            refresh_shop(profile, paid=True)
            save_profile(profile)
            st.session_state.shop_purchase_uid = None
            st.rerun()
        refresh_col.caption(
            f"本輪已刷新 {paid_refresh_count} 次；每5次費用加倍，24小時自動刷新後重設。"
        )
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

        special_stone_type = st.radio(
            "詞條熔煉石",
            ["不使用", "部位基礎熔煉石", "基礎詞條熔煉石", "進階詞條熔煉石"],
            help="一次只能選擇一種；選擇特殊熔煉石後，可以指定本次產出的部位或詞條。",
        )
        selected_slot = None
        if special_stone_type == "部位基礎熔煉石":
            selected_slot = st.selectbox(
                "指定部位", list(SLOT_NAMES),
                format_func=lambda slot: f"{SLOT_ICONS[slot]} {SLOT_NAMES[slot]}",
            )
        basic_affixes = ["hp_pct", "attack_pct", "defense_pct", "speed_pct"]
        advanced_affixes = [key for key in AFFIX_NAMES if key not in basic_affixes]
        selected_affix = None
        if special_stone_type == "基礎詞條熔煉石":
            selected_affix = st.selectbox(
                "指定基礎詞條", basic_affixes, format_func=lambda key: AFFIX_NAMES[key]
            )
        elif special_stone_type == "進階詞條熔煉石":
            selected_affix = st.selectbox(
                "指定進階詞條", advanced_affixes, format_func=lambda key: AFFIX_NAMES[key]
            )
        required_special_stone = {
            "不使用": None,
            "部位基礎熔煉石": "slot_smelting_stones",
            "基礎詞條熔煉石": "basic_affix_smelting_stones",
            "進階詞條熔煉石": "advanced_affix_smelting_stones",
        }[special_stone_type]
        enough_special_stone = (
            required_special_stone is None
            or profile.get(required_special_stone, 0) > 0
        )
        if not enough_special_stone:
            st.warning(f"目前沒有可使用的「{special_stone_type}」。")
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
            disabled=not valid_materials or not enough_stone or not enough_special_stone,
        ):
            result_item = make_forged_item(
                profile, source_stars, source_chapter, selected_slot=selected_slot,
                selected_affix=selected_affix,
            )
            remove_inventory_items(profile, selected)
            if source_stars == 2:
                profile["smelting_stones"] -= 1
            if special_stone_type == "部位基礎熔煉石":
                profile["slot_smelting_stones"] -= 1
            elif special_stone_type == "基礎詞條熔煉石":
                profile["basic_affix_smelting_stones"] -= 1
            elif special_stone_type == "進階詞條熔煉石":
                profile["advanced_affix_smelting_stones"] -= 1
            profile["inventory"].append(result_item)
            save_profile(profile)
            st.session_state.forge_result_uid = result_item["uid"]
            st.rerun()
    render_bottom_home_button("economy")

elif st.session_state.screen in {"backpack", "gallery"}:
    scroll_page_to_top("scroll_inventory_to_top")
    profile = get_profile()
    inventory_view = st.session_state.screen
    st.subheader("🎒 背包" if inventory_view == "backpack" else "📖 圖鑑收集")
    if inventory_view == "backpack":
        gear_tab, consumable_tab, title_tab, future_tab = st.tabs(
            ["⚔️ 裝備", "🧪 消耗道具", "🏅 成就稱號", "🔒 待開放"],
        )
        with gear_tab:
            st.markdown(
                """
                <style>
                [class*="st-key-gear_grid_"] [data-testid="stColumn"] {
                  border:1px solid #d9dee7;border-radius:8px;padding:.25rem !important;min-height:5rem;
                }
                @media (max-width:768px) and (orientation:portrait) {
                  [class*="st-key-gear_grid_"] [data-testid="stHorizontalBlock"] {display:flex !important;flex-wrap:nowrap !important;gap:.12rem !important;}
                  [class*="st-key-gear_grid_"] [data-testid="stColumn"] {min-width:0 !important;width:20% !important;max-width:20% !important;flex:0 0 calc(20% - .1rem) !important;padding:.18rem !important;min-height:4.8rem;overflow:hidden !important;}
                  [class*="st-key-gear_grid_"] button {padding:.35rem .06rem !important;font-size:.6rem !important;line-height:1.12 !important;white-space:normal !important;min-height:4.15rem !important;overflow:hidden !important;}
                }
                </style>
                """,
                unsafe_allow_html=True,
            )
            equipped_uids = {uid for uid in profile["equipment"].values() if uid}
            backpack_items = [
                item for item in profile["inventory"] if item["uid"] not in equipped_uids
            ]
            title_col, bulk_col = st.columns([4, 1], vertical_alignment="center")
            title_col.write(f"### 未裝備物品（{len(backpack_items)}件）")
            bulk_mode = st.session_state.get("bulk_dismantle_mode", False)
            if bulk_col.button(
                "取消多項分解" if bulk_mode else "多項分解",
                key="toggle_bulk_dismantle",
                use_container_width=True,
            ):
                st.session_state.bulk_dismantle_mode = not bulk_mode
                st.rerun()
            st.caption("背包只顯示未穿戴裝備；點擊格子可查看、裝備或分解。每列5格，超過25件可繼續往下瀏覽。")
            filter_col, star_col, sort_col = st.columns(3)
            selected_slot_filter = filter_col.selectbox(
                "部位篩選",
                options=["all", *SLOT_NAMES.keys()],
                format_func=lambda slot: "全部部位" if slot == "all" else SLOT_NAMES[slot],
                key="backpack_slot_filter",
            )
            selected_star_filter = star_col.selectbox(
                "星級篩選",
                options=[0, 4, 3, 2, 1],
                format_func=lambda stars: "全部星級" if stars == 0 else f"{stars} 星",
                key="backpack_star_filter",
            )
            selected_gear_sort = sort_col.selectbox(
                "排列方式",
                options=["star_desc", "star_asc", "slot"],
                format_func=lambda value: {
                    "star_desc": "星級：高到低",
                    "star_asc": "星級：低到高",
                    "slot": "依部位排列",
                }[value],
                key="backpack_gear_sort",
            )
            visible_items = [
                item for item in backpack_items
                if (selected_slot_filter == "all" or item["slot"] == selected_slot_filter)
                and (selected_star_filter == 0 or item["stars"] == selected_star_filter)
            ]
            slot_order = {slot: index for index, slot in enumerate(SLOT_NAMES)}
            if selected_gear_sort == "star_asc":
                sort_key = lambda item: (item["stars"], slot_order[item["slot"]], item["name"])
            elif selected_gear_sort == "slot":
                sort_key = lambda item: (slot_order[item["slot"]], -item["stars"], item["name"])
            else:
                sort_key = lambda item: (-item["stars"], slot_order[item["slot"]], item["name"])
            sorted_items = sorted(visible_items, key=sort_key)
            st.caption(f"目前顯示 {len(sorted_items)}／{len(backpack_items)} 件未裝備物品。")
            if bulk_mode:
                eligible_bulk_items = [item for item in sorted_items if item["stars"] in (1, 2, 3)]
                selected_bulk_items = [
                    item
                    for item in eligible_bulk_items
                    if st.session_state.get(f"bulk_break_{item['uid']}", False)
                ]
                bulk_coins = sum(item["stars"] * 100 for item in selected_bulk_items)
                bulk_stones = sum(1 for item in selected_bulk_items if item["stars"] == 3)
                st.info(
                    f"已選擇 {len(selected_bulk_items)} 件，可獲得 {bulk_coins} 金幣"
                    + (f"、{bulk_stones} 顆融煉石" if bulk_stones else "")
                    + "。四星裝備不可分解。"
                )
                confirm_col, clear_col = st.columns(2)
                if confirm_col.button(
                    "確認分解所選裝備",
                    key="confirm_bulk_dismantle",
                    type="primary",
                    disabled=not selected_bulk_items,
                    use_container_width=True,
                ):
                    profile["coins"] += bulk_coins
                    profile["smelting_stones"] += bulk_stones
                    remove_inventory_items(profile, [item["uid"] for item in selected_bulk_items])
                    save_profile(profile)
                    for item in selected_bulk_items:
                        st.session_state.pop(f"bulk_break_{item['uid']}", None)
                    st.session_state.bulk_dismantle_mode = False
                    st.session_state.bulk_dismantle_notice = (
                        f"已分解 {len(selected_bulk_items)} 件裝備，獲得 {bulk_coins} 金幣"
                        + (f"與 {bulk_stones} 顆融煉石" if bulk_stones else "")
                        + "。"
                    )
                    st.rerun()
                if clear_col.button("取消並清除選取", key="clear_bulk_dismantle", use_container_width=True):
                    for item in eligible_bulk_items:
                        st.session_state.pop(f"bulk_break_{item['uid']}", None)
                    st.session_state.bulk_dismantle_mode = False
                    st.rerun()
            if st.session_state.get("bulk_dismantle_notice"):
                st.success(st.session_state.pop("bulk_dismantle_notice"))
            if not sorted_items:
                st.info("完成單元後可以取得裝備。")
            for start in range(0, len(sorted_items), 5):
                with st.container(key=f"gear_grid_{start // 5}"):
                    grid_cols = st.columns(5)
                    row_items = sorted_items[start:start + 5]
                    for col_index, col in enumerate(grid_cols):
                        if col_index >= len(row_items):
                            col.markdown("&nbsp;", unsafe_allow_html=True)
                            continue
                        item = row_items[col_index]
                        equipped = profile["equipment"].get(item["slot"]) == item["uid"]
                        label = f"{SLOT_ICONS[item['slot']]} {item['name']}\n{'⭐' * item['stars']}"
                        if bulk_mode:
                            col.checkbox(
                                label,
                                key=f"bulk_break_{item['uid']}",
                                disabled=item["stars"] >= 4,
                                help="四星裝備不可分解" if item["stars"] >= 4 else "勾選後可一次分解",
                            )
                            continue
                        with col.popover(label, use_container_width=True):
                            render_item_comparison(profile, item)
                            if st.button("裝備", key=f"grid_equip_{item['uid']}", use_container_width=True):
                                profile["equipment"][item["slot"]] = item["uid"]
                                save_profile(profile)
                                st.rerun()
                            if item["stars"] in (1, 2, 3):
                                coin_gain = item["stars"] * 100
                                stone_text = "＋1顆融煉石" if item["stars"] == 3 else ""
                                st.warning(f"分解不可復原：{coin_gain}金幣{stone_text}")
                                if st.button("確認分解", key=f"grid_break_{item['uid']}", use_container_width=True):
                                    profile["coins"] += coin_gain
                                    profile["smelting_stones"] += 1 if item["stars"] == 3 else 0
                                    remove_inventory_items(profile, [item["uid"]])
                                    save_profile(profile)
                                    st.rerun()
                            elif item["stars"] >= 4:
                                st.caption("四星以上裝備目前不能分解。")
        with consumable_tab:
            st.markdown(
                """
                <style>
                .st-key-mobile_consumables [data-testid="stColumn"] {
                  border:1px solid #d9dee7;border-radius:8px;padding:.35rem !important;min-height:5rem;
                }
                @media (max-width:768px) and (orientation:portrait) {
                  .st-key-mobile_consumables [data-testid="stHorizontalBlock"] {display:flex !important;flex-wrap:nowrap !important;gap:.12rem !important;}
                  .st-key-mobile_consumables [data-testid="stColumn"] {min-width:0 !important;width:20% !important;max-width:20% !important;flex:0 0 calc(20% - .1rem) !important;padding:.12rem !important;min-height:4.3rem;}
                  .st-key-mobile_consumables [data-testid="stMetricLabel"] {font-size:.58rem !important;line-height:1.05 !important;white-space:normal !important;}
                  .st-key-mobile_consumables [data-testid="stMetricValue"] {font-size:1rem !important;line-height:1.1 !important;}
                }
                </style>
                """,
                unsafe_allow_html=True,
            )
            consumables = [
                ("🎫", "擊殺券", profile["sweep_tickets"]),
                ("💎", "融煉石", profile["smelting_stones"]),
                ("🧭", "部位融煉石", profile["slot_smelting_stones"]),
                ("🔷", "基礎詞條融煉石", profile["basic_affix_smelting_stones"]),
                ("🔶", "進階詞條融煉石", profile["advanced_affix_smelting_stones"]),
            ]
            with st.container(key="mobile_consumables"):
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
                    ("chapter-1", four_star_item_name("1", "整數勇者之劍"), "weapon", "完成第一章所有三星單元", "unit"),
                    ("chapter-1-collection", four_star_item_name("1", "九星守護項鍊"), "necklace", "收集第一章九部位三星", "collection"),
                    ("chapter-1-elite", four_star_item_name("1", "收藏家王冠"), "helmet", "首次擊敗第一章菁英BOSS", "elite"),
                ],
                "2": [
                    ("chapter-2", four_star_item_name("2", "乘除勇者手甲"), "gloves", "完成第二章所有三星單元", "unit"),
                    ("chapter-2-collection", four_star_item_name("2", "乘除疾風戰靴"), "boots", "收集第二章九部位三星", "collection"),
                    ("chapter-2-elite", four_star_item_name("2", "乘除霸主盾"), "shield", "首次擊敗第二章菁英BOSS", "elite"),
                ],
                "3": [
                    ("chapter-3", four_star_item_name("3", "龍鱗守護鎧"), "armor", "完成第三章所有三星單元", "unit"),
                    ("chapter-3-collection", four_star_item_name("3", "龍心腰帶"), "belt", "收集第三章九部位三星", "collection"),
                    ("chapter-3-elite", four_star_item_name("3", "烈焰龍王戒"), "ring", "首次擊敗第三章菁英BOSS「烈焰龍王」", "elite"),
                ],
                "4": [
                    ("chapter-4", four_star_item_name("4", "雷狐靈冠"), "helmet", "完成第四章所有三星單元", "unit"),
                    ("chapter-4-collection", four_star_item_name("4", "紫電踏雲靴"), "boots", "收集第四章九部位三星", "collection"),
                    ("chapter-4-elite", four_star_item_name("4", "九尾天雷刃"), "weapon", "首次擊敗第四章菁英BOSS「九尾天狐」", "elite"),
                ],
                "5": [
                    ("chapter-5", four_star_item_name("5", "冰河守護鎧"), "armor", "完成第五章所有三星單元", "unit"),
                    ("chapter-5-collection", four_star_item_name("5", "極寒潮汐項鍊"), "necklace", "收集第五章九部位三星", "collection"),
                    ("chapter-5-elite", four_star_item_name("5", "暴風王盾"), "shield", "首次擊敗第五章菁英BOSS「暴風熊王」", "elite"),
                ],
            }
            owned_four_slots = collected_achievement_slots(profile, 4)
            st.write(f"#### 全系列四星部位 {len(owned_four_slots)}/9")
            st.progress(len(owned_four_slots) / len(SLOT_NAMES))
            missing = [SLOT_NAMES[slot] for slot in SLOT_NAMES if slot not in owned_four_slots]
            if missing:
                st.caption(f"尚缺部位：{'、'.join(missing)}。四星九部位集滿前，成就裝備不會重複部位。")
            else:
                st.success("四星九部位已全部收藏！後續章節四星裝備可用來更新更高固定值的同部位裝備。")
            if not four_star_specs[gallery_chapter]:
                st.info("第三章四星成就裝備尚未開放；目前可先收集九部位三星裝備並測試BOSS難度。")
            reward_cols = st.columns(3)
            for col, (unit_key, name, slot, requirement, action) in zip(reward_cols, four_star_specs[gallery_chapter]):
                owned_item = achievement_item(profile, unit_key)
                if achievement_was_collected(profile, unit_key, 4):
                    detail = fixed_text(owned_item) if owned_item else "曾經取得（目前未持有）"
                    col.success(f"✅ ★★★★ {SLOT_ICONS[slot]} {name}｜已收藏\n\n{detail}")
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
                    elite_ready = profile.get({
                        "1": "boss_wins",
                        "2": "chapter2_boss_wins",
                        "3": "chapter3_boss_wins",
                        "4": "chapter4_boss_wins",
                        "5": "chapter5_boss_wins",
                    }[gallery_chapter], 0) > 0
                    if col.button("前往菁英BOSS", key=f"elite_go_{unit_key}", disabled=not elite_ready, use_container_width=True):
                        st.session_state.selected_chapter = gallery_chapter
                        st.session_state.selected_boss_type = "elite"
                        st.session_state.scroll_boss_to_top = True
                        st.session_state.screen = "boss_ready"
                        st.rerun()
            st.caption("四星固定值不隨章節倍率變動，但都高於首次登場章節可掉落的同部位三星固定值。")
    render_bottom_home_button(inventory_view)

elif st.session_state.screen == "quiz":
    st.markdown(
        """
        <style>
        @media (max-width: 768px) and (orientation: portrait) {
            .st-key-quiz-mobile-stats [data-testid="stHorizontalBlock"] {
                display: flex !important;
                flex-direction: row !important;
                flex-wrap: nowrap !important;
                gap: .2rem !important;
            }
            .st-key-quiz-mobile-stats [data-testid="stColumn"] {
                flex: 1 1 25% !important;
                width: 25% !important;
                min-width: 0 !important;
            }
            .st-key-quiz-mobile-stats [data-testid="stMetric"] {
                padding: .2rem .1rem !important;
            }
            .st-key-quiz-mobile-stats [data-testid="stMetricLabel"] {
                font-size: .72rem !important;
                line-height: 1.1 !important;
                white-space: nowrap !important;
            }
            .st-key-quiz-mobile-stats [data-testid="stMetricValue"] {
                font-size: 1.15rem !important;
                line-height: 1.2 !important;
            }
            .st-key-quiz-mobile-stats [data-testid="stMetricValue"] > div {
                font-size: inherit !important;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    if st.button("← 返回章節（離開本次測驗）", key="leave_quiz_button"):
        leave_quiz()
        st.session_state.scroll_menu_to_top = True
        st.rerun()

    unit = UNITS[st.session_state.selected_unit]
    st.subheader(f"單元{st.session_state.selected_unit}：{unit['name']}")
    if uses_advanced_combo_rules(st.session_state.selected_unit):
        st.caption("星級規則：最高連擊1～3為一星、4～6為二星、7～8為三星；達成8連擊立即三星通關。最多作答20題。")
    else:
        st.caption("星級規則：最高連擊1～4為一星、5～9為二星；達成10連擊立即三星通關。最多作答20題。")
    @st.fragment
    def quiz_panel():
        if st.session_state.screen != "quiz":
            st.rerun(scope="app")
        with st.container(key="quiz-mobile-stats"):
            cols = st.columns(4)
            cols[0].metric("作答進度", f"{st.session_state.attempts}/{MAX_QUESTIONS}題")
            cols[1].metric("目前連擊", st.session_state.combo)
            cols[2].metric("最高連擊", st.session_state.max_combo)
            cols[3].metric("答對", st.session_state.correct)
        st.progress(min(1.0, st.session_state.attempts / MAX_QUESTIONS))
        if st.session_state.question.get("fraction"):
            question = st.session_state.question
            source_numbers = re.findall(r"\d+", str(question.get("text", "")))
            source_numerator = question.get(
                "question_numerator", source_numbers[0] if source_numbers else "?"
            )
            source_denominator = question.get(
                "question_denominator", source_numbers[1] if len(source_numbers) > 1 else "?"
            )
            st.markdown(
                f"""
                <style>
                .fraction-question {{
                    display:flex;align-items:center;justify-content:flex-start;
                    gap:1rem;font-size:2.2rem;font-weight:700;margin:.7rem 0 1rem;
                }}
                .vertical-fraction {{
                    display:inline-flex;flex-direction:column;align-items:center;
                    justify-content:center;min-width:3.4rem;line-height:1.05;
                }}
                .vertical-fraction .fraction-top {{
                    width:100%;text-align:center;border-bottom:3px solid currentColor;
                    padding:0 .45rem .22rem;
                }}
                .vertical-fraction .fraction-bottom {{
                    width:100%;text-align:center;padding:.22rem .45rem 0;
                }}
                @media (max-width:768px) and (orientation:portrait) {{
                    .fraction-question {{font-size:1.75rem;gap:.65rem;justify-content:center;}}
                    .vertical-fraction {{min-width:2.8rem;}}
                }}
                </style>
                <div class="fraction-question">
                    <span class="vertical-fraction">
                        <span class="fraction-top">{source_numerator}</span>
                        <span class="fraction-bottom">{source_denominator}</span>
                    </span>
                    <span>＝</span>
                    <span class="vertical-fraction">
                        <span class="fraction-top">（　）</span>
                        <span class="fraction-bottom">（　）</span>
                    </span>
                </div>
                """,
                unsafe_allow_html=True,
            )
        else:
            st.markdown(f"## {st.session_state.question['text']}")
        with st.form("answer_form"):
            if st.session_state.question.get("fraction"):
                fraction_col = st.columns([1, 2, 1])[1]
                fraction_col.number_input(
                    "分子", value=None, step=1, format="%d",
                    key="answer_numerator", placeholder="分子",
                )
                fraction_col.markdown(
                    "<div style='height:3px;background:currentColor;margin:-.25rem 0 .4rem;'></div>",
                    unsafe_allow_html=True,
                )
                fraction_col.number_input(
                    "分母", value=None, step=1, min_value=1, format="%d",
                    key="answer_denominator", placeholder="分母",
                )
            else:
                st.number_input(
                    "你的答案", value=None,
                    step=0.01 if st.session_state.selected_unit.startswith(("3-", "4-")) else 1.0,
                    format="%.2f" if st.session_state.selected_unit.startswith(("3-", "4-")) else "%.0f",
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
    result = simulate_battle(stats, boss_type, chapter_id)
    has_cleared = boss_has_been_cleared(profile, chapter_id, boss_type)
    boss_label = "菁英BOSS" if boss_type == "elite" else "一般BOSS"
    title_prefix = f"「{profile['equipped_title']}」" if profile.get("equipped_title") else ""
    st.subheader(f"🧙 {title_prefix}{profile['name']}")
    st.markdown(
        """
        <style>
        @media (max-width:768px) and (orientation:portrait) {
          .st-key-boss_mobile_stats [data-testid="stHorizontalBlock"] {
            display:flex !important;flex-direction:row !important;
            flex-wrap:nowrap !important;gap:.12rem !important;width:100% !important;
          }
          .st-key-boss_mobile_stats [data-testid="stColumn"] {
            min-width:0 !important;width:20% !important;max-width:20% !important;
            flex:0 0 20% !important;padding:0 !important;
          }
          .st-key-boss_mobile_stats [data-testid="stMetricLabel"] {
            font-size:.64rem !important;line-height:1.05 !important;
          }
          .st-key-boss_mobile_stats [data-testid="stMetricValue"] {
            font-size:1rem !important;line-height:1.15 !important;white-space:nowrap !important;
          }
          .st-key-boss_mobile_stats [data-testid="stMetric"] {padding:.12rem !important;}
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    with st.container(key="boss_mobile_stats"):
        render_stats(profile, show_exp=False)
    st.divider()
    st.subheader(f"🐉 {CHAPTERS[chapter_id]['number']}{boss_label}：{config['name']}")
    boss_image_path = Path(__file__).parent / "assets" / "bosses" / config["image"]
    if boss_image_path.exists():
        st.image(boss_image_path, width=320, caption=config["name"])
    else:
        st.warning("BOSS 圖片素材尚未安裝，目前暫時使用預設圖示。")
    st.write("### BOSS 能力與技能")
    st.write(f"BOSS HP：{config['hp']}｜每{config['interval']:g}秒攻擊{config['damage']}")
    if config.get("critical_rate"):
        st.warning(
            f"⚠️ BOSS特殊能力：暴擊率 {config['critical_rate']:.0%}；"
            f"每第{round(1 / config['critical_rate'])}次攻擊必定暴擊，造成1.5倍傷害。"
        )
    if config.get("defense_reduction"):
        st.warning(
            f"⚡ BOSS被動：戰鬥期間勇者防禦降低 {config['defense_reduction']}（最低為0）；"
            "受到傷害降低詞條仍可生效。"
        )
    if config.get("hero_speed_reduction"):
        st.warning(
            f"❄️ BOSS被動：戰鬥期間勇者攻擊速度降低"
            f" {config['hero_speed_reduction']:.3f}次／秒，直到戰鬥結束。"
        )
    if config.get("hero_damage_reduction"):
        st.error(
            f"🌪️ BOSS技能「{config['skill']}」：戰鬥開始立即發動，勇者造成的傷害降低"
            f" {config['hero_damage_reduction']:.0%}；可與對菁英BOSS傷害加成互相抵銷。"
        )
    if config.get("skill"):
        if config.get("skill_at_start"):
            pass
        elif config.get("skill_hp_threshold") is not None:
            threshold_damage = config.get("true_damage", config.get("skill_damage", 0))
            st.error(
                f"⚡ BOSS技能「{config['skill']}」：BOSS血量首次低於"
                f"{config['skill_hp_threshold']:.0%}時發動一次，造成{threshold_damage:g}"
                f"{'真實傷害；無法被防禦、傷害減免或護盾抵銷。' if config.get('true_damage') is not None else '傷害；不計算防禦，但可被受到傷害降低與開場護盾抵銷。'}"
            )
        else:
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
    if st.button("⚔️ 開始並觀看戰鬥", type="primary", use_container_width=True):
        force_top_before_navigation()
        st.session_state.battle_events = result
        st.session_state.battle_started_at = time.time()
        st.session_state.battle_recorded = False
        st.session_state.scroll_battle_to_top = True
        st.session_state.screen = "boss_watch"
        st.rerun()
    st.caption("所有 BOSS 挑戰都必須觀看完整戰鬥；通關時間會自動記錄至排行榜。")
    if st.button("返回章節"):
        st.session_state.screen = "menu"
        st.rerun()

elif st.session_state.screen == "boss_watch":
    st.markdown(
        """
        <style>
        header[data-testid="stHeader"],
        [data-testid="stToolbar"],
        [data-testid="stDecoration"],
        footer { display: none !important; }
        /* 戰鬥頁不使用能力卡，隱藏切頁動畫殘留的準備畫面數值。 */
        .st-key-boss_mobile_stats,
        [class*="st-key-boss_mobile_stats"],
        [data-testid="stMetric"] { display: none !important; }
        [data-testid="stMainBlockContainer"] {
            padding-top: 0.35rem !important;
            padding-bottom: 0.35rem !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    components.html(
        """
        <script>
        const removeBattlePrepResidue = () => {
            const doc = parent.document;
            doc.querySelectorAll(
                '.st-key-boss_mobile_stats, [class*="st-key-boss_mobile_stats"], [data-testid="stMetric"]'
            ).forEach(node => node.remove());
        };
        [0, 50, 120, 250, 500, 900].forEach(delay => setTimeout(removeBattlePrepResidue, delay));
        </script>
        """,
        height=0,
        scrolling=False,
    )
    scroll_page_to_top("scroll_battle_to_top")
    @st.fragment(run_every=0.35)
    def battle_panel():
        result = st.session_state.battle_events
        elapsed = time.time() - st.session_state.battle_started_at
        simulated_elapsed, active_skill, presentation_duration = battle_presentation_state(result, elapsed)
        visible = [e for e in result["events"] if e["time"] <= simulated_elapsed]
        event = visible[-1]
        profile = get_profile()
        config = BOSS_CONFIGS[
            f"{st.session_state.selected_chapter}_{st.session_state.selected_boss_type}"
        ]
        title_prefix = f"「{profile['equipped_title']}」" if profile.get("equipped_title") else ""
        render_health_bar(
            f"{title_prefix}{profile['name']}",
            event["player_hp"], result["events"][0]["player_hp"], "#2185d0"
        )
        render_health_bar(
            config["name"], event["boss_hp"], result["events"][0]["boss_hp"], "#e53935"
        )
        render_battle_scene(
            event, st.session_state.selected_chapter,
            st.session_state.selected_boss_type, len(visible), active_skill,
            profile.get("gender") or "male",
        )
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
