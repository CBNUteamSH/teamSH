import os
import secrets
import httpx
from flask import Blueprint, redirect, request, session, url_for

auth_bp = Blueprint("auth", __name__)

CLIENT_ID     = os.getenv("SPOTIFY_CLIENT_ID")
CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
REDIRECT_URI  = os.getenv("REDIRECT_URI")
SCOPE         = SCOPE = os.getenv("SCOPE", "user-read-email user-read-private playlist-read-private playlist-read-collaborative")

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
    url = httpx.URL(SPOTIFY_AUTH_URL).copy_with(params=params)
    return redirect(str(url))


@auth_bp.route("/callback")
def spotify_callback():
    code  = request.args.get("code")
    state = request.args.get("state")
    error = request.args.get("error")

    if error:
        return {"spotify_error": error}, 400

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
        
        # 에러 내용 그대로 출력 (디버깅용)
        if token_res.status_code != 200:
            return {
                "status": token_res.status_code,
                "spotify_response": token_res.json()
            }, 400
        
        tokens = token_res.json()

        me_res = client.get(
            SPOTIFY_ME_URL,
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
        )
        me_res.raise_for_status()
        user = me_res.json()

    session["user"] = {
        "id":           user["id"],
        "display_name": user.get("display_name"),
        "email":        user.get("email"),
        "image":        user["images"][0]["url"] if user.get("images") else None,
    }
    session["access_token"]  = tokens["access_token"]
    session["refresh_token"] = tokens["refresh_token"]

    return redirect(url_for("main.me"))

@auth_bp.route("/refresh")
def refresh_token():
    rt = session.get("refresh_token")
    if not rt:
        return {"error": "로그인이 필요합니다"}, 401

    with httpx.Client() as client:
        res = client.post(
            SPOTIFY_TOKEN_URL,
            data={"grant_type": "refresh_token", "refresh_token": rt},
            auth=(CLIENT_ID, CLIENT_SECRET),
        )
        res.raise_for_status()
        new_tokens = res.json()

    session["access_token"] = new_tokens["access_token"]
    return {"message": "토큰 갱신 완료"}


@auth_bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("main.index"))