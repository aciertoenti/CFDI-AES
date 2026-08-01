/**
 * Configuración base del cliente HTTP hacia el API Gateway.
 * Todas las llamadas del frontend pasan por aquí.
 */

const API_BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

/**
 * Wrapper de fetch con manejo de errores y token JWT automático.
 * @param {string} path  - Ruta relativa, ej: "/facturas/timbrar"
 * @param {RequestInit} options - Opciones de fetch
 */
export async function apiFetch(path, options = {}) {
  const token = localStorage.getItem("access_token");

  const headers = {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(options.headers || {}),
  };

  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
  });

  if (response.status === 401) {
    localStorage.removeItem("access_token");
    window.location.href = "/login";
    return;
  }

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || `HTTP ${response.status}`);
  }

  return response.json();
}

// ── Auth ──────────────────────────────────────────────────────────────────────

export const authAPI = {
  login: (email, password) =>
    apiFetch("/auth/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),
};

// ── Facturación ───────────────────────────────────────────────────────────────

export const facturasAPI = {
  timbrar: (payload) =>
    apiFetch("/facturas/facturas/timbrar", { method: "POST", body: JSON.stringify(payload) }),

  listar: (params = {}) => {
    const qs = new URLSearchParams(params).toString();
    return apiFetch(`/facturas/facturas${qs ? `?${qs}` : ""}`);
  },

  obtener: (uuid) => apiFetch(`/facturas/facturas/${uuid}`),

  descargarXml: (uuid) => apiFetch(`/facturas/facturas/${uuid}/xml`),

  descargarPdf: (uuid) => apiFetch(`/facturas/facturas/${uuid}/pdf`),

  cancelar: (uuid, motivo, uuidSustitucion) =>
    apiFetch(`/facturas/facturas/${uuid}/cancelar`, {
      method: "POST",
      body: JSON.stringify({ uuid, motivo, uuid_sustitucion: uuidSustitucion }),
    }),
};

// ── Administración ────────────────────────────────────────────────────────────

export const adminAPI = {
  clientes: {
    listar: (params = {}) => {
      const qs = new URLSearchParams(params).toString();
      return apiFetch(`/admin/admin/clientes${qs ? `?${qs}` : ""}`);
    },
    crear: (payload) =>
      apiFetch("/admin/admin/clientes", { method: "POST", body: JSON.stringify(payload) }),
    actualizar: (rfc, payload) =>
      apiFetch(`/admin/admin/clientes/${rfc}`, { method: "PUT", body: JSON.stringify(payload) }),
  },
  emisores: {
    listar: () => apiFetch("/admin/admin/emisores"),
  },
};
