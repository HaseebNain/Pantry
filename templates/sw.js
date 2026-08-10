/* Pantry service worker — offline support.
   Strategy:
   - App shell (HTML/fonts/scanner lib): cache-first, so the app opens with no signal.
   - API GETs (items, stats, recipes): network-first, falling back to the last
     cached copy when offline. Writes (POST/PATCH/DELETE) are never cached.
*/
const SHELL = "pantry-shell-v10";
const DATA  = "pantry-data-v10";

const SHELL_ASSETS = [
  "/",
  "/manifest.json",
  "https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600;9..144,900&family=Archivo:wght@400;500;600;700&display=swap",
  "https://cdn.jsdelivr.net/npm/@zxing/library@0.21.3/umd/index.min.js",
];

self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(SHELL).then((c) =>
      // Don't let one failed CDN asset abort the whole install.
      Promise.allSettled(SHELL_ASSETS.map((u) => c.add(u)))
    ).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys.filter((k) => k !== SHELL && k !== DATA).map((k) => caches.delete(k))
      )
    ).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const { request } = e;
  if (request.method !== "GET") return; // never cache writes

  const url = new URL(request.url);
  const isReadApi =
    url.pathname === "/api/items" ||
    url.pathname === "/api/stats" ||
    url.pathname === "/api/recipes" ||
    url.pathname === "/api/list";

  // Network-first for inventory data, fall back to last good copy.
  if (isReadApi) {
    e.respondWith(
      fetch(request)
        .then((res) => {
          const copy = res.clone();
          caches.open(DATA).then((c) => c.put(request, copy));
          return res;
        })
        .catch(() =>
          caches.match(request).then(
            (cached) =>
              cached ||
              new Response(JSON.stringify({ __offline: true }), {
                headers: { "Content-Type": "application/json" },
              })
          )
        )
    );
    return;
  }

  // Cache-first for the app shell and static assets.
  e.respondWith(
    caches.match(request).then(
      (cached) =>
        cached ||
        fetch(request)
          .then((res) => {
            if (res.ok && (url.origin === location.origin || url.protocol === "https:")) {
              const copy = res.clone();
              caches.open(SHELL).then((c) => c.put(request, copy));
            }
            return res;
          })
          .catch(() => cached)
    )
  );
});
