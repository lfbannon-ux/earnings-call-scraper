#!/usr/bin/env python3
"""
Seeking Alpha Earnings Call Transcripts Scraper (Authenticated Version)

This version supports Google login for premium/pro account access,
enabling full transcript retrieval.

Usage:
    # First run - will prompt for Google login
    python seeking_alpha_authenticated.py --login
    
    # Subsequent runs - uses saved session
    python seeking_alpha_authenticated.py --pages 5
    
    # API-style usage
    from seeking_alpha_authenticated import SeekingAlphaAPI
    api = SeekingAlphaAPI()
    await api.start()
    transcript = await api.get_transcript("AAPL")

Requirements:
    pip install playwright beautifulsoup4 lxml aiofiles
    playwright install chromium
"""

import argparse
import asyncio
import json
import os
import random
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, Page, Browser, BrowserContext


class SeekingAlphaAPI:
    """
    Authenticated Seeking Alpha scraper with API-like interface.
    
    Supports Google OAuth login and persistent sessions for premium access.
    """
    
    BASE_URL = "https://seekingalpha.com"
    TRANSCRIPTS_URL = f"{BASE_URL}/earnings/earnings-call-transcripts"
    LOGIN_URL = f"{BASE_URL}/login"
    
    # Default paths
    DEFAULT_SESSION_DIR = Path.home() / ".seeking_alpha_session"
    DEFAULT_STATE_FILE = "auth_state.json"
    
    def __init__(
        self,
        session_dir: Optional[Path] = None,
        headless: bool = True,
        verbose: bool = True
    ):
        self.session_dir = Path(session_dir) if session_dir else self.DEFAULT_SESSION_DIR
        self.state_file = self.session_dir / self.DEFAULT_STATE_FILE
        self.headless = headless
        self.verbose = verbose
        
        self.playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.is_authenticated = False
        
        # Ensure session directory exists
        self.session_dir.mkdir(parents=True, exist_ok=True)
        
    def _log(self, message: str):
        if self.verbose:
            print(message)
            
    async def _random_delay(self, min_sec: float = 1.0, max_sec: float = 3.0):
        delay = random.uniform(min_sec, max_sec)
        await asyncio.sleep(delay)
        
    async def start(self, force_login: bool = False):
        """
        Start browser and restore session if available.
        
        Args:
            force_login: If True, ignore saved session and prompt for new login
        """
        self._log("Starting browser...")
        
        self.playwright = await async_playwright().start()
        
        self.browser = await self.playwright.chromium.launch(
            headless=self.headless,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--disable-dev-shm-usage',
                '--no-sandbox',
            ]
        )
        
        # Check for existing session
        if not force_login and self.state_file.exists():
            self._log("Restoring saved session...")
            try:
                self.context = await self.browser.new_context(
                    storage_state=str(self.state_file),
                    viewport={'width': 1920, 'height': 1080},
                    user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                )
                await self._add_stealth_scripts()
                self.page = await self.context.new_page()
                
                # Verify session is still valid
                if await self._verify_login():
                    self._log("Session restored successfully!")
                    self.is_authenticated = True
                    return
                else:
                    self._log("Saved session expired, need to re-login")
                    await self.context.close()
            except Exception as e:
                self._log(f"Could not restore session: {e}")
        
        # Create fresh context
        self.context = await self.browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            locale='en-US',
            timezone_id='America/New_York',
        )
        await self._add_stealth_scripts()
        self.page = await self.context.new_page()
        
    async def _add_stealth_scripts(self):
        """Add anti-detection scripts to browser context."""
        await self.context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
            window.chrome = { runtime: {} };
        """)
        
    async def _verify_login(self) -> bool:
        """Check if current session has valid premium access."""
        try:
            await self.page.goto(self.BASE_URL, wait_until='domcontentloaded', timeout=30000)
            await asyncio.sleep(2)
            
            # Check for premium indicator or user menu
            html = await self.page.content()
            
            # Look for signs of being logged in
            logged_in_indicators = [
                'data-test-id="user-nav"',
                'data-test-id="user-menu"',
                '"isLoggedIn":true',
                'Sign Out',
                'My Portfolio',
            ]
            
            for indicator in logged_in_indicators:
                if indicator in html:
                    return True
                    
            return False
            
        except Exception as e:
            self._log(f"Login verification failed: {e}")
            return False
            
    async def login_with_google(self, timeout: int = 300):
        """
        Perform Google OAuth login.
        
        Opens a visible browser window for you to complete Google login.
        The session will be saved for future use.
        
        Args:
            timeout: Maximum seconds to wait for login completion
        """
        self._log("\n" + "="*60)
        self._log("GOOGLE LOGIN REQUIRED")
        self._log("="*60)
        self._log("A browser window will open. Please:")
        self._log("1. Click 'Sign in with Google'")
        self._log("2. Complete the Google login process")
        self._log("3. Wait for redirect back to Seeking Alpha")
        self._log("="*60 + "\n")
        
        # Need visible browser for OAuth
        if self.headless:
            await self.close()
            self.headless = False
            await self.start(force_login=True)
        
        # Navigate to login page
        await self.page.goto(self.LOGIN_URL, wait_until='domcontentloaded')
        await asyncio.sleep(2)
        
        # Try to click Google login button
        google_selectors = [
            'button:has-text("Google")',
            'a:has-text("Google")',
            '[data-test-id="google-login"]',
            'button[class*="google"]',
            '.google-login',
        ]
        
        clicked = False
        for selector in google_selectors:
            try:
                btn = self.page.locator(selector).first
                if await btn.is_visible(timeout=2000):
                    await btn.click()
                    clicked = True
                    self._log("Clicked Google login button")
                    break
            except:
                continue
                
        if not clicked:
            self._log("Could not find Google button - please click it manually")
        
        # Wait for user to complete login
        self._log(f"\nWaiting up to {timeout}s for login completion...")
        
        start_time = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - start_time < timeout:
            await asyncio.sleep(3)
            
            # Check if we're back on SA and logged in
            current_url = self.page.url
            if 'seekingalpha.com' in current_url and 'login' not in current_url:
                if await self._verify_login():
                    self._log("\n✓ Login successful!")
                    self.is_authenticated = True
                    
                    # Save session state
                    await self._save_session()
                    return True
                    
        self._log("\n✗ Login timed out")
        return False
        
    async def login_with_credentials(self, email: str, password: str):
        """
        Login with email/password (Seeking Alpha native account).
        
        Note: This won't work for Google-only accounts.
        """
        self._log("Logging in with credentials...")
        
        await self.page.goto(self.LOGIN_URL, wait_until='domcontentloaded')
        await asyncio.sleep(2)
        
        # Fill email
        email_selectors = ['input[name="email"]', 'input[type="email"]', '#email']
        for selector in email_selectors:
            try:
                await self.page.fill(selector, email, timeout=3000)
                break
            except:
                continue
                
        # Fill password
        password_selectors = ['input[name="password"]', 'input[type="password"]', '#password']
        for selector in password_selectors:
            try:
                await self.page.fill(selector, password, timeout=3000)
                break
            except:
                continue
        
        # Click submit
        submit_selectors = ['button[type="submit"]', 'button:has-text("Sign In")', 'input[type="submit"]']
        for selector in submit_selectors:
            try:
                await self.page.click(selector, timeout=3000)
                break
            except:
                continue
                
        await asyncio.sleep(5)
        
        if await self._verify_login():
            self._log("✓ Login successful!")
            self.is_authenticated = True
            await self._save_session()
            return True
        else:
            self._log("✗ Login failed")
            return False
            
    async def _save_session(self):
        """Save browser session state for reuse."""
        self._log(f"Saving session to {self.state_file}")
        await self.context.storage_state(path=str(self.state_file))
        
    async def close(self):
        """Close browser and cleanup."""
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
            
    # =========================================================================
    # API Methods
    # =========================================================================
    
    async def get_latest_transcripts(self, max_pages: int = 3) -> list[dict]:
        """
        Get latest earnings call transcript listings.
        
        Returns:
            List of transcript metadata dicts
        """
        if not self.page:
            raise RuntimeError("Call start() first")
            
        all_transcripts = []
        
        await self.page.goto(self.TRANSCRIPTS_URL, wait_until='domcontentloaded')
        await asyncio.sleep(2)
        
        for page_num in range(max_pages):
            self._log(f"Scraping page {page_num + 1}/{max_pages}")
            
            # Scroll to load content
            await self._scroll_page()
            
            html = await self.page.content()
            transcripts = self._parse_transcript_list(html)
            
            existing_urls = {t['url'] for t in all_transcripts}
            new_transcripts = [t for t in transcripts if t['url'] not in existing_urls]
            all_transcripts.extend(new_transcripts)
            
            self._log(f"  Found {len(new_transcripts)} new transcripts")
            
            if page_num < max_pages - 1:
                # Try to load more
                if not await self._load_more():
                    break
                await self._random_delay()
                
        return all_transcripts
    
    async def get_transcript(self, ticker_or_url: str) -> Optional[dict]:
        """
        Get full transcript content by ticker or URL.
        
        Args:
            ticker_or_url: Either a stock ticker (e.g., "AAPL") or full transcript URL
            
        Returns:
            Dict with transcript content or None if not found
        """
        if not self.page:
            raise RuntimeError("Call start() first")
            
        # If it's a ticker, search for latest transcript
        if not ticker_or_url.startswith('http'):
            transcript_meta = await self.search_transcript(ticker_or_url)
            if not transcript_meta:
                self._log(f"No transcript found for {ticker_or_url}")
                return None
            url = transcript_meta['url']
        else:
            url = ticker_or_url
            
        self._log(f"Fetching transcript: {url}")
        
        await self.page.goto(url, wait_until='domcontentloaded', timeout=60000)
        await asyncio.sleep(2)
        await self._scroll_page()
        
        html = await self.page.content()
        return self._parse_transcript_content(html, url)
    
    async def search_transcript(self, ticker: str) -> Optional[dict]:
        """
        Search for the latest transcript for a given ticker.
        
        Args:
            ticker: Stock ticker symbol
            
        Returns:
            Transcript metadata or None
        """
        search_url = f"{self.BASE_URL}/search?q={ticker}%20earnings%20call%20transcript&tab=transcripts"
        
        await self.page.goto(search_url, wait_until='domcontentloaded')
        await asyncio.sleep(2)
        
        html = await self.page.content()
        soup = BeautifulSoup(html, 'lxml')
        
        # Find transcript links
        links = soup.find_all('a', href=lambda h: h and 'earnings-call-transcript' in h)
        
        for link in links:
            title = link.get_text(strip=True)
            href = link.get('href', '')
            
            # Check if ticker matches
            if f'({ticker.upper()})' in title or f'{ticker.upper()}:' in title:
                url = self.BASE_URL + href if href.startswith('/') else href
                return {
                    'title': title,
                    'url': url,
                    'ticker': ticker.upper(),
                }
                
        return None
    
    async def get_transcripts_for_tickers(self, tickers: list[str]) -> dict[str, dict]:
        """
        Batch fetch transcripts for multiple tickers.
        
        Args:
            tickers: List of stock ticker symbols
            
        Returns:
            Dict mapping ticker to transcript data
        """
        results = {}
        
        for ticker in tickers:
            self._log(f"\nProcessing {ticker}...")
            transcript = await self.get_transcript(ticker)
            if transcript:
                results[ticker] = transcript
            await self._random_delay(2, 4)
            
        return results
    
    # =========================================================================
    # Parsing Methods
    # =========================================================================
    
    def _parse_transcript_list(self, html: str) -> list[dict]:
        """Parse transcript listings from HTML."""
        soup = BeautifulSoup(html, 'lxml')
        transcripts = []
        
        # Find transcript links
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
            if not title or len(title) < 10:
                continue
                
            # Extract ticker
            ticker = None
            match = re.search(r'\(([A-Z]{1,5})\)', title)
            if match:
                ticker = match.group(1)
                
            # Find date (look in parent elements)
            date_str = None
            parent = link.find_parent(['article', 'li', 'div'])
            if parent:
                time_elem = parent.find('time')
                if time_elem:
                    date_str = time_elem.get('datetime') or time_elem.get_text(strip=True)
                    
            transcripts.append({
                'title': title,
                'url': href,
                'ticker': ticker,
                'date': date_str,
            })
            
        return transcripts
    
    def _parse_transcript_content(self, html: str, url: str) -> dict:
        """Parse full transcript content from article page."""
        soup = BeautifulSoup(html, 'lxml')
        
        # Extract title
        title_elem = soup.select_one('h1') or soup.select_one('[data-test-id="article-title"]')
        title = title_elem.get_text(strip=True) if title_elem else None
        
        # Extract date
        date_elem = soup.select_one('time') or soup.select_one('[data-test-id="article-date"]')
        date_str = None
        if date_elem:
            date_str = date_elem.get('datetime') or date_elem.get_text(strip=True)
            
        # Extract content
        content_selectors = [
            'div[data-test-id="article-body"]',
            'article[data-test-id="article-content"]',
            '.paywall-full-content',
            '.article-content',
            'article',
        ]
        
        content = None
        content_html = None
        
        for selector in content_selectors:
            elem = soup.select_one(selector)
            if elem:
                content = elem.get_text(separator='\n', strip=True)
                content_html = str(elem)
                if len(content) > 1000:  # Substantial content
                    break
                    
        # Check for paywall
        is_paywalled = bool(
            soup.select_one('.paywall-message') or
            soup.select_one('[data-test-id="paywall"]') or
            'premium' in html.lower() and 'subscribe' in html.lower() and len(content or '') < 2000
        )
        
        # Extract participants if available
        participants = self._extract_participants(soup)
        
        # Extract Q&A section if available
        qa_section = self._extract_qa_section(content or '')
        
        return {
            'url': url,
            'title': title,
            'date': date_str,
            'ticker': self._extract_ticker_from_title(title) if title else None,
            'content': content,
            'content_html': content_html,
            'is_paywalled': is_paywalled,
            'participants': participants,
            'qa_section': qa_section,
            'scraped_at': datetime.now().isoformat(),
            'is_authenticated': self.is_authenticated,
        }
    
    def _extract_participants(self, soup: BeautifulSoup) -> list[dict]:
        """Extract call participants from transcript."""
        participants = []
        
        # Look for participants section
        participants_section = soup.find(string=re.compile(r'(Call Participants|Conference Call Participants)', re.I))
        if participants_section:
            parent = participants_section.find_parent(['div', 'section', 'p'])
            if parent:
                # Extract names and titles
                text = parent.get_text(separator='\n')
                lines = text.split('\n')
                
                for line in lines:
                    line = line.strip()
                    if ' - ' in line:
                        parts = line.split(' - ', 1)
                        participants.append({
                            'name': parts[0].strip(),
                            'title': parts[1].strip() if len(parts) > 1 else None
                        })
                        
        return participants
    
    def _extract_qa_section(self, content: str) -> Optional[str]:
        """Extract Q&A portion of transcript."""
        qa_markers = [
            'Question-and-Answer Session',
            'Q&A Session',
            'Questions and Answers',
        ]
        
        for marker in qa_markers:
            if marker in content:
                idx = content.find(marker)
                return content[idx:]
                
        return None
    
    def _extract_ticker_from_title(self, title: str) -> Optional[str]:
        """Extract stock ticker from title."""
        match = re.search(r'\(([A-Z]{1,5})\)', title)
        return match.group(1) if match else None
    
    # =========================================================================
    # Helper Methods
    # =========================================================================
    
    async def _scroll_page(self):
        """Scroll page to load dynamic content."""
        for _ in range(3):
            await self.page.evaluate('window.scrollBy(0, 500)')
            await asyncio.sleep(0.5)
            
    async def _load_more(self) -> bool:
        """Try to load more content."""
        try:
            selectors = [
                'button:has-text("Load More")',
                'button:has-text("Show More")',
                '[data-test-id="load-more"]',
            ]
            
            for selector in selectors:
                try:
                    btn = self.page.locator(selector).first
                    if await btn.is_visible(timeout=2000):
                        await btn.click()
                        await asyncio.sleep(2)
                        return True
                except:
                    continue
                    
            # Fallback: scroll to bottom
            await self.page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
            await asyncio.sleep(2)
            return True
            
        except:
            return False


# =============================================================================
# CLI Interface
# =============================================================================

async def main():
    parser = argparse.ArgumentParser(
        description='Seeking Alpha Authenticated Scraper'
    )
    parser.add_argument('--login', action='store_true', help='Force new Google login')
    parser.add_argument('--pages', '-p', type=int, default=3, help='Pages to scrape')
    parser.add_argument('--ticker', '-t', type=str, help='Get transcript for specific ticker')
    parser.add_argument('--tickers', type=str, help='Comma-separated list of tickers')
    parser.add_argument('--output', '-o', type=str, default='sa_transcripts.json')
    parser.add_argument('--visible', action='store_true', help='Show browser')
    parser.add_argument('--quiet', '-q', action='store_true')
    
    args = parser.parse_args()
    
    api = SeekingAlphaAPI(
        headless=not args.visible and not args.login,
        verbose=not args.quiet
    )
    
    try:
        await api.start(force_login=args.login)
        
        # Handle login if needed
        if args.login or not api.is_authenticated:
            success = await api.login_with_google()
            if not success:
                print("Login failed. Exiting.")
                return
                
        # Fetch data
        if args.ticker:
            # Single ticker
            result = await api.get_transcript(args.ticker)
            data = {'ticker': args.ticker, 'transcript': result}
            
        elif args.tickers:
            # Multiple tickers
            ticker_list = [t.strip().upper() for t in args.tickers.split(',')]
            result = await api.get_transcripts_for_tickers(ticker_list)
            data = {'tickers': ticker_list, 'transcripts': result}
            
        else:
            # List latest transcripts
            result = await api.get_latest_transcripts(max_pages=args.pages)
            data = {
                'scraped_at': datetime.now().isoformat(),
                'count': len(result),
                'transcripts': result
            }
            
        # Save output
        output_path = Path(args.output)
        with open(output_path, 'w') as f:
            json.dump(data, f, indent=2, default=str)
            
        print(f"\nSaved to {output_path}")
        
    finally:
        await api.close()


if __name__ == '__main__':
    asyncio.run(main())
