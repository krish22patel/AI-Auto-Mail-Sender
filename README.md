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
│   ├── main.py             # FastAPI entry point & lifespan startup
│   ├── config.py           # Settings loader (.env parsing)
│   ├── db.py               # SQLite database tables setup & CRUD functions
│   ├── worker.py           # Background auto-reply sync loop task
│   ├── auth/
│   │   └── gmail_auth.py   # Google OAuth2 authorization helper
│   ├── services/
│   │   ├── gmail_service.py # Gmail API send/read operations
│   │   └── ai_service.py   # Anthropic Claude reply drafting & filters
│   ├── schemas/
│   │   └── email_schemas.py # Pydantic data validation schemas
│   └── routers/
│       └── email_router.py  # REST API route handlers
├── mcp_server/
│   └── server.py            # FastMCP server registration and tools
├── reports/
│   ├── generate_report.py   # Word document report compilation script
│   └── screenshots/         # Captured project images embedded in report
├── credentials.json        # Google Cloud desktop client credentials (Git ignored)
├── token.json              # Local cached user access token (Git ignored)
├── data.db                 # Local SQLite database cache (Git ignored)
├── requirements.txt        # Project dependencies
└── README.md               # Setup and project documentation
```

---

## 🚀 Setup & Installation Guide (for another PC)

Follow these detailed steps to deploy the application on another system from scratch:

### 1. Prerequisites
- **Python 3.10** or higher installed.
- **Git** installed.
- A **Google/Gmail Account** to authorize the email agent.
- An **Anthropic API Key** to power Claude's responses.

### 2. Clone the Repository
Open a terminal (or PowerShell on Windows) and run:
```bash
git clone https://github.com/VadsolaKishan/INTERN.git
cd INTERN
```

### 3. Initialize Virtual Environment & Install Dependencies
Create a Python virtual environment and install the required modules:
```bash
# On Windows:
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt

# On macOS/Linux:
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 4. Set Up Google Gmail API Credentials
To allow the application to read and write to your Gmail inbox:
1. Go to the [Google Cloud Console](https://console.cloud.google.com).
2. Create a new project (e.g., `AI-Email-Agent`).
3. In the sidebar, navigate to **APIs & Services > Library**. Search for **Gmail API** and click **Enable**.
4. Configure the **OAuth Consent Screen**:
   - Select **External** user type.
   - Enter standard app info (name, support email).
   - In the **Scopes** step, add `https://www.googleapis.com/auth/gmail.modify` (to read, draft, send, and apply labels).
   - Under **Test Users**, add the Gmail email address you want to link.
5. Generate Credentials:
   - Navigate to **APIs & Services > Credentials**.
   - Click **Create Credentials > OAuth Client ID**.
   - Select Application Type: **Desktop Application**.
   - Name it `EmailAgentDesktop` and click **Create**.
6. Download the JSON credentials file:
   - Click the download icon next to your client ID.
   - Rename the downloaded file exactly to `credentials.json`.
   - Place `credentials.json` directly into the project's root folder (`INTERN/`).

### 5. Configure Environment Settings
Copy the template `.env` file and input your keys:
```bash
# Windows:
copy .env.example .env

# macOS/Linux:
cp .env.example .env
```
Open the `.env` file in a text editor and update:
```env
ANTHROPIC_API_KEY=your_anthropic_claude_api_key_here
GMAIL_CREDENTIALS_PATH=credentials.json
GMAIL_TOKEN_PATH=token.json
REPLY_TONE=professional
```

### 6. Launch the Server & Complete Authentication
Run the FastAPI application. The first execution will prompt you to complete the Gmail OAuth login:
```bash
uvicorn app.main:app --reload --port 8000
```
- A browser window will automatically open redirecting you to Google login.
- Log in with the test Gmail account you added to your Google Cloud Console.
- You might see a "Google hasn't verified this app" warning page. Click **Advanced** and then click **Go to [App Name] (unsafe)** to proceed.
- Approve the requested permissions.
- Once authenticated, a message reading "Authentication Successful! You can close this window." will appear, and `token.json` will be created in your root folder.

---

## 💻 Running the Applications

### Web Dashboard
Open your web browser and navigate to:
```
http://localhost:8000/
```
From here, you can toggle the **Auto-Reply Engine** to **ON**, monitor the background worker thread checks, and inspect synced inbox items or replies.

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
