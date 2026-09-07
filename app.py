"""
Kribi Tour Travel Assistant - Phase 1: The Monolith
A single Flask server handling all requests, with data stored in a JSON file.
"""

import io
import json
import os
import secrets
import time
from datetime import datetime, timedelta

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request, send_file, session as flask_session
from flask_jwt_extended import (
    JWTManager,
    create_access_token,
    decode_token,
    get_jwt_identity,
    jwt_required,
    verify_jwt_in_request,
)
from flask_socketio import SocketIO, join_room, emit, disconnect as socket_disconnect
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token

load_dotenv()  # charge automatiquement les variables definies dans un fichier .env

# ---------------------------------------------------------------------------
# App configuration
# ---------------------------------------------------------------------------
app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("FLASK_SECRET_KEY", "kribi-tour-dev-secret")
app.config["JWT_SECRET_KEY"] = os.environ.get("JWT_SECRET_KEY", "globetrotter-dev-secret")
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(hours=6)
jwt = JWTManager(app)

# SocketIO permet la messagerie en temps reel (salon commun + messages prives)
# sans devoir rafraichir la page. Mode "threading" choisi car il ne demande
# pas de dependance serveur supplementaire (eventlet/gevent) et reste simple
# a deployer sur Render aux cotes de gunicorn.
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

DATA_FILE = os.path.join(os.path.dirname(__file__), "data.json")

# ---------------------------------------------------------------------------
# Supabase Storage configuration
# Permet de conserver data.json ailleurs que sur le disque local de Render,
# qui n'est pas persistant sur le plan gratuit (les donnees sont perdues a
# chaque redeploiement / reveil apres mise en veille). Si ces variables ne
# sont pas definies, l'app continue de fonctionner uniquement avec le fichier
# local (comportement precedent), pour ne jamais bloquer le demarrage.
# ---------------------------------------------------------------------------
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_SECRET_KEY = os.environ.get("SUPABASE_SECRET_KEY", "")
SUPABASE_BUCKET = os.environ.get("SUPABASE_BUCKET", "Globetrotter-data")
SUPABASE_STORAGE_ENABLED = bool(SUPABASE_URL and SUPABASE_SECRET_KEY)
SUPABASE_OBJECT_PATH = "data.json"

# ---------------------------------------------------------------------------
# Google Sign-In configuration
# ---------------------------------------------------------------------------
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")

# ---------------------------------------------------------------------------
# Image API configuration (Pexels — gratuit, cle sur https://www.pexels.com/api/)
# ---------------------------------------------------------------------------
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "")
PEXELS_SEARCH_URL = "https://api.pexels.com/v1/search"
_photo_cache = {}  # simple cache memoire : {query: url_or_None}

# ---------------------------------------------------------------------------
# Weather API configuration (Open-Meteo — gratuit, sans cle)
# ---------------------------------------------------------------------------
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
_weather_cache = {}  # {"lat,lng": {"data": ..., "ts": ...}}
WEATHER_CACHE_TTL = 1800  # 30 minutes


# ---------------------------------------------------------------------------
# Data Access Layer (reads/writes the JSON "database")
# ---------------------------------------------------------------------------
def _supabase_object_url():
    return f"{SUPABASE_URL}/storage/v1/object/{SUPABASE_BUCKET}/{SUPABASE_OBJECT_PATH}"


def _supabase_download_to_disk():
    """Telecharge data.json depuis Supabase Storage et l'ecrit sur le disque
    local. Retourne True si reussi. Ne leve jamais d'exception : en cas
    d'echec (reseau, fichier absent la 1ere fois...), on continue avec la
    copie locale existante (celle du zip deploye)."""
    try:
        resp = requests.get(
            _supabase_object_url(),
            headers={
                "apikey": SUPABASE_SECRET_KEY,
                "Authorization": f"Bearer {SUPABASE_SECRET_KEY}",
            },
            timeout=10,
        )
        if resp.status_code == 200:
            # Valide que le contenu telecharge est bien un JSON exploitable
            # AVANT de l'ecrire sur disque : un fichier corrompu sur Supabase
            # (upload partiel, encodage errone...) ne doit jamais ecraser la
            # copie locale saine du zip deploye.
            try:
                json.loads(resp.content.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                print(f"[supabase] fichier data.json distant corrompu, conserve la copie locale: {exc}")
                return False

            with open(DATA_FILE, "wb") as f:
                f.write(resp.content)
            return True
        elif resp.status_code != 400:
            # 400 = fichier pas encore cree sur Supabase (1er demarrage), attendu.
            # Toute autre erreur (401/403/...) est loguee pour diagnostic.
            print(f"[supabase] echec download data.json: {resp.status_code} {resp.text[:200]}")
    except requests.RequestException as exc:
        print(f"[supabase] erreur reseau download data.json: {exc}")
    return False


def _supabase_upload_from_disk():
    """Envoie le data.json local vers Supabase Storage (upsert). Ne leve
    jamais d'exception : si Supabase est injoignable, l'ecriture locale reste
    valable pour la duree de vie du process, mais ne survivra pas a un
    redemarrage - on log simplement l'echec."""
    try:
        with open(DATA_FILE, "rb") as f:
            content = f.read()
        resp = requests.post(
            _supabase_object_url(),
            headers={
                "apikey": SUPABASE_SECRET_KEY,
                "Authorization": f"Bearer {SUPABASE_SECRET_KEY}",
                "Content-Type": "application/json",
                "x-upsert": "true",
            },
            data=content,
            timeout=10,
        )
        if resp.status_code not in (200, 201):
            print(f"[supabase] echec upload data.json: {resp.status_code} {resp.text[:200]}")
    except requests.RequestException as exc:
        print(f"[supabase] erreur reseau upload data.json: {exc}")


def _supabase_upload_bytes(object_path, content, content_type):
    """Fonction generique : envoie un fichier quelconque (ex: avatar) vers
    Supabase Storage, dans le meme bucket que data.json mais a un chemin
    different (ex: 'avatars/user_12.jpg'). Retourne l'URL publique en cas de
    succes, ou None en cas d'echec (jamais d'exception levee)."""
    if not SUPABASE_STORAGE_ENABLED:
        return None
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
            return f"{SUPABASE_URL}/storage/v1/object/public/{SUPABASE_BUCKET}/{object_path}"
        print(f"[supabase] echec upload {object_path}: {resp.status_code} {resp.text[:200]}")
    except requests.RequestException as exc:
        print(f"[supabase] erreur reseau upload {object_path}: {exc}")
    return None


# Au demarrage du process, on tente une seule fois de recuperer la derniere
# version connue depuis Supabase (qui peut contenir des utilisateurs/avis
# crees depuis le dernier deploiement). Si indisponible, on garde le
# data.json du zip deploye tel quel.
if SUPABASE_STORAGE_ENABLED:
    _supabase_download_to_disk()


def load_data():
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    if SUPABASE_STORAGE_ENABLED:
        _supabase_upload_from_disk()


def next_id(items):
    return max((item["id"] for item in items), default=0) + 1


def admin_required(fn):
    """Decorateur : verifie que l'utilisateur JWT courant a le role 'admin'.
    A utiliser en plus (et apres) de @jwt_required()."""
    from functools import wraps

    @wraps(fn)
    def wrapper(*args, **kwargs):
        user_id = int(get_jwt_identity())
        data = load_data()
        user = next((u for u in data["users"] if u["id"] == user_id), None)
        if not user or user.get("role") != "admin":
            return jsonify({"error": "admin access required"}), 403
        return fn(*args, **kwargs)

    return wrapper


# ---------------------------------------------------------------------------
# Frontend routes (serve the HTML pages)
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/register-page")
def register_page():
    # Meme page que la connexion, desormais fusionnees avec un bouton
    # de bascule (voir templates/login.html)
    return render_template("login.html", google_client_id=GOOGLE_CLIENT_ID)


@app.route("/login-page")
def login_page():
    return render_template("login.html", google_client_id=GOOGLE_CLIENT_ID)


@app.route("/destinations-page")
def destinations_page():
    return render_template("destinations.html")


@app.route("/itineraries-page")
def itineraries_page():
    return render_template("itineraries.html")


@app.route("/reservations-page")
def reservations_page():
    return render_template("reservations.html")


@app.route("/map-page")
def map_page():
    return render_template("map.html")


@app.route("/kribi-page")
def kribi_page():
    return render_template("kribi.html")


@app.route("/category/<path:category_name>")
def category_page(category_name):
    return render_template("category.html", category_name=category_name)


@app.route("/events-page")
def events_page():
    return render_template("events.html")


@app.route("/services-page")
def services_page():
    return render_template("services.html")


@app.route("/favorites-page")
def favorites_page():
    return render_template("favorites.html")


@app.route("/profile-page")
def profile_page():
    # La verification de connexion se fait cote client (redirection si non
    # connecte), la route API /me exige elle un token JWT valide.
    return render_template("profile.html")


@app.route("/chat-page")
def chat_page():
    # Meme logique : la page se rend toujours, la verification de connexion
    # et le chargement des messages se font cote client.
    return render_template("chat.html")


@app.route("/messages-page")
def messages_page():
    return render_template("messages.html")


@app.route("/admin-page")
def admin_page():
    # La verification du role admin se fait cote client (redirection si non
    # admin) et surtout cote serveur sur la route API /admin/stats, qui est
    # la seule a exposer des donnees sensibles.
    return render_template("admin.html")


@app.route("/destination/<int:destination_id>")
def destination_detail_page(destination_id):
    return render_template("destination_detail.html", destination_id=destination_id)


# ---------------------------------------------------------------------------
# API Layer - Images
# Priorite 1 : Wikimedia Commons (gratuit, sans cle, souvent plus pertinent
#              pour des lieux precis - musees, monuments, sites touristiques).
# Priorite 2 : Pexels (banque generaliste, sert de repli si rien trouve).
# ---------------------------------------------------------------------------
WIKIMEDIA_API_URL = "https://commons.wikimedia.org/w/api.php"


WIKIPEDIA_FR_API_URL = "https://fr.wikipedia.org/w/api.php"
WIKIPEDIA_EN_API_URL = "https://en.wikipedia.org/w/api.php"


def _search_wikipedia_pageimage(query, api_url):
    """Cherche l'article Wikipedia le plus pertinent pour la requete, et retourne
    l'image principale de cet article (celle de l'infobox en general). Cette
    approche est plus precise qu'une recherche de fichiers Commons "en vrac",
    car elle s'appuie sur le bon article plutot que sur un mot-cle isole."""
    try:
        search_resp = requests.get(
            api_url,
            params={
                "action": "query",
                "list": "search",
                "srsearch": query,
                "srlimit": 1,
                "format": "json",
            },
            headers={"User-Agent": "KribiTourApp/1.0 (student project)"},
            timeout=6,
        )
        search_resp.raise_for_status()
        results = search_resp.json().get("query", {}).get("search", [])
        if not results:
            return None
        page_title = results[0]["title"]

        image_resp = requests.get(
            api_url,
            params={
                "action": "query",
                "titles": page_title,
                "prop": "pageimages",
                "piprop": "original",
                "format": "json",
            },
            headers={"User-Agent": "KribiTourApp/1.0 (student project)"},
            timeout=6,
        )
        image_resp.raise_for_status()
        pages = image_resp.json().get("query", {}).get("pages", {})
        for page in pages.values():
            original = page.get("original")
            if original:
                return original.get("source")
        return None
    except (requests.RequestException, ValueError, KeyError, IndexError):
        return None


def _search_wikimedia_commons(query):
    """Cherche une image libre de droits sur Wikimedia Commons pour la requete.

    Retourne l'URL de l'image (thumbnail large) ou None si rien de pertinent.
    """
    try:
        # Etape 1 : rechercher des fichiers image correspondant a la requete
        search_resp = requests.get(
            WIKIMEDIA_API_URL,
            params={
                "action": "query",
                "list": "search",
                "srsearch": f"{query} filetype:bitmap",
                "srnamespace": 6,  # namespace "File:"
                "srlimit": 1,
                "format": "json",
            },
            headers={"User-Agent": "KribiTourApp/1.0 (student project)"},
            timeout=6,
        )
        search_resp.raise_for_status()
        results = search_resp.json().get("query", {}).get("search", [])
        if not results:
            return None

        title = results[0]["title"]

        # Etape 2 : recuperer l'URL de l'image a partir de son titre
        info_resp = requests.get(
            WIKIMEDIA_API_URL,
            params={
                "action": "query",
                "titles": title,
                "prop": "imageinfo",
                "iiprop": "url",
                "iiurlwidth": 800,
                "format": "json",
            },
            headers={"User-Agent": "KribiTourApp/1.0 (student project)"},
            timeout=6,
        )
        info_resp.raise_for_status()
        pages = info_resp.json().get("query", {}).get("pages", {})
        for page in pages.values():
            imageinfo = page.get("imageinfo")
            if imageinfo:
                return imageinfo[0].get("thumburl") or imageinfo[0].get("url")
        return None
    except (requests.RequestException, ValueError, KeyError, IndexError):
        return None


def _search_pexels(query):
    """Cherche une photo libre de droits sur Pexels (banque generaliste)."""
    if not PEXELS_API_KEY:
        return None
    try:
        resp = requests.get(
            PEXELS_SEARCH_URL,
            params={"query": query, "per_page": 1, "orientation": "landscape"},
            headers={"Authorization": PEXELS_API_KEY},
            timeout=6,
        )
        resp.raise_for_status()
        photos = resp.json().get("photos", [])
        return photos[0]["src"]["large"] if photos else None
    except (requests.RequestException, ValueError, KeyError, IndexError):
        return None


@app.route("/api/photo", methods=["GET"])
def get_photo():
    """Retourne l'URL d'une photo libre de droits correspondant a la requete.

    Ordre de recherche, du plus precis au plus large :
      1. Image principale de l'article Wikipedia francophone correspondant
      2. Idem sur Wikipedia anglophone (au cas ou l'article FR n'existe pas)
      3. Recherche de fichier sur Wikimedia Commons (requete precise)
      4. Recherche de fichier sur Wikimedia Commons (requete generique de repli, ?fallback=)
    Pexels a ete volontairement exclu : les resultats etaient trop generiques
    et ne correspondaient pas toujours au lieu exact recherche. Si aucune
    source ne renvoie de resultat, url=None : le frontend affiche alors une
    vignette generique (icone de categorie) plutot qu'une photo non pertinente.
    """
    query = request.args.get("q", "").strip()
    fallback_query = request.args.get("fallback", "").strip()
    if not query:
        return jsonify({"url": None}), 200

    cache_key = f"{query}|{fallback_query}"
    if cache_key in _photo_cache:
        return jsonify({"url": _photo_cache[cache_key]}), 200

    url = _search_wikipedia_pageimage(query, WIKIPEDIA_FR_API_URL)
    source = "wikipedia-fr" if url else None

    if not url:
        url = _search_wikipedia_pageimage(query, WIKIPEDIA_EN_API_URL)
        source = "wikipedia-en" if url else None

    if not url:
        url = _search_wikimedia_commons(query)
        source = "wikimedia-commons" if url else None

    if not url and fallback_query:
        url = _search_wikimedia_commons(fallback_query)
        source = "wikimedia-commons-fallback" if url else None

    _photo_cache[cache_key] = url
    return jsonify({"url": url, "source": source}), 200


@app.route("/api/weather", methods=["GET"])
def get_weather():
    """Retourne la meteo actuelle + prevision 4 jours pour des coordonnees GPS.

    Utilise Open-Meteo (https://open-meteo.com), gratuit et sans cle API.
    Reponse mise en cache 30 minutes par coordonnees pour eviter les appels
    repetes.
    """
    lat = request.args.get("lat")
    lng = request.args.get("lng")
    if not lat or not lng:
        return jsonify({"error": "parametres lat et lng requis"}), 400

    cache_key = f"{lat},{lng}"
    now = time.time()
    cached = _weather_cache.get(cache_key)
    if cached and (now - cached["ts"]) < WEATHER_CACHE_TTL:
        return jsonify(cached["data"]), 200

    try:
        resp = requests.get(
            OPEN_METEO_URL,
            params={
                "latitude": lat,
                "longitude": lng,
                "current_weather": "true",
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,weathercode",
                "timezone": "auto",
                "forecast_days": 4,
            },
            timeout=6,
        )
        resp.raise_for_status()
        payload = resp.json()
    except (requests.RequestException, ValueError):
        return jsonify({"error": "meteo indisponible pour le moment"}), 502

    _weather_cache[cache_key] = {"data": payload, "ts": now}
    return jsonify(payload), 200


# ---------------------------------------------------------------------------
# API Layer - Authentication
# ---------------------------------------------------------------------------
@app.route("/register", methods=["POST"])
def register():
    """Register a new user. Un email optionnel peut etre fourni (utilise
    ensuite pour la connexion par email, en plus du nom d'utilisateur)."""
    body = request.get_json(silent=True) or {}
    username = body.get("username", "").strip()
    password = body.get("password", "").strip()
    email = body.get("email", "").strip().lower()
    preferences = body.get("preferences", [])

    if not username or not password:
        return jsonify({"error": "username and password are required"}), 400

    data = load_data()

    if any(u["username"] == username for u in data["users"]):
        return jsonify({"error": "username already exists"}), 409

    if email and any(u.get("email", "").lower() == email for u in data["users"]):
        return jsonify({"error": "email already exists"}), 409

    user = {
        "id": next_id(data["users"]),
        "username": username,
        "password": password,  # NOTE: plain text for the demo/monolith phase only
        "preferences": preferences,
    }
    if email:
        user["email"] = email
    data["users"].append(user)
    save_data(data)

    return jsonify({"message": "user registered", "user": {"id": user["id"], "username": username}}), 201


@app.route("/login", methods=["POST"])
def login():
    """Authenticate a user and return a JWT access token. Le champ
    'username' peut contenir soit le nom d'utilisateur, soit l'email
    (connexion par email), les deux sont acceptes indifferemment."""
    body = request.get_json(silent=True) or {}
    identifier = body.get("username", "").strip()
    password = body.get("password", "").strip()

    data = load_data()
    identifier_lower = identifier.lower()
    user = next(
        (u for u in data["users"] if u["username"] == identifier or u.get("email", "").lower() == identifier_lower),
        None,
    )

    if not user or user.get("password") is None or user["password"] != password:
        return jsonify({"error": "invalid username or password"}), 401

    token = create_access_token(identity=str(user["id"]))
    return jsonify({"access_token": token, "user": {"id": user["id"], "username": user["username"]}}), 200


@app.route("/auth/google", methods=["POST"])
def auth_google():
    """Connecte ou cree un utilisateur a partir d'un jeton d'identite Google.

    Le front-end recupere un "credential" (jeton signe) via Google Identity
    Services, puis l'envoie ici. On le verifie aupres de Google (signature,
    audience, expiration) avant de faire confiance a son contenu.
    """
    if not GOOGLE_CLIENT_ID:
        return jsonify({"error": "Google sign-in is not configured on the server"}), 503

    body = request.get_json(silent=True) or {}
    credential = body.get("credential", "").strip()

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

    # Un compte Google est retrouve via son identifiant Google unique (sub),
    # jamais via le mot de passe puisqu'il n'y en a pas pour ce type de compte.
    user = next((u for u in data["users"] if u.get("google_sub") == google_sub), None)

    if not user:
        # Evite les collisions avec un nom d'utilisateur "classique" existant.
        username = name
        suffix = 1
        existing_usernames = {u["username"] for u in data["users"]}
        while username in existing_usernames:
            suffix += 1
            username = f"{name}{suffix}"

        user = {
            "id": next_id(data["users"]),
            "username": username,
            "password": None,  # pas de mot de passe pour les comptes Google
            "preferences": [],
            "auth_provider": "google",
            "google_sub": google_sub,
            "email": email,
        }
        data["users"].append(user)
        save_data(data)

    token = create_access_token(identity=str(user["id"]))
    return jsonify({"access_token": token, "user": {"id": user["id"], "username": user["username"]}}), 200


@app.route("/me", methods=["GET"])
@jwt_required()
def get_me():
    """Retourne le profil complet de l'utilisateur actuellement connecte
    (utilise par l'onglet Profil et pour savoir si le lien admin doit
    s'afficher dans la navigation)."""
    user_id = int(get_jwt_identity())
    data = load_data()

    user = next((u for u in data["users"] if u["id"] == user_id), None)
    if not user:
        return jsonify({"error": "user not found"}), 404

    # Ne jamais renvoyer le mot de passe, meme hashe/absent.
    safe_user = {
        "id": user["id"],
        "username": user["username"],
        "preferences": user.get("preferences", []),
        "role": user.get("role", "user"),
        "auth_provider": user.get("auth_provider", "password"),
        "email": user.get("email"),
        "avatar_url": user.get("avatar_url"),
    }
    return jsonify(safe_user), 200


@app.route("/me/avatar", methods=["POST"])
@jwt_required()
def upload_avatar():
    """Recoit une image envoyee en multipart/form-data (champ 'avatar') et
    la stocke sur Supabase Storage. Necessite que Supabase soit configure -
    sans cela l'upload de photo n'est pas disponible (mais le reste de
    l'app continue de fonctionner normalement)."""
    if not SUPABASE_STORAGE_ENABLED:
        return jsonify({"error": "l'upload de photo n'est pas disponible pour le moment"}), 503

    if "avatar" not in request.files:
        return jsonify({"error": "aucun fichier recu"}), 400

    file = request.files["avatar"]
    if not file.filename:
        return jsonify({"error": "aucun fichier recu"}), 400

    allowed_types = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
    content_type = file.mimetype
    if content_type not in allowed_types:
        return jsonify({"error": "format d'image non supporte (JPEG, PNG ou WEBP uniquement)"}), 400

    content = file.read()
    max_size = 3 * 1024 * 1024  # 3 Mo, largement suffisant pour un avatar
    if len(content) > max_size:
        return jsonify({"error": "image trop volumineuse (3 Mo maximum)"}), 400

    user_id = int(get_jwt_identity())
    ext = allowed_types[content_type]
    object_path = f"avatars/user_{user_id}.{ext}"

    url = _supabase_upload_bytes(object_path, content, content_type)
    if not url:
        return jsonify({"error": "echec de l'envoi de la photo, reessayez"}), 502

    data = load_data()
    user = next((u for u in data["users"] if u["id"] == user_id), None)
    if not user:
        return jsonify({"error": "user not found"}), 404

    # Ajoute un parametre de cache-busting pour que le navigateur affiche
    # bien la nouvelle photo immediatement (sinon il pourrait garder
    # l'ancienne en cache, l'URL Supabase etant identique a chaque upload).
    user["avatar_url"] = f"{url}?t={int(time.time())}"
    save_data(data)

    return jsonify({"avatar_url": user["avatar_url"]}), 200


# ---------------------------------------------------------------------------
# API Layer - Destinations
# ---------------------------------------------------------------------------
IMAGES_DIR = os.path.join(os.path.dirname(__file__), "static", "images")
LOCAL_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")


def get_local_image_url(image_id, prefix=""):
    """Si une image a ete fournie manuellement (fichier nomme d'apres son id,
    eventuellement prefixe pour les evenements/services), retourne son URL.
    Sinon retourne None (le frontend se rabattra alors sur Wikimedia/Pexels)."""
    for ext in LOCAL_IMAGE_EXTENSIONS:
        filename = f"{prefix}{image_id}{ext}"
        if os.path.isfile(os.path.join(IMAGES_DIR, filename)):
            return f"/static/images/{filename}"
    return None


def attach_local_image(destination):
    destination = dict(destination)
    destination["local_image"] = get_local_image_url(destination["id"])
    return destination


def attach_event_image(event):
    event = dict(event)
    event["local_image"] = get_local_image_url(event["id"], prefix="event-")
    return event


@app.route("/destinations", methods=["GET"])
def get_destinations():
    """Search destinations, optionally filtered by name, country, tag, category or city."""
    data = load_data()
    destinations = data["destinations"]

    query = request.args.get("q", "").strip().lower()
    tag = request.args.get("tag", "").strip().lower()
    category = request.args.get("category", "").strip().lower()
    city = request.args.get("city", "").strip().lower()

    if query:
        destinations = [
            d for d in destinations
            if query in d["name"].lower() or query in d["country"].lower()
        ]

    if tag:
        destinations = [d for d in destinations if tag in [t.lower() for t in d["tags"]]]

    if category:
        destinations = [d for d in destinations if d.get("category", "").lower() == category]

    if city:
        destinations = [d for d in destinations if d.get("city", "").lower() == city]

    return jsonify([attach_local_image(d) for d in destinations]), 200


@app.route("/destinations/<int:destination_id>", methods=["GET"])
def get_destination_by_id(destination_id):
    """Return a single destination's full details."""
    data = load_data()
    destination = next((d for d in data["destinations"] if d["id"] == destination_id), None)
    if not destination:
        return jsonify({"error": "destination not found"}), 404

    # Compteur de vues, utilise ensuite par le tableau de bord admin
    # pour identifier les lieux les plus consultes.
    destination["views"] = destination.get("views", 0) + 1
    save_data(data)

    return jsonify(attach_local_image(destination)), 200


# ---------------------------------------------------------------------------
# API Layer - Avis / Reviews
# ---------------------------------------------------------------------------
@app.route("/destinations/<int:destination_id>/reviews", methods=["GET"])
def get_reviews(destination_id):
    """Retourne les avis d'une destination, triés du plus récent au plus ancien,
    ainsi que la note moyenne."""
    data = load_data()
    if not any(d["id"] == destination_id for d in data["destinations"]):
        return jsonify({"error": "destination not found"}), 404

    reviews = [r for r in data.get("reviews", []) if r["destination_id"] == destination_id]
    reviews.sort(key=lambda r: r["date"], reverse=True)
    average = round(sum(r["rating"] for r in reviews) / len(reviews), 1) if reviews else None

    return jsonify({"reviews": reviews, "average": average, "count": len(reviews)}), 200


@app.route("/destinations/<int:destination_id>/reviews", methods=["POST"])
def create_review(destination_id):
    """Ajoute un avis (note + commentaire + photo optionnelle) sur une
    destination. Ouvert a tous, connecte ou non (un pseudonyme facultatif
    peut etre fourni). Accepte soit du JSON classique (sans photo), soit du
    multipart/form-data (avec un champ 'photo' optionnel), pour rester
    compatible avec les appels existants qui n'envoient pas de photo."""
    data = load_data()
    if not any(d["id"] == destination_id for d in data["destinations"]):
        return jsonify({"error": "destination not found"}), 404

    if request.content_type and "multipart/form-data" in request.content_type:
        body = request.form
    else:
        body = request.get_json(silent=True) or {}

    author = (body.get("author") or "").strip() or "Visiteur anonyme"
    comment = (body.get("comment") or "").strip()
    rating = body.get("rating")

    try:
        rating = int(rating)
    except (TypeError, ValueError):
        return jsonify({"error": "rating must be an integer between 1 and 5"}), 400

    if rating < 1 or rating > 5:
        return jsonify({"error": "rating must be between 1 and 5"}), 400
    if not comment:
        return jsonify({"error": "comment is required"}), 400

    review_id = next_id(data.get("reviews", []))
    photo_url = None

    # La photo est facultative et necessite Supabase Storage (comme pour les
    # avatars) ; son absence n'empeche jamais la publication de l'avis.
    if "photo" in request.files and request.files["photo"].filename:
        if SUPABASE_STORAGE_ENABLED:
            file = request.files["photo"]
            allowed_types = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
            content_type = file.mimetype
            if content_type in allowed_types:
                content = file.read()
                max_size = 5 * 1024 * 1024  # 5 Mo, suffisant pour une photo de lieu
                if len(content) <= max_size:
                    ext = allowed_types[content_type]
                    object_path = f"reviews/destination_{destination_id}_review_{review_id}.{ext}"
                    uploaded_url = _supabase_upload_bytes(object_path, content, content_type)
                    if uploaded_url:
                        photo_url = f"{uploaded_url}?t={int(time.time())}"

    review = {
        "id": review_id,
        "destination_id": destination_id,
        "author": author[:60],
        "rating": rating,
        "comment": comment[:1000],
        "photo_url": photo_url,
        "date": datetime.utcnow().isoformat() + "Z",
    }
    data.setdefault("reviews", []).append(review)
    save_data(data)

    return jsonify({"message": "review added", "review": review}), 201


# ---------------------------------------------------------------------------
# API Layer - Evenements & Services utiles
# ---------------------------------------------------------------------------
KRIBI_CENTER = (2.9464, 9.9074)


def haversine_km(lat1, lng1, lat2, lng2):
    from math import radians, sin, cos, sqrt, atan2
    r = 6371.0
    dlat = radians(lat2 - lat1)
    dlng = radians(lng2 - lng1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng / 2) ** 2
    return r * 2 * atan2(sqrt(a), sqrt(1 - a))


@app.route("/events", methods=["GET"])
def get_events():
    """List upcoming/all events, sorted by date. ?upcoming=true filters out past events."""
    data = load_data()
    events = data.get("events", [])
    if request.args.get("upcoming", "").lower() == "true":
        today = datetime.utcnow().strftime("%Y-%m-%d")
        events = [e for e in events if (e.get("end_date") or e.get("date")) >= today]
    events = sorted(events, key=lambda e: e["date"])
    return jsonify([attach_event_image(e) for e in events]), 200


@app.route("/services", methods=["GET"])
def get_services():
    """List useful services (hospitals, pharmacies, banks...), sorted by distance
    from the Kribi city center. ?type= filters by service type."""
    data = load_data()
    services = data.get("services", [])

    service_type = request.args.get("type", "").strip().lower()
    if service_type:
        services = [s for s in services if s.get("type", "").lower() == service_type]

    enriched = []
    for s in services:
        item = dict(s)
        item["distance_km"] = round(
            haversine_km(KRIBI_CENTER[0], KRIBI_CENTER[1], s["lat"], s["lng"]), 2
        )
        enriched.append(item)

    enriched.sort(key=lambda s: s["distance_km"])
    return jsonify(enriched), 200


# ---------------------------------------------------------------------------
# API Layer - Recommendations
# ---------------------------------------------------------------------------
@app.route("/recommendations", methods=["GET"])
@jwt_required()
def get_recommendations():
    """Return destinations matching the current user's preferences."""
    user_id = int(get_jwt_identity())
    data = load_data()

    user = next((u for u in data["users"] if u["id"] == user_id), None)
    if not user:
        return jsonify({"error": "user not found"}), 404

    preferences = set(p.lower() for p in user.get("preferences", []))

    if not preferences:
        # No preferences set -> return everything
        recommended = data["destinations"]
    else:
        recommended = [
            d for d in data["destinations"]
            if preferences.intersection(t.lower() for t in d["tags"])
        ]

    return jsonify([attach_local_image(d) for d in recommended]), 200


# ---------------------------------------------------------------------------
# API Layer - Itineraries
# ---------------------------------------------------------------------------
@app.route("/itineraries", methods=["POST"])
@jwt_required()
def create_itinerary():
    """Create a new itinerary for the current user."""
    user_id = int(get_jwt_identity())
    body = request.get_json(silent=True) or {}

    title = body.get("title", "").strip()
    destination_id = body.get("destination_id")
    start_date = body.get("start_date", "")
    end_date = body.get("end_date", "")
    notes = body.get("notes", "")

    if not title or destination_id is None:
        return jsonify({"error": "title and destination_id are required"}), 400

    data = load_data()

    if not any(d["id"] == destination_id for d in data["destinations"]):
        return jsonify({"error": "destination_id does not exist"}), 400

    itinerary = {
        "id": next_id(data["itineraries"]),
        "user_id": user_id,
        "title": title,
        "destination_id": destination_id,
        "start_date": start_date,
        "end_date": end_date,
        "notes": notes,
    }
    data["itineraries"].append(itinerary)
    save_data(data)

    return jsonify({"message": "itinerary created", "itinerary": itinerary}), 201


@app.route("/itineraries", methods=["GET"])
@jwt_required()
def get_itineraries():
    """Return all itineraries belonging to the current user."""
    user_id = int(get_jwt_identity())
    data = load_data()

    user_itineraries = [it for it in data["itineraries"] if it["user_id"] == user_id]
    return jsonify(user_itineraries), 200


def build_itinerary_pdf(itinerary, destination):
    """Genere un PDF autonome (consultable hors-ligne, imprimable) pour un
    itineraire, avec les infos pratiques de la destination associee."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        topMargin=2 * cm, bottomMargin=2 * cm, leftMargin=2 * cm, rightMargin=2 * cm,
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "GTTitle", parent=styles["Title"], fontSize=22, textColor=colors.HexColor("#0e3a5c"),
    )
    heading_style = ParagraphStyle(
        "GTHeading", parent=styles["Heading2"], fontSize=13, spaceBefore=14, spaceAfter=6,
        textColor=colors.HexColor("#0e3a5c"),
    )
    normal_style = ParagraphStyle("GTNormal", parent=styles["Normal"], fontSize=10.5, leading=15)
    muted_style = ParagraphStyle("GTMuted", parent=styles["Normal"], fontSize=9, textColor=colors.grey)

    story = []
    story.append(Paragraph("Kribi Tour", muted_style))
    story.append(Paragraph(itinerary.get("title") or "Mon itineraire", title_style))
    story.append(Spacer(1, 4))
    story.append(HRFlowable(width="100%", color=colors.HexColor("#0e3a5c"), thickness=1))
    story.append(Spacer(1, 10))

    dest_name = destination["name"] if destination else f"Destination #{itinerary.get('destination_id')}"
    dest_category = destination.get("category", "") if destination else ""

    story.append(Paragraph("Destination", heading_style))
    story.append(Paragraph(f"<b>{dest_name}</b>" + (f" &nbsp;&nbsp;<font color='grey'>({dest_category})</font>" if dest_category else ""), normal_style))
    if destination and destination.get("description"):
        story.append(Spacer(1, 4))
        story.append(Paragraph(destination["description"], normal_style))

    story.append(Paragraph("Dates du sejour", heading_style))
    date_rows = [
        ["Depart", itinerary.get("start_date") or "Non precise"],
        ["Retour", itinerary.get("end_date") or "Non precise"],
    ]
    date_table = Table(date_rows, colWidths=[4 * cm, 10 * cm])
    date_table.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 10.5),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#0e3a5c")),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
    ]))
    story.append(date_table)

    if itinerary.get("notes"):
        story.append(Paragraph("Notes personnelles", heading_style))
        story.append(Paragraph(itinerary["notes"], normal_style))

    if destination:
        if destination.get("budget"):
            story.append(Paragraph("Budget indicatif", heading_style))
            story.append(Paragraph(destination["budget"], normal_style))

        transport = destination.get("transport")
        if transport:
            story.append(Paragraph("Transport", heading_style))
            if isinstance(transport, dict):
                if transport.get("walk"):
                    story.append(Paragraph(f"<b>À pied :</b> {transport['walk']}", normal_style))
                if transport.get("moto"):
                    story.append(Paragraph(f"<b>Moto :</b> {transport['moto']}", normal_style))
                if transport.get("taxi"):
                    story.append(Paragraph(f"<b>Voiture :</b> {transport['taxi']}", normal_style))
                if transport.get("note"):
                    story.append(Paragraph(f"<i>{transport['note']}</i>", muted_style))
            else:
                story.append(Paragraph(str(transport), normal_style))

        if destination.get("contact"):
            story.append(Paragraph("Contact", heading_style))
            story.append(Paragraph(destination["contact"], normal_style))

        practical = destination.get("practical_info") or {}
        if practical:
            story.append(Paragraph("Informations pratiques", heading_style))
            for label, key in [("Horaires", "hours"), ("Meilleure periode", "best_time"), ("Acces", "access")]:
                if practical.get(key):
                    story.append(Paragraph(f"<b>{label} :</b> {practical[key]}", normal_style))

    story.append(Spacer(1, 20))
    story.append(HRFlowable(width="100%", color=colors.HexColor("#cccccc"), thickness=0.5))
    story.append(Spacer(1, 6))
    story.append(Paragraph(
        f"Genere le {datetime.utcnow().strftime('%d/%m/%Y')} depuis Kribi Tour. "
        "Document telechargeable, consultable sans connexion internet.",
        muted_style,
    ))

    doc.build(story)
    buffer.seek(0)
    return buffer


@app.route("/itineraries/<int:itinerary_id>/download", methods=["GET"])
@jwt_required()
def download_itinerary(itinerary_id):
    """Genere et renvoie un PDF telechargeable de l'itineraire, pour une
    consultation hors-ligne (utile la ou le reseau est absent)."""
    user_id = int(get_jwt_identity())
    data = load_data()

    itinerary = next((it for it in data["itineraries"] if it["id"] == itinerary_id), None)
    if not itinerary:
        return jsonify({"error": "itinerary not found"}), 404
    if itinerary["user_id"] != user_id:
        return jsonify({"error": "not authorized to access this itinerary"}), 403

    destination = next((d for d in data["destinations"] if d["id"] == itinerary["destination_id"]), None)

    pdf_buffer = build_itinerary_pdf(itinerary, destination)
    safe_title = "".join(c if c.isalnum() or c in " -_" else "" for c in (itinerary.get("title") or "itineraire")).strip() or "itineraire"
    filename = f"{safe_title}.pdf"

    # Journalise le telechargement pour l'historique d'activites du profil.
    data.setdefault("pdf_downloads", []).append({
        "id": next_id(data.setdefault("pdf_downloads", [])),
        "user_id": user_id,
        "itinerary_id": itinerary_id,
        "itinerary_title": itinerary.get("title") or "itineraire",
        "downloaded_at": datetime.utcnow().isoformat() + "Z",
    })
    save_data(data)

    return send_file(
        pdf_buffer,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=filename,
    )


@app.route("/itineraries/<int:itinerary_id>/share", methods=["POST"])
@jwt_required()
def share_itinerary(itinerary_id):
    """Genere (ou renvoie, si deja existant) un token de partage public pour
    cet itineraire. Le token permet a n'importe qui possedant le lien de
    consulter l'itineraire sans etre connecte, sans pouvoir deviner l'URL
    d'un autre itineraire (contrairement a un simple ID incremental)."""
    user_id = int(get_jwt_identity())
    data = load_data()

    itinerary = next((it for it in data["itineraries"] if it["id"] == itinerary_id), None)
    if not itinerary:
        return jsonify({"error": "itinerary not found"}), 404
    if itinerary["user_id"] != user_id:
        return jsonify({"error": "not authorized to access this itinerary"}), 403

    if not itinerary.get("share_token"):
        itinerary["share_token"] = secrets.token_urlsafe(16)
        save_data(data)

    return jsonify({"share_token": itinerary["share_token"]}), 200


@app.route("/itineraries/public/<token>", methods=["GET"])
def get_public_itinerary(token):
    """Renvoie les infos d'un itineraire partage via son token public,
    accessible sans compte ni connexion (pour un lien envoye par
    SMS/WhatsApp/etc.)."""
    data = load_data()

    itinerary = next((it for it in data["itineraries"] if it.get("share_token") == token), None)
    if not itinerary:
        return jsonify({"error": "shared itinerary not found"}), 404

    destination = next((d for d in data["destinations"] if d["id"] == itinerary["destination_id"]), None)

    return jsonify({
        "title": itinerary.get("title"),
        "start_date": itinerary.get("start_date"),
        "end_date": itinerary.get("end_date"),
        "notes": itinerary.get("notes"),
        "destination": destination,
    }), 200


@app.route("/itinerary/shared/<token>")
def public_itinerary_page(token):
    return render_template("itinerary_public.html", token=token)


# ---------------------------------------------------------------------------
# API Layer - Reservations (hotels et restaurants uniquement)
# ---------------------------------------------------------------------------
RESERVABLE_CATEGORIES = {"Hôtels", "Restaurants"}


@app.route("/reservations", methods=["POST"])
def create_reservation():
    """Cree une reservation pour un hotel ou restaurant. Ne necessite pas
    d'etre connecte (formulaire accessible a tout visiteur), mais si un
    jeton JWT valide est fourni, la reservation est rattachee au compte."""
    body = request.get_json(silent=True) or {}

    destination_id = body.get("destination_id")
    guest_name = body.get("guest_name", "").strip()
    date = body.get("date", "").strip()
    time = body.get("time", "").strip()
    party_size = body.get("party_size")
    note = body.get("note", "").strip()

    if not destination_id or not guest_name or not date or not time or not party_size:
        return jsonify({"error": "destination_id, guest_name, date, time et party_size sont requis"}), 400

    try:
        party_size = int(party_size)
        if party_size < 1:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({"error": "party_size doit etre un nombre entier positif"}), 400

    data = load_data()
    destination = next((d for d in data["destinations"] if d["id"] == destination_id), None)

    if not destination:
        return jsonify({"error": "destination not found"}), 404
    if destination.get("category") not in RESERVABLE_CATEGORIES:
        return jsonify({"error": "les reservations ne sont disponibles que pour les hotels et restaurants"}), 400

    # Rattache la reservation au compte connecte si un jeton valide est present,
    # sans exiger de connexion (visiteur de passage accepte aussi).
    user_id = None
    try:
        verify_jwt_in_request(optional=True)
        identity = get_jwt_identity()
        if identity:
            user_id = int(identity)
    except Exception:
        user_id = None

    reservation = {
        "id": next_id(data["reservations"]),
        "destination_id": destination_id,
        "destination_name": destination["name"],
        "user_id": user_id,
        "guest_name": guest_name,
        "date": date,
        "time": time,
        "party_size": party_size,
        "note": note,
        "status": "pending",
        "created_at": datetime.utcnow().isoformat() + "Z",
    }
    data["reservations"].append(reservation)
    save_data(data)

    return jsonify(reservation), 201


@app.route("/reservations", methods=["GET"])
@jwt_required()
def get_my_reservations():
    """Retourne les reservations de l'utilisateur connecte."""
    user_id = int(get_jwt_identity())
    data = load_data()
    my_reservations = [r for r in data["reservations"] if r.get("user_id") == user_id]
    my_reservations.sort(key=lambda r: r["created_at"], reverse=True)
    return jsonify(my_reservations), 200


@app.route("/me/activity", methods=["GET"])
@jwt_required()
def get_my_activity():
    """Agrege l'activite de l'utilisateur connecte pour l'onglet Profil :
    nombre d'itineraires, de reservations, et historique des PDF
    telecharges (les favoris restent geres cote client via localStorage,
    donc non inclus ici)."""
    user_id = int(get_jwt_identity())
    data = load_data()

    my_itineraries = [it for it in data.get("itineraries", []) if it.get("user_id") == user_id]
    my_reservations = [r for r in data.get("reservations", []) if r.get("user_id") == user_id]
    my_downloads = [d for d in data.get("pdf_downloads", []) if d.get("user_id") == user_id]
    my_downloads.sort(key=lambda d: d["downloaded_at"], reverse=True)

    return jsonify({
        "itineraries_count": len(my_itineraries),
        "reservations_count": len(my_reservations),
        "pdf_downloads": my_downloads[:10],  # les 10 plus recents suffisent pour l'affichage
        "pdf_downloads_count": len(my_downloads),
    }), 200



@app.route("/admin/supabase-repair", methods=["GET"])
@jwt_required()
@admin_required
def admin_supabase_repair():
    """Outil de secours : diagnostique et tente de reparer le data.json
    distant sur Supabase s'il est corrompu (caractere de controle invalide,
    upload partiel...). N'ecrase Supabase que si la reparation aboutit a un
    JSON valide contenant au moins autant d'utilisateurs que la version
    locale actuelle (pour ne jamais perdre silencieusement des comptes)."""
    if not SUPABASE_STORAGE_ENABLED:
        return jsonify({"error": "Supabase non configure"}), 503

    try:
        resp = requests.get(
            _supabase_object_url(),
            headers={
                "apikey": SUPABASE_SECRET_KEY,
                "Authorization": f"Bearer {SUPABASE_SECRET_KEY}",
            },
            timeout=10,
        )
    except requests.RequestException as exc:
        return jsonify({"error": f"impossible de joindre Supabase: {exc}"}), 502

    if resp.status_code != 200:
        return jsonify({"error": f"Supabase a repondu {resp.status_code}", "detail": resp.text[:500]}), 502

    raw = resp.content

    # 1) Le fichier distant est-il deja valide ?
    try:
        remote_data = json.loads(raw.decode("utf-8"))
        return jsonify({
            "status": "already_valid",
            "message": "Le fichier sur Supabase est deja un JSON valide, aucune reparation necessaire.",
            "users_count": len(remote_data.get("users", [])),
        }), 200
    except (json.JSONDecodeError, UnicodeDecodeError) as first_error:
        pass

    # 2) Tentative de reparation : on retire les caracteres de controle
    # invalides (hors \n, \r, \t qui sont autorises dans une chaine JSON
    # correctement echappee) qui sont la cause la plus frequente de ce
    # type de corruption lors d'un transfert.
    try:
        text = raw.decode("utf-8", errors="replace")
    except Exception as exc:
        return jsonify({"error": f"decodage impossible: {exc}"}), 500

    cleaned = "".join(
        ch for ch in text
        if ch in ("\n", "\r", "\t") or ord(ch) >= 0x20
    )

    try:
        repaired_data = json.loads(cleaned)
    except json.JSONDecodeError as second_error:
        return jsonify({
            "status": "repair_failed",
            "message": "Le fichier distant est corrompu et n'a pas pu etre repare automatiquement.",
            "first_error": str(first_error),
            "error_after_cleanup": str(second_error),
            "hint": "Contacter le support technique avec ce message pour une reparation manuelle.",
        }), 500

    # 3) Garde-fou : ne jamais ecraser Supabase si la version reparee a
    # moins d'utilisateurs que la copie locale actuelle (signe que la
    # reparation a corrompu/perdu des donnees plutot que les restaurer).
    local_data = load_data()
    local_users = len(local_data.get("users", []))
    repaired_users = len(repaired_data.get("users", []))

    if repaired_users < local_users:
        return jsonify({
            "status": "repair_rejected",
            "message": (
                f"La version reparee ne contient que {repaired_users} utilisateur(s) "
                f"contre {local_users} dans la copie locale actuelle. Reparation annulee "
                "par securite pour ne pas perdre de comptes."
            ),
        }), 409

    # La reparation semble sure : on l'ecrit localement puis on la renvoie
    # vers Supabase pour remplacer la version corrompue.
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(repaired_data, f, indent=2, ensure_ascii=False)
    _supabase_upload_from_disk()

    return jsonify({
        "status": "repaired",
        "message": f"Fichier repare avec succes et renvoye vers Supabase. {repaired_users} utilisateur(s) recuperes.",
        "users": [u.get("username") for u in repaired_data.get("users", [])],
    }), 200


@app.route("/admin/stats", methods=["GET"])
@jwt_required()
@admin_required
def admin_stats():
    """Tableau de bord admin : vue d'ensemble de l'activite de l'application."""
    data = load_data()

    destinations = data.get("destinations", [])
    reviews = data.get("reviews", [])
    users = data.get("users", [])
    itineraries = data.get("itineraries", [])
    events = data.get("events", [])
    services = data.get("services", [])

    # Endroits les plus consultes (compteur de vues incremente a chaque
    # ouverture de fiche detail, voir /destinations/<id>)
    most_viewed = sorted(destinations, key=lambda d: d.get("views", 0), reverse=True)[:10]
    most_viewed_list = [
        {
            "id": d["id"],
            "name": d["name"],
            "category": d.get("category"),
            "views": d.get("views", 0),
        }
        for d in most_viewed
        if d.get("views", 0) > 0
    ]

    # Note moyenne globale et repartition des notes
    ratings = [r["rating"] for r in reviews]
    average_rating = round(sum(ratings) / len(ratings), 2) if ratings else None

    # Avis les plus recents, avec le nom de la destination concernee pour lisibilite
    dest_by_id = {d["id"]: d["name"] for d in destinations}
    recent_reviews = sorted(reviews, key=lambda r: r["date"], reverse=True)[:10]
    recent_reviews_list = [
        {
            "id": r["id"],
            "destination_id": r["destination_id"],
            "destination_name": dest_by_id.get(r["destination_id"], "?"),
            "author": r["author"],
            "rating": r["rating"],
            "comment": r["comment"],
            "date": r["date"],
        }
        for r in recent_reviews
    ]

    # Repartition des destinations par categorie (utile pour voir la couverture du catalogue)
    by_category = {}
    for d in destinations:
        cat = d.get("category", "Autres")
        by_category[cat] = by_category.get(cat, 0) + 1

    # Reservations les plus recentes (hotels/restaurants), toutes confondues
    reservations = data.get("reservations", [])
    recent_reservations = sorted(reservations, key=lambda r: r["created_at"], reverse=True)[:20]

    stats = {
        "totals": {
            "users": len(users),
            "destinations": len(destinations),
            "reviews": len(reviews),
            "itineraries": len(itineraries),
            "events": len(events),
            "services": len(services),
            "total_views": sum(d.get("views", 0) for d in destinations),
            "reservations": len(reservations),
        },
        "average_rating": average_rating,
        "most_viewed_destinations": most_viewed_list,
        "recent_reviews": recent_reviews_list,
        "destinations_by_category": by_category,
        "recent_reservations": recent_reservations,
    }

    return jsonify(stats), 200


# ---------------------------------------------------------------------------
# Stories : photo ou courte video visible par tous pendant 24h, a la maniere
# de WhatsApp/Instagram. Pas de suppression physique du fichier a l'expiration
# (simplicite du monolithe) : on filtre simplement les stories de plus de 24h
# a la lecture, elles restent invisibles sans etre effacees du stockage.
# ---------------------------------------------------------------------------

@app.route("/stories", methods=["POST"])
@jwt_required()
def create_story():
    """Publie une story (photo ou courte video) pour l'utilisateur connecte."""
    if not SUPABASE_STORAGE_ENABLED:
        return jsonify({"error": "story upload is not configured on this server"}), 503

    user_id = int(get_jwt_identity())
    data = load_data()
    user = next((u for u in data["users"] if u["id"] == user_id), None)
    if not user:
        return jsonify({"error": "user not found"}), 404

    if "media" not in request.files or not request.files["media"].filename:
        return jsonify({"error": "media file is required"}), 400

    file = request.files["media"]
    allowed_types = {
        "image/jpeg": "jpg", "image/png": "png", "image/webp": "webp",
        "video/mp4": "mp4", "video/quicktime": "mov",
    }
    content_type = file.mimetype
    if content_type not in allowed_types:
        return jsonify({"error": "unsupported media type"}), 400

    content = file.read()
    max_size = 20 * 1024 * 1024  # 20 Mo, suffisant pour une courte video de story
    if len(content) > max_size:
        return jsonify({"error": "file too large (max 20 MB)"}), 400

    story_id = next_id(data.get("stories", []))
    ext = allowed_types[content_type]
    object_path = f"stories/user_{user_id}_story_{story_id}.{ext}"
    uploaded_url = _supabase_upload_bytes(object_path, content, content_type)
    if not uploaded_url:
        return jsonify({"error": "upload failed"}), 502

    story = {
        "id": story_id,
        "user_id": user_id,
        "username": user["username"],
        "media_url": f"{uploaded_url}?t={int(time.time())}",
        "media_type": "video" if content_type.startswith("video") else "image",
        "created_at": datetime.utcnow().isoformat() + "Z",
    }
    data.setdefault("stories", []).append(story)
    save_data(data)

    return jsonify({"message": "story published", "story": story}), 201


@app.route("/stories", methods=["GET"])
@jwt_required()
def list_stories():
    """Renvoie les stories publiees il y a moins de 24h, groupees par auteur
    (la plus recente de chaque auteur en tete de son groupe)."""
    data = load_data()
    cutoff = datetime.utcnow() - timedelta(hours=24)

    active_stories = [
        s for s in data.get("stories", [])
        if datetime.fromisoformat(s["created_at"].replace("Z", "")) > cutoff
    ]

    by_author = {}
    for s in sorted(active_stories, key=lambda s: s["created_at"]):
        by_author.setdefault(s["user_id"], {"user_id": s["user_id"], "username": s["username"], "stories": []})
        by_author[s["user_id"]]["stories"].append(s)

    return jsonify(list(by_author.values())), 200


# ---------------------------------------------------------------------------
# Messagerie en temps reel (Socket.IO)
# Un salon commun ("public") ouvert a tous les utilisateurs connectes, et des
# conversations privees a deux (room nommee par les deux user_id tries).
# ---------------------------------------------------------------------------

@app.route("/messages/public", methods=["GET"])
@jwt_required()
def get_public_messages():
    """Renvoie les 100 derniers messages du salon commun, pour affichage a
    l'ouverture de la page de chat (l'historique n'arrive pas par socket)."""
    data = load_data()
    messages = data.get("public_messages", [])
    return jsonify(messages[-100:]), 200


@app.route("/users/list", methods=["GET"])
@jwt_required()
def list_users_for_messaging():
    """Renvoie la liste des autres utilisateurs (id + username), pour
    permettre de choisir avec qui demarrer une conversation privee."""
    user_id = int(get_jwt_identity())
    data = load_data()
    others = [
        {"id": u["id"], "username": u["username"]}
        for u in data["users"]
        if u["id"] != user_id
    ]
    return jsonify(others), 200


@app.route("/messages/private/<int:other_user_id>", methods=["GET"])
@jwt_required()
def get_private_messages(other_user_id):
    """Renvoie l'historique des messages prives entre l'utilisateur connecte
    et other_user_id (dans les deux sens), tries par date."""
    user_id = int(get_jwt_identity())
    data = load_data()

    conversation = [
        m for m in data.get("private_messages", [])
        if {m["from_user_id"], m["to_user_id"]} == {user_id, other_user_id}
    ]
    return jsonify(conversation[-200:]), 200


@app.route("/groups", methods=["POST"])
@jwt_required()
def create_group():
    """Cree un groupe de discussion. Le createur est automatiquement membre,
    meme s'il ne figure pas dans la liste envoyee par le client."""
    user_id = int(get_jwt_identity())
    body = request.get_json(silent=True) or {}

    name = (body.get("name") or "").strip()
    member_ids = body.get("member_ids", [])

    if not name:
        return jsonify({"error": "group name is required"}), 400
    if not isinstance(member_ids, list) or len(member_ids) == 0:
        return jsonify({"error": "at least one other member is required"}), 400

    data = load_data()
    valid_user_ids = {u["id"] for u in data["users"]}
    members = sorted(set([user_id] + [int(m) for m in member_ids if int(m) in valid_user_ids]))

    group = {
        "id": next_id(data.get("groups", [])),
        "name": name[:60],
        "creator_id": user_id,
        "member_ids": members,
        "created_at": datetime.utcnow().isoformat() + "Z",
    }
    data.setdefault("groups", []).append(group)
    save_data(data)

    return jsonify({"message": "group created", "group": group}), 201


@app.route("/groups", methods=["GET"])
@jwt_required()
def list_my_groups():
    """Renvoie les groupes dont l'utilisateur connecte est membre."""
    user_id = int(get_jwt_identity())
    data = load_data()

    my_groups = [g for g in data.get("groups", []) if user_id in g.get("member_ids", [])]
    return jsonify(my_groups), 200


@app.route("/messages/group/<int:group_id>", methods=["GET"])
@jwt_required()
def get_group_messages(group_id):
    """Renvoie l'historique des messages d'un groupe, uniquement si
    l'utilisateur connecte en est membre."""
    user_id = int(get_jwt_identity())
    data = load_data()

    group = next((g for g in data.get("groups", []) if g["id"] == group_id), None)
    if not group:
        return jsonify({"error": "group not found"}), 404
    if user_id not in group.get("member_ids", []):
        return jsonify({"error": "not a member of this group"}), 403

    messages = [m for m in data.get("group_messages", []) if m["group_id"] == group_id]
    return jsonify(messages[-200:]), 200


def _private_room_name(user_id_a, user_id_b):
    """Nom de room stable pour une conversation privee entre 2 utilisateurs,
    peu importe qui initie la connexion en premier."""
    a, b = sorted([int(user_id_a), int(user_id_b)])
    return f"dm_{a}_{b}"


@socketio.on("connect")
def handle_socket_connect(auth):
    """Authentifie la connexion websocket via le token JWT envoye par le
    client (meme token que pour les appels HTTP). Refuse la connexion si le
    token est absent ou invalide, pour eviter les messages anonymes."""
    token = (auth or {}).get("token") if isinstance(auth, dict) else None
    if not token:
        return False  # refuse la connexion

    try:
        decoded = decode_token(token)
        user_id = int(decoded["sub"])
    except Exception:
        return False  # token invalide ou expire

    data = load_data()
    user = next((u for u in data["users"] if u["id"] == user_id), None)
    if not user:
        return False

    # Associe l'utilisateur a sa session socket courante, et l'inscrit
    # automatiquement au salon commun.
    flask_session["user_id"] = user_id
    flask_session["username"] = user["username"]
    join_room("public")
    join_room(f"user_{user_id}")  # room personnelle : utile pour les notifications futures


@socketio.on("disconnect")
def handle_socket_disconnect():
    pass  # rien a nettoyer pour l'instant (pas d'etat "en ligne" persistant)


@socketio.on("send_public_message")
def handle_public_message(payload):
    """Recoit un message pour le salon commun, le sauvegarde et le diffuse
    a tous les utilisateurs connectes au salon."""
    user_id = flask_session.get("user_id")
    username = flask_session.get("username")
    if not user_id:
        return  # connexion non authentifiee (ne devrait pas arriver)

    text = (payload or {}).get("text", "").strip()
    if not text or len(text) > 2000:
        return

    data = load_data()
    message = {
        "id": (max([m["id"] for m in data["public_messages"]], default=0) + 1),
        "user_id": user_id,
        "username": username,
        "text": text,
        "created_at": datetime.utcnow().isoformat() + "Z",
    }
    data["public_messages"].append(message)
    save_data(data)

    emit("new_public_message", message, room="public")


@socketio.on("join_private_conversation")
def handle_join_private_conversation(payload):
    """Rejoint la room d'une conversation privee avec un autre utilisateur,
    pour recevoir ses messages en temps reel."""
    user_id = flask_session.get("user_id")
    if not user_id:
        return

    other_user_id = (payload or {}).get("other_user_id")
    if not other_user_id:
        return

    join_room(_private_room_name(user_id, other_user_id))


@socketio.on("send_private_message")
def handle_private_message(payload):
    """Recoit un message prive destine a un autre utilisateur, le sauvegarde
    et le diffuse uniquement dans la room de cette conversation."""
    user_id = flask_session.get("user_id")
    username = flask_session.get("username")
    if not user_id:
        return

    other_user_id = (payload or {}).get("other_user_id")
    text = (payload or {}).get("text", "").strip()
    if not other_user_id or not text or len(text) > 2000:
        return

    data = load_data()
    message = {
        "id": (max([m["id"] for m in data["private_messages"]], default=0) + 1),
        "from_user_id": user_id,
        "from_username": username,
        "to_user_id": int(other_user_id),
        "text": text,
        "created_at": datetime.utcnow().isoformat() + "Z",
    }
    data["private_messages"].append(message)
    save_data(data)

    emit("new_private_message", message, room=_private_room_name(user_id, other_user_id))


def _group_room_name(group_id):
    """Nom de room stable pour un groupe donne."""
    return f"group_{group_id}"


@socketio.on("join_group_room")
def handle_join_group_room(payload):
    """Rejoint la room d'un groupe, uniquement si l'utilisateur en est
    membre, pour recevoir ses messages en temps reel."""
    user_id = flask_session.get("user_id")
    if not user_id:
        return

    group_id = (payload or {}).get("group_id")
    if not group_id:
        return

    data = load_data()
    group = next((g for g in data.get("groups", []) if g["id"] == int(group_id)), None)
    if not group or user_id not in group.get("member_ids", []):
        return  # pas membre : on ignore silencieusement, pas d'acces a la room

    join_room(_group_room_name(group_id))


@socketio.on("send_group_message")
def handle_group_message(payload):
    """Recoit un message destine a un groupe, le sauvegarde et le diffuse a
    tous les membres actuellement connectes a la room du groupe."""
    user_id = flask_session.get("user_id")
    username = flask_session.get("username")
    if not user_id:
        return

    group_id = (payload or {}).get("group_id")
    text = (payload or {}).get("text", "").strip()
    if not group_id or not text or len(text) > 2000:
        return

    data = load_data()
    group = next((g for g in data.get("groups", []) if g["id"] == int(group_id)), None)
    if not group or user_id not in group.get("member_ids", []):
        return  # pas membre : message refuse silencieusement

    message = {
        "id": (max([m["id"] for m in data.get("group_messages", [])], default=0) + 1),
        "group_id": int(group_id),
        "from_user_id": user_id,
        "from_username": username,
        "text": text,
        "created_at": datetime.utcnow().isoformat() + "Z",
    }
    data.setdefault("group_messages", []).append(message)
    save_data(data)

    emit("new_group_message", message, room=_group_room_name(group_id))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host="0.0.0.0", port=port, debug=True)
