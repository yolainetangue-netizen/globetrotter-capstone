# Déploiement Render – GlobeTrotter Phase 2

## Conserver l'URL de la Phase 1

Le service Render existant qui sert le frontend doit être conservé. Il peut continuer à utiliser la même URL :
`https://globetrotter-monolith.onrender.com`

Dans Render, modifier le repository GitHub du service existant vers le nouveau repository, puis utiliser le dossier `frontend` comme **Root Directory**.

### Service frontend existant
- Root Directory: `frontend`
- Build Command: `pip install -r requirements.txt`
- Start Command: `gunicorn --bind 0.0.0.0:$PORT --workers 2 app:app`
- Variable: `API_GATEWAY_URL=<URL publique du service api-gateway>`
- Optionnel: `PEXELS_API_KEY`, `GOOGLE_CLIENT_ID`

Ne pas supprimer/recréer ce Web Service : modifier sa source conserve son URL Render.

## Microservices

Créer/configurer séparément les services backend suivants sur Render :
- `api-gateway`
- `user-service`
- `recommendation-service`
- `itinerary-service`

Chaque service utilise son propre dossier comme Root Directory et sa commande Gunicorn correspondante.

Variables principales :

### api-gateway
- `USER_SERVICE_URL=<URL publique user-service>`
- `RECOMMENDATION_SERVICE_URL=<URL publique recommendation-service>`
- `ITINERARY_SERVICE_URL=<URL publique itinerary-service>`

### user-service
- `JWT_SECRET_KEY=<même secret que les autres services>`
- `GOOGLE_CLIENT_ID=<ID client Google si Google Sign-In est utilisé>`
- `SUPABASE_URL`, `SUPABASE_SECRET_KEY`, `SUPABASE_BUCKET` si l'upload d'avatar doit être persistant

### recommendation-service
- `USER_SERVICE_URL=<URL publique user-service>`
- `JWT_SECRET_KEY=<même secret>`

### itinerary-service
- `RECOMMENDATION_SERVICE_URL=<URL publique recommendation-service>`
- `JWT_SECRET_KEY=<même secret>`
- `RABBITMQ_HOST=<hôte RabbitMQ>`

## RabbitMQ

`docker-compose.yml` est prévu pour un environnement local. Sur Render, RabbitMQ doit être fourni par une instance/service compatible AMQP accessible par `itinerary-service` et `event-consumer`.

## Important

La discussion, les messages privés, les groupes et les stories de la Phase 1 ne sont pas réintroduits dans cette Phase 2.
