// Ruta relativa (zg5nh5Y, 05 sep 2026): las llamadas van a /api/... del
// mismo origen que sirve el frontend; nginx (frontend/nginx.conf) las
// proxea al gateway. Antes era "http://localhost:8000" absoluto, que solo
// funcionaba desde el navegador de la maquina de dev (fallaba por
// alcanzabilidad / mixed-content / CORS desde cualquier otro host).
// En `npm run dev` (sin nginx) el proxy /api ya esta en vite.config.js.
export const API_BASE = "/api";

const TOKEN_KEY = "cfdi_aes_token";

const getToken = () => sessionStorage.getItem(TOKEN_KEY);
const setStoredToken = token => token ? sessionStorage.setItem(TOKEN_KEY, token) : sessionStorage.removeItem(TOKEN_KEY);

export { getToken, setStoredToken };

export async function fetchAuth(url, options = {}) {
  const token = getToken();
  const headers = { ...(options.headers || {}), ...(token ? { Authorization: `Bearer ${token}` } : {}) };
  const res = await fetch(url, { ...options, headers });
  if (res.status === 401 || res.status === 403) {
    setStoredToken(null);
    window.dispatchEvent(new Event("cfdi-auth-expired"));
  }
  return res;
}
