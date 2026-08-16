"""Database schema creation and backward-compatible column migrations."""


def initialize_schema(db_connection, use_postgres):
    """Create every application table and add columns required by older data."""
    serial_primary_key = "BIGSERIAL PRIMARY KEY" if use_postgres else "INTEGER PRIMARY KEY AUTOINCREMENT"
    with db_connection() as db:
        db.executescript(
            f"""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS players (
                student_code TEXT PRIMARY KEY,
                hero_name TEXT NOT NULL,
                real_name TEXT NOT NULL DEFAULT '',
                pin_salt TEXT NOT NULL,
                pin_hash TEXT NOT NULL,
                profile_json TEXT NOT NULL,
                failed_attempts INTEGER NOT NULL DEFAULT 0,
                locked_until REAL NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS rankings (
                student_code TEXT PRIMARY KEY,
                hero_name TEXT NOT NULL,
                level INTEGER NOT NULL,
                clear_time REAL NOT NULL,
                achieved_at TEXT NOT NULL,
                FOREIGN KEY(student_code) REFERENCES players(student_code) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS elite_rankings (
                student_code TEXT PRIMARY KEY,
                hero_name TEXT NOT NULL,
                level INTEGER NOT NULL,
                clear_time REAL NOT NULL,
                achieved_at TEXT NOT NULL,
                FOREIGN KEY(student_code) REFERENCES players(student_code) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS chapter2_rankings (
                student_code TEXT PRIMARY KEY, hero_name TEXT NOT NULL, level INTEGER NOT NULL,
                clear_time REAL NOT NULL, achieved_at TEXT NOT NULL,
                FOREIGN KEY(student_code) REFERENCES players(student_code) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS chapter2_elite_rankings (
                student_code TEXT PRIMARY KEY, hero_name TEXT NOT NULL, level INTEGER NOT NULL,
                clear_time REAL NOT NULL, achieved_at TEXT NOT NULL,
                FOREIGN KEY(student_code) REFERENCES players(student_code) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS chapter3_rankings (
                student_code TEXT PRIMARY KEY, hero_name TEXT NOT NULL, level INTEGER NOT NULL,
                clear_time REAL NOT NULL, achieved_at TEXT NOT NULL,
                FOREIGN KEY(student_code) REFERENCES players(student_code) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS chapter3_elite_rankings (
                student_code TEXT PRIMARY KEY, hero_name TEXT NOT NULL, level INTEGER NOT NULL,
                clear_time REAL NOT NULL, achieved_at TEXT NOT NULL,
                FOREIGN KEY(student_code) REFERENCES players(student_code) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS chapter4_rankings (
                student_code TEXT PRIMARY KEY, hero_name TEXT NOT NULL, level INTEGER NOT NULL,
                clear_time REAL NOT NULL, achieved_at TEXT NOT NULL,
                FOREIGN KEY(student_code) REFERENCES players(student_code) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS chapter4_elite_rankings (
                student_code TEXT PRIMARY KEY, hero_name TEXT NOT NULL, level INTEGER NOT NULL,
                clear_time REAL NOT NULL, achieved_at TEXT NOT NULL,
                FOREIGN KEY(student_code) REFERENCES players(student_code) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS chapter5_rankings (
                student_code TEXT PRIMARY KEY, hero_name TEXT NOT NULL, level INTEGER NOT NULL,
                clear_time REAL NOT NULL, achieved_at TEXT NOT NULL,
                FOREIGN KEY(student_code) REFERENCES players(student_code) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS chapter5_elite_rankings (
                student_code TEXT PRIMARY KEY, hero_name TEXT NOT NULL, level INTEGER NOT NULL,
                clear_time REAL NOT NULL, achieved_at TEXT NOT NULL,
                FOREIGN KEY(student_code) REFERENCES players(student_code) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS attempts (
                id {serial_primary_key},
                student_code TEXT NOT NULL,
                unit_id TEXT NOT NULL,
                stars INTEGER NOT NULL,
                max_combo INTEGER NOT NULL,
                correct_count INTEGER NOT NULL,
                elapsed_seconds REAL NOT NULL DEFAULT 0,
                average_seconds REAL NOT NULL DEFAULT 0,
                finished_at TEXT NOT NULL,
                FOREIGN KEY(student_code) REFERENCES players(student_code) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS question_logs (
                id {serial_primary_key},
                student_code TEXT NOT NULL,
                unit_id TEXT NOT NULL,
                question_text TEXT NOT NULL,
                submitted_answer REAL NOT NULL,
                correct_answer REAL NOT NULL,
                is_correct INTEGER NOT NULL,
                combo_after INTEGER NOT NULL,
                elapsed_seconds REAL NOT NULL DEFAULT 0,
                answered_at TEXT NOT NULL,
                FOREIGN KEY(student_code) REFERENCES players(student_code) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS game_feedback (
                id {serial_primary_key},
                student_code TEXT NOT NULL,
                category TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL,
                replied_at TEXT,
                FOREIGN KEY(student_code) REFERENCES players(student_code) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS mailbox (
                id {serial_primary_key},
                student_code TEXT NOT NULL,
                subject TEXT NOT NULL,
                message TEXT NOT NULL,
                reward_json TEXT,
                is_read INTEGER NOT NULL DEFAULT 0,
                is_claimed INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY(student_code) REFERENCES players(student_code) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS announcements (
                id {serial_primary_key},
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );
            """
        )
        db.execute("INSERT OR IGNORE INTO settings(key, value) VALUES('registration_enabled', '1')")
        if use_postgres:
            db.execute("ALTER TABLE attempts ADD COLUMN IF NOT EXISTS elapsed_seconds REAL NOT NULL DEFAULT 0")
            db.execute("ALTER TABLE attempts ADD COLUMN IF NOT EXISTS average_seconds REAL NOT NULL DEFAULT 0")
            db.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS real_name TEXT NOT NULL DEFAULT ''")
            db.execute("ALTER TABLE game_feedback ADD COLUMN IF NOT EXISTS replied_at TEXT")
            db.execute("ALTER TABLE question_logs ALTER COLUMN submitted_answer TYPE DOUBLE PRECISION USING submitted_answer::DOUBLE PRECISION")
            db.execute("ALTER TABLE question_logs ALTER COLUMN correct_answer TYPE DOUBLE PRECISION USING correct_answer::DOUBLE PRECISION")
        else:
            attempt_columns = {
                row["name"] for row in db.execute("PRAGMA table_info(attempts)").fetchall()
            }
            if "elapsed_seconds" not in attempt_columns:
                db.execute("ALTER TABLE attempts ADD COLUMN elapsed_seconds REAL NOT NULL DEFAULT 0")
            if "average_seconds" not in attempt_columns:
                db.execute("ALTER TABLE attempts ADD COLUMN average_seconds REAL NOT NULL DEFAULT 0")
            player_columns = {
                row["name"] for row in db.execute("PRAGMA table_info(players)").fetchall()
            }
            if "real_name" not in player_columns:
                db.execute("ALTER TABLE players ADD COLUMN real_name TEXT NOT NULL DEFAULT ''")
            feedback_columns = {
                row["name"] for row in db.execute("PRAGMA table_info(game_feedback)").fetchall()
            }
            if "replied_at" not in feedback_columns:
                db.execute("ALTER TABLE game_feedback ADD COLUMN replied_at TEXT")
    return True
