"""Pure shop, forging, and dismantling rules.

This module deliberately has no Streamlit or database imports.  UI code may
call these helpers and decide when a changed profile should be persisted.
"""

from datetime import datetime, timedelta, timezone

from game_logic.profile import clear_equipment_item_uids
import random
import uuid


SHOP_ITEM_PRICE = 500
SHOP_ITEM_COUNT = 6
SHOP_REFRESH_HOURS = 24
SPECIAL_STONE_CRAFT_COST = 5

BASIC_AFFIXES = ("hp_pct", "attack_pct", "defense_pct", "speed_pct")
SPECIAL_STONE_KEYS = {
    "不使用": None,
    "部位基礎熔煉石": "slot_smelting_stones",
    "基礎詞條熔煉石": "basic_affix_smelting_stones",
    "進階詞條熔煉石": "advanced_affix_smelting_stones",
}


def highest_shop_chapter_id(profile, chapters, chapter_unit_ids):
    """Return the highest chapter in which the player cleared any unit."""
    completed = [
        chapter_id
        for chapter_id in chapters
        if any(
            profile["unit_best_stars"].get(unit_id, 0) > 0
            for unit_id in chapter_unit_ids(chapter_id)
        )
    ]
    return completed[-1] if completed else "1"


def make_shop_inventory_item(
    profile,
    chapters,
    units,
    chapter_unit_ids,
    slot_names,
    affix_names,
    affix_values,
    gear_names,
    fixed_value_for,
    chapter_id=None,
):
    chapter_id = chapter_id or highest_shop_chapter_id(
        profile, chapters, chapter_unit_ids
    )
    unit_id = random.choice(chapter_unit_ids(chapter_id))
    slot = random.choice(list(slot_names))
    affix_stat = random.choice(list(affix_names))
    value_pool = affix_values.get(affix_stat, affix_values["default"])[3]
    affix_value = random.choice(value_pool)
    fixed_stat, fixed_value = fixed_value_for(chapter_id, slot, 3)
    return {
        "shop_id": uuid.uuid4().hex,
        "sold": False,
        "item": {
            "uid": uuid.uuid4().hex,
            "unit": unit_id,
            "chapter": chapter_id,
            "slot": slot,
            "stars": 3,
            "name": gear_names[3][slot],
            "fixed_stat": fixed_stat,
            "fixed_value": fixed_value,
            "affix_stat": affix_stat,
            "affix_value": affix_value,
            "achievement": False,
            "source": "shop",
        },
    }


def paid_shop_refresh_cost(profile):
    """Double the cost after each group of five paid refreshes."""
    refresh_count = int(
        (profile.get("shop") or {}).get("paid_refresh_count", 0) or 0
    )
    return 100 * (2 ** (refresh_count // 5))


def refresh_shop_inventory(
    profile,
    chapters,
    units,
    chapter_unit_ids,
    slot_names,
    affix_names,
    affix_values,
    gear_names,
    fixed_value_for,
    paid=False,
    now_utc=None,
):
    paid_refresh_count = int(
        (profile.get("shop") or {}).get("paid_refresh_count", 0) or 0
    )
    if paid:
        refresh_cost = paid_shop_refresh_cost(profile)
        if profile["coins"] < refresh_cost:
            return False
        profile["coins"] -= refresh_cost
        paid_refresh_count += 1
    else:
        paid_refresh_count = 0

    chapter_id = highest_shop_chapter_id(profile, chapters, chapter_unit_ids)
    profile["shop"] = {
        "generated_at": (now_utc or datetime.now(timezone.utc)).isoformat(),
        "items": [
            make_shop_inventory_item(
                profile,
                chapters,
                units,
                chapter_unit_ids,
                slot_names,
                affix_names,
                affix_values,
                gear_names,
                fixed_value_for,
                chapter_id,
            )
            for _ in range(SHOP_ITEM_COUNT)
        ],
        "paid_refresh_count": paid_refresh_count,
    }
    return True


def ensure_shop_inventory(
    profile,
    chapters,
    units,
    chapter_unit_ids,
    slot_names,
    affix_names,
    affix_values,
    gear_names,
    fixed_value_for,
    now_utc=None,
):
    now_utc = now_utc or datetime.now(timezone.utc)
    shop = profile.get("shop") or {"generated_at": None, "items": []}
    needs_refresh = not shop.get("items") or not shop.get("generated_at")
    if not needs_refresh:
        try:
            generated = datetime.fromisoformat(
                shop["generated_at"].replace("Z", "+00:00")
            )
            needs_refresh = now_utc >= generated + timedelta(hours=SHOP_REFRESH_HOURS)
        except (TypeError, ValueError):
            needs_refresh = True
    if not needs_refresh:
        return False
    refresh_shop_inventory(
        profile,
        chapters,
        units,
        chapter_unit_ids,
        slot_names,
        affix_names,
        affix_values,
        gear_names,
        fixed_value_for,
        paid=False,
        now_utc=now_utc,
    )
    return True


def remove_inventory_entries(profile, uids):
    uid_set = set(uids)
    clear_equipment_item_uids(profile, uid_set)
    profile["inventory"] = [
        item for item in profile["inventory"] if item["uid"] not in uid_set
    ]


def make_forged_inventory_item(
    profile,
    source_stars,
    chapter_id,
    chapter_unit_ids,
    units,
    gear_names,
    affix_values,
    fixed_value_for,
    make_random_item,
    selected_slot=None,
    selected_affix=None,
):
    target_stars = source_stars + 1
    if selected_slot:
        unit_id = next(
            unit_id
            for unit_id in chapter_unit_ids(chapter_id)
            if selected_slot in units[unit_id]["slots"]
        )
    else:
        unit_id = random.choice(chapter_unit_ids(chapter_id))

    item = make_random_item({"inventory": []}, unit_id, target_stars)
    if selected_slot:
        item["slot"] = selected_slot
        item["name"] = gear_names[target_stars][selected_slot]
        fixed_stat, fixed_value = fixed_value_for(
            chapter_id, selected_slot, target_stars
        )
        item["fixed_stat"] = fixed_stat
        item["fixed_value"] = fixed_value
    if selected_affix:
        item["affix_stat"] = selected_affix
        item["affix_value"] = random.choice(
            affix_values.get(selected_affix, affix_values["default"])[target_stars]
        )
    item["source"] = "forge"
    return item


def purchase_shop_entry(profile, entry):
    """Buy one unsold shop entry; return whether the purchase succeeded."""
    if entry.get("sold") or profile.get("coins", 0) < SHOP_ITEM_PRICE:
        return False
    profile["coins"] -= SHOP_ITEM_PRICE
    entry["sold"] = True
    profile["inventory"].append(entry["item"])
    return True


def craft_special_stone(profile, stone_key):
    if profile.get("smelting_stones", 0) < SPECIAL_STONE_CRAFT_COST:
        return False
    profile["smelting_stones"] -= SPECIAL_STONE_CRAFT_COST
    profile[stone_key] = profile.get(stone_key, 0) + 1
    return True


def dismantle_value(items):
    """Return coins and ordinary smelting stones yielded by equipment."""
    return (
        sum(item["stars"] * 100 for item in items),
        sum(1 for item in items if item["stars"] == 3),
    )


def dismantle_inventory_items(profile, items):
    if any(item["stars"] >= 4 for item in items):
        return False
    coins, stones = dismantle_value(items)
    profile["coins"] += coins
    profile["smelting_stones"] += stones
    remove_inventory_entries(profile, [item["uid"] for item in items])
    return True
