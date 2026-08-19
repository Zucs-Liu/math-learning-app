from datetime import datetime, timedelta, timezone

import streamlit as st

from game_data.config import AFFIX_NAMES, CHAPTERS, SLOT_ICONS, SLOT_NAMES
from game_logic.economy import (
    BASIC_AFFIXES,
    SHOP_ITEM_PRICE,
    SPECIAL_STONE_CRAFT_COST,
    SPECIAL_STONE_KEYS,
    craft_special_stone,
    purchase_shop_entry,
)
from game_logic.equipment import fixed_text, item_chapter_id, item_text
from game_logic.profile import equipped_item_uids
from game_ui.common import render_bottom_home_button
from game_ui.profile import render_item_comparison


def render_economy_screen(
    profile,
    save_profile,
    ensure_shop,
    find_item,
    render_forge_result_dialog,
    highest_shop_chapter,
    shop_paid_refresh_cost,
    refresh_shop,
    make_forged_item,
    remove_inventory_items,
):
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
        equipped_uids = equipped_item_uids(profile)
        eligible = [
            item for item in profile["inventory"]
            if item["stars"] in (1, 2)
            and item["uid"] not in equipped_uids
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
