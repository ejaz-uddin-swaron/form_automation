"""
agent.py – The autonomous contact-form submission agent.

For each target URL the agent:
  1.  Navigates to the page and locates the contact form (or a link to it).
  2.  Inspects form fields via browser-use's accessibility-tree engine.
  3.  Fills in the sender payload (name, email, phone, subject, message).
  4.  Clicks the submit button and waits for confirmation or redirect.
  5.  Detects CAPTCHA walls and gracefully skips them.

All results are persisted to SQLite via db.ResultsDB.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

from browser_use.llm.google.chat import ChatGoogle
from browser_use import Agent, Browser

from config import Settings
from db import ResultsDB

try:
    from playwright_stealth import stealth_async

    _HAS_STEALTH = True
except ImportError:
    _HAS_STEALTH = False

log = logging.getLogger("contact-agent")



# ── Data structures ──────────────────────────────────────────
@dataclass
class Target:
    url: str
    company: str = ""


@dataclass
class SubmissionResult:
    url: str
    status: str  # "submitted" | "captcha_blocked" | "no_form" | "error"
    company: str = ""
    detail: Optional[str] = None


# ── Prompt builder ───────────────────────────────────────────
def _build_task_prompt(target: Target | str, cfg: Settings) -> str:
    s = cfg.sender
    url = target.url if isinstance(target, Target) else target
    company_context = f"\nTARGET COMPANY: {target.company}" if isinstance(target, Target) and target.company else ""
    return f"""\
You are an autonomous web agent whose ONLY job is to submit a contact form.

TARGET URL: {url}{company_context}

────────────────────────────────────────────
STEP 1 – FIND THE CONTACT FORM
────────────────────────────────────────────
• If the current page already contains a visible contact form, proceed to Step 2.
• Otherwise look for links or buttons labelled "Contact", "Contact Us",
  "Get in Touch", "Reach Out", "Message Us", or similar. Click the most
  relevant one and wait for the page to load.
• If you land on a page with multiple contact options (email, phone, form),
  find and interact with the web form.
• If after 3 attempts you cannot find any contact form, report
  STATUS=no_form and stop.

────────────────────────────────────────────
STEP 2 – FILL IN THE FORM
────────────────────────────────────────────
Map the following payload to the appropriate form fields.  Fields on the
page may have slightly different labels; use your best judgement.

  • First Name   → {s.first_name}
  • Last Name    → {s.last_name}
  • Full Name    → {s.full_name}          (use if there is a single "Name" field)
  • Email        → {s.email}
  • Phone        → {s.phone}
  • Company      → {s.company}
  • Subject      → {s.resolved_subject}
  • Message      → {s.resolved_message}

Rules:
  – Only fill fields that exist on the form. Skip any that are absent.
  – If there is a dropdown or radio group (e.g. "Reason for contact"),
    pick the closest match or the first option.
  – Do NOT check any marketing-consent / newsletter checkboxes.
  – If the form spans multiple steps/pages, fill each step and click Next.

────────────────────────────────────────────
STEP 3 – SUBMIT
────────────────────────────────────────────
• Click the submit / send button.
• Wait up to 10 seconds for a confirmation message, a "thank you" banner,
  or a URL change that indicates success.
• If you see a success indicator, report STATUS=submitted.

────────────────────────────────────────────
STEP 4 – CAPTCHA DETECTION
────────────────────────────────────────────
• If at ANY point you detect a CAPTCHA challenge (reCAPTCHA, hCaptcha,
  Cloudflare Turnstile, image puzzles, "I am not a robot" checkboxes),
  DO NOT attempt to solve it.
• Immediately report STATUS=captcha_blocked and stop.

────────────────────────────────────────────
OUTPUT FORMAT (mandatory)
────────────────────────────────────────────
When finished, output exactly ONE line in this format:

  STATUS=<submitted|captcha_blocked|no_form|error> | DETAIL=<brief explanation>

Examples:
  STATUS=submitted | DETAIL=Form submitted successfully, saw "Thank you" message
  STATUS=captcha_blocked | DETAIL=reCAPTCHA v2 detected on /contact
  STATUS=no_form | DETAIL=No contact form found after checking 3 pages
  STATUS=error | DETAIL=Form submission returned a 500 server error
"""


# ── Single-URL handler ───────────────────────────────────────
async def submit_one(
    target: Target | str,
    cfg: Settings,
    db: ResultsDB,
    browser: Browser,
) -> SubmissionResult:
    """Run the browser-use agent against a single target."""
    if isinstance(target, str):
        target = Target(url=target)

    label = f"{target.company} ({target.url})" if target.company else target.url
    log.info("▶  Processing %s", label)
    task_prompt = _build_task_prompt(target, cfg)

    llm = ChatGoogle(
        model=cfg.llm_model,
        api_key=cfg.gemini_api_key,
    )

    fallback_model = (
        "gemini-3.5-flash-lite"
        if cfg.llm_model != "gemini-3.5-flash-lite"
        else "gemini-3.5-flash"
    )
    fallback_llm = ChatGoogle(
        model=fallback_model,
        api_key=cfg.gemini_api_key,
    )

    agent = Agent(
        task=task_prompt,
        llm=llm,
        fallback_llm=fallback_llm,
        browser=browser,
    )

    try:
        history = await agent.run(max_steps=cfg.max_agent_steps)
        raw = history.final_result() or ""

        # Parse the STATUS=… line from the agent's answer
        status, detail = _parse_agent_output(raw)
        result = SubmissionResult(
            url=target.url,
            company=target.company,
            status=status,
            detail=detail,
        )

    except Exception as exc:
        log.exception("Agent crashed on %s", target.url)
        result = SubmissionResult(
            url=target.url,
            company=target.company,
            status="error",
            detail=str(exc)[:300],
        )

    # Persist
    db.upsert(
        url=result.url,
        company=result.company,
        status=result.status,
        notes=result.detail,
    )
    _log_result(result)
    return result


# ── Output parser ────────────────────────────────────────────
def _parse_agent_output(raw: str) -> tuple[str, str]:
    """
    Extract STATUS and DETAIL from the agent's free-text answer.
    Gracefully falls back to 'error' if the format is unexpected.
    """
    status = "error"
    detail = raw.strip()[:500] if raw else "No output from agent"

    for line in raw.splitlines():
        line = line.strip()
        if line.upper().startswith("STATUS="):
            parts = line.split("|", 1)
            status_part = parts[0].split("=", 1)[1].strip().lower()
            if status_part in ("submitted", "captcha_blocked", "no_form", "error"):
                status = status_part
            if len(parts) > 1 and "DETAIL=" in parts[1].upper():
                detail = parts[1].split("=", 1)[1].strip()
            break

    return status, detail


# ── Pretty logging ───────────────────────────────────────────
_STATUS_ICONS = {
    "submitted": "✅",
    "captcha_blocked": "🛡️",
    "no_form": "⚠️",
    "error": "❌",
}


def _log_result(r: SubmissionResult) -> None:
    icon = _STATUS_ICONS.get(r.status, "❓")
    label = f"{r.company} [{r.url}]" if r.company else r.url
    log.info("%s  [%s]  %s  →  %s", icon, r.status.upper(), label, r.detail)


# ── Batch runner ─────────────────────────────────────────────
async def run_batch(
    targets: list[Target | str],
    cfg: Settings,
    db: ResultsDB,
    skip_existing: bool = False,
) -> list[SubmissionResult]:
    """Process every target sequentially (one browser, fresh context each time)."""

    browser = Browser(
        headless=cfg.headless,
        disable_security=True,
    )

    results: list[SubmissionResult] = []
    total = len(targets)
    for idx, item in enumerate(targets, 1):
        target = item if isinstance(item, Target) else Target(url=item)
        target_label = f"{target.company} ({target.url})" if target.company else target.url

        if skip_existing and db.is_already_done(target.url):
            log.info("⏩ [%d/%d] Skipping already processed: %s", idx, total, target_label)
            continue

        log.info("━━━ [%d/%d] %s ━━━", idx, total, target_label)
        result = await submit_one(target, cfg, db, browser)
        results.append(result)

        # Short cooldown between sites to appear more human
        if idx < total:
            await asyncio.sleep(2)

    try:
        await browser.close()
    except Exception:
        pass

    return results
