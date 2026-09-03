import streamlit as st

from game_data.config import CHAPTERS, SLOT_ICONS, SLOT_NAMES, UNITS
from game_logic.economy import dismantle_inventory_items, dismantle_value
from game_logic.equipment import fixed_text, four_star_item_name, item_chapter_id
from game_logic.loot import (
    achievement_was_collected,
    collected_achievement_slots,
    collected_three_star_slots as loot_collected_three_star_slots,
    find_achievement_item,
)
from game_ui.profile import render_item_comparison


def _collected_three_star_slots(profile, chapter_id):
    return loot_collected_three_star_slots(
        profile, chapter_id, SLOT_NAMES, item_chapter_id
    )


def _render_legacy_backpack(profile, save_profile):
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
            bulk_coins, bulk_stones = dismantle_value(selected_bulk_items)
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
                if dismantle_inventory_items(profile, selected_bulk_items):
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
                                if dismantle_inventory_items(profile, [item]):
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


def _pet_training_consumables(profile):
    element_names = {
        "wood": "木", "earth": "土", "water": "水",
        "fire": "火", "light": "光", "dark": "暗",
    }
    items = [("🥫", "美味罐頭", int(profile.get("pet_food_cans", 0)))]
    elixirs = profile.get("pet_element_elixirs", {})
    for element in ("wood", "earth", "water", "fire", "light", "dark"):
        items.append(
            ("🧪", f"特製仙丹（{element_names[element]}屬性）", int(elixirs.get(element, 0)))
        )
    return items


def _render_consumable_grid(container_key, consumables):
    """Render any number of consumables as continuous five-column rows."""
    with st.container(key=container_key):
        for start in range(0, len(consumables), 5):
            row = consumables[start:start + 5]
            cols = st.columns(5)
            for col, (icon, name, count) in zip(cols, row):
                col.metric(f"{icon} {name}", count)


def render_backpack(profile, save_profile):
    """The backpack now contains consumables only; gear and titles moved to Character."""
    st.write("### 🧪 消耗道具")
    st.markdown(
        """
        <style>
        [class*="st-key-backpack_consumables"] [data-testid="stColumn"] {
          border:1px solid #d9dee7;border-radius:8px;padding:.35rem !important;min-height:6rem;
          overflow:visible !important;
        }
        [class*="st-key-backpack_consumables"] [data-testid="stMetricLabel"],
        [class*="st-key-backpack_consumables"] [data-testid="stMetricLabel"] > div,
        [class*="st-key-backpack_consumables"] [data-testid="stMetricLabel"] p {
          white-space:normal !important;overflow:visible !important;text-overflow:clip !important;
          overflow-wrap:anywhere !important;word-break:break-word !important;
          -webkit-line-clamp:unset !important;display:block !important;
        }
        @media (max-width:768px) and (orientation:portrait) {
          [class*="st-key-backpack_consumables"] [data-testid="stHorizontalBlock"] {
            display:flex !important;flex-direction:row !important;flex-wrap:nowrap !important;
            gap:.12rem !important;width:100% !important;
          }
          [class*="st-key-backpack_consumables"] [data-testid="stColumn"] {
            min-width:0 !important;width:calc(20% - .1rem) !important;
            max-width:calc(20% - .1rem) !important;flex:0 0 calc(20% - .1rem) !important;
            padding:.12rem !important;min-height:5.5rem !important;overflow:visible !important;
          }
          [class*="st-key-backpack_consumables"] [data-testid="stMetricLabel"] {
            font-size:.58rem !important;line-height:1.08 !important;white-space:normal !important;
            min-height:2.45rem !important;align-items:flex-start !important;
          }
          [class*="st-key-backpack_consumables"] [data-testid="stMetricValue"] {
            font-size:1rem !important;line-height:1.1 !important;
          }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    consumables = [
        ("🎫", "擊殺券", profile["sweep_tickets"]),
        ("🎟️", "召喚券", int(profile.get("summon_tickets", 0))),
        ("💎", "融煉石", profile["smelting_stones"]),
        ("🧭", "部位融煉石", profile["slot_smelting_stones"]),
        ("🔷", "基礎詞條融煉石", profile["basic_affix_smelting_stones"]),
        ("🔶", "進階詞條融煉石", profile["advanced_affix_smelting_stones"]),
    ] + _pet_training_consumables(profile)
    _render_consumable_grid("backpack_consumables", consumables)
    st.caption("未使用裝備與稱號已移至『角色能力』；背包專門收納消耗道具。")


def render_gallery(profile, chapter_unit_ids, unit_unlocked, start_quiz):
    gallery_chapter = st.selectbox(
        "選擇圖鑑章節", list(CHAPTERS),
        format_func=lambda cid: f"{CHAPTERS[cid]['number']}：{CHAPTERS[cid]['name']}",
        key="gallery_chapter",
    )
    star_filter = st.selectbox("星級篩選", ["全部", "三星", "四星"], key="gallery_star_filter")
    chapter = CHAPTERS[gallery_chapter]
    collected_slots = _collected_three_star_slots(profile, gallery_chapter)
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
            "6": [
                ("chapter-6", four_star_item_name("6", "黃金比例手甲"), "gloves", "完成第六章所有三星單元", "unit"),
                ("chapter-6-collection", four_star_item_name("6", "等比靈環"), "ring", "收集第六章九部位三星", "collection"),
                ("chapter-6-elite", four_star_item_name("6", "鬼火王刃"), "weapon", "首次擊敗第六章菁英BOSS「鬼火王」", "elite"),
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
            owned_item = find_achievement_item(profile, unit_key)
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
                    "6": "chapter6_boss_wins",
                }[gallery_chapter], 0) > 0
                if col.button("前往菁英BOSS", key=f"elite_go_{unit_key}", disabled=not elite_ready, use_container_width=True):
                    st.session_state.selected_chapter = gallery_chapter
                    st.session_state.selected_boss_type = "elite"
                    st.session_state.scroll_boss_to_top = True
                    st.session_state.screen = "boss_ready"
                    st.rerun()
        st.caption("四星固定值不隨章節倍率變動，但都高於首次登場章節可掉落的同部位三星固定值。")
