# Kribi Tour — Phase 1: The Monolith (Kribi Edition)

A single Flask server handling all requests, with data stored in a JSON file
(`data.json`). This is the monolithic baseline for the Kribi Tour capstone
project: a travel discovery app focused exclusively on **Kribi**, Cameroon.
No database, no microservices, single point of failure by design — this is
intentional for Phase 1, which serves as a baseline for comparison with the
later phases (microservices, cloud deployment, resilience).

> **Scope note:** earlier iterations of this project covered multiple
> Cameroonian cities (Douala, Yaoundé, Limbé, Bafoussam, Bamenda,
> Ngaoundéré). Per course guidance, the project now focuses on **Kribi
> only**, so all other cities and their destinations have been removed.

## Coverage

The app currently covers **25 destinations and addresses in Kribi**, across
five categories: Site historique (historical site), Nature, Distraction,
Restaurant and Hôtel. Each destination can be explored via search, category
filters, tag filters, an interactive map, a transport price comparator, and
a full detail page (with live weather, seasonal budget, and user reviews).

## Architecture

```
Client (HTML/CSS/JS) --> Flask API Layer --> Business Logic --> data.json
                                          \--> External APIs (Wikimedia
                                               Commons, Pexels, Open-Meteo)
```

- **API Layer**: REST endpoints for registration, login, destination search,
  destination detail, reviews, recommendations, itinerary management,
  photo lookup, and weather lookup.
- **Business Logic**: recommendation matching based on user preferences;
  seasonal budget adjustment; distance-based transport price estimation.
- **Data Access**: `load_data()` / `save_data()` read and write `data.json`.
- **Authentication**: JWT via Flask-JWT-Extended.
- **Images**: destination photos are resolved in this order — (1) a local
  image manually placed in `static/images/<id>.jpg`, (2) Wikimedia Commons
  search, (3) Pexels search (requires a free `PEXELS_API_KEY`), (4) a
  generic category icon if nothing is found.

## Endpoints

| Method | Path                                      | Auth | Description                                |
|--------|-------------------------------------------|------|---------------------------------------------|
| POST   | `/register`                                | No   | Register a new user                         |
| POST   | `/login`                                   | No   | Authenticate, returns a JWT token           |
| GET    | `/destinations`                            | No   | Search destinations (`?q=` `&tag=` `&category=`) |
| GET    | `/destinations/<id>`                       | No   | Get full details for a single destination   |
| GET    | `/destinations/<id>/reviews`               | No   | List reviews (rating + comment) for a destination |
| POST   | `/destinations/<id>/reviews`               | No   | Submit a review (rating + comment)          |
| GET    | `/recommendations`                         | Yes  | Personalized recommendations                |
| POST   | `/itineraries`                             | Yes  | Create a new itinerary                      |
| GET    | `/itineraries`                             | Yes  | List the current user's itineraries         |
| GET    | `/api/photo?q=&fallback=`                  | No   | Resolve a photo URL (Wikimedia → Pexels)    |
| GET    | `/api/weather?lat=&lng=`                   | No   | Current weather + 4-day forecast (Open-Meteo) |

## Pages

| Route                        | Description                                      |
|-------------------------------|---------------------------------------------------|
| `/`                            | Home page                                          |
| `/register-page`               | Registration form                                  |
| `/login-page`                  | Login form                                         |
| `/destinations-page`           | Search, filter and browse all Kribi destinations   |
| `/destination/<id>`             | Full detail page: description, weather, seasonal budget, transport, reviews |
| `/map-page`                     | Interactive map (Leaflet + OpenStreetMap) with departure-point distance/price estimator |
| `/transport-page`               | Moto vs. voiture price comparator for every destination |
| `/itineraries-page`             | View and create itineraries                        |

## Recent updates

- **Map routing**: the departure → destination line on `/map-page` now
  follows real roads (via the free OSRM public routing service) instead of
  a straight line, with the moto/car price estimate based on the actual
  road distance. Falls back to the previous straight-line estimate if the
  routing service is unavailable.
- **Satellite view by default**: `/map-page` now opens in satellite view;
  the toggle button switches to the standard OpenStreetMap view.
- **"Le saviez-vous ?" page** (formerly "Découvrir Kribi"): renamed to match
  the navigation menu, and the hand-drawn Cameroon outline was replaced with
  a real map image (`static/images/cameroon-map.png`).
- **Itinerary sharing**: itineraries can now be shared via a public link
  (`/itinerary/shared/<token>`), viewable without an account. Generate a
  link from the "🔗 Partager" button on `/itineraries-page`; each itinerary
  gets a unique, non-guessable share token stored in `data.json`.
- **Home page**: hero background is now a photo of Kribi's port instead of
  a color gradient, and the 3-number stats strip (lieux/catégories/transport)
  was removed.
- **Category fallback images**: destinations without a photo now show a
  real photo for their category (Hôtels, Restaurants, Activités, Loisirs,
  Excursions) instead of a plain color gradient; remaining categories still
  use the gradient until images are provided.
- **Welcome overlay**: the first-load welcome screen now shows an aerial
  photo of Kribi instead of a color gradient.
- **Mobile navigation drawer**: redesigned as a left-side, translucent/blurred
  drawer with a profile header (avatar + username), icons next to each link,
  a highlighted active link, and a distinct logout button — closer to a
  native app menu.



```bash
cd globetrotter-monolith
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Then open **http://127.0.0.1:5000** in your browser.

Demo account: username `demo`, password `demo123`.

### Optional: enabling real photos

Copy `.env.example` to `.env` and add a free Pexels API key
(https://www.pexels.com/api/) to enable the Pexels fallback. Wikimedia
Commons lookup works with no key at all. You can also drop your own images
directly into `static/images/`, named after each destination's numeric id
(e.g. `static/images/6.jpg`) — local images always take priority over both
APIs.

## Testing the API directly (optional, e.g. with curl or Postman)

```bash
# Register
curl -X POST http://127.0.0.1:5000/register \
  -H "Content-Type: application/json" \
  -d '{"username":"sheilla","password":"pass123","preferences":["beach"]}'

# Login
curl -X POST http://127.0.0.1:5000/login \
  -H "Content-Type: application/json" \
  -d '{"username":"sheilla","password":"pass123"}'
# -> copy the "access_token" from the response

# Recommendations (replace TOKEN)
curl http://127.0.0.1:5000/recommendations \
  -H "Authorization: Bearer TOKEN"

# Single destination detail
curl http://127.0.0.1:5000/destinations/1
```

## Deploying to Render (free tier)

1. Push this folder to a GitHub repository.
2. Go to https://render.com, sign in with GitHub.
3. Click **New +** → **Web Service**, select your repo.
4. Configure:
   - **Runtime**: Python 3
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn app:app`
5. Add environment variables: `JWT_SECRET_KEY` (any secret value) and,
   optionally, `PEXELS_API_KEY`.
6. Click **Create Web Service**. Render will build and deploy automatically,
   giving you a public URL like `https://globetrotter-monolith.onrender.com`.

Note: Render's free tier uses an ephemeral filesystem — `data.json` resets
whenever the service restarts/redeploys. That's fine for a Phase 1 demo, but
mention it explicitly during your defense as one of the "Challenges of the
Monolith" (Data Storage row in the course slides).

## Known limitations (by design — this is Phase 1)

- No real database (matches the "Data Storage" challenge in the slides).
- Single server, no horizontal scaling.
- Any bug can crash the whole app (no service isolation).
- Passwords are stored in plain text in `data.json` — acceptable only for
  this teaching exercise, never in production.

## Roadmap (future phases, not part of Phase 1)

- Phase 2 — Microservices: split into User, Itinerary and Recommendation services.
- Phase 3 — Cloud Deployment: containerization, load balancing, auto-scaling.
- Phase 4 — Resilience: caching, message queues, circuit breakers, fault tolerance.
