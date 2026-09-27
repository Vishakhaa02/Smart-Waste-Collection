# CircuitBin — Smart Waste Collection & Recycling Platform

A lightweight web app that lets residents submit waste pickup requests against the
correct waste category, track the request with a code, and lets a collection team
manage every request from one dashboard.

Built for **FITFEST2026 / GDG FIT Pune Hackathon 2026** (solo, software-only, ~4 hour MVP).

---

## Problem

Residents often don't know which category their waste falls into or how to request a
pickup, and collection teams have no single place to see, prioritize, or update the
status of incoming requests — most of it happens over phone calls with no record.

## Solution

CircuitBin gives residents a simple form to describe their waste and pickup details,
a category guide so they choose correctly, and a tracking code so they can check
status without calling anyone. Collection staff get a password-protected dashboard
to search, filter, and update every request, with live counts by status and category.

---

## Features

**Resident-facing**

| Feature | Where |
|---|---|
| Marketing landing page with live impact stats & how-it-works | `/` |
| Waste category selection with disposal guidance | `/request` |
| Pickup location (address + optional landmark) | `/request` |
| Pickup request submission | `/request` → generates a tracking code |
| Preferred pickup date scheduling | `/request` |
| Request status tracking with a full status timeline | `/track` |
| Look up every request tied to a phone number | `/my-requests` |
| Rate & comment once a pickup is collected | `/track` (after collection) |
| About page with platform stats | `/about` |
| FAQ | `/faq` |
| Site-wide announcement banner (managed by admin) | every page |

**Admin dashboard** (password-protected, `/admin`)

| Feature | Where |
|---|---|
| Overview: stat cards, status/category charts, recent activity feed | `/admin/overview` |
| Full request list with filters, search & pagination | `/admin/requests` |
| Bulk status updates across selected requests | `/admin/requests` |
| CSV export (all or filtered results) | `/admin/export.csv` |
| Request detail page with full status history timeline | `/admin/requests/<id>` |
| Feedback & ratings review | `/admin/feedback` |
| Create/hide/delete site-wide announcements | `/admin/announcements` |

---

## Technologies used

- **Python 3 / Flask** — application server and routing
- **SQLite** — embedded database (zero setup, file-based)
- **Jinja2** — server-rendered templates
- **HTML / CSS (custom, no framework)** — UI
- **Gunicorn** — production WSGI server
- **Docker** — containerized for deployment
- **Google Cloud Run** — serverless container hosting

No JavaScript framework, no external accounts, no paid services required to run it.

---

## Project structure

```
waste-platform/
├── app.py                     # Flask app: routes, DB access, business logic
├── requirements.txt            # Python dependencies
├── Dockerfile                  # Container build for Cloud Run
├── .gitignore
├── templates/
│   ├── base.html                  # shared header/nav/footer/announcement banner
│   ├── landing.html                # marketing homepage
│   ├── request_form.html           # pickup request form
│   ├── confirmation.html
│   ├── track.html                  # tracking + status timeline + feedback form
│   ├── my_requests.html            # lookup by phone number
│   ├── about.html
│   ├── faq.html
│   ├── admin_login.html
│   └── admin/
│       ├── layout.html             # sidebar shell for the dashboard
│       ├── overview.html           # stats + charts + activity feed
│       ├── requests.html           # filter/search/bulk-update/export table
│       ├── detail.html             # single request + timeline + update form
│       ├── feedback.html
│       └── announcements.html
└── static/
    └── style.css
```

## Data model

Four SQLite tables, created automatically on first run:

- **requests** — the core pickup request record
- **status_history** — an append-only log of every status change (powers the timelines)
- **feedback** — one rating + comment per collected request
- **announcements** — admin-managed banner messages shown site-wide

---

## Run locally

Requirements: Python 3.10+

```bash
git clone <your-repo-url>
cd waste-platform
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

python3 app.py
```

The app starts on **http://localhost:8080**.

- Submit a request at `/`
- Track it at `/track` using the code shown after submitting
- Admin dashboard at `/admin` — default password is `admin123` (see below to change it)

A SQLite file is created automatically at `data/waste.db` on first run.

### Environment variables (optional)

| Variable | Default | Purpose |
|---|---|---|
| `ADMIN_PASSWORD` | `admin123` | Password for `/admin` |
| `SECRET_KEY` | `dev-secret-change-me` | Flask session signing key — set a real secret in production |
| `PORT` | `8080` | Port the server listens on |
| `DB_PATH` | `./data/waste.db` | SQLite file location |

Example:
```bash
export ADMIN_PASSWORD="change-me"
export SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_hex(16))')"
python3 app.py
```

---

## Run with Docker

```bash
docker build -t circuitbin .
docker run -p 8080:8080 -e ADMIN_PASSWORD=change-me circuitbin
```

Visit http://localhost:8080

---

## Deploy to Google Cloud Run

Prerequisites: a Google Cloud project with billing enabled, and the `gcloud` CLI
installed and authenticated (`gcloud auth login`).

```bash
# 1. Set your project
gcloud config set project YOUR_PROJECT_ID

# 2. Enable required APIs (one-time)
gcloud services enable run.googleapis.com cloudbuild.googleapis.com

# 3. Build and deploy directly from source (Cloud Build creates the container for you)
gcloud run deploy circuitbin \
  --source . \
  --region asia-south1 \
  --allow-unauthenticated \
  --set-env-vars ADMIN_PASSWORD=change-me,SECRET_KEY=$(python3 -c "import secrets;print(secrets.token_hex(16))")

# 4. Cloud Run prints a Service URL when it finishes — that's your submission link
```

**Notes on this MVP's storage:** the app uses a local SQLite file for simplicity,
which is appropriate for demoing an MVP. Cloud Run containers are stateless and can
scale to multiple instances, so data is not guaranteed to persist across deploys or
be shared across instances. For the hackathon demo, deploy with a single instance:

```bash
gcloud run deploy circuitbin --source . --max-instances=1 --min-instances=1 ...
```

For a production version, swap SQLite for a managed database (e.g. Cloud SQL for
PostgreSQL/MySQL, or Firestore) — the data-access code is isolated in `app.py`
(`get_db`, `init_db`, and the query calls), so this is a contained change.

---

## Security notes (MVP scope)

- Admin auth is a single shared password stored in an environment variable, suitable
  for a hackathon demo — not per-user accounts or role-based access.
- Always set a real `SECRET_KEY` and `ADMIN_PASSWORD` before deploying publicly.
- Form inputs are stored via parameterized SQL queries (no raw string interpolation),
  which protects against SQL injection.

---

## Possible next steps

- Map-based pickup location picker (lat/lng) instead of free-text address
- SMS/email notifications when status changes
- Per-collector accounts and assignment
- Recurring pickup schedules
- Photo upload for bulky/hazardous waste items

---

## Author

Built by Vishakha Hiwrale, solo for FITFEST2026 Hackathon — Flora Institute of Technology / GDG FIT Pune.

