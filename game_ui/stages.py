import streamlit as st

from game_data.config import CHAPTERS, SLOT_NAMES, UNITS
from game_logic.equipment import fixed_value_for


def render_chapter_selector(profile, available_chapters, chapter_unit_ids):
    """Render chapter selection and return the selected chapter and its units."""
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
    total_stars = sum(
        profile["unit_best_stars"][unit_id] for unit_id in current_unit_ids
    )
    max_stars = len(current_unit_ids) * 3
    st.write(
        f"{CHAPTERS[chapter_id]['number']}星級：**{total_stars}／{max_stars}** "
        f"{'⭐' * total_stars}"
    )
    return chapter_id, current_unit_ids


def render_unit_cards(
    profile,
    current_unit_ids,
    unit_unlocked,
    start_quiz,
    make_random_item,
    save_profile,
):
    """Render unit launch and sweep-ticket controls."""
    st.subheader("選擇單元")
    for unit_id in current_unit_ids:
        unit = UNITS[unit_id]
        unlocked = unit_unlocked(profile, unit_id)
        cols = st.columns([1, 4, 1, 1])
        cols[0].write(f"### {unit_id}")
        cols[1].write(
            f"**{unit['name']}**｜{unit['description']}  \n"
            f"掉落：{'、'.join(SLOT_NAMES[slot] for slot in unit['slots'])}"
        )
        stars = profile["unit_best_stars"][unit_id]
        if unlocked:
            if cols[2].button(
                f"{'⭐' * stars or '未通關'}｜開始",
                key=f"start_{unit_id}",
                use_container_width=True,
            ):
                start_quiz(unit_id)
                st.rerun()
            if cols[3].button(
                f"🎫 擊殺券 ×{profile['sweep_tickets']}",
                key=f"sweep_{unit_id}",
                disabled=stars <= 0 or profile["sweep_tickets"] <= 0,
                use_container_width=True,
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
            cols[2].button(
                "🔒 尚未解鎖",
                disabled=True,
                key=f"locked_{unit_id}",
                use_container_width=True,
            )
            cols[3].button(
                "🎫 尚未通關",
                disabled=True,
                key=f"sweep_locked_{unit_id}",
                use_container_width=True,
            )


def render_chapter_reward_status(profile, chapter_id):
    """Render the already-earned four-star chapter reward summaries."""
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
    elif chapter_id == "6":
        if profile["chapter6_reward_claimed"]:
            st.success(f"第六章滿星成就已完成：★★★★ 第六章・黃金比例手甲｜固定：攻擊力 +{fixed_value_for('6', 'gloves', 4)[1]:g}｜詞條：攻擊力 +25%")
        if profile["chapter6_collection_reward_claimed"]:
            st.success(f"第六章三星全裝收藏已完成：100 EXP＋★★★★ 第六章・等比靈環｜固定：第一擊額外傷害 {fixed_value_for('6', 'ring', 4)[1]:.0%}｜詞條：暴擊率 +25%")
        if profile["chapter6_elite_reward_claimed"]:
            st.success(f"第六章菁英征服已完成：★★★★ 第六章・鬼火王刃｜固定：攻擊力 +{fixed_value_for('6', 'weapon', 4)[1]:g}｜詞條：對菁英BOSS傷害 +25%")
