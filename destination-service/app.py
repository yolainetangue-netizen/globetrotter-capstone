import os,time,math,requests
from datetime import datetime
from flask import Flask,jsonify,request
from flask_jwt_extended import JWTManager
from dotenv import load_dotenv
from common import load_json,save_json,next_id
load_dotenv(); app=Flask(__name__); app.config['JWT_SECRET_KEY']=os.environ.get('JWT_SECRET_KEY','globetrotter-dev-secret'); JWTManager(app)
DATA='destination_data.json'; IMG_DIR=os.path.join(os.path.dirname(__file__),'..','static','images')
def data(): return load_json(DATA,{'destinations':[],'reviews':[],'events':[],'services':[],'reservations':[]})
def save(d): save_json(DATA,d)
def img(i,prefix=''):
    for ext in ('.jpg','.jpeg','.png','.webp'):
        if os.path.isfile(os.path.join(IMG_DIR,f'{prefix}{i}{ext}')): return f'/static/images/{prefix}{i}{ext}'
    return None
def attach(d): x=dict(d); x['local_image']=img(d['id']); return x

def hav(a,b,c,d):
    r=6371.; x=math.radians(c-a); y=math.radians(d-b); z=math.sin(x/2)**2+math.cos(math.radians(a))*math.cos(math.radians(c))*math.sin(y/2)**2; return r*2*math.atan2(math.sqrt(z),math.sqrt(1-z))

@app.get('/destinations')
def destinations():
    d=data(); arr=d['destinations']; q=request.args.get('q','').strip().lower(); tag=request.args.get('tag','').strip().lower(); cat=request.args.get('category','').strip().lower(); city=request.args.get('city','').strip().lower()
    if q:arr=[x for x in arr if q in x['name'].lower() or q in x.get('country','').lower()]
    if tag:arr=[x for x in arr if tag in [t.lower() for t in x.get('tags',[])]]
    if cat:arr=[x for x in arr if cat==x.get('category','').lower()]
    if city:arr=[x for x in arr if city==x.get('city','').lower()]
    return jsonify([attach(x) for x in arr])
@app.get('/internal/destinations')
def internal_destinations(): return jsonify([attach(x) for x in data()['destinations']])
@app.get('/internal/destinations/<int:did>')
def internal_destination(did):
    x=next((x for x in data()['destinations'] if x['id']==did),None)
    return (jsonify(error='destination not found'),404) if not x else jsonify(attach(x))

@app.get('/destinations/<int:did>')
def destination(did):
    d=data(); x=next((x for x in d['destinations'] if x['id']==did),None)
    if not x:return jsonify(error='destination not found'),404
    x['views']=x.get('views',0)+1; save(d); return jsonify(attach(x))
@app.get('/destinations/<int:did>/reviews')
def reviews(did):
    d=data()
    if not any(x['id']==did for x in d['destinations']):return jsonify(error='destination not found'),404
    arr=sorted([r for r in d.get('reviews',[]) if r['destination_id']==did],key=lambda r:r['date'],reverse=True); avg=round(sum(r['rating'] for r in arr)/len(arr),1) if arr else None; return jsonify(reviews=arr,average=avg,count=len(arr))
@app.post('/destinations/<int:did>/reviews')
def add_review(did):
    d=data()
    if not any(x['id']==did for x in d['destinations']):return jsonify(error='destination not found'),404
    body=request.form if request.content_type and 'multipart/form-data' in request.content_type else (request.get_json(silent=True) or {})
    author=(body.get('author') or '').strip() or 'Visiteur anonyme'; comment=(body.get('comment') or '').strip()
    try:r=int(body.get('rating'))
    except:return jsonify(error='rating must be an integer between 1 and 5'),400
    if not 1<=r<=5:return jsonify(error='rating must be between 1 and 5'),400
    if not comment:return jsonify(error='comment is required'),400
    rid=next_id(d.get('reviews',[])); photo=None
    if 'photo' in request.files and request.files['photo'].filename:
        url=os.environ.get('SUPABASE_URL','').rstrip('/'); key=os.environ.get('SUPABASE_SECRET_KEY',''); bucket=os.environ.get('SUPABASE_BUCKET','Globetrotter-data'); f=request.files['photo']; types={'image/jpeg':'jpg','image/png':'png','image/webp':'webp'}
        if url and key and f.mimetype in types:
            c=f.read()
            if len(c)<=5*1024*1024:
                path=f'reviews/destination_{did}_review_{rid}.{types[f.mimetype]}'; rr=requests.post(f'{url}/storage/v1/object/{bucket}/{path}',headers={'apikey':key,'Authorization':f'Bearer {key}','Content-Type':f.mimetype,'x-upsert':'true'},data=c,timeout=15)
                if rr.status_code in (200,201):photo=f'{url}/storage/v1/object/public/{bucket}/{path}?t={int(time.time())}'
    rev={'id':rid,'destination_id':did,'author':author[:60],'rating':r,'comment':comment[:1000],'photo_url':photo,'date':datetime.utcnow().isoformat()+'Z'}; d.setdefault('reviews',[]).append(rev); save(d); return jsonify(message='review added',review=rev),201
@app.get('/events')
def events():
    d=data(); arr=d.get('events',[])
    if request.args.get('upcoming','').lower()=='true':
        today=datetime.utcnow().strftime('%Y-%m-%d'); arr=[e for e in arr if (e.get('end_date') or e.get('date'))>=today]
    arr=sorted(arr,key=lambda e:e['date']); return jsonify([{**e,'local_image':img(e['id'],'event-')} for e in arr])
@app.get('/services')
def services():
    arr=data().get('services',[]); typ=request.args.get('type','').strip().lower()
    if typ:arr=[s for s in arr if s.get('type','').lower()==typ]
    out=[]
    for s in arr:
        x=dict(s); x['distance_km']=round(hav(2.9464,9.9074,s['lat'],s['lng']),2); out.append(x)
    out.sort(key=lambda x:x['distance_km']); return jsonify(out)
@app.post('/reservations')
def reservation():
    b=request.get_json(silent=True) or {}; did=b.get('destination_id'); name=(b.get('guest_name') or '').strip(); date=(b.get('date') or '').strip(); tm=(b.get('time') or '').strip(); ps=b.get('party_size'); note=(b.get('note') or '').strip()
    if not did or not name or not date or not tm or not ps:return jsonify(error='destination_id, guest_name, date, time et party_size sont requis'),400
    try:ps=int(ps); assert ps>=1
    except:return jsonify(error='party_size doit etre un nombre entier positif'),400
    d=data(); dest=next((x for x in d['destinations'] if x['id']==did),None)
    if not dest:return jsonify(error='destination not found'),404
    if dest.get('category') not in {'Hôtels','Restaurants'}:return jsonify(error='les reservations ne sont disponibles que pour les hotels et restaurants'),400
    uid=None
    from flask_jwt_extended import verify_jwt_in_request,get_jwt_identity
    try:verify_jwt_in_request(optional=True); ident=get_jwt_identity(); uid=int(ident) if ident else None
    except:pass
    arr=d.setdefault('reservations',[]); r={'id':next_id(arr),'destination_id':did,'destination_name':dest['name'],'user_id':uid,'guest_name':name,'date':date,'time':tm,'party_size':ps,'note':note,'status':'pending','created_at':datetime.utcnow().isoformat()+'Z'}; arr.append(r); save(d); return jsonify(r),201
@app.get('/reservations')
def my_reservations():
    from flask_jwt_extended import jwt_required,get_jwt_identity
    # Decorator applied dynamically is unnecessary; enforce token here.
    from flask_jwt_extended import verify_jwt_in_request
    try:verify_jwt_in_request(); uid=int(get_jwt_identity())
    except:return jsonify(msg='Missing Authorization Header'),401
    arr=[r for r in data().get('reservations',[]) if r.get('user_id')==uid]; arr.sort(key=lambda x:x['created_at'],reverse=True); return jsonify(arr)
@app.get('/internal/stats')
def internal_stats():
    d=data(); ds=d['destinations']; rev=d.get('reviews',[]); ratings=[r['rating'] for r in rev]; by={}
    for x in ds:by[x.get('category','Autres')]=by.get(x.get('category','Autres'),0)+1
    destmap={x['id']:x['name'] for x in ds}; recent=sorted(rev,key=lambda r:r['date'],reverse=True)[:10]
    return jsonify(destinations_count=len(ds),reviews_count=len(rev),events_count=len(d.get('events',[])),services_count=len(d.get('services',[])),total_views=sum(x.get('views',0) for x in ds),average_rating=round(sum(ratings)/len(ratings),2) if ratings else None,most_viewed_destinations=[{'id':x['id'],'name':x['name'],'category':x.get('category'),'views':x.get('views',0)} for x in sorted(ds,key=lambda x:x.get('views',0),reverse=True)[:10] if x.get('views',0)>0],recent_reviews=[{**r,'destination_name':destmap.get(r['destination_id'],'?')} for r in recent],destinations_by_category=by,reservations=d.get('reservations',[]))

if __name__=='__main__':app.run(host='0.0.0.0',port=int(os.environ.get('PORT',5003)),debug=True)
