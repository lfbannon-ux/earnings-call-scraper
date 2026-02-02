#!/usr/bin/env python3
"""
Seeking Alpha Scraper API - Railway Deployment

FastAPI service that exposes the Seeking Alpha scraper as an API.

Environment Variables:
    SEEKING_ALPHA_SESSION_DIR: Path to store session data (default: /app/data/sa_session)
    API_KEY: Optional API key for authentication
"""

import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from seeking_alpha_authenticated import SeekingAlphaAPI


# =============================================================================
# Configuration
# =============================================================================

SESSION_DIR = Path(os.environ.get('SEEKING_ALPHA_SESSION_DIR', '/app/data/sa_session'))
API_KEY = os.environ.get('API_KEY')

# Global scraper instance
scraper: Optional[SeekingAlphaAPI] = None


# =============================================================================
# Models
# =============================================================================

class TranscriptRequest(BaseModel):
    ticker: str

class BatchRequest(BaseModel):
    tickers: list[str]

class HealthResponse(BaseModel):
    status: str
    authenticated: bool
    session_dir: str
    timestamp: str


# =============================================================================
# Auth
# =============================================================================

async def verify_api_key(x_api_key: Optional[str] = Header(None)):
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return True


# =============================================================================
# Lifespan
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    global scraper
    
    # Startup
    print(f"Starting Seeking Alpha scraper...")
    print(f"Session directory: {SESSION_DIR}")
    
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    
    scraper = SeekingAlphaAPI(
        session_dir=SESSION_DIR,
        headless=True,
        verbose=True
    )
    await scraper.start()
    
    if scraper.is_authenticated:
        print("✓ Session restored - authenticated")
    else:
        print("⚠ No valid session - run /login endpoint to authenticate")
    
    yield
    
    # Shutdown
    if scraper:
        await scraper.close()
        print("Scraper closed")


# =============================================================================
# App
# =============================================================================

app = FastAPI(
    title="Seeking Alpha Scraper API",
    description="API for fetching earnings call transcripts from Seeking Alpha",
    version="1.0.0",
    lifespan=lifespan
)


@app.get("/health", response_model=HealthResponse)
async def health():
    """Health check endpoint."""
    return HealthResponse(
        status="ok",
        authenticated=scraper.is_authenticated if scraper else False,
        session_dir=str(SESSION_DIR),
        timestamp=datetime.now().isoformat()
    )


@app.get("/latest")
async def get_latest(
    pages: int = 3,
    _: bool = Depends(verify_api_key)
):
    """Get latest earnings call transcript listings."""
    if not scraper:
        raise HTTPException(status_code=503, detail="Scraper not initialized")
    
    try:
        transcripts = await scraper.get_latest_transcripts(max_pages=pages)
        return {
            "count": len(transcripts),
            "transcripts": transcripts,
            "scraped_at": datetime.now().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/transcript/{ticker}")
async def get_transcript(
    ticker: str,
    _: bool = Depends(verify_api_key)
):
    """Get full transcript for a specific ticker."""
    if not scraper:
        raise HTTPException(status_code=503, detail="Scraper not initialized")
    
    try:
        transcript = await scraper.get_transcript(ticker.upper())
        if not transcript:
            raise HTTPException(status_code=404, detail=f"No transcript found for {ticker}")
        return transcript
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/batch")
async def batch_transcripts(
    request: BatchRequest,
    _: bool = Depends(verify_api_key)
):
    """Fetch transcripts for multiple tickers."""
    if not scraper:
        raise HTTPException(status_code=503, detail="Scraper not initialized")
    
    try:
        results = await scraper.get_transcripts_for_tickers(
            [t.upper() for t in request.tickers]
        )
        return {
            "count": len(results),
            "transcripts": results,
            "scraped_at": datetime.now().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/search/{ticker}")
async def search_transcript(
    ticker: str,
    _: bool = Depends(verify_api_key)
):
    """Search for transcript metadata by ticker."""
    if not scraper:
        raise HTTPException(status_code=503, detail="Scraper not initialized")
    
    try:
        result = await scraper.search_transcript(ticker.upper())
        if not result:
            raise HTTPException(status_code=404, detail=f"No transcript found for {ticker}")
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/status")
async def auth_status():
    """Check authentication status."""
    return {
        "authenticated": scraper.is_authenticated if scraper else False,
        "session_file_exists": (SESSION_DIR / "auth_state.json").exists(),
        "message": "Ready" if (scraper and scraper.is_authenticated) else "Login required - see /login"
    }


@app.post("/login")
async def trigger_login():
    """
    Trigger Google login flow.
    
    Note: This requires manual interaction in a browser.
    For Railway deployment, run locally first to generate session,
    then copy the session file to Railway's persistent storage.
    """
    return {
        "message": "Google login requires browser interaction",
        "instructions": [
            "1. Run locally: python seeking_alpha_authenticated.py --login",
            "2. Complete Google sign-in in the browser",
            "3. Copy ~/.seeking_alpha_session/auth_state.json to Railway volume",
            "4. Restart the Railway service"
        ]
    }


# =============================================================================
# Run directly
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
