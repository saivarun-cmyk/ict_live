"""
Daily Kite Login Script.
Run this every morning at 08:50 AM IST before market opens.
It opens a browser for Zerodha login → captures the request_token →
generates an access_token → saves it to .env.

Usage:
    python scripts/kite_login.py

Requires:
    KITE_API_KEY and KITE_API_SECRET set in .env
"""
import os
import sys
import webbrowser
from urllib.parse import urlparse, parse_qs
from dotenv import load_dotenv, set_key

# Load .env from project root
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_FILE = os.path.join(BASE_DIR, ".env")
load_dotenv(ENV_FILE)

try:
    from kiteconnect import KiteConnect
except ImportError:
    print("ERROR: kiteconnect not installed. Run: pip install kiteconnect")
    sys.exit(1)


def main():
    api_key    = os.getenv("KITE_API_KEY", "").strip()
    api_secret = os.getenv("KITE_API_SECRET", "").strip()

    if not api_key:
        print("\n❌  KITE_API_KEY not set in .env")
        print("    Add it to .env: KITE_API_KEY=your_key_here")
        sys.exit(1)

    if not api_secret:
        print("\n❌  KITE_API_SECRET not set in .env")
        print("    Add it to .env: KITE_API_SECRET=your_secret_here")
        sys.exit(1)

    kite = KiteConnect(api_key=api_key)

    login_url = kite.login_url()
    print("\n" + "="*60)
    print("  Zerodha Kite Login")
    print("="*60)
    print(f"\n  Opening browser to log in...")
    print(f"  URL: {login_url}")
    print()
    webbrowser.open(login_url)

    print("  After logging in, Zerodha will redirect to a URL like:")
    print("  https://127.0.0.1?request_token=XXXXX&action=login&status=success")
    print()
    redirect_url = input("  Paste the full redirect URL here: ").strip()

    # Parse request_token from URL
    try:
        parsed = urlparse(redirect_url)
        params = parse_qs(parsed.query)
        request_token = params.get("request_token", [None])[0]
        if not request_token:
            # Try fragment
            params2 = parse_qs(parsed.fragment)
            request_token = params2.get("request_token", [None])[0]
    except Exception:
        request_token = None

    if not request_token:
        print("\n❌  Could not find request_token in the URL. Please try again.")
        sys.exit(1)

    print(f"\n  request_token: {request_token[:10]}...  ✅")
    print("  Generating access token...")

    try:
        session = kite.generate_session(request_token, api_secret=api_secret)
        access_token = session["access_token"]
        user_id      = session.get("user_id", "")
        user_name    = session.get("user_name", "")
    except Exception as e:
        print(f"\n❌  Failed to generate session: {e}")
        sys.exit(1)

    # Save to .env
    set_key(ENV_FILE, "KITE_ACCESS_TOKEN", access_token)
    set_key(ENV_FILE, "KITE_USER_ID",      user_id)

    print(f"\n✅  Access token generated and saved to .env")
    print(f"    User: {user_name} ({user_id})")
    print(f"    Token: {access_token[:20]}...")
    print()
    print("  You can now run the live engine. Token is valid until 06:00 AM tomorrow.")
    print("  Run this script again tomorrow morning before 09:15 AM IST.")
    print()


if __name__ == "__main__":
    main()
