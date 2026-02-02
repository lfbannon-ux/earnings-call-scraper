#!/usr/bin/env python3
"""
FactSet API Access Tester

Tests which FactSet APIs your account has access to.
"""

import os
import sys
from datetime import datetime
import requests
from requests.auth import HTTPBasicAuth


def test_factset_apis():
    username = os.environ.get('FACTSET_USERNAME')
    api_key = os.environ.get('FACTSET_API_KEY')
    
    if not username or not api_key:
        print("ERROR: Set FACTSET_USERNAME and FACTSET_API_KEY")
        sys.exit(1)
    
    auth = HTTPBasicAuth(username, api_key)
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    
    print("\n" + "=" * 70)
    print("FACTSET API ACCESS TESTER")
    print(f"Account: {username}")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)
    
    # List of APIs to test
    apis_to_test = [
        # Events and Transcripts
        ("Events - Calendar", "GET", "https://api.factset.com/content/events/v2/meta/categories", None),
        ("Events - Transcripts", "POST", "https://api.factset.com/content/events/v2/transcripts", 
         {"data": {"startDate": "2025-01-01", "endDate": "2025-01-07", "timeZone": "America/New_York"}, "meta": {"pagination": {"limit": 5, "offset": 0}}}),
        
        # FactSet Fundamentals
        ("Fundamentals", "GET", "https://api.factset.com/content/factset-fundamentals/v2/fundamentals", None),
        
        # FactSet Estimates  
        ("Estimates", "GET", "https://api.factset.com/content/factset-estimates/v2/consensus", None),
        
        # FactSet Prices
        ("Prices", "GET", "https://api.factset.com/content/factset-prices/v1/prices", None),
        
        # FactSet Entity
        ("Entity", "POST", "https://api.factset.com/content/factset-entity/v1/entity-references",
         {"ids": ["AAPL-US"]}),
        
        # Formula API
        ("Formula API", "POST", "https://api.factset.com/formula-api/v1/time-series",
         {"data": {"ids": ["AAPL-US"], "formulas": ["P_PRICE"]}}),
        
        # FactSet Search
        ("Search - Lookup", "GET", "https://api.factset.com/idsearch/v1/idsearch", None),
        
        # StreetAccount News
        ("StreetAccount News", "GET", "https://api.factset.com/streetaccount/v1/headlines", None),
        
        # Global Filings
        ("Global Filings", "GET", "https://api.factset.com/global-filings/v1/filings", None),
        
        # Real-Time News
        ("Real-Time News", "GET", "https://api.factset.com/real-time-news/v1/headlines", None),
        
        # Concordance
        ("Concordance", "GET", "https://api.factset.com/content/factset-concordance/v2/entity-match", None),
        
        # People
        ("People", "GET", "https://api.factset.com/content/factset-people/v1/company-people", None),
        
        # Ownership
        ("Ownership", "GET", "https://api.factset.com/content/factset-ownership/v1/security-holders", None),
        
        # Content API - Company Reports
        ("Company Reports", "GET", "https://api.factset.com/content/company-report/v1/reports", None),
        
        # Documents Distributor
        ("Documents Distributor", "GET", "https://api.factset.com/bulk-documents/news/v1/list-files", None),
    ]
    
    accessible = []
    forbidden = []
    other_errors = []
    
    print("\nTesting APIs...\n")
    
    for name, method, url, payload in apis_to_test:
        try:
            if method == "GET":
                response = requests.get(url, auth=auth, headers=headers, timeout=15)
            else:
                response = requests.post(url, auth=auth, headers=headers, json=payload, timeout=15)
            
            status = response.status_code
            
            if status == 200:
                print(f"  ✓ {name:25} - ACCESSIBLE (200)")
                accessible.append((name, url))
            elif status == 401:
                print(f"  ✗ {name:25} - AUTH FAILED (401)")
                other_errors.append((name, "Auth failed"))
            elif status == 403:
                print(f"  ✗ {name:25} - FORBIDDEN (403)")
                forbidden.append((name, url))
            elif status == 400:
                # 400 often means the API is accessible but we sent bad params
                print(f"  ? {name:25} - BAD REQUEST (400) - API may be accessible")
                accessible.append((name, url + " (needs valid params)"))
            elif status == 404:
                print(f"  ? {name:25} - NOT FOUND (404)")
                other_errors.append((name, "Endpoint not found"))
            else:
                print(f"  ? {name:25} - STATUS {status}")
                other_errors.append((name, f"Status {status}"))
                
        except requests.exceptions.Timeout:
            print(f"  ? {name:25} - TIMEOUT")
            other_errors.append((name, "Timeout"))
        except Exception as e:
            print(f"  ? {name:25} - ERROR: {str(e)[:30]}")
            other_errors.append((name, str(e)[:50]))
    
    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    
    print(f"\n✓ ACCESSIBLE ({len(accessible)}):")
    if accessible:
        for name, url in accessible:
            print(f"    - {name}")
    else:
        print("    None")
    
    print(f"\n✗ FORBIDDEN ({len(forbidden)}):")
    if forbidden:
        for name, url in forbidden:
            print(f"    - {name}")
    else:
        print("    None")
    
    if other_errors:
        print(f"\n? OTHER ({len(other_errors)}):")
        for name, error in other_errors:
            print(f"    - {name}: {error}")
    
    print("\n" + "=" * 70)
    
    if accessible:
        print("\nYou have access to some APIs! We can potentially use these.")
    else:
        print("\nNo accessible APIs found. Contact FactSet support.")
    
    print("=" * 70 + "\n")


if __name__ == "__main__":
    test_factset_apis()
