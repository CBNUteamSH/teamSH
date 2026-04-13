import os
import firebase_admin
from firebase_admin import credentials, firestore

_db = None

def get_db():
    global _db
    if _db is None:
        if not firebase_admin._apps:
            cred = credentials.Certificate(os.getenv("FIREBASE_CREDENTIAL", "serviceAccountKey.json"))
            firebase_admin.initialize_app(cred)
        _db = firestore.client()
    return _db


def save_user(user: dict, access_token: str, refresh_token: str):
    """로그인 시 유저 정보 + 토큰 저장/갱신"""
    db = get_db()
    db.collection("users").document(user["id"]).set({
        "id":            user["id"],
        "display_name":  user.get("display_name", ""),
        "email":         user.get("email", ""),
        "image":         user.get("image", ""),
        "access_token":  access_token,
        "refresh_token": refresh_token,
        "updated_at":    firestore.SERVER_TIMESTAMP,
    }, merge=True)


def save_history(user_id: str, items: list):
    """
    청취 기록 저장 — played_at을 doc ID로 사용해 중복 방지
    items: Spotify recently-played items 리스트
    """
    db = get_db()
    col = db.collection("users").document(user_id).collection("history")

    batch = db.batch()
    count = 0
    for item in items:
        track = item.get("track")
        if not track:
            continue
        doc_id = item["played_at"].replace(":", "-").replace(".", "-")  # doc ID에 특수문자 불가
        ref = col.document(doc_id)
        batch.set(ref, {
            "played_at":   item["played_at"],
            "track_id":    track["id"],
            "track_name":  track["name"],
            "artists":     [a["name"] for a in track["artists"]],
            "album":       track["album"]["name"],
            "duration_ms": track.get("duration_ms"),
            "track_url":   track["external_urls"].get("spotify"),
        }, merge=False)  # 이미 존재하면 덮어쓰지 않으려면 create만 해도 되지만 set이 안전
        count += 1
        if count % 400 == 0:  # Firestore 배치 한도 500
            batch.commit()
            batch = db.batch()

    batch.commit()
    return count