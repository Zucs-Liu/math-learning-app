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


def _equipment_slot(profile, slot, save_profile, key_prefix):
    uid = profile["equipment"].get(slot)
    item = find_item(profile, uid) if uid else None
    label = f"{SLOT_ICONS[slot]} {SLOT_NAMES[slot]}"
    with st.container(border=True):
        st.markdown(f"**{label}**")
        if item:
            with st.popover(f"{'⭐' * item['stars']} {item['name']}", use_container_width=True):
                st.write(item_text(item))
                if st.button("卸下", key=f"{key_prefix}_off_{slot}", use_container_width=True):
                    profile["equipment"][slot] = None
                    save_profile(profile)
                    st.rerun()
        else:
            st.caption("尚未裝備")


def _render_loadout_controls(profile, save_profile):
    active = int(profile.get("active_equipment_loadout", 0))
    loadouts = profile["equipment_loadouts"]
    current = loadouts[active]
    label_col, switch_col = st.columns([3, 1], vertical_alignment="bottom")
    new_name = label_col.text_input(
        "配裝名稱",
        value=current.get("name", f"裝備配置 {active + 1}"),
        max_chars=16,
        key=f"loadout_name_{active}",
    ).strip()
    if new_name and new_name != current.get("name"):
        current["name"] = new_name
        save_profile(profile)
    other = 1 - active
    if switch_col.button(
        f"切換至：{loadouts[other]['name']}",
        key="switch_equipment_loadout",
        use_container_width=True,
    ):
        loadouts[active]["equipment"] = dict(profile["equipment"])
        profile["active_equipment_loadout"] = other
        profile["equipment"] = dict(loadouts[other]["equipment"])
        save_profile(profile)
        st.rerun()
    st.caption(f"當前裝備：{current['name']}（第 {active + 1} 套）")


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
          .st-key-character-equipment-scene [data-testid="stHorizontalBlock"] {gap:.18rem !important;}
          .st-key-character-equipment-scene [data-testid="stColumn"]:nth-child(1),
          .st-key-character-equipment-scene [data-testid="stColumn"]:nth-child(3) {
            flex:0 0 31% !important; width:31% !important;
          }
          .st-key-character-equipment-scene [data-testid="stColumn"]:nth-child(2) {
            flex:0 0 36% !important; width:36% !important;
          }
          .st-key-character-equipment-scene p,
          .st-key-character-equipment-scene button {font-size:.65rem !important; line-height:1.12 !important;}
          .st-key-character-equipment-scene [data-testid="stVerticalBlockBorderWrapper"] {
            padding:.18rem !important;min-height:3.6rem !important;
          }
          .st-key-character-equipment-scene [data-testid="stImage"] img {
            max-height:19rem !important;object-fit:contain !important;
          }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    with st.container(key="character_equipment_scene"):
        left, hero, right = st.columns([3, 3.4, 3], vertical_alignment="center")
        with left:
            for slot in LEFT_SLOTS:
                _equipment_slot(profile, slot, save_profile, "left")
        with hero:
            hero_file = (
                "blue-silver-hero-female.webp"
                if profile.get("gender") == "female"
                else "blue-silver-hero.webp"
            )
            hero_path = Path(__file__).resolve().parent.parent / "assets" / "heroes" / hero_file
            st.image(str(hero_path), use_container_width=True)
            st.markdown(
                f"<div style='text-align:center;font-weight:800'>Lv{profile['level']}　{profile['name']}</div>",
                unsafe_allow_html=True,
            )
        with right:
            for slot in RIGHT_SLOTS:
                _equipment_slot(profile, slot, save_profile, "right")
            with st.container(border=True):
                st.markdown("**🐾 寵物**")
                st.caption("尚未裝備（下一階段開放）")


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
          [data-testid="stTabs"] [role="tablist"] {gap:0 !important;width:100% !important;}
          [data-testid="stTabs"] [role="tab"] {
            flex:1 1 25% !important;min-width:0 !important;padding:.38rem .08rem !important;
            font-size:.67rem !important;white-space:nowrap !important;
          }
          .st-key-character-loadout-row [data-testid="stHorizontalBlock"] {
            display:flex !important;flex-direction:row !important;flex-wrap:nowrap !important;
          }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    current_tab, unused_tab, pet_tab, title_tab = st.tabs(
        ["⚔️ 目前裝備", "🎒 未使用裝備", "🐾 寵物", "🏅 稱號"]
    )
    with current_tab:
        _render_loadout_controls(profile, save_profile)
        _render_equipment_scene(profile, save_profile)
        _render_compact_stats(profile)
    with unused_tab:
        _render_unused_equipment(profile, save_profile)
    with pet_tab:
        _render_pet_placeholder()
    with title_tab:
        _render_titles(profile, save_profile)
