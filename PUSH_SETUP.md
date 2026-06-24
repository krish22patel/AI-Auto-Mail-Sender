# Gmail Push Notifications + HuggingFace Setup Guide

This is a **one-time setup** guide for two things:

1. **HuggingFace Token** — so the AI can generate email replies using free open-source models.
2. **Gmail Push Notifications** — so new emails trigger instant replies instead of waiting for a polling cycle.

---

## Part 1 — HuggingFace API Token (5 minutes)

### Step 1.1 — Get your token

1. Go to https://huggingface.co/settings/tokens
2. Click **New token**
3. Name it `ai-email-agent`
4. Select the **"Make calls to the serverless Inference API"** permission (under *Inference*)
5. Click **Create token** and copy it

### Step 1.2 — Add to `.env`

```env
HF_TOKEN=hf_YourTokenHere
HF_MODEL=Qwen/Qwen2.5-7B-Instruct:together
```

**Alternative models you can use:**

| Model | HF_MODEL value |
|-------|---------------|
| Llama 3.1 8B | `meta-llama/Meta-Llama-3.1-8B-Instruct:together` |
| Mistral 7B | `mistralai/Mistral-7B-Instruct-v0.3:nebius` |
| Phi-3.5 Mini | `microsoft/Phi-3.5-mini-instruct:together` |

---

## Part 2 — Gmail Push Notifications via Google Cloud Pub/Sub (~20 minutes)

### Why do this?

The old polling method checked for new emails every 5 minutes:
- Emails could wait up to 5 minutes for a reply
- Repeated API calls hit rate limits on free accounts
- Emails could be dropped during cool-down periods

With **Gmail Push**, Google sends an HTTP notification to your server the moment a new email arrives (~1 second latency). No polling. No rate limits on email detection. Zero data loss.

---

### Step 2.1 — Enable required Google APIs

1. Go to Google Cloud Console: https://console.cloud.google.com
2. Select the same project where you got `credentials.json`
3. Go to **APIs & Services > Library**
4. Search and **Enable** these two APIs:
   - `Gmail API`
   - `Cloud Pub/Sub API`

---

### Step 2.2 — Create a Pub/Sub Topic

> **Can't see "Pub/Sub" or "Topics" in the sidebar?**
> The Pub/Sub section only appears **after** the Cloud Pub/Sub API is enabled (Step 2.1).
> After enabling it, **hard-refresh the page** (Ctrl + Shift + R) or wait ~30 seconds and reload.

**Fastest way — use the direct link:**

Go to: `https://console.cloud.google.com/cloudpubsub/topic/list`

*(Make sure your correct project is selected in the top project dropdown first.)*

**Or navigate manually:**

1. In the left sidebar, scroll down and click **"Pub/Sub"**
   - If you don't see it, click the **☰ hamburger menu** (top-left) → search for "Pub/Sub"
2. Under Pub/Sub, click **"Topics"** (it's a sub-item in the sidebar)
3. You will land on the Topics list page — click **"Create Topic"** at the top
4. Fill in:
   - **Topic ID**: `gmail-push`
   - Leave **"Add a default subscription"** unchecked (we'll create a push subscription separately)
   - Leave everything else as default
5. Click **Create**

Your topic resource name will be shown on the next screen — copy it, it looks like:
```
projects/YOUR-PROJECT-ID/topics/gmail-push
```

> **Note:** Replace `YOUR-PROJECT-ID` with your actual GCP project ID. You can find it in the top
> project dropdown bar — it's the text in parentheses, e.g. `my-project-123456`.

---

### Step 2.3 — Grant Gmail the Publisher role

Gmail uses a special Google service account to publish to your topic.
You **must** grant it permission.

1. Click on your `gmail-push` topic
2. Go to **Permissions** tab
3. Click **Add Principal**
4. New principal (type exactly):
   ```
   gmail-api-push@system.gserviceaccount.com
   ```
5. Role: `Pub/Sub Publisher`
6. Click **Save**

---

### Step 2.4 — Create a Push Subscription

1. Go to **Pub/Sub > Subscriptions**
2. Click **Create Subscription**
3. Settings:
   - **Subscription ID**: `gmail-push-sub`
   - **Topic**: `gmail-push`
   - **Delivery type**: **Push**
   - **Endpoint URL**: `https://YOUR-URL/webhook/gmail`
   - **Acknowledge deadline**: 60 seconds
4. Click **Create**

---

### Step 2.5 — Set up a public HTTPS URL

Gmail can only push to **public HTTPS** endpoints.

#### Option A: ngrok (Local development — step-by-step install)

**A1 — Create a free ngrok account**

1. Go to https://dashboard.ngrok.com/signup
2. Sign up with Google, GitHub, or email (free, no credit card)
3. After login you'll land on the **Getting Started** page — keep this tab open

**A2 — Download and install ngrok on Windows**

1. Go to https://ngrok.com/download
2. Click **Windows** → download the `.zip` file
3. Extract the `.zip` — you'll get a single file: `ngrok.exe`
4. Move `ngrok.exe` to a permanent folder, e.g.:
   ```
   C:\tools\ngrok\ngrok.exe
   ```
5. Add that folder to your system PATH so you can run `ngrok` from any terminal:
   - Press `Win + S` → search **"Environment Variables"** → click **"Edit the system environment variables"**
   - Click **Environment Variables…**
   - Under **System variables**, select **Path** → click **Edit**
   - Click **New** → type `C:\tools\ngrok`
   - Click **OK** on all dialogs
6. Open a **new** PowerShell or Command Prompt and verify:
   ```
   ngrok version
   ```
   You should see something like `ngrok version 3.x.x`

> **Alternative — install via Chocolatey** (if you have Chocolatey installed):
> ```
> choco install ngrok
> ```
> Or via **Winget**:
> ```
> winget install ngrok
> ```

**A3 — Connect your ngrok account (one-time)**

1. In your ngrok dashboard, go to **Your Authtoken**:
   https://dashboard.ngrok.com/get-started/your-authtoken
2. Copy your authtoken (looks like: `2abc...XYZ_abc...`)
3. Run this command once in your terminal (paste your token):
   ```
   ngrok config add-authtoken YOUR_AUTHTOKEN_HERE
   ```
   You'll see: `Authtoken saved to configuration file`

**A4 — Run ngrok**

Make sure your AI Email Agent server is NOT running yet. In a **separate terminal window**, run:
```
ngrok http 8000
```

You'll see output like:
```
Session Status     online
Account            your@email.com (Plan: Free)
Forwarding         https://abc123.ngrok-free.app -> http://localhost:8000
```

Copy the **Forwarding** HTTPS URL (e.g. `https://abc123.ngrok-free.app`) — you need it for the next steps.

**A5 — Update the Pub/Sub subscription endpoint**

Go back to your Pub/Sub subscription in Google Cloud Console and update the **Endpoint URL** to:
```
https://abc123.ngrok-free.app/webhook/gmail
```

*(Use your actual ngrok URL, not the example above)*

**A6 — Update `.env`**

```env
WEBHOOK_BASE_URL=https://abc123.ngrok-free.app
```

> **Important:** Free ngrok URLs **change every time** you restart ngrok.
> When the URL changes, repeat A5 and A6 with the new URL.
> To get a **permanent free URL**, enable a static domain in the ngrok dashboard:
> https://dashboard.ngrok.com/cloud-edge/domains → **New Domain** (one free static domain per account)
> Then run ngrok with: `ngrok http --domain=your-static-domain.ngrok-free.app 8000`

#### Option B: Production domain

If your server is deployed publicly (VPS, cloud, etc.), just use your real domain directly — no ngrok needed:
```
https://yourdomain.com/webhook/gmail
```

---


### Step 2.6 — Update `.env`

```env
PUBSUB_TOPIC=projects/YOUR-GCP-PROJECT-ID/topics/gmail-push
WEBHOOK_BASE_URL=https://abc123.ngrok-free.app
```

---

### Step 2.7 — Test

1. Start the server: `run.bat`
2. Look for in console:
   ```
   [WORKER] Gmail watch registered successfully.
   ```
3. Send a test email from a whitelisted domain
4. Within ~2 seconds you should see:
   ```
   [Webhook] Received Pub/Sub notification historyId=XXXXX
   [Webhook] Enqueued message <ID> (sender@gmail.com | Subject)
   [WORKER] Auto-replied to sender@gmail.com
   ```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `HF_TOKEN is not set` | Missing token | Add `HF_TOKEN=hf_...` to `.env` |
| `HuggingFace auth failed (401)` | Wrong/expired token | Re-generate at HF settings |
| `Model not found (404)` | Wrong HF_MODEL value | Check model name + `:backend` suffix |
| `HF rate limit` | Free tier quota hit | Wait or upgrade HF account |
| `PUBSUB_TOPIC not set` | Push not configured | Follow Part 2 above |
| Gmail watch fails 403 | Missing Pub/Sub publisher role | Redo Step 2.3 |
| Webhook never called | ngrok down or URL mismatch | Restart ngrok, update subscription URL |
| Duplicate replies | Pub/Sub retry | Safe — DB deduplication prevents double-send |
