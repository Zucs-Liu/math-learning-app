import unittest

from game_logic.combat import simulate_battle
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


if __name__ == "__main__":
    unittest.main()
