import random
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).resolve().parent / "classroom_companion.db"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER NOT NULL UNIQUE,
                username TEXT,
                role TEXT NOT NULL
            )
            """
        )
        # Ensure AI columns exist on older databases (safe, idempotent migration)
        with get_connection() as conn:
            try:
                existing = conn.execute("PRAGMA table_info('assignments')").fetchall()
                existing_cols = {row['name'] for row in existing}
            except Exception:
                existing_cols = set()

            if 'ai_category' not in existing_cols:
                conn.execute("ALTER TABLE assignments ADD COLUMN ai_category TEXT")
            if 'ai_summary' not in existing_cols:
                conn.execute("ALTER TABLE assignments ADD COLUMN ai_summary TEXT")
            if 'ai_confidence' not in existing_cols:
                conn.execute("ALTER TABLE assignments ADD COLUMN ai_confidence REAL")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS classrooms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                teacher_id INTEGER NOT NULL,
                join_code TEXT NOT NULL UNIQUE
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS classroom_students (
                classroom_id INTEGER NOT NULL,
                student_id INTEGER NOT NULL,
                PRIMARY KEY (classroom_id, student_id),
                FOREIGN KEY (classroom_id) REFERENCES classrooms (id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS assignments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                classroom_id INTEGER NOT NULL,
                teacher_id INTEGER NOT NULL,
                student_id INTEGER NOT NULL,
                assignment_text TEXT NOT NULL,
                due_date TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'assigned',
                ai_category TEXT,
                ai_summary TEXT,
                ai_confidence REAL,
                FOREIGN KEY (classroom_id) REFERENCES classrooms (id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS assignment_progress (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                assignment_id INTEGER NOT NULL,
                student_id INTEGER NOT NULL,
                progress_text TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (assignment_id) REFERENCES assignments (id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS submissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                assignment_id INTEGER NOT NULL,
                student_id INTEGER NOT NULL,
                submission_text TEXT NOT NULL,
                submitted_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (assignment_id) REFERENCES assignments (id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                assignment_id INTEGER NOT NULL,
                teacher_id INTEGER NOT NULL,
                student_id INTEGER NOT NULL,
                feedback_text TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (assignment_id) REFERENCES assignments (id)
            )
            """
        )


def save_user(telegram_id: int, username: str | None, role: str) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO users (telegram_id, username, role)
            VALUES (?, ?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET
                username = excluded.username,
                role = excluded.role
            """,
            (telegram_id, username, role),
        )


def get_user_role(telegram_id: int) -> str | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT role FROM users WHERE telegram_id = ?",
            (telegram_id,),
        ).fetchone()
    return row["role"] if row else None


def _generate_join_code() -> str:
    return f"CLASS{random.randint(100, 999)}"


def create_classroom(teacher_id: int) -> tuple[int, str]:
    with get_connection() as conn:
        for _ in range(20):
            join_code = _generate_join_code()
            try:
                cursor = conn.execute(
                    """
                    INSERT INTO classrooms (teacher_id, join_code)
                    VALUES (?, ?)
                    """,
                    (teacher_id, join_code),
                )
                return cursor.lastrowid, join_code
            except sqlite3.IntegrityError:
                continue
    raise RuntimeError("Could not generate a unique join code")


def get_classroom_by_join_code(join_code: str) -> sqlite3.Row | None:
    with get_connection() as conn:
        return conn.execute(
            "SELECT id, teacher_id, join_code FROM classrooms WHERE join_code = ?",
            (join_code.upper(),),
        ).fetchone()


def is_student_in_classroom(student_id: int, classroom_id: int) -> bool:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT 1 FROM classroom_students
            WHERE student_id = ? AND classroom_id = ?
            """,
            (student_id, classroom_id),
        ).fetchone()
    return row is not None


def join_classroom(student_id: int, join_code: str) -> sqlite3.Row:
    classroom = get_classroom_by_join_code(join_code)
    if classroom is None:
        raise ValueError("invalid_code")
    if is_student_in_classroom(student_id, classroom["id"]):
        raise ValueError("already_joined")

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO classroom_students (classroom_id, student_id)
            VALUES (?, ?)
            """,
            (classroom["id"], student_id),
        )
    return classroom


def get_teacher_students(teacher_id: int) -> list[sqlite3.Row]:
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT c.join_code, u.username, cs.student_id
            FROM classrooms c
            JOIN classroom_students cs ON cs.classroom_id = c.id
            JOIN users u ON u.telegram_id = cs.student_id
            WHERE c.teacher_id = ? AND u.role = 'student'
            ORDER BY c.join_code, u.username
            """,
            (teacher_id,),
        ).fetchall()


def get_incomplete_assignments() -> list[sqlite3.Row]:
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT id, student_id, assignment_text, due_date, status
            FROM assignments
            WHERE status != 'completed'
            ORDER BY id
            """
        ).fetchall()


def get_teacher_assignments(teacher_id: int) -> list[sqlite3.Row]:
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT a.id, c.join_code, u.username, a.student_id,
                   a.assignment_text, a.status, a.due_date,
                   a.ai_category, a.ai_summary, a.ai_confidence
            FROM assignments a
            JOIN classrooms c ON c.id = a.classroom_id
            JOIN users u ON u.telegram_id = a.student_id
            WHERE a.teacher_id = ?
            ORDER BY c.join_code, a.id DESC
            """,
            (teacher_id,),
        ).fetchall()


def teacher_has_classroom(teacher_id: int) -> bool:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM classrooms WHERE teacher_id = ? LIMIT 1",
            (teacher_id,),
        ).fetchone()
    return row is not None


def find_student_for_teacher(
    teacher_id: int, student_name: str
) -> tuple[int, int] | None:
    name = student_name.strip().lstrip("@").lower()
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT c.id AS classroom_id, cs.student_id
            FROM classrooms c
            JOIN classroom_students cs ON cs.classroom_id = c.id
            JOIN users u ON u.telegram_id = cs.student_id
            WHERE c.teacher_id = ?
              AND u.role = 'student'
              AND LOWER(COALESCE(u.username, '')) = ?
            LIMIT 1
            """,
            (teacher_id, name),
        ).fetchone()
    if row is None:
        return None
    return row["classroom_id"], row["student_id"]


def get_teacher_student_activity(teacher_id: int, student_id: int) -> dict[str, Any]:
    with get_connection() as conn:
        assignments = conn.execute(
            """
            SELECT a.id, c.join_code, a.assignment_text,
                   a.due_date, a.status
            FROM assignments a
            JOIN classrooms c ON c.id = a.classroom_id
            WHERE a.teacher_id = ? AND a.student_id = ?
            ORDER BY a.id DESC
            """,
            (teacher_id, student_id),
        ).fetchall()

        assignment_ids = [row["id"] for row in assignments]
        progress_by_assignment: dict[int, list[dict[str, str]]] = {
            row["id"]: [] for row in assignments
        }
        submission_by_assignment: dict[int, list[dict[str, str]]] = {
            row["id"]: [] for row in assignments
        }

        if assignment_ids:
            placeholders = ",".join("?" for _ in assignment_ids)
            progress_rows = conn.execute(
                f"""
                SELECT assignment_id, progress_text, created_at
                FROM assignment_progress
                WHERE assignment_id IN ({placeholders})
                ORDER BY created_at ASC
                """,
                assignment_ids,
            ).fetchall()
            for row in progress_rows:
                progress_by_assignment[row["assignment_id"]].append(
                    {
                        "progress_text": row["progress_text"],
                        "created_at": row["created_at"],
                    }
                )

            submission_rows = conn.execute(
                f"""
                SELECT assignment_id, submission_text, submitted_at
                FROM submissions
                WHERE assignment_id IN ({placeholders})
                ORDER BY submitted_at DESC
                """,
                assignment_ids,
            ).fetchall()
            for row in submission_rows:
                submission_by_assignment[row["assignment_id"]].append(
                    {
                        "submission_text": row["submission_text"],
                        "submitted_at": row["submitted_at"],
                    }
                )

    return {
        "student_id": student_id,
        "assignments": [
            {
                "assignment_id": row["id"],
                "join_code": row["join_code"],
                "assignment_text": row["assignment_text"],
                "due_date": row["due_date"],
                "status": row["status"],
                "progress_updates": progress_by_assignment[row["id"]],
                "submissions": submission_by_assignment[row["id"]],
            }
            for row in assignments
        ],
    }


def normalize_due_date(date_str: str) -> str:
    value = date_str.strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    raise ValueError("invalid_date")


def parse_assignment_message(text: str) -> tuple[str, str, str]:
    student_name: str | None = None
    due_date_raw: str | None = None
    body_lines: list[str] = []

    for line in text.strip().splitlines():
        stripped = line.strip()
        student_match = re.match(r"(?i)^Student:\s*(.+)$", stripped)
        due_match = re.match(r"(?i)^Due:\s*(.+)$", stripped)
        if student_match:
            student_name = student_match.group(1).strip()
        elif due_match:
            due_date_raw = due_match.group(1).strip()
        else:
            body_lines.append(line)

    assignment_text = "\n".join(body_lines).strip()
    if not assignment_text or not student_name or not due_date_raw:
        raise ValueError("invalid_format")

    due_date = normalize_due_date(due_date_raw)
    return assignment_text, student_name, due_date


def create_assignment(
    classroom_id: int,
    teacher_id: int,
    student_id: int,
    assignment_text: str,
    due_date: str,
) -> int:
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO assignments (
                classroom_id, teacher_id, student_id,
                assignment_text, due_date, status
            )
            VALUES (?, ?, ?, ?, ?, 'assigned')
            """,
            (
                classroom_id,
                teacher_id,
                student_id,
                assignment_text,
                due_date,
            ),
        )
        return cursor.lastrowid


def get_latest_active_assignment(student_id: int) -> sqlite3.Row | None:
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT id, teacher_id, assignment_text, due_date, status
            FROM assignments
            WHERE student_id = ? AND status IN ('assigned', 'in_progress')
            ORDER BY id DESC
            LIMIT 1
            """,
            (student_id,),
        ).fetchone()


def save_assignment_progress(
    assignment_id: int, student_id: int, progress_text: str
) -> int:
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO assignment_progress (
                assignment_id, student_id, progress_text
            )
            VALUES (?, ?, ?)
            """,
            (assignment_id, student_id, progress_text),
        )
        conn.execute(
            """
            UPDATE assignments
            SET status = 'in_progress'
            WHERE id = ? AND student_id = ? AND status IN ('assigned', 'in_progress')
            """,
            (assignment_id, student_id),
        )
        return cursor.lastrowid


def save_submission(
    assignment_id: int, student_id: int, submission_text: str
) -> int:
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO submissions (
                assignment_id, student_id, submission_text
            )
            VALUES (?, ?, ?)
            """,
            (assignment_id, student_id, submission_text),
        )
        conn.execute(
            """
            UPDATE assignments
            SET status = 'completed'
            WHERE id = ? AND student_id = ?
            """,
            (assignment_id, student_id),
        )
        return cursor.lastrowid


def get_latest_submission_for_teacher(teacher_id: int) -> sqlite3.Row | None:
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT s.id AS submission_id, s.assignment_id, s.student_id,
                   s.submission_text, s.submitted_at,
                   a.assignment_text, a.due_date
            FROM submissions s
            JOIN assignments a ON a.id = s.assignment_id
            WHERE a.teacher_id = ?
            ORDER BY s.id DESC
            LIMIT 1
            """,
            (teacher_id,),
        ).fetchone()


def get_submission_for_teacher(
    teacher_id: int, submission_id: int
) -> sqlite3.Row | None:
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT s.id AS submission_id, s.assignment_id, s.student_id,
                   s.submission_text, s.submitted_at,
                   a.assignment_text, a.due_date
            FROM submissions s
            JOIN assignments a ON a.id = s.assignment_id
            WHERE a.teacher_id = ? AND s.id = ?
            """,
            (teacher_id, submission_id),
        ).fetchone()


def save_feedback(
    assignment_id: int,
    teacher_id: int,
    student_id: int,
    feedback_text: str,
) -> int:
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO feedback (
                assignment_id, teacher_id, student_id, feedback_text
            )
            VALUES (?, ?, ?, ?)
            """,
            (assignment_id, teacher_id, student_id, feedback_text),
        )
        return cursor.lastrowid


def get_latest_progress_for_assignment(assignment_id: int) -> sqlite3.Row | None:
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT progress_text, created_at
            FROM assignment_progress
            WHERE assignment_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (assignment_id,),
        ).fetchone()


def update_assignment_ai(
    assignment_id: int,
    ai_category: str | None,
    ai_summary: str | None,
    ai_confidence: float | None,
) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE assignments
            SET ai_category = ?, ai_summary = ?, ai_confidence = ?
            WHERE id = ?
            """,
            (ai_category, ai_summary, ai_confidence, assignment_id),
        )
