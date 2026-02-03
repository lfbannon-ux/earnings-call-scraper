#!/usr/bin/env python3
"""
AUB Group Peer Earnings Monitor — Seeking Alpha Edition
Uses Playwright + stealth to scrape SA earnings transcripts,
Claude API to analyse for AUB-relevant signals, emails summary.

Deploy on Railway as a cron job.
"""

import os
import sys
import re
import json
import time
import random
import asyncio
import smtplib
import logging
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from bs4 import BeautifulSoup
import requests

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------

FOCUS_COMPANY = "AUB Group (ASX: AUB)"
FOCUS_DESCRIPTION = """AUB Group is an Australasian insurance broker network.
Key exposures: Business/ISR/Strata/Farm (property ~45-50% of book),
Liability/WC/Motor/PI (casualty ~27%), with CGU/IAG (43%), Lloyd's (16%),
Allianz (12%), QBE (8%) as key panel insurers."""

PEERS = {
    "AJG":   {"name": "Arthur J. Gallagher & Co.",  "sa_slug": "AJG"},
    "BRO":   {"name": "Brown & Brown, Inc.",         "sa_slug": "BRO"},
    "MMC":   {"name": "Marsh McLennan Companies",    "sa_slug": "MMC"},
    "AON":   {"name": "Aon plc",                     "sa_slug": "AON"},
    "AUBBF": {"name": "AUB Group (OTC)",             "sa_slug": "AUBBF"},
    "SFGLF": {"name": "Steadfast Group (OTC)",       "sa_slug": "SFGLF"},
}

LOOKBACK_DAYS = int(os.environ.get("LOOKBACK_DAYS", "21"))

# Email
SMTP_USER     = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
EMAIL_TO      = os.environ.get("EMAIL_TO", "lfbannon@gmail.com")
SMTP_HOST     = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT     = int(os.environ.get("SMTP_PORT", "587"))

# SA cookies from your browser
SA_COOKIES = {
    "session_id":          os.environ.get("SA_SESSION_ID", ""),
    "user_id":             os.environ.get("SA_USER_ID", ""),
    "user_remember_token": os.environ.get("SA_REMEMBER_TOKEN", ""),
    "machine_cookie":      os.environ.get("SA_MACHINE_COOKIE", ""),
    "user_cookie_key":     os.environ.get("SA_COOKIE_KEY", ""),
    "sapu":                os.environ.get("SA_SAPU", ""),
}

# Claude API
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# Tickers override
TICKERS_ENV = os.environ.get("TICKERS", "")

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# PLAYWRIGHT — STEALTH BROWSER WITH SA COOKIES
# ---------------------------------------------------------------------------

# Global references kept alive outside context manager
_pw_instance = None
_browser_instance = None

async def create_browser_context():
    """Launch stealth Playwright browser with SA cookies injected."""
    global _pw_instance, _browser_instance
    from playwright.async_api import async_playwright

    try:
        from playwright_stealth import Stealth
        stealth = Stealth()
        # use_async wraps async_playwright() — must be used as context manager
        _pw_instance = stealth.use_async(async_playwright())
        pw = await _pw_instance.__aenter__()
        log.info("  Stealth mode: playwright_stealth active")
    except Exception as e:
        log.warning(f"  Stealth import failed ({e}), using manual evasions")
        _pw_instance = async_playwright()
        pw = await _pw_instance.__aenter__()

    browser = await pw.chromium.launch(
        headless=True,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
        ],
    )
    _browser_instance = browser

    context = await browser.new_context(
        viewport={"width": 1920, "height": 1080},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        locale="en-US",
        timezone_id="America/New_York",
    )

    # Extra manual evasions on top of stealth plugin
    await context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        if (!window.chrome) { window.chrome = { runtime: {} }; }
        Object.defineProperty(navigator, 'plugins', {
            get: () => [1, 2, 3, 4, 5]
        });
        Object.defineProperty(navigator, 'languages', {
            get: () => ['en-US', 'en']
        });
        const originalQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (parameters) =>
            parameters.name === 'notifications'
                ? Promise.resolve({ state: Notification.permission })
                : originalQuery(parameters);
    """)

    # Inject SA cookies
    cookies_to_add = []
    for name, value in SA_COOKIES.items():
        if value:
            cookies_to_add.append({
                "name": name,
                "value": value,
                "domain": ".seekingalpha.com",
                "path": "/",
                "httpOnly": False,
                "secure": True,
                "sameSite": "Lax",
            })

    if cookies_to_add:
        await context.add_cookies(cookies_to_add)
        log.info(f"  Injected {len(cookies_to_add)} SA cookies")
    else:
        log.warning("  No SA cookies — will only get preview content")

    return _pw_instance, browser, context


async def cleanup_browser(pw_ref, browser):
    """Clean up browser and playwright."""
    try:
        await browser.close()
    except Exception:
        pass
    try:
        await pw_ref.__aexit__(None, None, None)
    except Exception:
        pass


async def human_delay(min_s=2, max_s=5):
    await asyncio.sleep(random.uniform(min_s, max_s))


async def scroll_page(page):
    for _ in range(random.randint(2, 4)):
        await page.evaluate("window.scrollBy(0, window.innerHeight * 0.6)")
        await asyncio.sleep(random.uniform(0.5, 1.5))


# ---------------------------------------------------------------------------
# SCRAPE SA — TRANSCRIPT LISTING
# ---------------------------------------------------------------------------

async def get_transcript_links(context, ticker, sa_slug):
    """Get recent transcript links for a ticker from SA."""
    url = f"https://seekingalpha.com/symbol/{sa_slug}/earnings/transcripts"
    log.info(f"  Listing: {url}")

    page = await context.new_page()
    try:
        await human_delay(1, 3)
        resp = await page.goto(url, wait_until="domcontentloaded", timeout=30000)

        if not resp or resp.status != 200:
            log.warning(f"  HTTP {resp.status if resp else 'None'} for {sa_slug}")
            return []

        await asyncio.sleep(3)
        await scroll_page(page)

        html = await page.content()
        soup = BeautifulSoup(html, "html.parser")

        results = []
        for link in soup.find_all("a", href=True):
            href = link.get("href", "")
            text = link.get_text(strip=True)

            if "earnings-call-transcript" in href.lower() and text and len(text) > 20:
                full_url = href if href.startswith("http") else f"https://seekingalpha.com{href}"
                full_url = full_url.split("?")[0]

                if full_url not in [r["url"] for r in results]:
                    results.append({"title": text, "url": full_url, "ticker": ticker})

        log.info(f"  Found {len(results)} transcript links")
        return results[:3]

    except Exception as e:
        log.warning(f"  Error listing {sa_slug}: {e}")
        return []
    finally:
        await page.close()


# ---------------------------------------------------------------------------
# SCRAPE SA — FULL TRANSCRIPT CONTENT
# ---------------------------------------------------------------------------

async def get_transcript_content(context, url, title):
    """Fetch full transcript from a SA article page."""
    fetch_url = url + "?part=single" if "?" not in url else url
    log.info(f"  Fetching: {fetch_url[:80]}...")

    page = await context.new_page()
    try:
        await human_delay(3, 7)
        await page.set_extra_http_headers({"Referer": "https://www.google.com/"})
        resp = await page.goto(fetch_url, wait_until="domcontentloaded", timeout=45000)

        if not resp or resp.status != 200:
            log.warning(f"  HTTP {resp.status if resp else 'None'}")
            return None, False

        await asyncio.sleep(4)
        await scroll_page(page)

        html = await page.content()
        is_paywalled = "paywall" in html.lower() and "subscribe" in html.lower()
        soup = BeautifulSoup(html, "html.parser")

        # Try multiple selectors
        body = None
        for sel in [
            {"data-test-id": "article-body"},
            {"class": re.compile(r"paywall-full-content")},
            {"id": "a-body"},
            {"class": re.compile(r"article-body")},
        ]:
            body = soup.find("div", sel)
            if body:
                break
        if not body:
            body = soup.find("article")

        if body:
            for tag in body.find_all(["script", "style", "iframe", "noscript", "svg", "button"]):
                tag.decompose()
            text = body.get_text(separator="\n", strip=True)
            if len(text) > 1000:
                log.info(f"  ✓ {len(text):,} chars (paywalled: {is_paywalled})")
                return text, is_paywalled

        # Fallback
        paras = soup.find_all("p")
        text = "\n".join(p.get_text(strip=True) for p in paras if len(p.get_text(strip=True)) > 40)
        if len(text) > 500:
            log.info(f"  ✓ {len(text):,} chars (fallback, paywalled: {is_paywalled})")
            return text, is_paywalled

        log.warning(f"  ✗ Insufficient content ({len(text)} chars)")
        return None, is_paywalled

    except Exception as e:
        log.warning(f"  Error fetching transcript: {e}")
        return None, False
    finally:
        await page.close()


# ---------------------------------------------------------------------------
# MAIN SCRAPING FLOW
# ---------------------------------------------------------------------------

async def scrape_all_transcripts(tickers_to_scan):
    log.info("Starting browser...")
    pw, browser, context = await create_browser_context()
    transcripts = []

    try:
        for ticker, info in tickers_to_scan.items():
            log.info(f"\n--- {ticker} ({info['name']}) ---")

            links = await get_transcript_links(context, ticker, info["sa_slug"])
            if not links:
                continue

            for link in links[:1]:
                content, paywalled = await get_transcript_content(
                    context, link["url"], link["title"]
                )
                if content and len(content) > 1000:
                    transcripts.append({
                        "ticker": ticker,
                        "name": info["name"],
                        "title": link["title"],
                        "url": link["url"],
                        "content": content,
                        "content_length": len(content),
                        "paywalled": paywalled,
                    })
                    break
    finally:
        await cleanup_browser(pw, browser)

    return transcripts


# ---------------------------------------------------------------------------
# CLAUDE API ANALYSIS
# ---------------------------------------------------------------------------

AUB_PROMPT = """You are an equity research analyst covering AUB Group (ASX: AUB),
an Australian insurance broker network. You are reviewing a peer company's earnings
call transcript to identify early warning signals for AUB.

AUB CONTEXT:
{focus_description}

PEER: {peer_name} ({peer_ticker})
TRANSCRIPT: {title}

Produce a CONCISE summary (max 400 words):

**{peer_ticker} — {title}**

HEADLINE: One sentence on the most important read-through for AUB.

KEY SIGNALS FOR AUB:
🟢 Positive (2-4 bullets of good news for AUB)
🔴 Negative (2-4 bullets of bad news / risks for AUB)

SPECIFIC DATA POINTS:
- Premium rate changes by line (property, casualty, specialty)
- Organic growth rates, especially APAC/Australia
- M&A activity, multiples, pipeline
- Margin trends
- Any mentions of Australia, APAC, competitors

BOTTOM LINE: 2-3 sentences on what this means for AUB.

Be specific with numbers. Only include what's in the transcript.

TRANSCRIPT:
{transcript_text}
"""


def analyse_with_claude(transcript):
    if not ANTHROPIC_API_KEY:
        return keyword_fallback(transcript)

    text = transcript["content"][:150000]
    prompt = AUB_PROMPT.format(
        focus_description=FOCUS_DESCRIPTION,
        peer_name=transcript["name"],
        peer_ticker=transcript["ticker"],
        title=transcript["title"],
        transcript_text=text,
    )

    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 1500,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=120,
        )
        if resp.status_code == 200:
            return resp.json()["content"][0]["text"]
        else:
            log.warning(f"  Claude error: {resp.status_code}")
            return keyword_fallback(transcript)
    except Exception as e:
        log.warning(f"  Claude exception: {e}")
        return keyword_fallback(transcript)


def keyword_fallback(transcript):
    text = transcript["content"].lower()
    kw = {
        "Property rates": ["property rate", "property premium", "property pricing"],
        "Casualty rates": ["casualty rate", "casualty premium", "casualty pricing"],
        "Organic growth": ["organic growth", "organic revenue"],
        "M&A": ["acquisition", "acquired", "term sheet", "pipeline"],
        "Margins": ["margin expansion", "margin compression", "ebitda margin"],
        "APAC": ["australia", "apac", "asia pacific", "pacific"],
        "Reinsurance": ["reinsurance", "reinsurer", "property cat"],
    }
    findings = []
    for cat, terms in kw.items():
        count = sum(text.count(t) for t in terms)
        if count > 0:
            for t in terms:
                idx = text.find(t)
                if idx != -1:
                    s = max(0, idx - 80)
                    e = min(len(text), idx + len(t) + 150)
                    snippet = re.sub(r"\s+", " ", transcript["content"][s:e].strip())
                    findings.append(f"**{cat}** ({count}x): ...{snippet}...")
                    break

    header = f"**{transcript['ticker']} — {transcript['title']}**\n"
    header += "(Keyword fallback — set ANTHROPIC_API_KEY for AI summary)\n\n"
    return header + "\n".join(findings) if findings else header + "No key terms found."


# ---------------------------------------------------------------------------
# EMAIL
# ---------------------------------------------------------------------------

def send_email(subject, html_body, text_body=None):
    if not SMTP_USER or not SMTP_PASSWORD:
        log.error("SMTP not configured")
        print(f"\nSUBJECT: {subject}\n{'='*60}\n{text_body or html_body}")
        return False

    msg = MIMEMultipart("alternative")
    msg["From"] = SMTP_USER
    msg["To"] = EMAIL_TO
    msg["Subject"] = subject
    if text_body:
        msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_USER, EMAIL_TO.split(","), msg.as_string())
        log.info(f"✓ Email sent to {EMAIL_TO}")
        return True
    except Exception as e:
        log.error(f"✗ Email failed: {e}")
        return False


def build_email(analyses, transcripts_found, total_peers):
    now = datetime.now(timezone.utc).strftime("%d %b %Y %H:%M UTC")

    text_parts = [
        "AUB PEER EARNINGS MONITOR",
        f"Generated: {now}",
        f"Transcripts: {transcripts_found}/{total_peers} peers",
        "=" * 60,
    ]
    for a in analyses:
        text_parts += ["", a, "", "-" * 60]
    if not analyses:
        text_parts += ["", "No new peer transcripts found."]
    text_body = "\n".join(text_parts)

    html_sections = ""
    for a in analyses:
        f = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", a)
        f = re.sub(r"🟢", '<span style="color:#16a34a">🟢</span>', f)
        f = re.sub(r"🔴", '<span style="color:#dc2626">🔴</span>', f)
        f = f.replace("\n", "<br>")
        html_sections += f"""
        <div style="background:#f9fafb; border-left:4px solid #2563eb; padding:16px;
                     margin:16px 0; border-radius:4px; font-size:14px; line-height:1.7;">
            {f}
        </div>"""

    if not analyses:
        html_sections = f"""
        <div style="background:#fef9c3; border-left:4px solid #eab308; padding:16px;
                     margin:16px 0; border-radius:4px;">
            No new peer transcripts found in the last {LOOKBACK_DAYS} days.
        </div>"""

    html_body = f"""<html><body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
        max-width:700px; margin:0 auto; color:#1a1a1a;">
        <div style="background:#1e3a5f; color:white; padding:20px; border-radius:8px 8px 0 0;">
            <h2 style="margin:0; font-size:20px;">📊 AUB Peer Earnings Monitor</h2>
            <p style="margin:8px 0 0; opacity:0.8; font-size:13px;">
                {now} · {transcripts_found}/{total_peers} peers · Lookback: {LOOKBACK_DAYS}d</p>
        </div>
        <div style="padding:16px;">
            {html_sections}
            <div style="margin-top:24px; padding-top:16px; border-top:1px solid #e5e7eb;
                         font-size:12px; color:#6b7280;">
                Peers: {', '.join(PEERS.keys())} · Source: Seeking Alpha
            </div>
        </div></body></html>"""

    return html_body, text_body


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

async def async_main():
    log.info("=" * 60)
    log.info("AUB PEER EARNINGS MONITOR — Seeking Alpha")
    log.info(f"Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    log.info("=" * 60)

    if TICKERS_ENV:
        tickers_to_scan = {}
        for t in TICKERS_ENV.split(","):
            t = t.strip()
            if t in PEERS:
                tickers_to_scan[t] = PEERS[t]
            else:
                tickers_to_scan[t] = {"name": t, "sa_slug": t}
    else:
        tickers_to_scan = PEERS.copy()

    log.info(f"Peers: {', '.join(tickers_to_scan.keys())}")
    log.info(f"Email: {SMTP_USER or '(none)'} → {EMAIL_TO}")
    log.info(f"Claude API: {'yes' if ANTHROPIC_API_KEY else 'no'}")
    log.info(f"SA cookies: {sum(1 for v in SA_COOKIES.values() if v)}/6")

    if "--dry-run" in sys.argv:
        log.info("\nDRY RUN — test email")
        test = (
            "**AJG — Arthur J. Gallagher Q4 2025 Earnings Call**\n\n"
            "HEADLINE: Property reinsurance rates down in the teens globally.\n\n"
            "🟢 Positive:\n• Casualty rates stable (+5-7% US)\n"
            "• Strong retention\n• Risk mgmt organic +7%\n\n"
            "🔴 Negative:\n• Property cat rates down in teens\n"
            "• APAC weakest at +3%\n• $10bn M&A firepower\n\n"
            "BOTTOM LINE: Property softening hits ~45% of AUB's book. "
            "Casualty firmness provides partial offset."
        )
        html, text = build_email([test], 1, len(tickers_to_scan))
        send_email(f"[TEST] AUB Peer Monitor — {datetime.now().strftime('%d %b %Y')}", html, text)
        return

    transcripts = await scrape_all_transcripts(tickers_to_scan)
    log.info(f"\nRESULTS: {len(transcripts)} transcripts")

    if not transcripts:
        html, text = build_email([], 0, len(tickers_to_scan))
        send_email(f"AUB Peer Monitor — No transcripts — {datetime.now().strftime('%d %b')}", html, text)
        return

    analyses = []
    for t in transcripts:
        log.info(f"\nAnalysing {t['ticker']} ({t['content_length']:,} chars)...")
        a = analyse_with_claude(t)
        if a:
            analyses.append(a)
            log.info(f"  ✓ Done")

    tickers_found = list(set(t["ticker"] for t in transcripts))
    subject = f"AUB Peer Monitor — {', '.join(tickers_found)} — {datetime.now().strftime('%d %b %Y')}"
    html, text = build_email(analyses, len(transcripts), len(tickers_to_scan))
    send_email(subject, html, text)

    log.info("\nCOMPLETE")


def main():
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
