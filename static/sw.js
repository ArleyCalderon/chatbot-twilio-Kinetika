self.addEventListener("install", (event) => {
  console.log("Service Worker instalado");
});

self.addEventListener("fetch", (event) => {
  // Por ahora no cacheamos nada
});