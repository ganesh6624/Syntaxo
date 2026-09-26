# Syntaxo — Learn programming by playing

A web game platform where users learn **Python, JavaScript, Java, C++ and SQL** part by part through mini-games.
Every user gets a **personal agent** that tracks their scores, analyses their progress and chats with them about the subjects.
30-day free trial, then subscription plans. Works on phones, tablets and desktops.

**Backend: Python 3.11+ / Django 5 · Database: SQLite (built in) · Frontend: one HTML page + vanilla JS/CSS (no build step).**

---

## 1. Run it

```bash
cd syntaxo
python3 -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
sh start.sh                                        # → http://localhost:3000
```

`start.sh` runs `manage.py migrate` (creates/updates the database `data/syntaxo.sqlite3`) and starts the Python web
server **gunicorn** with `gunicorn.conf.py`. The whole project is Python — no Node.js or npm is needed anywhere.

Development server with auto-reload instead:

```bash
python manage.py migrate
DJANGO_DEBUG=1 python manage.py runserver 0.0.0.0:3000
```

Windows (gunicorn is Unix-only): `python manage.py migrate` then `python manage.py runserver 0.0.0.0:3000`
(or `pip install waitress` → `waitress-serve --port=3000 config.wsgi:application`).

| Page | URL |
|---|---|
| The app | `/` |
| Admin dashboard (users, trials, revenue, agent data) | `/admin.html` — key `admin123` (change it with `ADMIN_KEY`) |
| Django admin (raw database records) | `/django-admin/` — first run `python manage.py createsuperuser` |

### Environment variables
| Variable | Purpose | Default |
|---|---|---|
| `PORT` | HTTP port | `3000` |
| `JWT_SECRET` | login-token + Django secret | generated once into `data/.secret` |
| `ADMIN_KEY` | admin dashboard key | `admin123` — **change it** |
| `TRIAL_DAYS` | free-trial length | `30` |
| `SMTP_HOST` `SMTP_PORT` `SMTP_USER` `SMTP_PASS` `MAIL_FROM` | real email (Gmail: `smtp.gmail.com`, `465`, address, App Password) | unset → **demo mode**: emails are printed in the server console and shown on screen |
| `RAZORPAY_KEY_ID` `RAZORPAY_KEY_SECRET` | real payments (UPI / cards / net-banking) | unset → **demo checkout** (no money charged) |
| `OPENAI_API_KEY` (+`OPENAI_MODEL`, `OPENAI_BASE_URL`) · `GEMINI_API_KEY` (+`GEMINI_MODEL`) · `ANTHROPIC_API_KEY` (+`ANTHROPIC_MODEL`) | optional AI model for free-form chat answers | unset → built-in tutor answers everything |
| `AI_TIMEOUT_MS` | AI request timeout | `30000` |
| `APP_TZ` | timezone for daily streaks | `Asia/Kolkata` |
| `DATA_DIR` | where the database, secret and backups live | `./data` |
| `HTTPS_ONLY=1` | behind HTTPS: redirect http→https, HSTS, secure cookies | off |
| `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS` | comma-separated, for the Django admin on a real domain | `*` |
| `DJANGO_DEBUG=1` | Django debug pages (development only) | off |
| `THREADS`, `ACCESS_LOG=1` | gunicorn threads · request log | `8` · off |

---

## 2. What users can do
1. **Register**: full name, username, email, mobile number (with country code) and password. Username, email and mobile
   must be unique. The system creates a **User ID** (e.g. `CQ100001`) and **assigns an agent** (Byte, Nova, Blaze or Luna).
   Mobile numbers are stored as `+919876543210`; Indian numbers must be 10 digits starting with 6–9.
2. **Log in** with **username** + password (email or User ID also work). bcrypt password hashes, 7-day login token
   (cookie + header), 5 wrong tries → 60 s lock-out.
3. **Play**: language → part map → lesson + cheat sheet → a 10-challenge round drawn at random from that part's
   100–320 questions (recently seen ones are avoided, weak topics come up more often).
   Quiz · predict-the-output · bug hunt · fill-the-blank · 5 lives · 30 s timer (45 s for long code) · speed bonus · combo.
   ≥ 60 % passes and unlocks the next part. All grading happens on the server, so scores can't be faked.
4. **Forgot username / password** → registered email → 6-digit code + username emailed → verify → optionally set a new
   password. Codes expire in 10 min, max 5 wrong tries, 60 s resend cooldown, reset links are single-use.
5. **30-day free trial** with full access, then **Subscription**: Monthly ₹199 · Quarterly ₹499 · Yearly ₹1,499.
   Expired users keep all progress but lessons/games return `402` until they subscribe; subscribing again extends the plan.
6. **Agent report**: skill per language, topic mastery, speed, accuracy trend, streaks, recommendations, notes log,
   engagement score and plan suggestion.
7. **Chat with the agent** ("Ask ‹agent›"): concepts, cheat sheets, comparisons (list vs tuple, DELETE vs TRUNCATE…),
   error messages, code review of pasted code, 17 pattern programs (pyramid, diamond, butterfly, heart…) in any language,
   18 classic programs verified in 4 languages, practice quizzes, and "how am I doing?" answers from the agent's real data.
   Off-topic questions are declined. Last 80 messages kept · 20 messages/min · 4000 characters max.

### Responsive design
* **Phones (320 px and up):** single column, a bottom tab bar (Play · Agent · Ask · Ranks · Plan; hidden while you play),
  tap targets of 36–44 px, 16 px inputs (no iOS zoom), code blocks scroll inside their box, the chat fits above the tab bar.
* **Tablets (561–1060 px):** two-column cards + the tab bar.
* **Desktop (> 1060 px):** top navigation links; the layout is centred with a maximum width of 1150 px.
* Checked automatically at 320 · 360 · 390 · 768 · 1024 · 1280 · 1440 px: no horizontal scrolling on any screen.

---

## 3. Project structure
```
manage.py               Django command-line entry point
start.sh                migrate (create/update tables) → gunicorn
gunicorn.conf.py        production server settings (1 worker × 8 threads)
requirements.txt
config/                 Django project: settings.py · urls.py · wsgi.py
core/                   the application
  models.py             Player · Attempt · Payment · GameSession · Counter (SQLite tables)
  store.py              all database reads/writes (the only file that touches the ORM)
  views.py · urls.py    every /api/… route + serving public/ (ETag caching, ?v= asset versioning)
  http.py               @api decorator: JSON in/out, auth, subscription check, errors, CORS, CSRF rule
  auth.py               register · login · lock-out · JWT · password recovery · mobile validation
  game.py               game engine: rounds, timer, scoring, XP, stars, unlocking (server-side grading)
  agent.py              personal agent: tracking, analysis, recommendations, plan targeting
  plans.py              trial + subscription rules (access_for = single source of truth)
  billing.py            Razorpay orders + signature check (or demo checkout)
  mailer.py             SMTP email (or demo mode) + email templates
  content.py            curriculum + question-bank loader
  util.py               shared helpers (time, rounding, errors)
  tutor/                agent chat: engine.py (intents, quizzes, code review…), kb.py (knowledge base),
                        patterns.py (pattern-program generator), llm.py (optional OpenAI / Gemini / Anthropic)
  data/                 curriculum.json · pool.json (14,482 questions) · kb.json · programs.json · patterns.json
  management/commands/  export_data · import_data · check_questions · verify_programs
  admin.py              Django admin registration
tests/test_app.py       27 automated tests
public/                 index.html · app.js · styles.css · admin.html  (the frontend)
data/                   runtime: syntaxo.sqlite3 (database) · .secret (login-token key) · backup.json (export_data)
```

## 4. Maintenance commands
```bash
python manage.py test tests                 # 27 tests on a throw-away database
python manage.py check_questions --run      # validate all 14,482 questions + re-run every Python output question
python manage.py verify_programs            # run the chat's 18 example programs and compare outputs
                                            # (JS/Java/C++ versions only if those compilers are installed — optional)
python manage.py export_data [file]         # back up all accounts, games & payments → data/backup.json
python manage.py import_data [file]         # restore from such a backup (existing accounts are skipped)
python manage.py createsuperuser            # login for /django-admin/
```
Back up with `python manage.py export_data` (or copy the `data/` folder while the server is stopped).

## 5. API
| Method | Path | Purpose |
|---|---|---|
| POST | /api/auth/register | `{fullName, username, email, countryCode, mobile, password, goalLanguage?}` → account + agent |
| POST | /api/auth/login | `{identifier, password}` → token (+ `cq_token` cookie) |
| POST | /api/auth/logout | clears the cookie |
| POST | /api/auth/forgot · verify-code · reset-password | recover username / reset password by email |
| GET | /api/me | current user |
| POST | /api/me/mobile | `{countryCode, mobile}` add / change mobile number |
| GET | /api/languages · /api/public/languages | catalog with unlock state & progress · public catalog |
| GET | /api/lesson/:lang/:level | lesson card |
| POST | /api/game/start · next · answer · finish | game session |
| GET | /api/agent/report | full agent analysis |
| GET · POST | /api/agent/chat | history + suggestions · `{message}` → reply (`text`, optional `quiz`, `actions`) |
| POST | /api/agent/chat/clear | clear chat history |
| GET | /api/plans | plans, access status, payment history |
| POST | /api/billing/order · /api/billing/verify | create payment order · verify & activate |
| GET | /api/leaderboard | top 20 by XP |
| GET | /api/admin/users | all users (header `x-admin-key`) |
| POST | /api/admin/users/:id/trial | testing: `{days:0}` ends access now, `{days:30}` adds trial days |

Auth: `Authorization: Bearer <token>`, `X-Auth-Token: <token>` or the `cq_token` cookie. Errors are JSON `{error, code?, field?}`.

## 6. Going live checklist
1. Set `SMTP_*` so recovery codes and usernames are really emailed.
2. Razorpay account → `RAZORPAY_KEY_ID` / `RAZORPAY_KEY_SECRET` (test keys first).
3. Strong `ADMIN_KEY`; keep `data/.secret` private (or set `JWT_SECRET`).
4. Put nginx/Caddy (HTTPS) in front of gunicorn and set `HTTPS_ONLY=1`. Only turn on HSTS subdomains/preload if every subdomain is HTTPS.
5. Back up daily (`python manage.py export_data`). For many simultaneous users, switch `DATABASES` in `config/settings.py` to PostgreSQL
   (models are ordinary Django models) and `CACHES` to Redis so you can run several gunicorn workers.
