"""Deterministic boss battle calculation.

The simulator returns only data. Streamlit rendering, animation timing and
database rewards stay in ``app.py``.
"""

from game_data.config import BOSS_CONFIGS
from game_logic.pets import element_matchup


def simulate_battle(stats, boss_type, chapter_id):
    config = BOSS_CONFIGS[f"{chapter_id}_{boss_type}"]
    boss_element = config["element"]
    pet_skill = stats.get("pet_skill")
    attack_element = stats.get("attack_element")
    pet_element = pet_skill.get("element") if pet_skill else None
    pet_level = int(pet_skill.get("level", 0)) if pet_skill else 0
    _, element_damage_multiplier = element_matchup(attack_element, boss_element)
    elite_boss_reduction = stats["boss_hp_reduction"] if boss_type == "elite" else 0.0
    elite_boss_damage = stats["boss_damage_pct"] if boss_type == "elite" else 0.0
    elite_boss_slow = stats["boss_attack_slow_pct"] if boss_type == "elite" else 0.0
    elite_first_hit = stats["first_hit_percent"] if boss_type == "elite" else 0.0
    boss_max = config["hp"] * (1 - elite_boss_reduction)
    pet_start_text = None
    pet_damage_multiplier = 1.0
    pet_periodic_interval = float("inf")
    if pet_element == "water":
        hp_multiplier = 0.8 if boss_element == "fire" else 1.2 if boss_element == "earth" else 0.9
        boss_max *= hp_multiplier
        pet_start_text = f"魚躍龍門發動：BOSS最大HP{'增加' if hp_multiplier > 1 else '降低'}{abs(1 - hp_multiplier):.0%}"
    elif pet_element == "dark":
        pet_damage_multiplier = 1.25 if boss_element == "light" else 0.75 if boss_element == "dark" else 1.10
        pet_start_text = f"心有餘力不足發動：勇者傷害調整為{pet_damage_multiplier:.0%}"
    elif pet_element == "wood":
        pet_start_text = "盤根錯節發動"
    elif pet_element == "earth":
        pet_periodic_interval = 1.0
        pet_start_text = "吞天裂地發動"
    elif pet_element == "fire":
        pet_periodic_interval = 5.0
        pet_start_text = "烈焰咆嘯發動"
    elif pet_element == "light":
        pet_start_text = "大橘為重發動"
    boss_hp = boss_max
    core_hp = stats["hp"]
    shield_hp = stats["hp"] * stats["shield_pct"]
    player_hp = core_hp + shield_hp
    effective_attack_speed = max(
        0.1, stats["attack_speed"] - config.get("hero_speed_reduction", 0.0)
    )
    hero_interval = 1 / effective_attack_speed
    boss_attack_speed = 1 / config["interval"]
    if pet_element == "wood":
        pet_speed_delta = -0.300 if boss_element == "earth" else 0.300 if boss_element == "fire" else -0.150
        boss_attack_speed = max(0.1, boss_attack_speed + pet_speed_delta)
    boss_interval = (1 / boss_attack_speed) * (1 + elite_boss_slow)
    effective_defense = max(0.0, stats["defense"] - config.get("defense_reduction", 0))
    received = (
        config["damage"] * 100 / (100 + effective_defense)
        * (1 - stats["damage_reduction_pct"])
    )
    critical_every = round(1 / stats["critical_rate"]) if stats["critical_rate"] > 0 else None
    skill_interval = config.get("skill_interval")
    next_skill = skill_interval if skill_interval else float("inf")
    threshold_skill_used = False
    next_hero, next_boss = 0.0, boss_interval
    next_pet_skill = pet_periodic_interval
    hero_hits = boss_hits = 0
    events = [{"time": 0.0, "boss_hp": boss_hp, "player_hp": player_hp, "text": "戰鬥開始"}]
    if pet_start_text:
        events.append({
            "time": 0.0,
            "boss_hp": boss_hp,
            "player_hp": player_hp,
            "text": pet_start_text,
            "event_type": "pet_skill",
            "pet_skill": pet_skill["name"],
            "pet_element": pet_element,
        })
    if config.get("skill_at_start"):
        events.append({
            "time": 0.0, "boss_hp": boss_hp, "player_hp": player_hp,
            "text": (
                f"BOSS施放技能「{config['skill']}」："
                f"勇者造成的傷害降低{config.get('hero_damage_reduction', 0):.0%}"
            ),
        })
    for _ in range(10000):
        if next_hero <= next_boss and next_hero <= next_skill and next_hero <= next_pet_skill:
            now = next_hero
            hero_hits += 1
            is_critical = bool(critical_every and hero_hits % critical_every == 0)
            damage_multiplier = max(
                0.0,
                1 + elite_boss_damage - config.get("hero_damage_reduction", 0.0),
            )
            normal_damage = (
                stats["attack"]
                * damage_multiplier
                * pet_damage_multiplier
                * element_damage_multiplier
            )
            if is_critical:
                normal_damage *= 1.5 + stats["critical_damage"]
            damage = normal_damage + (boss_max * elite_first_hit if hero_hits == 1 else 0)
            pet_damage = 0.0
            pet_healing = 0.0
            if pet_element == "light":
                if boss_element == "light":
                    pet_healing = pet_level * 5
                else:
                    pet_damage = pet_level * 5
            boss_hp = max(0.0, min(boss_max, boss_hp - damage - pet_damage + pet_healing))
            critical_text = "，暴擊！" if is_critical else ""
            events.append({"time": now, "boss_hp": boss_hp, "player_hp": player_hp, "text": f"勇者第{hero_hits}擊{critical_text}造成{damage:.1f}傷害"})
            if pet_damage or pet_healing:
                events.append({
                    "time": now,
                    "boss_hp": boss_hp,
                    "player_hp": player_hp,
                    "text": (
                        f"大橘為重造成{pet_damage:g}真實傷害"
                        if pet_damage else f"大橘為重使BOSS回復{pet_healing:g}HP"
                    ),
                    "event_type": "pet_skill",
                    "pet_skill": pet_skill["name"],
                    "pet_element": pet_element,
                    "damage": pet_damage,
                    "healing": pet_healing,
                })
            if boss_hp <= 0:
                return {"victory": True, "duration": now, "events": events}
            if (
                config.get("skill_hp_threshold") is not None
                and not threshold_skill_used
                and boss_hp <= boss_max * config["skill_hp_threshold"]
            ):
                next_skill = now
            next_hero += hero_interval
        elif next_boss <= next_skill and next_boss <= next_pet_skill:
            now = next_boss
            boss_hits += 1
            boss_critical = bool(config.get("critical_rate") and boss_hits % round(1 / config["critical_rate"]) == 0)
            hit_damage = received * (1.5 if boss_critical else 1.0)
            shield_absorbed = min(shield_hp, hit_damage)
            shield_hp -= shield_absorbed
            core_hp = max(0.0, core_hp - (hit_damage - shield_absorbed))
            player_hp = core_hp + shield_hp
            critical_text = "，暴擊！" if boss_critical else ""
            events.append({"time": now, "boss_hp": boss_hp, "player_hp": player_hp, "text": f"BOSS第{boss_hits}擊{critical_text}造成{hit_damage:.1f}傷害"})
            if core_hp <= 0:
                return {"victory": False, "duration": now, "events": events}
            next_boss += boss_interval
        elif next_skill <= next_pet_skill:
            now = next_skill
            if config.get("skill_hp_threshold") is not None:
                threshold_skill_used = True
                if config.get("true_damage") is not None:
                    skill_damage = config["true_damage"]
                    core_hp = max(0.0, core_hp - skill_damage)
                else:
                    skill_damage = config.get("skill_damage", 0) * (1 - stats["damage_reduction_pct"])
                    shield_absorbed = min(shield_hp, skill_damage)
                    shield_hp -= shield_absorbed
                    core_hp = max(0.0, core_hp - (skill_damage - shield_absorbed))
            else:
                skill_damage = config.get("true_damage", 0)
                core_hp = max(0.0, core_hp - skill_damage)
            player_hp = core_hp + shield_hp
            events.append({
                "time": now, "boss_hp": boss_hp, "player_hp": player_hp,
                "text": f"BOSS施放技能「{config.get('skill')}」，造成{skill_damage:g}{'真實' if config.get('true_damage') else ''}傷害！",
            })
            if core_hp <= 0:
                return {"victory": False, "duration": now, "events": events}
            next_skill = (
                next_skill + skill_interval if skill_interval else float("inf")
            )
        else:
            now = next_pet_skill
            pet_damage = 0.0
            pet_healing = 0.0
            if pet_element == "earth":
                amount = pet_level * 5
                if boss_element == "wood":
                    pet_healing = amount
                else:
                    pet_damage = amount * (1 - config.get("hero_damage_reduction", 0.0))
            elif pet_element == "fire":
                base_damage = 0 if boss_element == "water" else 600 if boss_element == "wood" else 300
                pet_damage = base_damage * (1 - config.get("hero_damage_reduction", 0.0))
            boss_hp = max(0.0, min(boss_max, boss_hp - pet_damage + pet_healing))
            events.append({
                "time": now,
                "boss_hp": boss_hp,
                "player_hp": player_hp,
                "text": (
                    f"{pet_skill['name']}造成{pet_damage:g}傷害"
                    if pet_damage else
                    f"{pet_skill['name']}使BOSS回復{pet_healing:g}HP"
                    if pet_healing else f"{pet_skill['name']}未造成傷害"
                ),
                "event_type": "pet_skill",
                "pet_skill": pet_skill["name"],
                "pet_element": pet_element,
                "damage": pet_damage,
                "healing": pet_healing,
            })
            if boss_hp <= 0:
                return {"victory": True, "duration": now, "events": events}
            next_pet_skill += pet_periodic_interval
    raise RuntimeError("戰鬥計算超出限制")
