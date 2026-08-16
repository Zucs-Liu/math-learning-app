"""Persistence operations for feedback, mailbox messages, and announcements."""


def create_feedback_record(db_connection, student_code, category, message, created_at):
    with db_connection() as db:
        db.execute(
            "INSERT INTO game_feedback(student_code, category, message, created_at) "
            "VALUES(?, ?, ?, ?)",
            (student_code, category, message, created_at),
        )


def create_mail_record(
    db_connection, student_code, subject, message, reward_json, claimed, created_at
):
    with db_connection() as db:
        db.execute(
            "INSERT INTO mailbox(student_code, subject, message, reward_json, "
            "is_read, is_claimed, created_at) VALUES(?, ?, ?, ?, 0, ?, ?)",
            (student_code, subject, message, reward_json, 1 if claimed else 0, created_at),
        )


def fetch_mail_rows(db_connection, student_code):
    with db_connection() as db:
        return [
            dict(row)
            for row in db.execute(
                "SELECT id, subject, message, reward_json, is_read, is_claimed, created_at "
                "FROM mailbox WHERE student_code=? "
                "ORDER BY is_read ASC, is_claimed ASC, id DESC",
                (student_code,),
            ).fetchall()
        ]


def count_unread_mail(db_connection, student_code):
    with db_connection() as db:
        row = db.execute(
            "SELECT COUNT(*) AS count FROM mailbox WHERE student_code=? AND is_read=0",
            (student_code,),
        ).fetchone()
    return int(row["count"] or 0)


def set_mail_read(db_connection, mail_id, student_code):
    with db_connection() as db:
        db.execute(
            "UPDATE mailbox SET is_read=1 WHERE id=? AND student_code=?",
            (mail_id, student_code),
        )


def set_all_mail_read(db_connection, student_code):
    with db_connection() as db:
        result = db.execute(
            "UPDATE mailbox SET is_read=1 WHERE student_code=? AND is_read=0",
            (student_code,),
        )
    return max(0, int(result.rowcount or 0))


def fetch_mail_reward(db_connection, mail_id, student_code):
    with db_connection() as db:
        return db.execute(
            "SELECT reward_json, is_claimed FROM mailbox WHERE id=? AND student_code=?",
            (mail_id, student_code),
        ).fetchone()


def set_mail_claimed(db_connection, mail_id, student_code):
    with db_connection() as db:
        db.execute(
            "UPDATE mailbox SET is_read=1, is_claimed=1 WHERE id=? AND student_code=?",
            (mail_id, student_code),
        )


def fetch_feedback_rows(db_connection):
    with db_connection() as db:
        return [
            dict(row)
            for row in db.execute(
                "SELECT f.id AS 編號, f.student_code AS 學生代碼, "
                "p.real_name AS 正式姓名, p.hero_name AS 勇者名稱, "
                "f.category AS 問題分類, f.message AS 回饋內容, "
                "f.created_at AS 送出時間, f.replied_at AS 回覆時間 "
                "FROM game_feedback f JOIN players p ON p.student_code=f.student_code "
                "ORDER BY f.id DESC"
            ).fetchall()
        ]


def set_feedback_replied(db_connection, feedback_id, replied_at):
    with db_connection() as db:
        db.execute(
            "UPDATE game_feedback SET replied_at=? WHERE id=?",
            (replied_at, feedback_id),
        )


def fetch_announcement_rows(db_connection, active_only=False):
    sql = "SELECT id, title, content, is_active, created_at FROM announcements"
    if active_only:
        sql += " WHERE is_active=1"
    sql += " ORDER BY id DESC"
    with db_connection() as db:
        return [dict(row) for row in db.execute(sql).fetchall()]


def create_announcement_record(db_connection, title, content, created_at):
    with db_connection() as db:
        db.execute(
            "INSERT INTO announcements(title, content, is_active, created_at) "
            "VALUES(?, ?, 1, ?)",
            (title, content, created_at),
        )


def set_announcement_status(db_connection, announcement_id, is_active):
    with db_connection() as db:
        db.execute(
            "UPDATE announcements SET is_active=? WHERE id=?",
            (1 if is_active else 0, announcement_id),
        )


def update_announcement_record(
    db_connection, announcement_id, title, content, created_at
):
    with db_connection() as db:
        db.execute(
            "UPDATE announcements SET title=?, content=?, is_active=1, created_at=? "
            "WHERE id=?",
            (title, content, created_at, announcement_id),
        )


def delete_announcement_record(db_connection, announcement_id):
    with db_connection() as db:
        db.execute("DELETE FROM announcements WHERE id=?", (announcement_id,))
