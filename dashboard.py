import streamlit as st
from db import get_connection


def format_assignment_rows(rows):
    def ai_insight_value(row):
        ai_summary = row["ai_summary"] if "ai_summary" in row.keys() else None
        if ai_summary:
            return ai_summary

        latest_progress = row["latest_progress"] if "latest_progress" in row.keys() else None
        if latest_progress:
            short_progress = latest_progress if len(latest_progress) <= 70 else latest_progress[:67] + "..."
            return f"Latest progress: {short_progress}"

        return "No progress yet"

    return [
        {
            "Student": row["username"],
            "Assignment": row["assignment_text"],
            "Status": row["status"],
            "Due Date": row["due_date"],
            "AI Summary": ai_insight_value(row),
        }
        for row in rows
    ]


def format_student_rows(rows):
    return [
        {
            "Assignment": row["assignment_text"],
            "Status": row["status"],
            "Due Date": row["due_date"],
            "Latest Feedback": row["latest_feedback"] or "No feedback yet",
        }
        for row in rows
    ]


def get_teacher_student_options(teacher_id):
    with get_connection() as conn:
        students = conn.execute(
            """
            SELECT DISTINCT u.username, u.telegram_id
            FROM users u
            JOIN assignments a ON a.student_id = u.telegram_id
            WHERE a.teacher_id = ?
            ORDER BY lower(u.username)
            """,
            (teacher_id,),
        ).fetchall()
    return [("All students", None)] + [
        (row["username"], row["telegram_id"]) for row in students
    ]


def get_student_teacher_options(student_id):
    with get_connection() as conn:
        teachers = conn.execute(
            """
            SELECT DISTINCT u.username, u.telegram_id
            FROM users u
            JOIN assignments a ON a.teacher_id = u.telegram_id
            WHERE a.student_id = ?
            ORDER BY lower(u.username)
            """,
            (student_id,),
        ).fetchall()
    return [("All teachers", None)] + [
        (row["username"], row["telegram_id"]) for row in teachers
    ]


def reset_dashboard():
    st.session_state.role = None
    st.session_state.username = ""
    st.session_state.username_input = ""
    st.session_state.teacher_student_filter = "All students"
    st.session_state.student_teacher_filter = "All teachers"


def render_welcome():
    st.subheader("Welcome to Classroom Companion")
    st.write(
        "Classroom Companion is a lightweight dashboard for viewing assignment and feedback data "
        "from the existing SQLite database. Use the sidebar to select your role and username, "
        "then explore assignment insights on the main screen."
    )
    st.markdown(
        "- **Teacher Dashboard:** view all assigned work, current status, due dates, and student progress summaries."
        "\n- **Student Dashboard:** view your active assignments, status, due dates, and the latest teacher feedback."
        "\n- **AI progress signals:** when available, assignments include concise AI-based progress summaries from stored classifications."
    )
    st.info(
        "Start by choosing Teacher or Student in the sidebar. Then enter your username and press Show dashboard."
    )


def main():
    st.set_page_config(page_title="Classroom Companion Dashboard", layout="wide")
    st.title("Classroom Companion")

    if "role" not in st.session_state:
        st.session_state.role = None
    if "username" not in st.session_state:
        st.session_state.username = ""
    if "username_input" not in st.session_state:
        st.session_state.username_input = ""
    if "teacher_student_filter" not in st.session_state:
        st.session_state.teacher_student_filter = "All students"
    if "student_teacher_filter" not in st.session_state:
        st.session_state.student_teacher_filter = "All teachers"

    st.sidebar.header("Dashboard Controls")
    if st.session_state.role is None:
        if st.sidebar.button("Teacher"):
            st.session_state.role = "teacher"
            st.session_state.username_input = ""
            st.session_state.username = ""
        if st.sidebar.button("Student"):
            st.session_state.role = "student"
            st.session_state.username_input = ""
            st.session_state.username = ""

        render_welcome()
        return

    if st.sidebar.button("Back"):
        reset_dashboard()
        render_welcome()
        return

    st.sidebar.subheader(f"{st.session_state.role.title()} Login")
    st.session_state.username_input = st.sidebar.text_input(
        "Username",
        value=st.session_state.username_input,
        key="sidebar_username_input",
    )

    if st.sidebar.button("Show dashboard"):
        st.session_state.username = st.session_state.username_input.strip()

    if not st.session_state.username:
        render_welcome()
        st.sidebar.info(f"Enter a {st.session_state.role} username and click Show dashboard.")
        return

    if st.session_state.role == "teacher":
        username_value = st.session_state.username.lstrip("@").lower()
        with get_connection() as conn:
            teacher_row = conn.execute(
                "SELECT telegram_id FROM users WHERE lower(username) = ? AND role = 'teacher'",
                (username_value,),
            ).fetchone()

        if teacher_row is None:
            st.sidebar.error("No teacher found with that username.")
            return

        student_options = get_teacher_student_options(teacher_row["telegram_id"])
        selected_student = st.sidebar.selectbox(
            "Filter by student",
            [label for label, _ in student_options],
            index=0,
            key="teacher_student_filter",
        )
        selected_student_id = next(
            (student_id for label, student_id in student_options if label == selected_student),
            None,
        )

        query = """
            SELECT a.id, u.username, a.assignment_text, a.status, a.due_date,
                   a.ai_summary,
                   (SELECT progress_text
                    FROM assignment_progress ap
                    WHERE ap.assignment_id = a.id
                    ORDER BY ap.created_at DESC
                    LIMIT 1) AS latest_progress
            FROM assignments a
            JOIN users u ON u.telegram_id = a.student_id
            WHERE a.teacher_id = ?
            """
        params = [teacher_row["telegram_id"]]
        if selected_student_id is not None:
            query += " AND a.student_id = ?"
            params.append(selected_student_id)
        query += "\n                ORDER BY a.due_date ASC\n                """
        with get_connection() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()

        if not rows:
            st.info("No assignments found for this teacher.")
        else:
            st.subheader(f"Teacher Dashboard for @{st.session_state.username}")
            st.table(format_assignment_rows(rows))

    else:
        student_value = st.session_state.username.lstrip("@").lower()
        with get_connection() as conn:
            student_row = conn.execute(
                "SELECT telegram_id FROM users WHERE lower(username) = ? AND role = 'student'",
                (student_value,),
            ).fetchone()

        if student_row is None:
            st.sidebar.error("No student found with that username.")
            return

        teacher_options = get_student_teacher_options(student_row["telegram_id"])
        selected_teacher = st.sidebar.selectbox(
            "Filter by teacher",
            [label for label, _ in teacher_options],
            index=0,
            key="student_teacher_filter",
        )
        selected_teacher_id = next(
            (teacher_id for label, teacher_id in teacher_options if label == selected_teacher),
            None,
        )

        student_query = """
            SELECT a.assignment_text, a.status, a.due_date,
                   (SELECT f.feedback_text
                    FROM feedback f
                    WHERE f.assignment_id = a.id
                    ORDER BY f.created_at DESC
                    LIMIT 1) AS latest_feedback
            FROM assignments a
            WHERE a.student_id = ?
            """
        params = [student_row["telegram_id"]]
        if selected_teacher_id is not None:
            student_query += " AND a.teacher_id = ?"
            params.append(selected_teacher_id)
        student_query += "\n                ORDER BY a.due_date ASC\n                """
        with get_connection() as conn:
            student_rows = conn.execute(student_query, tuple(params)).fetchall()

        if not student_rows:
            st.info("No assignments found for this student.")
        else:
            st.subheader(f"Student Dashboard for @{st.session_state.username}")
            st.table(format_student_rows(student_rows))


if __name__ == "__main__":
    main()
