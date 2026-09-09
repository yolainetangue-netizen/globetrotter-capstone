# -*- coding: utf-8 -*-
"""
GlobeTrotter - Phase 2 - Itinerary Service
Proprietaire des donnees "itineraries". Cree et liste les
itineraires de l'utilisateur connecte.

Demontre les DEUX modes de communication inter-services demandes :
  - SYNCHRONE (REST) : verifie que la destination existe en appelant
    le Recommendation Service avant de creer l'itineraire.
  - ASYNCHRONE (file de messages RabbitMQ) : publie un evenement
    "itinerary.created" apres chaque creation, sans bloquer la
    reponse HTTP sur son traitement (ex: pourrait plus tard declencher
    un email de confirmation, un recalcul de recommandations, etc.)
"""
import io
import json
import os
import secrets
import time
from datetime import datetime, timedelta

import pika
import requests
from flask import Flask, jsonify, request, send_file
from flask_jwt_extended import JWTManager, get_jwt_identity, jwt_required

app = Flask(__name__)
app.config["JWT_SECRET_KEY"] = os.environ.get("JWT_SECRET_KEY", "globetrotter-phase2-secret")
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(hours=6)
jwt = JWTManager(app)

DATA_FILE = os.path.join(os.path.dirname(__file__), "data.json")
RECOMMENDATION_SERVICE_URL = os.environ.get("RECOMMENDATION_SERVICE_URL", "http://recommendation-service:5003")
RABBITMQ_HOST = os.environ.get("RABBITMQ_HOST", "rabbitmq")
QUEUE_NAME = "itinerary_events"


def load_data():
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def publish_event(event_type, payload, retries=3):
    """Publie un evenement sur RabbitMQ (communication ASYNCHRONE).
    N'echoue jamais la requete HTTP si la file est indisponible :
    on journalise simplement l'echec (pattern courant en systemes
    distribues : ne pas bloquer le chemin critique pour un evenement
    secondaire)."""
    message = json.dumps({"event": event_type, "data": payload})
    for attempt in range(retries):
        try:
            connection = pika.BlockingConnection(pika.ConnectionParameters(host=RABBITMQ_HOST))
            channel = connection.channel()
            channel.queue_declare(queue=QUEUE_NAME, durable=True)
            channel.basic_publish(exchange="", routing_key=QUEUE_NAME, body=message)
            connection.close()
            return True
        except Exception as exc:  # pragma: no cover - RabbitMQ peut etre indisponible
            print(f"[itinerary-service] echec publication evenement (tentative {attempt+1}): {exc}")
            time.sleep(1)
    return False


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"service": "itinerary-service", "status": "ok"}), 200


@app.route("/itineraries", methods=["POST"])
@jwt_required()
def create_itinerary():
    user_id = int(get_jwt_identity())
    body = request.get_json(force=True) or {}

    title = (body.get("title") or "").strip()
    destination_id = body.get("destination_id")
    start_date = body.get("start_date")
    end_date = body.get("end_date")
    notes = body.get("notes", "")

    if not title or not destination_id:
        return jsonify({"error": "title and destination_id are required"}), 400

    # Communication SYNCHRONE : on verifie que la destination existe
    # reellement en interrogeant le Recommendation Service.
    try:
        resp = requests.get(f"{RECOMMENDATION_SERVICE_URL}/destinations/{destination_id}", timeout=5)
        if resp.status_code == 404:
            return jsonify({"error": "destination not found"}), 404
        resp.raise_for_status()
    except requests.RequestException:
        return jsonify({"error": "recommendation-service unavailable"}), 502

    data = load_data()
    new_id = (max((i["id"] for i in data["itineraries"]), default=0)) + 1
    itinerary = {
        "id": new_id,
        "user_id": user_id,
        "title": title,
        "destination_id": destination_id,
        "start_date": start_date,
        "end_date": end_date,
        "notes": notes,
        "created_at": datetime.utcnow().isoformat() + "Z",
    }
    data["itineraries"].append(itinerary)
    save_data(data)

    # Communication ASYNCHRONE : publication d'un evenement, sans bloquer
    # la reponse HTTP sur son bon traitement par un eventuel consommateur.
    publish_event("itinerary.created", itinerary)

    return jsonify({"message": "itinerary created", "itinerary": itinerary}), 201


@app.route("/itineraries", methods=["GET"])
@jwt_required()
def get_itineraries():
    user_id = int(get_jwt_identity())
    data = load_data()
    mine = [i for i in data["itineraries"] if i["user_id"] == user_id]
    return jsonify(mine), 200



@app.route("/reservations", methods=["POST"])
def create_reservation():
    body=request.get_json(silent=True) or {}
    destination_id=body.get("destination_id")
    guest_name=(body.get("guest_name") or "").strip()
    date=(body.get("date") or "").strip()
    at_time=(body.get("time") or "").strip()
    party_size=body.get("party_size")
    note=(body.get("note") or "").strip()
    if not destination_id or not guest_name or not date or not at_time or not party_size:
        return jsonify({"error":"destination_id, guest_name, date, time et party_size sont requis"}),400
    try: party_size=int(party_size)
    except (TypeError,ValueError): return jsonify({"error":"party_size doit etre un entier positif"}),400
    if party_size<1: return jsonify({"error":"party_size doit etre un entier positif"}),400
    resp=requests.get(f"{RECOMMENDATION_SERVICE_URL}/destinations/{destination_id}",timeout=5)
    if resp.status_code==404: return jsonify({"error":"destination not found"}),404
    if not resp.ok: return jsonify({"error":"recommendation-service unavailable"}),502
    dest=resp.json()
    if dest.get("category") not in {"Hôtels","Restaurants"}:
        return jsonify({"error":"les reservations sont disponibles uniquement pour les hotels et restaurants"}),400
    data=load_data(); reservations=data.setdefault("reservations",[])
    rid=max((r.get("id",0) for r in reservations),default=0)+1
    user_id=None
    try:
        from flask_jwt_extended import verify_jwt_in_request
        verify_jwt_in_request(optional=True)
        identity=get_jwt_identity()
        if identity: user_id=int(identity)
    except Exception: pass
    item={"id":rid,"destination_id":destination_id,"destination_name":dest["name"],
          "user_id":user_id,"guest_name":guest_name,"date":date,"time":at_time,
          "party_size":party_size,"note":note,"status":"pending",
          "created_at":datetime.utcnow().isoformat()+"Z"}
    reservations.append(item); save_data(data)
    return jsonify(item),201

@app.route("/reservations", methods=["GET"])
@jwt_required()
def get_reservations():
    uid=int(get_jwt_identity()); data=load_data()
    items=[r for r in data.get("reservations",[]) if r.get("user_id")==uid]
    return jsonify(sorted(items,key=lambda x:x.get("created_at",""),reverse=True)),200

@app.route("/me/activity", methods=["GET"])
@jwt_required()
def activity():
    uid=int(get_jwt_identity()); data=load_data()
    its=[x for x in data.get("itineraries",[]) if x.get("user_id")==uid]
    rs=[x for x in data.get("reservations",[]) if x.get("user_id")==uid]
    ds=[x for x in data.get("pdf_downloads",[]) if x.get("user_id")==uid]
    ds.sort(key=lambda x:x.get("downloaded_at",""),reverse=True)
    return jsonify({"itineraries_count":len(its),"reservations_count":len(rs),
                    "pdf_downloads":ds[:10],"pdf_downloads_count":len(ds)}),200

@app.route("/itineraries/<int:itinerary_id>/share", methods=["POST"])
@jwt_required()
def share_itinerary(itinerary_id):
    uid=int(get_jwt_identity()); data=load_data()
    item=next((x for x in data.get("itineraries",[]) if x.get("id")==itinerary_id and x.get("user_id")==uid),None)
    if not item: return jsonify({"error":"itinerary not found"}),404
    token=item.get("share_token") or secrets.token_urlsafe(16)
    item["share_token"]=token; save_data(data)
    return jsonify({"token":token,"url":f"/itinerary/shared/{token}"}),200

@app.route("/itineraries/public/<token>", methods=["GET"])
def public_itinerary(token):
    data=load_data()
    item=next((x for x in data.get("itineraries",[]) if x.get("share_token")==token),None)
    if not item: return jsonify({"error":"itinerary not found"}),404
    return jsonify(item),200

@app.route("/itineraries/<int:itinerary_id>/download", methods=["GET"])
@jwt_required()
def download_itinerary(itinerary_id):
    uid=int(get_jwt_identity()); data=load_data()
    item=next((x for x in data.get("itineraries",[]) if x.get("id")==itinerary_id and x.get("user_id")==uid),None)
    if not item: return jsonify({"error":"itinerary not found"}),404
    try:
        from reportlab.pdfgen import canvas
        buf=io.BytesIO(); c=canvas.Canvas(buf)
        c.setTitle(item.get("title","Itineraire"))
        c.drawString(60,800,item.get("title","Itineraire"))
        c.drawString(60,775,f"Destination ID : {item.get('destination_id')}")
        c.drawString(60,750,f"Du {item.get('start_date') or '-'} au {item.get('end_date') or '-'}")
        c.drawString(60,725,f"Notes : {item.get('notes') or '-'}")
        c.save(); buf.seek(0)
    except Exception as exc:
        return jsonify({"error":f"PDF generation failed: {exc}"}),500
    downloads=data.setdefault("pdf_downloads",[])
    downloads.append({"itinerary_id":itinerary_id,"user_id":uid,
                      "downloaded_at":datetime.utcnow().isoformat()+"Z"})
    save_data(data)
    return send_file(buf,mimetype="application/pdf",as_attachment=True,
                     download_name=f"itineraire-{itinerary_id}.pdf")

@app.route("/admin/summary", methods=["GET"])
@jwt_required()
def admin_summary():
    """Admin-only summary of itinerary/reservation activity."""
    data = load_data()
    reservations = data.get("reservations", [])
    return jsonify({"itineraries": len(data.get("itineraries", [])),
                    "reservations": len(reservations),
                    "recent_reservations": sorted(reservations, key=lambda r: r.get("created_at", ""), reverse=True)[:20]}), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5002))
    app.run(host="0.0.0.0", port=port, debug=True)
