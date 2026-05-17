<div align="center">

# 🎓 Classroom Companion

**AI-powered classroom workflow orchestration — built for teachers and students, delivered through Telegram.**

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![Telegram](https://img.shields.io/badge/Telegram-Bot-26A5E4?style=flat-square&logo=telegram&logoColor=white)](https://core.telegram.org/bots)
[![Streamlit](https://img.shields.io/badge/Streamlit-Dashboard-FF4B4B?style=flat-square&logo=streamlit&logoColor=white)](https://streamlit.io)
[![SQLite](https://img.shields.io/badge/SQLite-Database-003B57?style=flat-square&logo=sqlite&logoColor=white)](https://sqlite.org)
[![Railway](https://img.shields.io/badge/Deployed-Railway-0B0D0E?style=flat-square&logo=railway&logoColor=white)](https://railway.app)

</div>

---

## 📌 What is Classroom Companion?

Classroom Companion is a lightweight, AI-native classroom management system that lets teachers and students collaborate directly inside **Telegram** — no custom app required.

It combines conversational workflows with an LLM layer for smart assignment parsing, contextual reminders, progress classification, and a Streamlit dashboard for full visibility.

> Built with a clear philosophy: **AI as enhancement, not dependency.**  
> Workflows stay reliable even when AI calls fail.

---

## ✨ Feature Overview

### 👩‍🏫 Teacher Workflows

| Feature | Description |
|---|---|
| **Classroom Management** | Create classrooms, generate invite codes, view enrolled students |
| **Natural Language Assignment** | Assign work conversationally — AI extracts student, task & due date |
| **Progress Visibility** | Receive AI-interpreted student progress updates with sentiment context |
| **Feedback Loop** | Review submissions and send feedback directly to students via Telegram |

### 🧑‍🎓 Student Workflows

| Feature | Description |
|---|---|
| **Join via Invite Code** | Simple one-command classroom onboarding |
| **Assignment Tracking** | Receive assignments instantly; view tasks and deadlines |
| **Conversational Progress Updates** | Update progress in plain language — AI classifies it |
| **Multi-format Submissions** | Submit text, PDFs, documents, or photos |

---

## 🤖 AI Layer

### Assignment Parsing

Teachers write naturally. The AI extracts the structure.

```
Assign Riya a 500-word essay on climate change due Friday
```

| Extracted Field | Value |
|---|---|
| Student | Riya |
| Assignment | 500-word essay on climate change |
| Due Date | Friday |

---

### Progress Classification

Student messages are interpreted contextually.

| Student Update | AI Classification |
|---|---|
| "Finished introduction and outline" | ✅ On Track |
| "I'm stuck on the conclusion" | 🆘 Needs Help |
| "Completed final draft" | 🎉 Complete |

---

### Contextual Reminders

Reminders are dynamically generated using assignment context, due dates, and current progress state — not generic templates.

```
You're close to finishing your science essay.
Try updating your progress if you've already started.
```

---

## 🏗️ Architecture

```
┌─────────────────────┐
│    Telegram Bot      │
└────────┬────────────┘
         │
┌────────▼────────────┐
│  Workflow           │
│  Orchestration      │
│  Layer              │
└────────┬────────────┘
         │
┌────────▼────────────┐     ┌──────────────────────┐
│   SQLite Database   │◄────│  Streamlit Dashboard  │
└─────────────────────┘     └──────────────────────┘

┌─────────────────────────────────────┐
│         LLM Layer (Groq / Gemini)   │
│  Parsing · Classification · Summary │
└─────────────────────────────────────┘
```

---

## 🛠️ Tech Stack

| Layer | Technology |
|---|---|
| Bot Framework | `python-telegram-bot` |
| Backend | Python |
| Database | SQLite |
| Scheduler | APScheduler |
| AI Layer | Groq (Llama 3.1) + Gemini 2.0 |
| Dashboard | Streamlit |
| Environment | python-dotenv |
| Deployment | Railway + Streamlit Cloud |

---

## 📁 Project Structure

```
classroom_companion/
│
├── main.py                   # Bot entrypoint & command handlers
├── db.py                     # Database models & queries
├── llm_service.py            # LLM abstraction layer
├── dashboard.py              # Streamlit dashboard
├── classroom_companion.db    # SQLite database
├── requirements.txt
├── .env.example
└── README.md
```

---

## ⚙️ Setup & Installation

### 1. Clone the Repository

```bash
git clone <repo_url>
cd classroom_companion
```

### 2. Create a Virtual Environment

**Windows**
```bash
python -m venv .venv
.venv\Scripts\activate
```

**Mac / Linux**
```bash
python -m venv .venv
source .venv/bin/activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables

Create a `.env` file in the project root:

```env
BOT_TOKEN=your_telegram_bot_token

LLM_PROVIDER=groq

GROQ_API_KEY=your_groq_api_key
GROQ_MODEL=llama-3.1-8b-instant

GEMINI_API_KEY=your_gemini_api_key
GEMINI_MODEL=gemini-2.0-flash
```

---

## 🚀 Running the Project

**Start the Telegram Bot**
```bash
python main.py
```

**Launch the Dashboard**
```bash
streamlit run dashboard.py
```

---

## 💬 Telegram Command Reference

### Teacher Commands

| Command | Description |
|---|---|
| `/start` | Start bot and select role |
| `/create_class` | Create a classroom and generate an invite code |
| `/students` | View enrolled students |
| `/assign` | Create an assignment (natural language supported) |
| `/status` | View assignment status |
| `/feedback` | Send feedback to a student |

### Student Commands

| Command | Description |
|---|---|
| `/start` | Start bot and select role |
| `/join` | Join a classroom via invite code |
| `/progress` | Send a progress update |
| `/submit` | Submit completed assignment |

---

## 🔄 End-to-End Demo Flow

```
1.  Teacher creates classroom        →  Invite code generated
2.  Student joins with code          →  Enrolled instantly
3.  Teacher assigns (natural lang.)  →  AI parses task, student, due date
4.  Student receives assignment      →  Delivered via Telegram
5.  Student updates progress         →  AI classifies status
6.  Teacher receives insight         →  Contextual summary surfaced
7.  AI reminder triggered            →  Dynamic, context-aware nudge
8.  Student submits work / files     →  Forwarded to teacher
9.  Teacher sends feedback           →  Delivered to student
10. Dashboard visualizes lifecycle   →  Full assignment visibility
```

---

## 🧠 LLM Architecture

The LLM layer uses a provider abstraction to avoid vendor lock-in.

```python
BaseLLMService
├── GroqService
└── GeminiService
```

This makes it straightforward to add:
- OpenAI / Claude
- Local models (Ollama, etc.)
- Multi-provider routing with fallback chains

---

## 🛡️ Reliability Design

A core design goal was **workflow stability under AI failures**.

If any AI call fails due to quota limits, provider outages, or parsing errors — the system falls back to:

- ✅ Deterministic assignment parsing
- ✅ Static reminder templates
- ✅ Existing workflow logic

**Telegram orchestration always stays functional. AI enhances; it never controls.**

---

## 📊 Dashboard Features

**Teacher Dashboard**
- View all assignments and statuses
- AI-generated progress insights
- Filter by student or deadline

**Student Dashboard**
- View assigned tasks and due dates
- View teacher feedback
- Filter by teacher

---

## 🔭 Future Improvements

- [ ] Voice-note transcription for submissions
- [ ] Multi-classroom support per teacher
- [ ] Rich analytics and completion trends
- [ ] Assignment prioritization engine
- [ ] Parent notification layer
- [ ] Mobile-optimized dashboard
- [ ] Vector memory for long-term student insights
- [ ] Multi-provider LLM routing
- [ ] Shared production database (PostgreSQL migration)

---

## ⚠️ Known Limitations

- SQLite is used for MVP-phase persistence; not suitable for high-concurrency production use
- Bot and dashboard run in separate containers — shared state relies on the database
- Dashboard is a visibility layer; it does not interact with the bot directly

---

## 🎯 Design Philosophy

> Build fast. Stay reliable. Let AI augment, not dictate.

This project deliberately prioritises:

- **Speed of execution** over infrastructure perfection
- **Workflow reliability** over agentic complexity
- **AI as a layer** that enhances deterministic orchestration
- **Extensibility** so the architecture grows without rewrites

---

<div align="center">

Made with 🤖 + ☕ · Deployed on Railway & Streamlit Cloud

</div>
