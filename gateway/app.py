import os, requests, time
from flask import Flask, render_template, request, Response, jsonify, send_from_directory
from flask_socketio import SocketIO, join_room, emit
from flask_jwt_extended import JWTManager, decode_token
from dotenv import load_dotenv
load_dotenv()
app=Flask(__name__,template_folder='../templates',static_folder='../static')
app.config['SECRET_KEY']=os.environ.get('FLASK_SECRET_KEY','kribi-tour-dev-secret')
app.config['JWT_SECRET_KEY']=os.environ.get('JWT_SECRET_KEY','globetrotter-dev-secret')
JWTManager(app); socketio=SocketIO(app,cors_allowed_origins='*',async_mode='threading')
SERVICES={
    'user': os.environ.get('USER_SERVICE_URL','http://127.0.0.1:5001'),
    'itinerary': os.environ.get('ITINERARY_SERVICE_URL','http://127.0.0.1:5002'),
    'destination': os.environ.get('DESTINATION_SERVICE_URL','http://127.0.0.1:5003'),
    'recommendation': os.environ.get('RECOMMENDATION_SERVICE_URL','http://127.0.0.1:5004'),
}
ROUTES={
 '/me/activity':'itinerary','/register':'user','/login':'user','/auth/google':'user','/me':'user','/me/avatar':'user','/users/list':'user','/messages/public':'user','/messages/private/':'user','/groups':'user','/messages/group/':'user','/stories':'user','/admin/stats':'user','/admin/supabase-repair':'user',
 '/destinations':'destination','/events':'destination','/services':'destination','/reservations':'destination',
 '/itineraries':'itinerary','/recommendations':'recommendation'
}
def target(path):
    for prefix,s in ROUTES.items():
        if path==prefix or path.startswith(prefix): return SERVICES[s]+path
    return None
def proxy(path):
    url=target(path)
    if not url:return jsonify(error='route not found'),404
    headers={k:v for k,v in request.headers if k.lower() not in {'host','content-length'}}
    try:
        r=requests.request(request.method,url,params=request.args,headers=headers,data=request.get_data(),files=request.files,timeout=30,allow_redirects=False)
        excluded={'content-encoding','content-length','transfer-encoding','connection'}
        rh={k:v for k,v in r.headers.items() if k.lower() not in excluded}
        return Response(r.content,status=r.status_code,headers=rh)
    except requests.RequestException as e:return jsonify(error='microservice unavailable',detail=str(e)),503

@app.route('/')
def index():return render_template('index.html')
@app.route('/register-page')
def register_page():return render_template('login.html',google_client_id=os.environ.get('GOOGLE_CLIENT_ID',''))
@app.route('/login-page')
def login_page():return render_template('login.html',google_client_id=os.environ.get('GOOGLE_CLIENT_ID',''))
@app.route('/destinations-page')
def destinations_page():return render_template('destinations.html')
@app.route('/itineraries-page')
def itineraries_page():return render_template('itineraries.html')
@app.route('/reservations-page')
def reservations_page():return render_template('reservations.html')
@app.route('/map-page')
def map_page():return render_template('map.html')
@app.route('/kribi-page')
def kribi_page():return render_template('kribi.html')
@app.route('/category/<path:category_name>')
def category_page(category_name):return render_template('category.html',category_name=category_name)
@app.route('/events-page')
def events_page():return render_template('events.html')
@app.route('/services-page')
def services_page():return render_template('services.html')
@app.route('/favorites-page')
def favorites_page():return render_template('favorites.html')
@app.route('/profile-page')
def profile_page():return render_template('profile.html')
@app.route('/chat-page')
def chat_page():return render_template('chat.html')
@app.route('/messages-page')
def messages_page():return render_template('messages.html')
@app.route('/admin-page')
def admin_page():return render_template('admin.html')
@app.route('/destination/<int:destination_id>')
def destination_detail_page(destination_id):return render_template('destination_detail.html',destination_id=destination_id)
@app.route('/itinerary/shared/<token>')
def public_itinerary_page(token):return render_template('itinerary_public.html',token=token)
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



# REST proxy: all API calls keep the original Phase 1 URLs.
@app.route('/register',methods=['POST'])
def p_register():return proxy('/register')
@app.route('/login',methods=['POST'])
def p_login():return proxy('/login')
@app.route('/auth/google',methods=['POST'])
def p_google():return proxy('/auth/google')
@app.route('/me',methods=['GET'])
def p_me():return proxy('/me')
@app.route('/me/avatar',methods=['POST'])
def p_avatar():return proxy('/me/avatar')
@app.route('/users/list',methods=['GET'])
def p_users():return proxy('/users/list')
@app.route('/messages/public',methods=['GET'])
def p_pub():return proxy('/messages/public')
@app.route('/messages/private/<int:uid>',methods=['GET'])
def p_priv(uid):return proxy(f'/messages/private/{uid}')
@app.route('/groups',methods=['GET','POST'])
def p_groups():return proxy('/groups')
@app.route('/messages/group/<int:gid>',methods=['GET'])
def p_gm(gid):return proxy(f'/messages/group/{gid}')
@app.route('/stories',methods=['GET','POST'])
def p_stories():return proxy('/stories')
@app.route('/admin/stats',methods=['GET'])
def p_admin():return proxy('/admin/stats')
@app.route('/admin/supabase-repair',methods=['GET'])
def p_supabase_repair():return proxy('/admin/supabase-repair')
@app.route('/destinations',methods=['GET'])
def p_dest():return proxy('/destinations')
@app.route('/destinations/<int:did>',methods=['GET'])
def p_did(did):return proxy(f'/destinations/{did}')
@app.route('/destinations/<int:did>/reviews',methods=['GET','POST'])
def p_reviews(did):return proxy(f'/destinations/{did}/reviews')
@app.route('/events',methods=['GET'])
def p_events():return proxy('/events')
@app.route('/services',methods=['GET'])
def p_services():return proxy('/services')
@app.route('/reservations',methods=['GET','POST'])
def p_reservations():return proxy('/reservations')
@app.route('/recommendations',methods=['GET'])
def p_rec():return proxy('/recommendations')
@app.route('/itineraries',methods=['GET','POST'])
def p_it():return proxy('/itineraries')
@app.route('/itineraries/<int:iid>/download',methods=['GET'])
def p_dl(iid):return proxy(f'/itineraries/{iid}/download')
@app.route('/itineraries/<int:iid>/share',methods=['POST'])
def p_share(iid):return proxy(f'/itineraries/{iid}/share')
@app.route('/itineraries/public/<token>',methods=['GET'])
def p_public_it(token):return proxy(f'/itineraries/public/{token}')
@app.route('/me/activity',methods=['GET'])
def p_activity():return proxy('/me/activity')

def auth_user(auth):
    try:
        token=(auth or {}).get('token') if isinstance(auth,dict) else None
        if not token:return None
        return int(decode_token(token)['sub'])
    except:return None

def uname(uid):
    try:return requests.get(f"{SERVICES['user']}/internal/users/{uid}",timeout=3).json().get('username')
    except:return None

def room_dm(a,b):a,b=sorted([int(a),int(b)]);return f'dm_{a}_{b}'
def room_group(g):return f'group_{int(g)}'
@socketio.on('connect')
def connect(auth):
    uid=auth_user(auth)
    if not uid or not uname(uid):return False
    from flask import session
    session['user_id']=uid;session['username']=uname(uid);join_room('public');join_room(f'user_{uid}')
@socketio.on('send_public_message')
def public_msg(payload):
    from flask import session
    uid=session.get('user_id'); text=(payload or {}).get('text','').strip()
    if not uid or not text or len(text)>2000:return
    r=requests.post(f"{SERVICES['user']}/messages/public",headers={'Authorization':request.headers.get('Authorization','')},json={'text':text},timeout=5)
    # socket auth token is not in HTTP headers, so create equivalent history entry via internal endpoint fallback
    if r.status_code==201: emit('new_public_message',r.json(),room='public')
    else:
        # Use service internal endpoint with trusted local user id.
        rr=requests.post(f"{SERVICES['user']}/internal/messages/public",json={'user_id':uid,'text':text},timeout=5)
        if rr.status_code==201:emit('new_public_message',rr.json(),room='public')
@socketio.on('join_private_conversation')
def join_private(payload):
    from flask import session
    uid=session.get('user_id'); other=(payload or {}).get('other_user_id')
    if uid and other:join_room(room_dm(uid,other))
@socketio.on('send_private_message')
def priv_msg(payload):
    from flask import session
    uid=session.get('user_id');other=(payload or {}).get('other_user_id');text=(payload or {}).get('text','').strip()
    if not uid or not other or not text or len(text)>2000:return
    rr=requests.post(f"{SERVICES['user']}/internal/messages/private",json={'user_id':uid,'other_user_id':int(other),'text':text},timeout=5)
    if rr.status_code==201:emit('new_private_message',rr.json(),room=room_dm(uid,other))
@socketio.on('join_group_room')
def join_group(payload):
    from flask import session
    uid=session.get('user_id');gid=(payload or {}).get('group_id')
    if not uid or not gid:return
    try:g=requests.get(f"{SERVICES['user']}/groups",headers={'X-Internal-User':str(uid)},timeout=3).json()
    except:return
    if any(int(x['id'])==int(gid) and uid in x.get('member_ids',[]) for x in g):join_room(room_group(gid))
@socketio.on('send_group_message')
def group_msg(payload):
    from flask import session
    uid=session.get('user_id');gid=(payload or {}).get('group_id');text=(payload or {}).get('text','').strip()
    if not uid or not gid or not text or len(text)>2000:return
    rr=requests.post(f"{SERVICES['user']}/internal/messages/group",json={'user_id':uid,'group_id':int(gid),'text':text},timeout=5)
    if rr.status_code==201:emit('new_group_message',rr.json(),room=room_group(gid))

if __name__=='__main__':socketio.run(app,host='0.0.0.0',port=int(os.environ.get('PORT',5000)),debug=True,allow_unsafe_werkzeug=True)
