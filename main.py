import atexit
import os
import re
import sys
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from db import (
    create_assignment,
    create_classroom,
    find_student_for_teacher,
    get_incomplete_assignments,
    get_latest_active_assignment,
    get_latest_submission_for_teacher,
    get_submission_for_teacher,
    get_teacher_assignments,
    get_teacher_students,
    get_teacher_student_activity,
    get_user_role,
    init_db,
    join_classroom,
    parse_assignment_message,
    get_latest_progress_for_assignment,
    save_assignment_progress,
    save_feedback,
    save_submission,
    save_user,
    teacher_has_classroom,
    update_assignment_ai,
)
from llm_service import create_llm_service, LLMServiceError
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from telegram.request import HTTPXRequest

load_dotenv(Path(__file__).resolve().parent / ".env")

LOCK_FILE = Path(__file__).resolve().parent / ".bot.lock"


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def ensure_single_instance() -> None:
    if LOCK_FILE.exists():
        try:
            old_pid = int(LOCK_FILE.read_text(encoding="utf-8").strip())
        except ValueError:
            old_pid = 0
        if _pid_alive(old_pid):
            print(
                f"Another bot instance is already running (PID {old_pid}).\n"
                "Stop it with Ctrl+C in that terminal, then try again.",
                file=sys.stderr,
            )
            sys.exit(1)
        LOCK_FILE.unlink(missing_ok=True)

    LOCK_FILE.write_text(str(os.getpid()), encoding="utf-8")

    def _release_lock() -> None:
        if LOCK_FILE.exists() and LOCK_FILE.read_text(encoding="utf-8").strip() == str(
            os.getpid()
        ):
            LOCK_FILE.unlink()

    atexit.register(_release_lock)


async def send_assignment_reminders(application: Application) -> None:
    llm_service = application.bot_data.get("llm_service")
    for row in get_incomplete_assignments():
        try:
            reminder_text = None
            if llm_service is not None:
                try:
                    reminder_text = llm_service.generate_reminder(
                        assignment_text=row["assignment_text"],
                        due_date=row["due_date"],
                        status=row["status"],
                    )
                except Exception:
                    reminder_text = None

            if not reminder_text:
                reminder_text = (
                    "Assignment reminder\n\n"
                    f"Assignment #{row['id']}:\n"
                    f"{row['assignment_text']}\n\n"
                    f"Due: {row['due_date']}\n"
                    f"Status: {row['status']}\n\n"
                    "Use /progress or /submit to update your work."
                )

            await application.bot.send_message(
                chat_id=row["student_id"],
                text=reminder_text,
            )
        except TelegramError:
            continue


async def on_startup(application: Application) -> None:
    await application.bot.delete_webhook(drop_pending_updates=True)

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        send_assignment_reminders,
        "interval",
        minutes=5,
        args=[application],
        id="assignment_reminders",
        replace_existing=True,
    )
    scheduler.start()
    application.bot_data["scheduler"] = scheduler


async def on_shutdown(application: Application) -> None:
    scheduler = application.bot_data.get("scheduler")
    if scheduler:
        scheduler.shutdown(wait=False)


START_MESSAGE = (
    "Welcome to Classroom Companion!\n"
    "Please choose your role:"
)

ROLE_KEYBOARD = InlineKeyboardMarkup(
    [
        [
            InlineKeyboardButton("Teacher", callback_data="role:teacher"),
            InlineKeyboardButton("Student", callback_data="role:student"),
        ]
    ]
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(START_MESSAGE, reply_markup=ROLE_KEYBOARD)


async def create_class(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user is None or update.message is None:
        return

    role = get_user_role(user.id)
    if role is None:
        await update.message.reply_text(
            "Please use /start and choose your role first."
        )
        return
    if role != "teacher":
        await update.message.reply_text("Only teachers can create a classroom.")
        return

    classroom_id, join_code = create_classroom(user.id)
    await update.message.reply_text(
        f"Classroom created successfully!\n"
        f"Classroom ID: {classroom_id}\n"
        f"Join code: {join_code}\n\n"
        f"Share this code with students so they can use:\n"
        f"/join {join_code}"
    )


async def join_class(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user is None or update.message is None:
        return

    role = get_user_role(user.id)
    if role is None:
        await update.message.reply_text(
            "Please use /start and choose your role first."
        )
        return
    if role != "student":
        await update.message.reply_text("Only students can join a classroom.")
        return

    if not context.args:
        await update.message.reply_text("Usage: /join <code>\nExample: /join CLASS123")
        return

    join_code = context.args[0].strip().upper()
    try:
        classroom = join_classroom(user.id, join_code)
    except ValueError as exc:
        if str(exc) == "invalid_code":
            await update.message.reply_text(
                f"Invalid join code '{join_code}'. Please check and try again."
            )
        elif str(exc) == "already_joined":
            await update.message.reply_text(
                f"You are already in classroom {join_code}."
            )
        return

    await update.message.reply_text(
        f"You have successfully joined the classroom!\n"
        f"Join code: {classroom['join_code']}\n"
        f"Classroom ID: {classroom['id']}"
    )


ASSIGN_FORMAT_HELP = (
    "Send assignments in natural language\n\n"
    "I can extract the student, task, and due date automatically."
)


async def list_students(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user is None or update.message is None:
        return

    role = get_user_role(user.id)
    if role is None:
        await update.message.reply_text(
            "Please use /start and choose your role first."
        )
        return
    if role != "teacher":
        await update.message.reply_text("Only teachers can view students.")
        return
    if not teacher_has_classroom(user.id):
        await update.message.reply_text(
            "Create a classroom first with /create_class."
        )
        return

    rows = get_teacher_students(user.id)
    if not rows:
        await update.message.reply_text(
            "No students have joined your classroom yet."
        )
        return

    by_classroom: dict[str, list[str]] = {}
    for row in rows:
        label = (
            f"@{row['username']}"
            if row["username"]
            else f"(no username, id: {row['student_id']})"
        )
        by_classroom.setdefault(row["join_code"], []).append(label)

    lines = ["Students in your classroom(s):\n"]
    for join_code, usernames in by_classroom.items():
        lines.append(f"{join_code}:")
        lines.extend(f"  • {name}" for name in usernames)
        lines.append("")

    await update.message.reply_text("\n".join(lines).strip())


async def assignment_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user is None or update.message is None:
        return

    role = get_user_role(user.id)
    if role is None:
        await update.message.reply_text(
            "Please use /start and choose your role first."
        )
        return
    if role != "teacher":
        await update.message.reply_text("Only teachers can view assignment status.")
        return
    if not teacher_has_classroom(user.id):
        await update.message.reply_text(
            "Create a classroom first with /create_class."
        )
        return

    rows = get_teacher_assignments(user.id)
    if not rows:
        await update.message.reply_text(
            "No assignments found for your classroom(s)."
        )
        return

    lines = ["Assignment status:\n"]
    current_classroom: str | None = None
    for row in rows:
        if row["join_code"] != current_classroom:
            current_classroom = row["join_code"]
            lines.append(f"\n{current_classroom}:")
        student = (
            f"@{row['username']}"
            if row["username"]
            else f"(no username, id: {row['student_id']})"
        )
        text_preview = row["assignment_text"]
        if len(text_preview) > 120:
            text_preview = text_preview[:117] + "..."

        # Use stored AI classification (if available) — do not call LLM live here
        classification_snippet = ""
        try:
            progress_row = get_latest_progress_for_assignment(row["id"])
            ai_category = row["ai_category"] if "ai_category" in row.keys() else None
            ai_summary = row["ai_summary"] if "ai_summary" in row.keys() else None
            ai_confidence = row["ai_confidence"] if "ai_confidence" in row.keys() else None
            if ai_category and ai_summary:
                summary = ai_summary
                if len(summary) > 80:
                    summary = summary[:77] + "..."
                classification_snippet = f"AI: {ai_category} — {summary} ({ai_confidence})"
        except Exception:
            classification_snippet = ""

        lines.append(
            f"\n  #{row['id']} — {student}\n"
            f"  Status: {row['status']}\n"
            f"  Due: {row['due_date']}\n"
            f"  Task: {text_preview}"
            + (f"\n  {classification_snippet}" if classification_snippet else "")
        )

    message = "\n".join(lines).strip()
    if len(message) > 4000:
        message = message[:3997] + "..."
    await update.message.reply_text(message)


async def assign_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user is None or update.message is None:
        return

    role = get_user_role(user.id)
    if role is None:
        await update.message.reply_text(
            "Please use /start and choose your role first."
        )
        return
    if role != "teacher":
        await update.message.reply_text("Only teachers can assign work.")
        return
    if not teacher_has_classroom(user.id):
        await update.message.reply_text(
            "Create a classroom first with /create_class."
        )
        return

    context.user_data["awaiting_assignment"] = True
    await update.message.reply_text(
        "Please send the assignment details.\n\n" + ASSIGN_FORMAT_HELP
    )


async def progress_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user is None or update.message is None:
        return

    role = get_user_role(user.id)
    if role is None:
        await update.message.reply_text(
            "Please use /start and choose your role first."
        )
        return
    if role != "student":
        await update.message.reply_text("Only students can submit progress.")
        return

    assignment = get_latest_active_assignment(user.id)
    if assignment is None:
        await update.message.reply_text(
            "You have no active assignments to update."
        )
        return

    context.user_data["awaiting_progress"] = True
    await update.message.reply_text(
        f"Submitting progress for assignment #{assignment['id']} "
        f"(due {assignment['due_date']}).\n\n"
        "Please send your progress update."
    )


async def receive_progress(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.user_data.get("awaiting_progress"):
        return

    user = update.effective_user
    if user is None or update.message is None:
        return
    if get_user_role(user.id) != "student":
        context.user_data.pop("awaiting_progress", None)
        return
    if not update.message.text:
        await update.message.reply_text("Please send your progress as text.")
        return

    progress_text = update.message.text.strip()
    if not progress_text:
        await update.message.reply_text("Progress cannot be empty. Please try again.")
        return

    assignment = get_latest_active_assignment(user.id)
    if assignment is None:
        context.user_data.pop("awaiting_progress", None)
        await update.message.reply_text(
            "You have no active assignments to update."
        )
        return

    progress_id = save_assignment_progress(
        assignment_id=assignment["id"],
        student_id=user.id,
        progress_text=progress_text,
    )

    classification_text = ""
    llm_service = context.application.bot_data.get("llm_service")
    if llm_service is not None:
        try:
            classification = llm_service.classify_progress(
                progress_text=progress_text,
                assignment_text=assignment["assignment_text"],
            )
            # Persist classification to DB for later reads
            try:
                update_assignment_ai(
                    assignment_id=assignment["id"],
                    ai_category=classification.category,
                    ai_summary=classification.summary,
                    ai_confidence=classification.confidence,
                )
            except Exception:
                pass

            classification_text = (
                f"\n\nProgress classification: {classification.category}\n"
                f"Summary: {classification.summary}\n"
                f"Confidence: {classification.confidence}"
            )
        except Exception:
            classification_text = "\n\nProgress classification unavailable."

    student_label = f"@{user.username}" if user.username else f"Student {user.id}"
    await context.bot.send_message(
        chat_id=assignment["teacher_id"],
        text=(
            f"Progress update from {student_label}\n\n"
            f"Assignment #{assignment['id']} (due {assignment['due_date']}):\n"
            f"{assignment['assignment_text']}\n\n"
            f"Progress:\n{progress_text}"
            f"{classification_text}"
        ),
    )
    await update.message.reply_text(
        f"Progress #{progress_id} saved for assignment #{assignment['id']}. "
        "Your teacher has been notified."
    )
    context.user_data.pop("awaiting_progress", None)


async def submit_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user is None or update.message is None:
        return

    role = get_user_role(user.id)
    if role is None:
        await update.message.reply_text(
            "Please use /start and choose your role first."
        )
        return
    if role != "student":
        await update.message.reply_text("Only students can submit assignments.")
        return

    assignment = get_latest_active_assignment(user.id)
    if assignment is None:
        await update.message.reply_text(
            "You have no active assignments to submit."
        )
        return

    context.user_data["awaiting_submission"] = True
    await update.message.reply_text(
        f"Submitting assignment #{assignment['id']} "
        f"(due {assignment['due_date']}).\n\n"
        "Please send your submission."
    )


async def receive_submission(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.user_data.get("awaiting_submission"):
        return

    user = update.effective_user
    if user is None or update.message is None:
        return
    if get_user_role(user.id) != "student":
        context.user_data.pop("awaiting_submission", None)
        return
    if not update.message.text:
        await update.message.reply_text("Please send your submission as text.")
        return

    submission_text = update.message.text.strip()
    if not submission_text:
        await update.message.reply_text(
            "Submission cannot be empty. Please try again."
        )
        return

    assignment = get_latest_active_assignment(user.id)
    if assignment is None:
        context.user_data.pop("awaiting_submission", None)
        await update.message.reply_text(
            "You have no active assignments to submit."
        )
        return

    submission_id = save_submission(
        assignment_id=assignment["id"],
        student_id=user.id,
        submission_text=submission_text,
    )

    student_label = f"@{user.username}" if user.username else f"Student {user.id}"
    await context.bot.send_message(
        chat_id=assignment["teacher_id"],
        text=(
            f"Assignment submitted by {student_label}\n\n"
            f"Assignment #{assignment['id']} (due {assignment['due_date']}):\n"
            f"{assignment['assignment_text']}\n\n"
            f"Submission:\n{submission_text}\n\n"
            "Status: completed"
        ),
    )
    await update.message.reply_text(
        f"Submission #{submission_id} saved for assignment #{assignment['id']}. "
        "Your teacher has been notified. This assignment is now completed."
    )
    context.user_data.pop("awaiting_submission", None)


async def feedback_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user is None or update.message is None:
        return

    role = get_user_role(user.id)
    if role is None:
        await update.message.reply_text(
            "Please use /start and choose your role first."
        )
        return
    if role != "teacher":
        await update.message.reply_text("Only teachers can give feedback.")
        return

    submission = get_latest_submission_for_teacher(user.id)
    if submission is None:
        await update.message.reply_text(
            "No student submissions found yet."
        )
        return

    context.user_data["awaiting_feedback"] = True
    context.user_data["feedback_submission_id"] = submission["submission_id"]
    await update.message.reply_text(
        f"Giving feedback on submission #{submission['submission_id']} "
        f"for assignment #{submission['assignment_id']}.\n\n"
        f"Student submission:\n{submission['submission_text']}\n\n"
        "Please send your feedback."
    )


async def receive_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.user_data.get("awaiting_feedback"):
        return

    user = update.effective_user
    if user is None or update.message is None:
        return
    if get_user_role(user.id) != "teacher":
        context.user_data.pop("awaiting_feedback", None)
        context.user_data.pop("feedback_submission_id", None)
        return
    if not update.message.text:
        await update.message.reply_text("Please send your feedback as text.")
        return

    feedback_text = update.message.text.strip()
    if not feedback_text:
        await update.message.reply_text(
            "Feedback cannot be empty. Please try again."
        )
        return

    submission_id = context.user_data.get("feedback_submission_id")
    if submission_id is None:
        submission = get_latest_submission_for_teacher(user.id)
    else:
        submission = get_submission_for_teacher(user.id, submission_id)

    if submission is None:
        context.user_data.pop("awaiting_feedback", None)
        context.user_data.pop("feedback_submission_id", None)
        await update.message.reply_text(
            "No submission found to attach feedback to."
        )
        return

    feedback_id = save_feedback(
        assignment_id=submission["assignment_id"],
        teacher_id=user.id,
        student_id=submission["student_id"],
        feedback_text=feedback_text,
    )

    await context.bot.send_message(
        chat_id=submission["student_id"],
        text=(
            f"Feedback on assignment #{submission['assignment_id']}\n\n"
            f"Assignment:\n{submission['assignment_text']}\n\n"
            f"Your submission:\n{submission['submission_text']}\n\n"
            f"Feedback:\n{feedback_text}"
        ),
    )
    await update.message.reply_text(
        f"Feedback #{feedback_id} saved and sent to the student."
    )
    context.user_data.pop("awaiting_feedback", None)
    context.user_data.pop("feedback_submission_id", None)


async def receive_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if context.user_data.get("awaiting_assignment"):
        await receive_assignment(update, context)
    elif context.user_data.get("awaiting_progress"):
        await receive_progress(update, context)
    elif context.user_data.get("awaiting_submission"):
        await receive_submission(update, context)
    elif context.user_data.get("awaiting_feedback"):
        await receive_feedback(update, context)
    elif await handle_teacher_summary_query(update, context):
        return


def extract_summary_query_student(text: str) -> str | None:
    patterns = [
        r"(?i)^(?:how is|how's)\s+@?(?P<student>[A-Za-z0-9_]+(?:\s+[A-Za-z0-9_]+)*)\s+doing\??$",
        r"(?i)^(?:summarize|give me an update on|what is the progress of)\s+@?(?P<student>[A-Za-z0-9_]+(?:\s+[A-Za-z0-9_]+)*)\b(?:'s progress| progress)?\??$",
        r"(?i)^(?:status of|progress of)\s+@?(?P<student>[A-Za-z0-9_]+(?:\s+[A-Za-z0-9_]+)*)\??$",
    ]
    for pattern in patterns:
        match = re.search(pattern, text.strip())
        if match:
            return match.group("student").strip().lstrip("@")
    return None


def build_fallback_student_summary(student_activity: dict) -> str:
    assignments = student_activity.get("assignments", [])
    if not assignments:
        return "I couldn't find any assignments or progress for that student."

    active = [a for a in assignments if a["status"] in ("assigned", "in_progress")]
    completed = [a for a in assignments if a["status"] == "completed"]
    latest = assignments[0]

    lines = [
        f"Student progress summary for {len(assignments)} assignment(s):",
    ]
    if active:
        lines.append(
            f"{len(active)} active assignment(s) and {len(completed)} completed."
        )
    else:
        lines.append(f"All {len(completed)} assignment(s) are completed.")

    lines.append(f"Most recent assignment: {latest['assignment_text']}")
    lines.append(f"Status: {latest['status']}, due {latest['due_date']}.")

    if latest["progress_updates"]:
        lines.append(
            "Latest progress update: "
            + latest["progress_updates"][-1]["progress_text"]
        )
    elif latest["submissions"]:
        lines.append(
            "Submission received at "
            + latest["submissions"][0]["submitted_at"]
            + "."
        )
    else:
        lines.append("No progress updates or submissions have been recorded yet.")

    return "\n".join(lines)


async def handle_teacher_summary_query(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> bool:
    user = update.effective_user
    if user is None or update.message is None or not update.message.text:
        return False

    if get_user_role(user.id) != "teacher":
        return False

    student_name = extract_summary_query_student(update.message.text)
    if not student_name:
        return False

    student_match = find_student_for_teacher(user.id, student_name)
    if student_match is None:
        await update.message.reply_text(
            "I couldn't find that student in your classroom. "
            "Please use their Telegram username or check that they have joined."
        )
        return True

    _, student_id = student_match
    student_activity = get_teacher_student_activity(user.id, student_id)

    llm_service = context.application.bot_data.get("llm_service")
    summary_text = None
    if llm_service is not None:
        try:
            summary_text = llm_service.summarize_student(student_activity)
        except Exception:
            summary_text = None

    if not summary_text:
        summary_text = build_fallback_student_summary(student_activity)

    await update.message.reply_text(summary_text)
    return True


async def receive_assignment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.user_data.get("awaiting_assignment"):
        return

    user = update.effective_user
    if user is None or update.message is None:
        return
    if get_user_role(user.id) != "teacher":
        context.user_data.pop("awaiting_assignment", None)
        return
    if not update.message.text:
        await update.message.reply_text("Please send the assignment as text.")
        return

    try:
        llm_service = context.application.bot_data.get("llm_service")
        if llm_service is not None:
            try:
                parsed = llm_service.parse_assignment(update.message.text)
                assignment_text = parsed.assignment_text
                student_name = parsed.student
                due_date = parsed.due_date
            except LLMServiceError:
                # Log already handled by llm_service; fall back to deterministic parser
                assignment_text, student_name, due_date = parse_assignment_message(
                    update.message.text
                )
        else:
            assignment_text, student_name, due_date = parse_assignment_message(
                update.message.text
            )

        match = find_student_for_teacher(user.id, student_name)
        if match is None:
            raise ValueError("student_not_found")

        classroom_id, student_id = match
        assignment_id = create_assignment(
            classroom_id=classroom_id,
            teacher_id=user.id,
            student_id=student_id,
            assignment_text=assignment_text,
            due_date=due_date,
        )

        student_label = student_name.lstrip("@")
        await context.bot.send_message(
            chat_id=student_id,
            text=(
                "New assignment\n\n"
                f"{assignment_text}\n\n"
                f"Due: {due_date}\n"
                "Status: assigned"
            ),
        )
        await update.message.reply_text(
            f"Assignment #{assignment_id} saved and sent to @{student_label}."
        )
        context.user_data.pop("awaiting_assignment", None)
    except ValueError as exc:
        error = str(exc)
        if error == "invalid_format":
            await update.message.reply_text(
                "Could not parse your message. Use this format:\n\n"
                + ASSIGN_FORMAT_HELP
            )
        elif error == "invalid_date":
            await update.message.reply_text(
                "Invalid due date. Use YYYY-MM-DD (e.g. 2026-06-01)."
            )
        elif error == "student_not_found":
            await update.message.reply_text(
                f"Student '{student_name}' was not found in your classroom.\n"
                "Check their Telegram username and that they used /join."
            )
        else:
            await update.message.reply_text("Something went wrong. Please try again.")


async def role_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    role = query.data.removeprefix("role:")
    user = query.from_user
    save_user(user.id, user.username, role)

    label = role.capitalize()
    await query.edit_message_text(
        f"You selected: {label}. Welcome to the classroom companion Bot!"
    )


def main() -> None:
    ensure_single_instance()

    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN is not set in .env")

    request = HTTPXRequest(
        connect_timeout=30.0,
        read_timeout=30.0,
        write_timeout=30.0,
    )
    init_db()
    try:
        llm_service = create_llm_service()
    except RuntimeError as exc:
        print(
            "Warning: GEMINI_API_KEY is not set. "
            "Assignment parsing will fall back to legacy format."
        )
        llm_service = None

    application = (
        Application.builder()
        .token(token)
        .request(request)
        .post_init(on_startup)
        .post_shutdown(on_shutdown)
        .build()
    )
    application.bot_data["llm_service"] = llm_service
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("create_class", create_class))
    application.add_handler(CommandHandler("join", join_class))
    application.add_handler(CommandHandler("assign", assign_command))
    application.add_handler(CommandHandler("students", list_students))
    application.add_handler(CommandHandler("status", assignment_status))
    application.add_handler(CommandHandler("progress", progress_command))
    application.add_handler(CommandHandler("submit", submit_command))
    application.add_handler(CommandHandler("feedback", feedback_command))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, receive_text)
    )
    application.add_handler(CallbackQueryHandler(role_selected, pattern=r"^role:"))
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
