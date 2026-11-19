"""Log the app in to Schwab market data (first time, and again every 7 days).

Run it on the machine that runs the app, from the repo folder:
    .\\.venv\\Scripts\\python.exe python_app\\schwab_login.py           (Windows)
    .venv/bin/python python_app/schwab_login.py                       (Linux)

The first run asks for the App Key and Secret from the Schwab Developer Portal; later runs reuse
the saved ones (add --new-keys to replace them). It prints a Schwab login link. Open it, log in,
approve, and the browser lands on https://127.0.0.1 with an error page; that is expected. Copy the
whole address bar from that page and paste it here. The login is saved DPAPI-protected next to the
Alpaca keys, then one SPY quote is fetched to prove it works.

--status shows what is saved and when the login expires, without printing any key or token.
"""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from alpaca_desktop import schwab_data  # noqa: E402


def print_status(client: schwab_data.SchwabClient) -> None:
    status = client.status()
    if not status["saved"]:
        print("No Schwab login saved.")
        return
    print(f"App key saved: {'yes' if status['has_app_key'] else 'no'}")
    print(f"Secret saved:  {'yes' if status['has_app_secret'] else 'no'}")
    print(f"Callback URL:  {status['callback_url']}")
    print(f"Logged in:     {'yes' if status['logged_in'] else 'no'}")
    if status["login_expires_at"]:
        print(f"Login expires: {status['login_expires_at']} (UTC)")


def check_quote(client: schwab_data.SchwabClient) -> None:
    fields = schwab_data.schwab_quote_fields(client.get_quotes(["SPY"]).get("SPY"))
    if fields is None:
        raise schwab_data.SchwabError("Schwab returned no SPY quote.")
    print(
        f"Test quote OK: SPY last {fields['last']}, bid {fields['bid']}, ask {fields['ask']}, "
        f"realtime={fields['realtime']}, quote type {fields['quote_type'] or '-'}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Log the app in to Schwab market data.")
    parser.add_argument("--status", action="store_true", help="show what is saved, then exit")
    parser.add_argument("--new-keys", action="store_true", help="ask for the App Key and Secret again")
    args = parser.parse_args()

    client = schwab_data.SchwabClient()
    print(f"App folder: {schwab_data.credentials_path().parent}")
    if args.status:
        print_status(client)
        return 0

    saved = {} if args.new_keys else client.load()
    app_key = saved.get("app_key") or getpass.getpass("Schwab App Key (hidden): ").strip()
    app_secret = saved.get("app_secret") or getpass.getpass("Schwab Secret (hidden): ").strip()
    callback_url = saved.get("callback_url") or (
        input(f"Callback URL [{schwab_data.DEFAULT_CALLBACK_URL}]: ").strip() or schwab_data.DEFAULT_CALLBACK_URL
    )
    if not app_key or not app_secret:
        print("App Key and Secret are both required.")
        return 1

    print()
    print("1. Open this link, log in to Schwab, and approve:")
    print(f"   {client.authorize_url(app_key, callback_url)}")
    print(f"2. The browser then goes to {callback_url} and shows an error page. That is expected.")
    print("3. Copy the whole address bar from that page and paste it below right away (the code expires quickly).")
    received_url = input("Redirect URL: ").strip()

    try:
        client.login(app_key, app_secret, callback_url, received_url)
        print("Schwab login saved.")
        check_quote(client)
    except schwab_data.SchwabError as exc:
        print(f"Failed: {exc}")
        return 1
    print_status(client)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
