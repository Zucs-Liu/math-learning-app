import html
import json
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

from data_access.database import DatabaseConnection
from data_access.admin import (
    delete_student_record,
    fetch_recent_attempts,
    fetch_student_learning_detail,
    fetch_student_question_rows,
    fetch_teacher_name,
    reset_student_pin_record,
    update_student_real_name_record,
)
from data_access.communications import (
    count_unread_mail,
    create_announcement_record,
    create_feedback_record,
    create_mail_record,
    delete_announcement_record,
    fetch_announcement_rows,
    fetch_feedback_rows,
    fetch_mail_reward,
    fetch_mail_rows,
    set_all_mail_read,
    set_announcement_status,
    set_feedback_replied,
    set_mail_claimed,
    set_mail_read,
    update_announcement_record,
)
from data_access.players import (
    clear_login_failures,
    create_player_record,
    create_teacher_record,
    fetch_login_player,
    fetch_profile_row,
    fetch_teacher_profile_json,
    player_exists,
    record_login_failure,
    save_teacher_profile,
    update_profile_record,
)
from data_access.progress import (
    fetch_boss_ranking_rows,
    fetch_character_profiles,
    fetch_student_rows,
    insert_attempt,
    insert_question_log,
    save_best_boss_record,
)
from data_access.schema import initialize_schema

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
from game_logic.authentication import (
    create_short_login_token,
    make_pin_hash,
    normalized_hero_name,
    pin_digest,
    student_code_for_number,
    validate_public_hero_name,
    validate_short_login_token,
)
from game_logic.profile import (
    create_new_profile,
    normalize_profile_data,
    sync_profile_collection_catalog,
)
from game_logic.progression import (
    add_experience,
    apply_task_reward,
    award_first_clear_ticket,
    boss_unlocked,
    build_permanent_task_definitions,
    highest_unlocked_chapter_id,
    sync_daily_task_periods,
    visible_permanent_task_rows,
)
from game_logic.economy import (
    BASIC_AFFIXES,
    SHOP_ITEM_PRICE,
    SPECIAL_STONE_CRAFT_COST,
    SPECIAL_STONE_KEYS,
    craft_special_stone,
    dismantle_inventory_items,
    dismantle_value,
    ensure_shop_inventory,
    highest_shop_chapter_id,
    make_forged_inventory_item,
    make_shop_inventory_item,
    paid_shop_refresh_cost,
    purchase_shop_entry,
    refresh_shop_inventory,
    remove_inventory_entries,
)
from game_logic.loot import (
    achievement_was_collected as loot_achievement_was_collected,
    collected_achievement_slots as loot_collected_achievement_slots,
    collected_three_star_slots as loot_collected_three_star_slots,
    find_achievement_item,
    find_inventory_item,
    has_full_three_star_collection,
    item_signature as loot_item_signature,
    make_achievement_reward,
    make_random_drop,
    sync_achievement_item as sync_loot_achievement_item,
    sync_four_star_item_name,
)
from game_logic.equipment import (
    fixed_text,
    fixed_value_for,
    four_star_item_name,
    item_chapter_id,
    item_text,
    player_stats,
)
from game_ui.common import (
    force_top_before_navigation,
    remove_stale_elements_before,
    render_bottom_home_button,
    render_health_bar,
    scroll_page_to_top,
)
from game_ui.battle import (
    battle_presentation_state,
    render_battle_scene,
    render_chapter_boss_card,
)
from game_ui.profile import render_item_comparison, render_stats
from game_ui.login import apply_login_background, render_compact_avatar_editor
from game_ui.quiz import render_quiz_panel, render_quiz_result
from game_ui.stages import (
    render_chapter_reward_status,
    render_chapter_selector,
    render_unit_cards,
)
from game_ui.inventory import render_backpack, render_gallery

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


def validate_hero_name(name):
    return validate_public_hero_name(name, BLOCKED_NAME_WORDS)

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


def db_connection():
    return DatabaseConnection(DATABASE_URL, DB_FILE)


@st.cache_resource(show_spinner=False)
def init_db():
    return initialize_schema(db_connection, USE_POSTGRES)


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
    return create_short_login_token(
        student_code, short_login_secret(), SHORT_LOGIN_SECONDS
    )


def verify_short_login_token(token):
    return validate_short_login_token(
        token,
        short_login_secret(),
        lambda student_code: player_exists(db_connection, student_code),
    )


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
    return create_new_profile(name, SLOT_NAMES, UNITS)


def normalize_profile(profile, name):
    return normalize_profile_data(
        profile, name, SLOT_NAMES, UNITS, item_chapter_id
    )


def sequential_student_code(number):
    return student_code_for_number(number)


def create_student(real_name, hero_name, pin):
    validation_error = validate_hero_name(hero_name)
    if validation_error:
        raise ValueError(validation_error)
    salt, digest = make_pin_hash(pin)
    profile = new_profile(hero_name)
    profile["task_rewards_initialized"] = True
    profile["elite_special_tasks_migrated"] = True
    code = create_player_record(
        db_connection,
        USE_POSTGRES,
        real_name,
        hero_name,
        salt,
        digest,
        json.dumps(profile, ensure_ascii=False),
        database_timestamp(),
        sequential_student_code,
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
    row = fetch_teacher_profile_json(db_connection)
    if row:
        profile = normalize_profile(json.loads(row["profile_json"]), hero_name)
        profile["name"] = hero_name
        sync_teacher_test_profile(profile)
        save_teacher_profile(
            db_connection, hero_name, json.dumps(profile, ensure_ascii=False)
        )
    else:
        salt, digest = make_pin_hash(secrets.token_hex(16))
        profile = new_profile(hero_name)
        profile["task_rewards_initialized"] = True
        profile["elite_special_tasks_migrated"] = True
        sync_teacher_test_profile(profile)
        create_teacher_record(
            db_connection,
            hero_name,
            salt,
            digest,
            json.dumps(profile, ensure_ascii=False),
            database_timestamp(),
        )
    return code


def verify_student(code, pin):
    code = code.strip().upper()
    now = time.time()
    row = fetch_login_player(db_connection, code)
    if not row:
        return False, "學生代碼或PIN錯誤"
    if row["locked_until"] > now:
        wait_seconds = math.ceil(row["locked_until"] - now)
        return False, f"登入暫時鎖定，請等待{wait_seconds}秒"
    valid = hmac.compare_digest(pin_digest(pin, row["pin_salt"]), row["pin_hash"])
    if valid:
        clear_login_failures(db_connection, code)
        return True, code
    failed = row["failed_attempts"] + 1
    locked_until = now + 300 if failed >= 5 else 0
    record_login_failure(
        db_connection, code, 0 if locked_until else failed, locked_until
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
    row = fetch_profile_row(db_connection, code)
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
    update_profile_record(
        db_connection,
        st.session_state.active_player,
        profile["name"],
        json.dumps(profile, ensure_ascii=False),
    )
    st.session_state._profile_cache = {
        "code": st.session_state.active_player,
        "profile": profile,
        "loaded_at": time.time(),
    }




@st.cache_data(show_spinner=False)


@st.cache_data(show_spinner=False)








@st.cache_data(show_spinner=False)






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


def log_attempt(unit_id):
    if st.session_state.active_player == "__TEACHER__":
        return
    insert_attempt(
        db_connection,
        st.session_state.active_player,
        unit_id,
        st.session_state.stars,
        st.session_state.max_combo,
        st.session_state.correct,
        st.session_state.quiz_elapsed,
        st.session_state.quiz_elapsed / st.session_state.attempts
        if st.session_state.attempts
        else 0,
        database_timestamp(),
    )


def log_question_answer(unit_id, answer_row):
    """每答完一題立即保存，避免中途離開、斷線或部署更新造成紀錄遺失。"""
    if st.session_state.active_player == "__TEACHER__":
        return
    insert_question_log(
        db_connection, st.session_state.active_player, unit_id, answer_row
    )


def save_best_ranking(profile, clear_time, boss_type="normal", chapter_id="1"):
    code = st.session_state.active_player
    if code == "__TEACHER__":
        return
    save_best_boss_record(
        db_connection,
        code,
        profile["name"],
        profile["level"],
        clear_time,
        database_timestamp(),
        boss_type,
        chapter_id,
    )


def ranking_rows(boss_type="normal", chapter_id="1", include_private_identity=False):
    rows = fetch_boss_ranking_rows(db_connection, boss_type, chapter_id)
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
    rows = fetch_character_profiles(db_connection)
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
    rows = fetch_student_rows(db_connection)
    for row in rows:
        row["建立時間"] = taipei_time_text(row["建立時間"])
    return rows


def toggle_admin_progress_chapter(chapter_id):
    """老師後台章節排名手風琴；交由按鈕回呼避免額外重跑一次。"""
    current = st.session_state.get("admin_progress_chapter")
    st.session_state.admin_progress_chapter = None if current == chapter_id else chapter_id


def submit_game_feedback(student_code, category, message):
    create_feedback_record(
        db_connection, student_code, category, message.strip(), database_timestamp()
    )


def send_mail(student_code, subject, message, reward=None, claimed=False):
    reward_json = json.dumps(reward, ensure_ascii=False) if reward else None
    create_mail_record(
        db_connection,
        student_code,
        subject,
        message.strip(),
        reward_json,
        claimed,
        database_timestamp(),
    )


def mailbox_rows(student_code):
    rows = fetch_mail_rows(db_connection, student_code)
    for row in rows:
        row["reward"] = json.loads(row.pop("reward_json")) if row.get("reward_json") else None
        row["created_at"] = taipei_time_text(row["created_at"])
    return rows


def unread_mail_count(student_code):
    return count_unread_mail(db_connection, student_code)


def mark_mail_read(mail_id, student_code):
    set_mail_read(db_connection, mail_id, student_code)


def mark_all_mail_read(student_code):
    """將指定勇者的所有未讀信件標為已讀，不變更附件領取狀態。"""
    return set_all_mail_read(db_connection, student_code)


def claim_mail_reward(mail_id, student_code):
    row = fetch_mail_reward(db_connection, mail_id, student_code)
    if not row or row["is_claimed"] or not row["reward_json"]:
        return False
    reward = json.loads(row["reward_json"])
    profile = get_profile()
    profile["coins"] += int(reward.get("coins", 0))
    profile["sweep_tickets"] += int(reward.get("sweep_tickets", 0))
    profile["smelting_stones"] += int(reward.get("smelting_stones", 0))
    save_profile(profile)
    set_mail_claimed(db_connection, mail_id, student_code)
    return True


def game_feedback_rows():
    rows = fetch_feedback_rows(db_connection)
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
    set_feedback_replied(db_connection, feedback_id, database_timestamp())


def announcement_rows(active_only=False):
    rows = fetch_announcement_rows(db_connection, active_only)
    for row in rows:
        row["created_at_text"] = taipei_time_text(row["created_at"])
    return rows


def create_announcement(title, content):
    create_announcement_record(
        db_connection, title.strip(), content.strip(), database_timestamp()
    )


def set_announcement_active(announcement_id, is_active):
    set_announcement_status(db_connection, announcement_id, is_active)


def update_and_activate_announcement(announcement_id, title, content):
    """儲存舊公告的修改內容、更新發布時間並立即重新啟用。"""
    update_announcement_record(
        db_connection,
        announcement_id,
        title.strip(),
        content.strip(),
        database_timestamp(),
    )


def delete_announcement(announcement_id):
    delete_announcement_record(db_connection, announcement_id)


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
    reset_student_pin_record(db_connection, code, salt, digest)
    return pin


def update_student_real_name(code, real_name):
    update_student_real_name_record(db_connection, code, real_name)


def student_learning_detail(code):
    row = fetch_student_learning_detail(db_connection, code)
    if not row:
        return None
    return normalize_profile(json.loads(row["profile_json"]), row["hero_name"])


def student_question_rows(code, errors_only=False, limit=200):
    rows = fetch_student_question_rows(db_connection, code, errors_only, limit)
    for row in rows:
        row["是否答對"] = "✅" if row["是否答對"] else "❌"
        row["作答時間"] = taipei_time_text(row["作答時間"])
    return rows


def delete_student(code):
    delete_student_record(db_connection, code)


def add_exp(profile, amount):
    return add_experience(profile, amount)


def current_daily_period():
    now = datetime.now(TAIPEI_TZ)
    if now.hour < 8:
        now -= timedelta(days=1)
    return now.strftime("%Y-%m-%d")


def current_midnight_period():
    return datetime.now(TAIPEI_TZ).strftime("%Y-%m-%d")


def highest_unlocked_chapter(profile):
    return highest_unlocked_chapter_id(profile)


def sync_daily_tasks(profile):
    return sync_daily_task_periods(
        profile, current_daily_period(), current_midnight_period()
    )


def award_unit_ticket(profile, unit_id):
    return award_first_clear_ticket(profile, unit_id)


def permanent_task_definitions():
    return build_permanent_task_definitions(CHAPTERS, UNITS, chapter_unit_ids)


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
    apply_task_reward(profile, task)


def visible_permanent_tasks(profile):
    all_tasks = permanent_task_definitions()
    return visible_permanent_task_rows(profile, all_tasks, CHAPTERS)


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
    return boss_unlocked(profile, chapter_id, boss_type, chapter_unit_ids)


def go_to_boss(chapter_id, boss_type):
    st.session_state.selected_chapter = chapter_id
    st.session_state.selected_boss_type = boss_type
    st.session_state.scroll_boss_to_top = True
    st.session_state.screen = "boss_ready"


def item_signature(item):
    return loot_item_signature(item)


def make_random_item(profile, unit_id, stars):
    return make_random_drop(
        profile, unit_id, stars, UNITS, AFFIX_NAMES, AFFIX_VALUES,
        GEAR_NAMES, fixed_value_for,
    )


def highest_shop_chapter(profile):
    """商店依已經實際通關過的最高章節提供裝備。"""
    return highest_shop_chapter_id(profile, CHAPTERS, chapter_unit_ids)


def make_shop_item(profile, chapter_id=None):
    return make_shop_inventory_item(
        profile, CHAPTERS, UNITS, chapter_unit_ids, SLOT_NAMES, AFFIX_NAMES,
        AFFIX_VALUES, GEAR_NAMES, fixed_value_for, chapter_id,
    )


def shop_paid_refresh_cost(profile):
    """每五次強制刷新費用加倍：1～5次100、6～10次200，依此類推。"""
    return paid_shop_refresh_cost(profile)


def refresh_shop(profile, paid=False):
    return refresh_shop_inventory(
        profile, CHAPTERS, UNITS, chapter_unit_ids, SLOT_NAMES, AFFIX_NAMES,
        AFFIX_VALUES, GEAR_NAMES, fixed_value_for, paid=paid,
    )


def ensure_shop(profile):
    return ensure_shop_inventory(
        profile, CHAPTERS, UNITS, chapter_unit_ids, SLOT_NAMES, AFFIX_NAMES,
        AFFIX_VALUES, GEAR_NAMES, fixed_value_for,
    )


def remove_inventory_items(profile, uids):
    remove_inventory_entries(profile, uids)


def make_forged_item(profile, source_stars, chapter_id, selected_slot=None, selected_affix=None):
    return make_forged_inventory_item(
        profile, source_stars, chapter_id, chapter_unit_ids, UNITS, GEAR_NAMES,
        AFFIX_VALUES, fixed_value_for, make_random_item,
        selected_slot=selected_slot, selected_affix=selected_affix,
    )


def make_chapter_reward():
    return make_achievement_reward("1", "chapter", fixed_value_for, four_star_item_name)


def make_elite_reward():
    return make_achievement_reward("1", "elite", fixed_value_for, four_star_item_name)


def make_collection_reward():
    return make_achievement_reward("1", "collection", fixed_value_for, four_star_item_name)


def make_chapter2_reward():
    return make_achievement_reward("2", "chapter", fixed_value_for, four_star_item_name)


def make_chapter2_collection_reward():
    return make_achievement_reward("2", "collection", fixed_value_for, four_star_item_name)


def make_chapter2_elite_reward():
    return make_achievement_reward("2", "elite", fixed_value_for, four_star_item_name)


def make_chapter3_reward():
    return make_achievement_reward("3", "chapter", fixed_value_for, four_star_item_name)


def make_chapter3_collection_reward():
    return make_achievement_reward("3", "collection", fixed_value_for, four_star_item_name)


def make_chapter3_elite_reward():
    return make_achievement_reward("3", "elite", fixed_value_for, four_star_item_name)


def make_chapter4_reward():
    return make_achievement_reward("4", "chapter", fixed_value_for, four_star_item_name)


def make_chapter4_collection_reward():
    return make_achievement_reward("4", "collection", fixed_value_for, four_star_item_name)


def make_chapter4_elite_reward():
    return make_achievement_reward("4", "elite", fixed_value_for, four_star_item_name)


def make_chapter5_reward():
    return make_achievement_reward("5", "chapter", fixed_value_for, four_star_item_name)


def make_chapter5_collection_reward():
    return make_achievement_reward("5", "collection", fixed_value_for, four_star_item_name)


def make_chapter5_elite_reward():
    return make_achievement_reward("5", "elite", fixed_value_for, four_star_item_name)


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
    return sync_four_star_item_name(
        item, CHAPTERS, item_chapter_id, four_star_item_name
    )


def sync_collection_catalog(profile):
    """把目前物品登錄為永久收藏；只增加紀錄，永不因移除物品而倒退。"""
    sync_profile_collection_catalog(profile, item_chapter_id)


def collected_three_star_slots(profile, chapter_id="1"):
    return loot_collected_three_star_slots(
        profile, chapter_id, SLOT_NAMES, item_chapter_id
    )


def has_full_three_star_set(profile, chapter_id="1"):
    return has_full_three_star_collection(
        profile, chapter_id, SLOT_NAMES, item_chapter_id
    )


def find_item(profile, uid):
    return find_inventory_item(profile, uid)


def achievement_item(profile, unit_key):
    return find_achievement_item(profile, unit_key)


def achievement_was_collected(profile, unit_key, stars=4):
    return loot_achievement_was_collected(profile, unit_key, stars)


def collected_achievement_slots(profile, stars=4):
    return loot_collected_achievement_slots(profile, stars)


def sync_achievement_item(profile, unit_key, maker):
    """讓舊存檔中的成就裝備跟隨新版部位與固定數值，且不遺失穿戴狀態。"""
    return sync_loot_achievement_item(profile, unit_key, maker)


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
def boss_has_been_cleared(profile, chapter_id, boss_type):
    """是否曾經成功擊敗這一章、這一類 BOSS。"""
    return int(profile.get(BOSS_WIN_KEYS[(chapter_id, boss_type)], 0) or 0) > 0






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
    teacher_default_name = fetch_teacher_name(db_connection) or "老師測試勇者"
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
        attempts = fetch_recent_attempts(db_connection, 200)
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
    render_compact_avatar_editor(profile, save_profile)

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
    chapter_id, current_unit_ids = render_chapter_selector(
        profile, available_chapters, chapter_unit_ids
    )
    render_unit_cards(
        profile,
        current_unit_ids,
        unit_unlocked,
        start_quiz,
        make_random_item,
        save_profile,
    )
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
    render_chapter_reward_status(profile, chapter_id)
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
            f"每件{SHOP_ITEM_PRICE}金幣。自動刷新剩餘約 {hours}小時{minutes}分。"
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
                        f"🪙 {SHOP_ITEM_PRICE}｜購買",
                        disabled=profile["coins"] < SHOP_ITEM_PRICE,
                        key=f"buy_{entry['shop_id']}", use_container_width=True,
                    ):
                        if purchase_shop_entry(profile, entry):
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
                    f"用{SPECIAL_STONE_CRAFT_COST}顆融煉石合成",
                    key=f"craft_{key}",
                    disabled=profile["smelting_stones"] < SPECIAL_STONE_CRAFT_COST,
                    use_container_width=True,
                ):
                    if craft_special_stone(profile, key):
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
        basic_affixes = list(BASIC_AFFIXES)
        advanced_affixes = [key for key in AFFIX_NAMES if key not in BASIC_AFFIXES]
        selected_affix = None
        if special_stone_type == "基礎詞條熔煉石":
            selected_affix = st.selectbox(
                "指定基礎詞條", basic_affixes, format_func=lambda key: AFFIX_NAMES[key]
            )
        elif special_stone_type == "進階詞條熔煉石":
            selected_affix = st.selectbox(
                "指定進階詞條", advanced_affixes, format_func=lambda key: AFFIX_NAMES[key]
            )
        required_special_stone = SPECIAL_STONE_KEYS[special_stone_type]
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
        render_backpack(profile, save_profile)
    if inventory_view == "gallery":
        render_gallery(profile, chapter_unit_ids, unit_unlocked, start_quiz)
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
    render_quiz_panel(submit_quiz_answer)

elif st.session_state.screen == "quiz_result":
    process_rewards()
    profile = get_profile()
    render_quiz_result(profile, save_profile, start_quiz)

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
