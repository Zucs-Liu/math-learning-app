import re

import streamlit as st

from game_data.config import MAX_QUESTIONS
from game_ui.common import focus_answer_input


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

    if st.session_state.question.get("fraction"):
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
        if st.session_state.question.get("fraction"):
            fraction_col = st.columns([1, 2, 1])[1]
            fraction_col.number_input(
                "分子",
                value=None,
                step=1,
                format="%d",
                key="answer_numerator",
                placeholder="分子",
            )
            fraction_col.markdown(
                "<div style='height:3px;background:currentColor;margin:-.25rem 0 .4rem;'></div>",
                unsafe_allow_html=True,
            )
            fraction_col.number_input(
                "分母",
                value=None,
                step=1,
                min_value=1,
                format="%d",
                key="answer_denominator",
                placeholder="分母",
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
