"""Deterministic boss battle calculation.

The simulator returns only data. Streamlit rendering, animation timing and
database rewards stay in ``app.py``.
"""

from game_data.config import BOSS_CONFIGS


def simulate_battle(stats, boss_type, chapter_id):
    config = BOSS_CONFIGS[f"{chapter_id}_{boss_type}"]
    elite_boss_reduction = stats["boss_hp_reduction"] if boss_type == "elite" else 0.0
    elite_boss_damage = stats["boss_damage_pct"] if boss_type == "elite" else 0.0
    elite_boss_slow = stats["boss_attack_slow_pct"] if boss_type == "elite" else 0.0
    elite_first_hit = stats["first_hit_percent"] if boss_type == "elite" else 0.0
    boss_max = config["hp"] * (1 - elite_boss_reduction)
    boss_hp = boss_max
    core_hp = stats["hp"]
    shield_hp = stats["hp"] * stats["shield_pct"]
    player_hp = core_hp + shield_hp
    effective_attack_speed = max(
        0.1, stats["attack_speed"] - config.get("hero_speed_reduction", 0.0)
    )
    hero_interval = 1 / effective_attack_speed
    boss_interval = config["interval"] * (1 + elite_boss_slow)
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
    hero_hits = boss_hits = 0
    events = [{"time": 0.0, "boss_hp": boss_hp, "player_hp": player_hp, "text": "戰鬥開始"}]
    if config.get("skill_at_start"):
        events.append({
            "time": 0.0, "boss_hp": boss_hp, "player_hp": player_hp,
            "text": (
                f"BOSS施放技能「{config['skill']}」："
                f"勇者造成的傷害降低{config.get('hero_damage_reduction', 0):.0%}"
            ),
        })
    for _ in range(10000):
        if next_hero <= next_boss and next_hero <= next_skill:
            now = next_hero
            hero_hits += 1
            is_critical = bool(critical_every and hero_hits % critical_every == 0)
            damage_multiplier = max(
                0.0,
                1 + elite_boss_damage - config.get("hero_damage_reduction", 0.0),
            )
            normal_damage = stats["attack"] * damage_multiplier
            if is_critical:
                normal_damage *= 1.5 + stats["critical_damage"]
            damage = normal_damage + (boss_max * elite_first_hit if hero_hits == 1 else 0)
            boss_hp = max(0.0, boss_hp - damage)
            critical_text = "，暴擊！" if is_critical else ""
            events.append({"time": now, "boss_hp": boss_hp, "player_hp": player_hp, "text": f"勇者第{hero_hits}擊{critical_text}造成{damage:.1f}傷害"})
            if boss_hp <= 0:
                return {"victory": True, "duration": now, "events": events}
            if (
                config.get("skill_hp_threshold") is not None
                and not threshold_skill_used
                and boss_hp <= boss_max * config["skill_hp_threshold"]
            ):
                next_skill = now
            next_hero += hero_interval
        elif next_boss <= next_skill:
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
        else:
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
    raise RuntimeError("戰鬥計算超出限制")
