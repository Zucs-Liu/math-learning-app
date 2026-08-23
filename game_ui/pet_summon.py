"""Pet summon screen, rate disclosure, catalog preview, and result display."""

from pathlib import Path

import streamlit as st

from game_logic.pets import (
    PET_FREE_SUMMONS_PER_DAY,
    PET_PAID_SUMMONS_PER_DAY,
    PET_SUMMON_COIN_COST,
    pet_asset_path,
    pet_catalog,
    summon_pet,
    sync_pet_summon_period,
)


ELEMENT_ORDER = ("light", "dark", "wood", "earth", "water", "fire")


def _render_summon_styles():
    """Keep the supplied compact layout on portrait phones without changing landscape."""
    st.markdown(
        """
        <style>
        @media (max-width:768px) and (orientation:portrait) {
          .st-key-pet_summon_top_actions [data-testid="stHorizontalBlock"] {
            display:flex !important;flex-direction:row !important;flex-wrap:nowrap !important;
            justify-content:center !important;gap:.35rem !important;
          }
          .st-key-pet_summon_top_actions [data-testid="stColumn"]:first-child,
          .st-key-pet_summon_top_actions [data-testid="stColumn"]:last-child {
            display:none !important;
          }
          .st-key-pet_summon_top_actions [data-testid="stColumn"]:nth-child(2),
          .st-key-pet_summon_top_actions [data-testid="stColumn"]:nth-child(3) {
            min-width:0 !important;width:42% !important;max-width:42% !important;
            flex:0 0 42% !important;
          }
          .st-key-pet_summon_top_actions button {min-height:2.35rem !important;padding:.25rem !important;}

          .st-key-pet_summon_collection [data-testid="stHorizontalBlock"] {
            display:flex !important;flex-direction:row !important;justify-content:center !important;
            gap:0 !important;
          }
          .st-key-pet_summon_collection [data-testid="stColumn"]:first-child,
          .st-key-pet_summon_collection [data-testid="stColumn"]:last-child {display:none !important;}
          .st-key-pet_summon_collection [data-testid="stColumn"]:nth-child(2) {
            min-width:0 !important;width:72% !important;max-width:72% !important;flex:0 0 72% !important;
          }
          .st-key-pet_summon_collection [data-testid="stImage"] img {
            display:block !important;width:100% !important;height:auto !important;
            max-height:45vh !important;object-fit:contain !important;margin:auto !important;
          }

          .st-key-pet_summon_actions [data-testid="stHorizontalBlock"] {
            display:flex !important;flex-direction:row !important;flex-wrap:nowrap !important;
            gap:.4rem !important;
          }
          .st-key-pet_summon_actions [data-testid="stColumn"] {
            min-width:0 !important;width:50% !important;max-width:50% !important;flex:0 0 calc(50% - .2rem) !important;
          }
          .st-key-pet_summon_actions button {padding:.35rem .1rem !important;white-space:normal !important;}

          .st-key-summon_content_gallery [data-testid="stHorizontalBlock"] {
            display:flex !important;flex-direction:row !important;flex-wrap:nowrap !important;
            align-items:center !important;gap:.22rem !important;
          }
          .st-key-summon_content_gallery [data-testid="stColumn"]:first-child,
          .st-key-summon_content_gallery [data-testid="stColumn"]:last-child {
            min-width:0 !important;width:11% !important;max-width:11% !important;flex:0 0 11% !important;
          }
          .st-key-summon_content_gallery [data-testid="stColumn"]:nth-child(2) {
            min-width:0 !important;width:78% !important;max-width:78% !important;flex:0 0 78% !important;
          }
          .st-key-summon_content_gallery [data-testid="stImage"] img {
            display:block !important;width:100% !important;height:auto !important;
            max-height:36vh !important;object-fit:contain !important;margin:auto !important;
          }
          .st-key-summon_content_gallery button {padding:.18rem !important;min-height:2.25rem !important;}
          .summon-pet-name {font-size:1.25rem !important;margin:.15rem 0 !important;}
          .summon-affixes {font-size:.88rem !important;line-height:1.25 !important;margin:.15rem 0 !important;}
          .summon-affixes > div {padding:.12rem .2rem !important;border-bottom:1px solid #e5e7eb;}
        }
        .st-key-pet_summon_collection [data-testid="stImage"] {
          display:flex !important;justify-content:center !important;width:100% !important;
        }
        .st-key-pet_summon_collection [data-testid="stImage"] img {
          display:block !important;width:min(62%,28rem) !important;height:auto !important;
          object-fit:contain !important;margin-inline:auto !important;
        }
        .st-key-summon_content_gallery [data-testid="stColumn"]:nth-child(2) [data-testid="stImage"] {
          display:flex !important;justify-content:center !important;
        }
        .st-key-summon_content_gallery [data-testid="stColumn"]:nth-child(2) [data-testid="stImage"] img {
          display:block !important;margin-inline:auto !important;object-fit:contain !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _special_affixes(pet, elements):
    element = elements[pet["element"]]
    strong = elements[element["strong_against"]]["name"]
    return [
        f"跟隨時，勇者攻擊轉為{element['name']}屬性。",
        f"對{strong}屬性 BOSS 傷害增加 15%。",
        "每個單元增加 10% 額外掉落裝備機率。",
    ]


def _available_pet_ids():
    # 2026/09/15 活動結束後，心機狐退出目前的召喚池；既有寵物不受影響。
    from datetime import date

    ids = list(pet_catalog()[0])
    if date.today() > date(2026, 9, 15):
        ids = [pet_id for pet_id in ids if pet_id != "cunning_fox"]
    return ids


def _render_rates():
    st.markdown("### 召喚機率")
    available = _available_pet_ids()
    rate = 100 / len(available) if available else 0
    catalog, elements = pet_catalog()
    for pet_id in available:
        pet = catalog[pet_id]
        st.write(f"**{pet['name']}｜{elements[pet['element']]['name']}屬性：{rate:.2f}%**")
    st.caption("每次召喚皆獨立計算；目前召喚池內每隻寵物機率相同。")


def _render_contents():
    catalog, elements = pet_catalog()
    available = _available_pet_ids()
    index = int(st.session_state.get("summon_catalog_index", 0)) % max(1, len(available))
    st.session_state.summon_catalog_index = index
    pet_id = available[index]
    pet = catalog[pet_id]

    element = elements[pet["element"]]
    with st.container(key="summon_content_gallery"):
        previous_col, image_col, next_col = st.columns([1, 6, 1], vertical_alignment="center")
        if previous_col.button("←", key="summon_content_previous", use_container_width=True):
            st.session_state.summon_catalog_index = (index - 1) % len(available)
            st.rerun()
        image_col.image(pet_asset_path(pet, "mythic"), use_container_width=True)
        if next_col.button("→", key="summon_content_next", use_container_width=True):
            st.session_state.summon_catalog_index = (index + 1) % len(available)
            st.rerun()
        affix_html = "".join(
            f"<div>• {line}</div>" for line in _special_affixes(pet, elements)
        )
        st.markdown(
            f"""
            <div style="text-align:center;">
              <div class="summon-pet-name" style="color:{element['color']};font-weight:900;">
                {pet['name']}｜{element['name']}屬性
              </div>
              <div class="summon-affixes" style="text-align:left;">
                <strong>特殊詞條</strong>{affix_html}
              </div>
              <div style="font-size:.82rem;color:#6b7280;">{index + 1} / {len(available)}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def _render_result(result):
    pet = result["pet"]
    if result["is_new"]:
        result_text = "首次獲得"
    else:
        catalog, elements = pet_catalog()
        element_name = elements[result["soul_element"]]["name"]
        result_text = (
            f"已擁有，自動轉化為{element_name}屬性元神 ×1"
            f"（目前 ×{result['soul_count']}）"
        )
    st.success(f"召喚成功：{pet['display_name']}｜{result_text}")
    result_col, text_col = st.columns([2, 3], vertical_alignment="center")
    result_col.image(pet_asset_path(pet, "chibi"), use_container_width=True)
    text_col.markdown(
        f"### {pet['display_name']}\n"
        f"**{pet['element_name']}屬性｜{'★' * int(pet['stars'])}{'☆' * (3 - int(pet['stars']))}**"
    )
    if result.get("payment") == "coins":
        st.info(f"本次使用 {PET_SUMMON_COIN_COST} 金幣；剩餘金幣：{result['coins_remaining']}")


def render_pet_summon_screen(profile, save_profile, daily_period):
    """Render the complete summon feature inside one independent page."""
    if sync_pet_summon_period(profile, daily_period):
        save_profile(profile)

    _render_summon_styles()
    st.markdown("<h2 style='text-align:center;margin:.15rem 0 .35rem;'>召喚系統</h2>", unsafe_allow_html=True)
    with st.container(key="pet_summon_top_actions"):
        mode_cols = st.columns([1.2, 1, 1, 1.2])
    if mode_cols[1].button("召喚機率", key="open_summon_rates", use_container_width=True):
        st.session_state.pet_summon_view = "rates"
        st.rerun()
    if mode_cols[2].button("召喚內容", key="open_summon_contents", use_container_width=True):
        st.session_state.pet_summon_view = "contents"
        st.rerun()

    view = st.session_state.get("pet_summon_view", "main")
    if view != "main":
        if st.button("← 返回召喚", key="return_summon_main"):
            st.session_state.pet_summon_view = "main"
            st.rerun()
        if view == "rates":
            _render_rates()
        else:
            _render_contents()
        return

    st.markdown(
        """
        <div style="text-align:center;margin:.45rem 0 .7rem;">
          <div style="color:#d71920;font-size:1.55rem;font-weight:900;">限時召喚！！</div>
          <div style="color:#d71920;font-size:1.08rem;font-weight:800;">
            即日起到9/15，「心機狐」將再也抽不中！
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    image_path = Path(__file__).resolve().parent.parent / "assets" / "pets" / "pet-summon-collection.png"
    with st.container(key="pet_summon_collection"):
        st.image(image_path, use_container_width=True)

    free_used = int(profile.get("pet_free_summons_used", 0))
    paid_used = int(profile.get("pet_paid_summons_used", 0))
    free_remaining = max(0, PET_FREE_SUMMONS_PER_DAY - free_used)
    paid_remaining = max(0, PET_PAID_SUMMONS_PER_DAY - paid_used)
    ticket_count = int(profile.get("summon_tickets", 0))
    coins = int(profile.get("coins", 0))
    payment_note = (
        f"召喚券 ×{ticket_count}（優先消耗召喚券）"
        if ticket_count > 0
        else (
            f"無召喚券，將使用 {PET_SUMMON_COIN_COST} 金幣；"
            f"目前 {coins}，召喚後剩餘 {max(0, coins - PET_SUMMON_COIN_COST)}"
            if coins >= PET_SUMMON_COIN_COST
            else f"無召喚券；目前 {coins} 金幣，尚缺 {PET_SUMMON_COIN_COST - coins} 金幣"
        )
    )

    with st.container(key="pet_summon_actions"):
        action_cols = st.columns(2)
        free_pressed = action_cols[0].button(
            f"免費召喚 {free_remaining}/1",
            key="free_pet_summon",
            type="primary",
            disabled=free_remaining <= 0,
            use_container_width=True,
        )
        paid_pressed = action_cols[1].button(
            f"道具召喚 {paid_remaining}/10",
            key="paid_pet_summon",
            type="primary",
            disabled=paid_remaining <= 0,
            help=payment_note,
            use_container_width=True,
        )
    st.caption(f"道具召喚：{payment_note}")
    st.markdown("<div style='text-align:center'>刷新時間：每天早上 8 點重置</div>", unsafe_allow_html=True)

    if free_pressed or paid_pressed:
        result = summon_pet(
            profile,
            mode="free" if free_pressed else "paid",
            available_pet_ids=_available_pet_ids(),
        )
        if result["ok"]:
            save_profile(profile)
            st.session_state.pet_summon_result = result
            st.rerun()
        st.error(result["reason"])

    if st.session_state.get("pet_summon_result"):
        _render_result(st.session_state.pet_summon_result)
        if st.button("關閉召喚結果", key="close_pet_summon_result", use_container_width=True):
            st.session_state.pet_summon_result = None
            st.rerun()
