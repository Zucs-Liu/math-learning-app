import unittest

from game_logic.combat import (
    battle_passive_effects,
    merge_simultaneous_action_event,
    simulate_battle,
)
from game_logic.pets import element_matchup


def combat_stats(attack_element):
    return {
        "hp": 1000.0,
        "attack": 100.0,
        "defense": 10.0,
        "attack_speed": 1.0,
        "boss_hp_reduction": 0.0,
        "first_hit_percent": 0.0,
        "boss_damage_pct": 0.0,
        "damage_reduction_pct": 0.0,
        "critical_rate": 0.0,
        "critical_damage": 0.0,
        "shield_pct": 0.0,
        "boss_attack_slow_pct": 0.0,
        "attack_element": attack_element,
        "pet_skill": None,
    }


class ElementCombatTests(unittest.TestCase):
    def test_matchup_states(self):
        self.assertEqual(element_matchup("dark", "light"), ("advantage", 1.15))
        self.assertEqual(element_matchup("wood", "fire"), ("disadvantage", 0.85))
        self.assertEqual(element_matchup("wood", "light"), ("neutral", 1.0))

    def test_non_three_star_pet_element_changes_normal_attack(self):
        advantaged = simulate_battle(combat_stats("dark"), "normal", "4")
        disadvantaged = simulate_battle(combat_stats("wood"), "elite", "3")
        self.assertIn("造成115.0傷害", advantaged["events"][1]["text"])
        self.assertIn("造成85.0傷害", disadvantaged["events"][1]["text"])

    def test_same_time_light_pet_event_preserves_hero_action(self):
        visible = [
            {"time": 0.0, "text": "戰鬥開始", "boss_hp": 1200, "player_hp": 100},
            {"time": 0.0, "text": "勇者第1擊造成100.0傷害", "boss_hp": 1100, "player_hp": 100},
            {
                "time": 0.0,
                "text": "大橘為重造成25真實傷害",
                "boss_hp": 1075,
                "player_hp": 100,
                "event_type": "pet_skill",
                "damage": 25,
            },
        ]
        merged = merge_simultaneous_action_event(visible)
        self.assertEqual(merged["simultaneous_hero_text"], visible[1]["text"])
        self.assertEqual(merged["boss_hp"], 1075)

    def test_passive_effects_are_assigned_to_modified_health_bar(self):
        stats = combat_stats("water")
        stats["pet_skill"] = {"name": "魚躍龍門", "element": "water", "level": 3}
        effects = battle_passive_effects(stats, "normal", "3")
        self.assertEqual(effects["player"], [])
        self.assertEqual(effects["boss"][0]["text"], "魚躍龍門：BOSS 最大 HP -10%")

        stats["pet_skill"] = {"name": "心有餘力不足", "element": "dark", "level": 3}
        effects = battle_passive_effects(stats, "elite", "5")
        self.assertIn("勇者傷害 +10%", effects["player"][0]["text"])
        self.assertIn("勇者傷害 -40%", effects["player"][1]["text"])


if __name__ == "__main__":
    unittest.main()
