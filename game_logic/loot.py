"""Equipment drops, permanent collection records, and four-star rewards."""

import random
import uuid


ACHIEVEMENT_REWARD_SPECS = {
    ("1", "chapter"): {
        "unit": "chapter-1", "slot": "weapon", "name": "整數勇者之劍",
        "fixed_stat": "attack", "affix_stat": "attack_pct",
    },
    ("1", "elite"): {
        "unit": "chapter-1-elite", "slot": "helmet", "name": "收藏家王冠",
        "fixed_stat": "hp", "affix_stat": "defense_pct",
    },
    ("1", "collection"): {
        "unit": "chapter-1-collection", "slot": "necklace", "name": "九星守護項鍊",
        "fixed_stat": "boss_hp_reduction", "affix_stat": "hp_pct",
    },
    ("2", "chapter"): {
        "unit": "chapter-2", "slot": "gloves", "name": "乘除勇者手甲",
        "fixed_stat": "attack", "affix_stat": "attack_pct",
    },
    ("2", "collection"): {
        "unit": "chapter-2-collection", "slot": "boots", "name": "乘除疾風戰靴",
        "fixed_stat": "attack_speed", "affix_stat": "speed_pct",
    },
    ("2", "elite"): {
        "unit": "chapter-2-elite", "slot": "shield", "name": "乘除霸主盾",
        "fixed_stat": "defense", "affix_stat": "hp_pct",
    },
    ("3", "chapter"): {
        "unit": "chapter-3", "slot": "armor", "name": "龍鱗守護鎧",
        "fixed_stat": "defense", "affix_stat": "defense_pct",
    },
    ("3", "collection"): {
        "unit": "chapter-3-collection", "slot": "belt", "name": "龍心腰帶",
        "fixed_stat": "hp", "affix_stat": "hp_pct",
    },
    ("3", "elite"): {
        "unit": "chapter-3-elite", "slot": "ring", "name": "烈焰龍王戒",
        "fixed_stat": "first_hit_percent", "affix_stat": "boss_damage_pct",
    },
    ("4", "chapter"): {
        "unit": "chapter-4", "slot": "helmet", "name": "雷狐靈冠",
        "fixed_stat": "hp", "affix_stat": "hp_pct",
    },
    ("4", "collection"): {
        "unit": "chapter-4-collection", "slot": "boots", "name": "紫電踏雲靴",
        "fixed_stat": "attack_speed", "affix_stat": "speed_pct",
    },
    ("4", "elite"): {
        "unit": "chapter-4-elite", "slot": "weapon", "name": "九尾天雷刃",
        "fixed_stat": "attack", "affix_stat": "critical_rate",
    },
    ("5", "chapter"): {
        "unit": "chapter-5", "slot": "armor", "name": "冰河守護鎧",
        "fixed_stat": "defense", "affix_stat": "defense_pct", "include_chapter": True,
    },
    ("5", "collection"): {
        "unit": "chapter-5-collection", "slot": "necklace", "name": "極寒潮汐項鍊",
        "fixed_stat": "boss_hp_reduction", "affix_stat": "damage_reduction_pct",
        "include_chapter": True,
    },
    ("5", "elite"): {
        "unit": "chapter-5-elite", "slot": "shield", "name": "暴風王盾",
        "fixed_stat": "defense", "affix_stat": "boss_damage_pct", "include_chapter": True,
    },
    ("6", "chapter"): {
        "unit": "chapter-6", "slot": "gloves", "name": "黃金比例手甲",
        "fixed_stat": "attack", "affix_stat": "attack_pct", "include_chapter": True,
    },
    ("6", "collection"): {
        "unit": "chapter-6-collection", "slot": "ring", "name": "等比靈環",
        "fixed_stat": "first_hit_percent", "affix_stat": "critical_rate", "include_chapter": True,
    },
    ("6", "elite"): {
        "unit": "chapter-6-elite", "slot": "weapon", "name": "鬼火王刃",
        "fixed_stat": "attack", "affix_stat": "boss_damage_pct", "include_chapter": True,
    },
}


def item_signature(item):
    return (
        item["unit"], item["slot"], item["stars"],
        item["affix_stat"], item["affix_value"],
    )


def make_random_drop(
    profile,
    unit_id,
    stars,
    units,
    affix_names,
    affix_values,
    gear_names,
    fixed_value_for,
):
    if stars == 0:
        return None
    owned = {
        item_signature(item)
        for item in profile["inventory"]
        if not item.get("achievement")
    }
    unit_slots = units[unit_id]["slots"]
    owned_same_star_slots = {
        item["slot"]
        for item in profile["inventory"]
        if not item.get("achievement")
        and item["unit"] == unit_id
        and item["stars"] == stars
    }
    missing_slots = [slot for slot in unit_slots if slot not in owned_same_star_slots]
    candidate_slots = missing_slots if missing_slots else unit_slots
    combinations = []
    for slot in candidate_slots:
        for affix_stat in affix_names:
            value_pool = affix_values.get(affix_stat, affix_values["default"])
            for affix_value in value_pool[stars]:
                signature = (unit_id, slot, stars, affix_stat, affix_value)
                if signature not in owned:
                    combinations.append((slot, affix_stat, affix_value))
    if not combinations:
        return None
    slot, affix_stat, affix_value = random.choice(combinations)
    chapter_id = unit_id.split("-")[0]
    fixed_stat, fixed_value = fixed_value_for(chapter_id, slot, stars)
    return {
        "uid": uuid.uuid4().hex,
        "unit": unit_id,
        "chapter": chapter_id,
        "slot": slot,
        "stars": stars,
        "name": gear_names[stars][slot],
        "fixed_stat": fixed_stat,
        "fixed_value": fixed_value,
        "affix_stat": affix_stat,
        "affix_value": affix_value,
        "achievement": False,
    }


def make_achievement_reward(chapter_id, reward_type, fixed_value_for, name_formatter):
    chapter_id = str(chapter_id)
    spec = ACHIEVEMENT_REWARD_SPECS[(chapter_id, reward_type)]
    item = {
        "uid": uuid.uuid4().hex,
        "unit": spec["unit"],
        "slot": spec["slot"],
        "stars": 4,
        "name": name_formatter(chapter_id, spec["name"]),
        "fixed_stat": spec["fixed_stat"],
        "fixed_value": fixed_value_for(chapter_id, spec["slot"], 4)[1],
        "affix_stat": spec["affix_stat"],
        "affix_value": 0.25,
        "achievement": True,
    }
    if spec.get("include_chapter"):
        item["chapter"] = chapter_id
    return item


def sync_four_star_item_name(item, chapters, item_chapter_id, name_formatter):
    if int(item.get("stars", 0) or 0) != 4:
        return False
    chapter_id = item_chapter_id(item)
    if chapter_id not in chapters or not item.get("name"):
        return False
    expected_name = name_formatter(chapter_id, item["name"])
    if item["name"] == expected_name:
        return False
    item["name"] = expected_name
    item.setdefault("chapter", chapter_id)
    return True


def collected_three_star_slots(profile, chapter_id, slot_names, item_chapter_id):
    prefix = f"{chapter_id}:3:"
    recorded = {
        entry[len(prefix):]
        for entry in profile.get("collection_catalog", [])
        if entry.startswith(prefix)
    }
    currently_owned = {
        item["slot"]
        for item in profile["inventory"]
        if item.get("stars") == 3
        and not item.get("achievement")
        and item_chapter_id(item) == chapter_id
    }
    return recorded | currently_owned


def has_full_three_star_collection(profile, chapter_id, slot_names, item_chapter_id):
    return set(slot_names).issubset(
        collected_three_star_slots(profile, chapter_id, slot_names, item_chapter_id)
    )


def find_inventory_item(profile, uid):
    return next(
        (item for item in profile["inventory"] if item["uid"] == uid), None
    )


def find_achievement_item(profile, unit_key):
    return next(
        (item for item in profile["inventory"] if item.get("unit") == unit_key),
        None,
    )


def achievement_was_collected(profile, unit_key, stars=4):
    prefix = f"achievement:{stars}:{unit_key}:"
    return any(
        entry.startswith(prefix)
        for entry in profile.get("collection_catalog", [])
    ) or find_achievement_item(profile, unit_key) is not None


def collected_achievement_slots(profile, stars=4):
    owned = {
        item["slot"]
        for item in profile["inventory"]
        if item.get("achievement") and item.get("stars") == stars
    }
    prefix = f"achievement:{stars}:"
    recorded = {
        entry.rsplit(":", 1)[-1]
        for entry in profile.get("collection_catalog", [])
        if entry.startswith(prefix)
    }
    return owned | recorded


def sync_achievement_item(profile, unit_key, maker):
    """Update a legacy reward item without losing its equipped state."""
    item = find_achievement_item(profile, unit_key)
    if not item:
        return False
    expected = maker()
    old_slot = item["slot"]
    was_equipped = profile["equipment"].get(old_slot) == item["uid"]
    synced_keys = (
        "slot", "stars", "name", "fixed_stat", "fixed_value",
        "affix_stat", "affix_value", "achievement",
    )
    changed = any(item.get(key) != expected[key] for key in synced_keys)
    if not changed:
        return False
    for key in synced_keys:
        item[key] = expected[key]
    if old_slot != item["slot"] and was_equipped:
        profile["equipment"][old_slot] = None
        if not profile["equipment"].get(item["slot"]):
            profile["equipment"][item["slot"]] = item["uid"]
    return True
