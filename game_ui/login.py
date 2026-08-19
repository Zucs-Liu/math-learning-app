"""Login artwork, responsive background styling, and avatar image helpers."""

import base64
import io
from pathlib import Path

import streamlit as st
from PIL import Image


APP_ROOT = Path(__file__).resolve().parent.parent


def avatar_from_upload(uploaded_file):
    if uploaded_file.size > 2 * 1024 * 1024:
        raise ValueError("圖片不可超過2MB。")
    image = Image.open(uploaded_file)
    image.thumbnail((256, 256))
    if image.mode not in ("RGB", "RGBA"):
        image = image.convert("RGBA")
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(output.getvalue()).decode("ascii")


def built_in_avatar_data(index):
    image_path = APP_ROOT / "assets" / "avatars" / f"avatar-{index:02d}.webp"
    if not image_path.exists():
        return None
    return "data:image/webp;base64," + base64.b64encode(image_path.read_bytes()).decode("ascii")


def _login_background_data_uri(filename, modified_ns):
    """modified_ns is part of the cache key so replaced artwork reloads immediately."""
    image_path = APP_ROOT / "assets" / "login" / filename
    if not image_path.exists():
        return ""
    return "data:image/webp;base64," + base64.b64encode(image_path.read_bytes()).decode("ascii")


def login_background_data_uri(animated=True):
    filename = "heroes-vs-demon-animated-v2.webp" if animated else "heroes-vs-demon-v2.webp"
    image_path = APP_ROOT / "assets" / "login" / filename
    if not image_path.exists():
        return ""
    return _login_background_data_uri(filename, image_path.stat().st_mtime_ns)


def login_landscape_background_data_uri():
    filename = "heroes-vs-demon-landscape-animated-v4.webp"
    image_path = APP_ROOT / "assets" / "login" / filename
    if not image_path.exists():
        return ""
    return _login_background_data_uri(filename, image_path.stat().st_mtime_ns)


def login_landscape_static_background_data_uri():
    filename = "heroes-vs-demon-landscape-v4.webp"
    image_path = APP_ROOT / "assets" / "login" / filename
    if not image_path.exists():
        return ""
    return _login_background_data_uri(filename, image_path.stat().st_mtime_ns)


def _login_background_video_data_uri(filename, modified_ns):
    """Cache the MP4 data URI; modified_ns refreshes it when the file is replaced."""
    video_path = APP_ROOT / "assets" / "login" / filename
    if not video_path.exists():
        return ""
    return "data:video/mp4;base64," + base64.b64encode(video_path.read_bytes()).decode("ascii")


def login_background_video_data_uri():
    filename = "heroes-vs-demon-idle.mp4"
    video_path = APP_ROOT / "assets" / "login" / filename
    if not video_path.exists():
        return ""
    return _login_background_video_data_uri(filename, video_path.stat().st_mtime_ns)


def apply_login_background():
    static_background = login_background_data_uri(animated=False)
    landscape_background = login_landscape_background_data_uri()
    landscape_static_background = login_landscape_static_background_data_uri()
    video_background = login_background_video_data_uri()
    background = static_background or login_background_data_uri(animated=True)
    if not background and not video_background:
        return
    video_html = ""
    if video_background:
        video_html = f"""
        <video class="login-video-background" autoplay muted loop playsinline preload="auto"
               poster="{background}" aria-hidden="true">
            <source src="{video_background}" type="video/mp4">
        </video>
        """
    st.markdown(
        f"""
        {video_html}
        <div class="login-landscape-background" aria-hidden="true"></div>
        <style>
        .stApp {{
            background: #090a18;
            isolation: isolate;
        }}
        .login-video-background {{
            position: fixed;
            inset: 0;
            width: 100vw;
            height: 100vh;
            z-index: 0;
            pointer-events: none;
            object-fit: contain;
            object-position: center top;
            background: #090a18;
        }}
        .login-landscape-background {{
            display: none;
            position: fixed;
            inset: 0;
            width: 100vw;
            height: 100vh;
            z-index: 0;
            pointer-events: none;
            background: #090a18 url('{landscape_background or landscape_static_background or static_background or background}') center center / cover no-repeat;
        }}
        .stApp::before {{
            content: "";
            position: fixed;
            inset: 0;
            z-index: 1;
            pointer-events: none;
            background:
                linear-gradient(rgba(7, 10, 25, .10), rgba(7, 10, 25, .24));
        }}
        .stApp > header,
        .stApp [data-testid="stAppViewContainer"],
        .stApp [data-testid="stMain"] {{
            position: relative;
            z-index: 2;
            background: transparent !important;
        }}
        .stMainBlockContainer, [data-testid="stMainBlockContainer"] {{
            width: min(560px, calc(100% - 32px));
            max-width: 560px;
            margin: 92px auto 30px !important;
            padding: 1rem 1.25rem 2rem !important;
            border: 0 !important;
            border-radius: 0 !important;
            background: transparent !important;
            box-shadow: none !important;
        }}
        .stMainBlockContainer h1, [data-testid="stMainBlockContainer"] h1 {{
            position: fixed;
            z-index: 10;
            top: 4.15rem;
            left: .8rem;
            margin: 0 !important;
            padding: .15rem .3rem !important;
            color: white !important;
            text-shadow: 0 3px 12px rgba(0,0,0,.9);
        }}
        [data-testid="stRadio"] > div,
        [data-testid="stCheckbox"],
        [data-testid="stTextInput"] input,
        [data-testid="stButton"] button {{
            border-radius: 14px !important;
        }}
        [data-testid="stRadio"] > div,
        [data-testid="stCheckbox"] {{
            width: fit-content;
            padding: .45rem .8rem;
            background: rgba(255,255,255,.88);
            border: 1px solid rgba(255,255,255,.78);
            box-shadow: 0 5px 18px rgba(0,0,0,.18);
            color: #171717 !important;
        }}
        [data-testid="stRadio"] > div label,
        [data-testid="stRadio"] > div label p,
        [data-testid="stRadio"] > div label span,
        [data-testid="stCheckbox"] label,
        [data-testid="stCheckbox"] label p,
        [data-testid="stCheckbox"] label span,
        [data-testid="stTabs"] [role="tab"] {{
            color: #171717 !important;
        }}
        [data-testid="stRadio"] > div label:has(input:checked),
        [data-testid="stCheckbox"] label:has(input:checked),
        [data-testid="stTabs"] [role="tab"][aria-selected="true"] {{
            color: #ff4b4b !important;
        }}
        [data-testid="stRadio"] {{
            width: fit-content !important;
            margin-left: 0 !important;
            margin-right: auto !important;
        }}
        [data-testid="stCheckbox"] {{
            width: fit-content !important;
            margin-left: auto !important;
            margin-right: auto !important;
        }}
        div[data-testid="stElementContainer"]:has(> [data-testid="stCheckbox"]),
        div[data-testid="stElementContainer"]:has([data-testid="stCheckbox"]) {{
            width: fit-content !important;
            max-width: max-content !important;
            margin-left: auto !important;
            margin-right: auto !important;
        }}
        [data-testid="stRadio"] > label {{
            width: 100%;
            text-align: left;
            justify-content: flex-start;
        }}
        [data-testid="stTextInput"] {{
            width: min(320px, 100%) !important;
            margin-left: auto !important;
            margin-right: auto !important;
        }}
        [data-testid="stTextInput"] input,
        [data-testid="stTextInput"] input::placeholder {{
            color: #171717 !important;
            opacity: 1 !important;
            -webkit-text-fill-color: #171717 !important;
        }}
        [data-testid="stTextInput"] label,
        [data-testid="stRadio"] label,
        [data-testid="stCheckbox"] label,
        [data-testid="stTabs"] button {{
            font-weight: 700 !important;
        }}
        [data-testid="stTextInput"] > label,
        [data-testid="stRadio"] > label {{
            color: white !important;
            text-shadow: 0 2px 7px rgba(0,0,0,.95);
        }}
        [data-testid="stTabs"] [role="tablist"] {{
            width: min(320px, 100%);
            margin-left: auto;
            margin-right: auto;
            padding: .18rem .45rem;
            border-radius: 14px;
            background: rgba(255,255,255,.88);
            box-shadow: 0 5px 18px rgba(0,0,0,.18);
        }}
        [data-testid="stTabs"] [role="tab"] {{
            flex: 1 1 50%;
            justify-content: center;
        }}
        .st-key-login_fields_row [data-testid="stHorizontalBlock"],
        .st-key-login_actions_row [data-testid="stHorizontalBlock"] {{
            display: flex !important;
            flex-direction: row !important;
            flex-wrap: nowrap !important;
            gap: .55rem !important;
            align-items: end !important;
        }}
        .st-key-login_fields_row [data-testid="stColumn"],
        .st-key-login_actions_row [data-testid="stColumn"] {{
            min-width: 0 !important;
            width: 50% !important;
            flex: 1 1 50% !important;
        }}
        .st-key-login_fields_row [data-testid="stTextInput"] {{
            width: 100% !important;
        }}
        .st-key-login_actions_row [data-testid="stCheckbox"],
        .st-key-login_actions_row [data-testid="stButton"] {{
            margin-left: auto !important;
            margin-right: auto !important;
        }}
        [data-testid="stButton"] {{
            width: fit-content !important;
            margin-left: auto !important;
            margin-right: auto !important;
        }}
        [data-testid="stButton"] button {{
            width: auto !important;
            min-width: max-content !important;
            padding-left: 1.2rem !important;
            padding-right: 1.2rem !important;
        }}
        @media (max-width: 600px) {{
            .stApp::before {{
                background: linear-gradient(rgba(7,10,25,.08), rgba(7,10,25,.24));
            }}
            .login-video-background {{
                object-fit: cover;
                object-position: center top;
            }}
            .stMainBlockContainer, [data-testid="stMainBlockContainer"] {{
                width: min(88vw, 430px);
                margin: 58px auto 24px !important;
                padding: .5rem 0 1.25rem !important;
            }}
            .stMainBlockContainer h1, [data-testid="stMainBlockContainer"] h1 {{
                font-size: 2rem !important;
                top: 4.05rem;
                left: .35rem;
            }}
            [data-testid="stRadio"], [data-testid="stTabs"],
            [data-testid="stCheckbox"] {{
                max-width: 390px;
                margin-left: auto;
                margin-right: auto;
            }}
            [data-testid="stCheckbox"] {{
                max-width: max-content;
                padding: .38rem .7rem;
            }}
            [data-testid="stTextInput"] {{
                width: min(125px, 42vw) !important;
            }}
            [data-testid="stTabs"] [role="tablist"] {{
                width: min(250px, 76vw);
            }}
            [data-testid="stTextInput"] input {{
                background: rgba(255,255,255,.90) !important;
                border: 1px solid rgba(255,255,255,.82) !important;
                box-shadow: 0 5px 18px rgba(0,0,0,.20);
            }}
        }}
        @media (orientation: landscape) {{
            .login-video-background {{
                display: none !important;
            }}
            .login-landscape-background {{
                display: block !important;
                inset: 3.6rem 0 0 !important;
                height: calc(100vh - 3.6rem) !important;
                background-position: center top !important;
            }}
            .stMainBlockContainer, [data-testid="stMainBlockContainer"] {{
                width: min(340px, 42vw);
                max-width: 340px;
                margin: 104px auto 24px 4vw !important;
                padding: .75rem 1rem 1.25rem !important;
            }}
            .stMainBlockContainer h1, [data-testid="stMainBlockContainer"] h1 {{
                top: 4.75rem;
                left: 1.1rem;
                font-size: 2.35rem !important;
            }}
            .stApp::before {{
                background: linear-gradient(90deg, rgba(7,10,25,.32) 0%, rgba(7,10,25,.14) 48%, rgba(7,10,25,.04) 100%);
            }}
            [data-testid="stRadio"],
            [data-testid="stTabs"],
            [data-testid="stTextInput"],
            [data-testid="stCheckbox"],
            [data-testid="stButton"] {{
                margin-left: 0 !important;
                margin-right: auto !important;
            }}
            [data-testid="stTabs"] [role="tablist"] {{
                width: 280px !important;
                min-width: 0 !important;
                max-width: 100% !important;
                margin-left: 0 !important;
                margin-right: auto !important;
            }}
            [data-testid="stTabs"] [role="tab"] {{
                flex: 0 0 auto !important;
                padding-left: 1rem !important;
                padding-right: 1rem !important;
            }}
            [data-testid="stTextInput"] {{
                width: min(280px, 100%) !important;
            }}
            .st-key-login_fields_row [data-testid="stTextInput"] {{
                width: min(280px, 100%) !important;
            }}
            .st-key-login_fields_row [data-testid="stHorizontalBlock"],
            .st-key-login_actions_row [data-testid="stHorizontalBlock"] {{
                display: flex !important;
                flex-direction: column !important;
                flex-wrap: nowrap !important;
                gap: .35rem !important;
                align-items: flex-start !important;
            }}
            .st-key-login_fields_row [data-testid="stColumn"],
            .st-key-login_actions_row [data-testid="stColumn"] {{
                min-width: 0 !important;
                width: 100% !important;
                max-width: 100% !important;
                flex: 0 0 auto !important;
            }}
            .st-key-login_actions_row {{
                width: min(280px, 100%) !important;
                max-width: 280px !important;
            }}
            .st-key-login_actions_row [data-testid="stHorizontalBlock"] {{
                flex-direction: row !important;
                align-items: center !important;
                gap: .35rem !important;
            }}
            .st-key-login_actions_row [data-testid="stColumn"]:first-child {{
                width: 58% !important;
                max-width: 58% !important;
                flex: 0 0 58% !important;
            }}
            .st-key-login_actions_row [data-testid="stColumn"]:last-child {{
                width: 42% !important;
                max-width: 42% !important;
                flex: 0 0 42% !important;
            }}
            .st-key-login_actions_row [data-testid="stCheckbox"],
            .st-key-login_actions_row [data-testid="stButton"] {{
                margin-left: 0 !important;
                margin-right: auto !important;
            }}
        }}
        @media (prefers-reduced-motion: reduce) {{
            .login-video-background {{
                display: none;
            }}
            .login-landscape-background {{
                background-image: url('{landscape_static_background or landscape_background}') !important;
            }}
            .stApp::before {{
                background:
                    linear-gradient(rgba(7,10,25,.10), rgba(7,10,25,.26)),
                    url('{static_background or background}') center top / contain no-repeat,
                    #090a18 !important;
            }}
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_compact_avatar_editor(profile, save_profile):
    """Render the home-screen avatar editor and persist changes via callback."""
    with st.container(key="home_avatar_summary"):
        avatar_col, gender_col, notice_col = st.columns(
            [1.2, 2.2, 2], vertical_alignment="top"
        )
    if profile.get("avatar_data"):
        avatar_col.image(profile["avatar_data"], width=96)
    else:
        avatar_col.markdown("## 🧙")
    if avatar_col.button(
        "點擊頭像更換", key="toggle_avatar_editor", use_container_width=True
    ):
        st.session_state.show_avatar_editor = not st.session_state.get(
            "show_avatar_editor", False
        )
        st.rerun()

    if profile.get("gender") in {"male", "female"}:
        gender_col.write(
            f"**角色性別：{'男性' if profile['gender'] == 'male' else '女性'}**"
        )
    else:
        gender_col.warning("性別只能設定一次，並會影響後續 BOSS 戰鬥中的勇者圖片。")
        selected_gender = gender_col.radio(
            "選擇角色性別",
            ["male", "female"],
            horizontal=True,
            format_func=lambda value: "男性" if value == "male" else "女性",
            key="one_time_gender",
        )
        if gender_col.button(
            "確認性別（設定後不能更改）", type="primary", use_container_width=True
        ):
            profile["gender"] = selected_gender
            save_profile(profile)
            st.rerun()

    if notice_col.button(
        "📢 公告事項", key="open_announcements", type="primary", use_container_width=True
    ):
        st.session_state.scroll_announcements_to_top = True
        st.session_state.screen = "announcements"
        st.rerun()

    if not st.session_state.get("show_avatar_editor", False):
        return
    st.divider()
    editor_header, editor_close = st.columns([5, 1], vertical_alignment="center")
    editor_header.markdown("#### 更換大頭貼")
    if editor_close.button(
        "關閉", key="close_avatar_editor", use_container_width=True
    ):
        st.session_state.show_avatar_editor = False
        st.rerun()
    avatar_source = st.radio(
        "選擇更換方式",
        ["內建Q版大頭貼", "自行上傳大頭貼"],
        horizontal=True,
        key="avatar_source",
    )
    if avatar_source == "自行上傳大頭貼":
        uploaded = st.file_uploader(
            "選擇圖片",
            type=["png", "jpg", "jpeg", "webp"],
            key="compact_avatar_upload",
            help="圖片上限2MB，會自動縮小；只顯示於角色與排行榜。",
        )
        if uploaded and st.button(
            "儲存大頭貼", type="primary", use_container_width=True
        ):
            try:
                profile["avatar_data"] = avatar_from_upload(uploaded)
                save_profile(profile)
                st.session_state.show_avatar_editor = False
                st.session_state.scroll_home_after_avatar = True
                st.rerun()
            except Exception as error:
                st.error(f"無法處理圖片：{error}")
        return

    st.caption("選擇一張內建Q版大頭貼；選定後會自動收起選單並回到人物區。")
    st.markdown(
        """
        <style>
        @media (max-width:768px) and (orientation:portrait) {
          [class*="st-key-compact_avatar_row_"] [data-testid="stHorizontalBlock"] {display:flex !important;flex-direction:row !important;flex-wrap:nowrap !important;gap:.18rem !important;width:100% !important;}
          [class*="st-key-compact_avatar_row_"] [data-testid="stColumn"] {min-width:0 !important;width:calc(25% - .14rem) !important;max-width:calc(25% - .14rem) !important;flex:0 0 calc(25% - .14rem) !important;padding:0 !important;}
          [class*="st-key-compact_avatar_row_"] [data-testid="stImage"] img {width:100% !important;height:auto !important;border-radius:8px !important;}
          [class*="st-key-compact_avatar_row_"] button {min-height:1.9rem !important;padding:.15rem .05rem !important;font-size:.72rem !important;}
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    for row_number, row_start in enumerate(range(1, 21, 4), 1):
        with st.container(key=f"compact_avatar_row_{row_number}"):
            columns = st.columns(4, gap="small")
            for column, index in zip(columns, range(row_start, row_start + 4)):
                avatar_data = built_in_avatar_data(index)
                if avatar_data:
                    column.image(avatar_data, use_container_width=True)
                if column.button(
                    "使用", key=f"compact_avatar_{index}", use_container_width=True
                ):
                    profile["avatar_data"] = avatar_data
                    save_profile(profile)
                    st.session_state.show_avatar_editor = False
                    st.session_state.scroll_home_after_avatar = True
                    st.rerun()
