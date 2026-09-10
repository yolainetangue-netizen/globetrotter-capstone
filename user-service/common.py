import json, os, requests
from functools import wraps
from datetime import timedelta
from flask import jsonify
from flask_jwt_extended import JWTManager, jwt_required, get_jwt_identity, decode_token

BASE=os.path.dirname(__file__)
JWT_SECRET=os.environ.get("JWT_SECRET_KEY","globetrotter-dev-secret")

# ---------------------------------------------------------------------------
# Persistance Supabase Storage (portee depuis le monolithe Phase 1)
# Permet de conserver les fichiers JSON de ce service ailleurs que sur le
# disque local du conteneur/instance, qui n'est pas persistant sur la
# plupart des plans gratuits (donnees perdues a chaque redeploiement /
# reveil apres mise en veille). Si les variables ne sont pas definies,
# le service continue de fonctionner uniquement avec les fichiers locaux
# (comportement precedent), pour ne jamais bloquer le demarrage.
# Chaque service utilise son propre sous-dossier ("prefix") dans le bucket
# partage, afin de ne jamais ecraser les donnees d'un autre service.
# ---------------------------------------------------------------------------
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_SECRET_KEY = os.environ.get("SUPABASE_SECRET_KEY", "")
SUPABASE_BUCKET = os.environ.get("SUPABASE_BUCKET", "Globetrotter-data")
SUPABASE_STORAGE_ENABLED = bool(SUPABASE_URL and SUPABASE_SECRET_KEY)
SUPABASE_DATA_PREFIX = "service-data/user-service"


def _supabase_object_url(filename):
    return f"{SUPABASE_URL}/storage/v1/object/{SUPABASE_BUCKET}/{SUPABASE_DATA_PREFIX}/{filename}"


def _supabase_download_to_disk(filename):
    """Telecharge <filename> depuis Supabase Storage et l'ecrit sur le
    disque local. Retourne True si reussi. Ne leve jamais d'exception : en
    cas d'echec (reseau, fichier absent la 1ere fois...), on continue avec
    la copie locale existante."""
    try:
        resp = requests.get(
            _supabase_object_url(filename),
            headers={
                "apikey": SUPABASE_SECRET_KEY,
                "Authorization": f"Bearer {SUPABASE_SECRET_KEY}",
            },
            timeout=10,
        )
        if resp.status_code == 200:
            try:
                json.loads(resp.content.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                print(f"[supabase] {filename} distant corrompu, conserve la copie locale: {exc}")
                return False
            with open(os.path.join(BASE, filename), "wb") as f:
                f.write(resp.content)
            return True
        elif resp.status_code != 400:
            print(f"[supabase] echec download {filename}: {resp.status_code} {resp.text[:200]}")
    except requests.RequestException as exc:
        print(f"[supabase] erreur reseau download {filename}: {exc}")
    return False


def _supabase_upload_from_disk(filename):
    """Envoie le fichier local vers Supabase Storage (upsert). Ne leve
    jamais d'exception : si Supabase est injoignable, l'ecriture locale
    reste valable pour la duree de vie du process, mais ne survivra pas a
    un redemarrage - on log simplement l'echec."""
    if not SUPABASE_STORAGE_ENABLED:
        return
    try:
        with open(os.path.join(BASE, filename), "rb") as f:
            content = f.read()
        resp = requests.post(
            _supabase_object_url(filename),
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
            print(f"[supabase] echec upload {filename}: {resp.status_code} {resp.text[:200]}")
    except requests.RequestException as exc:
        print(f"[supabase] erreur reseau upload {filename}: {exc}")


# Au demarrage du process, on tente une seule fois par fichier de recuperer
# la derniere version connue depuis Supabase. Si indisponible, on garde le
# fichier local tel quel.
_SUPABASE_SYNCED_FILES = set()


def load_json(filename, default):
    if SUPABASE_STORAGE_ENABLED and filename not in _SUPABASE_SYNCED_FILES:
        _supabase_download_to_disk(filename)
        _SUPABASE_SYNCED_FILES.add(filename)
    path=os.path.join(BASE,filename)
    if not os.path.exists(path): return default
    with open(path,encoding="utf-8") as f: return json.load(f)

def save_json(filename,data):
    with open(os.path.join(BASE,filename),"w",encoding="utf-8") as f: json.dump(data,f,ensure_ascii=False,indent=2)
    if SUPABASE_STORAGE_ENABLED:
        _supabase_upload_from_disk(filename)

def next_id(items): return max((int(x.get("id",0)) for x in items),default=0)+1

def user_id(): return int(get_jwt_identity())
