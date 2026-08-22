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
        with st.container(
            key="character_slot_actions", horizontal=True,
            horizontal_alignment="center", vertical_alignment="center", gap="small",
        ):
            if st.button("穿戴", key=f"character_slot_equip_{slot}", type="primary", width="stretch"):
                profile["equipment"][slot] = selected_uid
                save_profile(profile)
                st.session_state.character_selected_slot = None
                st.rerun()
            if current_item and st.button("卸下", key=f"character_slot_remove_{slot}", width="stretch"):
                profile["equipment"][slot] = None
                save_profile(profile)
                st.session_state.character_selected_slot = None
                st.rerun()
            if st.button("返回", key=f"character_slot_close_{slot}", width="stretch"):
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
        .st-key-character_center_panel [data-testid="stImage"] img {max-height:13.6rem !important;}
        .st-key-character_center_panel [data-testid="stImage"] {
          display:flex !important;justify-content:center !important;align-items:flex-start !important;width:100% !important;
        }
        .st-key-character_slot_actions [data-testid="stHorizontalBlock"] {
          display:flex !important;flex-direction:row !important;flex-wrap:nowrap !important;gap:.18rem !important;
        }
        .st-key-character_slot_actions {
          display:flex !important;flex-direction:row !important;flex-wrap:nowrap !important;
          align-items:center !important;gap:.18rem !important;width:100% !important;
        }
        .st-key-character_slot_actions > div,
        .st-key-character_slot_actions [class*="st-key-character_slot_equip_"],
        .st-key-character_slot_actions [class*="st-key-character_slot_remove_"],
        .st-key-character_slot_actions [class*="st-key-character_slot_close_"] {
          flex:1 1 0 !important;min-width:0 !important;width:auto !important;
        }
        .st-key-character_slot_actions [data-testid="stColumn"] {
          min-width:0 !important;flex:1 1 33.333% !important;width:33.333% !important;
        }
        .st-key-character_slot_actions button {
          width:100% !important;min-height:1.8rem !important;padding:.08rem .03rem !important;
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
                elif selected_slot == "pet":
                    st.info("尚未裝備寵物（下一階段開放）")
                    if st.button("返回人物", key="character_pet_slot_close", use_container_width=True):
                        st.session_state.character_selected_slot = None
                        st.rerun()
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
            display:grid;grid-template-rows:2.15rem minmax(0,1fr);
            height:100%;min-height:0;padding:.18rem .28rem;border-radius:5px;box-sizing:border-box;
            overflow:hidden;isolation:isolate;
          }}
          .character-stat-box h4 {{
            display:flex;align-items:center;justify-content:center;
            font-size:clamp(.9rem,3.8vw,1.08rem);line-height:1;margin:0;text-align:center;
          }}
          .character-stat-list {{
            position:relative;z-index:20;display:block;
            width:100%;height:100%;max-height:100%;min-height:0;
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
            box-sizing:border-box;height:calc(100% / 6);min-height:calc(100% / 6);
            font-size:clamp(.72rem,3.1vw,.92rem);line-height:1.05;padding:.05rem 0;
          }}
          .character-stat-list div b {{min-width:0;line-height:1.12;overflow-wrap:anywhere;}}
          .character-stat-box:nth-child(2) .character-stat-list div {{
            height:auto;min-height:calc(100% / 6);flex-shrink:0;
            align-items:center;padding:.12rem 0;
          }}
          .character-stat-list .character-stat-scroll-spacer {{
            display:block;height:3.6rem !important;min-height:3.6rem !important;
            padding:0 !important;border:0 !important;pointer-events:none;
          }}
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
              <div class="character-stat-scroll-spacer" aria-hidden="true"></div>
            </div>
          </section>
          <section class="character-stat-box">
            <h4>特殊詞條</h4>
            <div class="character-stat-list">{''.join(active_effects)}<div class="character-stat-scroll-spacer" aria-hidden="true"></div></div>
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
    else:
        # 未使用裝備、寵物與稱號會持續增加，限制在視窗內獨立捲動。
        with st.container(key="character_scroll_view", height=520, border=False):
            if view == "unused":
                _render_unused_equipment(profile, save_profile)
            elif view == "pet":
                _render_pet_placeholder()
            else:
                _render_titles(profile, save_profile)


def _close_character_dialog():
    st.session_state.show_character_dialog = False
    st.session_state.character_panel_view = "equipment"
    st.session_state.character_selected_slot = None
    st.rerun()


@st.dialog("角色能力", width="large", dismissible=False)
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
        .st-key-character_dialog_close {
          position:absolute !important;right:.65rem !important;top:.55rem !important;z-index:20 !important;
          width:2.45rem !important;height:2.45rem !important;
        }
        .st-key-character_dialog_close button {
          width:2.45rem !important;height:2.45rem !important;min-height:2.45rem !important;
          padding:0 !important;border:2px solid #111 !important;border-radius:4px !important;
          background:#fff !important;color:#e53935 !important;font-size:1.35rem !important;font-weight:900 !important;
        }
        [data-testid="stDialog"] [role="dialog"] .st-key-character_dialog_close button,
        [data-testid="stDialog"] [role="dialog"] .st-key-character_dialog_close button * {
          color:#e53935 !important;border-color:#111 !important;background:#fff !important;
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
            margin:0 !important;padding:0 !important;overflow:hidden !important;z-index:2147483647 !important;
          }
          body:has([data-testid="stDialog"]) [data-baseweb="modal"] > div {
            margin:0 !important;padding:0 !important;max-width:100% !important;max-height:100dvh !important;
          }
          [data-testid="stDialog"] {
            position:fixed !important;inset:0 !important;z-index:2147483647 !important;
            box-sizing:border-box !important;width:100% !important;height:100dvh !important;
            max-width:100% !important;max-height:100dvh !important;
            padding:0 !important;margin:0 !important;align-items:stretch !important;justify-content:stretch !important;
            overflow:hidden !important;overscroll-behavior:none !important;background:#fff !important;
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
          .st-key-character_dialog_close {
            right:.28rem !important;top:.2rem !important;width:2rem !important;height:2rem !important;
          }
          .st-key-character_dialog_close button {
            width:2rem !important;height:2rem !important;min-height:2rem !important;font-size:1.05rem !important;
          }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    with st.container(key="character_dialog_close"):
        if st.button("✕", key="close_character_dialog", help="關閉"):
            _close_character_dialog()
    render_character_equipment_hub(profile, save_profile)
