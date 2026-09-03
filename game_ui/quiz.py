import re

import streamlit as st

from game_data.config import MAX_QUESTIONS
from game_logic.equipment import item_text
from game_logic.loot import find_inventory_item
from game_ui.common import focus_answer_input
from game_ui.profile import render_item_comparison


@st.fragment
def render_quiz_panel(submit_quiz_answer):
    """Render the live question panel while quiz state stays in the app session."""
    if st.session_state.screen != "quiz":
        st.rerun(scope="app")

    with st.container(key="quiz-mobile-stats"):
        cols = st.columns(4)
        cols[0].metric(
            "作答進度", f"{st.session_state.attempts}/{MAX_QUESTIONS}題"
        )
        cols[1].metric("目前連擊", st.session_state.combo)
        cols[2].metric("最高連擊", st.session_state.max_combo)
        cols[3].metric("答對", st.session_state.correct)
    st.progress(min(1.0, st.session_state.attempts / MAX_QUESTIONS))

    if st.session_state.question.get("ratio_pair"):
        st.markdown(f"## {st.session_state.question['text']}")
    elif st.session_state.question.get("fraction"):
        question = st.session_state.question
        source_numbers = re.findall(r"\d+", str(question.get("text", "")))
        source_numerator = question.get(
            "question_numerator", source_numbers[0] if source_numbers else "?"
        )
        source_denominator = question.get(
            "question_denominator",
            source_numbers[1] if len(source_numbers) > 1 else "?",
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
        if st.session_state.question.get("fraction") or st.session_state.question.get("ratio_pair"):
            fraction_col = st.columns([1, 2, 1])[1]
            fraction_col.number_input(
                "前項" if st.session_state.question.get("ratio_pair") else "分子",
                value=None,
                step=1,
                format="%d",
                key="answer_numerator",
                placeholder="前項" if st.session_state.question.get("ratio_pair") else "分子",
            )
            fraction_col.markdown("<div style='text-align:center;font-size:1.4rem'>：</div>" if st.session_state.question.get("ratio_pair") else "<div style='height:3px;background:currentColor;margin:-.25rem 0 .4rem;'></div>", unsafe_allow_html=True)
            fraction_col.number_input(
                "後項" if st.session_state.question.get("ratio_pair") else "分母",
                value=None,
                step=1,
                min_value=1,
                format="%d",
                key="answer_denominator",
                placeholder="後項" if st.session_state.question.get("ratio_pair") else "分母",
            )
        else:
            is_decimal_unit = st.session_state.selected_unit.startswith(("3-", "4-"))
            st.number_input(
                "你的答案",
                value=None,
                step=0.01 if is_decimal_unit else 1.0,
                format="%.2f" if is_decimal_unit else "%.0f",
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


def render_quiz_result(profile, save_profile, start_quiz):
    """Render a processed quiz result without owning reward calculations."""
    st.subheader(f"單元{st.session_state.selected_unit}完成")
    st.markdown(f"## {'⭐' * st.session_state.stars or '未取得星星'}")
    st.write(
        f"最高連擊 **{st.session_state.max_combo}**，"
        f"共答對 **{st.session_state.correct}題**。"
    )
    average_seconds = (
        st.session_state.quiz_elapsed / st.session_state.attempts
        if st.session_state.attempts
        else 0
    )
    st.caption(
        f"共作答 {st.session_state.attempts}題｜"
        f"總時間 {st.session_state.quiz_elapsed:.1f}秒｜"
        f"平均每題 {average_seconds:.1f}秒"
    )

    if st.session_state.stars == 0:
        st.warning("本回合尚未答對任何題目，因此不獲得星星、經驗值或裝備。")
    elif st.session_state.earned_exp:
        level_message = (
            f" 已升級到 Lv{st.session_state.level_up_to}！"
            if st.session_state.level_up_to
            else ""
        )
        st.success(
            f"刷新單元成績，獲得 {st.session_state.earned_exp} EXP！{level_message}"
        )
    else:
        st.info("經驗值不重複領取；重刷仍可取得新詞條裝備。")

    pending_uid = st.session_state.pending_item_uid
    item = find_inventory_item(profile, pending_uid) if pending_uid else None
    if item:
        st.write("### 本次掉落")
        render_item_comparison(profile, item)
        equip_col, keep_col = st.columns(2)
        if equip_col.button("立即裝備", type="primary", use_container_width=True):
            profile["equipment"][item["slot"]] = item["uid"]
            save_profile(profile)
            st.session_state.pending_item_uid = None
            st.rerun()
        if keep_col.button("放入物品欄", use_container_width=True):
            st.session_state.pending_item_uid = None
            st.rerun()
    elif st.session_state.drop_exhausted:
        st.info("本次沒有出現新的詞條組合；你仍可重複挑戰，練習並刷新關卡成績。")

    if st.session_state.chapter_reward_new:
        reward = next(
            (inventory_item for inventory_item in profile["inventory"] if inventory_item.get("achievement")),
            None,
        )
        st.success(f"🏆 第一章9星達成！免費獲得：{item_text(reward)}")
    if st.session_state.collection_reward_new:
        level_message = (
            f" 已升級到 Lv{st.session_state.collection_level_up_to}！"
            if st.session_state.collection_level_up_to
            else ""
        )
        st.success(
            "🏆 九部位三星收集完成！獲得「三星全裝收藏家」成就與100 EXP！"
            f"{level_message}"
        )
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
