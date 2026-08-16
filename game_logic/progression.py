"""Pure character growth, daily reset, and permanent-task rules."""


def add_experience(profile, amount):
    profile["exp"] += amount
    gained = 0
    while profile["level"] < 20 and profile["exp"] >= profile["level"] * 100:
        profile["exp"] -= profile["level"] * 100
        profile["level"] += 1
        gained += 1
    return gained


def highest_unlocked_chapter_id(profile):
    if profile.get("chapter4_boss_wins", 0) > 0:
        return "5"
    if profile.get("chapter3_boss_wins", 0) > 0:
        return "4"
    if profile.get("chapter2_boss_wins", 0) > 0:
        return "3"
    if profile.get("boss_wins", 0) > 0:
        return "2"
    return "1"


def sync_daily_task_periods(profile, daily_period, practice_period):
    changed = False
    if profile.get("daily_login_period") != daily_period:
        profile["daily_login_period"] = daily_period
        profile["daily_login_claimed"] = False
        changed = True
    if profile.get("daily_practice_period") != practice_period:
        profile["daily_practice_period"] = practice_period
        profile["daily_practice_count"] = 0
        profile["daily_practice_claimed"] = False
        changed = True
    return changed


def award_first_clear_ticket(profile, unit_id):
    if unit_id not in profile["ticket_rewarded_units"]:
        profile["ticket_rewarded_units"].append(unit_id)
        profile["sweep_tickets"] += 1
        return True
    return False


def build_permanent_task_definitions(chapters, units, chapter_unit_ids):
    tasks = []
    boss_keys = {
        "1": ("boss_wins", "elite_boss_wins"),
        "2": ("chapter2_boss_wins", "chapter2_elite_boss_wins"),
        "3": ("chapter3_boss_wins", "chapter3_elite_boss_wins"),
        "4": ("chapter4_boss_wins", "chapter4_elite_boss_wins"),
        "5": ("chapter5_boss_wins", "chapter5_elite_boss_wins"),
    }
    for chapter_id in chapters:
        for unit_id in chapter_unit_ids(chapter_id):
            tasks.append(
                {
                    "id": f"unit_{unit_id}",
                    "chapter": chapter_id,
                    "task_type": "unit",
                    "target_unit": unit_id,
                    "name": f"通過{unit_id}單元：{units[unit_id]['name']}",
                    "reward_text": "100金幣",
                    "coins": 100,
                    "complete": lambda profile, uid=unit_id: profile[
                        "unit_best_stars"
                    ].get(uid, 0)
                    > 0,
                }
            )
        normal_key, elite_key = boss_keys[chapter_id]
        tasks.extend(
            [
                {
                    "id": f"boss_{chapter_id}_normal",
                    "chapter": chapter_id,
                    "task_type": "boss",
                    "boss_type": "normal",
                    "name": f"通過{chapters[chapter_id]['number']}普通BOSS",
                    "reward_text": "300金幣＋1顆部位融煉石",
                    "coins": 300,
                    "stone_key": "slot_smelting_stones",
                    "complete": lambda profile, key=normal_key: profile.get(key, 0)
                    > 0,
                },
                {
                    "id": f"boss_{chapter_id}_elite",
                    "chapter": chapter_id,
                    "task_type": "boss",
                    "boss_type": "elite",
                    "name": f"通過{chapters[chapter_id]['number']}菁英BOSS",
                    "reward_text": "300金幣＋1顆基礎詞條融煉石",
                    "coins": 300,
                    "stone_key": "basic_affix_smelting_stones",
                    "complete": lambda profile, key=elite_key: profile.get(key, 0)
                    > 0,
                },
            ]
        )
    return tasks


def apply_task_reward(profile, task):
    profile["coins"] += task.get("coins", 0)
    if task.get("stone_key"):
        profile[task["stone_key"]] += 1


def visible_permanent_task_rows(profile, all_tasks, chapter_ids):
    claimed = set(profile["claimed_permanent_tasks"])
    visible = []
    for chapter_id in chapter_ids:
        if int(chapter_id) > 1:
            previous = str(int(chapter_id) - 1)
            previous_ids = {
                task["id"] for task in all_tasks if task["chapter"] == previous
            }
            if not previous_ids.issubset(claimed):
                break
        visible.extend(
            task for task in all_tasks if task["chapter"] == chapter_id
        )
    return visible


def boss_unlocked(profile, chapter_id, boss_type, chapter_unit_ids):
    if boss_type == "normal":
        return all(
            profile["unit_best_stars"].get(unit_id, 0) == 3
            for unit_id in chapter_unit_ids(chapter_id)
        )
    normal_wins_key = {
        "1": "boss_wins",
        "2": "chapter2_boss_wins",
        "3": "chapter3_boss_wins",
        "4": "chapter4_boss_wins",
        "5": "chapter5_boss_wins",
    }[chapter_id]
    return profile.get(normal_wins_key, 0) > 0
