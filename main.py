#!/usr/bin/env python3
"""
Seeking Alpha Scraper - Main Entry Point

Scrapes earnings call transcripts and emails results.

Environment Variables:
    SMTP_USER: Email username (required)
    SMTP_PASSWORD: Email app password (required)
    EMAIL_TO: Recipient (default: lfbannon@gmail.com)
    
    SEEKING_ALPHA_SESSION_DIR: Session storage path
    TICKERS: Comma-separated tickers to fetch (optional)
    PAGES: Number of pages to scrape (default: 3)
    
Usage:
    # With environment variables set
    python main.py
    
    # Or with command line args
    python main.py --tickers AAPL,MSFT,NVDA
    python main.py --pages 5
    python main.py --login  # First-time auth
"""

import asyncio
import argparse
import os
import sys
from datetime import datetime

from seeking_alpha_authenticated import SeekingAlphaAPI
from email_sender import EmailSender, send_transcript_email


async def run_scraper(tickers: list[str] = None, pages: int = 3) -> list[dict]:
    """Run the scraper and return transcripts."""
    
    session_dir = os.environ.get('SEEKING_ALPHA_SESSION_DIR')
    
    api = SeekingAlphaAPI(
        session_dir=session_dir,
        headless=True,
        verbose=True
    )
    
    try:
        await api.start()
        
        if not api.is_authenticated:
            print("⚠ Not authenticated - will only get preview content")
            print("  Run with --login to authenticate with Google")
        
        if tickers:
            print(f"Fetching transcripts for: {', '.join(tickers)}")
            results = []
            for ticker in tickers:
                print(f"  → {ticker}...")
                transcript = await api.get_transcript(ticker)
                if transcript:
                    results.append(transcript)
                    print(f"    ✓ Found: {transcript.get('title', 'No title')[:50]}...")
                else:
                    print(f"    ✗ No transcript found")
            return results
        else:
            print(f"Fetching latest transcripts ({pages} pages)...")
            return await api.get_latest_transcripts(max_pages=pages)
            
    finally:
        await api.close()


async def do_login():
    """Interactive login flow."""
    print("\n" + "=" * 60)
    print("GOOGLE LOGIN")
    print("=" * 60)
    
    session_dir = os.environ.get('SEEKING_ALPHA_SESSION_DIR')
    
    api = SeekingAlphaAPI(
        session_dir=session_dir,
        headless=False,  # Need visible browser for OAuth
        verbose=True
    )
    
    try:
        await api.start(force_login=True)
        success = await api.login_with_google()
        
        if success:
            print("\n✓ Login successful! Session saved.")
            print("  Run again without --login to scrape.")
        else:
            print("\n✗ Login failed or timed out.")
            sys.exit(1)
    finally:
        await api.close()


async def main():
    parser = argparse.ArgumentParser(description='Seeking Alpha Scraper')
    parser.add_argument('--login', action='store_true', help='Authenticate with Google')
    parser.add_argument('--tickers', type=str, help='Comma-separated tickers (or set TICKERS env var)')
    parser.add_argument('--pages', type=int, help='Pages to scrape (or set PAGES env var)')
    parser.add_argument('--dry-run', action='store_true', help='Skip email, just print results')
    
    args = parser.parse_args()
    
    print("\n" + "=" * 60)
    print("SEEKING ALPHA SCRAPER")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    # Handle login
    if args.login:
        await do_login()
        return
    
    # Check email config
    email_sender = EmailSender()
    if not email_sender.is_configured():
        print("\n⚠ EMAIL NOT CONFIGURED")
        print("  Set SMTP_USER and SMTP_PASSWORD environment variables")
        print("  For Gmail, use an App Password from:")
        print("  https://myaccount.google.com/apppasswords")
        if not args.dry_run:
            print("\nContinuing in dry-run mode...\n")
            args.dry_run = True
    else:
        print(f"Email: {email_sender.smtp_user} → {email_sender.email_to}")
    
    # Get tickers from args or env
    tickers = None
    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(',')]
    elif os.environ.get('TICKERS'):
        tickers = [t.strip().upper() for t in os.environ['TICKERS'].split(',')]
    
    # Get pages from args or env
    pages = args.pages or int(os.environ.get('PAGES', '3'))
    
    # Run scraper
    print()
    try:
        transcripts = await run_scraper(tickers=tickers, pages=pages)
    except Exception as e:
        print(f"\n✗ Scraper error: {e}")
        print("  Try running with --login first")
        sys.exit(1)
    
    # Results summary
    print(f"\n{'=' * 60}")
    print(f"RESULTS: {len(transcripts)} transcripts")
    print("=" * 60)
    
    if not transcripts:
        print("No transcripts found.")
        return
    
    for t in transcripts:
        ticker = t.get('ticker', 'N/A')
        date = t.get('date', '')[:10] if t.get('date') else 'N/A'
        title = t.get('title', 'No title')[:55]
        paywalled = " [PAYWALLED]" if t.get('is_paywalled') else ""
        print(f"  {ticker:6} | {date} | {title}...{paywalled}")
    
    # Send email
    if args.dry_run:
        print("\n[Dry run - skipping email]")
    else:
        print(f"\n{'=' * 60}")
        print("SENDING EMAIL")
        print("=" * 60)
        
        date_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        subject = f"Seeking Alpha Transcripts - {date_str}"
        
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
    asyncio.run(main())
