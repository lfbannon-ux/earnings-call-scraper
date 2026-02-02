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

Usage:
    python main.py
    python main.py --tickers AUB-AU,SDF-AU,AJG-US,BRO-US
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
    
    BASE_URL = "https://api.factset.com"
    
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
    
    def search_transcripts(
        self,
        tickers: list[str] = None,
        days_back: int = 90
    ) -> list[dict]:
        """Search for transcripts by ticker or date range."""
        
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days_back)
        
        payload = {
            "data": {
                "startDate": start_date.strftime("%Y-%m-%d"),
                "endDate": end_date.strftime("%Y-%m-%d"),
                "types": ["EarningsCall"]
            }
        }
        
        if tickers:
            payload["data"]["ids"] = tickers
        
        self._log(f"Searching transcripts...")
        if tickers:
            self._log(f"  Tickers: {', '.join(tickers)}")
        
        try:
            response = requests.post(
                f"{self.BASE_URL}/events/v2/transcripts/search",
                headers=self.headers,
                json=payload,
                timeout=30
            )
            response.raise_for_status()
            data = response.json()
            
            transcripts = data.get('data', [])
            self._log(f"  Found {len(transcripts)} transcripts")
            return transcripts
            
        except requests.exceptions.HTTPError as e:
            self._log(f"  HTTP Error: {e.response.status_code}")
            if e.response.status_code == 403:
                self._log("  → Access denied. Check your API entitlements.")
            elif e.response.status_code == 401:
                self._log("  → Authentication failed. Check credentials.")
            try:
                self._log(f"  Response: {e.response.text[:500]}")
            except:
                pass
            return []
        except Exception as e:
            self._log(f"  Error: {e}")
            return []
    
    def get_transcript_by_id(self, transcript_id: str) -> Optional[dict]:
        """Get full transcript content by ID."""
        
        self._log(f"  Fetching transcript {transcript_id}...")
        
        try:
            response = requests.get(
                f"{self.BASE_URL}/events/v2/transcripts/{transcript_id}",
                headers=self.headers,
                timeout=30
            )
            response.raise_for_status()
            return response.json()
            
        except Exception as e:
            self._log(f"    Error: {e}")
            return None
    
    def get_calendar_events(
        self,
        tickers: list[str] = None,
        days_back: int = 30
    ) -> list[dict]:
        """Get earnings calendar events."""
        
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days_back)
        
        payload = {
            "data": {
                "startDate": start_date.strftime("%Y-%m-%d"),
                "endDate": end_date.strftime("%Y-%m-%d"),
                "types": ["EarningsCall", "EarningsRelease"]
            }
        }
        
        if tickers:
            payload["data"]["ids"] = tickers
        
        self._log(f"Fetching calendar events...")
        
        try:
            response = requests.post(
                f"{self.BASE_URL}/events/v2/calendar/events",
                headers=self.headers,
                json=payload,
                timeout=30
            )
            response.raise_for_status()
            data = response.json()
            
            events = data.get('data', [])
            self._log(f"  Found {len(events)} events")
            return events
            
        except requests.exceptions.HTTPError as e:
            self._log(f"  HTTP Error: {e.response.status_code}")
            try:
                self._log(f"  Response: {e.response.text[:500]}")
            except:
                pass
            return []
        except Exception as e:
            self._log(f"  Error: {e}")
            return []
    
    def get_transcripts_for_tickers(self, tickers: list[str]) -> list[dict]:
        """Get transcripts for a list of tickers."""
        
        results = []
        
        # First try transcripts search
        transcripts_meta = self.search_transcripts(tickers=tickers)
        
        if transcripts_meta:
            for meta in transcripts_meta[:20]:
                transcript_id = meta.get('transcriptId') or meta.get('id')
                if transcript_id:
                    full = self.get_transcript_by_id(transcript_id)
                    if full:
                        results.append({
                            **meta,
                            'content': full.get('data', {}).get('content', ''),
                        })
                else:
                    results.append(meta)
            return results
        
        # Fallback to calendar events
        self._log("No transcripts found, trying calendar events...")
        events = self.get_calendar_events(tickers=tickers)
        
        for event in events:
            results.append({
                'ticker': event.get('ticker', event.get('ids', [''])[0] if event.get('ids') else ''),
                'title': event.get('title', event.get('eventTitle', 'Earnings Event')),
                'date': event.get('eventDateTime', event.get('startDateTime')),
                'event_id': event.get('eventId'),
                'type': event.get('type', event.get('eventType')),
            })
        
        return results
    
    def test_connection(self) -> bool:
        """Test API connectivity."""
        
        self._log("Testing FactSet API connection...")
        
        # Try multiple endpoints
        endpoints = [
            f"{self.BASE_URL}/events/v2/transcripts/categories",
            f"{self.BASE_URL}/events/v2/calendar/events",
        ]
        
        for endpoint in endpoints:
            try:
                self._log(f"  Trying: {endpoint}")
                response = requests.get(
                    endpoint,
                    headers=self.headers,
                    timeout=15
                )
                
                self._log(f"    Status: {response.status_code}")
                
                if response.status_code == 200:
                    self._log("  ✓ Connection successful!")
                    return True
                elif response.status_code == 401:
                    self._log("    → Authentication failed")
                elif response.status_code == 403:
                    self._log("    → Access denied (may need entitlement)")
                elif response.status_code == 404:
                    self._log("    → Endpoint not found")
                    
            except Exception as e:
                self._log(f"    Error: {e}")
        
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
        api.test_connection()
        return
    
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
