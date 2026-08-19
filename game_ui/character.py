"""Character equipment hub: loadouts, inventory gear, pets and titles."""

from pathlib import Path

import streamlit as st

from game_data.config import SLOT_ICONS, SLOT_NAMES
from game_logic.economy import dismantle_inventory_items
from game_logic.equipment import item_text, player_stats
from game_logic.loot import find_inventory_item as find_item
from game_logic.profile import equipped_item_uids
from game_ui.profile import render_item_comparison


LEFT_SLOTS = ("helmet", "necklace", "weapon", "gloves", "ring")
RIGHT_SLOTS = ("armor", "shield", "belt", "boots")


def _equipment_slot(profile, slot, key_prefix):
    uid = profile["equipment"].get(slot)
    item = find_item(profile, uid) if uid else None
    icon = SLOT_ICONS[slot] if item else "▫️"
    with st.container(key=f"character_slot_{key_prefix}_{slot}"):
        if st.button(
            icon,
            key=f"{key_prefix}_slot_{slot}",
            help=f"{SLOT_NAMES[slot]}（點擊查看或更換）",
            use_container_width=True,
        ):
            st.session_state.character_selected_slot = slot
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
            with st.popover(
                f"⚔️ {loadouts[active]['name']}",
                use_container_width=True,
            ):
                selected = st.selectbox(
                    "切換裝備配置",
                    [0, 1],
                    index=active,
                    format_func=lambda index: loadouts[index]["name"],
                    key="character_loadout_choice",
                )
                _switch_loadout(profile, selected, save_profile)
                new_name = st.text_input(
                    "更改此套裝備名稱",
                    value=loadouts[active]["name"],
                    max_chars=16,
                    key=f"character_loadout_name_{active}",
                ).strip()
                if st.button("儲存名稱", key=f"save_loadout_name_{active}", use_container_width=True):
                    if new_name:
                        loadouts[active]["name"] = new_name
                        save_profile(profile)
                        st.rerun()
                if st.button("顯示目前裝備", key="show_character_equipment", use_container_width=True):
                    st.session_state.character_panel_view = "equipment"
                    st.rerun()
        if unused_col.button(
            "🎒 未使用裝備", key="show_character_unused",
            type="primary" if st.session_state.character_panel_view == "unused" else "secondary",
            use_container_width=True,
        ):
            st.session_state.character_panel_view = "unused"
            st.rerun()
        if pet_col.button(
            "🐾 寵物", key="show_character_pet",
            type="primary" if st.session_state.character_panel_view == "pet" else "secondary",
            use_container_width=True,
        ):
            st.session_state.character_panel_view = "pet"
            st.rerun()
        if title_col.button(
            "🏅 稱號", key="show_character_titles",
            type="primary" if st.session_state.character_panel_view == "titles" else "secondary",
            use_container_width=True,
        ):
            st.session_state.character_panel_view = "titles"
            st.rerun()


def _render_slot_selector(profile, slot, save_profile):
    current_uid = profile["equipment"].get(slot)
    current_item = find_item(profile, current_uid) if current_uid else None
    st.markdown(f"#### {SLOT_ICONS[slot]} {SLOT_NAMES[slot]}")
    if current_item:
        st.caption("目前裝備")
        st.write(item_text(current_item))
    else:
        st.caption("目前尚未裝備")

    candidates = [item for item in profile["inventory"] if item["slot"] == slot]
    if candidates:
        selected_uid = st.selectbox(
            "可穿戴裝備",
            [item["uid"] for item in candidates],
            index=next(
                (index for index, item in enumerate(candidates) if item["uid"] == current_uid),
                0,
            ),
            format_func=lambda uid: item_text(find_item(profile, uid)),
            key=f"character_slot_candidate_{slot}",
        )
        equip_col, close_col = st.columns(2)
        if equip_col.button("穿戴此裝備", key=f"character_slot_equip_{slot}", type="primary", use_container_width=True):
            profile["equipment"][slot] = selected_uid
            save_profile(profile)
            st.session_state.character_selected_slot = None
            st.rerun()
        if close_col.button("返回人物", key=f"character_slot_close_{slot}", use_container_width=True):
            st.session_state.character_selected_slot = None
            st.rerun()
        if current_item and st.button("卸下目前裝備", key=f"character_slot_remove_{slot}", use_container_width=True):
            profile["equipment"][slot] = None
            save_profile(profile)
            st.session_state.character_selected_slot = None
            st.rerun()
    else:
        st.info("目前沒有可穿戴的此部位裝備。")
        if st.button("返回人物", key=f"character_slot_empty_close_{slot}", use_container_width=True):
            st.session_state.character_selected_slot = None
            st.rerun()


def _render_equipment_scene(profile, save_profile):
    st.markdown(
        """
        <style>
        .st-key-character-equipment-scene [data-testid="stHorizontalBlock"] {
          display:flex !important; flex-direction:row !important; flex-wrap:nowrap !important;
          gap:.55rem !important; align-items:center !important;
        }
        .st-key-character-equipment-scene [data-testid="stColumn"] {min-width:0 !important;}
        .st-key-character-equipment-scene [data-testid="stImage"] img {
          max-height:32rem; object-fit:contain;
        }
        .st-key-character-equipment-scene [data-testid="stVerticalBlockBorderWrapper"] {
          background:linear-gradient(145deg,rgba(250,245,225,.96),rgba(238,226,187,.92));
          min-height:4.45rem;
        }
        @media (max-width:768px) and (orientation:portrait) {
          .st-key-character-equipment-scene [data-testid="stHorizontalBlock"] {
            display:flex !important;
            flex-direction:row !important;
            flex-wrap:nowrap !important;
            gap:.18rem !important;
            width:100% !important;
            align-items:center !important;
          }
          .st-key-character-equipment-scene [data-testid="stColumn"]:nth-child(1),
          .st-key-character-equipment-scene [data-testid="stColumn"]:nth-child(3) {
            flex:0 0 18% !important;width:18% !important;max-width:18% !important;
          }
          .st-key-character-equipment-scene [data-testid="stColumn"]:nth-child(2) {
            flex:0 0 63% !important;width:63% !important;max-width:63% !important;
          }
          .st-key-character-equipment-scene p,
          .st-key-character-equipment-scene button {font-size:.7rem !important;line-height:1.1 !important;}
          .st-key-character-equipment-scene [data-testid="stImage"] img {
            max-height:20rem !important;object-fit:contain !important;
          }
        }
        [class*="st-key-character-slot-"] button {
          min-height:3.45rem !important;font-size:1.45rem !important;padding:.2rem !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    with st.container(key="character_equipment_scene"):
        left, hero, right = st.columns([3, 3.4, 3], vertical_alignment="center")
        with left:
            for slot in LEFT_SLOTS:
                _equipment_slot(profile, slot, "left")
        with hero:
            st.markdown(
                f"<div style='text-align:center;font-weight:800'>Lv{profile['level']}　{profile['name']}</div>",
                unsafe_allow_html=True,
            )
            selected_slot = st.session_state.get("character_selected_slot")
            if selected_slot in SLOT_NAMES:
                _render_slot_selector(profile, selected_slot, save_profile)
            elif selected_slot == "pet":
                st.info("尚未裝備寵物（下一階段開放）")
                if st.button("返回人物", key="character_pet_slot_close", use_container_width=True):
                    st.session_state.character_selected_slot = None
                    st.rerun()
            else:
                hero_file = (
                    "blue-silver-hero-female.webp"
                    if profile.get("gender") == "female"
                    else "blue-silver-hero.webp"
                )
                hero_path = Path(__file__).resolve().parent.parent / "assets" / "heroes" / hero_file
                st.image(str(hero_path), use_container_width=True)
        with right:
            for slot in RIGHT_SLOTS:
                _equipment_slot(profile, slot, "right")
            with st.container(key="character_slot_right_pet"):
                if st.button("🐾", key="character_pet_equipment_slot", help="寵物（點擊查看）", use_container_width=True):
                    st.session_state.character_selected_slot = "pet"
                    st.rerun()


def _render_compact_stats(profile):
    stats = player_stats(profile)
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
    ] or ["<div><b>目前無特殊詞條</b><span>—</span></div>"]
    exp_text = (
        f"{profile['exp']} / {profile['level'] * 100}"
        if profile["level"] < 20 else "已滿級"
    )
    st.markdown(
        f"""
        <style>
        .character-stat-panels {{display:grid;grid-template-columns:1fr 1fr;gap:.65rem;margin-top:.65rem;}}
        .character-stat-box {{border:1px solid #d6dce5;border-radius:10px;padding:.75rem;background:#fff;min-width:0;}}
        .character-stat-box h4 {{margin:0 0 .45rem;font-size:1rem;}}
        .character-stat-list {{max-height:12rem;overflow-y:auto;padding-right:.2rem;}}
        .character-stat-list div {{display:flex;justify-content:space-between;gap:.4rem;padding:.2rem 0;border-bottom:1px solid #edf0f4;font-size:.9rem;}}
        .character-stat-list div:last-child {{border-bottom:0;}}
        .character-stat-list span {{white-space:nowrap;font-weight:700;}}
        @media (max-width:768px) and (orientation:portrait) {{
          .character-stat-panels {{gap:.28rem;}}
          .character-stat-box {{padding:.42rem;}}
          .character-stat-box h4 {{font-size:.78rem;}}
          .character-stat-list div {{font-size:.66rem;line-height:1.15;}}
        }}
        </style>
        <div class="character-stat-panels">
          <section class="character-stat-box">
            <h4>基礎能力</h4>
            <div class="character-stat-list">
              <div><b>等級</b><span>Lv{profile['level']}</span></div>
              <div><b>EXP</b><span>{exp_text}</span></div>
              <div><b>HP</b><span>{stats['hp']:.1f}</span></div>
              <div><b>攻擊</b><span>{stats['attack']:.1f}</span></div>
              <div><b>防禦</b><span>{stats['defense']:.1f}</span></div>
              <div><b>攻速</b><span>{stats['attack_speed']:.2f}/秒</span></div>
            </div>
          </section>
          <section class="character-stat-box">
            <h4>特殊詞條</h4>
            <div class="character-stat-list">{''.join(active_effects)}</div>
          </section>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_unused_equipment(profile, save_profile):
    equipped_uids = equipped_item_uids(profile)
    items = [item for item in profile["inventory"] if item["uid"] not in equipped_uids]
    st.write(f"### 未使用裝備（{len(items)}件）")
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
    if not visible:
        st.info("目前沒有符合條件的未使用裝備。")
        return
    for start in range(0, len(visible), 5):
        columns = st.columns(5)
        for column, item in zip(columns, visible[start:start + 5]):
            label = f"{SLOT_ICONS[item['slot']]} {item['name']}\n{'⭐' * item['stars']}"
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


def _render_pet_placeholder():
    st.write("### 🐾 寵物")
    st.info("寵物召喚與寵物能力將在下一階段開放。")
    st.markdown("**當前裝備：尚未裝備寵物**")
    st.caption("此處已預留寵物立繪、屬性、詞條、技能與兩套寵物配置的位置。")


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
        @media (max-width:768px) and (orientation:portrait) {
          .st-key-character-panel-navigation [data-testid="stHorizontalBlock"] {
            display:flex !important;flex-direction:row !important;flex-wrap:nowrap !important;gap:.15rem !important;
          }
          .st-key-character-panel-navigation [data-testid="stColumn"] {
            min-width:0 !important;flex:1 1 25% !important;width:25% !important;
          }
          .st-key-character-panel-navigation button {
            padding:.3rem .05rem !important;font-size:.65rem !important;white-space:nowrap !important;
          }
          .st-key-character-loadout-row [data-testid="stHorizontalBlock"] {
            display:flex !important;flex-direction:row !important;flex-wrap:nowrap !important;
          }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        "<style>.st-key-character-hub-frame{border:3px solid #142a38;border-radius:4px;padding:.45rem}</style>",
        unsafe_allow_html=True,
    )
    with st.container(key="character_hub_frame"):
        st.markdown("<h3 style='text-align:center;margin:.1rem 0 .35rem'>角色能力</h3>", unsafe_allow_html=True)
        _render_panel_navigation(profile, save_profile)
        view = st.session_state.character_panel_view
        if view == "equipment":
            _render_equipment_scene(profile, save_profile)
            _render_compact_stats(profile)
        elif view == "unused":
            _render_unused_equipment(profile, save_profile)
        elif view == "pet":
            _render_pet_placeholder()
        else:
            _render_titles(profile, save_profile)
