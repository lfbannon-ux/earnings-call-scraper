#!/usr/bin/env python3
"""
FactSet Earnings Call Transcripts Scraper

Fetches earnings call transcripts via FactSet's Events and Transcripts API.

Environment Variables:
    FACTSET_USERNAME: FactSet USERNAME-SERIAL
    FACTSET_API_KEY: FactSet API Key
    SMTP_USER: Email username
    SMTP_PASSWORD: Email app password
    EMAIL_TO: Recipient (default: lfbannon@gmail.com)
    TICKERS: Comma-separated tickers to fetch
"""

import argparse
import base64
import os
import sys
from datetime import datetime, timedelta
from typing import Optional
import requests

from email_sender import EmailSender, send_transcript_email


class FactSetAPI:
    """FactSet Events and Transcripts API client."""
    
    # Correct base URL
    BASE_URL = "https://api.factset.com/content/events/v2"
    
    def __init__(
        self,
        username: Optional[str] = None,
        api_key: Optional[str] = None,
        verbose: bool = True
    ):
        self.username = username or os.environ.get('FACTSET_USERNAME')
        self.api_key = api_key or os.environ.get('FACTSET_API_KEY')
        self.verbose = verbose
        
        if not self.username or not self.api_key:
            raise ValueError("FACTSET_USERNAME and FACTSET_API_KEY required")
        
        # Create auth header
        credentials = f"{self.username}:{self.api_key}"
        encoded = base64.b64encode(credentials.encode()).decode()
        self.headers = {
            "Authorization": f"Basic {encoded}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        
    def _log(self, message: str):
        if self.verbose:
            print(message)
    
    def _make_request(self, method: str, endpoint: str, **kwargs) -> Optional[requests.Response]:
        """Make API request with error handling."""
        url = f"{self.BASE_URL}{endpoint}"
        self._log(f"  Request: {method} {url}")
        
        try:
            response = requests.request(
                method,
                url,
                headers=self.headers,
                timeout=30,
                **kwargs
            )
            self._log(f"  Status: {response.status_code}")
            return response
        except Exception as e:
            self._log(f"  Error: {e}")
            return None

    def get_categories(self) -> list[dict]:
        """Get available transcript categories - useful for testing connection."""
        self._log("Getting categories (connection test)...")
        
        response = self._make_request("GET", "/transcripts/categories")
        
        if response and response.status_code == 200:
            data = response.json()
            categories = data.get('data', [])
            self._log(f"  ✓ Found {len(categories)} categories")
            return categories
        elif response:
            self._log(f"  Response: {response.text[:300]}")
        
        return []

    def search_transcripts(
        self,
        tickers: list[str] = None,
        days_back: int = 90
    ) -> list[dict]:
        """Search for transcripts by ticker or date range."""
        
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days_back)
        
        # Build request payload per FactSet API spec
        payload = {
            "data": {
                "startDate": start_date.strftime("%Y-%m-%d"),
                "endDate": end_date.strftime("%Y-%m-%d"),
                "eventTypes": ["EarningsCall"]
            }
        }
        
        if tickers:
            payload["data"]["ids"] = tickers
        
        self._log(f"Searching transcripts...")
        if tickers:
            self._log(f"  Tickers: {', '.join(tickers)}")
        self._log(f"  Date range: {payload['data']['startDate']} to {payload['data']['endDate']}")
        
        response = self._make_request("POST", "/transcripts/search", json=payload)
        
        if response and response.status_code == 200:
            data = response.json()
            transcripts = data.get('data', [])
            self._log(f"  ✓ Found {len(transcripts)} transcripts")
            return transcripts
        elif response:
            self._log(f"  Response: {response.text[:500]}")
        
        return []
    
    def get_company_events(
        self,
        tickers: list[str] = None,
        days_back: int = 30,
        days_forward: int = 30
    ) -> list[dict]:
        """Get earnings calendar events."""
        
        end_date = datetime.now() + timedelta(days=days_forward)
        start_date = datetime.now() - timedelta(days=days_back)
        
        payload = {
            "data": {
                "startDate": start_date.strftime("%Y-%m-%d"),
                "endDate": end_date.strftime("%Y-%m-%d"),
            }
        }
        
        if tickers:
            payload["data"]["ids"] = tickers
        
        self._log(f"Fetching company events...")
        
        response = self._make_request("POST", "/calendar/events", json=payload)
        
        if response and response.status_code == 200:
            data = response.json()
            events = data.get('data', [])
            self._log(f"  ✓ Found {len(events)} events")
            return events
        elif response:
            self._log(f"  Response: {response.text[:500]}")
        
        return []

    def get_transcript_content(self, report_id: str) -> Optional[str]:
        """Download transcript XML content."""
        
        self._log(f"  Fetching transcript content for {report_id}...")
        
        response = self._make_request("GET", f"/transcripts/{report_id}")
        
        if response and response.status_code == 200:
            return response.text
        
        return None

    def get_transcripts_for_tickers(self, tickers: list[str]) -> list[dict]:
        """Get transcripts for a list of tickers."""
        
        results = []
        
        # Try transcript search first
        transcripts = self.search_transcripts(tickers=tickers)
        
        if transcripts:
            for t in transcripts[:20]:
                result = {
                    'ticker': t.get('primaryIds', [''])[0] if t.get('primaryIds') else t.get('ticker', ''),
                    'title': t.get('title', t.get('eventTitle', 'Earnings Call')),
                    'date': t.get('eventDateTime', t.get('transcriptDateTime', '')),
                    'report_id': t.get('reportId', t.get('report_id', '')),
                    'url': t.get('transcriptsUrl', t.get('transcripts_url', '')),
                }
                results.append(result)
            return results
        
        # Fallback to calendar events
        self._log("No transcripts found, trying calendar events...")
        events = self.get_company_events(tickers=tickers)
        
        for event in events:
            result = {
                'ticker': event.get('ticker', ''),
                'title': event.get('eventTitle', event.get('title', 'Earnings Event')),
                'date': event.get('eventDateTime', event.get('startDateTime', '')),
                'type': event.get('eventType', ''),
            }
            if result['ticker'] or result['title']:
                results.append(result)
        
        return results
    
    def test_connection(self) -> bool:
        """Test API connectivity."""
        
        self._log("Testing FactSet API connection...")
        self._log(f"  Username: {self.username}")
        self._log(f"  Base URL: {self.BASE_URL}")
        
        # Try categories endpoint (simple GET)
        categories = self.get_categories()
        if categories:
            return True
        
        # Try a simple search
        self._log("\nTrying transcript search...")
        transcripts = self.search_transcripts(tickers=["AAPL-US"], days_back=30)
        if transcripts:
            return True
        
        self._log("\n✗ Could not connect to FactSet API")
        self._log("  Possible issues:")
        self._log("  - API credentials may be incorrect")
        self._log("  - Account may not have Events & Transcripts API entitlement")
        self._log("  - Contact FactSet support to verify API access")
        
        return False


def main():
    parser = argparse.ArgumentParser(description='FactSet Transcripts Scraper')
    parser.add_argument('--tickers', type=str, help='Comma-separated tickers')
    parser.add_argument('--days', type=int, default=30, help='Days to look back')
    parser.add_argument('--dry-run', action='store_true', help='Skip email')
    parser.add_argument('--test', action='store_true', help='Test API connection only')
    
    args = parser.parse_args()
    
    print("\n" + "=" * 60)
    print("FACTSET TRANSCRIPTS SCRAPER")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    # Check FactSet credentials
    if not os.environ.get('FACTSET_USERNAME') or not os.environ.get('FACTSET_API_KEY'):
        print("\n✗ FACTSET CREDENTIALS NOT SET")
        print("  Set FACTSET_USERNAME and FACTSET_API_KEY environment variables")
        sys.exit(1)
    
    print(f"FactSet User: {os.environ.get('FACTSET_USERNAME')}")
    
    # Initialize API
    try:
        api = FactSetAPI(verbose=True)
    except ValueError as e:
        print(f"\n✗ {e}")
        sys.exit(1)
    
    # Test mode
    if args.test:
        success = api.test_connection()
        sys.exit(0 if success else 1)
    
    # Check email config
    email_sender = EmailSender()
    if not email_sender.is_configured():
        print("\n⚠ EMAIL NOT CONFIGURED")
        if not args.dry_run:
            args.dry_run = True
    else:
        print(f"Email: {email_sender.smtp_user} → {email_sender.email_to}")
    
    # Get tickers
    tickers = None
    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(',')]
    elif os.environ.get('TICKERS'):
        tickers = [t.strip().upper() for t in os.environ['TICKERS'].split(',')]
    
    if not tickers:
        print("\n⚠ No tickers specified")
        print("  Set TICKERS env var or use --tickers flag")
        print("  Example: --tickers AAPL-US,MSFT-US,AUB-AU")
        sys.exit(1)
    
    print(f"\nFetching transcripts for: {', '.join(tickers)}")
    transcripts = api.get_transcripts_for_tickers(tickers)
    
    # Results
    print(f"\n{'=' * 60}")
    print(f"RESULTS: {len(transcripts)} items")
    print("=" * 60)
    
    if not transcripts:
        print("No transcripts found.")
        print("\nTips:")
        print("  - Use FactSet ticker format: SYMBOL-EXCHANGE")
        print("  - Examples: AAPL-US, AUB-AU, BRO-US")
        print("  - Run with --test to verify API connection")
        return
    
    for t in transcripts:
        ticker = t.get('ticker', 'N/A')
        date = str(t.get('date', ''))[:10] if t.get('date') else 'N/A'
        title = t.get('title', 'No title')[:50]
        print(f"  {ticker:12} | {date} | {title}...")
    
    # Send email
    if args.dry_run:
        print("\n[Dry run - skipping email]")
    else:
        print(f"\n{'=' * 60}")
        print("SENDING EMAIL")
        print("=" * 60)
        
        subject = f"FactSet Transcripts - {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        success = send_transcript_email(transcripts, subject=subject)
        
        if success:
            print("✓ Email sent!")
        else:
            print("✗ Failed to send email")
            sys.exit(1)
    
    print(f"\n{'=' * 60}")
    print("DONE")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
