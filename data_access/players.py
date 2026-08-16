"""Raw persistence operations for player accounts and saved profiles."""


def player_exists(db_connection, student_code):
    with db_connection() as db:
        return db.execute(
            "SELECT 1 FROM players WHERE student_code=?", (student_code,)
        ).fetchone() is not None


def create_player_record(
    db_connection,
    use_postgres,
    real_name,
    hero_name,
    pin_salt,
    pin_hash,
    profile_json,
    created_at,
    code_factory,
):
    """Atomically reserve the next student code and insert one player."""
    with db_connection() as db:
        db.execute("BEGIN IMMEDIATE")
        if use_postgres:
            db.execute(
                "INSERT INTO settings(key, value) VALUES('student_counter', '0') "
                "ON CONFLICT(key) DO NOTHING"
            )
        lock_suffix = " FOR UPDATE" if use_postgres else ""
        row = db.execute(
            f"SELECT value FROM settings WHERE key='student_counter'{lock_suffix}"
        ).fetchone()
        duplicate = db.execute(
            "SELECT 1 FROM players WHERE LOWER(hero_name)=LOWER(?) "
            "AND student_code <> '__TEACHER__' LIMIT 1",
            (hero_name,),
        ).fetchone()
        if duplicate:
            raise ValueError("這個勇者名稱已經有人使用，請換一個名稱。")
        number = int(row["value"]) + 1 if row else 1
        student_code = code_factory(number)
        db.execute(
            "INSERT INTO players(student_code, hero_name, real_name, pin_salt, pin_hash, "
            "profile_json, created_at) VALUES(?, ?, ?, ?, ?, ?, ?)",
            (
                student_code,
                hero_name,
                real_name,
                pin_salt,
                pin_hash,
                profile_json,
                created_at,
            ),
        )
        db.execute(
            "INSERT INTO settings(key, value) VALUES('student_counter', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(number),),
        )
    return student_code


def fetch_teacher_profile_json(db_connection):
    with db_connection() as db:
        return db.execute(
            "SELECT profile_json FROM players WHERE student_code='__TEACHER__'"
        ).fetchone()


def save_teacher_profile(db_connection, hero_name, profile_json):
    with db_connection() as db:
        db.execute(
            "UPDATE players SET hero_name=?, profile_json=? WHERE student_code='__TEACHER__'",
            (hero_name, profile_json),
        )


def create_teacher_record(
    db_connection, hero_name, pin_salt, pin_hash, profile_json, created_at
):
    with db_connection() as db:
        db.execute(
            "INSERT INTO players(student_code, hero_name, pin_salt, pin_hash, "
            "profile_json, created_at) VALUES('__TEACHER__', ?, ?, ?, ?, ?)",
            (hero_name, pin_salt, pin_hash, profile_json, created_at),
        )


def fetch_login_player(db_connection, student_code):
    with db_connection() as db:
        return db.execute(
            "SELECT * FROM players WHERE student_code=?", (student_code,)
        ).fetchone()


def clear_login_failures(db_connection, student_code):
    with db_connection() as db:
        db.execute(
            "UPDATE players SET failed_attempts=0, locked_until=0 WHERE student_code=?",
            (student_code,),
        )


def record_login_failure(db_connection, student_code, failed_attempts, locked_until):
    with db_connection() as db:
        db.execute(
            "UPDATE players SET failed_attempts=?, locked_until=? WHERE student_code=?",
            (failed_attempts, locked_until, student_code),
        )


def fetch_profile_row(db_connection, student_code):
    with db_connection() as db:
        return db.execute(
            "SELECT hero_name, profile_json FROM players WHERE student_code=?",
            (student_code,),
        ).fetchone()


def update_profile_record(db_connection, student_code, hero_name, profile_json):
    with db_connection() as db:
        db.execute(
            "UPDATE players SET hero_name=?, profile_json=? WHERE student_code=?",
            (hero_name, profile_json, student_code),
        )
