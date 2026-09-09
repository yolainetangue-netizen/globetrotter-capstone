# -*- coding: utf-8 -*-
"""
GlobeTrotter - Phase 2 - Recommendation Service
Proprietaire des donnees "destinations". Expose la recherche de
destinations et genere des recommandations personnalisees en
appelant le User Service (communication SYNCHRONE REST) pour
recuperer les preferences de l'utilisateur connecte.
"""
import json
import os
from datetime import timedelta

import requests
from flask import Flask, jsonify, request
from flask_jwt_extended import JWTManager, get_jwt_identity, jwt_required

app = Flask(__name__)
app.config["JWT_SECRET_KEY"] = os.environ.get("JWT_SECRET_KEY", "globetrotter-phase2-secret")
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(hours=6)
jwt = JWTManager(app)

DATA_FILE = os.path.join(os.path.dirname(__file__), "data.json")
USER_SERVICE_URL = os.environ.get("USER_SERVICE_URL", "http://user-service:5001")


def load_data():
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"service": "recommendation-service", "status": "ok"}), 200


@app.route("/destinations", methods=["GET"])
def get_destinations():
    """Recherche de destinations, filtrable par nom, tag ou categorie."""
    data = load_data()
    destinations = data["destinations"]

    query = request.args.get("q", "").strip().lower()
    tag = request.args.get("tag", "").strip().lower()
    category = request.args.get("category", "").strip().lower()

    if query:
        destinations = [d for d in destinations if query in d["name"].lower()]
    if tag:
        destinations = [d for d in destinations if tag in [t.lower() for t in d.get("tags", [])]]
    if category:
        destinations = [d for d in destinations if d.get("category", "").lower() == category]

    return jsonify(destinations), 200


@app.route("/destinations/<int:destination_id>", methods=["GET"])
def get_destination(destination_id):
    data = load_data()
    destination = next((d for d in data["destinations"] if d["id"] == destination_id), None)
    if not destination:
        return jsonify({"error": "destination not found"}), 404
    # Keep the Phase 1 analytics behavior: every detail view increments the
    # destination view counter. This is owned by the destination service.
    destination["views"] = int(destination.get("views", 0)) + 1
    save_data(data)
    return jsonify(destination), 200



@app.route("/events", methods=["GET"])
def get_events():
    data = load_data()
    events = data.get("events", [])
    if request.args.get("upcoming", "").lower() == "true":
        from datetime import datetime
        today = datetime.utcnow().strftime("%Y-%m-%d")
        events = [e for e in events if (e.get("end_date") or e.get("date")) >= today]
    return jsonify(sorted(events, key=lambda e: e.get("date",""))), 200

@app.route("/services", methods=["GET"])
def get_services():
    data = load_data()
    services = data.get("services", [])
    kind = request.args.get("type", "").strip().lower()
    if kind:
        services = [s for s in services if s.get("type","").lower() == kind]
    from math import radians, sin, cos, sqrt, atan2
    lat0,lng0 = 2.9464,9.9074
    def distance(s):
        lat,lng=s.get("lat",lat0),s.get("lng",lng0)
        dlat=radians(lat-lat0); dlng=radians(lng-lng0)
        a=sin(dlat/2)**2+cos(radians(lat0))*cos(radians(lat))*sin(dlng/2)**2
        return 6371*2*atan2(sqrt(a),sqrt(1-a))
    enriched=[]
    for item in services:
        x=dict(item); x["distance_km"]=round(distance(x),2); enriched.append(x)
    enriched.sort(key=lambda x:x["distance_km"])
    return jsonify(enriched), 200

@app.route("/destinations/<int:destination_id>/reviews", methods=["GET","POST"])
def reviews(destination_id):
    data=load_data()
    if not any(d["id"]==destination_id for d in data.get("destinations",[])):
        return jsonify({"error":"destination not found"}),404
    if request.method=="GET":
        return jsonify([r for r in data.get("reviews",[]) if r.get("destination_id")==destination_id]),200
    body=request.get_json(silent=True) or {}
    try: rating=int(body.get("rating"))
    except (TypeError,ValueError): rating=0
    comment=(body.get("comment") or "").strip()
    author=(body.get("author") or "Visiteur").strip()[:60]
    if rating<1 or rating>5 or not comment:
        return jsonify({"error":"rating (1-5) and comment are required"}),400
    reviews=data.setdefault("reviews",[])
    new_id=max((r.get("id",0) for r in reviews),default=0)+1
    review={"id":new_id,"destination_id":destination_id,"author":author,
            "rating":rating,"comment":comment[:1000],
            "date":__import__("datetime").datetime.utcnow().isoformat()+"Z"}
    reviews.append(review); save_data(data)
    return jsonify({"message":"review added","review":review}),201

@app.route("/recommendations", methods=["GET"])
@jwt_required()
def get_recommendations():
    """Recommandations personnalisees : appelle le User Service (REST
    synchrone) pour recuperer les preferences, puis filtre les
    destinations en consequence."""
    user_id = int(get_jwt_identity())

    try:
        resp = requests.get(f"{USER_SERVICE_URL}/users/{user_id}", timeout=5)
        resp.raise_for_status()
        preferences = resp.json().get("preferences", [])
    except requests.RequestException:
        return jsonify({"error": "user-service unavailable"}), 502

    data = load_data()
    destinations = data["destinations"]

    if preferences:
        prefs_lower = [p.lower() for p in preferences]
        recommended = [
            d for d in destinations
            if any(tag.lower() in prefs_lower for tag in d.get("tags", []))
        ]
        if not recommended:
            recommended = destinations[:10]
    else:
        recommended = destinations[:10]

    return jsonify(recommended[:10]), 200


@app.route("/admin/summary", methods=["GET"])
@jwt_required()
def admin_summary():
    """Admin-only read model for destination/event/review statistics."""
    data = load_data()
    destinations = data.get("destinations", [])
    reviews = data.get("reviews", [])
    ratings = [r.get("rating") for r in reviews if isinstance(r.get("rating"), (int, float))]
    average_rating = round(sum(ratings) / len(ratings), 2) if ratings else None
    most_viewed = sorted(destinations, key=lambda d: d.get("views", 0), reverse=True)[:10]
    most_viewed = [{"id": d["id"], "name": d["name"], "category": d.get("category"), "views": d.get("views", 0)} for d in most_viewed if d.get("views", 0) > 0]
    dest_by_id = {d["id"]: d["name"] for d in destinations}
    recent_reviews = sorted(reviews, key=lambda r: r.get("date", ""), reverse=True)[:10]
    recent_reviews = [{**r, "destination_name": dest_by_id.get(r.get("destination_id"), "?")} for r in recent_reviews]
    by_category = {}
    for d in destinations:
        cat = d.get("category", "Autres")
        by_category[cat] = by_category.get(cat, 0) + 1
    return jsonify({"destinations": len(destinations), "events": len(data.get("events", [])),
                    "services": len(data.get("services", [])), "reviews": len(reviews), "total_views": sum(d.get("views", 0) for d in destinations),
                    "average_rating": average_rating, "most_viewed_destinations": most_viewed,
                    "recent_reviews": recent_reviews, "destinations_by_category": by_category}), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5003))
    app.run(host="0.0.0.0", port=port, debug=True)
