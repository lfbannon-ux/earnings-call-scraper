#!/usr/bin/env python3
"""
Seeking Alpha API - Simple Interface

Clean API wrapper for authenticated Seeking Alpha transcript access.

Usage:
    from seeking_alpha_api import SeekingAlpha
    
    async with SeekingAlpha() as sa:
        # Get latest transcripts
        transcripts = await sa.latest(pages=3)
        
        # Get specific ticker
        aapl = await sa.transcript("AAPL")
        
        # Batch fetch
        results = await sa.batch(["AAPL", "MSFT", "GOOGL"])
"""

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from seeking_alpha_authenticated import SeekingAlphaAPI


class SeekingAlpha:
    """
    Simple async context manager interface for Seeking Alpha.
    
    Example:
        async with SeekingAlpha() as sa:
            data = await sa.transcript("AAPL")
    """
    
    def __init__(
        self,
        session_dir: Optional[Path] = None,
        headless: bool = True,
        verbose: bool = False
    ):
        self._api = SeekingAlphaAPI(
            session_dir=session_dir,
            headless=headless,
            verbose=verbose
        )
        
    async def __aenter__(self):
        await self._api.start()
        
        # Auto-prompt for login if not authenticated
        if not self._api.is_authenticated:
            print("No valid session found. Starting Google login...")
            await self._api.login_with_google()
            
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self._api.close()
        
    @property
    def is_authenticated(self) -> bool:
        return self._api.is_authenticated
        
    async def latest(self, pages: int = 3) -> list[dict]:
        """Get latest transcript listings."""
        return await self._api.get_latest_transcripts(max_pages=pages)
        
    async def transcript(self, ticker_or_url: str) -> Optional[dict]:
        """Get full transcript for a ticker or URL."""
        return await self._api.get_transcript(ticker_or_url)
        
    async def search(self, ticker: str) -> Optional[dict]:
        """Search for latest transcript metadata for a ticker."""
        return await self._api.search_transcript(ticker)
        
    async def batch(self, tickers: list[str]) -> dict[str, dict]:
        """Fetch transcripts for multiple tickers."""
        return await self._api.get_transcripts_for_tickers(tickers)


# =============================================================================
# Synchronous wrapper for non-async code
# =============================================================================

class SeekingAlphaSync:
    """
    Synchronous wrapper for environments that don't support async.
    
    Example:
        sa = SeekingAlphaSync()
        sa.start()
        data = sa.transcript("AAPL")
        sa.close()
    """
    
    def __init__(self, **kwargs):
        self._api = SeekingAlphaAPI(**kwargs)
        self._loop = None
        
    def _get_loop(self):
        if self._loop is None:
            try:
                self._loop = asyncio.get_event_loop()
            except RuntimeError:
                self._loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self._loop)
        return self._loop
        
    def start(self, force_login: bool = False):
        loop = self._get_loop()
        loop.run_until_complete(self._api.start(force_login=force_login))
        
        if not self._api.is_authenticated:
            print("Starting Google login...")
            loop.run_until_complete(self._api.login_with_google())
            
    def close(self):
        loop = self._get_loop()
        loop.run_until_complete(self._api.close())
        
    def latest(self, pages: int = 3) -> list[dict]:
        return self._get_loop().run_until_complete(
            self._api.get_latest_transcripts(max_pages=pages)
        )
        
    def transcript(self, ticker_or_url: str) -> Optional[dict]:
        return self._get_loop().run_until_complete(
            self._api.get_transcript(ticker_or_url)
        )
        
    def search(self, ticker: str) -> Optional[dict]:
        return self._get_loop().run_until_complete(
            self._api.search_transcript(ticker)
        )
        
    def batch(self, tickers: list[str]) -> dict[str, dict]:
        return self._get_loop().run_until_complete(
            self._api.get_transcripts_for_tickers(tickers)
        )


# =============================================================================
# Example usage
# =============================================================================

async def example_async():
    """Example async usage."""
    async with SeekingAlpha(verbose=True) as sa:
        # Get latest transcripts
        print("\n=== Latest Transcripts ===")
        transcripts = await sa.latest(pages=2)
        for t in transcripts[:5]:
            print(f"  {t['ticker']}: {t['title'][:60]}...")
            
        # Get specific transcript
        if transcripts:
            print(f"\n=== Full Transcript: {transcripts[0]['ticker']} ===")
            full = await sa.transcript(transcripts[0]['url'])
            if full:
                print(f"  Title: {full['title']}")
                print(f"  Date: {full['date']}")
                print(f"  Content length: {len(full.get('content', '')) or 0} chars")
                print(f"  Paywalled: {full['is_paywalled']}")


def example_sync():
    """Example sync usage."""
    sa = SeekingAlphaSync(verbose=True)
    
    try:
        sa.start()
        
        print("\n=== Latest Transcripts ===")
        transcripts = sa.latest(pages=2)
        for t in transcripts[:5]:
            print(f"  {t['ticker']}: {t['title'][:60]}...")
            
    finally:
        sa.close()


if __name__ == '__main__':
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == '--sync':
        example_sync()
    else:
        asyncio.run(example_async())
