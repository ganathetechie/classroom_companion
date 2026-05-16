Classroom Companion : AI-powered Telegram classroom workflow assistant for teachers and students.

Overview
Classroom Companion is an AI-native assignment orchestration system built using Telegram, Python, SQLite, Gemini, and Streamlit.
The system enables teachers and students to collaborate through conversational workflows directly inside Telegram while providing AI-powered assignment parsing, contextual reminders, progress understanding, and dashboard visibility.
The product was designed as a lightweight but extensible workflow orchestration MVP focused on:
•	Natural-language classroom interactions
•	AI-enhanced assignment management
•	Teacher/student workflow automation
•	Progress tracking and contextual insights
•	Fast execution with reliable deterministic fallback logic
________________________________________
Core Features
Teacher Workflows
Classroom Management
•	Create classrooms
•	Generate invite/join codes
•	View joined students
Assignment Orchestration
•	Assign work using natural language
•	AI extracts:
o	student
o	assignment
o	due date
•	Assignment delivery through Telegram
Progress Visibility
•	Receive student progress updates
•	AI interprets progress and sentiment
•	View assignment status and AI insights
Feedback Workflow
•	Review submissions
•	Send feedback directly to students
________________________________________
Student Workflows
Classroom Joining
•	Join classrooms using invite codes
Assignment Tracking
•	Receive assignments instantly
•	View assignments and due dates
•	Update progress conversationally
•	Submit completed work
AI Assistance
•	Receive contextual reminders
•	Receive feedback updates from teachers
________________________________________
AI Features
AI Assignment Parsing
Teachers can use natural language instead of strict templates.
Example:
Assign Riya a 500-word essay on climate change due Friday
The LLM extracts:
•	Student name
•	Assignment description
•	Due date
________________________________________
AI Progress Classification
Student progress updates are interpreted using Gemini.
Examples:
Student Update	AI Interpretation
“Finished introduction and outline”	On Track
“I’m stuck on the conclusion”	Needs Help
“Completed final draft”	Complete
________________________________________
AI Contextual Reminders
Reminder messages are generated dynamically using assignment context and due dates.
Example:
You're close to finishing your science essay. Try updating your progress if you've already started.
________________________________________
AI Dashboard Insights
Teacher dashboard surfaces:
•	Assignment status
•	Progress interpretation
•	AI-generated insights
•	Student activity summaries
________________________________________
Architecture
High-Level System Flow
Telegram Bot
      ↓
Workflow Orchestration Layer
      ↓
SQLite Database
      ↑
Streamlit Dashboard

LLM Layer (Gemini)
      ↓
AI Parsing + Classification + Summaries
________________________________________
Tech Stack
Layer	Technology
Bot Framework	python-telegram-bot
Backend	Python
Database	SQLite
Scheduler	APScheduler
AI Layer	Gemini API
Dashboard	Streamlit
Environment Management	python-dotenv
________________________________________
Project Structure
classroom_companion/
│
├── main.py
├── db.py
├── llm_service.py
├── dashboard.py
├── classroom_companion.db
├── requirements.txt
├── .env
└── README.md
________________________________________
LLM Architecture
The project uses a provider abstraction layer to avoid vendor lock-in.
Current Provider
•	Gemini
Extensible Design
The LLM layer is abstracted through:
BaseLLMService
This allows future support for:
•	OpenAI
•	Groq
•	Claude
•	Local models
without changing orchestration workflows.
________________________________________
Reliability Design
A major design goal was maintaining workflow reliability even during AI failures.
Deterministic Fallbacks
If AI calls fail due to:
•	quota limits
•	provider outages
•	parsing failures
the system falls back to:
•	deterministic parsing
•	static reminders
•	existing workflow logic
This ensures:
•	workflows never crash
•	Telegram orchestration remains functional
•	AI acts as enhancement, not dependency
________________________________________
Dashboard Features
Teacher Dashboard
•	View assignments
•	View assignment status
•	AI progress insights
•	Filter by student
•	View deadlines
Student Dashboard
•	View assignments
•	View due dates
•	View feedback
•	Filter by teacher
________________________________________
Setup Instructions
1. Clone Repository
git clone <repo_url>
cd classroom_companion
________________________________________
2. Create Virtual Environment
python -m venv .venv
Activate:
Windows
.venv\Scripts\activate
Mac/Linux
source .venv/bin/activate
________________________________________
3. Install Dependencies
pip install -r requirements.txt
________________________________________
4. Configure Environment Variables
Create .env
BOT_TOKEN=your_telegram_bot_token
GEMINI_API_KEY=your_gemini_api_key
LLM_PROVIDER=gemini
GEMINI_MODEL=gemini-2.0-flash
________________________________________
Running the Bot
python main.py
________________________________________
Running the Dashboard
streamlit run dashboard.py
________________________________________
Telegram Commands
Teacher Commands
Command	Description
/start	Start bot and select role
/create_class	Create classroom and invite code
/students	View students
/assign	Create assignment
/status	View assignment status
/feedback	Send feedback
________________________________________
Student Commands
Command	Description
/start	Start bot and select role
/join	Join classroom
/progress	Send progress update
/submit	Submit assignment
________________________________________
Example End-to-End Workflow
Teacher
Assign Riya a climate change essay due Friday
AI Layer
•	Extracts student
•	Extracts task
•	Extracts due date
Student
Receives assignment instantly.
________________________________________
Student Progress Update
Finished introduction but stuck on conclusion
AI Layer
Classifies:
•	Needs Help
•	In Progress
Teacher receives contextual update.
________________________________________
Reminder Workflow
AI generates contextual reminder messages based on:
•	assignment status
•	due date
•	progress state
________________________________________
Tradeoffs & Design Decisions
Why Telegram?
Telegram enables:
•	conversational workflows
•	multi-user orchestration
•	rapid prototyping
•	lightweight collaboration
without requiring custom frontend development.
________________________________________
Why SQLite?
SQLite was chosen for:
•	simplicity
•	portability
•	rapid iteration
•	low operational overhead
for MVP development.
________________________________________
Why Streamlit?
Streamlit allowed rapid creation of visibility and analytics layers without building a dedicated frontend.
________________________________________
Why AI Augmentation Instead of AI-First Control?
The product intentionally uses:
AI as enhancement
NOT AI as workflow dependency
This improves:
•	reliability
•	predictability
•	graceful degradation
•	workflow stability
________________________________________
Future Improvements
Potential future enhancements:
•	Voice-note progress updates
•	Multi-classroom support
•	Rich analytics
•	Assignment prioritization
•	Parent notifications
•	Mobile dashboard
•	Vector memory for long-term student learning insights
•	Multi-provider LLM routing
________________________________________
Demo Flow
Recommended demo sequence:
1.	Teacher creates classroom
2.	Student joins classroom
3.	Teacher assigns naturally using AI
4.	Student receives assignment
5.	Student updates progress conversationally
6.	AI interprets progress
7.	Teacher receives contextual insight
8.	AI reminder triggered
9.	Student submits work
10.	Teacher provides feedback
11.	Dashboard visualizes assignment lifecycle
________________________________________
Key Product Themes
This project focuses on:
•	AI-native workflows
•	Conversational orchestration
•	Human-in-the-loop automation
•	Reliable AI augmentation
•	Fast execution and extensibility
________________________________________
Author Notes
The product was intentionally designed as a pragmatic AI-native MVP focused on balancing:
•	speed of execution
•	workflow reliability
•	AI augmentation
•	extensibility
•	user experience
rather than overengineering infrastructure or agentic complexity.
