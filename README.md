# 🤖 AI Email Agent — Automated Gmail Response System

An intelligent, autonomous email agent powered by **Anthropic Claude AI** that automatically syncs, filters, reads, and replies to Gmail messages. Built with **FastAPI** for backend operations and REST endpoints, **SQLite** for local caching, a responsive web dashboard for real-time supervision, and **FastMCP** for Model Context Protocol integration.

This project was developed by **Kishan Vadsola** as part of an engineering internship project.

---

## ✨ Key Features

- **📬 Autonomous Auto-Reply** — Reads unread emails and drafts contextually intelligent replies using Claude AI.
- **🛡️ Intelligent Loop Prevention** — Applies a custom `auto-replied` Gmail label to processed messages, preventing infinite reply loops between auto-responders.
- **⏭️ Smart Email Filtering** — Automatically skips system messages, newsletters, automated receipts, and generic email addresses (e.g., `no-reply@`, `notifications@`).
- **🎭 Adjustable Responder Tone** — Supports configuring the reply style (e.g., `professional`, `friendly`, `casual`) via settings.
- **📡 REST API Layer** — A comprehensive FastAPI backend exposing endpoints to control the auto-reply engine, view inbox sync status, and pull email logs.
- **📊 Glassmorphism Web Dashboard** — A beautiful browser interface featuring:
  - Statistics cards for Pending, Captured, and Sent emails.
  - An ON/OFF service toggle to pause/resume the background worker.
  - Active worker queue monitor to visualize current threads.
  - Dual tabs to search captured inbox mail and read generated AI replies.
  - Detail preview modals for inspection.
- **🔌 Model Context Protocol (MCP)** — Exposes email capabilities as standard MCP tools, allowing desktop AI hosts (like Claude Desktop) to invoke them.

---

## 🏗️ Technical Architecture

```
┌────────────────────────────────────────────────────────┐
│                    Frontend Dashboard                  │
│             (HTML5 / JavaScript / Vanilla CSS)         │
└───────────┬─────────────────────────────▲──────────────┘
            │ REST Requests               │ SSE / Long-poll updates
            ▼                             │
┌─────────────────────────────────────────┴──────────────┐
│                  FastAPI Backend Server                │
│     - Endpoints: /api/emails, /api/settings, etc.      │
│     - Background Async Task (Auto-Reply Engine Loop)   │
└─────┬──────────────┬─────────────┬─────────────┬───────┘
      │ Read/Write   │ OAuth       │ API Call    │ Tool Calls
      ▼              ▼             ▼             ▼
┌──────────┐   ┌───────────┐ ┌───────────┐ ┌───────────┐
│  SQLite  │   │ Gmail API │ │ Claude AI │ │    MCP    │
│ Database │   │ (Google)  │ │ (Anthropic│ │  Server   │
└──────────┘   └───────────┘ └───────────┘ └───────────┘
```

---

## 📁 Project Structure

```
├── app/
│   ├── main.py              # FastAPI entry point & lifespan startup
│   ├── config.py            # Settings loader (.env parsing)
│   ├── db.py                # SQLite database tables setup & CRUD functions
│   ├── worker.py            # Background auto-reply sync loop task
│   ├── auth/
│   │   └── gmail_auth.py    # Google OAuth2 authorization helper
│   ├── services/
│   │   ├── gmail_service.py  # Gmail API send/read operations
│   │   ├── gmail_push.py     # Gmail Push Notifications (Pub/Sub) handler
│   │   └── ai_service.py    # Anthropic Claude reply drafting & filters
│   ├── schemas/
│   │   └── email_schemas.py  # Pydantic data validation schemas
│   └── routers/
│       ├── email_router.py   # REST API route handlers
│       └── push_router.py    # Gmail Pub/Sub push webhook endpoints
├── mcp_server/
│   └── server.py             # FastMCP server registration and tools
├── reports/
│   ├── generate_report.py    # Word document report compilation script
│   └── screenshots/          # Captured project images embedded in report
├── credentials.json         # Google Cloud desktop client credentials (Git ignored)
├── token.json               # Local cached user access token (Git ignored)
├── data.db                  # Local SQLite database cache (Git ignored)
├── generate_token.py        # One-time Gmail OAuth token generator script
├── run.bat                  # One-click Windows launcher script
├── requirements.txt         # Project dependencies
└── README.md                # Setup and project documentation
```

---

## 🚀 Setup & Installation Guide

Follow these steps to deploy the application from scratch on any Windows machine.

---

### ⚡ Option A — One-Click Setup (Windows)

If you are on Windows, simply double-click **`run.bat`** in the project root. It will:
1. Verify Python is installed.
2. Create a virtual environment if one does not exist.
3. Install all dependencies from `requirements.txt`.
4. Check for `.env` and `credentials.json` (opens Notepad if `.env` is missing).
5. Launch the FastAPI server at `http://localhost:8000`.

> **Note:** You still need to complete Steps 1–4 below before running `run.bat` for the first time.

---

### 🔧 Option B — Manual Setup

#### 1. Prerequisites
- **Python 3.10+** installed and on your system PATH.
- **Git** installed.
- A **Google/Gmail Account** to authorize the agent.
- An **Anthropic API Key** (get one at [console.anthropic.com](https://console.anthropic.com)).

#### 2. Clone the Repository
```bash
git clone https://github.com/VadsolaKishan/INTERN.git
cd INTERN
```

#### 3. Create Virtual Environment & Install Dependencies
```bash
# Windows
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt

# macOS / Linux
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

#### 4. Set Up Google Gmail API Credentials
This step grants the app access to read and send Gmail messages.

1. Go to [Google Cloud Console](https://console.cloud.google.com) and create a new project (e.g., `AI-Email-Agent`).
2. Navigate to **APIs & Services → Library**, search for **Gmail API**, and click **Enable**.
3. Configure the **OAuth Consent Screen**:
   - Choose **External** user type.
   - Fill in app name and support email.
   - Add scope: `https://www.googleapis.com/auth/gmail.modify`.
   - Under **Test Users**, add the Gmail address the agent will use.
4. Create Credentials:
   - Go to **APIs & Services → Credentials → Create Credentials → OAuth Client ID**.
   - Set Application Type to **Desktop App**, name it (e.g., `EmailAgentDesktop`).
5. Download the credentials:
   - Click the download icon next to your new Client ID.
   - **Rename** the file to exactly `credentials.json`.
   - **Place** it in the project root folder.

#### 5. Configure Environment Variables
```bash
# Windows
copy .env.example .env

# macOS / Linux
cp .env.example .env
```
Open `.env` and fill in your values:
```env
# Required — your Anthropic Claude API key
ANTHROPIC_API_KEY=your_anthropic_api_key_here

# Gmail OAuth file paths (defaults are fine)
GMAIL_CREDENTIALS_PATH=credentials.json
GMAIL_TOKEN_PATH=token.json

# Your name and email shown in replies
USER_NAME="Your Name"
USER_EMAIL=you@gmail.com

# Reply tone: professional | friendly | casual
REPLY_TONE=professional
```

#### 6. Generate Gmail OAuth Token (`token.json`)
`token.json` is a **one-time** user authorization token — it must be generated by logging in via your browser. Run:
```bash
# Windows
venv\Scripts\python.exe generate_token.py

# macOS / Linux
python generate_token.py
```
What happens:
- A browser window will open asking you to sign in to the Gmail account set as a test user.
- You may see **"Google hasn't verified this app"** — click **Advanced → Go to [App Name] (unsafe)**.
- Grant the requested Gmail permissions.
- The script saves `token.json` to the project root and prints `[OK] token.json saved successfully!`.

> ✅ After this step, `token.json` is managed automatically — the app refreshes it silently. You **do not** need to repeat this unless you revoke access.

#### 7. Launch the Server
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```
Or on Windows, simply run:
```
run.bat
```

---

## 💻 Running the Application

### Web Dashboard
Once the server is running, open your browser and go to:
```
http://localhost:8000/
```
From the dashboard you can:
- Toggle the **Auto-Reply Engine** ON/OFF.
- Monitor the live background worker status.
- Browse synced inbox emails and generated AI replies.
- View per-email detail modals and reply previews.

### REST API Documentation
FastAPI provides interactive Swagger documentation (disabled on root for production safety but accessible locally if enabled). 

### MCP Server (Claude Desktop Integration)
To use the email agent as dynamic tools within your local Claude Desktop app:
1. Run the MCP server directly to test connection:
   ```bash
   python mcp_server/server.py
   ```
2. Open your Claude Desktop configuration file (accessible via Settings or located at `%APPDATA%\Claude\claude_desktop_config.json` on Windows):
3. Add the server entry:
   ```json
   {
     "mcpServers": {
       "email-agent": {
         "command": "python",
         "args": ["f:/Krish/mcp_server/server.py"],
         "env": {
           "ANTHROPIC_API_KEY": "your_api_key_here"
         }
       }
     }
   }
   ```
4. Restart Claude Desktop. You will see a hammer icon representing active email-agent tools (`list_unread_emails`, `get_email_details`, `reply_to_email`, `auto_reply_all`, `search_emails`).

---

## 📄 License
This project is licensed under the MIT License.
