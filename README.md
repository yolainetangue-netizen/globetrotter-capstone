# GlobeTrotter — Phase 2 Microservices

Cette version conserve les modifications et le frontend de la Phase 1 tout en séparant le backend en microservices.

## Architecture
- Gateway : `5000` — frontend + point d'entrée unique REST + Socket.IO
- User Service : `5001` — utilisateurs, authentification, messagerie, groupes, stories
- Itinerary Service : `5002` — itinéraires, partage public, PDF, activité
- Destination Service : `5003` — destinations, avis, événements, services, réservations
- Recommendation Service : `5004` — recommandations personnalisées

Les trois bases JSON principales sont séparées : `users.json`, `itinerary_data.json`, `destination_data.json`; les données sociales sont dans `user_data.json`. Les 77 destinations et les données Phase 1 sont conservées.

## Lancer
1. `python -m venv venv` puis activation.
2. `pip install -r requirements.txt`
3. Copier `.env.example` vers `.env` et renseigner les secrets si nécessaire.
4. Ouvrir cinq terminaux et lancer :

```bash
python user-service/app.py
python itinerary-service/app.py
python destination-service/app.py
python recommendation-service/app.py
python gateway/app.py
```

5. Ouvrir `http://127.0.0.1:5000`.

## Correspondance avec le cours
Client → API Gateway → User / Itinerary / Recommendation. Le Destination Service fournit le catalogue et est utilisé par Itinerary et Recommendation. Les communications inter-services sont REST/HTTP. Docker/Kubernetes restent pour la Phase 3.


## Lancer la Phase 2 avec Docker

Cette version conserve les fonctionnalités de la Phase 1 et sépare l'application en 5 services :
Gateway, User, Itinerary, Destination et Recommendation.

### 1. Prérequis
Installer Docker Desktop.

### 2. Démarrer le projet
Ouvrir un terminal dans le dossier contenant `docker-compose.yml`, puis lancer :

```bash
docker compose build
docker compose up
```

Ensuite ouvrir dans le navigateur :

`http://localhost:5000`

### 3. Arrêter le projet
Dans le terminal : `Ctrl + C`

Ou :

```bash
docker compose down
```

### 4. GitHub
Après avoir vérifié que le projet fonctionne :

```bash
git init
git add .
git commit -m "Phase 2 microservices Docker"
git branch -M main
git remote add origin https://github.com/TON-UTILISATEUR/TON-REPO.git
git push -u origin main
```

Ne jamais envoyer le fichier `.env` sur GitHub. Le fichier `.env.example` peut être partagé.
