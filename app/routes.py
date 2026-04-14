import httpx
from flask import Blueprint, session, redirect, url_for, render_template, Response
from .auth import do_refresh_token
import json

main_bp = Blueprint("main", __name__)

SPOTIFY_BASE = "https://api.spotify.com/v1"
MAX_PAGES    = 50  # 페이지네이션 무한루프 방지 (최대 5000곡)


def get_auth_header():
    token = session.get("access_token")
    if not token:
        raise ValueError("No access token in session")
    return {"Authorization": f"Bearer {token}"}


def spotify_get(client, url, **kwargs):
    """
    GET 요청 래퍼.
    - 401(토큰 만료) 시 자동 갱신 후 1회 재시도
    - 429(Rate Limit) 시 None 반환
    - 네트워크/HTTP 오류 시 None 반환
    """
    try:
        res = client.get(url, headers=get_auth_header(), **kwargs)

        if res.status_code == 401:
            if do_refresh_token():
                res = client.get(url, headers=get_auth_header(), **kwargs)
            else:
                return None

        if res.status_code == 429:
            retry_after = res.headers.get("Retry-After", "N/A")
            # 로거가 없는 환경을 고려해 print로 fallback
            try:
                from flask import current_app
                current_app.logger.warning(f"Spotify rate limit hit. Retry-After: {retry_after}s")
            except RuntimeError:
                print(f"[WARN] Spotify rate limit hit. Retry-After: {retry_after}s")
            return None

        res.raise_for_status()
        return res

    except httpx.HTTPStatusError:
        return None
    except httpx.RequestError:
        return None


@main_bp.route("/")
def index():
    if session.get("user"):
        return redirect(url_for("main.me"))
    return render_template("me.html", user=None)


@main_bp.route("/me")
def me():
    user = session.get("user")
    if not user:
        return redirect(url_for("auth.spotify_login"))
    return render_template("me.html", user=user)

@main_bp.route("/cup")
def cup():
    user = session.get("user")
    if not user:
        return redirect(url_for("auth.spotify_login"))
    return render_template("cup.html", user=user)

@main_bp.route("/cupEnter")
def cupEnter():
    user = session.get("user")
    if not user:
        return redirect(url_for("auth.spotify_login"))
    return render_template("cupEnter.html", user=user)

@main_bp.route("/playlists")
def playlists():
    if not session.get("user"):
        return redirect(url_for("auth.spotify_login"))

    with httpx.Client() as client:
        res = spotify_get(client, f"{SPOTIFY_BASE}/me/playlists", params={"limit": 50})
        if res is None:
            return redirect(url_for("auth.spotify_login"))
        data = res.json()
        playlist_items = data.get("items", [])

    return render_template("playlist.html", playlists=playlist_items)


@main_bp.route("/playlists/<playlist_id>")
def playlist_detail(playlist_id):
    if not session.get("user"):
        return redirect(url_for("auth.spotify_login"))

    with httpx.Client() as client:
        # 플레이리스트 정보
        pl_res = spotify_get(client, f"{SPOTIFY_BASE}/playlists/{playlist_id}")
        if pl_res is None:
            return redirect(url_for("auth.spotify_login"))
        playlist = pl_res.json()

        # 트랙 목록 — 페이지네이션으로 전체 수집
        tracks = []
        url    = f"{SPOTIFY_BASE}/playlists/{playlist_id}/tracks"
        page   = 0
        while url and page < MAX_PAGES:
            tr_res = spotify_get(client, url, params={"limit": 100})
            if tr_res is None:
                return redirect(url_for("auth.spotify_login"))
            tr_data = tr_res.json()
            tracks.extend(tr_data.get("items", []))
            url = tr_data.get("next")  # 다음 페이지 URL (없으면 None)
            page += 1

    return render_template("playlist.html", playlist=playlist, tracks=tracks)


@main_bp.errorhandler(404)
def not_found(e):
    return render_template("404.html"), 404


@main_bp.errorhandler(500)
def server_error(e):
    return render_template("500.html"), 500

@main_bp.route("/history")
def listening_history():
    if not session.get("user"):
        return redirect(url_for("auth.spotify_login"))

    with httpx.Client() as client:
        res = spotify_get(
            client,
            f"{SPOTIFY_BASE}/me/player/recently-played",
            params={"limit": 50}
        )
        if res is None:
            return redirect(url_for("auth.spotify_login"))

        data = res.json()

    items = [
        {
            "played_at": item["played_at"],               # ISO 8601
            "track_name": item["track"]["name"],
            "artists": [a["name"] for a in item["track"]["artists"]],
            "album": item["track"]["album"]["name"],
            "duration_ms": item["track"]["duration_ms"],
            "track_id": item["track"]["id"],
            "track_url": item["track"]["external_urls"].get("spotify"),
        }
        for item in data.get("items", [])
    ]

    return Response(
        json.dumps({"count": len(items), "items": items}, ensure_ascii=False, indent=2),
        mimetype="application/json",
        headers={"Content-Disposition": "attachment; filename=listening_history.json"}
    )