#!/usr/bin/env python3
"""
AUB Peer Earnings Monitor — Seeking Alpha JSON API approach.

Uses SA's internal JSON API endpoints (same ones their frontend calls)
with authenticated session cookies. No browser/Playwright needed.
"""

import os
import re
import json
import time
import random
import logging
import smtplib
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# LOGGING
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-5s  %(message)s")
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
EMAIL_TO = os.environ.get("EMAIL_TO", SMTP_USER)
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
LOOKBACK_DAYS = int(os.environ.get("LOOKBACK_DAYS", "21"))
TICKERS_RAW = os.environ.get("TICKERS", "AJG,BRO,MMC,AON,AUBBF,SFGLF")

# SA cookie values from env
SA_COOKIES = {
    "_sasource":        "unknown",
    "session_id":       os.environ.get("SA_SESSION_ID", ""),
    "user_id":          os.environ.get("SA_USER_ID", ""),
    "user_remember_token": os.environ.get("SA_REMEMBER_TOKEN", ""),
    "machine_cookie":   os.environ.get("SA_MACHINE_COOKIE", ""),
    "_sp_ses.1cf2":     "*",
    "sapu":             os.environ.get("SA_SAPU", "12"),
    "gk_user_access":   "1",
    "gk_user_access_unpaid": "1",
}

# Add the cookie key if provided
SA_COOKIE_KEY = os.environ.get("SA_COOKIE_KEY", "")
if SA_COOKIE_KEY:
    SA_COOKIES[SA_COOKIE_KEY] = "1"

# Ticker -> full name and SA slug mapping
TICKER_INFO = {
    "AJG":   {"name": "Arthur J. Gallagher & Co.", "sa_slug": "ajg"},
    "BRO":   {"name": "Brown & Brown, Inc.", "sa_slug": "bro"},
    "MMC":   {"name": "Marsh McLennan Companies", "sa_slug": "mmc"},
    "AON":   {"name": "Aon plc", "sa_slug": "aon"},
    "AUBBF": {"name": "AUB Group (OTC)", "sa_slug": "aubbf"},
    "SFGLF": {"name": "Steadfast Group (OTC)", "sa_slug": "sfglf"},
    "WTW":   {"name": "Willis Towers Watson", "sa_slug": "wtw"},
}

TICKERS = [t.strip().upper() for t in TICKERS_RAW.split(",") if t.strip()]
CUTOFF = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)

# ---------------------------------------------------------------------------
# HTTP SESSION SETUP
# ---------------------------------------------------------------------------

def build_session():
    """Create a requests.Session with SA cookies and browser-like headers."""
    s = requests.Session()

    # Set cookies
    for name, value in SA_COOKIES.items():
        if value:
            s.cookies.set(name, value, domain=".seekingalpha.com")

    # Browser-like headers — critical for bypassing bot detection
    s.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": "https://seekingalpha.com/",
        "Origin": "https://seekingalpha.com",
        "DNT": "1",
        "Connection": "keep-alive",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        "Sec-CH-UA": '"Chromium";v="131", "Not_A Brand";v="24"',
        "Sec-CH-UA-Mobile": "?0",
        "Sec-CH-UA-Platform": '"Windows"',
    })

    cookie_count = sum(1 for v in SA_COOKIES.values() if v)
    log.info(f"  Session: {cookie_count} cookies loaded")

    # Warm up: hit homepage to collect cf_clearance and any redirect cookies
    try:
        log.info("  Warming up session on SA homepage...")
        warm = s.get(
            "https://seekingalpha.com/",
            headers={"Accept": "text/html,application/xhtml+xml"},
            timeout=30,
            allow_redirects=True,
        )
        log.info(f"  Homepage: HTTP {warm.status_code}, cookies now: {len(s.cookies)}")
        # Log any new cookies we picked up (especially cf_clearance)
        for c in s.cookies:
            if c.name.startswith("cf_") or c.name.startswith("__cf"):
                log.info(f"  Got Cloudflare cookie: {c.name}")
        time.sleep(random.uniform(3, 6))
    except Exception as e:
        log.warning(f"  Homepage warm-up failed: {e}")

    return s


# ---------------------------------------------------------------------------
# SEEKING ALPHA JSON API — TRANSCRIPT LISTING
# ---------------------------------------------------------------------------

def get_transcript_links(session, ticker):
    """
    Fetch transcript listing for a ticker via SA API.
    Uses /transcripts endpoint first (proved to work for AJG).
    """
    sa_slug = TICKER_INFO.get(ticker, {}).get("sa_slug", ticker.lower())
    transcripts = []

    # Strategy 1: dedicated /transcripts endpoint (worked for AJG)
    t_url = f"https://seekingalpha.com/api/v3/symbols/{sa_slug}/transcripts"
    params = {
        "include": "author,primaryTickers,secondaryTickers",
        "page[size]": "10",
        "page[number]": "1",
    }

    try:
        time.sleep(random.uniform(3, 6))
        resp = session.get(t_url, params=params, timeout=30)
        log.info(f"    API transcripts: HTTP {resp.status_code}")

        if resp.status_code == 200:
            data = resp.json()
            for article in data.get("data", []):
                attrs = article.get("attributes", {})
                title = attrs.get("title", "")
                pub_date_str = attrs.get("publishOn", "")

                try:
                    if pub_date_str:
                        pub_date = datetime.fromisoformat(
                            pub_date_str.replace("Z", "+00:00")
                        )
                        if pub_date < CUTOFF:
                            continue
                except (ValueError, TypeError):
                    pass

                article_id = article.get("id", "")
                slug = attrs.get("slug", "")
                if article_id:
                    transcripts.append({
                        "id": article_id,
                        "title": title,
                        "url": f"https://seekingalpha.com/article/{article_id}-{slug}",
                        "date": pub_date_str,
                    })

            if transcripts:
                log.info(f"    Found {len(transcripts)} via transcripts endpoint")
                return transcripts
        elif resp.status_code == 403:
            log.warning(f"    Rate limited on transcripts endpoint, waiting...")
            time.sleep(random.uniform(10, 20))
    except Exception as e:
        log.warning(f"    API transcripts error: {e}")

    # Strategy 3: HTML scrape of transcripts listing
    html_url = (
        f"https://seekingalpha.com/symbol/{sa_slug.upper()}/earnings/transcripts"
    )
    try:
        time.sleep(random.uniform(2, 4))
        resp = session.get(
            html_url,
            headers={"Accept": "text/html,application/xhtml+xml"},
            timeout=30,
        )
        log.info(f"    HTML listing: HTTP {resp.status_code}")

        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "lxml")
            for link in soup.find_all("a", href=True):
                href = link["href"]
                if "earnings-call-transcript" in href:
                    title = link.get_text(strip=True)
                    if not title:
                        continue
                    full_url = (
                        href
                        if href.startswith("http")
                        else f"https://seekingalpha.com{href}"
                    )
                    id_match = re.search(r"/article/(\d+)", full_url)
                    article_id = id_match.group(1) if id_match else ""
                    transcripts.append({
                        "id": article_id,
                        "title": title,
                        "url": full_url,
                        "date": "",
                    })

            if transcripts:
                transcripts = transcripts[:3]
                log.info(f"    Found {len(transcripts)} via HTML scrape")
                return transcripts
    except Exception as e:
        log.warning(f"    HTML scrape error: {e}")

    # Strategy 4: __NEXT_DATA__ from the HTML page
    try:
        if resp and resp.status_code == 200:
            match = re.search(
                r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
                resp.text,
                re.DOTALL,
            )
            if match:
                nd = json.loads(match.group(1))
                # Try common paths in SA's Next.js structure
                articles = []
                try:
                    articles = (
                        nd.get("props", {})
                        .get("pageProps", {})
                        .get("articles", {})
                        .get("data", [])
                    )
                except (AttributeError, TypeError):
                    pass

                for article in articles:
                    attrs = article.get("attributes", {})
                    title = attrs.get("title", "")
                    article_id = article.get("id", "")
                    slug = attrs.get("slug", "")
                    if article_id and "transcript" in title.lower():
                        transcripts.append({
                            "id": article_id,
                            "title": title,
                            "url": f"https://seekingalpha.com/article/{article_id}-{slug}",
                            "date": attrs.get("publishOn", ""),
                        })

                if transcripts:
                    log.info(f"    Found {len(transcripts)} via __NEXT_DATA__")
                    return transcripts
    except Exception as e:
        log.warning(f"    __NEXT_DATA__ listing error: {e}")

    return transcripts


# ---------------------------------------------------------------------------
# SEEKING ALPHA JSON API — TRANSCRIPT CONTENT
# ---------------------------------------------------------------------------

def get_transcript_content(session, transcript_info):
    """
    Fetch full transcript content via JSON API or HTML fallback.
    """
    article_id = transcript_info.get("id", "")
    url = transcript_info.get("url", "")
    title = transcript_info.get("title", "")

    # Strategy 1: JSON API for article body
    if article_id:
        content_url = f"https://seekingalpha.com/api/v3/articles/{article_id}"
        params = {
            "include": "author,primaryTickers,secondaryTickers,otherTags",
        }
        # Try the article API up to 2 times with backoff
        for attempt in range(2):
            try:
                wait = random.uniform(4, 8) if attempt == 0 else random.uniform(15, 25)
                time.sleep(wait)
                resp = session.get(content_url, params=params, timeout=30)
                log.info(f"    Article API (attempt {attempt+1}): HTTP {resp.status_code}")

                if resp.status_code == 200:
                    data = resp.json()
                    attrs = data.get("data", {}).get("attributes", {})
                    body_html = attrs.get("content", "") or attrs.get("body", "")

                    if body_html:
                        soup = BeautifulSoup(body_html, "lxml")
                        text = soup.get_text(separator="\n", strip=True)
                        if len(text) > 500:
                            log.info(f"    Got {len(text)} chars via article API")
                            return text
                    break  # Got 200 but no content — don't retry
                elif resp.status_code == 403:
                    log.warning(f"    Article API 403, backing off...")
                    continue  # Retry with longer wait
                else:
                    break  # Other error, don't retry
            except Exception as e:
                log.warning(f"    Article API error: {e}")
                break

    # Strategy 2: HTML page with ?part=single
    if url:
        fetch_url = url
        if "?part=single" not in fetch_url:
            fetch_url += "?part=single"

        try:
            time.sleep(random.uniform(6, 12))
            resp = session.get(
                fetch_url,
                headers={"Accept": "text/html,application/xhtml+xml"},
                timeout=30,
            )
            log.info(f"    HTML article: HTTP {resp.status_code}")

            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "lxml")

                body = None
                for selector in [
                    {"data-test-id": "article-body"},
                    {"class_": "paywall-full-content"},
                    {"id": "a-body"},
                    {"class_": "article-body"},
                ]:
                    body = soup.find("div", selector)
                    if body:
                        break

                if body:
                    text = body.get_text(separator="\n", strip=True)
                else:
                    paragraphs = [
                        p.get_text(strip=True)
                        for p in soup.find_all("p")
                        if len(p.get_text(strip=True)) > 40
                    ]
                    text = "\n".join(paragraphs)

                if len(text) > 500:
                    log.info(f"    Got {len(text)} chars via HTML page")
                    return text

                # Try __NEXT_DATA__ embedded in the article page
                match = re.search(
                    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
                    resp.text,
                    re.DOTALL,
                )
                if match:
                    try:
                        nd = json.loads(match.group(1))
                        props = nd.get("props", {}).get("pageProps", {})
                        article = props.get("article", {}) or props.get("data", {})
                        body_html = (
                            article.get("attributes", {}).get("content", "")
                            or article.get("body", "")
                        )
                        if body_html:
                            soup2 = BeautifulSoup(body_html, "lxml")
                            text = soup2.get_text(separator="\n", strip=True)
                            if len(text) > 500:
                                log.info(f"    Got {len(text)} chars via __NEXT_DATA__")
                                return text
                    except (json.JSONDecodeError, AttributeError):
                        pass
        except Exception as e:
            log.warning(f"    HTML fetch error: {e}")

    log.warning(f"    No content retrieved for: {title}")
    return None


# ---------------------------------------------------------------------------
# MAIN SCRAPING LOOP
# ---------------------------------------------------------------------------

def scrape_all_transcripts():
    """Scrape transcripts for all configured tickers."""
    session = build_session()
    all_transcripts = []

    for ticker in TICKERS:
        info = TICKER_INFO.get(ticker, {"name": ticker, "sa_slug": ticker.lower()})
        print(f"\n--- {ticker} ({info['name']}) ---")

        links = get_transcript_links(session, ticker)

        if not links:
            log.warning(f"    No transcripts found for {ticker}")
            continue

        latest = links[0]
        log.info(f"    Latest: {latest['title']}")

        content = get_transcript_content(session, latest)

        if content:
            all_transcripts.append({
                "ticker": ticker,
                "company": info["name"],
                "title": latest["title"],
                "url": latest.get("url", ""),
                "date": latest.get("date", ""),
                "content": content,
                "content_length": len(content),
            })
            log.info(f"    OK {ticker}: {len(content)} chars")
        else:
            log.warning(f"    FAIL {ticker}: no content")

        time.sleep(random.uniform(5, 10))

    return all_transcripts


# ---------------------------------------------------------------------------
# CLAUDE ANALYSIS
# ---------------------------------------------------------------------------

CLAUDE_PROMPT = """You are an expert insurance industry analyst. Analyse this earnings call transcript
for read-throughs relevant to AUB Group (ASX: AUB), Australia's largest insurance broker network.

AUB CONTEXT:
- Property insurance: ~45-50% of GWP (Business Packages, ISR, Strata, Farm)
- Casualty insurance: ~27% of GWP (Liability, Workers' Comp, Motor, PI)
- Panel composition: CGU/IAG 43%, Lloyd's 16%, Allianz 12%, QBE 8%
- Key themes: broker consolidation, premium rate cycle, claims inflation, APAC expansion

TRANSCRIPT:
{transcript}

Provide your analysis in this format:

HEADLINE: [One sentence - the single most important read-through for AUB]

Positive signals (2-4 bullets)
Negative signals (2-4 bullets)

SPECIFIC DATA: [Extract any specific numbers on: premium rates by line, organic growth
(especially APAC/international), M&A activity/multiples paid, margins, loss ratios]

BOTTOM LINE: [2-3 sentences on what this means for AUB specifically]

Keep it under 400 words. Be specific, not generic."""


def analyse_with_claude(transcript_text):
    """Send transcript to Claude for AUB-focused analysis."""
    if not ANTHROPIC_API_KEY:
        return keyword_fallback(transcript_text)

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
                "max_tokens": 1000,
                "messages": [
                    {
                        "role": "user",
                        "content": CLAUDE_PROMPT.format(
                            transcript=transcript_text[:80000]
                        ),
                    }
                ],
            },
            timeout=120,
        )

        if resp.status_code == 200:
            data = resp.json()
            parts = [
                b["text"] for b in data.get("content", []) if b.get("type") == "text"
            ]
            return "\n".join(parts)
        else:
            log.warning(f"  Claude API: HTTP {resp.status_code} — {resp.text[:200]}")
            return keyword_fallback(transcript_text)
    except Exception as e:
        log.warning(f"  Claude API error: {e}")
        return keyword_fallback(transcript_text)


def keyword_fallback(text):
    """Simple keyword extraction when Claude is unavailable."""
    keywords = {
        "property": ["property", "property insurance", "ISR", "strata"],
        "casualty": ["casualty", "liability", "workers comp", "motor"],
        "rates": ["rate increase", "premium rate", "rate hardening", "pricing"],
        "M&A": ["acquisition", "acquire", "merger", "bolt-on", "multiple"],
        "APAC": ["asia", "pacific", "australia", "apac", "international"],
        "margins": ["margin", "operating ratio", "expense ratio", "combined ratio"],
    }

    text_lower = text.lower()
    lines = []
    for category, terms in keywords.items():
        found = [t for t in terms if t.lower() in text_lower]
        if found:
            lines.append(f"**{category}**: mentions of {', '.join(found)}")

    if lines:
        return "KEYWORD ANALYSIS (Claude unavailable):\n" + "\n".join(lines)
    return "No relevant keywords found (Claude unavailable)."


# ---------------------------------------------------------------------------
# EMAIL
# ---------------------------------------------------------------------------

def send_email(transcripts, analyses):
    """Send results via Gmail."""
    if not SMTP_USER or not SMTP_PASSWORD:
        log.warning("No SMTP credentials — skipping email")
        return

    today = datetime.now().strftime("%d %b %Y")
    ticker_str = ", ".join(TICKERS)

    subject = f"AUB Peer Monitor — {ticker_str} — {today}"

    html_parts = [
        '<div style="font-family: -apple-system, BlinkMacSystemFont, sans-serif; max-width: 700px; margin: 0 auto;">',
        f'<div style="background: #1a365d; color: white; padding: 20px; border-radius: 8px 8px 0 0;">',
        f'<h2 style="margin: 0;">AUB Peer Earnings Monitor</h2>',
        f'<p style="margin: 5px 0 0; opacity: 0.8;">{today} | {len(transcripts)} transcript(s)</p>',
        "</div>",
    ]

    if not transcripts:
        html_parts.append(
            '<div style="padding: 20px; background: #fff3cd; border: 1px solid #ffc107; margin: 10px 0; border-radius: 4px;">'
            f"<p>No new transcripts found in the last {LOOKBACK_DAYS} days for: {ticker_str}</p>"
            "</div>"
        )
    else:
        for i, t in enumerate(transcripts):
            analysis = analyses[i] if i < len(analyses) else "Analysis unavailable"
            html_parts.append(
                f'<div style="border: 1px solid #e2e8f0; border-radius: 8px; margin: 15px 0; overflow: hidden;">'
                f'<div style="background: #f7fafc; padding: 12px 16px; border-bottom: 1px solid #e2e8f0;">'
                f'<strong>{t["ticker"]}</strong> — {t["company"]}<br>'
                f'<a href="{t["url"]}" style="color: #2b6cb0;">{t["title"]}</a>'
                f'<br><span style="color: #718096; font-size: 12px;">{t.get("date", "")} | {t["content_length"]:,} chars</span>'
                f"</div>"
                f'<div style="padding: 16px; font-size: 14px; line-height: 1.6; white-space: pre-wrap;">{analysis}</div>'
                f"</div>"
            )

    html_parts.append("</div>")
    html_body = "\n".join(html_parts)

    plain_parts = [f"AUB Peer Earnings Monitor — {today}\n{'=' * 50}\n"]
    if not transcripts:
        plain_parts.append(f"No new transcripts found (last {LOOKBACK_DAYS} days)\n")
    else:
        for i, t in enumerate(transcripts):
            analysis = analyses[i] if i < len(analyses) else "Analysis unavailable"
            plain_parts.append(
                f"\n--- {t['ticker']} ({t['company']}) ---\n"
                f"{t['title']}\n{t['url']}\n\n"
                f"{analysis}\n"
            )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = SMTP_USER
    msg["To"] = EMAIL_TO
    msg.attach(MIMEText("\n".join(plain_parts), "plain"))
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_USER, EMAIL_TO, msg.as_string())
        log.info(f"Email sent to {EMAIL_TO}")
    except Exception as e:
        log.error(f"Email failed: {e}")


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main():
    log.info("=" * 60)
    log.info("AUB PEER EARNINGS MONITOR — Seeking Alpha (JSON API)")
    log.info(f"Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC")
    log.info("=" * 60)
    log.info(f"Peers: {', '.join(TICKERS)}")
    log.info(f"Email: {SMTP_USER} -> {EMAIL_TO}")
    log.info(f"Claude API: {'yes' if ANTHROPIC_API_KEY else 'no'}")

    cookie_count = sum(1 for v in SA_COOKIES.values() if v)
    log.info(f"SA cookies: {cookie_count}/{len(SA_COOKIES)}")

    transcripts = scrape_all_transcripts()

    print(f"\nRESULTS: {len(transcripts)} transcripts")

    analyses = []
    for t in transcripts:
        log.info(f"  Analysing {t['ticker']}...")
        analysis = analyse_with_claude(t["content"])
        analyses.append(analysis)

    send_email(transcripts, analyses)


if __name__ == "__main__":
    main()
