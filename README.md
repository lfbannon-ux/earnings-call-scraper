# Seeking Alpha Earnings Transcripts Scraper

Three approaches for scraping earnings call transcripts from Seeking Alpha:

1. **Authenticated API** (recommended) - Full premium access via Google login
2. **Playwright** - Browser automation without login
3. **Requests** - Lightweight scraping

## Quick Start

### Option 1: Authenticated API (Premium Access)

```bash
pip install -r requirements-playwright.txt
playwright install chromium

# First run - opens browser for Google login
python seeking_alpha_authenticated.py --login

# Subsequent runs - uses saved session
python seeking_alpha_authenticated.py --ticker AAPL
python seeking_alpha_authenticated.py --tickers "AAPL,MSFT,GOOGL"
```

### Option 2: Playwright (No Login)

```bash
pip install -r requirements.txt
python seeking_alpha_scraper.py --pages 5 --output transcripts.json
```

### Option 2: Playwright-based (More robust)

```bash
pip install -r requirements-playwright.txt
playwright install chromium
python seeking_alpha_playwright.py --pages 5 --output transcripts.json
```

## API-Style Usage (Recommended)

The cleanest way to use this in your code:

```python
from seeking_alpha_api import SeekingAlpha

async def get_earnings_data():
    async with SeekingAlpha() as sa:
        # Get latest transcript listings
        transcripts = await sa.latest(pages=5)
        
        # Get full transcript for a ticker
        aapl = await sa.transcript("AAPL")
        print(aapl['content'][:500])
        
        # Batch fetch multiple tickers
        results = await sa.batch(["AUB.AX", "HUB.AX", "MIN.AX"])
        
        return results

# Run it
import asyncio
data = asyncio.run(get_earnings_data())
```

### Synchronous Version

```python
from seeking_alpha_api import SeekingAlphaSync

sa = SeekingAlphaSync()
sa.start()  # Opens browser for login on first run

transcript = sa.transcript("AAPL")
print(transcript['content'])

sa.close()
```

### Session Persistence

After the first Google login, your session is saved to `~/.seeking_alpha_session/`. Subsequent runs will reuse this session automatically until it expires.

```bash
# Force new login (if session expired)
python seeking_alpha_authenticated.py --login
```

## Which to Use?

| Feature | Authenticated API | Playwright | Requests |
|---------|-------------------|------------|----------|
| Premium content | ✅ Full access | ❌ Preview only | ❌ Preview only |
| Setup complexity | Google login once | Browser install | Simple pip |
| Session persistence | ✅ Auto-saved | ❌ None | ❌ None |
| API-like interface | ✅ Clean methods | ❌ Manual | ❌ Manual |
| Resource usage | High | High | Low |

**Recommendation**: Use the authenticated API if you have a Seeking Alpha Pro subscription.

## Usage

### Basic scraping

```bash
# Scrape 3 pages (default)
python seeking_alpha_playwright.py

# Scrape 10 pages
python seeking_alpha_playwright.py --pages 10

# Custom output file
python seeking_alpha_playwright.py --output my_transcripts.json

# Show browser window (for debugging)
python seeking_alpha_playwright.py --visible
```

### Output format

```json
{
  "scraped_at": "2025-02-02T10:30:00",
  "count": 45,
  "transcripts": [
    {
      "title": "Apple Inc. (AAPL) Q4 2024 Earnings Call Transcript",
      "url": "https://seekingalpha.com/article/...",
      "ticker": "AAPL",
      "date": "2024-11-01"
    }
  ]
}
```

### Programmatic usage

```python
import asyncio
from seeking_alpha_playwright import SeekingAlphaPlaywright

async def get_transcripts():
    scraper = SeekingAlphaPlaywright(headless=True)
    await scraper.start()
    
    try:
        transcripts = await scraper.scrape_transcripts(max_pages=5)
        
        # Optionally fetch full content (may be paywalled)
        for t in transcripts[:3]:
            content = await scraper.scrape_full_transcript(t['url'])
            print(f"{t['ticker']}: {len(content.get('content', '')) or 0} chars")
    finally:
        await scraper.close()
    
    return transcripts

transcripts = asyncio.run(get_transcripts())
```

## Deployment in Claude Code

1. **Create project directory**:
   ```bash
   mkdir ~/seeking-alpha-scraper && cd ~/seeking-alpha-scraper
   ```

2. **Copy files** (or clone from your repo)

3. **Install dependencies**:
   ```bash
   pip install -r requirements-playwright.txt
   playwright install chromium
   ```

4. **Run via Claude Code**:
   ```bash
   python seeking_alpha_playwright.py --pages 5
   ```

## Anti-Blocking Techniques Used

### Requests version
- Rotating user agents via `fake-useragent`
- Random delays between requests (2-5 seconds)
- Session persistence with cookies
- Realistic browser headers
- API endpoint fallback (Seeking Alpha's internal API)
- Exponential backoff on rate limits

### Playwright version (more effective)
- Full browser automation (real Chrome/Chromium)
- Anti-detection scripts (hides `navigator.webdriver`)
- Human-like scrolling behavior
- Realistic viewport and locale settings
- Google referrer for credibility
- Random timing variations

## Important Notes

### Paywalled Content
Full transcript content on Seeking Alpha requires a Premium subscription. The scrapers will:
- Return the publicly visible preview
- Flag `is_paywalled: true` when applicable

### Rate Limiting
Seeking Alpha may still block if you:
- Scrape too aggressively (keep pages ≤ 10 per session)
- Run too frequently (suggest once per day max)
- Use the same IP repeatedly

### Legal Considerations
- Respect Seeking Alpha's Terms of Service
- This tool is for personal research use only
- Do not redistribute scraped content commercially

## Troubleshooting

### "Access Denied" / 403 errors
- Try the Playwright version
- Reduce scraping frequency
- Use a VPN or residential proxy

### Empty results
- Seeking Alpha may have changed their HTML structure
- Check if the page loads in a regular browser
- Review console output for selector matches

### Playwright installation issues
```bash
# If chromium install fails, try:
playwright install --with-deps chromium

# Or on Ubuntu/Debian:
sudo apt-get install libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2
```

## Extending the Scraper

### Add proxy support (Playwright)

```python
context = await browser.new_context(
    proxy={
        "server": "http://proxy.example.com:8080",
        "username": "user",
        "password": "pass"
    }
)
```

### Filter by ticker

```python
transcripts = await scraper.scrape_transcripts(max_pages=10)
asx_tickers = ['BHP', 'CBA', 'CSL']
filtered = [t for t in transcripts if t['ticker'] in asx_tickers]
```

## Integration with Your Stock System

Based on your existing setup, here's how to integrate with your ASX monitoring:

```python
import asyncio
import anthropic
from seeking_alpha_api import SeekingAlpha

# Your ASX watchlist
WATCHLIST = ['AUB', 'MIN', 'HUB', 'WTC', 'BHP', 'CBA']

async def get_transcript_summaries():
    client = anthropic.Anthropic()
    summaries = []
    
    async with SeekingAlpha(verbose=True) as sa:
        for ticker in WATCHLIST:
            # Try ASX ticker format first, then plain
            transcript = await sa.transcript(f"{ticker}.AX")
            if not transcript:
                transcript = await sa.transcript(ticker)
                
            if transcript and transcript.get('content') and not transcript.get('is_paywalled'):
                # Summarize with Claude
                response = client.messages.create(
                    model="claude-sonnet-4-20250514",
                    max_tokens=500,
                    messages=[{
                        "role": "user",
                        "content": f"""Summarize this earnings call transcript in 3-4 bullet points.
Focus on: guidance, key metrics, risks mentioned.

{transcript['content'][:15000]}"""
                    }]
                )
                
                summaries.append({
                    'ticker': ticker,
                    'date': transcript['date'],
                    'summary': response.content[0].text
                })
                
    return summaries

# Use in your existing email report system
summaries = asyncio.run(get_transcript_summaries())
```

### Railway Deployment

Add to your existing Railway project:

```bash
# In your Dockerfile or build command
pip install playwright beautifulsoup4 lxml
playwright install chromium --with-deps

# Mount persistent volume for session storage
# Set SEEKING_ALPHA_SESSION_DIR=/app/data/sa_session
```

```python
# In your scheduled job
import os
from pathlib import Path
from seeking_alpha_api import SeekingAlpha

session_dir = Path(os.environ.get('SEEKING_ALPHA_SESSION_DIR', '/app/data/sa_session'))

async with SeekingAlpha(session_dir=session_dir) as sa:
    # Session persists across Railway deployments
    transcripts = await sa.latest(pages=3)
```
