#!/usr/bin/env python3
"""
FactSet Earnings Call Transcripts Scraper

Fetches earnings call transcripts via FactSet's Events and Transcripts API.

Environment Variables:
    FACTSET_USERNAME: FactSet USERNAME-SERIAL
    FACTSET_API_KEY: FactSet API Key
    SMTP_USER: Email username
    SMTP_PASSWORD: Email app password
    EMAIL_TO: Recipient
    TICKERS: Comma-separated tickers to fetch
"""

import argparse
import os
import sys
from datetime import datetime, timedelta
from typing import Optional
import requests
from requests.auth import HTTPBasicAuth

from email_sender import EmailSender, send_transcript_email


class FactSetAPI:
    """FactSet Events and Transcripts API client."""
    
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
        
        self.auth = HTTPBasicAuth(self.username, self.api_key)
        self.headers = {
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        
    def _log(self, message: str):
        if self.verbose:
            print(message)
    
    def _make_request(self, method: str, endpoint: str, json_data=None, params=None) -> Optional[requests.Response]:
        """Make API request with error handling."""
        url = f"{self.BASE_URL}{endpoint}"
        self._log(f"  Request: {method} {url}")
        if json_data:
            self._log(f"  Payload: {json_data}")
        
        try:
            response = requests.request(
                method,
                url,
                auth=self.auth,
                headers=self.headers,
                json=json_data,
                params=params,
                timeout=30
            )
            self._log(f"  Status: {response.status_code}")
            return response
        except Exception as e:
            self._log(f"  Error: {e}")
            return None

    def get_company_events(
        self,
        tickers: list[str],
        days_back: int = 90,
        days_forward: int = 30
    ) -> list[dict]:
        """Get earnings calendar events - matches exact API format."""
        
        end_date = datetime.now() + timedelta(days=days_forward)
        start_date = datetime.now() - timedelta(days=days_back)
        
        # Exact format from FactSet documentation
        payload = {
            "data": {
                "dateTime": {
                    "start": start_date.strftime("%Y-%m-%dT00:00:00Z"),
                    "end": end_date.strftime("%Y-%m-%dT23:59:59Z")
                },
                "universe": {
                    "symbols": tickers,
                    "type": "Tickers"
                },
                "eventTypes": ["Earnings"]
            }
        }
        
        self._log(f"Fetching company events...")
        
        response = self._make_request("POST", "/calendar/events", json_data=payload)
        
        if response and response.status_code == 200:
            data = response.json()
            events = data.get('data', [])
            self._log(f"  ✓ Found {len(events)} events")
            return events
        elif response:
            self._log(f"  Response: {response.text[:500]}")
        
        return []

    def search_transcripts_by_ids(self, tickers: list[str]) -> list[dict]:
        """Search transcripts by ticker IDs - exact format from documentation."""
        
        # Exact format: TranscriptsByIdsRequest
        payload = {
            "data": {
                "primaryId": False,
                "ids": tickers
            },
            "meta": {
                "pagination": {
                    "limit": 25,
                    "offset": 0
                },
                "sort": ["-storyDateTime"]
            }
        }
        
        self._log(f"Searching transcripts by IDs...")
        
        response = self._make_request("POST", "/transcripts", json_data=payload)
        
        if response and response.status_code == 200:
            data = response.json()
            transcripts = data.get('data', [])
            self._log(f"  ✓ Found {len(transcripts)} transcript groups")
            return transcripts
        elif response:
            self._log(f"  Response: {response.text[:500]}")
        
        return []

    def search_transcripts_by_date(self, days_back: int = 30) -> list[dict]:
        """Search transcripts by date range - exact format from documentation."""
        
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days_back)
        
        # Exact format: TranscriptsByDateRequest
        payload = {
            "data": {
                "startDate": start_date.strftime("%Y-%m-%d"),
                "endDate": end_date.strftime("%Y-%m-%d"),
                "timeZone": "America/New_York"
            },
            "meta": {
                "pagination": {
                    "limit": 25,
                    "offset": 0
                },
                "sort": ["-storyDateTime"]
            }
        }
        
        self._log(f"Searching transcripts by date...")
        
        response = self._make_request("POST", "/transcripts", json_data=payload)
        
        if response and response.status_code == 200:
            data = response.json()
            transcripts = data.get('data', [])
            self._log(f"  ✓ Found {len(transcripts)} transcripts")
            return transcripts
        elif response:
            self._log(f"  Response: {response.text[:500]}")
        
        return []

    def get_transcript_content(self, transcripts_url: str) -> Optional[str]:
        """Download transcript XML content."""
        
        self._log(f"  Downloading transcript...")
        
        try:
            response = requests.get(
                transcripts_url,
                auth=self.auth,
                timeout=30
            )
            if response.status_code == 200:
                return response.text
            else:
                self._log(f"    Failed: {response.status_code}")
        except Exception as e:
            self._log(f"    Error: {e}")
        
        return None

    def get_transcripts_for_tickers(self, tickers: list[str]) -> list[dict]:
        """Get transcripts for a list of tickers."""
        
        results = []
        
        # Try transcript search by IDs first
        self._log(f"\nSearching transcripts for: {', '.join(tickers)}")
        transcripts = self.search_transcripts_by_ids(tickers)
        
        if transcripts:
            # Response format per docs: nested documents array
            for entry in transcripts:
                if 'documents' in entry:
                    # TranscriptsByIdsResponse format
                    for doc in entry.get('documents', []):
                        result = {
                            'ticker': doc.get('primaryIds', [''])[0] if doc.get('primaryIds') else '',
                            'title': doc.get('headline', 'Earnings Call'),
                            'date': doc.get('storyDateTime', ''),
                            'report_id': doc.get('reportId', doc.get('report_id', '')),
                            'url': doc.get('transcriptsUrl', doc.get('transcripts_url', '')),
                            'event_type': doc.get('eventType', ''),
                            'transcript_type': doc.get('transcriptType', ''),
                        }
                        results.append(result)
                else:
                    # Direct transcript response format
                    result = {
                        'ticker': entry.get('primaryIds', [''])[0] if entry.get('primaryIds') else '',
                        'title': entry.get('headline', 'Earnings Call'),
                        'date': entry.get('storyDateTime', ''),
                        'report_id': entry.get('reportId', entry.get('report_id', '')),
                        'url': entry.get('transcriptsUrl', entry.get('transcripts_url', '')),
                        'event_type': entry.get('eventType', ''),
                        'transcript_type': entry.get('transcriptType', ''),
                    }
                    results.append(result)
            
            if results:
                return results
        
        # Fallback to calendar events
        self._log("\nNo transcripts found, trying calendar events...")
        events = self.get_company_events(tickers)
        
        for event in events:
            result = {
                'ticker': event.get('identifier', ''),
                'title': event.get('description', 'Earnings Event'),
                'date': event.get('eventDateTime', ''),
                'entity_name': event.get('entityName', ''),
                'event_type': event.get('eventType', ''),
                'event_id': event.get('eventId', ''),
                'report_id': event.get('reportId', ''),
            }
            if result['ticker'] or result['title']:
                results.append(result)
        
        return results
    
    def test_connection(self) -> bool:
        """Test API connectivity."""
        
        self._log("Testing FactSet API connection...")
        self._log(f"  Username: {self.username}")
        
        # Try /meta/categories (simple GET)
        response = self._make_request("GET", "/meta/categories")
        
        if response and response.status_code == 200:
            self._log("  ✓ /meta/categories works!")
            return True
        
        # Try calendar events with AAPL
        self._log("\nTrying calendar events with AAPL-US...")
        events = self.get_company_events(["AAPL-US"])
        if events:
            self._log("  ✓ Calendar events work!")
            return True
        
        # Try transcripts by date
        self._log("\nTrying transcripts by date...")
        transcripts = self.search_transcripts_by_date(days_back=7)
        if transcripts:
            self._log("  ✓ Transcripts work!")
            return True
        
        self._log("\n✗ Could not connect to FactSet API")
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
    
    print(f"\nFetching data for: {', '.join(tickers)}")
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
        ticker = t.get('ticker', t.get('identifier', 'N/A'))
        date = str(t.get('date', ''))[:10] if t.get('date') else 'N/A'
        title = t.get('title', t.get('description', 'No title'))[:50]
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
