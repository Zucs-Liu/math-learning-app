"""Persistence operations for quiz history, boss records, and rankings."""


RANKING_TABLES = {
    ("1", "normal"): "rankings",
    ("1", "elite"): "elite_rankings",
    ("2", "normal"): "chapter2_rankings",
    ("2", "elite"): "chapter2_elite_rankings",
    ("3", "normal"): "chapter3_rankings",
    ("3", "elite"): "chapter3_elite_rankings",
    ("4", "normal"): "chapter4_rankings",
    ("4", "elite"): "chapter4_elite_rankings",
    ("5", "normal"): "chapter5_rankings",
    ("5", "elite"): "chapter5_elite_rankings",
    ("6", "normal"): "chapter6_rankings",
    ("6", "elite"): "chapter6_elite_rankings",
}


def ranking_table(chapter_id, boss_type):
    """Return a fixed, trusted table name; invalid combinations fail early."""
    return RANKING_TABLES[(str(chapter_id), boss_type)]


def insert_attempt(
    db_connection,
    student_code,
    unit_id,
    stars,
    max_combo,
    correct_count,
    elapsed_seconds,
    average_seconds,
    finished_at,
):
    with db_connection() as db:
        db.execute(
            "INSERT INTO attempts(student_code, unit_id, stars, max_combo, correct_count, "
            "elapsed_seconds, average_seconds, finished_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
            (
                student_code,
                unit_id,
                stars,
                max_combo,
                correct_count,
                elapsed_seconds,
                average_seconds,
                finished_at,
            ),
        )


def insert_question_log(db_connection, student_code, unit_id, answer_row):
    with db_connection() as db:
        db.execute(
            "INSERT INTO question_logs(student_code, unit_id, question_text, "
            "submitted_answer, correct_answer, is_correct, combo_after, "
            "elapsed_seconds, answered_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                student_code,
                unit_id,
                answer_row["question_text"],
                answer_row["submitted_answer"],
                answer_row["correct_answer"],
                1 if answer_row["is_correct"] else 0,
                answer_row["combo_after"],
                answer_row["elapsed_seconds"],
                answer_row["answered_at"],
            ),
        )


def save_best_boss_record(
    db_connection,
    student_code,
    hero_name,
    level,
    clear_time,
    achieved_at,
    boss_type="normal",
    chapter_id="1",
):
    table = ranking_table(chapter_id, boss_type)
    with db_connection() as db:
        row = db.execute(
            f"SELECT clear_time FROM {table} WHERE student_code=?", (student_code,)
        ).fetchone()
        if row and clear_time >= row["clear_time"]:
            return False
        db.execute(
            f"INSERT INTO {table}(student_code, hero_name, level, clear_time, achieved_at) "
            "VALUES(?, ?, ?, ?, ?) ON CONFLICT(student_code) DO UPDATE SET "
            "hero_name=excluded.hero_name, level=excluded.level, "
            "clear_time=excluded.clear_time, achieved_at=excluded.achieved_at",
            (student_code, hero_name, level, round(clear_time, 2), achieved_at),
        )
    return True


def fetch_boss_ranking_rows(db_connection, boss_type="normal", chapter_id="1"):
    table = ranking_table(chapter_id, boss_type)
    with db_connection() as db:
        return db.execute(
            "SELECT r.student_code AS 學生代碼, p.real_name AS 正式姓名, "
            "r.hero_name AS 玩家, r.level AS 等級, r.clear_time AS 通關秒數, "
            f"r.achieved_at AS 日期, p.profile_json FROM {table} r "
            "JOIN players p ON p.student_code=r.student_code ORDER BY r.clear_time ASC"
        ).fetchall()


def fetch_character_profiles(db_connection):
    with db_connection() as db:
        return db.execute(
            "SELECT student_code, hero_name, profile_json FROM players "
            "WHERE student_code <> '__TEACHER__'"
        ).fetchall()


def fetch_student_rows(db_connection):
    with db_connection() as db:
        return [
            dict(row)
            for row in db.execute(
                "SELECT student_code AS 學生代碼, real_name AS 正式姓名, "
                "hero_name AS 勇者名稱, created_at AS 建立時間 FROM players "
                "WHERE student_code <> '__TEACHER__' ORDER BY created_at"
            ).fetchall()
        ]
