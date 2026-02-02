#!/usr/bin/env python3
"""
Seeking Alpha Earnings Call Transcripts Scraper

This script scrapes earnings call transcript listings from Seeking Alpha
using techniques to avoid access blocks.

Usage:
    python seeking_alpha_scraper.py [--pages N] [--output FILE]
    
Requirements:
    pip install requests beautifulsoup4 fake-useragent lxml
"""

import argparse
import json
import random
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup
from fake_useragent import UserAgent


class SeekingAlphaScraper:
    """Scraper for Seeking Alpha earnings call transcripts."""
    
    BASE_URL = "https://seekingalpha.com"
    TRANSCRIPTS_URL = f"{BASE_URL}/earnings/earnings-call-transcripts"
    
    # API endpoint that the page uses (often easier to scrape than HTML)
    API_URL = f"{BASE_URL}/api/v3/articles"
    
    def __init__(self, verbose: bool = True):
        self.verbose = verbose
        self.session = requests.Session()
        self.ua = UserAgent()
        self._setup_session()
        
    def _setup_session(self):
        """Configure session with headers to appear as a real browser."""
        self.session.headers.update({
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Cache-Control': 'max-age=0',
        })
        
    def _get_random_user_agent(self) -> str:
        """Get a random realistic user agent string."""
        try:
            return self.ua.random
        except Exception:
            # Fallback user agents if fake-useragent fails
            agents = [
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15',
            ]
            return random.choice(agents)
    
    def _random_delay(self, min_sec: float = 2.0, max_sec: float = 5.0):
        """Add random delay between requests to avoid rate limiting."""
        delay = random.uniform(min_sec, max_sec)
        if self.verbose:
            print(f"  Waiting {delay:.1f}s...")
        time.sleep(delay)
        
    def _log(self, message: str):
        """Print message if verbose mode is enabled."""
        if self.verbose:
            print(message)
            
    def fetch_page(self, url: str, retry_count: int = 3) -> Optional[requests.Response]:
        """
        Fetch a page with retry logic and anti-blocking measures.
        
        Args:
            url: The URL to fetch
            retry_count: Number of retries on failure
            
        Returns:
            Response object or None if all retries failed
        """
        for attempt in range(retry_count):
            try:
                # Rotate user agent on each attempt
                self.session.headers['User-Agent'] = self._get_random_user_agent()
                
                # Add referer to appear more legitimate
                if 'seekingalpha.com' in url:
                    self.session.headers['Referer'] = 'https://www.google.com/'
                
                response = self.session.get(url, timeout=30)
                
                if response.status_code == 200:
                    return response
                elif response.status_code == 403:
                    self._log(f"  Access denied (403). Attempt {attempt + 1}/{retry_count}")
                    self._random_delay(5, 10)  # Longer delay on 403
                elif response.status_code == 429:
                    self._log(f"  Rate limited (429). Waiting longer...")
                    self._random_delay(30, 60)
                else:
                    self._log(f"  HTTP {response.status_code}. Attempt {attempt + 1}/{retry_count}")
                    self._random_delay()
                    
            except requests.RequestException as e:
                self._log(f"  Request error: {e}. Attempt {attempt + 1}/{retry_count}")
                self._random_delay()
                
        return None
    
    def fetch_via_api(self, page: int = 1, per_page: int = 40) -> Optional[dict]:
        """
        Try to fetch transcripts via Seeking Alpha's internal API.
        
        This is often more reliable than scraping HTML.
        """
        params = {
            'filter[category]': 'earnings::earnings-call-transcripts',
            'filter[since]': '0',
            'filter[until]': '0',
            'include': 'author,primaryTickers,secondaryTickers',
            'isMounting': 'true' if page == 1 else 'false',
            'page[size]': per_page,
            'page[number]': page,
        }
        
        api_headers = {
            'Accept': 'application/json',
            'User-Agent': self._get_random_user_agent(),
            'Referer': self.TRANSCRIPTS_URL,
            'Origin': self.BASE_URL,
        }
        
        try:
            response = self.session.get(
                self.API_URL,
                params=params,
                headers=api_headers,
                timeout=30
            )
            
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            self._log(f"  API fetch error: {e}")
            
        return None
    
    def parse_html_page(self, html: str) -> list[dict]:
        """
        Parse transcript listings from HTML page.
        
        Args:
            html: Raw HTML content
            
        Returns:
            List of transcript dictionaries
        """
        soup = BeautifulSoup(html, 'lxml')
        transcripts = []
        
        # Look for article cards/links - SA uses various selectors
        # Try multiple selectors as their HTML structure changes
        selectors = [
            'article[data-test-id="post-list-item"]',
            'div[data-test-id="post-list"] article',
            'li[data-test-id="post-list-item"]',
            'a[data-test-id="post-list-item-title"]',
            '.content-list article',
            '[class*="article-card"]',
        ]
        
        articles = []
        for selector in selectors:
            articles = soup.select(selector)
            if articles:
                self._log(f"  Found {len(articles)} articles with selector: {selector}")
                break
        
        if not articles:
            # Fallback: look for any links containing "earnings-call-transcript"
            links = soup.find_all('a', href=lambda h: h and 'earnings-call-transcript' in h)
            for link in links:
                transcript = {
                    'title': link.get_text(strip=True),
                    'url': self.BASE_URL + link['href'] if link['href'].startswith('/') else link['href'],
                    'ticker': self._extract_ticker_from_title(link.get_text(strip=True)),
                }
                if transcript['title']:
                    transcripts.append(transcript)
            return transcripts
        
        for article in articles:
            try:
                # Extract title and URL
                title_elem = article.select_one('a[data-test-id="post-list-item-title"]') or article.find('a')
                if not title_elem:
                    continue
                    
                title = title_elem.get_text(strip=True)
                url = title_elem.get('href', '')
                if url and url.startswith('/'):
                    url = self.BASE_URL + url
                
                # Extract date
                date_elem = article.select_one('time') or article.select_one('[data-test-id="post-list-item-date"]')
                date_str = date_elem.get('datetime', date_elem.get_text(strip=True)) if date_elem else None
                
                # Extract ticker symbol
                ticker_elem = article.select_one('[data-test-id="post-list-item-ticker"]')
                ticker = ticker_elem.get_text(strip=True) if ticker_elem else self._extract_ticker_from_title(title)
                
                transcript = {
                    'title': title,
                    'url': url,
                    'ticker': ticker,
                    'date': date_str,
                }
                transcripts.append(transcript)
                
            except Exception as e:
                self._log(f"  Error parsing article: {e}")
                continue
                
        return transcripts
    
    def parse_api_response(self, data: dict) -> list[dict]:
        """
        Parse transcript listings from API response.
        
        Args:
            data: JSON response from API
            
        Returns:
            List of transcript dictionaries
        """
        transcripts = []
        
        articles = data.get('data', [])
        included = {item['id']: item for item in data.get('included', [])}
        
        for article in articles:
            try:
                attrs = article.get('attributes', {})
                
                # Get ticker from relationships
                ticker_ids = article.get('relationships', {}).get('primaryTickers', {}).get('data', [])
                ticker = None
                if ticker_ids and ticker_ids[0]['id'] in included:
                    ticker_data = included[ticker_ids[0]['id']]
                    ticker = ticker_data.get('attributes', {}).get('slug', '').upper()
                
                transcript = {
                    'id': article.get('id'),
                    'title': attrs.get('title'),
                    'url': f"{self.BASE_URL}{attrs.get('gettyImageUrl', '').replace('/v1/gettyimages', '')}" if attrs.get('gettyImageUrl') else None,
                    'ticker': ticker or self._extract_ticker_from_title(attrs.get('title', '')),
                    'date': attrs.get('publishOn'),
                    'summary': attrs.get('summary'),
                }
                
                # Construct proper URL
                if article.get('links', {}).get('self'):
                    transcript['url'] = f"{self.BASE_URL}{article['links']['self']}"
                    
                transcripts.append(transcript)
                
            except Exception as e:
                self._log(f"  Error parsing API article: {e}")
                continue
                
        return transcripts
    
    def _extract_ticker_from_title(self, title: str) -> Optional[str]:
        """Extract stock ticker from transcript title."""
        import re
        # Common patterns: "Company Name (TICK)" or "TICK - Company Name"
        match = re.search(r'\(([A-Z]{1,5})\)', title)
        if match:
            return match.group(1)
        match = re.search(r'^([A-Z]{1,5})\s*[-–—]', title)
        if match:
            return match.group(1)
        return None
    
    def scrape_transcripts(self, max_pages: int = 5) -> list[dict]:
        """
        Scrape earnings call transcript listings.
        
        Args:
            max_pages: Maximum number of pages to scrape
            
        Returns:
            List of transcript dictionaries
        """
        all_transcripts = []
        
        self._log(f"Starting scrape of {max_pages} page(s)...")
        
        for page in range(1, max_pages + 1):
            self._log(f"\nPage {page}/{max_pages}")
            
            # Try API first (usually more reliable)
            self._log("  Trying API endpoint...")
            api_data = self.fetch_via_api(page=page)
            
            if api_data:
                transcripts = self.parse_api_response(api_data)
                if transcripts:
                    self._log(f"  Found {len(transcripts)} transcripts via API")
                    all_transcripts.extend(transcripts)
                    self._random_delay()
                    continue
            
            # Fallback to HTML scraping
            self._log("  API failed, trying HTML scrape...")
            
            url = self.TRANSCRIPTS_URL
            if page > 1:
                url = f"{url}?page={page}"
                
            response = self.fetch_page(url)
            
            if response:
                transcripts = self.parse_html_page(response.text)
                self._log(f"  Found {len(transcripts)} transcripts via HTML")
                all_transcripts.extend(transcripts)
            else:
                self._log(f"  Failed to fetch page {page}")
                
            self._random_delay()
            
        # Deduplicate by URL
        seen = set()
        unique = []
        for t in all_transcripts:
            if t['url'] and t['url'] not in seen:
                seen.add(t['url'])
                unique.append(t)
                
        self._log(f"\nTotal unique transcripts: {len(unique)}")
        return unique
    
    def scrape_transcript_content(self, url: str) -> Optional[dict]:
        """
        Scrape the full content of a single transcript.
        
        Args:
            url: URL of the transcript page
            
        Returns:
            Dictionary with transcript content or None
        """
        self._log(f"Fetching transcript: {url}")
        
        response = self.fetch_page(url)
        if not response:
            return None
            
        soup = BeautifulSoup(response.text, 'lxml')
        
        # Extract article content
        content_selectors = [
            'article[data-test-id="article-content"]',
            'div[data-test-id="article-body"]',
            '.paywall-full-content',
            '#article-content',
        ]
        
        content = None
        for selector in content_selectors:
            content_elem = soup.select_one(selector)
            if content_elem:
                content = content_elem.get_text(separator='\n', strip=True)
                break
                
        if not content:
            # Try to get any substantial text
            main = soup.find('main') or soup.find('article')
            if main:
                content = main.get_text(separator='\n', strip=True)
        
        return {
            'url': url,
            'content': content,
            'scraped_at': datetime.now().isoformat(),
        }


def main():
    parser = argparse.ArgumentParser(
        description='Scrape Seeking Alpha earnings call transcripts'
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
        '--quiet', '-q',
        action='store_true',
        help='Suppress progress output'
    )
    
    args = parser.parse_args()
    
    scraper = SeekingAlphaScraper(verbose=not args.quiet)
    transcripts = scraper.scrape_transcripts(max_pages=args.pages)
    
    # Save results
    output_path = Path(args.output)
    with open(output_path, 'w') as f:
        json.dump({
            'scraped_at': datetime.now().isoformat(),
            'count': len(transcripts),
            'transcripts': transcripts,
        }, f, indent=2)
        
    print(f"\nSaved {len(transcripts)} transcripts to {output_path}")


if __name__ == '__main__':
    main()
