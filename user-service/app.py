import os, time, requests
from datetime import timedelta, datetime
from flask import Flask, jsonify, request
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity
from dotenv import load_dotenv
from common import load_json, save_json, next_id, SUPABASE_STORAGE_ENABLED, _supabase_object_url, _supabase_upload_from_disk, SUPABASE_SECRET_KEY
load_dotenv()
app=Flask(__name__)
app.config['JWT_SECRET_KEY']=os.environ.get('JWT_SECRET_KEY','globetrotter-dev-secret')
app.config['JWT_ACCESS_TOKEN_EXPIRES']=timedelta(hours=6)
JWTManager(app)
USERS='users.json'; UD='user_data.json'

def users(): return load_json(USERS,{'users':[]})['users']
def udata(): return load_json(UD,{'public_messages':[],'private_messages':[],'groups':[],'group_messages':[],'stories':[]})
def save_users(x): save_json(USERS,{'users':x})
def save_ud(x): save_json(UD,x)

def safe(u):
    return {'id':u['id'],'username':u['username'],'preferences':u.get('preferences',[]),'role':u.get('role','user'),'auth_provider':u.get('auth_provider','password'),'email':u.get('email'),'avatar_url':u.get('avatar_url')}

@app.post('/register')
def register():
    b=request.get_json(silent=True) or {}; username=(b.get('username') or '').strip(); password=(b.get('password') or '').strip(); email=(b.get('email') or '').strip().lower(); prefs=b.get('preferences',[])
    if not username or not password: return jsonify(error='username and password are required'),400
    us=users()
    if any(u['username']==username for u in us): return jsonify(error='username already exists'),409
    if email and any(u.get('email','').lower()==email for u in us): return jsonify(error='email already exists'),409
    u={'id':next_id(us),'username':username,'password':password,'preferences':prefs}
    if email:u['email']=email
    us.append(u); save_users(us)
    return jsonify(message='user registered',user={'id':u['id'],'username':username}),201

@app.post('/login')
def login():
    b=request.get_json(silent=True) or {}; ident=(b.get('username') or '').strip(); pw=(b.get('password') or '').strip(); il=ident.lower(); us=users()
    u=next((x for x in us if x['username']==ident or x.get('email','').lower()==il),None)
    if not u or u.get('password') is None or u['password']!=pw: return jsonify(error='invalid username or password'),401
    return jsonify(access_token=create_access_token(identity=str(u['id'])),user={'id':u['id'],'username':u['username']}),200

@app.post('/auth/google')
def google_login():
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token
    client=os.environ.get('GOOGLE_CLIENT_ID','')
    if not client:return jsonify(error='Google sign-in is not configured on the server'),503
    b=request.get_json(silent=True) or {}; cred=(b.get('credential') or '').strip()
    if not cred:return jsonify(error='missing Google credential'),400
    try: payload=id_token.verify_oauth2_token(cred,google_requests.Request(),client)
    except ValueError:return jsonify(error='invalid Google credential'),401
    sub=payload.get('sub'); email=payload.get('email',''); name=payload.get('name') or (email.split('@')[0] if email else f'user{sub}')
    if not sub:return jsonify(error='invalid Google credential'),401
    us=users(); u=next((x for x in us if x.get('google_sub')==sub),None)
    if not u:
        username=name; n=1; names={x['username'] for x in us}
        while username in names:n+=1; username=f'{name}{n}'
        u={'id':next_id(us),'username':username,'password':None,'preferences':[],'auth_provider':'google','google_sub':sub,'email':email}; us.append(u); save_users(us)
    return jsonify(access_token=create_access_token(identity=str(u['id'])),user={'id':u['id'],'username':u['username']}),200

@app.get('/me')
@jwt_required()
def me():
    uid=int(get_jwt_identity()); u=next((x for x in users() if x['id']==uid),None)
    return (jsonify(error='user not found'),404) if not u else (jsonify(safe(u)),200)

@app.get('/internal/users/<int:uid>')
def internal_user(uid):
    u=next((x for x in users() if x['id']==uid),None)
    return (jsonify(error='user not found'),404) if not u else (jsonify(u),200)

@app.post('/me/avatar')
@jwt_required()
def avatar():
    url=os.environ.get('SUPABASE_URL','').rstrip('/'); key=os.environ.get('SUPABASE_SECRET_KEY',''); bucket=os.environ.get('SUPABASE_BUCKET','Globetrotter-data')
    if not (url and key):return jsonify(error="l'upload de photo n'est pas disponible pour le moment"),503
    if 'avatar' not in request.files or not request.files['avatar'].filename:return jsonify(error='aucun fichier recu'),400
    f=request.files['avatar']; types={'image/jpeg':'jpg','image/png':'png','image/webp':'webp'}
    if f.mimetype not in types:return jsonify(error="format d'image non supporte (JPEG, PNG ou WEBP uniquement)"),400
    content=f.read()
    if len(content)>3*1024*1024:return jsonify(error='image trop volumineuse (3 Mo maximum)'),400
    uid=int(get_jwt_identity()); path=f'avatars/user_{uid}.{types[f.mimetype]}'
    r=requests.post(f'{url}/storage/v1/object/{bucket}/{path}',headers={'apikey':key,'Authorization':f'Bearer {key}','Content-Type':f.mimetype,'x-upsert':'true'},data=content,timeout=15)
    if r.status_code not in (200,201):return jsonify(error="echec de l'envoi de la photo, reessayez"),502
    public=f'{url}/storage/v1/object/public/{bucket}/{path}?t={int(time.time())}'
    us=users(); u=next((x for x in us if x['id']==uid),None)
    if not u:return jsonify(error='user not found'),404
    u['avatar_url']=public; save_users(us); return jsonify(avatar_url=public),200

@app.get('/users/list')
@jwt_required()
def user_list():
    uid=int(get_jwt_identity()); return jsonify([{'id':u['id'],'username':u['username']} for u in users() if u['id']!=uid])

@app.get('/messages/public')
@jwt_required()
def public_messages(): return jsonify(udata().get('public_messages',[])[-100:])
@app.post('/messages/public')
@jwt_required()
def add_public():
    uid=int(get_jwt_identity()); b=request.get_json(silent=True) or {}; text=(b.get('text') or '').strip()
    if not text or len(text)>2000:return jsonify(error='invalid message'),400
    us=users(); u=next((x for x in us if x['id']==uid),None); d=udata(); arr=d.setdefault('public_messages',[])
    m={'id':next_id(arr),'user_id':uid,'username':u['username'],'text':text,'created_at':datetime.utcnow().isoformat()+'Z'}; arr.append(m); save_ud(d); return jsonify(m),201

@app.get('/messages/private/<int:other>')
@jwt_required()
def private_messages(other):
    uid=int(get_jwt_identity()); d=udata(); arr=[m for m in d.get('private_messages',[]) if {m['from_user_id'],m['to_user_id']}=={uid,other}]; return jsonify(arr[-200:])
@app.post('/messages/private/<int:other>')
@jwt_required()
def add_private(other):
    uid=int(get_jwt_identity()); b=request.get_json(silent=True) or {}; text=(b.get('text') or '').strip()
    if not text or len(text)>2000:return jsonify(error='invalid message'),400
    us=users(); u=next((x for x in us if x['id']==uid),None); d=udata(); arr=d.setdefault('private_messages',[])
    m={'id':next_id(arr),'from_user_id':uid,'from_username':u['username'],'to_user_id':other,'text':text,'created_at':datetime.utcnow().isoformat()+'Z'}; arr.append(m); save_ud(d); return jsonify(m),201

@app.post('/groups')
@jwt_required()
def create_group():
    uid=int(get_jwt_identity()); b=request.get_json(silent=True) or {}; name=(b.get('name') or '').strip(); mids=b.get('member_ids',[])
    if not name:return jsonify(error='group name is required'),400
    if not isinstance(mids,list) or not mids:return jsonify(error='at least one other member is required'),400
    valid={u['id'] for u in users()}; members=sorted(set([uid]+[int(x) for x in mids if str(x).isdigit() and int(x) in valid])); d=udata(); arr=d.setdefault('groups',[])
    g={'id':next_id(arr),'name':name[:60],'creator_id':uid,'member_ids':members,'created_at':datetime.utcnow().isoformat()+'Z'}; arr.append(g); save_ud(d); return jsonify(message='group created',group=g),201
@app.get('/groups')
@jwt_required()
def groups():
    uid=int(request.headers.get('X-Internal-User') or get_jwt_identity()); return jsonify([g for g in udata().get('groups',[]) if uid in g.get('member_ids',[])])
@app.get('/messages/group/<int:gid>')
@jwt_required()
def group_messages(gid):
    uid=int(get_jwt_identity()); d=udata(); g=next((x for x in d.get('groups',[]) if x['id']==gid),None)
    if not g:return jsonify(error='group not found'),404
    if uid not in g.get('member_ids',[]):return jsonify(error='not a member of this group'),403
    return jsonify([m for m in d.get('group_messages',[]) if m['group_id']==gid][-200:])
@app.post('/messages/group/<int:gid>')
@jwt_required()
def add_group(gid):
    uid=int(get_jwt_identity()); b=request.get_json(silent=True) or {}; text=(b.get('text') or '').strip(); d=udata(); g=next((x for x in d.get('groups',[]) if x['id']==gid),None)
    if not g or uid not in g.get('member_ids',[]):return jsonify(error='not a member of this group'),403
    if not text or len(text)>2000:return jsonify(error='invalid message'),400
    u=next(x for x in users() if x['id']==uid); arr=d.setdefault('group_messages',[]); m={'id':next_id(arr),'group_id':gid,'from_user_id':uid,'from_username':u['username'],'text':text,'created_at':datetime.utcnow().isoformat()+'Z'}; arr.append(m); save_ud(d); return jsonify(m),201


@app.post('/internal/messages/public')
def internal_public():
    b=request.get_json(silent=True) or {}; uid=int(b.get('user_id')); text=(b.get('text') or '').strip(); u=next((x for x in users() if x['id']==uid),None)
    if not u or not text or len(text)>2000:return jsonify(error='invalid message'),400
    d=udata();arr=d.setdefault('public_messages',[]);m={'id':next_id(arr),'user_id':uid,'username':u['username'],'text':text,'created_at':datetime.utcnow().isoformat()+'Z'};arr.append(m);save_ud(d);return jsonify(m),201
@app.post('/internal/messages/private')
def internal_private():
    b=request.get_json(silent=True) or {};uid=int(b.get('user_id'));other=int(b.get('other_user_id'));text=(b.get('text') or '').strip();u=next((x for x in users() if x['id']==uid),None)
    if not u or not text or len(text)>2000:return jsonify(error='invalid message'),400
    d=udata();arr=d.setdefault('private_messages',[]);m={'id':next_id(arr),'from_user_id':uid,'from_username':u['username'],'to_user_id':other,'text':text,'created_at':datetime.utcnow().isoformat()+'Z'};arr.append(m);save_ud(d);return jsonify(m),201
@app.post('/internal/messages/group')
def internal_group():
    b=request.get_json(silent=True) or {};uid=int(b.get('user_id'));gid=int(b.get('group_id'));text=(b.get('text') or '').strip();d=udata();g=next((x for x in d.get('groups',[]) if x['id']==gid),None);u=next((x for x in users() if x['id']==uid),None)
    if not g or uid not in g.get('member_ids',[]) or not u or not text or len(text)>2000:return jsonify(error='not a member or invalid message'),403
    arr=d.setdefault('group_messages',[]);m={'id':next_id(arr),'group_id':gid,'from_user_id':uid,'from_username':u['username'],'text':text,'created_at':datetime.utcnow().isoformat()+'Z'};arr.append(m);save_ud(d);return jsonify(m),201

@app.post('/stories')
@jwt_required()
def story():
    url=os.environ.get('SUPABASE_URL','').rstrip('/'); key=os.environ.get('SUPABASE_SECRET_KEY',''); bucket=os.environ.get('SUPABASE_BUCKET','Globetrotter-data')
    if not (url and key):return jsonify(error='story upload is not configured on this server'),503
    uid=int(get_jwt_identity()); u=next((x for x in users() if x['id']==uid),None)
    if not u:return jsonify(error='user not found'),404
    if 'media' not in request.files or not request.files['media'].filename:return jsonify(error='media file is required'),400
    f=request.files['media']; types={'image/jpeg':'jpg','image/png':'png','image/webp':'webp','video/mp4':'mp4','video/quicktime':'mov'}
    if f.mimetype not in types:return jsonify(error='unsupported media type'),400
    content=f.read()
    if len(content)>20*1024*1024:return jsonify(error='file too large (max 20 MB)'),400
    d=udata(); sid=next_id(d.get('stories',[])); path=f'stories/user_{uid}_story_{sid}.{types[f.mimetype]}'
    r=requests.post(f'{url}/storage/v1/object/{bucket}/{path}',headers={'apikey':key,'Authorization':f'Bearer {key}','Content-Type':f.mimetype,'x-upsert':'true'},data=content,timeout=20)
    if r.status_code not in (200,201):return jsonify(error='upload failed'),502
    s={'id':sid,'user_id':uid,'username':u['username'],'media_url':f'{url}/storage/v1/object/public/{bucket}/{path}?t={int(time.time())}','media_type':'video' if f.mimetype.startswith('video') else 'image','created_at':datetime.utcnow().isoformat()+'Z'}; d.setdefault('stories',[]).append(s); save_ud(d); return jsonify(message='story published',story=s),201
@app.get('/stories')
@jwt_required()
def stories():
    cutoff=datetime.utcnow()-timedelta(hours=24); by={}
    for s in udata().get('stories',[]):
        try: active=datetime.fromisoformat(s['created_at'].replace('Z',''))>cutoff
        except: active=False
        if active: by.setdefault(s['user_id'],{'user_id':s['user_id'],'username':s['username'],'stories':[]})['stories'].append(s)
    return jsonify(list(by.values()))

@app.get('/admin/stats')
@jwt_required()
def admin_stats():
    uid=int(get_jwt_identity()); u=next((x for x in users() if x['id']==uid),None)
    if not u or u.get('role')!='admin':return jsonify(error='admin access required'),403
    base=os.environ.get('DESTINATION_SERVICE_URL','http://127.0.0.1:5003')
    try: dest=requests.get(base+'/internal/stats',timeout=5).json()
    except Exception: dest={}
    d=udata(); its=[]
    try: its=requests.get(os.environ.get('ITINERARY_SERVICE_URL','http://127.0.0.1:5002')+'/internal/stats',timeout=5).json().get('itineraries',[])
    except Exception: pass
    us=users(); reservations=dest.get('reservations',[]); return jsonify({'totals':{'users':len(us),'destinations':dest.get('destinations_count',0),'reviews':dest.get('reviews_count',0),'itineraries':len(its),'events':dest.get('events_count',0),'services':dest.get('services_count',0),'total_views':dest.get('total_views',0),'reservations':len(reservations)},'average_rating':dest.get('average_rating'),'most_viewed_destinations':dest.get('most_viewed_destinations',[]),'recent_reviews':dest.get('recent_reviews',[]),'destinations_by_category':dest.get('destinations_by_category',{}),'recent_reservations':reservations[-20:]})

@app.get('/admin/supabase-repair')
@jwt_required()
def admin_supabase_repair():
    """Outil de secours (porte depuis le monolithe Phase 1) : diagnostique
    et tente de reparer le users.json distant sur Supabase s'il est
    corrompu (caractere de controle invalide, upload partiel...). N'ecrase
    Supabase que si la reparation aboutit a un JSON valide contenant au
    moins autant d'utilisateurs que la version locale actuelle (pour ne
    jamais perdre silencieusement des comptes)."""
    uid=int(get_jwt_identity()); u=next((x for x in users() if x['id']==uid),None)
    if not u or u.get('role')!='admin':return jsonify(error='admin access required'),403
    if not SUPABASE_STORAGE_ENABLED:
        return jsonify(error='Supabase non configure'),503

    try:
        resp=requests.get(_supabase_object_url(USERS),headers={'apikey':SUPABASE_SECRET_KEY,'Authorization':f'Bearer {SUPABASE_SECRET_KEY}'},timeout=10)
    except requests.RequestException as exc:
        return jsonify(error=f'impossible de joindre Supabase: {exc}'),502
    if resp.status_code!=200:
        return jsonify(error=f'Supabase a repondu {resp.status_code}',detail=resp.text[:500]),502

    raw=resp.content
    try:
        remote_data=__import__('json').loads(raw.decode('utf-8'))
        return jsonify(status='already_valid',message='Le fichier sur Supabase est deja un JSON valide, aucune reparation necessaire.',users_count=len(remote_data.get('users',[]))),200
    except (ValueError,UnicodeDecodeError) as first_error:
        pass

    try:
        text=raw.decode('utf-8',errors='replace')
    except Exception as exc:
        return jsonify(error=f'decodage impossible: {exc}'),500

    cleaned=''.join(ch for ch in text if ch in ('\n','\r','\t') or ord(ch)>=0x20)
    try:
        repaired_data=__import__('json').loads(cleaned)
    except ValueError as second_error:
        return jsonify(status='repair_failed',message="Le fichier distant est corrompu et n'a pas pu etre repare automatiquement.",first_error=str(first_error),error_after_cleanup=str(second_error),hint='Contacter le support technique avec ce message pour une reparation manuelle.'),500

    local_users=len(users())
    repaired_users=len(repaired_data.get('users',[]))
    if repaired_users<local_users:
        return jsonify(status='repair_rejected',message=f'La version reparee ne contient que {repaired_users} utilisateur(s) contre {local_users} dans la copie locale actuelle. Reparation annulee par securite pour ne pas perdre de comptes.'),409

    save_users(repaired_data.get('users',[]))
    _supabase_upload_from_disk(USERS)
    return jsonify(status='repaired',message=f'Fichier repare avec succes et renvoye vers Supabase. {repaired_users} utilisateur(s) recuperes.',users=[x.get('username') for x in repaired_data.get('users',[])]),200

if __name__=='__main__': app.run(host='0.0.0.0',port=int(os.environ.get('PORT',5001)),debug=True)
