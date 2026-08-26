"""Character statistics and equipment comparison presentation."""

import json

import streamlit as st

from game_data.config import SLOT_ICONS, SLOT_NAMES
from game_logic.equipment import item_text, player_stats
from game_logic.loot import find_inventory_item as find_item
from game_logic.pets import PET_ELEMENT_DAMAGE_BONUS, element_matchup, pet_catalog


def render_item_comparison(profile, new_item):
    current = find_item(profile, profile["equipment"].get(new_item["slot"]))
    left, right = st.columns(2)
    left.info(f"**準備更換**\n\n{item_text(new_item)}")
    if current:
        right.warning(f"**目前穿戴**\n\n{item_text(current)}")
    else:
        right.success(f"**目前穿戴**\n\n{SLOT_ICONS[new_item['slot']]} {SLOT_NAMES[new_item['slot']]}尚未裝備")
    before = player_stats(profile)
    preview = json.loads(json.dumps(profile, ensure_ascii=False))
    preview["equipment"][new_item["slot"]] = new_item["uid"]
    after = player_stats(preview)
    stat_specs = [
        ("HP", "hp", "number"), ("攻擊", "attack", "number"),
        ("防禦", "defense", "number"), ("攻速／秒", "attack_speed", "speed"),
        ("菁英BOSS初始血量降低", "boss_hp_reduction", "percent"),
        ("第一擊額外扣除菁英BOSS血量", "first_hit_percent", "percent"),
        ("對菁英BOSS傷害", "boss_damage_pct", "percent"),
        ("受到傷害降低", "damage_reduction_pct", "percent"),
        ("暴擊率", "critical_rate", "percent"),
        ("暴擊傷害", "critical_damage", "percent"),
        ("開場護盾", "shield_pct", "percent"),
        ("菁英BOSS攻速降低", "boss_attack_slow_pct", "percent"),
    ]

    def display_value(value, kind, signed=False):
        if kind == "percent":
            return f"{value:+.0%}" if signed else f"{value:.0%}"
        digits = 2 if kind == "speed" else 1
        return f"{value:+.{digits}f}" if signed else f"{value:.{digits}f}"

    comparison_rows = []
    for label, key, kind in stat_specs:
        difference = after[key] - before[key]
        if abs(difference) < 1e-9:
            continue
        comparison_rows.append({
            "人物能力": label,
            "目前": display_value(before[key], kind),
            "更換後": display_value(after[key], kind),
            "增減": display_value(difference, kind, signed=True),
        })
    st.write("**能力變動對照**")
    if comparison_rows:
        st.dataframe(comparison_rows, hide_index=True, use_container_width=True)
    else:
        st.caption("更換後人物能力沒有變動。")


def render_stats(profile, show_exp=True, boss_element=None):
    stats = player_stats(profile)
    breakdown = stats["breakdown"]
    base = breakdown["base"]
    flat = breakdown["flat"]
    pct = breakdown["pct"]

    def formula_help(stat_key, pct_key, final_value, unit=""):
        multiplier = 1 + pct[pct_key]
        return (
            f"計算：({base[stat_key]:.2f} + {flat[stat_key]:.2f}) "
            f"× {multiplier:.2f} = {final_value:.2f}{unit}\n\n"
            f"等級基礎值：{base[stat_key]:.2f}{unit}\n\n"
            f"裝備固定值：+{flat[stat_key]:.2f}{unit}\n\n"
            f"附加詞條：+{pct[pct_key]:.0%}"
        )

    cols = st.columns(5)
    cols[0].metric(
        "等級",
        f"Lv{profile['level']}",
        help="每升一級，HP、攻擊力與防禦力的等級基礎值增加10%。",
    )
    cols[1].metric(
        "HP", f"{stats['hp']:.1f}",
        help=formula_help("hp", "hp_pct", stats["hp"]),
    )
    cols[2].metric(
        "攻擊", f"{stats['attack']:.1f}",
        help=formula_help("attack", "attack_pct", stats["attack"]),
    )
    cols[3].metric(
        "防禦", f"{stats['defense']:.1f}",
        help=formula_help("defense", "defense_pct", stats["defense"]),
    )
    cols[4].metric(
        "攻速", f"{stats['attack_speed']:.2f}/秒",
        help=formula_help("attack_speed", "speed_pct", stats["attack_speed"], "/秒"),
    )
    special_effects = [
        ("菁英BOSS初始血量降低", stats["boss_hp_reduction"]),
        ("第一擊額外扣除菁英BOSS血量", stats["first_hit_percent"]),
        ("對菁英BOSS傷害", stats["boss_damage_pct"]),
        ("傷害減免", stats["damage_reduction_pct"]),
        ("暴擊率", stats["critical_rate"]),
        ("暴擊傷害", stats["critical_damage"]),
        ("開場護盾", stats["shield_pct"]),
        ("菁英BOSS攻速降低", stats["boss_attack_slow_pct"]),
    ]
    active_effects = [f"{name} +{value:.0%}" for name, value in special_effects if value]
    if boss_element:
        matchup, _ = element_matchup(stats["attack_element"], boss_element)
        elements = pet_catalog()[1]
        attack_name = stats.get("attack_element_name")
        boss_name = elements.get(boss_element, {}).get("name")
        if matchup == "advantage":
            active_effects.append(
                f"目前{attack_name}屬剋制{boss_name}屬，傷害增加{PET_ELEMENT_DAMAGE_BONUS:.0%}"
            )
        elif matchup == "disadvantage":
            active_effects.append(
                f"目前{attack_name}屬被{boss_name}屬剋制，傷害降低{PET_ELEMENT_DAMAGE_BONUS:.0%}"
            )
        else:
            active_effects.append("目前未剋制")
    if active_effects:
        st.caption("附屬能力：" + "｜".join(active_effects))
    else:
        st.caption("附屬能力：目前無")
    if stats["critical_rate"]:
        critical_every = round(1 / stats["critical_rate"])
        st.caption(f"排行榜採固定暴擊：目前每第 {critical_every} 擊必定暴擊，不使用隨機判定。")
    elif stats["critical_damage"]:
        st.caption("目前暴擊率為0%，因此暴擊傷害詞條暫時不會生效；需要先取得暴擊率。")
    if show_exp:
        if profile["level"] < 20:
            st.progress(profile["exp"] / (profile["level"] * 100))
            st.caption(f"EXP：{profile['exp']} / {profile['level'] * 100}")
        else:
            st.caption("已達最高等級 Lv20")
