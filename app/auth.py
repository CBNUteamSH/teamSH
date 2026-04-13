import os
import secrets
import httpx
from flask import Blueprint, current_app, redirect, request, session, url_for
from urllib.parse import urlencode
from .firebase import save_user


auth_bp = Blueprint("auth", __name__)


def _require_env(key):
    val = os.getenv(key)
    if not val:
        raise RuntimeError(f"필수 환경변수 누락: {key}")
    return val


CLIENT_ID     = _require_env("SPOTIFY_CLIENT_ID")
CLIENT_SECRET = _require_env("SPOTIFY_CLIENT_SECRET")
REDIRECT_URI  = _require_env("REDIRECT_URI")
SCOPE         = SCOPE = "user-read-email user-read-private playlist-read-private playlist-read-collaborative user-read-recently-played"

SPOTIFY_AUTH_URL  = "https://accounts.spotify.com/authorize"
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_ME_URL    = "https://api.spotify.com/v1/me"


@auth_bp.route("/auth/spotify")
def spotify_login():
    state = secrets.token_urlsafe(16)
    session["oauth_state"] = state

    params = {
        "response_type": "code",
        "client_id":     CLIENT_ID,
        "scope":         SCOPE,
        "redirect_uri":  REDIRECT_URI,
        "state":         state,
    }
    url = f"{SPOTIFY_AUTH_URL}?{urlencode(params)}"

    # Flask 302 대신 JS로 리다이렉트 → IIS가 가로채지 못함
    return f"""<html><body>
    <script>window.location.href = "{url}";</script>
    <p>리다이렉트 중... <a href="{url}">여기를 클릭하세요</a></p>
    </body></html>"""


@auth_bp.route("/callback")
def spotify_callback():
    code  = request.args.get("code")
    state = request.args.get("state")
    error = request.args.get("error")

    # state 검증 — CSRF 방지
    if not state or state != session.pop("oauth_state", None):
        return {"error": "잘못된 state 값입니다"}, 400

    if error:
        return {"error": "Spotify 인증이 거부되었습니다"}, 400

    try:
        with httpx.Client() as client:
            token_res = client.post(
                SPOTIFY_TOKEN_URL,
                data={
                    "grant_type":   "authorization_code",
                    "code":         code,
                    "redirect_uri": REDIRECT_URI,
                },
                auth=(CLIENT_ID, CLIENT_SECRET),
            )

            if token_res.status_code != 200:
                current_app.logger.error(f"Token error [{token_res.status_code}]: {token_res.text}")
                return {"error": "인증에 실패했습니다. 다시 시도해 주세요."}, 400

            tokens = token_res.json()

            me_res = client.get(
                SPOTIFY_ME_URL,
                headers={"Authorization": f"Bearer {tokens['access_token']}"},
            )
            me_res.raise_for_status()
            user = me_res.json()

    except httpx.HTTPStatusError as e:
        current_app.logger.error(f"ME endpoint error: {e}")
        return {"error": "사용자 정보를 가져오지 못했습니다."}, 400
    except httpx.RequestError as e:
        current_app.logger.error(f"Network error: {e}")
        return {"error": "네트워크 오류가 발생했습니다."}, 503


    save_user(
    {
        "id":           user["id"],
        "display_name": user.get("display_name") or "",
        "email":        user.get("email"),
        "image":        (user.get("images") or [{}])[0].get("url"),
    },
    tokens["access_token"],
    tokens.get("refresh_token", ""),
)

    session["user"] = {
        "id":           user["id"],
        "display_name": user.get("display_name") or "",
        "email":        user.get("email"),
        "image":        (user.get("images") or [{}])[0].get("url"),
    }
    session["access_token"]  = tokens["access_token"]
    session["refresh_token"] = tokens.get("refresh_token")

    return redirect(url_for("main.me"))


def do_refresh_token():
    """내부용 토큰 갱신 헬퍼. 성공 시 True, 실패 시 False 반환."""
    rt = session.get("refresh_token")
    if not rt:
        return False

    try:
        with httpx.Client() as client:
            res = client.post(
                SPOTIFY_TOKEN_URL,
                data={"grant_type": "refresh_token", "refresh_token": rt},
                auth=(CLIENT_ID, CLIENT_SECRET),
            )
    except httpx.RequestError as e:
        current_app.logger.error(f"Refresh network error: {e}")
        return False

    if res.status_code != 200:
        current_app.logger.error(f"Refresh error [{res.status_code}]: {res.text}")
        return False

    new_tokens = res.json()
    session["access_token"] = new_tokens["access_token"]
    # Spotify는 갱신 시 새 refresh_token을 줄 수도 있음
    if "refresh_token" in new_tokens:
        session["refresh_token"] = new_tokens["refresh_token"]
    return True


@auth_bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("main.index"))
