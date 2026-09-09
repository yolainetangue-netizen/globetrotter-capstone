# GlobeTrotter — Phase 2 mise à jour

Cette version conserve l'architecture microservices de la Phase 2 et
réintègre les évolutions fonctionnelles et visuelles présentes dans la
Phase 1, **à l'exception de l'espace Discussion et des messages privés**.

## Ce qui a été reporté depuis la Phase 1

- interface Kribi Tour complète : accueil, lieux/destinations, détail d'un lieu,
  catégories, carte, événements, services utiles, favoris, profil,
  réservations et itinéraires ;
- nouvelle navigation/navbar, responsive mobile, bouton urgence et raccourci carte ;
- thème et styles actuels de la Phase 1 ;
- bascule FR/EN de l'interface ;
- recherche/filtres et recommandations ;
- descriptions enrichies et données actuelles des destinations (77 lieux) ;
- images et médias locaux de la Phase 1 ;
- avis sur les destinations ;
- événements et services utiles ;
- réservations ;
- itinéraires, partage public, téléchargement PDF et activité du profil ;
- authentification JWT et rôle administrateur.

### Explicitement non reporté

Les pages et fonctionnalités **Discussion**, **Messages privés** et leur logique
Socket.IO ne sont pas incluses dans cette version.

## Architecture

```text
Navigateur
    │
    ▼
Frontend (8080) ──► API Gateway (5000)
                         │
             ┌───────────┼──────────────┐
             ▼           ▼              ▼
        User Service  Itinerary    Recommendation
          (5001)       (5002)          (5003)
             │           │              │
             │           └── RabbitMQ ──┘
             │                │
             │                ▼
             │          Event Consumer
```

Le frontend ne contient pas de logique métier : il sert l'interface de la
Phase 1 et relaie les appels API vers l'API Gateway. Les données métier restent
dans les microservices.

## Lancer

Prérequis : Docker Desktop.

```bash
cd globetrotter-phase2-updated
docker-compose up --build
```

- Interface web : http://localhost:8080
- API Gateway : http://localhost:5000
- RabbitMQ : http://localhost:15672 (guest / guest)

Pour les photos dynamiques, définir `PEXELS_API_KEY` dans l'environnement.
La météo utilise Open-Meteo sans clé.

## Compte de démonstration

- utilisateur : `demo`
- mot de passe : `demo123`

Un second compte administrateur est conservé dans les données de la Phase 1.

## Vérification rapide

1. Ouvrir `http://localhost:8080`.
2. Se connecter avec `demo / demo123`.
3. Tester Lieux, Carte, Événements, Services utiles, Profil et Itinéraires.
4. Créer un itinéraire : la vérification de destination passe par le
   Recommendation Service et l'événement `itinerary.created` est publié via RabbitMQ.
5. Pour vérifier le consommateur :
```bash
docker-compose exec event-consumer cat events.log
```

## Chat

The project now includes only the chat module from the reference project: a public Community room and private 1-to-1 messages, with Socket.IO realtime updates. Chat data is isolated in `chat-service/data.json` and user lookup/search remains owned by `user-service`.

For local Docker, open `http://localhost:8080/chat-page`; Socket.IO connects to `http://localhost:5004`.
