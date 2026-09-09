# -*- coding: utf-8 -*-
"""GlobeTrotter Phase 2 - Web Frontend.
This service only renders the Phase 1 interface and proxies API calls to the
Phase 2 API Gateway. Business/data logic stays in the microservices.
The discussion and private-messaging areas are intentionally excluded.
"""
import os
import requests
from flask import Flask, Response, jsonify, render_template, request, redirect, url_for

app = Flask(__name__, template_folder="templates", static_folder="static")
GATEWAY_URL = os.environ.get("API_GATEWAY_URL", "http://api-gateway:5000").rstrip("/")

PAGE_ROUTES = {
    "/": "index.html",
    "/register-page": "register.html",
    "/login-page": "login.html",
    "/destinations-page": "destinations.html",
    "/itineraries-page": "itineraries.html",
    "/reservations-page": "reservations.html",
    "/map-page": "map.html",
    "/kribi-page": "kribi.html",
    "/events-page": "events.html",
    "/services-page": "services.html",
    "/favorites-page": "favorites.html",
    "/profile-page": "profile.html",
    "/admin-page": "admin.html",
    "/chat-page": "chat.html",
}

PROTECTED_PAGES = {"/itineraries-page", "/reservations-page", "/profile-page", "/admin-page", "/chat-page"}

def page_context(path, **kwargs):
    ctx = dict(kwargs)
    ctx["google_client_id"] = os.environ.get("GOOGLE_CLIENT_ID", "")
    return ctx

@app.route("/")
def index():
    return render_template("index.html", **page_context("/"))

@app.route("/register-page")
def register_page():
    return render_template("register.html", **page_context("/register-page"))

@app.route("/login-page")
def login_page():
    return render_template("login.html", **page_context("/login-page"))

@app.route("/destinations-page")
def destinations_page():
    return render_template("destinations.html", **page_context("/destinations-page"))

@app.route("/itineraries-page")
def itineraries_page():
    return render_template("itineraries.html", **page_context("/itineraries-page"))

@app.route("/reservations-page")
def reservations_page():
    return render_template("reservations.html", **page_context("/reservations-page"))

@app.route("/map-page")
def map_page():
    return render_template("map.html", **page_context("/map-page"))

@app.route("/kribi-page")
def kribi_page():
    return render_template("kribi.html", **page_context("/kribi-page"))

@app.route("/events-page")
def events_page():
    return render_template("events.html", **page_context("/events-page"))

@app.route("/services-page")
def services_page():
    return render_template("services.html", **page_context("/services-page"))

@app.route("/favorites-page")
def favorites_page():
    return render_template("favorites.html", **page_context("/favorites-page"))

@app.route("/profile-page")
def profile_page():
    return render_template("profile.html", **page_context("/profile-page"))

@app.route("/admin-page")
def admin_page():
    return render_template("admin.html", **page_context("/admin-page"))

@app.route("/chat-page")
def chat_page():
    socket_url = os.environ.get("CHAT_SOCKET_URL", "http://localhost:5004").rstrip("/")
    return render_template("chat.html", chat_socket_url=socket_url, **page_context("/chat-page"))

@app.route("/category/<path:category_name>")
def category_page(category_name):
    return render_template("category.html", category_name=category_name, **page_context("/category"))

@app.route("/destination/<int:destination_id>")
def destination_detail(destination_id):
    return render_template("destination_detail.html", destination_id=destination_id, **page_context("/destination"))

@app.route("/itinerary/shared/<token>")
def shared_itinerary(token):
    return render_template("itinerary_public.html", token=token, **page_context("/itinerary/shared"))

PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "")
_photo_cache = {}
_weather_cache = {}
WEATHER_CACHE_TTL = 1800

@app.route("/api/photo", methods=["GET"])
def photo():
    q = (request.args.get("q") or "").strip()
    fallback = (request.args.get("fallback") or "").strip()
    if not q:
        return jsonify({"url": None}), 200
    key = q + "|" + fallback
    if key in _photo_cache:
        return jsonify({"url": _photo_cache[key]}), 200
    if not PEXELS_API_KEY:
        return jsonify({"url": None}), 200
    try:
        r = requests.get("https://api.pexels.com/v1/search",
                         headers={"Authorization": PEXELS_API_KEY},
                         params={"query": q, "per_page": 1}, timeout=8)
        if r.ok:
            photos = r.json().get("photos", [])
            if photos:
                url = photos[0].get("src", {}).get("large2x") or photos[0].get("src", {}).get("large")
                _photo_cache[key] = url
                return jsonify({"url": url}), 200
        if fallback and fallback != q:
            r = requests.get("https://api.pexels.com/v1/search",
                             headers={"Authorization": PEXELS_API_KEY},
                             params={"query": fallback, "per_page": 1}, timeout=8)
            if r.ok:
                photos = r.json().get("photos", [])
                if photos:
                    url = photos[0].get("src", {}).get("large2x") or photos[0].get("src", {}).get("large")
                    _photo_cache[key] = url
                    return jsonify({"url": url}), 200
    except requests.RequestException:
        pass
    _photo_cache[key] = None
    return jsonify({"url": None}), 200

@app.route("/api/weather", methods=["GET"])
def weather():
    lat = request.args.get("lat", type=float)
    lng = request.args.get("lng", type=float)
    if lat is None or lng is None:
        return jsonify({"error": "lat and lng are required"}), 400
    key = f"{lat:.4f},{lng:.4f}"
    import time
    cached = _weather_cache.get(key)
    if cached and time.time() - cached["ts"] < WEATHER_CACHE_TTL:
        return jsonify(cached["data"]), 200
    try:
        r = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={"latitude":lat,"longitude":lng,
                    "current":"temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m",
                    "timezone":"auto"},
            timeout=8)
        r.raise_for_status()
        data = r.json()
        _weather_cache[key] = {"data": data, "ts": time.time()}
        return jsonify(data), 200
    except requests.RequestException as exc:
        return jsonify({"error": str(exc)}), 502

# All API routes used by the Phase 1 interface are transparently forwarded
# to the Phase 2 Gateway. The browser never needs to know service ports.
@app.route("/<path:path>", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
def api_proxy(path):
    full_path = "/" + path
    # Avoid swallowing real page paths.
    if full_path in PAGE_ROUTES or full_path.startswith("/category/") or full_path.startswith("/destination/") or full_path.startswith("/itinerary/shared/"):
        return ("Not found", 404)

    target = GATEWAY_URL + full_path
    try:
        resp = requests.request(
            request.method, target,
            headers={k: v for k, v in request.headers if k.lower() not in ("host","content-length")},
            params=request.args,
            data=request.get_data(),
            timeout=30,
            allow_redirects=False,
        )
    except requests.RequestException as exc:
        return {"error": "api gateway unavailable", "detail": str(exc)}, 502

    excluded = {"content-encoding", "transfer-encoding", "connection"}
    headers = [(k, v) for k, v in resp.headers.items() if k.lower() not in excluded]
    return Response(resp.content, resp.status_code, headers)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT","8080")), debug=True)
