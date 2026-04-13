"""
청취 기록 수집 스크립트
실행: python collector.py
Windows Task Scheduler 또는 cron으로 30분~1시간마다 실행 권장
(recently-played는 최근 50곡만 제공하므로 너무 간격이 길면 누락 발생)
"""

import os
import httpx
from dotenv import load_dotenv
from firebase_admin import credentials, firestore
import firebase_admin

load_dotenv()

SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_RECENT_URL = "https://api.spotify.com/v1/me/player/recently-played"
CLIENT_ID     = os.getenv("SPOTIFY_CLIENT_ID")
CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
CRED_PATH     = os.getenv("FIREBASE_CREDENTIAL", "serviceAccountKey.json")


def init_firebase():
    if not firebase_admin._apps:
        cred = credentials.Certificate(CRED_PATH)
        firebase_admin.initialize_app(cred)
    return firestore.client()


def refresh_access_token(refresh_token: str) -> str | None:
    try:
        res = httpx.post(
            SPOTIFY_TOKEN_URL,
            data={"grant_type": "refresh_token", "refresh_token": refresh_token},
            auth=(CLIENT_ID, CLIENT_SECRET),
        )
        if res.status_code == 200:
            return res.json()["access_token"]
    except Exception as e:
        print(f"[ERROR] 토큰 갱신 실패: {e}")
    return None


def fetch_recent(access_token: str) -> list | None:
    try:
        res = httpx.get(
            SPOTIFY_RECENT_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            params={"limit": 50},
        )
        if res.status_code == 401:
            return None
        if res.status_code == 403:
            print(f"[ERROR] 403 응답 본문: {res.text}")  # 추가
            res.raise_for_status()
        res.raise_for_status()
        return res.json().get("items", [])
    except Exception as e:
        print(f"[ERROR] 청취 기록 요청 실패: {e}")
        return None


def save_history(db, user_id: str, items: list) -> int:
    col = db.collection("users").document(user_id).collection("history")
    batch = db.batch()
    count = 0
    for item in items:
        track = item.get("track")
        if not track:
            continue
        doc_id = item["played_at"].replace(":", "-").replace(".", "-")
        ref = col.document(doc_id)
        batch.set(ref, {
            "played_at":   item["played_at"],
            "track_id":    track["id"],
            "track_name":  track["name"],
            "artists":     [a["name"] for a in track["artists"]],
            "album":       track["album"]["name"],
            "duration_ms": track.get("duration_ms"),
            "track_url":   track["external_urls"].get("spotify"),
        })
        count += 1
        if count % 400 == 0:
            batch.commit()
            batch = db.batch()
    batch.commit()
    return count


def run():
    db = init_firebase()
    users_ref = db.collection("users").stream()

    for user_doc in users_ref:
        user = user_doc.to_dict()
        user_id = user["id"]
        print(f"[{user_id}] 수집 시작")

        access_token  = user.get("access_token")
        refresh_token = user.get("refresh_token")

        items = fetch_recent(access_token)

        # 토큰 만료 시 갱신 후 재시도
        if items is None:
            print(f"[{user_id}] 토큰 만료 → 갱신 시도")
            access_token = refresh_access_token(refresh_token)
            if not access_token:
                print(f"[{user_id}] 갱신 실패, 스킵")
                continue
            # 갱신된 토큰 Firestore에 업데이트
            db.collection("users").document(user_id).update({
                "access_token": access_token
            })
            items = fetch_recent(access_token)

        if not items:
            print(f"[{user_id}] 기록 없음")
            continue

        saved = save_history(db, user_id, items)
        print(f"[{user_id}] {saved}건 저장 완료")


if __name__ == "__main__":
    run()