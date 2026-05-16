import atexit
import os
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
    get_user_role,
    init_db,
    join_classroom,
    parse_assignment_message,
    save_assignment_progress,
    save_feedback,
    save_submission,
    save_user,
    teacher_has_classroom,
)
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
    for row in get_incomplete_assignments():
        try:
            await application.bot.send_message(
                chat_id=row["student_id"],
                text=(
                    "Assignment reminder\n\n"
                    f"Assignment #{row['id']}:\n"
                    f"{row['assignment_text']}\n\n"
                    f"Due: {row['due_date']}\n"
                    f"Status: {row['status']}\n\n"
                    "Use /progress or /submit to update your work."
                ),
            )
        except TelegramError:
            continue


async def on_startup(application: Application) -> None:
    await application.bot.delete_webhook(drop_pending_updates=True)

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        send_assignment_reminders,
        "interval",
        minutes=1,
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
    "Send the assignment in this format:\n\n"
    "<assignment text>\n\n"
    "Student: <telegram username>\n"
    "Due: YYYY-MM-DD\n\n"
    "Example:\n"
    "Read chapter 5 and answer questions 1-10\n\n"
    "Student: jane_student\n"
    "Due: 2026-06-01"
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
        lines.append(
            f"\n  #{row['id']} — {student}\n"
            f"  Status: {row['status']}\n"
            f"  Due: {row['due_date']}\n"
            f"  Task: {text_preview}"
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

    student_label = f"@{user.username}" if user.username else f"Student {user.id}"
    await context.bot.send_message(
        chat_id=assignment["teacher_id"],
        text=(
            f"Progress update from {student_label}\n\n"
            f"Assignment #{assignment['id']} (due {assignment['due_date']}):\n"
            f"{assignment['assignment_text']}\n\n"
            f"Progress:\n{progress_text}"
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

    application = (
        Application.builder()
        .token(token)
        .request(request)
        .post_init(on_startup)
        .post_shutdown(on_shutdown)
        .build()
    )
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
