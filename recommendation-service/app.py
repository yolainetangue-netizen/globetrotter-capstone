import os,requests
from flask import Flask,jsonify
from flask_jwt_extended import JWTManager,jwt_required,get_jwt_identity
from dotenv import load_dotenv
load_dotenv();app=Flask(__name__);app.config['JWT_SECRET_KEY']=os.environ.get('JWT_SECRET_KEY','globetrotter-dev-secret');JWTManager(app)
USER=os.environ.get('USER_SERVICE_URL','http://127.0.0.1:5001');DEST=os.environ.get('DESTINATION_SERVICE_URL','http://127.0.0.1:5003')
@app.get('/recommendations')
@jwt_required()
def rec():
    uid=int(get_jwt_identity())
    try:u=requests.get(f'{USER}/internal/users/{uid}',timeout=5).json(); ds=requests.get(f'{DEST}/internal/destinations',timeout=5).json()
    except requests.RequestException:return jsonify(error='dependent service unavailable'),503
    prefs={str(x).lower() for x in u.get('preferences',[])}
    if not prefs:return jsonify(ds)
    return jsonify([d for d in ds if prefs.intersection(str(t).lower() for t in d.get('tags',[]))])
if __name__=='__main__':app.run(host='0.0.0.0',port=int(os.environ.get('PORT',5004)),debug=True)
