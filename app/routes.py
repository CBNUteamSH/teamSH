import httpx
from flask import Blueprint, session, redirect, url_for, render_template

main_bp = Blueprint("main", __name__)

SPOTIFY_BASE = "https://api.spotify.com/v1"


def get_auth_header():
    return {"Authorization": f"Bearer {session.get('access_token')}"}


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


@main_bp.route("/playlists")
def playlists():
    if not session.get("user"):
        return redirect(url_for("auth.spotify_login"))

    with httpx.Client() as client:
        # 내 플레이리스트 목록
        res = client.get(
            f"{SPOTIFY_BASE}/me/playlists",
            headers=get_auth_header(),
            params={"limit": 20}
        )
        res.raise_for_status()
        playlists = res.json().get("items", [])

    return render_template("playlist.html", playlists=playlists)


@main_bp.route("/playlists/<playlist_id>")
def playlist_detail(playlist_id):
    if not session.get("user"):
        return redirect(url_for("auth.spotify_login"))

    with httpx.Client() as client:
        # 플레이리스트 정보
        pl_res = client.get(
            f"{SPOTIFY_BASE}/playlists/{playlist_id}",
            headers=get_auth_header(),
        )
        pl_res.raise_for_status()
        playlist = pl_res.json()

        # 트랙 목록
        tr_res = client.get(
            f"{SPOTIFY_BASE}/playlists/{playlist_id}/tracks",
            headers=get_auth_header(),
            params={"limit": 50}
        )
        tr_res.raise_for_status()
        tracks = tr_res.json().get("items", [])

    return render_template("playlist.html", playlist=playlist, tracks=tracks)