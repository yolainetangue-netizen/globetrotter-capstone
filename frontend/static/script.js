// Shared helpers for all pages of the Kribi Tour monolith frontend

// ---------------------------------------------------------------------
// Traduction de l'interface (FR / EN)
// Ne traduit que les elements d'interface (menus, boutons, formulaires),
// pas le contenu des destinations qui reste en francais pour l'instant.
// ---------------------------------------------------------------------
const GT_TRANSLATIONS = {
  fr: {
    "nav.home": "Accueil",
    "nav.kribi": "Le saviez-vous ?",
    "nav.destinations": "Lieux",
    "nav.services": "Services utiles",
    "nav.map": "Carte",
    "nav.create_itinerary": "➕ Créer un itinéraire",
    "nav.itineraries": "Mes itinéraires",
    "nav.profile": "👤 Profil",
    "nav.login": "Connexion",
    "nav.logout": "Déconnexion",
  },
  en: {
    "nav.home": "Home",
    "nav.kribi": "Did you know?",
    "nav.destinations": "Places",
    "nav.services": "Useful services",
    "nav.map": "Map",
    "nav.create_itinerary": "➕ Create an itinerary",
    "nav.itineraries": "My itineraries",
    "nav.profile": "👤 Profile",
    "nav.login": "Log in",
    "nav.logout": "Log out",
  },
};

function getLang() {
  return localStorage.getItem("gt_lang") || "fr";
}

function setLang(lang) {
  localStorage.setItem("gt_lang", lang);
}

// Traduit une cle i18n dans la langue courante (retourne la cle si absente)
function t(key) {
  const lang = getLang();
  return (GT_TRANSLATIONS[lang] && GT_TRANSLATIONS[lang][key]) || GT_TRANSLATIONS.fr[key] || key;
}

// Applique les traductions a tous les elements [data-i18n] du document
function applyTranslations() {
  document.querySelectorAll("[data-i18n]").forEach((el) => {
    el.textContent = t(el.dataset.i18n);
  });
  document.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
    el.setAttribute("placeholder", t(el.dataset.i18nPlaceholder));
  });
  document.documentElement.setAttribute("lang", getLang());
}

// "Se souvenir de moi" coche -> localStorage (persiste apres fermeture du navigateur)
// decoche -> sessionStorage (efface a la fermeture de l'onglet/navigateur)
function getToken() {
  return localStorage.getItem("gt_token") || sessionStorage.getItem("gt_token");
}

function setToken(token, remember = true) {
  if (remember) {
    localStorage.setItem("gt_token", token);
    sessionStorage.removeItem("gt_token");
  } else {
    sessionStorage.setItem("gt_token", token);
    localStorage.removeItem("gt_token");
  }
}

function clearToken() {
  localStorage.removeItem("gt_token");
  sessionStorage.removeItem("gt_token");
}

function isLoggedIn() {
  return !!getToken();
}

// ---------------------------------------------------------------------------
// Favoris (aucune connexion requise, stockage local navigateur)
// ---------------------------------------------------------------------------
const FAVORITES_KEY = "gt_favorites";

function getFavorites() {
  try {
    return JSON.parse(localStorage.getItem(FAVORITES_KEY) || "[]");
  } catch {
    return [];
  }
}

function isFavorite(destinationId) {
  return getFavorites().includes(destinationId);
}

function toggleFavorite(destinationId) {
  let favs = getFavorites();
  if (favs.includes(destinationId)) {
    favs = favs.filter((id) => id !== destinationId);
  } else {
    favs.push(destinationId);
  }
  localStorage.setItem(FAVORITES_KEY, JSON.stringify(favs));
  return favs.includes(destinationId);
}

function favoritesCount() {
  return getFavorites().length;
}

// ---------------------------------------------------------------------------
// Récemment consultés (aucune connexion requise, stockage local navigateur)
// Garde les 10 derniers lieux visités, le plus recent en premier.
// ---------------------------------------------------------------------------
const RECENTLY_VIEWED_KEY = "gt_recently_viewed";
const RECENTLY_VIEWED_MAX = 10;

function getRecentlyViewed() {
  try {
    return JSON.parse(localStorage.getItem(RECENTLY_VIEWED_KEY) || "[]");
  } catch {
    return [];
  }
}

function recordRecentlyViewed(destinationId) {
  let recent = getRecentlyViewed().filter((id) => id !== destinationId);
  recent.unshift(destinationId);
  recent = recent.slice(0, RECENTLY_VIEWED_MAX);
  localStorage.setItem(RECENTLY_VIEWED_KEY, JSON.stringify(recent));
}

// ---------------------------------------------------------------------------
// Météo (Open-Meteo) — utilitaires partagés par plusieurs pages
// ---------------------------------------------------------------------------
const WEATHER_CODES = {
  0: { icon: "☀️", label: "Ciel dégagé" },
  1: { icon: "🌤️", label: "Plutôt dégagé" },
  2: { icon: "⛅", label: "Partiellement nuageux" },
  3: { icon: "☁️", label: "Couvert" },
  45: { icon: "🌫️", label: "Brouillard" },
  48: { icon: "🌫️", label: "Brouillard givrant" },
  51: { icon: "🌦️", label: "Bruine légère" },
  53: { icon: "🌦️", label: "Bruine" },
  55: { icon: "🌦️", label: "Bruine dense" },
  61: { icon: "🌧️", label: "Pluie légère" },
  63: { icon: "🌧️", label: "Pluie" },
  65: { icon: "🌧️", label: "Forte pluie" },
  80: { icon: "🌦️", label: "Averses" },
  81: { icon: "🌦️", label: "Fortes averses" },
  82: { icon: "⛈️", label: "Averses violentes" },
  95: { icon: "⛈️", label: "Orage" },
  96: { icon: "⛈️", label: "Orage avec grêle" },
  99: { icon: "⛈️", label: "Orage violent" },
};

function weatherInfo(code) {
  return WEATHER_CODES[code] || { icon: "🌡️", label: "Conditions variables" };
}

async function fetchWeatherData(lat, lng) {
  try {
    const res = await fetch(`/api/weather?lat=${lat}&lng=${lng}`);
    const data = await res.json();
    if (!res.ok || data.error || !data.current_weather) return null;
    return data;
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// Taxonomie des catégories (partagée par toutes les pages)
// ---------------------------------------------------------------------------
const CATEGORY_META = {
  "Plages": { icon: "🏖️", cls: "cat-beach", badge: "badge-cat-beach" },
  "Sites naturels": { icon: "🌿", cls: "cat-nature", badge: "badge-cat-nature" },
  "Restaurants": { icon: "🍽️", cls: "cat-food", badge: "badge-cat-food" },
  "Hôtels": { icon: "🏨", cls: "cat-hotel", badge: "badge-cat-hotel" },
  "Activités": { icon: "🚴", cls: "cat-activity", badge: "badge-cat-activity" },
  "Loisirs": { icon: "🎉", cls: "cat-fun", badge: "badge-cat-fun" },
  "Monuments": { icon: "🏛️", cls: "cat-heritage", badge: "badge-cat-heritage" },
  "Marchés et artisanat": { icon: "🛍️", cls: "cat-market", badge: "badge-cat-market" },
  "Bars et vie nocturne": { icon: "🍹", cls: "cat-nightlife", badge: "badge-cat-nightlife" },
  "Excursions": { icon: "🧭", cls: "cat-excursion", badge: "badge-cat-excursion" },
  "Shopping": { icon: "🛒", cls: "cat-shopping", badge: "badge-cat-shopping" },
  "Salons de beauté": { icon: "💇", cls: "cat-beauty", badge: "badge-cat-beauty" },
  "Autres": { icon: "📍", cls: "cat-other", badge: "badge-cat-other" },
};

function categoryMeta(name) {
  return CATEGORY_META[name] || { icon: "📍", cls: "cat-other", badge: "badge-cat-other" };
}

async function apiRequest(path, { method = "GET", body = null, auth = false } = {}) {
  const headers = { "Content-Type": "application/json" };
  if (auth) {
    const token = getToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
  }

  const response = await fetch(path, {
    method,
    headers,
    body: body ? JSON.stringify(body) : null,
  });

  const data = await response.json().catch(() => ({}));
  return { ok: response.ok, status: response.status, data };
}

function showMessage(el, text, type) {
  el.textContent = text;
  el.className = `message ${type}`;
}

// ---------------------------------------------------------------------------
// Photos dynamiques (API d'images) avec cache local
// ---------------------------------------------------------------------------
const PHOTO_CACHE_PREFIX = "gt_photo_";

async function fetchPhoto(query, fallbackQuery = "") {
  const cacheKey = PHOTO_CACHE_PREFIX + query + "|" + fallbackQuery;
  const cached = localStorage.getItem(cacheKey);
  if (cached !== null) return cached === "null" ? null : cached;

  try {
    const params = new URLSearchParams({ q: query });
    if (fallbackQuery) params.append("fallback", fallbackQuery);
    const res = await fetch(`/api/photo?${params.toString()}`);
    const data = await res.json();
    localStorage.setItem(cacheKey, data.url || "null");
    return data.url || null;
  } catch {
    return null;
  }
}

// Recherche tous les elements [data-photo-query] dans `root` et remplace
// leur fond par la photo trouvee (sans rien casser si l'API n'est pas configuree).
function hydratePhotos(root = document) {
  root.querySelectorAll("[data-photo-query]").forEach(async (el) => {
    const query = el.dataset.photoQuery;
    const fallbackQuery = el.dataset.photoFallback || "";
    if (!query || el.dataset.photoDone) return;
    el.dataset.photoDone = "1";
    const url = await fetchPhoto(query, fallbackQuery);
    if (url) {
      el.style.backgroundImage = `url('${url}')`;
      el.classList.add("photo-loaded");
    }
  });
}

// Bouton de bascule langue FR / EN (persiste dans localStorage)
// Vit desormais uniquement dans la page Profil > Parametres (retire de la
// navbar), mais le systeme reste generique au cas ou d'autres boutons
// langue seraient ajoutes ailleurs plus tard.
document.addEventListener("DOMContentLoaded", () => {
  applyTranslations();

  const langBtns = [
    { btn: document.getElementById("lang-toggle-btn-profile"), label: document.getElementById("lang-toggle-label-profile") },
  ].filter((pair) => pair.btn && pair.label);

  if (!langBtns.length) return;

  function applyLangLabel(lang) {
    // Affiche la langue VERS LAQUELLE on bascule si on clique
    const nextLabel = lang === "fr" ? "EN" : "FR";
    langBtns.forEach(({ label }) => { label.textContent = nextLabel; });
  }

  applyLangLabel(getLang());

  langBtns.forEach(({ btn }) => {
    btn.addEventListener("click", () => {
      const next = getLang() === "fr" ? "en" : "fr";
      setLang(next);
      applyLangLabel(next);
      applyTranslations();
    });
  });
});

// Update nav login/logout link on every page
document.addEventListener("DOMContentLoaded", () => {
  // Met en évidence le lien de navigation correspondant à la page actuelle
  const currentPath = window.location.pathname;
  document.querySelectorAll("nav a[href]").forEach((link) => {
    const href = link.getAttribute("href");
    if (href === "#") return;
    const isMatch =
      href === currentPath ||
      (href === "/" && currentPath === "/") ||
      (href !== "/" && currentPath.startsWith(href));
    if (isMatch) link.classList.add("nav-active");
  });

  const authLink = document.getElementById("auth-link");
  const authLinkDesktop = document.getElementById("auth-link-desktop");
  const authLinks = [authLink, authLinkDesktop].filter(Boolean);
  if (authLinks.length === 0) return;

  if (isLoggedIn()) {
    authLinks.forEach((link) => {
      link.removeAttribute("data-i18n");
      link.textContent = t("nav.logout");
      link.href = "#";
      link.addEventListener("click", (e) => {
        e.preventDefault();
        clearToken();
        window.location.href = "/login-page";
      });
    });

    // Renseigne l'avatar + le nom d'utilisateur dans l'en-tete du tiroir mobile.
    const avatarEl = document.getElementById("offcanvas-avatar");
    const usernameEl = document.getElementById("offcanvas-username");
    apiRequest("/me", { auth: true }).then(({ ok, data }) => {
      if (ok && usernameEl) {
        usernameEl.textContent = data.username || "Mon compte";
        if (avatarEl) avatarEl.textContent = (data.username || "?").trim().charAt(0).toUpperCase();
      }
      // Affiche le lien "Tableau de bord" uniquement pour l'administrateur.
      const adminNavItem = document.getElementById("admin-nav-item");
      if (adminNavItem && ok && data.role === "admin") {
        adminNavItem.style.display = "";
      }
    });
  } else {
    authLinks.forEach((link) => {
      link.setAttribute("data-i18n", "nav.login");
      link.textContent = t("nav.login");
      link.href = "/login-page";
    });
  }
});

