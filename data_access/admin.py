"""Teacher-side persistence operations for student account administration."""


def reset_student_pin_record(db_connection, student_code, pin_salt, pin_hash):
    with db_connection() as db:
        db.execute(
            "UPDATE players SET pin_salt=?, pin_hash=?, failed_attempts=0, "
            "locked_until=0 WHERE student_code=?",
            (pin_salt, pin_hash, student_code),
        )


def update_student_real_name_record(db_connection, student_code, real_name):
    with db_connection() as db:
        db.execute(
            "UPDATE players SET real_name=? WHERE student_code=?",
            (real_name, student_code),
        )


def fetch_student_learning_detail(db_connection, student_code):
    with db_connection() as db:
        return db.execute(
            "SELECT hero_name, real_name, profile_json FROM players WHERE student_code=?",
            (student_code,),
        ).fetchone()


def fetch_student_question_rows(
    db_connection, student_code, errors_only=False, limit=200
):
    condition = "AND is_correct=0" if errors_only else ""
    safe_limit = max(1, int(limit))
    with db_connection() as db:
        return [
            dict(row)
            for row in db.execute(
                "SELECT unit_id AS 單元, question_text AS 題目, "
                "submitted_answer AS 學生答案, correct_answer AS 正確答案, "
                "is_correct AS 是否答對, combo_after AS 作答後連擊, "
                "elapsed_seconds AS 回合累計秒數, answered_at AS 作答時間 "
                f"FROM question_logs WHERE student_code=? {condition} "
                f"ORDER BY id DESC LIMIT {safe_limit}",
                (student_code,),
            ).fetchall()
        ]


def delete_student_record(db_connection, student_code):
    with db_connection() as db:
        db.execute("DELETE FROM players WHERE student_code=?", (student_code,))


def fetch_teacher_name(db_connection):
    with db_connection() as db:
        row = db.execute(
            "SELECT hero_name FROM players WHERE student_code='__TEACHER__'"
        ).fetchone()
    return row["hero_name"] if row else None


def fetch_recent_attempts(db_connection, limit=200):
    safe_limit = max(1, int(limit))
    with db_connection() as db:
        return [
            dict(row)
            for row in db.execute(
                "SELECT p.student_code AS 學生代碼, p.real_name AS 正式姓名, "
                "p.hero_name AS 勇者, a.unit_id AS 單元, a.stars AS 星級, "
                "a.max_combo AS 最高連擊, a.correct_count AS 答對題數, "
                "ROUND(CAST(a.average_seconds AS NUMERIC), 1) AS 平均每題秒數, "
                "a.finished_at AS 完成時間 FROM attempts a "
                "JOIN players p ON p.student_code=a.student_code "
                f"ORDER BY a.id DESC LIMIT {safe_limit}"
            ).fetchall()
        ]
