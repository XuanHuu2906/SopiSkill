/* SopiSkill Service Worker: Web Push (Phase 7) + Offline App Shell Cache (Phase 8, 0 API/answer-key cache) */
const SHELL_CACHE = "sopiskill-shell-v1";

self.addEventListener("install", () => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

function normalizedCacheKey(url, isRsc) {
  return `${url.origin}${url.pathname}::${isRsc ? "rsc" : "html"}`;
}

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/v1/") || url.pathname.startsWith("/api/")) return;

  const isStaticAsset =
    url.pathname.startsWith("/_next/static/") || url.pathname.startsWith("/fonts/");
  const isRsc = req.headers.get("RSC") === "1" || url.searchParams.has("_rsc");
  const isNav = req.mode === "navigate" || (req.headers.get("Accept") || "").includes("text/html");

  if (isStaticAsset) {
    event.respondWith(
      caches.open(SHELL_CACHE).then(async (cache) => {
        const cached = await cache.match(req);
        if (cached) return cached;
        const fresh = await fetch(req);
        if (fresh && fresh.ok) {
          cache.put(req, fresh.clone()).catch(() => {});
        }
        return fresh;
      }),
    );
    return;
  }

  if (isNav || isRsc) {
    event.respondWith(
      caches.open(SHELL_CACHE).then(async (cache) => {
        const normKey = normalizedCacheKey(url, isRsc);
        try {
          const fresh = await fetch(req);
          if (fresh && fresh.ok) {
            cache.put(req, fresh.clone()).catch(() => {});
            cache.put(normKey, fresh.clone()).catch(() => {});
          }
          return fresh;
        } catch {
          const exact = await cache.match(req);
          if (exact) return exact;
          const byPath = await cache.match(normKey);
          if (byPath) return byPath;
          // Fallback to any cached lesson HTML shell when navigating to a cached lesson offline
          if (!isRsc && url.pathname.startsWith("/lesson/")) {
            const keys = await cache.keys();
            const isComplete = url.pathname.endsWith("/complete");
            const fallbackKey = keys.find((k) => {
              const u = new URL(k.url);
              if (!u.pathname.startsWith("/lesson/")) return false;
              return isComplete
                ? u.pathname.endsWith("/complete::html") || u.pathname.endsWith("/complete")
                : !u.pathname.includes("/complete");
            });
            if (fallbackKey) {
              const fb = await cache.match(fallbackKey);
              if (fb) return fb;
            }
          }
          throw new Error("Offline and route not cached");
        }
      }),
    );
  }
});

self.addEventListener("push", (event) => {
  let payload = {
    title: "SopiSkill",
    body: "Bạn có nhắc nhở học tập mới trên SopiSkill.",
    url: "/",
  };
  if (event.data) {
    try {
      const parsed = event.data.json();
      payload = { ...payload, ...parsed };
    } catch {
      payload.body = event.data.text() || payload.body;
    }
  }
  event.waitUntil(
    self.registration.showNotification(payload.title, {
      body: payload.body,
      tag: payload.kind || "sopiskill-nudge",
      data: { url: payload.url || "/" },
    }),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const targetUrl = (event.notification.data && event.notification.data.url) || "/";
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((clientList) => {
      for (const client of clientList) {
        if ("focus" in client) {
          client.navigate(targetUrl);
          return client.focus();
        }
      }
      if (self.clients.openWindow) {
        return self.clients.openWindow(targetUrl);
      }
      return undefined;
    }),
  );
});
