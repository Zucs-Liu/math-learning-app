"""Character equipment hub: loadouts, inventory gear, pets and titles."""

from pathlib import Path

import streamlit as st

from game_data.config import SLOT_ICONS, SLOT_NAMES
from game_logic.economy import dismantle_inventory_items, dismantle_value
from game_logic.equipment import item_text, player_stats
from game_logic.loot import find_inventory_item as find_item
from game_logic.profile import equipped_item_uids
from game_logic.pets import (
    PET_ADVANCE_SOUL_COSTS,
    PET_TOTAL,
    advance_pet,
    ensure_pet_profile,
    equipped_pet,
    owned_pet_entries,
    pet_asset_path,
    pet_details,
    use_pet_training_item,
)
from game_ui.profile import render_item_comparison


LEFT_SLOTS = ("helmet", "necklace", "weapon", "gloves", "ring")
RIGHT_SLOTS = ("armor", "shield", "belt", "boots")
def _candidate_option_text(item):
    """Return a compact two-line label that fits the portrait select menu."""
    text = item_text(item).replace("｜固定：", "\n").replace("｜詞條：", "｜")
    replacements = {
        "菁英BOSS初始血量降低": "菁英血量降低",
        "第一擊額外扣除菁英BOSS血量": "首擊扣血",
        "對菁英BOSS傷害": "菁英傷害",
        "菁英BOSS攻速降低": "菁英攻速降低",
        "攻擊速度": "攻速",
        "傷害減免": "減傷",
        "暴擊率": "暴率",
        "暴擊傷害": "暴傷",
        "開場護盾": "護盾",
    }
    for original, compact in replacements.items():
        text = text.replace(original, compact)
    return text.replace(" +", "+")


def _equipment_slot(profile, slot, key_prefix):
    uid = profile["equipment"].get(slot)
    item = find_item(profile, uid) if uid else None
    # 空格也顯示部位圖示，讓玩家不必靠文字辨認格子用途。
    icon = SLOT_ICONS[slot]
    with st.container(key=f"character_slot_{key_prefix}_{slot}"):
        if st.button(
            icon,
            key=f"{key_prefix}_slot_{slot}",
            help=f"{SLOT_NAMES[slot]}（點擊查看或更換）",
            use_container_width=True,
        ):
            st.session_state.character_selected_slot = slot
            # 每次重新點擊部位都先回到「目前裝備」畫面；不要沿用上次
            # 已選取的候選裝備，否則會直接跳過卸下／返回這一層。
            st.session_state.pop(f"character_slot_candidate_{slot}", None)
            st.rerun()


def _switch_loadout(profile, selected, save_profile):
    active = int(profile.get("active_equipment_loadout", 0))
    loadouts = profile["equipment_loadouts"]
    if selected != active:
        loadouts[active]["equipment"] = dict(profile["equipment"])
        profile["active_equipment_loadout"] = selected
        profile["equipment"] = dict(loadouts[selected]["equipment"])
        st.session_state.character_panel_view = "equipment"
        save_profile(profile)
        st.rerun()


def _render_panel_navigation(profile, save_profile):
    if "character_panel_view" not in st.session_state:
        st.session_state.character_panel_view = "equipment"
    active = int(profile.get("active_equipment_loadout", 0))
    loadouts = profile["equipment_loadouts"]
    with st.container(key="character_panel_navigation"):
        equipment_col, unused_col, pet_col, title_col = st.columns(4)
        with equipment_col:
            with st.container(key="character_nav_equipment"):
                if st.session_state.character_panel_view != "equipment":
                    if st.button(loadouts[active]["name"], key="show_character_equipment", use_container_width=True):
                        st.session_state.character_panel_view = "equipment"
                        st.session_state.character_selected_slot = None
                        st.rerun()
                else:
                    with st.popover(loadouts[active]["name"], use_container_width=True):
                        selected = st.selectbox(
                            "切換裝備配置", [0, 1], index=active,
                            format_func=lambda index: loadouts[index]["name"],
                            key="character_loadout_choice",
                        )
                        _switch_loadout(profile, selected, save_profile)
                        new_name = st.text_input(
                            "更改此套裝備名稱", value=loadouts[active]["name"],
                            max_chars=16, key=f"character_loadout_name_{active}",
                        ).strip()
                        if st.button("儲存名稱", key=f"save_loadout_name_{active}", use_container_width=True):
                            if new_name:
                                loadouts[active]["name"] = new_name
                                save_profile(profile)
                                st.rerun()
        with unused_col:
            with st.container(key="character_nav_unused"):
                if st.button(
                    "未使用裝備", key="show_character_unused",
                    type="primary" if st.session_state.character_panel_view == "unused" else "secondary",
                    use_container_width=True,
                ):
                    st.session_state.character_panel_view = "unused"
                    st.rerun()
        with pet_col:
            with st.container(key="character_nav_pet"):
                if st.button(
                    "寵物", key="show_character_pet",
                    type="primary" if st.session_state.character_panel_view == "pet" else "secondary",
                    use_container_width=True,
                ):
                    st.session_state.character_panel_view = "pet"
                    st.rerun()
        with title_col:
            with st.container(key="character_nav_titles"):
                if st.button(
                    "稱號", key="show_character_titles",
                    type="primary" if st.session_state.character_panel_view == "titles" else "secondary",
                    use_container_width=True,
                ):
                    st.session_state.character_panel_view = "titles"
                    st.rerun()


def _render_slot_selector(profile, slot, save_profile):
    current_uid = profile["equipment"].get(slot)
    current_item = find_item(profile, current_uid) if current_uid else None
    candidate_key = f"character_slot_candidate_{slot}"

    def return_to_character():
        st.session_state.pop(candidate_key, None)
        st.session_state.character_selected_slot = None

    st.markdown(f"#### {SLOT_ICONS[slot]} {SLOT_NAMES[slot]}")

    # 「未使用」只列出沒有穿在目前部位上的裝備。
    candidates = [
        item for item in profile["inventory"]
        if item["slot"] == slot and item["uid"] != current_uid
    ]
    candidate_uids = {item["uid"] for item in candidates}
    selected_uid = st.session_state.get(candidate_key)
    if selected_uid not in candidate_uids:
        selected_uid = None
        st.session_state.pop(candidate_key, None)

    if selected_uid is None:
        # 第一階段：只顯示目前裝備與「卸下／返回」。
        if current_item:
            st.caption("目前裝備")
            st.markdown(
                f"<div class='character-current-item'>{item_text(current_item)}</div>",
                unsafe_allow_html=True,
            )
        else:
            st.caption("目前尚未裝備")

        if candidates:
            st.selectbox(
                "選擇未使用裝備",
                [item["uid"] for item in candidates],
                index=None,
                placeholder="點擊箭頭查看未使用裝備",
                # 清單採兩行精簡顯示；選定後，下方仍會顯示完整能力。
                format_func=lambda uid: _candidate_option_text(find_item(profile, uid)),
                key=candidate_key,
            )
        else:
            st.caption("此部位目前沒有其他未使用裝備。")

        with st.container(
            key="character_slot_actions", horizontal=True,
            horizontal_alignment="center", vertical_alignment="center", gap="small",
        ):
            if current_item and st.button(
                "卸下", key=f"character_slot_remove_{slot}", width="stretch",
            ):
                profile["equipment"][slot] = None
                save_profile(profile)
                return_to_character()
                st.rerun()
            if st.button("返回", key=f"character_slot_close_{slot}", width="stretch"):
                return_to_character()
                st.rerun()
        return

    # 第二階段：選好候選裝備後，只顯示「更換／返回」。
    selected_item = find_item(profile, selected_uid)
    st.caption("更換為")
    st.markdown(
        f"<div class='character-candidate-item'>{item_text(selected_item)}</div>",
        unsafe_allow_html=True,
    )
    with st.container(
        key="character_slot_actions", horizontal=True,
        horizontal_alignment="center", vertical_alignment="center", gap="small",
    ):
        if st.button(
            "更換", key=f"character_slot_replace_{slot}", type="primary", width="stretch",
        ):
            profile["equipment"][slot] = selected_uid
            save_profile(profile)
            return_to_character()
            st.rerun()
        if st.button("返回", key=f"character_slot_candidate_close_{slot}", width="stretch"):
            return_to_character()
            st.rerun()


def _render_equipment_scene(profile, save_profile):
    current_pet = equipped_pet(profile)
    st.markdown(
        """
        <style>
        .st-key-character_equipment_scene [data-testid="stHorizontalBlock"]:has(.st-key-character_left_slots) {
          display:flex !important; flex-direction:row !important; flex-wrap:nowrap !important;
          gap:.45rem !important; align-items:flex-start !important;justify-content:center !important;
        }
        .st-key-character_equipment_scene [data-testid="stColumn"]:has(.st-key-character_left_slots),
        .st-key-character_equipment_scene [data-testid="stColumn"]:has(.st-key-character_right_slots) {
          flex:0 0 4.15rem !important;width:4.15rem !important;max-width:4.15rem !important;min-width:0 !important;
        }
        .st-key-character_equipment_scene [data-testid="stColumn"]:has(.st-key-character_center_panel) {
          flex:1 1 34rem !important;width:auto !important;max-width:34rem !important;min-width:0 !important;
        }
        .st-key-character_left_slots > [data-testid="stVerticalBlock"],
        .st-key-character_right_slots > [data-testid="stVerticalBlock"] {
          gap:.16rem !important;
        }
        .st-key-character_equipment_scene [data-testid="stImage"] img {
          max-height:15.5rem; object-fit:contain;
        }
        .st-key-character_equipment_scene [data-testid="stVerticalBlockBorderWrapper"] {
          background:linear-gradient(145deg,rgba(250,245,225,.96),rgba(238,226,187,.92));
          min-height:0;
        }
        .st-key-character_center_panel {
          height:16rem !important;min-height:16rem !important;max-height:16rem !important;
        }
        .st-key-character_center_panel [data-testid="stVerticalBlock"] {gap:.28rem !important;}
        .st-key-character_center_panel h4 {font-size:1rem !important;margin:.05rem 0 !important;}
        .st-key-character_center_panel p,
        .st-key-character_center_panel label,
        .st-key-character_center_panel [data-baseweb="select"] {font-size:.78rem !important;line-height:1.15 !important;}
        .st-key-character_center_panel button {min-height:2rem !important;padding:.18rem .25rem !important;font-size:.72rem !important;}
        .st-key-character_center_panel [data-testid="stSelectbox"] {margin-bottom:0 !important;}
        .st-key-character_center_panel [data-testid="stSelectbox"] > div {margin-top:.1rem !important;}
        .st-key-character_center_panel [data-baseweb="select"] > div {min-height:2.15rem !important;}
        .st-key-character_center_panel [data-testid="stMarkdownContainer"] p {margin:.05rem 0 !important;}
        .character-current-item,
        .character-candidate-item {
          width:100% !important;max-width:100% !important;box-sizing:border-box !important;
          white-space:normal !important;overflow-wrap:anywhere !important;word-break:break-word !important;
          line-height:1.28 !important;margin:.08rem 0 .16rem !important;
        }
        .st-key-character_center_panel [data-testid="stImage"] img {max-height:13.6rem !important;}
        .st-key-character_center_panel [data-testid="stImage"] {
          display:flex !important;justify-content:center !important;align-items:flex-start !important;width:100% !important;
        }
        .st-key-character_slot_actions [data-testid="stHorizontalBlock"] {
          display:flex !important;flex-direction:row !important;flex-wrap:nowrap !important;gap:.18rem !important;
          height:2rem !important;min-height:2rem !important;max-height:2rem !important;
        }
        .st-key-character_slot_actions {
          display:flex !important;flex-direction:row !important;flex-wrap:nowrap !important;
          align-items:center !important;gap:.18rem !important;width:100% !important;
          height:2rem !important;min-height:2rem !important;max-height:2rem !important;
        }
        .st-key-character_slot_actions > div,
        .st-key-character_slot_actions [class*="st-key-character_slot_equip_"],
        .st-key-character_slot_actions [class*="st-key-character_slot_remove_"],
        .st-key-character_slot_actions [class*="st-key-character_slot_close_"],
        .st-key-character_slot_actions [class*="st-key-character_slot_replace_"],
        .st-key-character_slot_actions [class*="st-key-character_slot_candidate_close_"] {
          flex:1 1 0 !important;min-width:0 !important;width:auto !important;
          height:2rem !important;min-height:2rem !important;max-height:2rem !important;
        }
        .st-key-character_slot_actions [data-testid="stColumn"] {
          min-width:0 !important;flex:1 1 0 !important;width:auto !important;
          height:2rem !important;min-height:2rem !important;max-height:2rem !important;
        }
        .st-key-character_slot_actions button {
          width:100% !important;height:2rem !important;min-height:2rem !important;max-height:2rem !important;
          padding:.08rem .03rem !important;
          font-size:.66rem !important;white-space:nowrap !important;
        }
        @media (min-width:769px) {
          [class*="st-key-character_slot_"] button p {font-size:1.85rem !important;}
        }
        @media (max-width:768px) and (orientation:portrait) {
          .st-key-character_equipment_scene [data-testid="stHorizontalBlock"]:has(.st-key-character_left_slots) {
            /* 人物／裝備區只佔分頁列與底部能力欄之間，不得穿過能力欄。 */
            position:absolute !important;inset:.08rem 0 33.333dvh 0 !important;
            display:flex !important;
            flex-direction:row !important;
            flex-wrap:nowrap !important;
            gap:.12rem !important;margin:0 !important;padding:0 !important;
            width:100% !important;height:auto !important;max-height:none !important;
            align-items:stretch !important;
          }
          .st-key-character_equipment_scene [data-testid="stLayoutWrapper"]:has(> .st-key-character_left_slots),
          .st-key-character_equipment_scene [data-testid="stLayoutWrapper"]:has(> .st-key-character_right_slots),
          .st-key-character_equipment_scene [data-testid="stLayoutWrapper"]:has(> .st-key-character_center_panel) {
            height:100% !important;min-height:0 !important;max-height:100% !important;
            flex:1 1 100% !important;
          }
          .st-key-character_equipment_scene [data-testid="stColumn"]:has(.st-key-character_left_slots),
          .st-key-character_equipment_scene [data-testid="stColumn"]:has(.st-key-character_right_slots) {
            flex:0 0 clamp(2.15rem,calc((100dvh - 10.5rem)/5),3rem) !important;
            width:clamp(2.15rem,calc((100dvh - 10.5rem)/5),3rem) !important;
            max-width:3rem !important;height:100% !important;
          }
          .st-key-character_equipment_scene [data-testid="stColumn"]:has(.st-key-character_center_panel) {
            flex:1 1 auto !important;width:auto !important;max-width:none !important;
          }
          .st-key-character_left_slots > [data-testid="stVerticalBlock"],
          .st-key-character_right_slots > [data-testid="stVerticalBlock"] {
            height:100% !important;justify-content:space-between !important;gap:.08rem !important;
          }
          .st-key-character_left_slots,
          .st-key-character_right_slots {
            display:flex !important;flex-direction:column !important;
            justify-content:space-between !important;gap:.08rem !important;
            height:100% !important;min-height:0 !important;
          }
          .st-key-character_equipment_scene p,
          .st-key-character_equipment_scene button {font-size:.62rem !important;line-height:1.05 !important;}
          .st-key-character_equipment_scene [data-testid="stImage"] img {
            width:auto !important;height:8.6rem !important;max-height:8.6rem !important;
            object-fit:contain !important;margin:0 auto !important;
          }
          .st-key-character_center_panel {
            position:relative !important;
            height:100% !important;min-height:0 !important;max-height:100% !important;
            margin:0 !important;padding:0 !important;
          }
          .st-key-character_center_panel > [data-testid="stVerticalBlock"] {
            height:100% !important;justify-content:flex-start !important;gap:.04rem !important;
            padding-top:2rem !important;box-sizing:border-box !important;
          }
          .character-hero-name {
            position:absolute !important;top:0 !important;left:0 !important;right:0 !important;
            z-index:3 !important;text-align:center !important;line-height:1.2 !important;
          }
          .st-key-character_center_panel [data-testid="stElementContainer"]:has([data-testid="stImage"]) {
            position:absolute !important;top:1.85rem !important;right:.12rem !important;
            bottom:.18rem !important;left:.12rem !important;
            display:flex !important;justify-content:center !important;align-items:center !important;
            width:auto !important;height:auto !important;margin:0 !important;padding:0 !important;
          }
          .st-key-character_center_panel [data-testid="stImage"] img {
            display:block !important;width:100% !important;height:100% !important;
            max-width:100% !important;max-height:100% !important;
            object-fit:contain !important;image-rendering:auto !important;margin:auto !important;
          }
          .st-key-character_center_panel [data-testid="stImage"] {
            position:static !important;
            display:flex !important;justify-content:center !important;align-items:center !important;
            width:100% !important;height:100% !important;margin:0 !important;padding:0 !important;
          }
          .st-key-character_center_panel [data-testid="stFullScreenFrame"],
          .st-key-character_center_panel [data-testid="stFullScreenFrame"] > div {
            display:flex !important;justify-content:center !important;align-items:center !important;
            width:100% !important;height:100% !important;margin:0 !important;
          }
          .st-key-character_center_panel [data-testid="stImage"] > div {
            display:flex !important;justify-content:center !important;width:100% !important;
          }
          .st-key-character_center_panel h4 {
            font-size:.78rem !important;line-height:1 !important;margin:0 0 .02rem !important;
          }
          .st-key-character_center_panel p,
          .st-key-character_center_panel label,
          .st-key-character_center_panel [data-baseweb="select"] {font-size:.61rem !important;}
          .st-key-character_center_panel button {font-size:.58rem !important;min-height:1.75rem !important;padding:.08rem !important;}
        }
        [class*="st-key-character_slot_"] button {
          aspect-ratio:1/1 !important;width:100% !important;min-height:0 !important;
          height:auto !important;font-size:clamp(1.5rem,5vw,2.15rem) !important;padding:.04rem !important;
        }
        [class*="st-key-character_slot_"] button p {
          font-size:clamp(1.65rem,7vw,2.15rem) !important;line-height:1 !important;
        }
        /* 寵物第十格使用真正的 PNG 小圖。透明按鈕覆蓋圖片，保留原本
           點擊進入寵物分頁的行為，也避開雲端瀏覽器阻擋 CSS data URI。 */
        .st-key-character_slot_right_pet {
          position:relative !important;aspect-ratio:1/1 !important;
          width:100% !important;min-height:0 !important;overflow:hidden !important;
          border:1px solid #d6dce5 !important;border-radius:.55rem !important;background:#fff !important;
        }
        .st-key-character_slot_right_pet > [data-testid="stElementContainer"]:has([data-testid="stImage"]) {
          position:absolute !important;inset:.12rem !important;z-index:4 !important;
          width:auto !important;height:auto !important;margin:0 !important;
          pointer-events:none !important;
        }
        .st-key-character_slot_right_pet > [data-testid="stElementContainer"]:has([data-testid="stImage"])
        > [data-testid="stFullScreenFrame"] {
          width:100% !important;height:100% !important;
        }
        .st-key-character_slot_right_pet [data-testid="stImage"] {
          position:relative !important;inset:auto !important;z-index:4 !important;
          width:100% !important;height:100% !important;margin:0 !important;pointer-events:none !important;
        }
        .st-key-character_slot_right_pet [data-testid="stImage"] > div,
        .st-key-character_slot_right_pet [data-testid="stFullScreenFrame"] {
          width:100% !important;height:100% !important;
        }
        .st-key-character_slot_right_pet [data-testid="stImage"] img {
          display:block !important;width:100% !important;height:100% !important;
          max-width:100% !important;max-height:100% !important;object-fit:contain !important;
        }
        .st-key-character_slot_right_pet .character-equipped-pet-icon {
          position:absolute !important;inset:.12rem !important;z-index:2 !important;
          display:block !important;width:calc(100% - .24rem) !important;
          height:calc(100% - .24rem) !important;object-fit:contain !important;
          pointer-events:none !important;
        }
        .st-key-character_pet_equipment_slot {
          position:absolute !important;inset:0 !important;z-index:3 !important;
          width:100% !important;height:100% !important;margin:0 !important;
          background:transparent !important;
        }
        .st-key-character_pet_equipment_slot > div,
        .st-key-character_pet_equipment_slot [data-testid="stElementContainer"] {
          background:transparent !important;
        }
        .st-key-character_pet_equipment_slot button {
          width:100% !important;height:100% !important;min-height:0 !important;
          opacity:0 !important;cursor:pointer !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    with st.container(key="character_equipment_scene"):
        left, hero, right = st.columns([3, 3.4, 3], vertical_alignment="top")
        with left:
            with st.container(key="character_left_slots"):
                for slot in LEFT_SLOTS:
                    _equipment_slot(profile, slot, "left")
        with hero:
            with st.container(key="character_center_panel", height=190, border=False):
                st.markdown(
                    f"<div class='character-hero-name' style='font-weight:800'>Lv{profile['level']}　{profile['name']}</div>",
                    unsafe_allow_html=True,
                )
                selected_slot = st.session_state.get("character_selected_slot")
                if selected_slot in SLOT_NAMES:
                    _render_slot_selector(profile, selected_slot, save_profile)
                else:
                    hero_file = (
                        "blue-silver-hero-female-hd.png"
                        if profile.get("gender") == "female"
                        else "blue-silver-hero-hd.png"
                    )
                    hero_path = Path(__file__).resolve().parent.parent / "assets" / "heroes" / hero_file
                    # Keep the original high-resolution media.  A small numeric width
                    # makes Streamlit downsample the file before CSS enlarges it,
                    # which leaves the hero visibly blurred in the dialog.
                    st.image(str(hero_path), width="stretch")
        with right:
            with st.container(key="character_right_slots"):
                for slot in RIGHT_SLOTS:
                    _equipment_slot(profile, slot, "right")
                with st.container(key="character_slot_right_pet"):
                    pet_help = (
                        f"跟隨寵物：{current_pet['display_name']}（點擊查看）"
                        if current_pet else "尚未跟隨寵物（點擊查看）"
                    )
                    if current_pet:
                        # Use Streamlit's native media pipeline.  Raw data-URI images
                        # can be filtered or detached from their positioned parent on
                        # Community Cloud/mobile, leaving an apparently empty slot.
                        st.image(
                            str(pet_asset_path(current_pet, "icon")),
                            width="stretch",
                        )
                    if st.button(
                        "檢視寵物" if current_pet else "🐾",
                        key="character_pet_equipment_slot",
                        help=pet_help,
                        use_container_width=True,
                    ):
                        if current_pet:
                            st.session_state.character_pet_selected_id = current_pet["id"]
                        st.session_state.character_panel_view = "pet"
                        st.session_state.character_selected_slot = None
                        st.rerun()


def _render_compact_stats(profile):
    stats = player_stats(profile)
    current_pet = equipped_pet(profile)
    special_specs = [
        ("菁英BOSS初始血量降低", stats["boss_hp_reduction"]),
        ("第一擊額外扣除菁英BOSS血量", stats["first_hit_percent"]),
        ("對菁英BOSS傷害", stats["boss_damage_pct"]),
        ("傷害減免", stats["damage_reduction_pct"]),
        ("暴擊率", stats["critical_rate"]),
        ("暴擊傷害", stats["critical_damage"]),
        ("開場護盾", stats["shield_pct"]),
        ("菁英BOSS攻速降低", stats["boss_attack_slow_pct"]),
    ]
    active_effects = [
        f"<div><b>{name}</b><span>+{value:.0%}</span></div>"
        for name, value in special_specs if value
    ]
    if current_pet:
        active_effects.extend(
            [
                (
                    "<div><b>寵物・額外裝備掉落機率</b>"
                    f"<span>+{current_pet['drop_bonus_pct']:.0%}</span></div>"
                ),
                (
                    "<div><b>寵物・攻擊屬性</b>"
                    f"<span>{current_pet['element_name']}</span></div>"
                ),
                (
                    "<div><b>寵物・分解裝備金幣</b>"
                    f"<span>{'+20%' if int(current_pet.get('stars', 1)) >= 2 else '未解鎖'}</span></div>"
                ),
                (
                    "<div><b>寵物・三星主動技能</b>"
                    f"<span>{current_pet['skill']['name'] if int(current_pet.get('stars', 1)) >= 3 else '未解鎖'}</span></div>"
                ),
            ]
        )
        bonus_labels = (
            ("hp_pct", "寵物・HP加成", "+25%"),
            ("attack_pct", "寵物・攻擊加成", "+25%"),
            ("defense_pct", "寵物・防禦加成", "+25%"),
            ("attack_speed_flat", "寵物・攻速加成", "+0.250/秒"),
        )
        for key, label, display in bonus_labels:
            if current_pet.get("unlocked_bonuses", {}).get(key):
                active_effects.append(f"<div><b>{label}</b><span>{display}</span></div>")
    if not active_effects:
        active_effects = ["<div><b>目前無特殊詞條</b><span>—</span></div>"]
    exp_text = (
        f"{profile['exp']} / {profile['level'] * 100}"
        if profile["level"] < 20 else "已滿級"
    )
    attack_label = "攻擊"
    attack_row_style = ""
    if current_pet:
        attack_label += f"（{current_pet['element_name']}屬性）"
        attack_row_style = (
            f" style=\"border-top:2px solid {current_pet['element_color']};"
            f"border-bottom:2px solid {current_pet['element_color']};\""
        )
    st.markdown(
        f"""
        <style>
        .character-stat-panels {{display:grid;grid-template-columns:1fr 1fr;gap:.5rem;margin-top:.38rem;}}
        .character-stat-box {{border:1px solid #d6dce5;border-radius:8px;padding:.5rem;background:#fff;min-width:0;color:#1f2937 !important;}}
        .character-stat-box * {{color:#1f2937 !important;}}
        .character-stat-box h4 {{margin:0 0 .45rem;font-size:1rem;}}
        .character-stat-list {{max-height:8.2rem;overflow-y:auto;padding-right:.2rem;}}
        .character-stat-list div {{display:flex;justify-content:space-between;gap:.4rem;padding:.13rem 0;border-bottom:1px solid #edf0f4;font-size:.82rem;}}
        .character-stat-list div:last-child {{border-bottom:0;}}
        .character-stat-list span {{white-space:nowrap;font-weight:700;}}
        @media (max-width:768px) and (orientation:portrait) {{
          .character-stat-panels {{
            gap:.22rem;margin:0;height:100% !important;
            min-height:0 !important;
          }}
          .character-stat-box {{
            display:flex;flex-direction:column;
            height:100%;min-height:0;padding:.18rem .28rem;border-radius:5px;box-sizing:border-box;
            overflow:hidden;isolation:isolate;
          }}
          .character-stat-box h4 {{
            display:flex;align-items:center;justify-content:center;
            flex:0 0 2.15rem;font-size:clamp(.9rem,3.8vw,1.08rem);
            line-height:1;margin:0;text-align:center;
          }}
          .character-stat-list {{
            position:relative;z-index:20;display:block;
            flex:1 1 auto;width:100%;height:auto;max-height:none;min-height:0;
            overflow-x:hidden;overflow-y:scroll !important;
            overscroll-behavior-y:contain;touch-action:pan-y !important;
            -webkit-overflow-scrolling:touch;
            pointer-events:auto !important;padding:0;box-sizing:border-box;
            scrollbar-gutter:stable;
          }}
          .character-stat-list {{scrollbar-width:thin;scrollbar-color:#9ca3af transparent;}}
          .character-stat-list::-webkit-scrollbar {{width:4px;}}
          .character-stat-list::-webkit-scrollbar-thumb {{background:#9ca3af;border-radius:999px;}}
          .character-stat-list div {{
            display:flex;align-items:center;justify-content:space-between;
            box-sizing:border-box;height:auto;min-height:0;
            font-size:clamp(.72rem,3.1vw,.92rem);line-height:1.05;padding:.05rem 0;
          }}
          .character-stat-list-basic {{
            display:grid !important;grid-template-rows:repeat(6,minmax(0,1fr));
            overflow-y:hidden !important;
          }}
          .character-stat-list-basic div {{height:auto !important;min-height:0 !important;}}
          .character-stat-list-special > div {{
            min-height:calc(100% / 6);height:auto;flex-shrink:0;
          }}
          .character-stat-list div b {{min-width:0;line-height:1.12;overflow-wrap:anywhere;}}
          .character-stat-box:nth-child(2) .character-stat-list div {{align-items:center;padding:.12rem 0;}}
        }}
        </style>
        <div class="character-stat-panels">
          <section class="character-stat-box">
            <h4>基礎能力</h4>
            <div class="character-stat-list character-stat-list-basic">
              <div><b>等級</b><span>Lv{profile['level']}</span></div>
              <div><b>EXP</b><span>{exp_text}</span></div>
              <div><b>HP</b><span>{stats['hp']:.1f}</span></div>
              <div{attack_row_style}><b>{attack_label}</b><span>{stats['attack']:.1f}</span></div>
              <div><b>防禦</b><span>{stats['defense']:.1f}</span></div>
              <div><b>攻速</b><span>{stats['attack_speed']:.2f}/秒</span></div>
            </div>
          </section>
          <section class="character-stat-box">
            <h4>特殊詞條</h4>
            <div class="character-stat-list character-stat-list-special">{''.join(active_effects)}</div>
          </section>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_unused_equipment(profile, save_profile):
    equipped_uids = equipped_item_uids(profile)
    items = [item for item in profile["inventory"] if item["uid"] not in equipped_uids]
    title_col, bulk_col = st.columns([3, 2], vertical_alignment="center")
    title_col.write(f"### 未使用裝備（{len(items)}件）")
    bulk_mode = st.session_state.get("character_bulk_dismantle_mode", False)
    if bulk_col.button(
        "取消多項分解" if bulk_mode else "多項分解",
        key="toggle_character_bulk_dismantle",
        use_container_width=True,
    ):
        st.session_state.character_bulk_dismantle_mode = not bulk_mode
        st.rerun()
    filter_col, star_col, sort_col = st.columns(3)
    selected_slot = filter_col.selectbox(
        "部位", ["all", *SLOT_NAMES],
        format_func=lambda value: "全部部位" if value == "all" else SLOT_NAMES[value],
        key="character_gear_slot_filter",
    )
    selected_star = star_col.selectbox(
        "星級", [0, 4, 3, 2, 1],
        format_func=lambda value: "全部星級" if value == 0 else f"{value}星",
        key="character_gear_star_filter",
    )
    sorting = sort_col.selectbox(
        "排序", ["star", "slot"],
        format_func=lambda value: "星級高到低" if value == "star" else "依部位",
        key="character_gear_sort",
    )
    visible = [
        item for item in items
        if (selected_slot == "all" or item["slot"] == selected_slot)
        and (selected_star == 0 or item["stars"] == selected_star)
    ]
    slot_order = {slot: index for index, slot in enumerate(SLOT_NAMES)}
    if sorting == "slot":
        visible.sort(key=lambda item: (slot_order[item["slot"]], -item["stars"], item["name"]))
    else:
        visible.sort(key=lambda item: (-item["stars"], slot_order[item["slot"]], item["name"]))

    eligible_items = [item for item in items if item["stars"] in (1, 2, 3)]
    if bulk_mode:
        selected_items = [
            item for item in eligible_items
            if st.session_state.get(f"character_bulk_break_{item['uid']}", False)
        ]
        coin_gain, stone_gain = dismantle_value(selected_items, profile)
        st.info(
            f"已選擇 {len(selected_items)} 件，可獲得 {coin_gain} 金幣"
            + (f"、{stone_gain} 顆融煉石" if stone_gain else "")
            + "。四星以上裝備不可分解。"
        )
        confirm_col, clear_col = st.columns(2)
        if confirm_col.button(
            "確認分解所選裝備",
            key="confirm_character_bulk_dismantle",
            type="primary",
            disabled=not selected_items,
            use_container_width=True,
        ):
            if dismantle_inventory_items(profile, selected_items):
                save_profile(profile)
                for item in eligible_items:
                    st.session_state.pop(f"character_bulk_break_{item['uid']}", None)
                st.session_state.character_bulk_dismantle_mode = False
                st.session_state.character_bulk_dismantle_notice = (
                    f"已分解 {len(selected_items)} 件裝備，獲得 {coin_gain} 金幣"
                    + (f"與 {stone_gain} 顆融煉石" if stone_gain else "")
                    + "。"
                )
                st.rerun()
        if clear_col.button(
            "取消並清除選取",
            key="clear_character_bulk_dismantle",
            use_container_width=True,
        ):
            for item in eligible_items:
                st.session_state.pop(f"character_bulk_break_{item['uid']}", None)
            st.session_state.character_bulk_dismantle_mode = False
            st.rerun()

    if st.session_state.get("character_bulk_dismantle_notice"):
        st.success(st.session_state.pop("character_bulk_dismantle_notice"))
    if not visible:
        st.info("目前沒有符合條件的未使用裝備。")
        return
    for start in range(0, len(visible), 5):
        columns = st.columns(5)
        for column, item in zip(columns, visible[start:start + 5]):
            label = f"{SLOT_ICONS[item['slot']]} {item['name']}\n{'⭐' * item['stars']}"
            if bulk_mode:
                column.checkbox(
                    label,
                    key=f"character_bulk_break_{item['uid']}",
                    disabled=item["stars"] >= 4,
                    help="四星以上裝備不可分解" if item["stars"] >= 4 else "勾選後可一次分解",
                )
                continue
            with column.popover(label, use_container_width=True):
                render_item_comparison(profile, item)
                if st.button("裝備", key=f"character_equip_{item['uid']}", use_container_width=True):
                    profile["equipment"][item["slot"]] = item["uid"]
                    save_profile(profile)
                    st.rerun()
                if item["stars"] in (1, 2, 3):
                    if st.button("分解", key=f"character_break_{item['uid']}", use_container_width=True):
                        if dismantle_inventory_items(profile, [item]):
                            save_profile(profile)
                            st.rerun()
                else:
                    st.caption("四星以上裝備不能分解。")


def _render_pet_layout_preview(profile, save_profile):
    """Render owned pets, persistent art preference, sorting and follow state."""
    ensure_pet_profile(profile)
    sort_options = ("acquired", "element", "stars")
    sort_labels = {
        "acquired": "獲得時間（舊→新）",
        "element": "屬性（光暗木土水火）",
        "stars": "星級（一星→三星）",
    }
    selected_sort = profile.get("pet_sort_mode", "acquired")
    pets = owned_pet_entries(profile, selected_sort)
    selected_id = st.session_state.get("character_pet_selected_id")
    owned_ids = [entry["id"] for entry in pets]
    if selected_id not in owned_ids:
        selected_id = profile.get("equipped_pet_id") if profile.get("equipped_pet_id") in owned_ids else owned_ids[0]
        st.session_state.character_pet_selected_id = selected_id
    current_index = owned_ids.index(selected_id)
    current_pet = pet_details(profile, selected_id)

    with st.container(key="character_pet_preview"):
        with st.container(key="character_pet_identity_row"):
            identity_col, picture_col, sort_col = st.columns(
                [3.1, 1.7, 2.7], vertical_alignment="center"
            )
            identity_col.markdown(
                f"**Lv{current_pet['level']}　{current_pet['display_name']}**"
            )
            if picture_col.button(
                "切換圖案",
                key="character_pet_preview_picture",
                help=(
                    "目前使用Q版大圖，點擊切換神話大圖"
                    if profile["pet_image_style"] == "chibi"
                    else "目前使用神話大圖，點擊切換Q版大圖"
                ),
                use_container_width=True,
            ):
                profile["pet_image_style"] = (
                    "mythic" if profile["pet_image_style"] == "chibi" else "chibi"
                )
                save_profile(profile)
                st.rerun()
            chosen_sort = sort_col.selectbox(
                "排序",
                sort_options,
                index=sort_options.index(selected_sort),
                format_func=lambda value: sort_labels[value],
                key="character_pet_sort_choice",
                label_visibility="collapsed",
            )
            if chosen_sort != selected_sort:
                profile["pet_sort_mode"] = chosen_sort
                save_profile(profile)
                st.rerun()

        with st.container(key="character_pet_page_count"):
            st.markdown(f"**{current_index + 1} / {PET_TOTAL}**")

        with st.container(key="character_pet_stage"):
            previous_col, art_col, next_col = st.columns(
                [1, 6, 1], vertical_alignment="center"
            )
            if previous_col.button(
                "←",
                key="character_pet_preview_previous",
                disabled=len(pets) <= 1,
                use_container_width=True,
            ):
                st.session_state.character_pet_selected_id = pets[(current_index - 1) % len(pets)]["id"]
                st.rerun()
            with art_col:
                with st.container(key="character_pet_art"):
                    st.image(
                        str(pet_asset_path(current_pet, profile["pet_image_style"])),
                        width="stretch",
                    )
            if next_col.button(
                "→",
                key="character_pet_preview_next",
                disabled=len(pets) <= 1,
                use_container_width=True,
            ):
                st.session_state.character_pet_selected_id = pets[(current_index + 1) % len(pets)]["id"]
                st.rerun()

        with st.container(key="character_pet_action_row"):
            cultivate_col, skill_col, follow_col = st.columns(3)
            with cultivate_col.popover("培養", use_container_width=True):
                st.caption(
                    f"美味罐頭 ×{int(profile.get('pet_food_cans', 0))}｜"
                    f"特製仙丹（{current_pet['element_name']}屬性）×"
                    f"{int(profile.get('pet_element_elixirs', {}).get(current_pet['element'], 0))}"
                )
                can_disabled = (
                    int(profile.get("pet_food_cans", 0)) <= 0
                    or int(current_pet["level"]) >= int(profile.get("level", 1))
                )
                can_count = int(profile.get("pet_food_cans", 0))
                can_quantity = st.number_input(
                    "使用美味罐頭數量",
                    min_value=1,
                    max_value=max(1, can_count),
                    value=1,
                    step=1,
                    disabled=can_disabled,
                    key=f"train_pet_can_quantity_{selected_id}",
                )
                if st.button(
                    f"＋ 使用 {int(can_quantity)} 個美味罐頭（每個 EXP +30）",
                    key=f"train_pet_can_{selected_id}",
                    disabled=can_disabled,
                    use_container_width=True,
                ):
                    result = use_pet_training_item(
                        profile, selected_id, "can", quantity=int(can_quantity)
                    )
                    if result["ok"]:
                        save_profile(profile)
                        st.session_state.pet_training_notice = (
                            f"使用 {result['items_used']} 個美味罐頭，"
                            f"{current_pet['display_name']}獲得 {result['exp_added']} EXP"
                            + (f"，升到 Lv{result['pet']['level']}！" if result["levels"] else "！")
                            + (" 已達目前勇者等級上限，其餘道具未消耗。" if result.get("stopped_at_cap") else "")
                        )
                    else:
                        st.session_state.pet_training_notice = result["reason"]
                    st.rerun()
                elixir_count = int(
                    profile.get("pet_element_elixirs", {}).get(current_pet["element"], 0)
                )
                elixir_disabled = (
                    elixir_count <= 0
                    or int(current_pet["level"]) >= int(profile.get("level", 1))
                )
                elixir_quantity = st.number_input(
                    f"使用特製仙丹（{current_pet['element_name']}屬性）數量",
                    min_value=1,
                    max_value=max(1, elixir_count),
                    value=1,
                    step=1,
                    disabled=elixir_disabled,
                    key=f"train_pet_elixir_quantity_{selected_id}",
                )
                if st.button(
                    f"＋ 使用 {int(elixir_quantity)} 個特製仙丹（每個 EXP +50）",
                    key=f"train_pet_elixir_{selected_id}",
                    disabled=elixir_disabled,
                    use_container_width=True,
                ):
                    result = use_pet_training_item(
                        profile,
                        selected_id,
                        f"elixir:{current_pet['element']}",
                        quantity=int(elixir_quantity),
                    )
                    if result["ok"]:
                        save_profile(profile)
                        st.session_state.pet_training_notice = (
                            f"使用 {result['items_used']} 個特製仙丹，"
                            f"{current_pet['display_name']}獲得 {result['exp_added']} EXP"
                            + (f"，升到 Lv{result['pet']['level']}！" if result["levels"] else "！")
                            + (" 已達目前勇者等級上限，其餘道具未消耗。" if result.get("stopped_at_cap") else "")
                        )
                    else:
                        st.session_state.pet_training_notice = result["reason"]
                    st.rerun()
            skill_clicked = skill_col.button(
                "技能",
                key="character_pet_preview_skill",
                use_container_width=True,
            )
            follow_clicked = follow_col.button(
                "取消跟隨" if profile.get("equipped_pet_id") == selected_id else "跟隨",
                key="character_pet_preview_follow",
                use_container_width=True,
            )

        if skill_clicked:
            st.session_state.character_pet_skill_modal_id = selected_id
            st.rerun()

        skill_modal_id = st.session_state.get("character_pet_skill_modal_id")
        if skill_modal_id:
            skill_pet = pet_details(profile, skill_modal_id)
            if skill_pet:
                with st.container(key="character_pet_skill_modal"):
                    st.markdown(f"### {skill_pet['skill']['name']}")
                    st.write(skill_pet["skill"]["description"])
                    if int(skill_pet.get("stars", 1)) < 3:
                        st.warning("請先將寵物進階到三星，才能解鎖此技能。")
                    else:
                        st.success("技能已解鎖；跟隨此寵物時會在戰鬥中發動。")
                    if st.button(
                        "關閉技能說明",
                        key="close_character_pet_skill_modal",
                        use_container_width=True,
                    ):
                        st.session_state.character_pet_skill_modal_id = None
                        st.rerun()

        # Follow behaves like equipping the tenth slot.  The rerun also refreshes
        # the character attack element, special traits and the pet-slot icon.
        if follow_clicked:
            profile["equipped_pet_id"] = (
                None if profile.get("equipped_pet_id") == selected_id else selected_id
            )
            save_profile(profile)
            st.rerun()

        training_notice = st.session_state.pop("pet_training_notice", None)
        if training_notice:
            st.toast(training_notice)

        star_count = max(1, min(3, int(current_pet.get("stars", 1))))
        # HTML entities plus a text-symbol font prevent mobile browsers from
        # turning the earned star into a yellow emoji.  ★☆☆ therefore means Lv1.
        star_text = "&#9733;" * star_count + "&#9734;" * (3 - star_count)
        element_souls = int(
            profile.get("pet_element_souls", {}).get(current_pet["element"], 0)
        )
        advance_cost = PET_ADVANCE_SOUL_COSTS.get(star_count)
        with st.container(key="character_pet_stats_section"):
            star_col, soul_col, advance_col = st.columns(
                [2.2, 3.2, 1.25], vertical_alignment="center"
            )
            star_col.markdown(
                f'<div class="pet-advance-stars">星級　<span>{star_text}</span></div>',
                unsafe_allow_html=True,
            )
            soul_col.markdown(
                f'<div class="pet-soul-count">{current_pet["element_name"]}屬性元神 ×{element_souls}</div>',
                unsafe_allow_html=True,
            )
            advance_clicked = advance_col.button(
                "進階",
                key=f"advance_pet_{selected_id}",
                disabled=star_count >= 3,
                help=(
                    "已達三星"
                    if star_count >= 3
                    else f"消耗 {advance_cost} 個{current_pet['element_name']}屬性元神"
                ),
                use_container_width=True,
            )
            st.markdown(
                f"""
                <div class="character-pet-stat-panels">
                  <section class="character-pet-stat-box">
                    <h4>基礎能力</h4>
                    <div class="character-pet-stat-list">
                      <div><b>Lv</b><span>{current_pet['level']}</span></div>
                      <div><b>EXP ＋</b><span>{current_pet['exp']} / {current_pet['exp_required']}</span></div>
                      <div><b>屬性</b><span>{current_pet['element_name']}</span></div>
                    </div>
                  </section>
                  <section class="character-pet-stat-box">
                    <h4>特殊詞條</h4>
                    <div class="character-pet-stat-list">
                      <div><b>額外裝備掉落機率</b><span>+{current_pet['drop_bonus_pct']:.0%}</span></div>
                      <div><b>跟隨時造成的攻擊轉為{current_pet['element_name']}屬性</b><span>{current_pet['element_name']}</span></div>
                      <div><b>二星・分解裝備獲得的金幣數量加20%</b><span>{'+20%' if star_count >= 2 else '未解鎖'}</span></div>
                      <div><b>三星・主動技能</b><span>{current_pet['skill']['name'] if star_count >= 3 else '未解鎖'}</span></div>
                      <div><b>Lv5・跟隨時增加HP</b><span>{'+25%' if current_pet['level'] >= 5 else '未解鎖'}</span></div>
                      <div><b>Lv10・跟隨時增加攻擊</b><span>{'+25%' if current_pet['level'] >= 10 else '未解鎖'}</span></div>
                      <div><b>Lv15・跟隨時增加防禦</b><span>{'+25%' if current_pet['level'] >= 15 else '未解鎖'}</span></div>
                      <div><b>Lv20・跟隨時增加攻速</b><span>{'+0.250/秒' if current_pet['level'] >= 20 else '未解鎖'}</span></div>
                    </div>
                  </section>
                </div>
                """,
                unsafe_allow_html=True,
            )

        if advance_clicked:
            result = advance_pet(profile, selected_id)
            if result["ok"]:
                save_profile(profile)
                if int(result["pet"]["stars"]) == 2:
                    unlock_notice = "解鎖被動能力：分解裝備獲得的金幣數量加20%！"
                else:
                    unlock_notice = f"解鎖主動技能：「{result['pet']['skill']['name']}」！"
                st.session_state.pet_advance_notice = (
                    f"{result['pet']['display_name']}已進階為 {result['pet']['stars']} 星！"
                    f"{unlock_notice}剩餘元神 ×{result['souls_remaining']}"
                )
            else:
                st.session_state.pet_advance_notice = result["reason"]
            st.rerun()

        advance_notice = st.session_state.pop("pet_advance_notice", None)
        if advance_notice:
            st.toast(advance_notice)

        with st.container(key="character_pet_summon_row"):
            go_to_summon = st.button(
                "前往召喚",
                key="character_pet_preview_summon",
                use_container_width=True,
            )
        if go_to_summon:
            st.session_state.show_character_dialog = False
            st.session_state.character_panel_view = "equipment"
            st.session_state.character_selected_slot = None
            st.session_state.character_pet_skill_modal_id = None
            st.session_state.pet_summon_view = "main"
            st.session_state.pet_summon_result = None
            st.session_state.screen = "pet_summon"
            st.rerun()


def _render_titles(profile, save_profile):
    st.write("### 🏅 稱號")
    if not profile["titles"]:
        st.info("擊敗各章菁英 BOSS 可以解鎖成就稱號。")
        return
    for title in profile["titles"]:
        text_col, action_col = st.columns([4, 1], vertical_alignment="center")
        text_col.write(f"🏅 **「{title}」**")
        if profile.get("equipped_title") == title:
            if action_col.button("卸下", key=f"character_title_off_{title}", use_container_width=True):
                profile["equipped_title"] = None
                save_profile(profile)
                st.rerun()
        elif action_col.button("佩戴", key=f"character_title_on_{title}", use_container_width=True):
            profile["equipped_title"] = title
            save_profile(profile)
            st.rerun()


def render_character_equipment_hub(profile, save_profile):
    """Render the complete character screen and its four focused tabs."""
    st.markdown(
        """
        <style>
        /* Streamlit 的按鈕、下拉選單與 Markdown 元件各自可能指定字型；
           角色能力視窗內統一強制使用標楷體字族。星號等符號另於下方保留符號字型。 */
        .st-key-character_panel_navigation,
        .st-key-character_panel_navigation *,
        .st-key-character_equipment_view,
        .st-key-character_equipment_view *,
        .st-key-character_scroll_view,
        .st-key-character_scroll_view *,
        .st-key-character_pet_view,
        .st-key-character_pet_view * {
          font-family:DFKai-SB,BiauKai,"標楷體",KaiTi,STKaiti,"Noto Serif TC",serif !important;
        }
        .st-key-character_panel_navigation .material-symbols-rounded,
        .st-key-character_panel_navigation .material-symbols-outlined,
        .st-key-character_panel_navigation [data-testid="stIconMaterial"],
        .st-key-character_panel_navigation [data-testid="stIconMaterial"] *,
        .st-key-character_equipment_view .material-symbols-rounded,
        .st-key-character_equipment_view .material-symbols-outlined,
        .st-key-character_equipment_view [data-testid="stIconMaterial"],
        .st-key-character_equipment_view [data-testid="stIconMaterial"] *,
        .st-key-character_scroll_view .material-symbols-rounded,
        .st-key-character_scroll_view .material-symbols-outlined,
        .st-key-character_scroll_view [data-testid="stIconMaterial"],
        .st-key-character_scroll_view [data-testid="stIconMaterial"] *,
        .st-key-character_pet_view .material-symbols-rounded,
        .st-key-character_pet_view .material-symbols-outlined,
        .st-key-character_pet_view [data-testid="stIconMaterial"],
        .st-key-character_pet_view [data-testid="stIconMaterial"] * {
          font-family:"Material Symbols Rounded" !important;
          font-weight:normal !important;font-style:normal !important;
          letter-spacing:normal !important;text-transform:none !important;
          white-space:nowrap !important;word-wrap:normal !important;
          -webkit-font-feature-settings:"liga" !important;font-feature-settings:"liga" !important;
        }
        @media (max-width:768px) and (orientation:portrait) {
          .st-key-character_panel_navigation [data-testid="stHorizontalBlock"]:has(.st-key-character_nav_equipment) {
            display:flex !important;flex-direction:row !important;flex-wrap:nowrap !important;gap:.15rem !important;
          }
          .st-key-character_panel_navigation [data-testid="stHorizontalBlock"]:has(.st-key-character_nav_equipment) > [data-testid="stColumn"] {
            min-width:0 !important;flex:1 1 25% !important;width:25% !important;
          }
          .st-key-character_panel_navigation button {
            min-height:2rem !important;padding:.12rem .01rem !important;font-size:.55rem !important;white-space:nowrap !important;
          }
          .st-key-character-loadout-row [data-testid="stHorizontalBlock"] {
            display:flex !important;flex-direction:row !important;flex-wrap:nowrap !important;
          }
        }
        .st-key-character_panel_navigation {margin-top:0 !important;}
        .st-key-character_panel_navigation [data-testid="stHorizontalBlock"] {gap:.35rem !important;}
        .st-key-character_equipment_view > [data-testid="stVerticalBlock"] {gap:.08rem !important;}
        .st-key-character_scroll_view {
          border:1px solid #d6dce5;border-radius:8px;background:#fff;padding:.25rem;
        }
        .st-key-character_scroll_view > [data-testid="stVerticalBlockBorderWrapper"] {
          max-height:min(62vh,34rem) !important;overflow-y:auto !important;background:#fff !important;
        }
        .st-key-character_pet_view {background:#fff;color:#1f2937;}
        .st-key-character_pet_skill_modal {
          position:fixed !important;left:50% !important;top:50% !important;
          transform:translate(-50%,-50%) !important;z-index:1000002 !important;
          width:min(88vw,32rem) !important;max-height:78vh !important;overflow-y:auto !important;
          padding:1rem 1.1rem !important;background:#fff !important;color:#1f2937 !important;
          border:3px solid #111 !important;border-radius:12px !important;
          box-shadow:0 18px 60px rgba(0,0,0,.42) !important;
        }
        .st-key-character_pet_skill_modal h3 {margin:.1rem 0 .55rem !important;text-align:center;}
        .st-key-character_pet_preview > [data-testid="stVerticalBlock"] {gap:.22rem !important;}
        .st-key-character_pet_identity_row [data-testid="stHorizontalBlock"],
        .st-key-character_pet_action_row [data-testid="stHorizontalBlock"],
        .st-key-character_pet_stage [data-testid="stHorizontalBlock"] {
          display:flex !important;flex-direction:row !important;flex-wrap:nowrap !important;
          align-items:center !important;
        }
        .st-key-character_pet_identity_row p {margin:0 !important;font-size:1.18rem;font-weight:800;}
        .st-key-character_pet_page_count p {margin:0 !important;}
        .st-key-character_pet_stage {min-height:19rem;}
        .st-key-character_pet_art [data-testid="stImage"] img {
          display:block;max-height:21rem;width:100%;object-fit:contain;border-radius:10px;
        }
        .st-key-character_pet_stage button {font-size:1.4rem !important;font-weight:800 !important;}
        .character-pet-stat-panels {display:grid;grid-template-columns:1fr 1fr;gap:.5rem;}
        .character-pet-stat-box {
          border:1px solid #d6dce5;border-radius:8px;padding:.5rem;background:#fff;
          color:#1f2937;min-width:0;
        }
        .character-pet-stat-box * {color:#1f2937 !important;}
        .character-pet-stat-box h4 {margin:0 0 .38rem;text-align:center;font-size:1rem;}
        .character-pet-stat-list {
          min-height:0;overflow-y:auto !important;overscroll-behavior-y:contain;
          touch-action:pan-y !important;-webkit-overflow-scrolling:touch;
        }
        .character-pet-stat-list div {
          display:grid;grid-template-columns:minmax(0,1fr) auto;gap:.35rem;
          width:100%;box-sizing:border-box;padding:0;
          border-bottom:0;font-size:.82rem;line-height:1.25;
        }
        .character-pet-stat-list div > b,
        .character-pet-stat-list div > span {
          display:flex;align-items:center;min-width:0;height:100%;box-sizing:border-box;
          padding:.18rem 0;border-bottom:1px solid #dfe4ea;
        }
        .character-pet-stat-list div > b {overflow-wrap:anywhere;}
        .character-pet-stat-list div > span {justify-content:flex-end;white-space:nowrap;font-weight:700;}
        .character-pet-stat-list .pet-star-level {
          color:#111 !important;font-family:Arial,"Segoe UI Symbol","Noto Sans Symbols 2",sans-serif !important;
          font-weight:900 !important;letter-spacing:.08em !important;
        }
        .character-pet-stat-list div:last-child > b,
        .character-pet-stat-list div:last-child > span {border-bottom:0;}
        .st-key-character_pet_stats_section > [data-testid="stVerticalBlock"] {
          height:100%;min-height:0;display:grid;grid-template-rows:1.75rem minmax(0,1fr);gap:.15rem !important;
        }
        .st-key-character_pet_stats_section [data-testid="stHorizontalBlock"] {
          display:flex !important;flex-direction:row !important;flex-wrap:nowrap !important;
          align-items:center !important;gap:.22rem !important;
        }
        .st-key-character_pet_stats_section [data-testid="stColumn"] {min-width:0 !important;}
        .pet-advance-stars,.pet-soul-count {font-size:.8rem;font-weight:800;line-height:1.1;white-space:nowrap;}
        .pet-advance-stars span {
          font-family:Arial,"Segoe UI Symbol","Noto Sans Symbols 2",sans-serif !important;
          color:#111 !important;font-weight:900;letter-spacing:.06em;
        }
        @media (max-width:768px) and (orientation:portrait) {
          .st-key-character_pet_view {
            position:absolute !important;left:.45rem !important;right:.45rem !important;
            top:3.45rem !important;bottom:.38rem !important;
            width:auto !important;height:auto !important;margin:0 !important;padding:0 !important;
            overflow:hidden !important;
          }
          .st-key-character_pet_view > [data-testid="stVerticalBlock"] {
            height:100% !important;min-height:0 !important;gap:0 !important;
          }
          .st-key-character_pet_preview,
          .st-key-character_pet_preview > [data-testid="stVerticalBlock"] {
            height:100% !important;min-height:0 !important;overflow:hidden !important;
          }
          .st-key-character_pet_preview > [data-testid="stVerticalBlock"] {
            display:grid !important;
            grid-template-rows:2.15rem 1.05rem minmax(0,1fr) 2rem 10.8rem 2rem;
            gap:.08rem !important;
          }
          .st-key-character_pet_identity_row,
          .st-key-character_pet_action_row,
          .st-key-character_pet_stage,
          .st-key-character_pet_page_count {margin:0 !important;padding:0 !important;min-height:0 !important;}
          .st-key-character_pet_identity_row [data-testid="stHorizontalBlock"],
          .st-key-character_pet_action_row [data-testid="stHorizontalBlock"],
          .st-key-character_pet_stage [data-testid="stHorizontalBlock"] {
            gap:.12rem !important;height:100% !important;min-height:0 !important;
          }
          .st-key-character_pet_identity_row [data-testid="stColumn"],
          .st-key-character_pet_action_row [data-testid="stColumn"],
          .st-key-character_pet_stage [data-testid="stColumn"] {
            min-width:0 !important;width:auto !important;padding:0 !important;
          }
          .st-key-character_pet_identity_row [data-testid="stColumn"]:nth-child(1) {
            flex:0 0 calc(39% - .08rem) !important;max-width:calc(39% - .08rem) !important;
          }
          .st-key-character_pet_identity_row [data-testid="stColumn"]:nth-child(2) {
            flex:0 0 calc(25% - .08rem) !important;max-width:calc(25% - .08rem) !important;
          }
          .st-key-character_pet_identity_row [data-testid="stColumn"]:nth-child(3) {
            flex:0 0 calc(36% - .08rem) !important;max-width:calc(36% - .08rem) !important;
          }
          .st-key-character_pet_action_row [data-testid="stColumn"] {
            flex:0 0 calc(33.333% - .08rem) !important;max-width:calc(33.333% - .08rem) !important;
          }
          .st-key-character_pet_stage [data-testid="stColumn"]:nth-child(1),
          .st-key-character_pet_stage [data-testid="stColumn"]:nth-child(3) {
            flex:0 0 calc(12% - .08rem) !important;max-width:calc(12% - .08rem) !important;
          }
          .st-key-character_pet_stage [data-testid="stColumn"]:nth-child(2) {
            flex:0 0 calc(76% - .08rem) !important;max-width:calc(76% - .08rem) !important;
          }
          .st-key-character_pet_identity_row button,
          .st-key-character_pet_action_row button {
            min-height:1.9rem !important;height:1.9rem !important;padding:.05rem !important;
            font-size:.68rem !important;
          }
          .st-key-character_pet_identity_row [data-testid="stSelectbox"],
          .st-key-character_pet_identity_row [data-baseweb="select"],
          .st-key-character_pet_identity_row [data-baseweb="select"] > div {
            min-height:1.9rem !important;height:1.9rem !important;margin:0 !important;
            font-size:.63rem !important;line-height:1 !important;
          }
          .st-key-character_pet_identity_row p {
            font-size:clamp(.92rem,4vw,1.08rem) !important;
            line-height:1 !important;font-weight:900 !important;white-space:nowrap !important;
          }
          .st-key-character_pet_page_count p {font-size:.95rem !important;line-height:1 !important;font-weight:900 !important;}
          .st-key-character_pet_stage {min-height:0 !important;height:100% !important;}
          .st-key-character_pet_stage button {
            min-height:2rem !important;height:2rem !important;padding:0 !important;font-size:1rem !important;
          }
          .st-key-character_pet_art,
          .st-key-character_pet_art > [data-testid="stVerticalBlock"],
          .st-key-character_pet_art [data-testid="stImage"],
          .st-key-character_pet_art [data-testid="stImage"] > div,
          .st-key-character_pet_art [data-testid="stImage"] img {
            height:100% !important;max-height:100% !important;min-height:0 !important;
          }
          .st-key-character_pet_art [data-testid="stImage"] img {
            width:100% !important;object-fit:contain !important;border-radius:8px !important;
          }
          .character-pet-stat-panels {height:100%;min-height:0;gap:.22rem;}
          .st-key-character_pet_stats_section,
          .st-key-character_pet_stats_section > [data-testid="stVerticalBlock"] {
            height:100% !important;min-height:0 !important;overflow:hidden !important;
          }
          .st-key-character_pet_stats_section > [data-testid="stVerticalBlock"] {
            display:grid !important;grid-template-rows:1.55rem minmax(0,1fr) !important;gap:.08rem !important;
          }
          .st-key-character_pet_stats_section [data-testid="stHorizontalBlock"] {height:1.55rem !important;}
          .st-key-character_pet_stats_section button {
            min-height:1.45rem !important;height:1.45rem !important;padding:.02rem .12rem !important;font-size:.68rem !important;
          }
          .pet-advance-stars,.pet-soul-count {font-size:clamp(.58rem,2.45vw,.72rem) !important;}
          .character-pet-stat-box {
            display:grid;grid-template-rows:1.75rem minmax(0,1fr);
            height:100%;min-height:0;padding:.18rem .25rem;border-radius:5px;box-sizing:border-box;
            overflow:hidden;
          }
          .character-pet-stat-box h4 {
            margin:0;display:flex;align-items:center;justify-content:center;
            font-size:.82rem;line-height:1;
          }
          .character-pet-stat-list {
            min-height:0;height:100%;overflow-x:hidden !important;overflow-y:scroll !important;
            overscroll-behavior-y:contain;touch-action:pan-y !important;
            display:grid;grid-auto-rows:calc(100% / 4);align-content:start;
            -webkit-overflow-scrolling:touch;scrollbar-gutter:stable;
          }
          .character-pet-stat-list div {
            box-sizing:border-box;height:auto;min-height:0;
            font-size:clamp(.66rem,2.8vw,.8rem);padding:0;align-items:stretch;
          }
          .character-pet-stat-list div > b,
          .character-pet-stat-list div > span {
            padding:.08rem 0;line-height:1.12;
          }
          .st-key-character_pet_summon_row,
          .st-key-character_pet_summon_row > [data-testid="stVerticalBlock"] {
            height:2rem !important;min-height:2rem !important;margin:0 !important;padding:0 !important;
          }
          .st-key-character_pet_summon_row button {
            height:2rem !important;min-height:2rem !important;padding:.05rem !important;
            font-size:.78rem !important;font-weight:800 !important;
          }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    _render_panel_navigation(profile, save_profile)
    view = st.session_state.character_panel_view
    if view == "equipment":
        with st.container(key="character_equipment_view"):
            _render_equipment_scene(profile, save_profile)
            _render_compact_stats(profile)
    elif view == "pet":
        with st.container(key="character_pet_view"):
            _render_pet_layout_preview(profile, save_profile)
    else:
        # 未使用裝備與稱號會持續增加，限制在視窗內獨立捲動。
        with st.container(key="character_scroll_view", height=520, border=False):
            if view == "unused":
                _render_unused_equipment(profile, save_profile)
            else:
                _render_titles(profile, save_profile)


def _dismiss_character_dialog():
    """Reset dialog-only state after the native dialog close button is used."""
    st.session_state.show_character_dialog = False
    st.session_state.character_panel_view = "equipment"
    st.session_state.character_selected_slot = None
    st.session_state.character_pet_skill_modal_id = None


@st.dialog(
    "角色能力",
    width="large",
    dismissible=True,
    on_dismiss=_dismiss_character_dialog,
)
def render_character_equipment_dialog(profile, save_profile):
    """Show the character hub as a theme-independent modal over the home screen."""
    st.markdown(
        """
        <style>
        body:has([data-testid="stDialog"]) {overflow:hidden !important;overscroll-behavior:none !important;}
        [data-testid="stDialog"] [role="dialog"] {
          background:#fff !important;color:#1f2937 !important;
          border:3px solid #111 !important;border-radius:6px !important;
          max-height:calc(100vh - .5rem) !important;
          font-family:DFKai-SB,BiauKai,"標楷體",KaiTi,STKaiti,"Noto Serif TC",serif !important;
        }
        [data-testid="stDialog"] [role="dialog"] *,
        body:has([data-testid="stDialog"]) [data-baseweb="popover"] *,
        body:has([data-testid="stDialog"]) [role="listbox"] * {
          font-family:DFKai-SB,BiauKai,"標楷體",KaiTi,STKaiti,"Noto Serif TC",serif !important;
        }
        /* 星級符號與 Streamlit 功能圖示不能改用中文字型，否則可能變成方框。 */
        [data-testid="stDialog"] [role="dialog"] .pet-star-level,
        [data-testid="stDialog"] [role="dialog"] .pet-star-level *,
        [data-testid="stDialog"] [role="dialog"] .material-symbols-rounded,
        [data-testid="stDialog"] [role="dialog"] .material-symbols-outlined,
        [data-testid="stDialog"] [role="dialog"] [data-testid="stIconMaterial"],
        [data-testid="stDialog"] [role="dialog"] [data-testid="stIconMaterial"] *,
        body:has([data-testid="stDialog"]) [data-baseweb="popover"] .material-symbols-rounded,
        body:has([data-testid="stDialog"]) [data-baseweb="popover"] .material-symbols-outlined,
        body:has([data-testid="stDialog"]) [data-baseweb="popover"] [data-testid="stIconMaterial"],
        body:has([data-testid="stDialog"]) [data-baseweb="popover"] [data-testid="stIconMaterial"] *,
        body:has([data-testid="stDialog"]) [role="listbox"] .material-symbols-rounded,
        body:has([data-testid="stDialog"]) [role="listbox"] .material-symbols-outlined,
        body:has([data-testid="stDialog"]) [role="listbox"] [data-testid="stIconMaterial"],
        body:has([data-testid="stDialog"]) [role="listbox"] [data-testid="stIconMaterial"] * {
          font-family:"Material Symbols Rounded" !important;
          font-weight:normal !important;font-style:normal !important;
          letter-spacing:normal !important;text-transform:none !important;
          white-space:nowrap !important;word-wrap:normal !important;
          -webkit-font-feature-settings:"liga" !important;font-feature-settings:"liga" !important;
        }
        [data-testid="stDialog"] [role="dialog"] > div {
          overflow-y:auto !important;
        }
        [data-testid="stDialog"] [role="dialog"] > div > [data-testid="stVerticalBlock"] {
          gap:.32rem !important;
        }
        [data-testid="stDialog"] [role="dialog"] h1,
        [data-testid="stDialog"] [role="dialog"] h2,
        [data-testid="stDialog"] [role="dialog"] h3,
        [data-testid="stDialog"] [role="dialog"] h4,
        [data-testid="stDialog"] [role="dialog"] p,
        [data-testid="stDialog"] [role="dialog"] label,
        [data-testid="stDialog"] [role="dialog"] span {color:#1f2937 !important;}
        [data-testid="stDialog"] [role="dialog"] button {
          background:#fff !important;color:#1f2937 !important;border-color:#cbd2da !important;
        }
        [data-testid="stDialog"] [role="dialog"] button[kind="primary"] {
          background:#ffe8e8 !important;color:#b91c1c !important;border-color:#ef4444 !important;
        }
        [data-testid="stDialog"] [role="dialog"] input,
        [data-testid="stDialog"] [role="dialog"] textarea,
        [data-testid="stDialog"] [role="dialog"] [data-baseweb="select"] > div {
          background:#fff !important;color:#1f2937 !important;
        }
        [data-testid="stDialog"] [role="dialog"] h2:first-of-type {
          text-align:center !important;width:100% !important;justify-content:center !important;
        }
        /* 使用 Streamlit 原生對話框關閉鈕。它真正位於 role=dialog 內，
           螢幕旋轉或重新繪製時不會脫離視窗，也不會留下空白容器。 */
        [data-testid="stDialog"] [role="dialog"] > button[aria-label="Close"] {
          position:absolute !important;inset:auto .45rem auto auto !important;
          top:.4rem !important;z-index:20 !important;
          width:2.45rem !important;height:2.45rem !important;
          min-width:2.45rem !important;min-height:2.45rem !important;
          margin:0 !important;
          padding:0 !important;border:2px solid #111 !important;border-radius:4px !important;
          background:#fff !important;color:#e53935 !important;
          display:flex !important;align-items:center !important;justify-content:center !important;
          visibility:visible !important;opacity:1 !important;pointer-events:auto !important;
        }
        [data-testid="stDialog"] [role="dialog"] > button[aria-label="Close"] svg {
          width:1.05rem !important;height:1.05rem !important;color:#e53935 !important;
        }
        @media (max-width:768px) and (orientation:portrait) {
          /* 對話框最外層會為「樣式、關閉鈕、分頁、內容」各保留一個
             16px flex gap。前三者本身不佔高度，卻會累積成大片空白；
             直屏改成真正連續的標題列、分頁列、內容列。 */
          [data-testid="stDialog"] [role="dialog"] > div > [data-testid="stVerticalBlock"] > [data-testid="stLayoutWrapper"] > [data-testid="stVerticalBlock"] {
            gap:0 !important;
          }
          body:has([data-testid="stDialog"]) [data-testid="stHeader"] {display:none !important;}
          body:has([data-testid="stDialog"]) [data-baseweb="modal"] {
            position:fixed !important;inset:0 !important;width:100% !important;height:100dvh !important;
            margin:0 !important;padding:0 !important;overflow:hidden !important;z-index:1000 !important;
          }
          body:has([data-testid="stDialog"]) [data-baseweb="modal"] > div {
            margin:0 !important;padding:0 !important;max-width:100% !important;max-height:100dvh !important;
          }
          [data-testid="stDialog"] {
            position:fixed !important;inset:0 !important;z-index:1000 !important;
            box-sizing:border-box !important;width:100% !important;height:100dvh !important;
            max-width:100% !important;max-height:100dvh !important;
            padding:0 !important;margin:0 !important;align-items:stretch !important;justify-content:stretch !important;
            overflow:hidden !important;overscroll-behavior:none !important;background:#fff !important;
          }
          /* BaseWeb 會把 selectbox、popover 的內容掛在 dialog 外面的 portal。
             角色視窗若佔用最高 z-index，這些選單其實已開啟卻會被白底蓋住。
             視窗維持在頁面上方，互動式浮層再高一層即可。 */
          body:has([data-testid="stDialog"]) [data-baseweb="popover"],
          body:has([data-testid="stDialog"]) [data-baseweb="menu"],
          body:has([data-testid="stDialog"]) [role="listbox"] {
            z-index:2000 !important;
          }
          /* 裝備名稱與詞條較長時，候選清單必須增加列高並自動換行，
             不能以省略號切掉後半段能力。 */
          body:has([data-testid="stDialog"]) [role="listbox"] {
            width:min(34rem,calc(100vw - 1rem)) !important;
            max-width:calc(100vw - 1rem) !important;
          }
          body:has([data-testid="stDialog"]) [role="option"] {
            display:block !important;height:auto !important;min-height:3.45rem !important;
            max-height:none !important;align-items:flex-start !important;
            padding:.36rem .55rem !important;box-sizing:border-box !important;
          }
          body:has([data-testid="stDialog"]) [role="option"],
          body:has([data-testid="stDialog"]) [role="option"] * {
            white-space:pre-wrap !important;overflow:visible !important;text-overflow:clip !important;
            overflow-wrap:anywhere !important;word-break:break-word !important;line-height:1.22 !important;
          }
          body:has([data-testid="stDialog"]) [role="option"] > div,
          body:has([data-testid="stDialog"]) [role="option"] span {
            display:block !important;width:100% !important;max-width:100% !important;
            height:auto !important;max-height:none !important;box-sizing:border-box !important;
          }
          [data-testid="stDialog"] [role="dialog"] {
            position:absolute !important;inset:0 !important;
            box-sizing:border-box !important;width:100% !important;max-width:100% !important;
            /* role=dialog 位於平台保留 16px 邊距的容器內；若再使用
               100dvh，底部會多出這段邊距並超過黑框與觸控範圍。 */
            height:100% !important;max-height:100% !important;
            margin:0 !important;padding:.16rem !important;border-radius:0 !important;
            overflow:hidden !important;overscroll-behavior:none !important;
          }
          [data-testid="stDialog"] [role="dialog"] > div {
            height:100% !important;max-height:100% !important;
            padding:.12rem !important;overflow:hidden !important;
          }
          [data-testid="stDialog"] [role="dialog"] > div > [data-testid="stVerticalBlock"] {
            gap:0 !important;height:100% !important;
          }
          [data-testid="stDialog"] [role="dialog"] h2:first-of-type {
            font-size:1.05rem !important;line-height:1 !important;margin:0 !important;padding:0 !important;
          }
          .st-key-character_panel_navigation {
            margin:0 !important;padding:0 !important;height:2rem !important;min-height:2rem !important;
          }
          .st-key-character_panel_navigation > [data-testid="stVerticalBlock"] {
            height:2rem !important;min-height:2rem !important;gap:0 !important;
          }
          .st-key-character_panel_navigation [data-testid="stHorizontalBlock"] {
            height:2rem !important;min-height:2rem !important;gap:.15rem !important;
            align-items:stretch !important;
          }
          .st-key-character_panel_navigation [data-testid="stColumn"],
          .st-key-character_panel_navigation [data-testid="stLayoutWrapper"] {
            height:2rem !important;min-height:2rem !important;margin:0 !important;padding:0 !important;
          }
          .st-key-character_panel_navigation button,
          .st-key-character_panel_navigation [data-baseweb="popover"] {
            height:2rem !important;min-height:2rem !important;margin:0 !important;
          }
          .st-key-character_equipment_view {
            position:absolute !important;left:.45rem !important;right:.45rem !important;
            /* 標題列下方緊接 2rem 分頁列；第三列從分頁下緣開始。 */
            top:3.45rem !important;bottom:.38rem !important;
            width:auto !important;height:auto !important;min-height:0 !important;
            margin:0 !important;padding:0 !important;overflow:hidden !important;
            isolation:isolate !important;
            --character-stats-height:calc((100dvh - 2rem) / 3);
          }
          .st-key-character_equipment_view > [data-testid="stVerticalBlock"] {
            position:relative !important;display:block !important;
            width:100% !important;height:100% !important;margin:0 !important;padding:0 !important;
          }
          /* Streamlit 會替每個元件加 stElementContainer；必須定位這一層，
             否則只定位裡面的 Markdown，寬度會縮成文字本身。 */
          .st-key-character_equipment_view [data-testid="stElementContainer"]:has(.st-key-character_equipment_scene) {
            position:absolute !important;inset:0 0 var(--character-stats-height) 0 !important;
            width:100% !important;height:auto !important;min-height:0 !important;
            margin:0 !important;padding:0 !important;overflow:hidden !important;
          }
          .st-key-character_equipment_scene {
            position:static !important;width:100% !important;height:100% !important;
            max-height:100% !important;min-height:0 !important;margin:0 !important;
            overflow:hidden !important;border-bottom:1px solid #9ca3af !important;
            padding-bottom:.1rem !important;box-sizing:border-box !important;
          }
          .st-key-character_equipment_scene > [data-testid="stVerticalBlock"] {
            height:100% !important;max-height:100% !important;justify-content:flex-start !important;
          }
          .st-key-character_equipment_view [data-testid="stElementContainer"]:has(.character-stat-panels) {
            position:absolute !important;left:.08rem !important;right:.08rem !important;bottom:.08rem !important;
            width:auto !important;height:calc(var(--character-stats-height) - .16rem) !important;
            max-height:calc(var(--character-stats-height) - .16rem) !important;min-height:0 !important;
            margin:0 !important;padding:0 !important;background:#fff !important;z-index:5 !important;
            overflow:hidden !important;box-sizing:border-box !important;contain:layout paint !important;
          }
          .st-key-character_equipment_view [data-testid="stMarkdownContainer"]:has(.character-stat-panels) {
            position:static !important;width:100% !important;height:100% !important;
            margin:0 !important;padding:0 !important;background:#fff !important;
          }
          /* Streamlit 在 stElementContainer 與 MarkdownContainer 之間另包了
             stMarkdown。三層都必須吃滿定位容器，否則畫面高度與真正的
             觸控捲動高度會不同，手指放開時就會回彈。 */
          .st-key-character_equipment_view [data-testid="stElementContainer"]:has(.character-stat-panels)
            > [data-testid="stMarkdown"],
          .st-key-character_equipment_view [data-testid="stElementContainer"]:has(.character-stat-panels)
            > [data-testid="stMarkdown"] > div,
          .st-key-character_equipment_view [data-testid="stElementContainer"]:has(.character-stat-panels)
            [data-testid="stMarkdownContainer"] {
            width:100% !important;height:100% !important;min-height:0 !important;
            margin:0 !important;padding:0 !important;box-sizing:border-box !important;
          }
          .character-stat-panels {
            position:static !important;
            width:100% !important;height:100% !important;min-height:0 !important;
            margin:0 !important;box-sizing:border-box !important;
          }
          .character-stat-box {
            position:relative !important;height:100% !important;min-height:0 !important;
            box-sizing:border-box !important;overflow:hidden !important;
          }
          .character-stat-list {
            height:100% !important;max-height:100% !important;min-height:0 !important;
            overflow-x:hidden !important;overflow-y:scroll !important;
            overscroll-behavior-y:contain !important;touch-action:pan-y !important;
            pointer-events:auto !important;-webkit-overflow-scrolling:touch;
            contain:content !important;
          }
          .st-key-character_scroll_view > [data-testid="stVerticalBlockBorderWrapper"] {
            height:calc(100dvh - 6.3rem) !important;max-height:calc(100dvh - 6.3rem) !important;
            overflow-y:auto !important;
          }
          .st-key-character_scroll_view {
            height:calc(100dvh - 6.3rem) !important;max-height:calc(100dvh - 6.3rem) !important;
            overflow-y:auto !important;overscroll-behavior:contain !important;
          }
          [data-testid="stDialog"] [role="dialog"] > button[aria-label="Close"] {
            inset:auto max(.28rem,env(safe-area-inset-right)) auto auto !important;
            top:max(.2rem,env(safe-area-inset-top)) !important;
            width:2rem !important;height:2rem !important;
            min-width:2rem !important;min-height:2rem !important;
          }
        }
        @media (max-width:1024px) and (orientation:landscape) {
          [data-testid="stDialog"] [role="dialog"] > button[aria-label="Close"] {
            inset:auto max(.42rem,env(safe-area-inset-right)) auto auto !important;
            top:max(.3rem,env(safe-area-inset-top)) !important;
            width:2.25rem !important;height:2.25rem !important;
            min-width:2.25rem !important;min-height:2.25rem !important;
          }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    render_character_equipment_hub(profile, save_profile)
