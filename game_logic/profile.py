"""Character save-data defaults and backward-compatible normalization."""

from game_logic.pets import default_owned_pet, ensure_pet_profile


def create_new_profile(name, slot_names, unit_ids):
    return {
        "data_version": 2,
        "name": name,
        "avatar_data": None,
        "gender": None,
        "level": 1,
        "exp": 0,
        "coins": 0,
        "smelting_stones": 0,
        "slot_smelting_stones": 0,
        "basic_affix_smelting_stones": 0,
        "advanced_affix_smelting_stones": 0,
        "sweep_tickets": 0,
        "ticket_rewarded_units": [],
        "titles": [],
        "equipped_title": None,
        "retro_reward_notice": [],
        "daily_login_period": None,
        "daily_login_claimed": False,
        "daily_practice_period": None,
        "daily_practice_count": 0,
        "daily_practice_claimed": False,
        "claimed_permanent_tasks": [],
        "claimed_special_tasks": [],
        "task_rewards_initialized": False,
        "elite_special_tasks_migrated": False,
        "boss_best_times": {},
        "shop": {"generated_at": None, "items": [], "paid_refresh_count": 0},
        "inventory": [],
        "collection_catalog": [],
        "equipment": {slot: None for slot in slot_names},
        "equipment_loadouts": None,
        "active_equipment_loadout": 0,
        "pets": [default_owned_pet()],
        "equipped_pet_id": None,
        "pet_image_style": "chibi",
        "pet_sort_mode": "acquired",
        "pet_food_cans": 0,
        "pet_element_elixirs": {
            "light": 0, "dark": 0, "wood": 0,
            "earth": 0, "water": 0, "fire": 0,
        },
        "pet_element_souls": {
            "light": 0, "dark": 0, "wood": 0,
            "earth": 0, "water": 0, "fire": 0,
        },
        "pet_food_boss_mail_sent": [],
        "summon_tickets": 0,
        "pet_summon_period": None,
        "pet_free_summons_used": 0,
        "pet_paid_summons_used": 0,
        "pet_summon_chapter_mail_sent": [],
        "unit_best_stars": {unit_id: 0 for unit_id in unit_ids},
        "chapter_reward_claimed": False,
        "collection_reward_claimed": False,
        "collection_item_claimed": False,
        "boss_exp_claimed": False,
        "boss_wins": 0,
        "elite_boss_exp_claimed": False,
        "elite_boss_wins": 0,
        "elite_reward_claimed": False,
        "chapter2_reward_claimed": False,
        "chapter2_collection_reward_claimed": False,
        "chapter2_boss_exp_claimed": False,
        "chapter2_boss_wins": 0,
        "chapter2_elite_boss_exp_claimed": False,
        "chapter2_elite_boss_wins": 0,
        "chapter2_elite_reward_claimed": False,
        "chapter3_boss_exp_claimed": False,
        "chapter3_boss_wins": 0,
        "chapter3_elite_boss_exp_claimed": False,
        "chapter3_elite_boss_wins": 0,
        "chapter3_reward_claimed": False,
        "chapter3_collection_reward_claimed": False,
        "chapter3_elite_reward_claimed": False,
        "chapter4_boss_exp_claimed": False,
        "chapter4_boss_wins": 0,
        "chapter4_elite_boss_exp_claimed": False,
        "chapter4_elite_boss_wins": 0,
        "chapter4_reward_claimed": False,
        "chapter4_collection_reward_claimed": False,
        "chapter4_elite_reward_claimed": False,
        "chapter5_boss_exp_claimed": False,
        "chapter5_boss_wins": 0,
        "chapter5_elite_boss_exp_claimed": False,
        "chapter5_elite_boss_wins": 0,
        "chapter5_reward_claimed": False,
        "chapter5_collection_reward_claimed": False,
        "chapter5_elite_reward_claimed": False,
        "chapter6_boss_exp_claimed": False,
        "chapter6_boss_wins": 0,
        "chapter6_elite_boss_exp_claimed": False,
        "chapter6_elite_boss_wins": 0,
        "chapter6_reward_claimed": False,
        "chapter6_collection_reward_claimed": False,
        "chapter6_elite_reward_claimed": False,
    }


def sync_profile_collection_catalog(profile, item_chapter_id):
    """Record every acquired item permanently, even after it is removed."""
    catalog = set(profile.get("collection_catalog", []))
    for item in profile.get("inventory", []):
        stars = int(item.get("stars", 0) or 0)
        slot = item.get("slot")
        if not stars or not slot:
            continue
        if item.get("achievement"):
            unit_key = str(item.get("unit", "achievement"))
            catalog.add(f"achievement:{stars}:{unit_key}:{slot}")
        else:
            chapter_id = item_chapter_id(item)
            if chapter_id:
                catalog.add(f"{chapter_id}:{stars}:{slot}")
    profile["collection_catalog"] = sorted(catalog)


def normalize_profile_data(profile, name, slot_names, unit_ids, item_chapter_id):
    template = create_new_profile(name, slot_names, unit_ids)
    if profile.get("data_version") != 2:
        migrated = {
            **template,
            "level": profile.get("level", 1),
            "exp": profile.get("exp", 0),
            "boss_exp_claimed": profile.get("boss_exp_claimed", False),
            "boss_wins": profile.get("boss_wins", 0),
        }
        ensure_equipment_loadouts(migrated, slot_names)
        return migrated
    for key, value in template.items():
        profile.setdefault(key, value)
    for slot in slot_names:
        profile["equipment"].setdefault(slot, None)
    ensure_equipment_loadouts(profile, slot_names)
    ensure_pet_profile(profile)
    for unit_id in unit_ids:
        profile["unit_best_stars"].setdefault(unit_id, 0)
    sync_profile_collection_catalog(profile, item_chapter_id)

    catalog = set(profile.get("collection_catalog", []))
    collection_claims = (
        ("collection_reward_claimed", "1"),
        ("chapter2_collection_reward_claimed", "2"),
        ("chapter3_collection_reward_claimed", "3"),
        ("chapter4_collection_reward_claimed", "4"),
        ("chapter5_collection_reward_claimed", "5"),
        ("chapter6_collection_reward_claimed", "6"),
    )
    for claimed_key, chapter_id in collection_claims:
        if profile.get(claimed_key):
            catalog.update(f"{chapter_id}:3:{slot}" for slot in slot_names)

    achievement_history = (
        ("chapter_reward_claimed", "chapter-1", "weapon"),
        ("collection_item_claimed", "chapter-1-collection", "necklace"),
        ("elite_reward_claimed", "chapter-1-elite", "helmet"),
        ("chapter2_reward_claimed", "chapter-2", "gloves"),
        ("chapter2_collection_reward_claimed", "chapter-2-collection", "boots"),
        ("chapter2_elite_reward_claimed", "chapter-2-elite", "shield"),
        ("chapter3_reward_claimed", "chapter-3", "armor"),
        ("chapter3_collection_reward_claimed", "chapter-3-collection", "belt"),
        ("chapter3_elite_reward_claimed", "chapter-3-elite", "ring"),
        ("chapter4_reward_claimed", "chapter-4", "helmet"),
        ("chapter4_collection_reward_claimed", "chapter-4-collection", "boots"),
        ("chapter4_elite_reward_claimed", "chapter-4-elite", "weapon"),
        ("chapter5_reward_claimed", "chapter-5", "armor"),
        ("chapter5_collection_reward_claimed", "chapter-5-collection", "necklace"),
        ("chapter5_elite_reward_claimed", "chapter-5-elite", "shield"),
        ("chapter6_reward_claimed", "chapter-6", "gloves"),
        ("chapter6_collection_reward_claimed", "chapter-6-collection", "ring"),
        ("chapter6_elite_reward_claimed", "chapter-6-elite", "weapon"),
    )
    for claimed_key, unit_key, slot in achievement_history:
        if profile.get(claimed_key):
            catalog.add(f"achievement:4:{unit_key}:{slot}")
    profile["collection_catalog"] = sorted(catalog)


    rewarded_units = set(profile.get("ticket_rewarded_units", []))
    passed_units = {
        unit_id for unit_id, stars in profile["unit_best_stars"].items() if stars > 0
    }
    missing_units = sorted(passed_units - rewarded_units)
    if missing_units:
        profile["sweep_tickets"] += len(missing_units)
        profile["ticket_rewarded_units"] = sorted(rewarded_units | set(missing_units))
        profile["retro_reward_notice"].append(
            f"依歷史通關紀錄補發 {len(missing_units)} 張擊殺券"
        )

    title_rewards = (
        ("elite_boss_wins", "好像有點勇哦"),
        ("chapter2_elite_boss_wins", "別小看我！"),
        ("chapter3_elite_boss_wins", "一刀斬龍"),
        ("chapter4_elite_boss_wins", "渡雷劫方可成仙"),
        ("chapter5_elite_boss_wins", "魚與熊掌我都要"),
        ("chapter6_elite_boss_wins", "鬼火不滅"),
    )
    for wins_key, title in title_rewards:
        if profile.get(wins_key, 0) > 0 and title not in profile["titles"]:
            profile["titles"].append(title)
            profile["retro_reward_notice"].append(f"補發成就稱號「{title}」")
    return profile


def ensure_equipment_loadouts(profile, slot_names):
    """Create two backward-compatible equipment sets around legacy equipment."""
    blank = {slot: None for slot in slot_names}
    loadouts = profile.get("equipment_loadouts")
    if not isinstance(loadouts, list) or len(loadouts) < 2:
        current = {
            slot: profile.get("equipment", {}).get(slot)
            for slot in slot_names
        }
        loadouts = [
            {"name": "裝備（一）", "equipment": current},
            {"name": "裝備（二）", "equipment": dict(blank)},
        ]
        profile["equipment_loadouts"] = loadouts
    for index in range(2):
        loadout = loadouts[index]
        if not isinstance(loadout, dict):
            loadout = {"name": f"裝備（{'一' if index == 0 else '二'}）", "equipment": dict(blank)}
            loadouts[index] = loadout
        loadout.setdefault("name", f"裝備（{'一' if index == 0 else '二'}）")
        legacy_names = {0: {"主要裝備", "裝備配置 1"}, 1: {"第二套裝備", "裝備配置 2"}}
        if loadout.get("name") in legacy_names[index]:
            loadout["name"] = f"裝備（{'一' if index == 0 else '二'}）"
        if not isinstance(loadout.get("equipment"), dict):
            loadout["equipment"] = dict(blank)
        for slot in slot_names:
            loadout["equipment"].setdefault(slot, None)
    active = int(profile.get("active_equipment_loadout", 0) or 0)
    active = 0 if active not in (0, 1) else active
    profile["active_equipment_loadout"] = active
    profile["equipment"] = dict(loadouts[active]["equipment"])


def sync_active_equipment_loadout(profile, slot_names):
    """Copy the legacy active-equipment mapping into the selected loadout."""
    if not isinstance(profile.get("equipment_loadouts"), list) or len(profile["equipment_loadouts"]) < 2:
        ensure_equipment_loadouts(profile, slot_names)
    active = profile["active_equipment_loadout"]
    profile["equipment_loadouts"][active]["equipment"] = {
        slot: profile["equipment"].get(slot) for slot in slot_names
    }


def equipped_item_uids(profile):
    """Return item IDs used by either equipment set."""
    result = {uid for uid in profile.get("equipment", {}).values() if uid}
    for loadout in profile.get("equipment_loadouts") or []:
        result.update(uid for uid in loadout.get("equipment", {}).values() if uid)
    return result


def clear_equipment_item_uids(profile, uids):
    """Remove deleted item references from the active and inactive sets."""
    uid_set = set(uids)
    for equipment in [profile.get("equipment", {})] + [
        loadout.get("equipment", {}) for loadout in profile.get("equipment_loadouts") or []
    ]:
        for slot, uid in equipment.items():
            if uid in uid_set:
                equipment[slot] = None
