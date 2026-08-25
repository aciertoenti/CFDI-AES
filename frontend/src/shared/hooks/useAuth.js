import { useCallback, useEffect, useMemo, useState } from "react";
import { API_BASE, fetchAuth, getToken, setStoredToken } from "./fetchAuth";
import { detalleError } from "../utils/format";

function decodeJwtClaims(token) {
  if (!token) return null;
  try {
    const [, payloadB64] = token.split(".");
    return JSON.parse(atob(payloadB64.replace(/-/g, "+").replace(/_/g, "/")));
  } catch {
    return null;
  }
}

export default function useAuth() {
  const [token, setToken] = useState(getToken);
  useEffect(() => {
    const onExpired = () => setToken(null);
    window.addEventListener("cfdi-auth-expired", onExpired);
    return () => window.removeEventListener("cfdi-auth-expired", onExpired);
  }, []);
  const login = useCallback(async (identificador, password) => {
    try {
      const res = await fetch(`${API_BASE}/auth/login`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ identificador, password }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) return { ok: false, error: detalleError(data, res) };
      setStoredToken(data.access_token);
      setToken(data.access_token);
      return { ok: true };
    } catch (e) {
      return { ok: false, error: e.message };
    }
  }, []);
  const registro = useCallback(async (nombreNegocio, email, rfcPersonal, password, nombre, usuario, plan) => {
    try {
      const res = await fetch(`${API_BASE}/auth/registro`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        // plan es opcional (backend cae en "basico" si se omite, ver
        // RegistroRequest.plan) - solo se manda si viene de la landing.
        body: JSON.stringify({ nombre_negocio: nombreNegocio, email, rfc_personal: rfcPersonal, password, nombre, usuario, ...(plan ? { plan } : {}) }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) return { ok: false, error: detalleError(data, res) };
      return login(rfcPersonal, password);
    } catch (e) {
      return { ok: false, error: e.message };
    }
  }, [login]);
  const logout = useCallback(() => { setStoredToken(null); setToken(null); }, []);
  const solicitarReset = useCallback(async email => {
    try {
      const res = await fetch(`${API_BASE}/auth/password-reset/request`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) return { ok: false, error: detalleError(data, res) };
      return { ok: true, mensaje: data.mensaje };
    } catch (e) {
      return { ok: false, error: e.message };
    }
  }, []);
  const confirmarReset = useCallback(async (token, nuevaPassword) => {
    try {
      const res = await fetch(`${API_BASE}/auth/password-reset/confirm`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token, nueva_password: nuevaPassword }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) return { ok: false, error: detalleError(data, res) };
      return { ok: true, mensaje: data.mensaje };
    } catch (e) {
      return { ok: false, error: e.message };
    }
  }, []);
  const cambiarPassword = useCallback(async (passwordActual, nuevaPassword) => {
    try {
      const res = await fetchAuth(`${API_BASE}/auth/password/change`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password_actual: passwordActual, nueva_password: nuevaPassword }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) return { ok: false, error: detalleError(data, res) };
      return { ok: true, mensaje: data.mensaje || "Contraseña actualizada correctamente." };
    } catch (e) {
      return { ok: false, error: e.message };
    }
  }, []);
  const usuarioActual = useMemo(() => decodeJwtClaims(token), [token]);
  return { token, isAuthenticated: !!token, usuarioActual, login, registro, logout, solicitarReset, confirmarReset, cambiarPassword };
}
