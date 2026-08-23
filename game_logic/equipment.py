"""Pure equipment helpers and character-stat calculation."""

import re

from game_data.config import (
    AFFIX_NAMES,
    CHAPTER_FIXED_INCREMENTS,
    CHAPTERS,
    FIXED_STATS,
    SLOT_ICONS,
)


def fixed_value_for(chapter_id, slot, stars):
    """Return the fixed stat and value for an item chapter, slot and rarity."""
    fixed_stat, base_values = FIXED_STATS[slot]
    chapter_steps = max(0, int(chapter_id) - 1)
    if stars == 4:
        chapter_three_star = base_values[3] + CHAPTER_FIXED_INCREMENTS[slot] * chapter_steps
        if fixed_stat == "attack_speed":
            value = chapter_three_star + 0.10
        elif fixed_stat in ("boss_hp_reduction", "first_hit_percent"):
            value = chapter_three_star + 0.03
        else:
            value = chapter_three_star + 3
    else:
        value = base_values[stars] + CHAPTER_FIXED_INCREMENTS[slot] * chapter_steps
    return fixed_stat, (round(value) if fixed_stat in ("hp", "attack", "defense") else round(value, 3))


def four_star_item_name(chapter_id, base_name):
    """Prefix a four-star item name with its acquisition chapter exactly once."""
    chapter_id = str(chapter_id)
    prefix = f"{CHAPTERS[chapter_id]['number']}・"
    clean_name = re.sub(r"^第[一二三四五六七八九十百0-9]+章・", "", str(base_name))
    return f"{prefix}{clean_name}"


def item_chapter_id(item):
    """Read the chapter from either the modern chapter field or a legacy unit."""
    if item.get("chapter"):
        return str(item["chapter"])
    unit = str(item.get("unit", ""))
    achievement_match = re.match(r"chapter-(\d+)", unit)
    if achievement_match:
        return achievement_match.group(1)
    return unit.split("-")[0] if unit and unit[0].isdigit() else None


def fixed_text(item):
    names = {
        "hp": "HP", "attack": "攻擊力", "defense": "防禦力",
        "attack_speed": "攻擊速度", "boss_hp_reduction": "菁英BOSS初始血量降低",
        "first_hit_percent": "第一擊額外扣除菁英BOSS血量",
    }
    value = item["fixed_value"]
    if item["fixed_stat"] in ("boss_hp_reduction", "first_hit_percent"):
        value_text = f"{value:.0%}"
    elif item["fixed_stat"] == "attack_speed":
        value_text = f"{value:.2f}/秒"
    else:
        value_text = f"{value:g}"
    return f"{names[item['fixed_stat']]} +{value_text}"


def item_text(item):
    chapter_id = item.get("chapter")
    if not chapter_id and re.match(r"^[1-9]-", str(item.get("unit", ""))):
        chapter_id = str(item["unit"]).split("-")[0]
    chapter_label = f"{CHAPTERS[chapter_id]['number']}・" if chapter_id in CHAPTERS else ""
    display_name = str(item["name"])
    if chapter_label and not display_name.startswith(chapter_label):
        display_name = f"{chapter_label}{display_name}"
    return f"{SLOT_ICONS[item['slot']]} {display_name} {'⭐' * item['stars']}｜固定：{fixed_text(item)}｜詞條：{AFFIX_NAMES[item['affix_stat']]} +{item['affix_value']:.0%}"


def equipped_items(profile):
    items = []
    inventory = profile["inventory"]
    for uid in profile["equipment"].values():
        item = next((entry for entry in inventory if entry["uid"] == uid), None) if uid else None
        if item:
            items.append(item)
    return items


def player_stats(profile):
    # Import locally to keep the equipment module usable during old-save migration.
    from game_logic.pets import equipped_pet

    level_factor = 1 + 0.10 * (profile["level"] - 1)
    base = {"hp": 100 * level_factor, "attack": 20 * level_factor, "defense": 10 * level_factor, "attack_speed": 1.0}
    flat = {"hp": 0.0, "attack": 0.0, "defense": 0.0, "attack_speed": 0.0}
    pct = {"hp_pct": 0.0, "attack_pct": 0.0, "defense_pct": 0.0, "speed_pct": 0.0}
    combat = {
        "boss_damage_pct": 0.0, "damage_reduction_pct": 0.0,
        "critical_rate": 0.0, "critical_damage": 0.0,
        "shield_pct": 0.0, "boss_attack_slow_pct": 0.0,
    }
    boss_reduction = 0.0
    first_hit = 0.0
    for item in equipped_items(profile):
        if item["fixed_stat"] in flat:
            flat[item["fixed_stat"]] += item["fixed_value"]
        elif item["fixed_stat"] == "boss_hp_reduction":
            boss_reduction += item["fixed_value"]
        elif item["fixed_stat"] == "first_hit_percent":
            first_hit += item["fixed_value"]
        if item["affix_stat"] in pct:
            pct[item["affix_stat"]] += item["affix_value"]
        elif item["affix_stat"] in combat:
            combat[item["affix_stat"]] += item["affix_value"]
    final_stats = {
        "hp": (base["hp"] + flat["hp"]) * (1 + pct["hp_pct"]),
        "attack": (base["attack"] + flat["attack"]) * (1 + pct["attack_pct"]),
        "defense": (base["defense"] + flat["defense"]) * (1 + pct["defense_pct"]),
        "attack_speed": (base["attack_speed"] + flat["attack_speed"]) * (1 + pct["speed_pct"]),
        "boss_hp_reduction": min(boss_reduction, 0.50),
        "first_hit_percent": min(first_hit, 0.50),
        "boss_damage_pct": min(combat["boss_damage_pct"], 1.00),
        "damage_reduction_pct": min(combat["damage_reduction_pct"], 0.40),
        "critical_rate": min(combat["critical_rate"], 0.50),
        "critical_damage": min(combat["critical_damage"], 1.00),
        "shield_pct": min(combat["shield_pct"], 0.50),
        "boss_attack_slow_pct": min(combat["boss_attack_slow_pct"], 0.40),
    }
    pet = equipped_pet(profile)
    if pet:
        pet_bonuses = pet.get("unlocked_bonuses", {})
        final_stats["hp"] *= 1 + float(pet_bonuses.get("hp_pct", 0.0))
        final_stats["attack"] *= 1 + float(pet_bonuses.get("attack_pct", 0.0))
        final_stats["defense"] *= 1 + float(pet_bonuses.get("defense_pct", 0.0))
        final_stats["attack_speed"] += float(
            pet_bonuses.get("attack_speed_flat", 0.0)
        )
    final_stats["attack_element"] = pet["element"] if pet else None
    final_stats["attack_element_name"] = pet["element_name"] if pet else None
    final_stats["attack_element_color"] = pet["element_color"] if pet else None
    final_stats["equipment_drop_bonus_pct"] = pet["drop_bonus_pct"] if pet else 0.0
    final_stats["pet_level_bonuses"] = pet.get("unlocked_bonuses", {}) if pet else {}
    final_stats["breakdown"] = {"base": base, "flat": flat, "pct": pct}
    return final_stats
