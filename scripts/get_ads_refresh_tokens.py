"""Generate refresh tokens for the READ-ONLY ad platform users. Run on your own machine, not in the cloud.

  python scripts/get_ads_refresh_tokens.py google      # needs GOOGLE_ADS_CLIENT_ID / _SECRET in env
  python scripts/get_ads_refresh_tokens.py microsoft   # needs MSADS_CLIENT_ID in env

Sign in as the read-only / Viewer user when the browser opens, NOT your admin login. The token
inherits that user's permissions, which is what makes the whole pipeline read-only.
Store the printed token as an environment secret. Don't commit it or paste it into chat.
"""
import os
import sys


def google():
    from google_auth_oauthlib.flow import InstalledAppFlow
    flow = InstalledAppFlow.from_client_config(
        {"installed": {"client_id": os.environ["GOOGLE_ADS_CLIENT_ID"],
                       "client_secret": os.environ["GOOGLE_ADS_CLIENT_SECRET"],
                       "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                       "token_uri": "https://oauth2.googleapis.com/token"}},
        scopes=["https://www.googleapis.com/auth/adwords"])
    creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")
    print("\nGOOGLE_ADS_REFRESH_TOKEN=" + creds.refresh_token)


def microsoft():
    from bingads.authorization import OAuthDesktopMobileAuthCodeGrant
    auth = OAuthDesktopMobileAuthCodeGrant(client_id=os.environ["MSADS_CLIENT_ID"], env="production")
    print("Open this URL, sign in as the Viewer user, then paste the full URL you land on:\n")
    print(auth.get_authorization_endpoint())
    auth.request_oauth_tokens_by_response_uri(input("\nRedirect URL: ").strip())
    print("\nMSADS_REFRESH_TOKEN=" + auth.oauth_tokens.refresh_token)


if __name__ == "__main__":
    {"google": google, "microsoft": microsoft}[sys.argv[1] if len(sys.argv) > 1 else "google"]()
