import json
import logging
import os
from functools import wraps

import jwt
import requests
from flask import Flask, jsonify, request
from flask_cors import CORS
from flask_socketio import SocketIO, join_room, emit, disconnect

logging.basicConfig(level=logging.INFO, format="%(asctime)s [chat-service] %(levelname)s %(message)s")
logger = logging.getLogger("chat-service")

app = Flask(__name__)
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

DATA_FILE = os.path.join(os.path.dirname(__file__), "data.json")
JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "globetrotter-phase2-secret")
USER_SERVICE_URL = os.environ.get("USER_SERVICE_URL", "http://user-service:5001").rstrip("/")
INTERNAL_KEY = os.environ.get("INTERNAL_KEY", "")
MAX_COMMUNITY_HISTORY = 200

_sid_to_user = {}
_online_users = {}


def load_data():
    if not os.path.exists(DATA_FILE):
        data = {"conversations": [], "messages": [], "community_messages": []}
        save_data(data)
        return data
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_data(data):
    tmp = DATA_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, DATA_FILE)


def next_id(items):
    return max((int(x.get("id", 0)) for x in items), default=0) + 1


def decode_token(token):
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=["HS256"], options={"verify_aud": False})
        user_id = int(payload.get("sub"))
        return user_id
    except Exception:
        return None


def auth_user():
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None
    return decode_token(header[7:].strip())


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user_id = auth_user()
        if user_id is None:
            return jsonify({"error": "authentication required"}), 401
        request.user_id = user_id
        return fn(*args, **kwargs)
    return wrapper


def user_by_id(user_id):
    try:
        r = requests.get(f"{USER_SERVICE_URL}/users/{int(user_id)}", timeout=4)
        return r.json() if r.ok else None
    except requests.RequestException:
        return None


def conversation_between(a, b):
    pair = {int(a), int(b)}
    return next((c for c in load_data()["conversations"] if {int(c["user_a"]), int(c["user_b"])} == pair), None)


def conversation_by_id(cid):
    return next((c for c in load_data()["conversations"] if int(c["id"]) == int(cid)), None)


def messages_for(cid):
    return sorted([m for m in load_data()["messages"] if int(m["conversation_id"]) == int(cid)], key=lambda m: m["id"])


def create_conversation(a, b):
    existing = conversation_between(a, b)
    if existing:
        return existing
    data = load_data()
    c = {"id": next_id(data["conversations"]), "user_a": int(a), "user_b": int(b)}
    data["conversations"].append(c)
    save_data(data)
    return c


def add_message(cid, sender_id, text):
    data = load_data()
    msg = {"id": next_id(data["messages"]), "conversation_id": int(cid), "sender_id": int(sender_id), "text": text}
    data["messages"].append(msg)
    save_data(data)
    return msg


def add_community_message(sender_id, sender_name, text):
    data = load_data()
    msg = {"id": next_id(data["community_messages"]), "sender_id": int(sender_id), "sender_name": sender_name, "text": text}
    data["community_messages"].append(msg)
    data["community_messages"] = data["community_messages"][-MAX_COMMUNITY_HISTORY:]
    save_data(data)
    return msg


@app.route("/health")
def health():
    return jsonify({"service": "chat-service", "status": "ok", "online": len(_online_users)})


@app.route("/conversations", methods=["GET"])
@login_required
def list_conversations():
    data = load_data()
    convos = [c for c in data["conversations"] if request.user_id in (int(c["user_a"]), int(c["user_b"]))]
    result = []
    for c in convos:
        peer_id = int(c["user_b"] if int(c["user_a"]) == request.user_id else c["user_a"])
        peer = user_by_id(peer_id)
        msgs = messages_for(c["id"])
        result.append({
            "id": c["id"], "peer_id": peer_id,
            "peer_username": (peer or {}).get("username", "Utilisateur"),
            "last_message": msgs[-1]["text"] if msgs else None,
            "message_count": len(msgs), "peer_online": peer_id in _online_users,
        })
    return jsonify(result)


@app.route("/conversations", methods=["POST"])
@login_required
def start_conversation():
    body = request.get_json(silent=True) or {}
    peer_id = body.get("peer_id")
    try:
        peer_id = int(peer_id)
    except (TypeError, ValueError):
        return jsonify({"error": "peer_id is required"}), 400
    if peer_id == request.user_id or not user_by_id(peer_id):
        return jsonify({"error": "peer_id must reference a different, known user"}), 400
    return jsonify(create_conversation(request.user_id, peer_id)), 201


@app.route("/conversations/<int:conversation_id>/messages")
@login_required
def list_messages(conversation_id):
    c = conversation_by_id(conversation_id)
    if not c or request.user_id not in (int(c["user_a"]), int(c["user_b"])):
        return jsonify({"error": "conversation not found"}), 404
    return jsonify(messages_for(conversation_id))


@app.route("/community/messages")
def community_messages():
    return jsonify(load_data()["community_messages"][-100:])


@app.route("/internal/stats")
def internal_stats():
    if INTERNAL_KEY and request.headers.get("X-Internal-Key") != INTERNAL_KEY:
        return jsonify({"error": "forbidden"}), 403
    d = load_data()
    return jsonify({"total_conversations": len(d["conversations"]), "total_messages": len(d["messages"]) + len(d["community_messages"]), "online_now": len(_online_users)})


def socket_user():
    token = request.args.get("token", "")
    uid = decode_token(token)
    if uid is None:
        return None
    user = user_by_id(uid) or {}
    return {"id": uid, "username": user.get("username", f"User {uid}")}


@socketio.on("connect")
def on_connect():
    user = socket_user()
    if not user:
        disconnect()
        return False
    _sid_to_user[request.sid] = user
    _online_users.setdefault(user["id"], set()).add(request.sid)
    join_room("community")
    join_room(f"user-{user['id']}")
    emit("presence", {"online_count": len(_online_users)}, room="community")


@socketio.on("disconnect")
def on_disconnect():
    user = _sid_to_user.pop(request.sid, None)
    if user:
        sids = _online_users.get(user["id"], set())
        sids.discard(request.sid)
        if not sids:
            _online_users.pop(user["id"], None)
        emit("presence", {"online_count": len(_online_users)}, room="community")


@socketio.on("join_conversation")
def on_join_conversation(data):
    user = _sid_to_user.get(request.sid)
    cid = (data or {}).get("conversation_id")
    if not user:
        return
    c = conversation_by_id(cid)
    if not c or user["id"] not in (int(c["user_a"]), int(c["user_b"])):
        emit("error", {"error": "conversation not found"})
        return
    join_room(f"conv-{c['id']}")


@socketio.on("send_message")
def on_send_message(data):
    user = _sid_to_user.get(request.sid)
    if not user:
        return
    data = data or {}
    c = conversation_by_id(data.get("conversation_id"))
    if not c or user["id"] not in (int(c["user_a"]), int(c["user_b"])):
        emit("error", {"error": "conversation not found"})
        return
    text = str(data.get("text") or "").strip()
    if not text or len(text) > 2000:
        emit("error", {"error": "text is required (max 2000 characters)"})
        return
    msg = add_message(c["id"], user["id"], text)
    emit("new_message", msg, room=f"conv-{c['id']}")
    peer_id = int(c["user_b"] if int(c["user_a"]) == user["id"] else c["user_a"])
    emit("conversation_updated", {"conversation_id": c["id"]}, room=f"user-{peer_id}")


@socketio.on("send_community")
def on_send_community(data):
    user = _sid_to_user.get(request.sid)
    if not user:
        return
    text = str((data or {}).get("text") or "").strip()
    if not text or len(text) > 1000:
        emit("error", {"error": "text is required (max 1000 characters)"})
        return
    msg = add_community_message(user["id"], user["username"], text)
    emit("community_message", msg, room="community")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5004"))
    socketio.run(app, host="0.0.0.0", port=port, debug=False, allow_unsafe_werkzeug=True)
