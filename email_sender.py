#!/usr/bin/env python3
"""
Email utility for sending scraper results.

Configuration via environment variables:
    SMTP_HOST: SMTP server (default: smtp.gmail.com)
    SMTP_PORT: SMTP port (default: 587)
    SMTP_USER: Email username/address
    SMTP_PASSWORD: Email password or app password
    EMAIL_TO: Recipient email (default: lfbannon@gmail.com)
    EMAIL_FROM: Sender email (defaults to SMTP_USER)
"""

import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from typing import Optional
import json


class EmailSender:
    """Simple email sender for scraper results."""
    
    def __init__(
        self,
        smtp_host: Optional[str] = None,
        smtp_port: Optional[int] = None,
        smtp_user: Optional[str] = None,
        smtp_password: Optional[str] = None,
        email_to: Optional[str] = None,
        email_from: Optional[str] = None,
    ):
        self.smtp_host = smtp_host or os.environ.get('SMTP_HOST', 'smtp.gmail.com')
        self.smtp_port = smtp_port or int(os.environ.get('SMTP_PORT', '587'))
        self.smtp_user = smtp_user or os.environ.get('SMTP_USER')
        self.smtp_password = smtp_password or os.environ.get('SMTP_PASSWORD')
        self.email_to = email_to or os.environ.get('EMAIL_TO', 'lfbannon@gmail.com')
        self.email_from = email_from or os.environ.get('EMAIL_FROM', self.smtp_user)
        
    def is_configured(self) -> bool:
        """Check if email is properly configured."""
        return bool(self.smtp_user and self.smtp_password)
    
    def send(
        self,
        subject: str,
        body: str,
        html_body: Optional[str] = None,
        to: Optional[str] = None
    ) -> bool:
        """
        Send an email.
        
        Args:
            subject: Email subject
            body: Plain text body
            html_body: Optional HTML body
            to: Override recipient
            
        Returns:
            True if sent successfully
        """
        if not self.is_configured():
            print("ERROR: Email not configured. Set SMTP_USER and SMTP_PASSWORD env vars.")
            return False
            
        recipient = to or self.email_to
        
        # Create message
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = self.email_from
        msg['To'] = recipient
        
        # Attach plain text
        msg.attach(MIMEText(body, 'plain'))
        
        # Attach HTML if provided
        if html_body:
            msg.attach(MIMEText(html_body, 'html'))
            
        try:
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.starttls()
                server.login(self.smtp_user, self.smtp_password)
                server.send_message(msg)
                print(f"✓ Email sent to {recipient}")
                return True
        except Exception as e:
            print(f"✗ Failed to send email: {e}")
            return False


def format_transcripts_email(transcripts: list[dict], title: str = "Seeking Alpha Transcripts") -> tuple[str, str]:
    """
    Format transcript data as email content.
    
    Returns:
        Tuple of (plain_text, html)
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    # Plain text version
    plain_lines = [
        f"{title}",
        f"Generated: {timestamp}",
        f"Total transcripts: {len(transcripts)}",
        "",
        "=" * 60,
        ""
    ]
    
    for t in transcripts:
        plain_lines.extend([
            f"Ticker: {t.get('ticker', 'N/A')}",
            f"Title: {t.get('title', 'N/A')}",
            f"Date: {t.get('date', 'N/A')}",
            f"URL: {t.get('url', 'N/A')}",
            ""
        ])
        
        if t.get('content'):
            # Include preview of content
            content_preview = t['content'][:500] + "..." if len(t['content']) > 500 else t['content']
            plain_lines.extend([
                "Preview:",
                content_preview,
                ""
            ])
            
        plain_lines.append("-" * 40)
        plain_lines.append("")
    
    plain_text = "\n".join(plain_lines)
    
    # HTML version
    html_rows = ""
    for t in transcripts:
        content_preview = ""
        if t.get('content'):
            preview = t['content'][:300] + "..." if len(t['content']) > 300 else t['content']
            content_preview = f'<p style="color: #666; font-size: 12px; margin-top: 8px;">{preview}</p>'
            
        html_rows += f"""
        <tr>
            <td style="padding: 12px; border-bottom: 1px solid #eee;">
                <strong style="color: #1a73e8;">{t.get('ticker', 'N/A')}</strong>
            </td>
            <td style="padding: 12px; border-bottom: 1px solid #eee;">
                <a href="{t.get('url', '#')}" style="color: #333; text-decoration: none;">
                    {t.get('title', 'N/A')}
                </a>
                {content_preview}
            </td>
            <td style="padding: 12px; border-bottom: 1px solid #eee; color: #666;">
                {t.get('date', 'N/A')}
            </td>
        </tr>
        """
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
    </head>
    <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px;">
        <h1 style="color: #333; border-bottom: 2px solid #1a73e8; padding-bottom: 10px;">
            {title}
        </h1>
        <p style="color: #666;">
            Generated: {timestamp} | Total: {len(transcripts)} transcripts
        </p>
        
        <table style="width: 100%; border-collapse: collapse; margin-top: 20px;">
            <thead>
                <tr style="background: #f5f5f5;">
                    <th style="padding: 12px; text-align: left; width: 80px;">Ticker</th>
                    <th style="padding: 12px; text-align: left;">Title</th>
                    <th style="padding: 12px; text-align: left; width: 120px;">Date</th>
                </tr>
            </thead>
            <tbody>
                {html_rows}
            </tbody>
        </table>
        
        <p style="color: #999; font-size: 12px; margin-top: 30px; border-top: 1px solid #eee; padding-top: 15px;">
            Sent by Seeking Alpha Scraper
        </p>
    </body>
    </html>
    """
    
    return plain_text, html


def send_transcript_email(
    transcripts: list[dict],
    subject: Optional[str] = None,
    to: Optional[str] = None
) -> bool:
    """
    Convenience function to format and send transcript results.
    
    Args:
        transcripts: List of transcript dicts
        subject: Email subject (auto-generated if not provided)
        to: Recipient email
        
    Returns:
        True if sent successfully
    """
    if not subject:
        date_str = datetime.now().strftime("%Y-%m-%d")
        subject = f"Seeking Alpha Transcripts - {date_str}"
        
    plain_text, html = format_transcripts_email(transcripts)
    
    sender = EmailSender()
    return sender.send(subject, plain_text, html, to=to)


# Quick test
if __name__ == "__main__":
    # Test with sample data
    sample = [
        {
            "ticker": "AAPL",
            "title": "Apple Inc. (AAPL) Q1 2025 Earnings Call Transcript",
            "date": "2025-01-30",
            "url": "https://seekingalpha.com/article/example",
            "content": "This is a sample transcript preview text that would contain the earnings call content..."
        },
        {
            "ticker": "MSFT", 
            "title": "Microsoft Corporation (MSFT) Q2 2025 Earnings Call Transcript",
            "date": "2025-01-29",
            "url": "https://seekingalpha.com/article/example2"
        }
    ]
    
    sender = EmailSender()
    if sender.is_configured():
        send_transcript_email(sample)
    else:
        print("Email not configured. Set these environment variables:")
        print("  SMTP_USER=your-email@gmail.com")
        print("  SMTP_PASSWORD=your-app-password")
        print("\nFor Gmail, create an App Password at:")
        print("  https://myaccount.google.com/apppasswords")
