# Running the Daily Lead Sweep in the Cloud

The desktop sweep drives a signed-in browser. The cloud version uses official APIs instead, so it doesn't need a browser or any saved logins:

| Source | Desktop version | Cloud version |
|---|---|---|
| Meta Leads Center | Browser | Meta Graph API (`lead_sweep` script) |
| Hope Path Messenger + Instagram | Browser | Meta Graph API (`lead_sweep` script), read-only |
| Gmail info@upeusa.com | Browser | Gmail connector, read by Claude |
| Lead Tracker sheet | Browser typing | Google Sheets API (`lead_sweep` script) |

The script does the mechanical parts: finding new lead-form submissions, checking for duplicates, giving out Lead IDs, filling columns A–T by the rules, and writing Master Contacts. Claude does the judgment calls: reading inbox threads and emails, spotting scams, and deciding what's a real lead. The routine never sends messages to anyone.

The environment's network policy already allows `graph.facebook.com`, `sheets.googleapis.com` and `oauth2.googleapis.com`. What's missing is the credentials below.

---

## Step 1: Meta Page access token → `META_PAGE_TOKEN`

The token needs to read the Hope Path Capital page's lead forms and inbox.

1. In **Meta Business Suite → Settings → Users → System users**, add a system user (e.g. "Lead Sweep"), role **Employee**.
2. Click **Assign assets**, choose the **Hope Path Capital** page, and turn on **Manage leads** and **Messages** (full control isn't needed).
3. Click **Generate new token**. Pick your app (create a basic Business app at developers.facebook.com if you don't have one), set expiry to **Never**, and tick these permissions:
   - `pages_show_list`
   - `pages_read_engagement`
   - `pages_manage_metadata`
   - `leads_retrieval`
   - `pages_messaging`
   - `instagram_basic` and `instagram_manage_messages` (for the Instagram inbox)
4. The token that comes back is a user token for the system user. To get the **Page** token, open the Graph API Explorer with it and call `GET /945022918699527?fields=access_token`, then copy the `access_token` value.
5. In **Leads Center → CRM setup / Lead access**, make sure the system user or your app has lead access. Otherwise lead reads return empty.

## Step 2: Google service account → `GOOGLE_SA_JSON`

1. At console.cloud.google.com, create a project (or use an existing one) and enable the **Google Sheets API**.
2. Go to **IAM & Admin → Service accounts → Create**, e.g. `lead-sweep`. It doesn't need a project role.
3. Open the service account, go to **Keys → Add key → JSON**, and download the file.
4. Open **UpRaise_Lead_Tracker** in Google Sheets. **Share** it with the service account's email (`lead-sweep@<project>.iam.gserviceaccount.com`) as **Editor**.
5. The environment variable's value is the **entire contents** of the JSON file, on one line is fine.

## Step 3: Add both to the cloud environment

In the Claude app, open the cloud environment menu in the session's title bar, click **Edit**, and add the two environment variables:

```
META_PAGE_TOKEN=<page token from Step 1>
GOOGLE_SA_JSON=<contents of the JSON key from Step 2>
```

Never paste these into a chat. New sessions pick them up automatically.

Optional, in the same place, a setup script so every session has the packages ready:

```
cd /home/user/daily-task-priority-tracker && python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt
```

(Use a virtualenv. The container's system `cryptography` package is broken and makes Google auth crash.)

## Step 4: Gmail for info@upeusa.com

The Gmail connector is currently signed in to **janice.jeilah@trojanconstructioninvestments.com**. The sweep needs **info@upeusa.com**. Connect Gmail for info@ at https://claude.ai/customize/connectors.

> ⚠️ If the connector holds one Google account at a time, switching it to info@ affects anything else that uses it, such as the GC bid follow-up skills on the Trojan account. If you'd rather not switch, the sweep still runs and reports "Gmail not checked".

## Step 5: Test it

In a new cloud session:

```
.venv/bin/python -m lead_sweep check
```

Every line should start with ✓. Then do a dry run that writes nothing:

```
.venv/bin/python -m lead_sweep collect
.venv/bin/python -m lead_sweep apply sweep_out/plan.json --dry-run
```

## Step 6: Switch the scheduled task

Once `check` passes, the daily routine's prompt can be replaced with the one in `daily_lead_sweep_cloud_task.md`, and the Gmail connector added to the routine. Claude can do this for you on request.

---

## Commands

| Command | What it does |
|---|---|
| `python -m lead_sweep check` | Confirms both keys work and the sheet tabs are readable. Writes nothing. |
| `python -m lead_sweep collect` | Reads the sheet and Meta. Writes `sweep_out/plan.json` (lead-form rows ready to add) and `sweep_out/review.json` (inbox threads + duplicates for Claude to review). |
| `python -m lead_sweep apply sweep_out/plan.json [--dry-run]` | Checks for duplicates again, gives out IDs, writes the rows and Master Contacts in one batch, and prints the report. |
| `python -m pytest` | Runs the offline tests. |

## How the rules are applied

These follow `daily_lead_sweep_task.md` Step 3. Where that file left a choice open, the script decides like this:

- **Duplicates:** matched by email, phone (last 10 digits) or Meta lead ID. An exact name match counts only for names of two or more words, so "Robert" doesn't match a different Robert.
- **Assigned To:** when a lead needs Cleveland, it goes to Cleveland even if it has a phone number. Otherwise it's Thomas if the lead is a priority with a phone, and Janice (Messenger) if the person is only reachable on Messenger. Never Josh.
- **Needs Cleveland on lead forms:** flagged automatically for commercial deals, partnership or equity asks, and $1M+ amounts.
- **Meta lead ID:** each lead-form row's notes end with `Meta lead ID: …`, so a lead is never added twice even if its name or phone changes.
- **Formula safety:** any text from a form or message that starts with `=`, `+`, `-` or `@` gets a leading `'`, so the sheet can't run it as a formula.
