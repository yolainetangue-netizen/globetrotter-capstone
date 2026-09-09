# -*- coding: utf-8 -*-
"""GlobeTrotter Phase 2 - API Gateway.
Single backend entry point for the frontend. No business data is stored here.
"""
import os

import requests
from flask import Flask, Response, jsonify, request

app = Flask(__name__)

USER_SERVICE_URL = os.environ.get("USER_SERVICE_URL", "http://user-service:5001").rstrip("/")
ITINERARY_SERVICE_URL = os.environ.get("ITINERARY_SERVICE_URL", "http://itinerary-service:5002").rstrip("/")
RECOMMENDATION_SERVICE_URL = os.environ.get("RECOMMENDATION_SERVICE_URL", "http://recommendation-service:5003").rstrip("/")
CHAT_SERVICE_URL = os.environ.get("CHAT_SERVICE_URL", "http://chat-service:5004").rstrip("/")

ROUTES = {
    "/register": USER_SERVICE_URL,
    "/login": USER_SERVICE_URL,
    "/auth/google": USER_SERVICE_URL,
    "/me/avatar": USER_SERVICE_URL,
    "/me": USER_SERVICE_URL,
    "/users": USER_SERVICE_URL,
    "/conversations": CHAT_SERVICE_URL,
    "/community": CHAT_SERVICE_URL,
    "/admin/stats": USER_SERVICE_URL,
    "/admin": USER_SERVICE_URL,
    "/destinations": RECOMMENDATION_SERVICE_URL,
    "/events": RECOMMENDATION_SERVICE_URL,
    "/services": RECOMMENDATION_SERVICE_URL,
    "/recommendations": RECOMMENDATION_SERVICE_URL,
    "/itineraries": ITINERARY_SERVICE_URL,
    "/reservations": ITINERARY_SERVICE_URL,
}


def resolve_target(path):
    for prefix, base_url in sorted(ROUTES.items(), key=lambda item: len(item[0]), reverse=True):
        if path == prefix or path.startswith(prefix + "/"):
            return base_url
    return None


@app.route("/health", methods=["GET"])
def health():
    checks = {}
    for name, base in {
        "user-service": USER_SERVICE_URL,
        "recommendation-service": RECOMMENDATION_SERVICE_URL,
        "itinerary-service": ITINERARY_SERVICE_URL,
    }.items():
        try:
            r = requests.get(f"{base}/health", timeout=2)
            checks[name] = r.ok
        except requests.RequestException:
            checks[name] = False
    status = "ok" if all(checks.values()) else "degraded"
    return jsonify({"service": "api-gateway", "status": status, "services": checks}), 200


@app.route("/admin/stats", methods=["GET"])
def admin_stats():
    """Aggregate the admin dashboard without centralizing business data."""
    auth = request.headers.get("Authorization")
    headers = {"Authorization": auth} if auth else {}
    try:
        u = requests.get(f"{USER_SERVICE_URL}/admin/stats", headers=headers, timeout=5)
        if u.status_code in (401, 403):
            return Response(u.content, u.status_code, content_type="application/json")
        u.raise_for_status()
        r = requests.get(f"{RECOMMENDATION_SERVICE_URL}/admin/summary", headers=headers, timeout=5)
        if r.status_code in (401, 403):
            return Response(r.content, r.status_code, content_type="application/json")
        r.raise_for_status()
        i = requests.get(f"{ITINERARY_SERVICE_URL}/admin/summary", headers=headers, timeout=5)
        if i.status_code in (401, 403):
            return Response(i.content, i.status_code, content_type="application/json")
        i.raise_for_status()
    except requests.RequestException as exc:
        return jsonify({"error": "one or more backend services are unavailable", "detail": str(exc)}), 502

    users = u.json().get("users_count", 0)
    rec = r.json()
    iti = i.json()
    return jsonify({
        "totals": {
            "users": users,
            "destinations": rec.get("destinations", 0),
            "reviews": rec.get("reviews", 0),
            "itineraries": iti.get("itineraries", 0),
            "events": rec.get("events", 0),
            "services": rec.get("services", 0),
            "total_views": rec.get("total_views", 0),
            "reservations": iti.get("reservations", 0),
        },
        "average_rating": rec.get("average_rating"),
        "most_viewed_destinations": rec.get("most_viewed_destinations", []),
        "recent_reviews": rec.get("recent_reviews", []),
        "destinations_by_category": rec.get("destinations_by_category", {}),
        "recent_reservations": iti.get("recent_reservations", []),
    }), 200


@app.route("/<path:path>", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
def proxy(path):
    full_path = "/" + path
    if full_path == "/admin/stats":
        return admin_stats()
    target_base = resolve_target(full_path)
    if not target_base:
        return jsonify({"error": f"no service registered for {full_path}"}), 404
    target_url = f"{target_base}{full_path}"
    try:
        resp = requests.request(
            method=request.method,
            url=target_url,
            headers={k: v for k, v in request.headers if k.lower() != "host"},
            params=request.args,
            data=request.get_data(),
            timeout=30,
        )
    except requests.RequestException as exc:
        return jsonify({"error": "upstream service unavailable", "detail": str(exc)}), 502
    excluded_headers = {"content-encoding", "transfer-encoding", "connection"}
    headers = [(k, v) for k, v in resp.raw.headers.items() if k.lower() not in excluded_headers]
    return Response(resp.content, resp.status_code, headers)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
