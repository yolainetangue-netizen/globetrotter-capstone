# -*- coding: utf-8 -*-
"""GlobeTrotter Phase 2 - User Service.
Owns users/authentication/profile data. Discussion and private messaging are
intentionally not part of this service.
"""
import json
import os
import time
from datetime import timedelta

import requests
from flask import Flask, jsonify, request
from flask_jwt_extended import JWTManager, create_access_token, get_jwt_identity, jwt_required
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token

app = Flask(__name__)
app.config["JWT_SECRET_KEY"] = os.environ.get("JWT_SECRET_KEY", "globetrotter-phase2-secret")
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(hours=6)
jwt = JWTManager(app)

DATA_FILE = os.path.join(os.path.dirname(__file__), "data.json")
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_SECRET_KEY = os.environ.get("SUPABASE_SECRET_KEY", "")
SUPABASE_BUCKET = os.environ.get("SUPABASE_BUCKET", "Globetrotter-data")
SUPABASE_STORAGE_ENABLED = bool(SUPABASE_URL and SUPABASE_SECRET_KEY)


def load_data():
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def next_id(items):
    return max((item.get("id", 0) for item in items), default=0) + 1


def safe_user(user):
    return {
        "id": user["id"],
        "username": user["username"],
        "preferences": user.get("preferences", []),
        "role": user.get("role", "user"),
        "auth_provider": user.get("auth_provider", "password"),
        "email": user.get("email"),
        "avatar_url": user.get("avatar_url"),
    }


def supabase_upload_avatar(user_id, content, content_type):
    if not SUPABASE_STORAGE_ENABLED:
        return None
    allowed = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
    ext = allowed.get(content_type)
    if not ext:
        return None
    object_path = f"avatars/user_{user_id}.{ext}"
    try:
        resp = requests.post(
            f"{SUPABASE_URL}/storage/v1/object/{SUPABASE_BUCKET}/{object_path}",
            headers={
                "apikey": SUPABASE_SECRET_KEY,
                "Authorization": f"Bearer {SUPABASE_SECRET_KEY}",
                "Content-Type": content_type,
                "x-upsert": "true",
            },
            data=content,
            timeout=15,
        )
        if resp.status_code in (200, 201):
            return f"{SUPABASE_URL}/storage/v1/object/public/{SUPABASE_BUCKET}/{object_path}?t={int(time.time())}"
    except requests.RequestException:
        pass
    return None


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"service": "user-service", "status": "ok"}), 200


@app.route("/register", methods=["POST"])
def register():
    body = request.get_json(force=True) or {}
    username = (body.get("username") or "").strip()
    password = (body.get("password") or "").strip()
    preferences = body.get("preferences", [])
    if not username or not password:
        return jsonify({"error": "username and password are required"}), 400
    data = load_data()
    if any(u["username"] == username for u in data["users"]):
        return jsonify({"error": "username already exists"}), 409
    new_id = next_id(data["users"])
    user = {"id": new_id, "username": username, "password": password,
            "preferences": preferences, "role": "user", "avatar_url": None}
    data["users"].append(user)
    save_data(data)
    return jsonify({"message": "user registered", "user": {"id": new_id, "username": username}}), 201


@app.route("/login", methods=["POST"])
def login():
    body = request.get_json(force=True) or {}
    username = (body.get("username") or "").strip()
    password = (body.get("password") or "").strip()
    data = load_data()
    user = next((u for u in data["users"] if u["username"] == username), None)
    if not user or user.get("password") != password:
        return jsonify({"error": "invalid username or password"}), 401
    access_token = create_access_token(identity=str(user["id"]))
    return jsonify({"access_token": access_token, "user": {"id": user["id"], "username": user["username"]}}), 200


@app.route("/auth/google", methods=["POST"])
def auth_google():
    if not GOOGLE_CLIENT_ID:
        return jsonify({"error": "Google sign-in is not configured on the server"}), 503
    body = request.get_json(silent=True) or {}
    credential = (body.get("credential") or "").strip()
    if not credential:
        return jsonify({"error": "missing Google credential"}), 400
    try:
        payload = google_id_token.verify_oauth2_token(
            credential, google_requests.Request(), GOOGLE_CLIENT_ID
        )
    except ValueError:
        return jsonify({"error": "invalid Google credential"}), 401
    google_sub = payload.get("sub")
    email = payload.get("email", "")
    name = payload.get("name") or (email.split("@")[0] if email else f"user{google_sub}")
    if not google_sub:
        return jsonify({"error": "invalid Google credential"}), 401
    data = load_data()
    user = next((u for u in data["users"] if u.get("google_sub") == google_sub), None)
    if not user:
        username = name
        suffix = 1
        existing = {u["username"] for u in data["users"]}
        while username in existing:
            suffix += 1
            username = f"{name}{suffix}"
        user = {"id": next_id(data["users"]), "username": username, "password": None,
                "preferences": [], "role": "user", "auth_provider": "google",
                "google_sub": google_sub, "email": email, "avatar_url": None}
        data["users"].append(user)
        save_data(data)
    token = create_access_token(identity=str(user["id"]))
    return jsonify({"access_token": token, "user": {"id": user["id"], "username": user["username"]}}), 200


@app.route("/users/search", methods=["GET"])
def search_users():
    q = (request.args.get("q") or "").strip().lower()
    if not q:
        return jsonify([]), 200
    data = load_data()
    current_id = None
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        try:
            current_id = int(get_jwt_identity())
        except Exception:
            current_id = None
    matches = [safe_user(u) for u in data["users"] if q in u.get("username", "").lower() and u.get("id") != current_id]
    return jsonify(matches[:20]), 200


@app.route("/users/<int:user_id>", methods=["GET"])
def get_user(user_id):
    data = load_data()
    user = next((u for u in data["users"] if u["id"] == user_id), None)
    if not user:
        return jsonify({"error": "user not found"}), 404
    return jsonify(safe_user(user)), 200


@app.route("/me", methods=["GET"])
@jwt_required()
def me():
    user_id = int(get_jwt_identity())
    data = load_data()
    user = next((u for u in data["users"] if u["id"] == user_id), None)
    if not user:
        return jsonify({"error": "user not found"}), 404
    return jsonify(safe_user(user)), 200


@app.route("/me/avatar", methods=["POST"])
@jwt_required()
def upload_avatar():
    if not SUPABASE_STORAGE_ENABLED:
        return jsonify({"error": "l'upload de photo n'est pas disponible pour le moment"}), 503
    if "avatar" not in request.files:
        return jsonify({"error": "aucun fichier recu"}), 400
    file = request.files["avatar"]
    if not file.filename:
        return jsonify({"error": "aucun fichier recu"}), 400
    if file.mimetype not in {"image/jpeg", "image/png", "image/webp"}:
        return jsonify({"error": "format d'image non supporte (JPEG, PNG ou WEBP uniquement)"}), 400
    content = file.read()
    if len(content) > 3 * 1024 * 1024:
        return jsonify({"error": "image trop volumineuse (3 Mo maximum)"}), 400
    user_id = int(get_jwt_identity())
    url = supabase_upload_avatar(user_id, content, file.mimetype)
    if not url:
        return jsonify({"error": "echec de l'envoi de la photo, reessayez"}), 502
    data = load_data()
    user = next((u for u in data["users"] if u["id"] == user_id), None)
    if not user:
        return jsonify({"error": "user not found"}), 404
    user["avatar_url"] = url
    save_data(data)
    return jsonify({"avatar_url": url}), 200


@app.route("/admin/stats", methods=["GET"])
@jwt_required()
def admin_stats():
    user_id = int(get_jwt_identity())
    data = load_data()
    user = next((u for u in data["users"] if u["id"] == user_id), None)
    if not user or user.get("role") != "admin":
        return jsonify({"error": "admin access required"}), 403
    return jsonify({"users_count": len(data["users"])}), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5001)), debug=True)
