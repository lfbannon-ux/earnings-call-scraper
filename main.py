#!/usr/bin/env python3
"""
AUB Group Peer Earnings Monitor
Scrapes recent earnings call transcripts from insurance broker peers,
analyses them for signals relevant to AUB Group, and emails a summary.

Peers: AJG, BRO, MMC, AON (US), AUBBF/SFGLF (ASX via OTC)
Sources: Seeking Alpha (with cookies), Insider Monkey, Yahoo Finance (Motley Fool)

Deploy on Railway as a cron job.
"""

import os
import sys
import json
import re
import time
import random
import smtplib
import logging
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------

# Focus company
FOCUS_COMPANY = "AUB Group (ASX: AUB)"
FOCUS_DESCRIPTION = """AUB Group is an Australasian insurance broker network. 
Key exposures: Business/ISR/Strata/Farm (property ~45-50% of book), 
Liability/WC/Motor/PI (casualty ~27%), with CGU/IAG (43%), Lloyd's (16%), 
Allianz (12%), QBE (8%) as key panel insurers."""

# Peer tickers and their SA/search identifiers
PEERS = {
    "AJG":   {"name": "Arthur J. Gallagher & Co.", "sa": "AJG",   "search": "Arthur J Gallagher AJG"},
    "BRO":   {"name": "Brown & Brown, Inc.",       "sa": "BRO",   "search": "Brown Brown BRO insurance"},
    "MMC":   {"name": "Marsh McLennan Companies",  "sa": "MMC",   "search": "Marsh McLennan MMC"},
    "AON":   {"name": "Aon plc",                   "sa": "AON",   "search": "Aon AON plc"},
    "AUBBF": {"name": "AUB Group (OTC)",           "sa": "AUBBF", "search": "AUB Group AUBBF"},
    "SFGLF": {"name": "Steadfast Group (OTC)",     "sa": "SFGLF", "search": "Steadfast Group SFGLF"},
}

LOOKBACK_DAYS = int(os.environ.get("LOOKBACK_DAYS", "21"))

# Email config
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
EMAIL_TO = os.environ.get("EMAIL_TO", "lfbannon@gmail.com")
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))

# Seeking Alpha cookies (from browser)
SA_COOKIES = {
    "session_id":           os.environ.get("SA_SESSION_ID", ""),
    "user_id":              os.environ.get("SA_USER_ID", ""),
    "user_remember_token":  os.environ.get("SA_REMEMBER_TOKEN", ""),
    "machine_cookie":       os.environ.get("SA_MACHINE_COOKIE", ""),
    "user_cookie_key":      os.environ.get("SA_COOKIE_KEY", ""),
    "sapu":                 os.environ.get("SA_SAPU", ""),
}

# Claude API (for summarisation) - optional
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# Override tickers via env
TICKERS_ENV = os.environ.get("TICKERS", "")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# HTTP SESSION
# ---------------------------------------------------------------------------

def build_session():
    """Build a requests session with realistic headers."""
    s = requests.Session()
    s.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
    })
    return s

# ---------------------------------------------------------------------------
# SOURCE 1: SEEKING ALPHA (cookie-authenticated)
# ---------------------------------------------------------------------------

def sa_search_transcripts(session, ticker_info, lookback_days):
    """Search Seeking Alpha for recent earnings transcripts for a ticker."""
    sa_ticker = ticker_info["sa"]
    url = f"https://seekingalpha.com/symbol/{sa_ticker}/earnings/transcripts"
    
    cookies = {k: v for k, v in SA_COOKIES.items() if v}
    if not cookies:
        log.info("  SA: No cookies configured, skipping")
        return []
    
    try:
        time.sleep(random.uniform(2, 5))
        resp = session.get(
            url,
            cookies=cookies,
            headers={
                "Referer": "https://www.google.com/",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
            },
            timeout=30,
        )
        
        if resp.status_code != 200:
            log.info(f"  SA: HTTP {resp.status_code} for {sa_ticker}")
            return []
        
        soup = BeautifulSoup(resp.text, "html.parser")
        
        # Find transcript links
        results = []
        cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
        
        for link in soup.find_all("a", href=True):
            href = link.get("href", "")
            text = link.get_text(strip=True)
            
            if "earnings-call-transcript" in href.lower() and text:
                full_url = href if href.startswith("http") else f"https://seekingalpha.com{href}"
                results.append({
                    "title": text,
                    "url": full_url,
                    "source": "Seeking Alpha",
                    "ticker": sa_ticker,
                })
        
        log.info(f"  SA: Found {len(results)} transcript links for {sa_ticker}")
        return results[:3]  # Latest 3
        
    except Exception as e:
        log.warning(f"  SA: Error for {sa_ticker}: {e}")
        return []


def sa_fetch_transcript(session, url):
    """Fetch full transcript content from Seeking Alpha."""
    cookies = {k: v for k, v in SA_COOKIES.items() if v}
    if not cookies:
        return None
    
    try:
        time.sleep(random.uniform(3, 7))
        
        # Append ?part=single to get full transcript on one page
        if "?" not in url:
            url += "?part=single"
        
        resp = session.get(
            url,
            cookies=cookies,
            headers={"Referer": "https://seekingalpha.com/earnings/earnings-call-transcripts"},
            timeout=30,
        )
        
        if resp.status_code != 200:
            return None
        
        soup = BeautifulSoup(resp.text, "html.parser")
        
        # Try multiple selectors for article body
        body = (
            soup.find("div", {"data-test-id": "article-body"})
            or soup.find("div", {"class": re.compile(r"paywall-full-content")})
            or soup.find("article")
        )
        
        if body:
            # Clean up
            for tag in body.find_all(["script", "style", "iframe", "noscript"]):
                tag.decompose()
            text = body.get_text(separator="\n", strip=True)
            if len(text) > 500:
                return text
        
        # Fallback: get all paragraph text
        paras = soup.find_all("p")
        text = "\n".join(p.get_text(strip=True) for p in paras if len(p.get_text(strip=True)) > 30)
        return text if len(text) > 500 else None
        
    except Exception as e:
        log.warning(f"  SA fetch error: {e}")
        return None

# ---------------------------------------------------------------------------
# SOURCE 2: INSIDER MONKEY (free full transcripts)
# ---------------------------------------------------------------------------

def im_search_transcripts(session, ticker_info, lookback_days):
    """Search Insider Monkey for recent earnings call transcripts."""
    search_term = ticker_info["sa"]
    name = ticker_info["name"]
    
    try:
        time.sleep(random.uniform(1, 3))
        
        # Search Google for Insider Monkey transcripts
        query = f"site:insidermonkey.com {search_term} earnings call transcript 2025 OR 2026"
        resp = session.get(
            "https://www.google.com/search",
            params={"q": query, "num": 5},
            timeout=15,
        )
        
        results = []
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            for a in soup.find_all("a", href=True):
                href = a.get("href", "")
                if "insidermonkey.com/blog/" in href and "earnings-call-transcript" in href:
                    # Clean Google redirect URL
                    if "/url?" in href:
                        from urllib.parse import urlparse, parse_qs
                        parsed = parse_qs(urlparse(href).query)
                        href = parsed.get("q", [href])[0]
                    results.append({
                        "title": a.get_text(strip=True),
                        "url": href,
                        "source": "Insider Monkey",
                        "ticker": search_term,
                    })
        
        log.info(f"  IM: Found {len(results)} results for {search_term}")
        return results[:2]
        
    except Exception as e:
        log.warning(f"  IM: Error for {search_term}: {e}")
        return []


def im_fetch_transcript(session, url):
    """Fetch full transcript from Insider Monkey."""
    try:
        time.sleep(random.uniform(2, 4))
        resp = session.get(url, timeout=30)
        
        if resp.status_code != 200:
            return None
        
        soup = BeautifulSoup(resp.text, "html.parser")
        
        article = soup.find("div", {"class": re.compile(r"single-post-content|entry-content|article")})
        if not article:
            article = soup.find("article")
        
        if article:
            for tag in article.find_all(["script", "style", "iframe", "noscript", "nav"]):
                tag.decompose()
            text = article.get_text(separator="\n", strip=True)
            if len(text) > 500:
                return text
        
        return None
        
    except Exception as e:
        log.warning(f"  IM fetch error: {e}")
        return None

# ---------------------------------------------------------------------------
# SOURCE 3: YAHOO FINANCE / MOTLEY FOOL (free transcripts)
# ---------------------------------------------------------------------------

def yf_search_transcripts(session, ticker_info, lookback_days):
    """Search for transcripts on Yahoo Finance (Motley Fool syndication)."""
    ticker = ticker_info["sa"]
    
    try:
        time.sleep(random.uniform(1, 3))
        
        query = f"site:finance.yahoo.com {ticker} earnings call transcript 2025 OR 2026"
        resp = session.get(
            "https://www.google.com/search",
            params={"q": query, "num": 5},
            timeout=15,
        )
        
        results = []
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            for a in soup.find_all("a", href=True):
                href = a.get("href", "")
                if "finance.yahoo.com" in href and "earnings" in href.lower() and "transcript" in href.lower():
                    if "/url?" in href:
                        from urllib.parse import urlparse, parse_qs
                        parsed = parse_qs(urlparse(href).query)
                        href = parsed.get("q", [href])[0]
                    results.append({
                        "title": a.get_text(strip=True),
                        "url": href,
                        "source": "Yahoo Finance",
                        "ticker": ticker,
                    })
        
        log.info(f"  YF: Found {len(results)} results for {ticker}")
        return results[:2]
        
    except Exception as e:
        log.warning(f"  YF: Error for {ticker}: {e}")
        return []


def yf_fetch_transcript(session, url):
    """Fetch transcript from Yahoo Finance."""
    try:
        time.sleep(random.uniform(2, 4))
        resp = session.get(url, timeout=30)
        
        if resp.status_code != 200:
            return None
        
        soup = BeautifulSoup(resp.text, "html.parser")
        
        body = soup.find("div", {"class": re.compile(r"body|article-body|caas-body")})
        if not body:
            body = soup.find("article")
        
        if body:
            for tag in body.find_all(["script", "style", "iframe", "noscript"]):
                tag.decompose()
            text = body.get_text(separator="\n", strip=True)
            if len(text) > 500:
                return text
        
        return None
        
    except Exception as e:
        log.warning(f"  YF fetch error: {e}")
        return None

# ---------------------------------------------------------------------------
# TRANSCRIPT DISCOVERY & FETCHING
# ---------------------------------------------------------------------------

def find_and_fetch_transcripts(tickers_to_scan):
    """
    For each peer ticker, search multiple sources for recent transcripts.
    Returns list of {ticker, name, title, url, source, content}.
    """
    session = build_session()
    transcripts = []
    seen_urls = set()
    
    for ticker, info in tickers_to_scan.items():
        log.info(f"Searching for {ticker} ({info['name']})...")
        
        # Search all sources
        candidates = []
        candidates.extend(sa_search_transcripts(session, info, LOOKBACK_DAYS))
        candidates.extend(im_search_transcripts(session, info, LOOKBACK_DAYS))
        candidates.extend(yf_search_transcripts(session, info, LOOKBACK_DAYS))
        
        if not candidates:
            log.info(f"  No transcript links found for {ticker}")
            continue
        
        # Deduplicate and fetch content (try first available)
        for c in candidates:
            url = c["url"]
            if url in seen_urls:
                continue
            seen_urls.add(url)
            
            log.info(f"  Fetching: {c['source']} - {c.get('title', url)[:80]}")
            
            content = None
            if c["source"] == "Seeking Alpha":
                content = sa_fetch_transcript(session, url)
            elif c["source"] == "Insider Monkey":
                content = im_fetch_transcript(session, url)
            elif c["source"] == "Yahoo Finance":
                content = yf_fetch_transcript(session, url)
            
            if content and len(content) > 1000:
                transcripts.append({
                    "ticker": ticker,
                    "name": info["name"],
                    "title": c.get("title", f"{ticker} Earnings Call"),
                    "url": url,
                    "source": c["source"],
                    "content": content,
                    "content_length": len(content),
                })
                log.info(f"  ✓ Got transcript: {len(content)} chars from {c['source']}")
                break  # One per ticker is enough
            else:
                log.info(f"  ✗ No usable content from {c['source']}")
    
    return transcripts

# ---------------------------------------------------------------------------
# ANALYSIS (Claude API or fallback keyword extraction)
# ---------------------------------------------------------------------------

AUB_ANALYSIS_PROMPT = """You are an equity research analyst covering AUB Group (ASX: AUB), 
an Australian insurance broker network. You are reviewing a peer company's earnings call 
transcript to identify early warning signals — both positive and negative — for AUB.

AUB CONTEXT:
{focus_description}

PEER: {peer_name} ({peer_ticker})
TRANSCRIPT TITLE: {title}

Analyse the transcript below and produce a CONCISE summary (max 400 words) structured as:

**{peer_ticker} — {title}**

HEADLINE: One sentence on the most important read-through for AUB.

KEY SIGNALS FOR AUB:
🟢 Positive (list 2-4 bullet points of things that are good news for AUB)
🔴 Negative (list 2-4 bullet points of things that are bad news or risks for AUB)

SPECIFIC DATA POINTS:
- Premium rate changes by line (property, casualty, specialty)
- Organic growth rates and geographic breakdown (especially APAC/Australia)
- M&A activity, multiples, pipeline
- Margin trends
- Any direct mentions of Australia, APAC, or competitors

BOTTOM LINE: 2-3 sentences on what this means for AUB's outlook.

Be specific with numbers. Only include what's actually in the transcript — don't speculate.

TRANSCRIPT:
{transcript_text}
"""


def analyse_with_claude(transcript):
    """Use Claude API to analyse a transcript for AUB relevance."""
    if not ANTHROPIC_API_KEY:
        return analyse_keyword_fallback(transcript)
    
    # Truncate transcript to fit context window (~150k chars ≈ ~40k tokens)
    text = transcript["content"][:150000]
    
    prompt = AUB_ANALYSIS_PROMPT.format(
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
            data = resp.json()
            return data["content"][0]["text"]
        else:
            log.warning(f"  Claude API error: {resp.status_code} {resp.text[:200]}")
            return analyse_keyword_fallback(transcript)
            
    except Exception as e:
        log.warning(f"  Claude API exception: {e}")
        return analyse_keyword_fallback(transcript)


def analyse_keyword_fallback(transcript):
    """Simple keyword extraction when Claude API is not available."""
    text = transcript["content"].lower()
    
    keywords = {
        "property": ["property rate", "property premium", "property pricing", "property renewal"],
        "casualty": ["casualty rate", "casualty premium", "casualty pricing", "casualty loss"],
        "organic growth": ["organic growth", "organic revenue"],
        "m&a": ["acquisition", "acquired", "merger", "term sheet", "pipeline"],
        "margin": ["margin expansion", "margin compression", "ebitda margin", "operating margin"],
        "australia": ["australia", "apac", "asia pacific", "pacific"],
        "reinsurance": ["reinsurance", "reinsurer", "cat rate", "property cat"],
        "rate": ["rate increase", "rate decrease", "pricing", "premium rate"],
    }
    
    findings = []
    for category, terms in keywords.items():
        matches = []
        for term in terms:
            idx = text.find(term)
            while idx != -1:
                start = max(0, idx - 100)
                end = min(len(text), idx + len(term) + 200)
                snippet = transcript["content"][start:end].strip()
                snippet = re.sub(r"\s+", " ", snippet)
                matches.append(f"...{snippet}...")
                idx = text.find(term, idx + 1)
        
        if matches:
            findings.append(f"**{category.upper()}** ({len(matches)} mentions):")
            for m in matches[:2]:
                findings.append(f"  → {m[:200]}")
    
    if findings:
        header = f"**{transcript['ticker']} — {transcript['title']}**\n"
        header += f"Source: {transcript['source']} | Length: {transcript['content_length']:,} chars\n"
        header += "(Keyword analysis — no Claude API key configured)\n\n"
        return header + "\n".join(findings)
    else:
        return f"**{transcript['ticker']}**: Transcript found but no key insurance terms detected."

# ---------------------------------------------------------------------------
# EMAIL
# ---------------------------------------------------------------------------

def send_email(subject, html_body, text_body=None):
    """Send email via SMTP."""
    if not SMTP_USER or not SMTP_PASSWORD:
        log.error("SMTP credentials not configured. Set SMTP_USER and SMTP_PASSWORD.")
        # Print to stdout as fallback
        print("\n" + "=" * 60)
        print(f"EMAIL SUBJECT: {subject}")
        print("=" * 60)
        print(text_body or html_body)
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


def build_email(analyses, transcripts_found, transcripts_total):
    """Build the HTML email from analysis results."""
    now = datetime.now(timezone.utc).strftime("%d %b %Y %H:%M UTC")
    
    # Plain text version
    text_parts = [
        f"AUB PEER EARNINGS MONITOR",
        f"Generated: {now}",
        f"Lookback: {LOOKBACK_DAYS} days",
        f"Transcripts found: {transcripts_found}/{transcripts_total} peers",
        "",
        "=" * 60,
    ]
    
    for analysis in analyses:
        text_parts.append("")
        text_parts.append(analysis)
        text_parts.append("")
        text_parts.append("-" * 60)
    
    if not analyses:
        text_parts.append("")
        text_parts.append("No new peer earnings call transcripts found in the lookback period.")
    
    text_body = "\n".join(text_parts)
    
    # HTML version
    html_analyses = ""
    for analysis in analyses:
        # Convert markdown-style formatting to HTML
        formatted = analysis
        formatted = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", formatted)
        formatted = re.sub(r"🟢", r'<span style="color:#22c55e">🟢</span>', formatted)
        formatted = re.sub(r"🔴", r'<span style="color:#ef4444">🔴</span>', formatted)
        formatted = formatted.replace("\n", "<br>")
        
        html_analyses += f"""
        <div style="background:#f8f9fa; border-left:4px solid #2563eb; padding:16px; 
                     margin:16px 0; border-radius:4px; font-size:14px; line-height:1.6;">
            {formatted}
        </div>
        """
    
    if not analyses:
        html_analyses = """
        <div style="background:#fef3c7; border-left:4px solid #f59e0b; padding:16px; 
                     margin:16px 0; border-radius:4px;">
            No new peer earnings call transcripts found in the last {lookback} days.
        </div>
        """.format(lookback=LOOKBACK_DAYS)
    
    html_body = f"""
    <html>
    <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; 
                 max-width: 700px; margin: 0 auto; color: #1a1a1a;">
        <div style="background: #1e3a5f; color: white; padding: 20px; border-radius: 8px 8px 0 0;">
            <h2 style="margin:0; font-size:20px;">📊 AUB Peer Earnings Monitor</h2>
            <p style="margin:8px 0 0; opacity:0.8; font-size:13px;">
                {now} · Lookback: {LOOKBACK_DAYS} days · 
                {transcripts_found}/{transcripts_total} peers with new transcripts
            </p>
        </div>
        
        <div style="padding: 16px;">
            {html_analyses}
            
            <div style="margin-top:24px; padding-top:16px; border-top:1px solid #e5e7eb; 
                         font-size:12px; color:#6b7280;">
                <p>Focus: {FOCUS_COMPANY}</p>
                <p>Peers monitored: {', '.join(PEERS.keys())}</p>
                <p>Sources: Seeking Alpha, Insider Monkey, Yahoo Finance</p>
            </div>
        </div>
    </body>
    </html>
    """
    
    return html_body, text_body

# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main():
    log.info("=" * 60)
    log.info("AUB PEER EARNINGS MONITOR")
    log.info(f"Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    log.info(f"Lookback: {LOOKBACK_DAYS} days")
    log.info("=" * 60)
    
    # Determine which tickers to scan
    if TICKERS_ENV:
        tickers_to_scan = {}
        for t in TICKERS_ENV.split(","):
            t = t.strip()
            if t in PEERS:
                tickers_to_scan[t] = PEERS[t]
            else:
                # Unknown ticker — build a basic entry
                tickers_to_scan[t] = {"name": t, "sa": t, "search": t}
    else:
        tickers_to_scan = PEERS.copy()
    
    log.info(f"Scanning peers: {', '.join(tickers_to_scan.keys())}")
    log.info(f"Email: {SMTP_USER or '(not configured)'} → {EMAIL_TO}")
    log.info(f"Claude API: {'configured' if ANTHROPIC_API_KEY else 'not configured (using keyword fallback)'}")
    
    # Check for dry-run
    if "--dry-run" in sys.argv:
        log.info("DRY RUN — sending test email")
        test_analysis = (
            "**AJG — Arthur J. Gallagher Q4 2025 Earnings Call**\n\n"
            "HEADLINE: Property reinsurance rates declined in the teens globally, "
            "signalling headwinds for AUB's property-exposed book (~45% of premium).\n\n"
            "🟢 Positive:\n"
            "• Casualty rates broadly stable (+5-7% US), supporting AUB's liability lines\n"
            "• Strong client retention across all geographies\n\n"
            "🔴 Negative:\n"
            "• Property cat rates down in the teens; buyers' market expected through 2026\n"
            "• APAC organic growth weakest region at +3%\n\n"
            "BOTTOM LINE: Mixed signals. Property softening will pressure ~45% of AUB's book "
            "but casualty firmness provides offset. APAC underperformance is a flag."
        )
        html, text = build_email([test_analysis], 1, len(tickers_to_scan))
        subject = f"[TEST] AUB Peer Monitor — {datetime.now().strftime('%d %b %Y')}"
        send_email(subject, html, text)
        return
    
    # Find and fetch transcripts
    transcripts = find_and_fetch_transcripts(tickers_to_scan)
    
    log.info(f"\nFound {len(transcripts)} transcripts total")
    
    if not transcripts:
        log.info("No transcripts found. Sending notification email.")
        html, text = build_email([], 0, len(tickers_to_scan))
        subject = f"AUB Peer Monitor — No new transcripts — {datetime.now().strftime('%d %b')}"
        send_email(subject, html, text)
        return
    
    # Analyse each transcript
    analyses = []
    for t in transcripts:
        log.info(f"\nAnalysing {t['ticker']} ({t['source']}, {t['content_length']:,} chars)...")
        analysis = analyse_with_claude(t)
        if analysis:
            analyses.append(analysis)
            log.info(f"  ✓ Analysis complete ({len(analysis)} chars)")
    
    # Build and send email
    tickers_found = list(set(t["ticker"] for t in transcripts))
    subject = (
        f"AUB Peer Monitor — {', '.join(tickers_found)} — "
        f"{datetime.now().strftime('%d %b %Y')}"
    )
    
    html, text = build_email(analyses, len(transcripts), len(tickers_to_scan))
    send_email(subject, html, text)
    
    log.info("\n" + "=" * 60)
    log.info("COMPLETE")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
