export const API_BASE = "http://localhost:8000";

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
