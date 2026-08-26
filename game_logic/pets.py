"""Pet catalog, save-data normalization, sorting, and equipped effects."""

from functools import lru_cache
import json
import random
from pathlib import Path


PET_TOTAL = 6
DEFAULT_PET_ID = "big_orange_cat"
PET_ELEMENT_ORDER = ("light", "dark", "wood", "earth", "water", "fire")
PET_MAX_LEVEL = 20
PET_FOOD_EXP = 30
PET_ELIXIR_EXP = 50
PET_FREE_SUMMONS_PER_DAY = 1
PET_PAID_SUMMONS_PER_DAY = 10
PET_SUMMON_COIN_COST = 2000
PET_ADVANCE_SOUL_COSTS = {1: 2, 2: 6}
PET_DISMANTLE_COIN_BONUS = 0.20
PET_ELEMENT_DAMAGE_BONUS = 0.15


@lru_cache(maxsize=1)
def pet_catalog():
    """Load the six-pet catalog once per Python process."""
    path = Path(__file__).resolve().parent.parent / "assets" / "pets" / "pets.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    pets = {entry["id"]: entry for entry in data["pets"]}
    return pets, data["elements"]


def element_matchup(attack_element, boss_element):
    """Return advantage state and multiplier for an elemental hero attack."""
    elements = pet_catalog()[1]
    if attack_element not in elements or boss_element not in elements:
        return "neutral", 1.0
    if elements[attack_element]["strong_against"] == boss_element:
        return "advantage", 1.0 + PET_ELEMENT_DAMAGE_BONUS
    if elements[boss_element]["strong_against"] == attack_element:
        return "disadvantage", 1.0 - PET_ELEMENT_DAMAGE_BONUS
    return "neutral", 1.0


def default_owned_pet():
    """Return the silent launch gift shared by new and existing players."""
    return new_owned_pet(DEFAULT_PET_ID, acquired_order=1)


def new_owned_pet(pet_id, acquired_order, stars=1):
    """Create one save-data entry from the catalog without sharing mutable state."""
    catalog_entry = pet_catalog()[0][pet_id]
    return {
        "id": pet_id,
        "nickname": catalog_entry["name"],
        "stars": max(1, min(3, int(stars))),
        "level": 1,
        "exp": 0,
        "acquired_order": int(acquired_order),
    }


def grant_pet(profile, pet_id, stars=1):
    """Grant one pet once.  Existing level, EXP, nickname and stars are preserved."""
    ensure_pet_profile(profile)
    if pet_id not in pet_catalog()[0]:
        raise KeyError(f"Unknown pet id: {pet_id}")
    if any(entry["id"] == pet_id for entry in profile["pets"]):
        return False
    next_order = max(
        (int(entry.get("acquired_order", 0)) for entry in profile["pets"]),
        default=0,
    ) + 1
    profile["pets"].append(new_owned_pet(pet_id, next_order, stars))
    return True


def grant_all_pets(profile, stars=1):
    """Grant every catalog pet once and return the names that were newly added."""
    granted = []
    for pet_id, catalog_entry in pet_catalog()[0].items():
        if grant_pet(profile, pet_id, stars=stars):
            granted.append(catalog_entry["name"])
    return granted


def ensure_pet_profile(profile):
    """Normalize old profiles without displaying or enqueueing a reward notice."""
    changed = False
    owned = profile.get("pets")
    if not isinstance(owned, list):
        owned = [default_owned_pet()]
        profile["pets"] = owned
        changed = True

    normalized = []
    seen = set()
    for position, raw in enumerate(owned, 1):
        entry = {"id": raw} if isinstance(raw, str) else dict(raw or {})
        pet_id = entry.get("id")
        if pet_id in seen or pet_id not in pet_catalog()[0]:
            continue
        seen.add(pet_id)
        catalog_entry = pet_catalog()[0][pet_id]
        entry.setdefault("nickname", catalog_entry["name"])
        entry.setdefault("stars", 1)
        entry.setdefault("level", 1)
        entry.setdefault("exp", 0)
        entry.setdefault("acquired_order", position)
        normalized.append(entry)
    if not normalized:
        normalized = [default_owned_pet()]
    if normalized != owned:
        profile["pets"] = normalized
        changed = True

    defaults = {
        "equipped_pet_id": None,
        "pet_image_style": "chibi",
        "pet_sort_mode": "acquired",
        "pet_food_cans": 0,
        "pet_element_elixirs": {element: 0 for element in PET_ELEMENT_ORDER},
        "pet_element_souls": {element: 0 for element in PET_ELEMENT_ORDER},
        "pet_food_boss_mail_sent": [],
        "summon_tickets": 0,
        "pet_summon_period": None,
        "pet_free_summons_used": 0,
        "pet_paid_summons_used": 0,
        "pet_summon_chapter_mail_sent": [],
    }
    for key, value in defaults.items():
        if key not in profile:
            profile[key] = value
            changed = True
    if profile.get("pet_image_style") not in {"chibi", "mythic"}:
        profile["pet_image_style"] = "chibi"
        changed = True
    if profile.get("pet_sort_mode") not in {"acquired", "element", "stars"}:
        profile["pet_sort_mode"] = "acquired"
        changed = True
    owned_ids = {entry["id"] for entry in profile["pets"]}
    if profile.get("equipped_pet_id") not in owned_ids:
        if profile.get("equipped_pet_id") is not None:
            changed = True
        profile["equipped_pet_id"] = None
    elixirs = profile.get("pet_element_elixirs")
    if not isinstance(elixirs, dict):
        elixirs = {}
        profile["pet_element_elixirs"] = elixirs
        changed = True
    for element in PET_ELEMENT_ORDER:
        if element not in elixirs:
            elixirs[element] = 0
            changed = True
    souls = profile.get("pet_element_souls")
    if not isinstance(souls, dict):
        souls = {}
        profile["pet_element_souls"] = souls
        changed = True
    for element in PET_ELEMENT_ORDER:
        if element not in souls:
            souls[element] = 0
            changed = True
    if not isinstance(profile.get("pet_food_boss_mail_sent"), list):
        profile["pet_food_boss_mail_sent"] = []
        changed = True
    if not isinstance(profile.get("pet_summon_chapter_mail_sent"), list):
        profile["pet_summon_chapter_mail_sent"] = []
        changed = True
    return changed


def sync_pet_summon_period(profile, period_key):
    """Reset free/paid summon counters at the daily 08:00 boundary."""
    ensure_pet_profile(profile)
    if profile.get("pet_summon_period") == period_key:
        return False
    profile["pet_summon_period"] = period_key
    profile["pet_free_summons_used"] = 0
    profile["pet_paid_summons_used"] = 0
    return True


def summon_pet(profile, mode="paid", available_pet_ids=None, rng=None):
    """Perform one equal-rate summon and consume the appropriate resource."""
    ensure_pet_profile(profile)
    catalog = pet_catalog()[0]
    candidates = [pet_id for pet_id in (available_pet_ids or catalog) if pet_id in catalog]
    if not candidates:
        return {"ok": False, "reason": "目前沒有可召喚的寵物。"}

    payment = "free"
    if mode == "free":
        used = int(profile.get("pet_free_summons_used", 0))
        if used >= PET_FREE_SUMMONS_PER_DAY:
            return {"ok": False, "reason": "今天的免費召喚已使用。"}
    else:
        used = int(profile.get("pet_paid_summons_used", 0))
        if used >= PET_PAID_SUMMONS_PER_DAY:
            return {"ok": False, "reason": "今天的道具召喚次數已用完。"}
        if int(profile.get("summon_tickets", 0)) > 0:
            profile["summon_tickets"] -= 1
            payment = "ticket"
        elif int(profile.get("coins", 0)) >= PET_SUMMON_COIN_COST:
            profile["coins"] -= PET_SUMMON_COIN_COST
            payment = "coins"
        else:
            return {
                "ok": False,
                "reason": f"召喚券不足，且金幣少於 {PET_SUMMON_COIN_COST}。",
            }

    randomizer = rng or random
    pet_id = randomizer.choice(candidates)
    owned = next((entry for entry in profile["pets"] if entry["id"] == pet_id), None)
    is_new = owned is None
    duplicate_converted = False
    soul_element = catalog[pet_id]["element"]
    if is_new:
        grant_pet(profile, pet_id, stars=1)
        owned = next(entry for entry in profile["pets"] if entry["id"] == pet_id)
    else:
        profile["pet_element_souls"][soul_element] = (
            int(profile["pet_element_souls"].get(soul_element, 0)) + 1
        )
        duplicate_converted = True

    if mode == "free":
        profile["pet_free_summons_used"] = int(profile.get("pet_free_summons_used", 0)) + 1
    else:
        profile["pet_paid_summons_used"] = int(profile.get("pet_paid_summons_used", 0)) + 1
    return {
        "ok": True,
        "pet_id": pet_id,
        "pet": pet_details(profile, pet_id),
        "is_new": is_new,
        "duplicate_converted": duplicate_converted,
        "soul_element": soul_element if duplicate_converted else None,
        "soul_count": int(profile["pet_element_souls"].get(soul_element, 0)),
        "payment": payment,
        "coins_remaining": int(profile.get("coins", 0)),
    }


def advance_pet(profile, pet_id):
    """Advance a pet with same-element souls; summons never raise stars directly."""
    ensure_pet_profile(profile)
    pet = next((entry for entry in profile["pets"] if entry["id"] == pet_id), None)
    if not pet:
        return {"ok": False, "reason": "找不到這隻寵物。"}
    stars = max(1, min(3, int(pet.get("stars", 1))))
    if stars >= 3:
        return {"ok": False, "reason": "這隻寵物已經是三星。"}
    element = pet_catalog()[0][pet_id]["element"]
    cost = PET_ADVANCE_SOUL_COSTS[stars]
    owned_souls = int(profile["pet_element_souls"].get(element, 0))
    if owned_souls < cost:
        element_name = pet_catalog()[1][element]["name"]
        return {
            "ok": False,
            "reason": f"{element_name}屬性元神不足，需要 {cost} 個，目前有 {owned_souls} 個。",
        }
    profile["pet_element_souls"][element] = owned_souls - cost
    pet["stars"] = stars + 1
    return {
        "ok": True,
        "pet": pet_details(profile, pet_id),
        "cost": cost,
        "souls_remaining": profile["pet_element_souls"][element],
    }


def pet_exp_requirement(level):
    """Use the same per-level EXP curve as the player."""
    return max(1, int(level)) * 100


def pet_unlocked_bonuses(pet):
    """Return the four permanent follow bonuses unlocked by pet level."""
    level = int(pet.get("level", 1)) if pet else 0
    return {
        "hp_pct": 0.25 if level >= 5 else 0.0,
        "attack_pct": 0.25 if level >= 10 else 0.0,
        "defense_pct": 0.25 if level >= 15 else 0.0,
        "attack_speed_flat": 0.25 if level >= 20 else 0.0,
    }


def pet_dismantle_coin_bonus(profile):
    """Return the followed pet's dismantling bonus after its two-star advance."""
    pet = equipped_pet(profile)
    if not pet or int(pet.get("stars", 1)) < 2:
        return 0.0
    return PET_DISMANTLE_COIN_BONUS


def add_pet_experience(profile, pet_id, amount):
    """Add EXP without allowing the pet to exceed its owner's current level."""
    ensure_pet_profile(profile)
    pet = next((entry for entry in profile["pets"] if entry["id"] == pet_id), None)
    if not pet:
        return {"ok": False, "reason": "找不到這隻寵物。", "levels": 0}
    player_level = max(1, int(profile.get("level", 1)))
    if int(pet.get("level", 1)) >= player_level:
        return {
            "ok": False,
            "reason": f"寵物等級不能超過勇者，目前上限為 Lv{player_level}。",
            "levels": 0,
        }
    pet["exp"] = int(pet.get("exp", 0)) + max(0, int(amount))
    gained = 0
    while (
        int(pet["level"]) < min(PET_MAX_LEVEL, player_level)
        and int(pet["exp"]) >= pet_exp_requirement(pet["level"])
    ):
        pet["exp"] -= pet_exp_requirement(pet["level"])
        pet["level"] += 1
        gained += 1
    # Do not display an impossible EXP value while the owner level is the cap.
    if int(pet["level"]) >= player_level:
        pet["exp"] = min(int(pet["exp"]), pet_exp_requirement(pet["level"]) - 1)
    return {"ok": True, "reason": "", "levels": gained, "pet": pet}


def use_pet_training_item(profile, pet_id, item_kind, quantity=1):
    """Consume up to ``quantity`` training items without wasting any at the level cap."""
    details = pet_details(profile, pet_id)
    if not details:
        return {"ok": False, "reason": "找不到這隻寵物。", "levels": 0}
    try:
        requested = max(1, int(quantity))
    except (TypeError, ValueError):
        requested = 1
    if item_kind == "can":
        stock = int(profile.get("pet_food_cans", 0))
        if stock <= 0:
            return {"ok": False, "reason": "美味罐頭數量不足。", "levels": 0}
        amount = PET_FOOD_EXP
        stock_key = "pet_food_cans"
    else:
        element = details["element"]
        if item_kind != f"elixir:{element}":
            return {"ok": False, "reason": "特製仙丹的屬性與寵物不符。", "levels": 0}
        stock = int(profile["pet_element_elixirs"].get(element, 0))
        if stock <= 0:
            return {"ok": False, "reason": f"特製仙丹（{details['element_name']}屬性）數量不足。", "levels": 0}
        amount = PET_ELIXIR_EXP
        stock_key = element

    target = min(requested, stock)
    items_used = 0
    levels = 0
    latest = None
    for _ in range(target):
        result = add_pet_experience(profile, pet_id, amount)
        if not result["ok"]:
            break
        if item_kind == "can":
            profile[stock_key] -= 1
        else:
            profile["pet_element_elixirs"][stock_key] -= 1
        items_used += 1
        levels += int(result.get("levels", 0))
        latest = result

    if items_used == 0:
        return {
            "ok": False,
            "reason": f"寵物等級不能超過勇者，目前上限為 Lv{int(profile.get('level', 1))}。",
            "levels": 0,
            "items_used": 0,
            "exp_added": 0,
        }
    return {
        "ok": True,
        "reason": "",
        "levels": levels,
        "pet": latest["pet"],
        "items_used": items_used,
        "exp_added": items_used * amount,
        "stopped_at_cap": items_used < target,
    }


def owned_pet_entries(profile, sort_mode=None):
    ensure_pet_profile(profile)
    entries = list(profile["pets"])
    mode = sort_mode or profile.get("pet_sort_mode", "acquired")
    element_order = {element: index for index, element in enumerate(PET_ELEMENT_ORDER)}
    catalog = pet_catalog()[0]
    if mode == "element":
        entries.sort(
            key=lambda entry: (
                element_order[catalog[entry["id"]]["element"]],
                entry.get("acquired_order", 0),
            )
        )
    elif mode == "stars":
        entries.sort(key=lambda entry: (int(entry.get("stars", 1)), entry.get("acquired_order", 0)))
    else:
        entries.sort(key=lambda entry: entry.get("acquired_order", 0))
    return entries


def pet_details(profile, pet_id):
    ensure_pet_profile(profile)
    owned = next((entry for entry in profile["pets"] if entry["id"] == pet_id), None)
    catalog, elements = pet_catalog()
    if not owned or pet_id not in catalog:
        return None
    base = catalog[pet_id]
    element = elements[base["element"]]
    details = {
        **base,
        **owned,
        "display_name": owned.get("nickname") or base["name"],
        "element_name": element["name"],
        "element_color": element["color"],
        "drop_bonus_pct": 0.10,
    }
    details["exp_required"] = pet_exp_requirement(details["level"])
    details["unlocked_bonuses"] = pet_unlocked_bonuses(details)
    return details


def equipped_pet(profile):
    pet_id = profile.get("equipped_pet_id")
    return pet_details(profile, pet_id) if pet_id else None


def pet_asset_path(pet, style):
    relative = pet["images"].get(style, pet["images"]["chibi"])
    return Path(__file__).resolve().parent.parent / relative
