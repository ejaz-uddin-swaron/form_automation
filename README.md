# 🤖 AI-Driven Contact Form Submitter

An autonomous Python agent that navigates to target company websites, discovers
their contact forms, fills them in with your payload, and submits — all powered
by an LLM + Playwright browser automation.

---

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
playwright install chromium
```

### 2. Configure your `.env`

```bash
cp .env.example .env
# Edit .env with your OpenAI API key and sender details
```

### 3. Add target URLs

Edit `targets.csv` — one URL per row in the `url` column:

```csv
url,notes
https://www.example.com,Test site
https://www.somecompany.com/contact,Direct contact page
```

### 4. Run

```bash
python main.py               # process all URLs from targets.csv
python main.py --url URL      # single URL
python main.py --headless     # run without visible browser
python main.py -v             # verbose/debug logging
```

---

## Architecture

```
main.py          CLI entry point — parses args, loads CSV, runs batch
  ├─ config.py   Pydantic settings from .env (API keys, sender payload)
  ├─ agent.py    browser-use Agent loop with stealth context
  └─ db.py       SQLite persistence (results.db)
```

### How each URL is processed

1. **Navigate** — Open the URL; if no form is visible, find and click "Contact Us" links.
2. **Inspect** — The LLM reads the accessibility tree to identify form fields.
3. **Fill** — Map payload fields (name, email, phone, subject, message) to form inputs.
4. **Submit** — Click the submit button and wait for confirmation.
5. **CAPTCHA guard** — If a CAPTCHA is detected, the agent skips without crashing.

---

## Results

Every run appends rows to `results.db` (SQLite). You can query it directly:

```bash
sqlite3 results.db "SELECT * FROM submissions ORDER BY id DESC LIMIT 10;"
```

| Column        | Description                        |
| ------------- | ---------------------------------- |
| `url`         | Target URL                         |
| `status`      | `submitted` / `captcha_blocked` / `no_form` / `error` |
| `submitted_at`| UTC ISO-8601 timestamp             |
| `notes`       | Agent's explanation of the outcome |

---

## License

Private — internal use only.
