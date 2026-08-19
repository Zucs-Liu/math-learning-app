"""Shared Streamlit widgets and navigation helpers.

These helpers contain presentation behavior only.  Gameplay rules and database
operations must stay in ``game_logic`` and ``data_access`` respectively.
"""

import streamlit as st
import streamlit.components.v1 as components


def focus_answer_input():
    """Refocus the current quiz answer field after a Streamlit rerun."""
    components.html(
        """
        <script>
        const focusAnswer = () => {
            const doc = parent.window.document;
            const answer = doc.querySelector('input[aria-label="你的答案"]')
                || doc.querySelector('input[placeholder="輸入後按 Enter"]')
                || doc.querySelector('input[aria-label="分子"]')
                || doc.querySelector('input[placeholder="分子"]');
            if (answer) {
                answer.focus({preventScroll: true});
                answer.click();
                if (answer.select) answer.select();
            }
        };
        [50, 150, 300, 600, 1000].forEach(delay => setTimeout(focusAnswer, delay));
        </script>
        """,
        height=0,
        scrolling=False,
    )


def scroll_page_to_top(state_key):
    """Scroll once after navigation without disturbing later manual scrolling."""
    if not st.session_state.get(state_key):
        return
    components.html(
        """
        <script>
        const scrollTop = () => {
            const doc = parent.window.document;
            const selectors = [
                '.stMain',
                'section.main',
                '[data-testid="stMain"]',
                '[data-testid="stAppViewContainer"]',
                '[data-testid="stApp"]',
                '.main'
            ];
            selectors.forEach(selector => {
                doc.querySelectorAll(selector).forEach(node => {
                    node.scrollTop = 0;
                    node.scrollLeft = 0;
                    if (node.scrollTo) node.scrollTo({top: 0, left: 0, behavior: 'instant'});
                });
            });
            doc.documentElement.scrollTop = 0;
            doc.documentElement.scrollLeft = 0;
            doc.body.scrollTop = 0;
            doc.body.scrollLeft = 0;
            parent.window.scrollTo(0, 0);
        };
        scrollTop();
        requestAnimationFrame(() => requestAnimationFrame(scrollTop));
        </script>
        """,
        height=1,
        scrolling=False,
    )
    st.session_state[state_key] = False


def remove_stale_elements_before(marker_id):
    """Remove stale tab/button rows briefly retained by Streamlit navigation."""
    st.markdown(f'<div id="{marker_id}"></div>', unsafe_allow_html=True)
    components.html(
        f"""
        <script>
        const clearStaleElements = () => {{
            const doc = parent.document;
            const marker = doc.getElementById('{marker_id}');
            if (!marker) return;
            const markerTop = marker.getBoundingClientRect().top;

            doc.querySelectorAll('[data-testid="stTabs"]').forEach(tabs => {{
                const rect = tabs.getBoundingClientRect();
                if (rect.bottom > 0 && rect.top < markerTop - 2) tabs.remove();
            }});

            doc.querySelectorAll('button').forEach(button => {{
                if (button.closest('header[data-testid="stHeader"]')) return;
                const rect = button.getBoundingClientRect();
                if (rect.bottom <= 0 || rect.top >= markerTop - 2) return;
                const row = button.closest('[data-testid="stHorizontalBlock"]');
                const element = row || button.closest('[data-testid="stElementContainer"]');
                if (element) element.remove();
            }});
        }};
        [0, 40, 100, 220, 450, 800, 1300].forEach(
            delay => setTimeout(clearStaleElements, delay)
        );
        </script>
        """,
        height=0,
        scrolling=False,
    )


def force_top_before_navigation():
    """Reset mobile scroll position immediately before changing screens."""
    components.html(
        """
        <script>
        const doc = parent.window.document;
        doc.querySelectorAll('.stMain, section.main, [data-testid="stMain"], [data-testid="stAppViewContainer"]')
          .forEach(node => { node.scrollTop = 0; node.scrollLeft = 0; });
        doc.documentElement.scrollTop = 0;
        doc.body.scrollTop = 0;
        parent.window.scrollTo(0, 0);
        </script>
        """,
        height=1,
        scrolling=False,
    )


def render_health_bar(label, current, maximum, color):
    """Render a named numeric health bar."""
    ratio = max(0.0, min(1.0, current / maximum if maximum else 0.0))
    label_col, bar_col = st.columns([1.3, 8.7], vertical_alignment="center")
    label_col.markdown(f"**{label}**  \n{current:.1f} / {maximum:.1f}")
    bar_col.markdown(
        f"""
        <div style="width:100%;height:24px;background:#e9edf2;border-radius:12px;overflow:hidden;">
          <div style="width:{ratio * 100:.2f}%;height:100%;background:{color};border-radius:12px;"></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _close_feature_page():
    st.session_state.shop_purchase_uid = None
    st.session_state.forge_result_uid = None
    st.session_state.screen = "home"
    st.rerun()


def render_page_close_button(key):
    """Render a compact fixed close button without consuming a content row."""
    st.markdown(
        """
        <style>
        .st-key-page-close-top {
          position:fixed !important;right:1.15rem;top:4.15rem;z-index:999;
          width:2.65rem !important;height:2.65rem !important;
        }
        .st-key-page-close-top button {
          width:2.65rem !important;height:2.65rem !important;min-height:2.65rem !important;
          padding:0 !important;border-radius:50% !important;font-size:1.15rem !important;
          background:#fff !important;color:#e53935 !important;border:2px solid #111 !important;
          box-shadow:0 2px 10px rgba(0,0,0,.14);font-weight:900 !important;
        }
        .st-key-page-close-top button * {color:#e53935 !important;}
        @media (max-width:768px) and (orientation:portrait) {
          .st-key-page-close-top {right:.65rem;top:3.65rem;}
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    with st.container(key="page-close-top"):
        if st.button("✕", key=f"page_close_{key}", help="關閉"):
            _close_feature_page()


def render_bottom_home_button(key):
    """Render a small bottom-right close shortcut for long pages."""
    st.markdown(
        """
        <style>
        [class*="st-key-bottom_home_"] button {
          background:#fff !important;color:#e53935 !important;border:2px solid #111 !important;
          font-weight:900 !important;
        }
        [class*="st-key-bottom_home_"] button * {color:#e53935 !important;}
        </style>
        """,
        unsafe_allow_html=True,
    )
    spacer, close_col = st.columns([12, 1])
    if not close_col.button("✕", key=f"bottom_home_{key}", help="關閉", use_container_width=True):
        return False
    _close_feature_page()
    return True
