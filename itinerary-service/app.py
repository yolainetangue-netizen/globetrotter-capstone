import os,io,secrets,requests
from datetime import datetime
from flask import Flask,jsonify,request,send_file
from flask_jwt_extended import JWTManager,jwt_required,get_jwt_identity
from dotenv import load_dotenv
from common import load_json,save_json,next_id
load_dotenv(); app=Flask(__name__); app.config['JWT_SECRET_KEY']=os.environ.get('JWT_SECRET_KEY','globetrotter-dev-secret'); JWTManager(app)
DATA='itinerary_data.json'; DEST=os.environ.get('DESTINATION_SERVICE_URL','http://127.0.0.1:5003')
def data():return load_json(DATA,{'itineraries':[],'pdf_downloads':[]})
def save(d):save_json(DATA,d)
@app.post('/itineraries')
@jwt_required()
def create():
    uid=int(get_jwt_identity()); b=request.get_json(silent=True) or {}; title=(b.get('title') or '').strip(); did=b.get('destination_id')
    if not title or did is None:return jsonify(error='title and destination_id are required'),400
    try:r=requests.get(f'{DEST}/internal/destinations/{int(did)}',timeout=5)
    except requests.RequestException:return jsonify(error='destination service unavailable'),503
    if r.status_code!=200:return jsonify(error='destination_id does not exist'),400
    d=data(); arr=d['itineraries']; it={'id':next_id(arr),'user_id':uid,'title':title,'destination_id':did,'start_date':b.get('start_date',''),'end_date':b.get('end_date',''),'notes':b.get('notes','')}; arr.append(it); save(d); return jsonify(message='itinerary created',itinerary=it),201
@app.get('/itineraries')
@jwt_required()
def list_it():uid=int(get_jwt_identity());return jsonify([x for x in data()['itineraries'] if x['user_id']==uid])
def pdf(it,dest):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet,ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Table,TableStyle,HRFlowable
    buf=io.BytesIO(); doc=SimpleDocTemplate(buf,pagesize=A4,topMargin=2*cm,bottomMargin=2*cm,leftMargin=2*cm,rightMargin=2*cm); st=getSampleStyleSheet(); title=ParagraphStyle('GTTitle',parent=st['Title'],fontSize=22,textColor=colors.HexColor('#0e3a5c')); head=ParagraphStyle('GTHead',parent=st['Heading2'],fontSize=13,spaceBefore=14,spaceAfter=6,textColor=colors.HexColor('#0e3a5c')); normal=ParagraphStyle('GTNormal',parent=st['Normal'],fontSize=10.5,leading=15); muted=ParagraphStyle('GTMuted',parent=st['Normal'],fontSize=9,textColor=colors.grey)
    story=[Paragraph('Kribi Tour',muted),Paragraph(it.get('title') or 'Mon itineraire',title),Spacer(1,4),HRFlowable(width='100%',color=colors.HexColor('#0e3a5c'),thickness=1),Spacer(1,10)]
    name=dest['name'] if dest else f"Destination #{it.get('destination_id')}"; cat=dest.get('category','') if dest else ''
    story += [Paragraph('Destination',head),Paragraph(f'<b>{name}</b>'+ (f' &nbsp;&nbsp;<font color="grey">({cat})</font>' if cat else ''),normal)]
    if dest and dest.get('description'):story += [Spacer(1,4),Paragraph(dest['description'],normal)]
    story += [Paragraph('Dates du sejour',head),Table([['Depart',it.get('start_date') or 'Non precise'],['Retour',it.get('end_date') or 'Non precise']],colWidths=[4*cm,10*cm])]
    if it.get('notes'):story += [Paragraph('Notes personnelles',head),Paragraph(it['notes'],normal)]
    if dest:
        if dest.get('budget'):story += [Paragraph('Budget indicatif',head),Paragraph(dest['budget'],normal)]
        tr=dest.get('transport')
        if tr:
            story.append(Paragraph('Transport',head))
            if isinstance(tr,dict):
                for lab,k in [('À pied','walk'),('Moto','moto'),('Voiture','taxi')]:
                    if tr.get(k):story.append(Paragraph(f'<b>{lab} :</b> {tr[k]}',normal))
                if tr.get('note'):story.append(Paragraph(f"<i>{tr['note']}</i>",muted))
            else:story.append(Paragraph(str(tr),normal))
        if dest.get('contact'):story += [Paragraph('Contact',head),Paragraph(dest['contact'],normal)]
        practical=dest.get('practical_info') or {}
        for lab,k in [('Horaires','hours'),('Meilleure periode','best_time'),('Acces','access')]:
            if practical.get(k):story += [Paragraph('Informations pratiques',head),Paragraph(f'<b>{lab} :</b> {practical[k]}',normal)]
    story += [Spacer(1,20),HRFlowable(width='100%',color=colors.HexColor('#cccccc'),thickness=.5),Spacer(1,6),Paragraph(f"Genere le {datetime.utcnow().strftime('%d/%m/%Y')} depuis Kribi Tour. Document telechargeable, consultable sans connexion internet.",muted)]
    doc.build(story);buf.seek(0);return buf
@app.get('/itineraries/<int:iid>/download')
@jwt_required()
def download(iid):
    uid=int(get_jwt_identity()); d=data(); it=next((x for x in d['itineraries'] if x['id']==iid),None)
    if not it:return jsonify(error='itinerary not found'),404
    if it['user_id']!=uid:return jsonify(error='not authorized to access this itinerary'),403
    try:r=requests.get(f"{DEST}/internal/destinations/{it['destination_id']}",timeout=5); dest=r.json() if r.status_code==200 else None
    except:dest=None
    arr=d.setdefault('pdf_downloads',[]); arr.append({'id':next_id(arr),'user_id':uid,'itinerary_id':iid,'itinerary_title':it.get('title') or 'itineraire','downloaded_at':datetime.utcnow().isoformat()+'Z'});save(d)
    fn=''.join(c if c.isalnum() or c in ' -_' else '' for c in (it.get('title') or 'itineraire')).strip() or 'itineraire';return send_file(pdf(it,dest),mimetype='application/pdf',as_attachment=True,download_name=f'{fn}.pdf')
@app.post('/itineraries/<int:iid>/share')
@jwt_required()
def share(iid):
    uid=int(get_jwt_identity());d=data();it=next((x for x in d['itineraries'] if x['id']==iid),None)
    if not it:return jsonify(error='itinerary not found'),404
    if it['user_id']!=uid:return jsonify(error='not authorized to access this itinerary'),403
    if not it.get('share_token'):it['share_token']=secrets.token_urlsafe(16);save(d)
    return jsonify(share_token=it['share_token'])
@app.get('/itineraries/public/<token>')
def public(token):
    d=data();it=next((x for x in d['itineraries'] if x.get('share_token')==token),None)
    if not it:return jsonify(error='shared itinerary not found'),404
    try:r=requests.get(f"{DEST}/internal/destinations/{it['destination_id']}",timeout=5);dest=r.json() if r.status_code==200 else None
    except:dest=None
    return jsonify(title=it.get('title'),start_date=it.get('start_date'),end_date=it.get('end_date'),notes=it.get('notes'),destination=dest)
@app.get('/me/activity')
@jwt_required()
def activity():
    uid=int(get_jwt_identity());d=data();its=[x for x in d['itineraries'] if x.get('user_id')==uid];downs=[x for x in d.get('pdf_downloads',[]) if x.get('user_id')==uid];downs.sort(key=lambda x:x['downloaded_at'],reverse=True);
    try: reservations=requests.get(f'{DEST}/reservations',headers={'Authorization':request.headers.get('Authorization','')},timeout=5).json()
    except: reservations=[]
    return jsonify(itineraries_count=len(its),reservations_count=len(reservations),pdf_downloads=downs[:10],pdf_downloads_count=len(downs))
@app.get('/internal/stats')
def stats():return jsonify(itineraries=data()['itineraries'])
if __name__=='__main__':app.run(host='0.0.0.0',port=int(os.environ.get('PORT',5002)),debug=True)
