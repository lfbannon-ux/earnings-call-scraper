#!/usr/bin/env python3
"""
Seeking Alpha Earnings Call Transcripts Scraper (Playwright Version)

This version uses Playwright for browser automation, which is significantly
more effective at avoiding blocks as it runs a real browser.

Usage:
    python seeking_alpha_playwright.py [--pages N] [--output FILE] [--headless]
    
Requirements:
    pip install playwright beautifulsoup4 lxml
    playwright install chromium
"""

import argparse
import asyncio
import json
import random
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, Page, Browser


class SeekingAlphaPlaywright:
    """Playwright-based scraper for Seeking Alpha earnings transcripts."""
    
    BASE_URL = "https://seekingalpha.com"
    TRANSCRIPTS_URL = f"{BASE_URL}/earnings/earnings-call-transcripts"
    
    def __init__(self, headless: bool = True, verbose: bool = True):
        self.headless = headless
        self.verbose = verbose
        self.browser: Optional[Browser] = None
        self.page: Optional[Page] = None
        
    def _log(self, message: str):
        """Print message if verbose mode is enabled."""
        if self.verbose:
            print(message)
            
    async def _random_delay(self, min_sec: float = 1.5, max_sec: float = 4.0):
        """Add random delay to mimic human behavior."""
        delay = random.uniform(min_sec, max_sec)
        self._log(f"  Waiting {delay:.1f}s...")
        await asyncio.sleep(delay)
        
    async def _human_scroll(self, page: Page):
        """Simulate human-like scrolling behavior."""
        # Scroll down in chunks
        for _ in range(random.randint(2, 4)):
            scroll_amount = random.randint(300, 700)
            await page.evaluate(f'window.scrollBy(0, {scroll_amount})')
            await asyncio.sleep(random.uniform(0.3, 0.8))
            
    async def start(self):
        """Start the browser."""
        self._log("Starting browser...")
        
        playwright = await async_playwright().start()
        
        # Use chromium with stealth settings
        self.browser = await playwright.chromium.launch(
            headless=self.headless,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--disable-dev-shm-usage',
                '--no-sandbox',
            ]
        )
        
        # Create context with realistic viewport and settings
        context = await self.browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            locale='en-US',
            timezone_id='America/New_York',
        )
        
        # Add anti-detection scripts
        await context.add_init_script("""
            // Override webdriver detection
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
            
            // Override automation flags
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5]
            });
            
            // Override languages
            Object.defineProperty(navigator, 'languages', {
                get: () => ['en-US', 'en']
            });
            
            // Override chrome property
            window.chrome = {
                runtime: {}
            };
        """)
        
        self.page = await context.new_page()
        
        # Set extra headers
        await self.page.set_extra_http_headers({
            'Accept-Language': 'en-US,en;q=0.9',
        })
        
    async def close(self):
        """Close the browser."""
        if self.browser:
            await self.browser.close()
            
    async def navigate_to_transcripts(self):
        """Navigate to the transcripts page."""
        self._log(f"Navigating to {self.TRANSCRIPTS_URL}")
        
        # First visit Google to get a realistic referrer
        await self.page.goto('https://www.google.com', wait_until='domcontentloaded')
        await asyncio.sleep(random.uniform(1, 2))
        
        # Then navigate to Seeking Alpha
        await self.page.goto(
            self.TRANSCRIPTS_URL,
            wait_until='domcontentloaded',
            timeout=60000
        )
        
        # Wait for content to load
        await asyncio.sleep(2)
        await self._human_scroll(self.page)
        
    def parse_page_content(self, html: str) -> list[dict]:
        """Parse transcript listings from page HTML."""
        soup = BeautifulSoup(html, 'lxml')
        transcripts = []
        
        # Multiple selector strategies
        selectors = [
            'article[data-test-id="post-list-item"]',
            'div[data-test-id="post-list"] article',
            'li[data-test-id="post-list-item"]',
            '[class*="article-card"]',
            'article',
        ]
        
        articles = []
        for selector in selectors:
            articles = soup.select(selector)
            if articles and len(articles) > 3:  # Ensure we found actual articles
                self._log(f"  Found {len(articles)} articles with: {selector}")
                break
        
        # Fallback: find all transcript links
        if not articles or len(articles) < 3:
            self._log("  Using fallback link extraction...")
            links = soup.find_all('a', href=lambda h: h and 'earnings-call-transcript' in h)
            seen_urls = set()
            
            for link in links:
                href = link.get('href', '')
                if href.startswith('/'):
                    href = self.BASE_URL + href
                    
                if href in seen_urls:
                    continue
                seen_urls.add(href)
                
                title = link.get_text(strip=True)
                if title and len(title) > 10:  # Skip navigation links
                    transcripts.append({
                        'title': title,
                        'url': href,
                        'ticker': self._extract_ticker(title),
                        'date': None,
                    })
            return transcripts
        
        for article in articles:
            try:
                # Find the title link
                title_link = (
                    article.select_one('a[data-test-id="post-list-item-title"]') or
                    article.select_one('h3 a') or
                    article.select_one('h2 a') or
                    article.find('a', href=lambda h: h and '/article/' in str(h))
                )
                
                if not title_link:
                    continue
                    
                title = title_link.get_text(strip=True)
                url = title_link.get('href', '')
                
                if not title or 'transcript' not in title.lower():
                    continue
                    
                if url.startswith('/'):
                    url = self.BASE_URL + url
                
                # Extract date
                date_elem = (
                    article.select_one('time') or
                    article.select_one('[data-test-id="post-list-item-date"]') or
                    article.select_one('span[class*="date"]')
                )
                date_str = None
                if date_elem:
                    date_str = date_elem.get('datetime') or date_elem.get_text(strip=True)
                
                # Extract ticker
                ticker_elem = article.select_one('[data-test-id="post-list-item-ticker"]')
                ticker = ticker_elem.get_text(strip=True) if ticker_elem else self._extract_ticker(title)
                
                transcripts.append({
                    'title': title,
                    'url': url,
                    'ticker': ticker,
                    'date': date_str,
                })
                
            except Exception as e:
                self._log(f"  Parse error: {e}")
                continue
                
        return transcripts
    
    def _extract_ticker(self, title: str) -> Optional[str]:
        """Extract stock ticker from title."""
        # Pattern: "Company Name (TICK)" or "TICK:"
        match = re.search(r'\(([A-Z]{1,5})\)', title)
        if match:
            return match.group(1)
        match = re.search(r'^([A-Z]{1,5}):', title)
        if match:
            return match.group(1)
        return None
    
    async def scrape_page(self) -> list[dict]:
        """Scrape the current page."""
        # Get page content
        html = await self.page.content()
        return self.parse_page_content(html)
    
    async def load_more_content(self) -> bool:
        """Try to load more content by scrolling or clicking 'load more'."""
        try:
            # Try clicking "Load More" or "Show More" button
            load_more_selectors = [
                'button:has-text("Load More")',
                'button:has-text("Show More")',
                'a:has-text("Load More")',
                '[data-test-id="load-more"]',
            ]
            
            for selector in load_more_selectors:
                try:
                    btn = self.page.locator(selector).first
                    if await btn.is_visible():
                        await btn.click()
                        await asyncio.sleep(2)
                        return True
                except:
                    continue
            
            # Scroll to bottom to trigger infinite scroll
            await self.page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
            await asyncio.sleep(2)
            
            return True
            
        except Exception as e:
            self._log(f"  Could not load more: {e}")
            return False
    
    async def scrape_transcripts(self, max_pages: int = 5) -> list[dict]:
        """
        Scrape multiple pages of earnings call transcripts.
        
        Args:
            max_pages: Maximum number of pages/load-more clicks
            
        Returns:
            List of transcript dictionaries
        """
        all_transcripts = []
        
        await self.navigate_to_transcripts()
        
        for page_num in range(1, max_pages + 1):
            self._log(f"\nScraping page {page_num}/{max_pages}")
            
            transcripts = await self.scrape_page()
            new_count = 0
            
            existing_urls = {t['url'] for t in all_transcripts}
            for t in transcripts:
                if t['url'] not in existing_urls:
                    all_transcripts.append(t)
                    new_count += 1
                    
            self._log(f"  Found {new_count} new transcripts")
            
            if page_num < max_pages:
                if not await self.load_more_content():
                    self._log("  No more content to load")
                    break
                await self._random_delay()
        
        self._log(f"\nTotal transcripts: {len(all_transcripts)}")
        return all_transcripts
    
    async def scrape_full_transcript(self, url: str) -> Optional[dict]:
        """
        Scrape the full content of a single transcript.
        
        Note: Seeking Alpha requires login for full transcripts.
        This will return whatever is publicly accessible.
        """
        self._log(f"Fetching: {url}")
        
        await self.page.goto(url, wait_until='domcontentloaded', timeout=60000)
        await asyncio.sleep(2)
        await self._human_scroll(self.page)
        
        html = await self.page.content()
        soup = BeautifulSoup(html, 'lxml')
        
        # Try to find article content
        content_selectors = [
            'article[data-test-id="article-content"]',
            'div[data-test-id="article-body"]',
            '.paywall-full-content',
            'article',
            'main',
        ]
        
        content = None
        for selector in content_selectors:
            elem = soup.select_one(selector)
            if elem:
                content = elem.get_text(separator='\n', strip=True)
                if len(content) > 500:  # Substantial content
                    break
        
        # Check for paywall
        is_paywalled = bool(soup.select_one('.paywall-message') or 
                           soup.select_one('[data-test-id="paywall"]'))
        
        return {
            'url': url,
            'content': content,
            'is_paywalled': is_paywalled,
            'scraped_at': datetime.now().isoformat(),
        }


async def main():
    parser = argparse.ArgumentParser(
        description='Scrape Seeking Alpha earnings transcripts (Playwright)'
    )
    parser.add_argument(
        '--pages', '-p',
        type=int,
        default=3,
        help='Number of pages to scrape (default: 3)'
    )
    parser.add_argument(
        '--output', '-o',
        type=str,
        default='sa_transcripts.json',
        help='Output JSON file (default: sa_transcripts.json)'
    )
    parser.add_argument(
        '--headless',
        action='store_true',
        default=True,
        help='Run in headless mode (default: True)'
    )
    parser.add_argument(
        '--visible',
        action='store_true',
        help='Show browser window (for debugging)'
    )
    parser.add_argument(
        '--quiet', '-q',
        action='store_true',
        help='Suppress progress output'
    )
    
    args = parser.parse_args()
    
    headless = not args.visible
    
    scraper = SeekingAlphaPlaywright(
        headless=headless,
        verbose=not args.quiet
    )
    
    try:
        await scraper.start()
        transcripts = await scraper.scrape_transcripts(max_pages=args.pages)
        
        # Save results
        output_path = Path(args.output)
        with open(output_path, 'w') as f:
            json.dump({
                'scraped_at': datetime.now().isoformat(),
                'count': len(transcripts),
                'transcripts': transcripts,
            }, f, indent=2)
            
        print(f"\nSaved {len(transcripts)} transcripts to {output_path}")
        
    finally:
        await scraper.close()


if __name__ == '__main__':
    asyncio.run(main())
