import { useEffect, useRef, useState } from "react";
import { API_BASE, fetchAuth } from "../hooks/fetchAuth";
import { C } from "../utils/format";

// Campanita de notificaciones (zg6k9Ok, primera alerta: plan cerca del
// limite mensual) - reemplaza el div puramente decorativo que habia antes
// en AppShell.jsx (punto rojo fijo, sin fetch ni onClick - ver hallazgo
// documentado antes de esta implementacion).
//
// GET /admin/negocios/{id}/notificaciones ya genera la alerta de forma
// lazy del lado del backend (sin scheduler) - este componente solo pide
// la lista y la muestra, no decide cuando "hay algo que notificar".
export default function NotificationBell({ negocioId }) {
  const [notificaciones, setNotificaciones] = useState([]);
  const [abierto, setAbierto] = useState(false);
  const contenedorRef = useRef(null);

  const cargar = async () => {
    if (!negocioId) return;
    try {
      const res = await fetchAuth(`${API_BASE}/admin/negocios/${negocioId}/notificaciones`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setNotificaciones(await res.json());
    } catch {
      // Silencioso a proposito: la campanita no debe romper el resto del
      // header si falla. Igual que el resto de fetches del header (ej.
      // negocio/emisores en Perfil.jsx), sin bloquear la vista.
    }
  };

  useEffect(() => { cargar(); }, [negocioId]);

  // Cierra el panel al hacer click fuera - patron estandar, sin libreria
  // nueva (mismo criterio "sin dependencias nuevas" del resto del proyecto).
  useEffect(() => {
    if (!abierto) return;
    const onClickFuera = e => {
      if (contenedorRef.current && !contenedorRef.current.contains(e.target)) setAbierto(false);
    };
    document.addEventListener("mousedown", onClickFuera);
    return () => document.removeEventListener("mousedown", onClickFuera);
  }, [abierto]);

  const marcarLeida = async id => {
    // Optimistic update: se marca leida en pantalla de inmediato, el POST
    // real va despues. Si falla, se revierte (misma idea que el resto del
    // proyecto no usa una libreria de estado optimista - se hace a mano).
    setNotificaciones(prev => prev.map(n => (n.id === id ? { ...n, leida: true } : n)));
    try {
      const res = await fetchAuth(
        `${API_BASE}/admin/negocios/${negocioId}/notificaciones/${id}/marcar-leida`,
        { method: "POST" },
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
    } catch {
      setNotificaciones(prev => prev.map(n => (n.id === id ? { ...n, leida: false } : n)));
    }
  };

  const hayNoLeidas = notificaciones.some(n => !n.leida);

  return (
    <div ref={contenedorRef} style={{ position: "relative" }}>
      <div
        role="button"
        aria-label="Notificaciones"
        onClick={() => setAbierto(a => !a)}
        style={{ position: "relative", cursor: "pointer" }}
      >
        {hayNoLeidas && (
          <div style={{ width: 7, height: 7, borderRadius: "50%", background: C.danger, position: "absolute", top: -1, right: -1, border: "2px solid #fff" }} />
        )}
        <span style={{ fontSize: 17 }}>🔔</span>
      </div>

      {abierto && (
        <div
          style={{
            position: "absolute", top: "calc(100% + 8px)", right: 0, width: 300, maxWidth: "calc(100vw - 24px)",
            maxHeight: 360, overflowY: "auto", background: "#fff", border: `1px solid ${C.border}`,
            borderRadius: 10, boxShadow: "0 12px 32px rgba(0,0,0,.18)", zIndex: 300,
          }}
        >
          <div style={{ padding: "10px 14px", fontSize: 13, fontWeight: 700, color: C.text, borderBottom: `1px solid ${C.border}` }}>
            Notificaciones
          </div>
          {notificaciones.length === 0 && (
            <div style={{ padding: "18px 14px", fontSize: 13, color: C.textMuted, textAlign: "center" }}>
              No tienes notificaciones
            </div>
          )}
          {notificaciones.map(n => (
            <div
              key={n.id}
              onClick={() => !n.leida && marcarLeida(n.id)}
              style={{
                padding: "10px 14px", fontSize: 12.5, color: C.text, borderBottom: `1px solid ${C.border}`,
                cursor: n.leida ? "default" : "pointer", background: n.leida ? "transparent" : C.accentSoft, lineHeight: 1.4,
              }}
            >
              {n.mensaje}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
