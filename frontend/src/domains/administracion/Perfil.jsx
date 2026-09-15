import { useCallback, useEffect, useState } from "react";
import useAuth from "../../shared/hooks/useAuth";
import useEmisores from "../../shared/hooks/useEmisores";
import { useNav } from "../../shared/layout/nav";
import { API_BASE, fetchAuth } from "../../shared/hooks/fetchAuth";
import { Card, Btn, SectionTitle, SectionSub } from "../../shared/components/atoms";
import { C } from "../../shared/utils/format";
import DashboardMiCuenta from "./DashboardMiCuenta";
import ConfiguracionMarca from "./ConfiguracionMarca";
import EmisoresResumenDashboard from "./EmisoresResumenDashboard";

// Vista de aterrizaje post-login para usuarios admin (zg5z04A):
// una vista NEUTRAL, no ligada a un emisor concreto.
//   - Datos de usuario (nombre/RFC/correo/usuario/rol/id/miembro desde):
//     GET /auth/me, consulta real a BD - ya NO se leen del JWT decodificado
//     client-side (useAuth sigue existiendo, pero solo para lo que SI debe
//     seguir siendo client-side: negocio_id para las otras llamadas de esta
//     pantalla, sesion activa, roles para gating de UI en otras partes).
//   - emisores + su estado (contexto de useEmisores, ya cargado por AppShell)
//   - plan del negocio + limites del plan (Parte B): GET /admin/negocios/{id}
//     - endpoint self-only (compara el id del path contra X-Negocio-Id que el
//       Gateway inyecta desde el JWT), asi que se pide con el propio
//       usuarioActual.negocio_id. limite_emisores / limite_facturas_mes salen
//       de PLAN_LIMITS del backend, no se duplica la tabla aqui.
const fila = { display: "flex", justifyContent: "space-between", gap: 12, padding: "8px 0", borderTop: `1px solid ${C.border}`, fontSize: 13 };
const etiqueta = { color: C.textMuted };
const valor = { color: C.text, fontWeight: 600, textAlign: "right", wordBreak: "break-word" };

function badgeEstado(estado) {
  const activo = estado === "Activo";
  return (
    <span style={{ background: activo ? C.accentSoft : C.dangerSoft, color: activo ? C.accentBorder : C.danger, fontSize: 11, fontWeight: 600, padding: "3px 10px", borderRadius: 20, whiteSpace: "nowrap" }}>
      {estado}
    </span>
  );
}

const MESES_ES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"];

// "Miembro desde marzo 2026" - nunca el timestamp crudo. null si la fecha
// no llega o no se puede interpretar (nunca revienta el render por esto).
function formatMiembroDesde(createdAtIso) {
  if (!createdAtIso) return null;
  const d = new Date(createdAtIso);
  if (Number.isNaN(d.getTime())) return null;
  return `Miembro desde ${MESES_ES[d.getMonth()]} ${d.getFullYear()}`;
}

// Skeleton de la seccion "Datos de la cuenta" mientras carga GET /auth/me -
// NO bloquea el resto de la pantalla (plan/resumen/emisores siguen su
// propio ciclo de carga independiente, como ya hacian antes de este cambio).
function SkeletonDatosCuenta() {
  const barra = { height: 12, borderRadius: 4, background: C.border };
  return (
    <div style={{ padding: "4px 0" }}>
      {[60, 90, 70, 50, 40, 65].map((ancho, i) => (
        <div key={i} style={fila}>
          <div style={{ ...barra, width: 80 }} />
          <div style={{ ...barra, width: `${ancho}%`, maxWidth: 160 }} />
        </div>
      ))}
    </div>
  );
}

// ID de usuario discreto + copiar (util para soporte, no protagonista de
// la pantalla - por eso texto pequeño y color secundario, no un Btn normal).
function IdConCopiar({ id }) {
  const [copiado, setCopiado] = useState(false);
  const copiar = async () => {
    try {
      await navigator.clipboard.writeText(String(id));
      setCopiado(true);
      setTimeout(() => setCopiado(false), 1500);
    } catch {
      // Clipboard API puede no estar disponible (contexto no seguro,
      // permiso denegado) - se degrada en silencio, no rompe la pantalla
      // por algo que es una conveniencia menor.
    }
  };
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
      <span style={{ fontFamily: "monospace", color: C.textMuted, fontSize: 12 }}>{id}</span>
      <button
        type="button"
        onClick={copiar}
        title="Copiar ID"
        style={{ background: "transparent", border: "none", cursor: "pointer", fontSize: 12, color: copiado ? C.accentBorder : C.textMuted, padding: 0, lineHeight: 1 }}
      >
        {copiado ? "✓ copiado" : "⧉ copiar"}
      </button>
    </span>
  );
}

export default function Perfil() {
  const { usuarioActual } = useAuth();
  const { emisores, loading, error, emisorActivoRfc } = useEmisores();
  const { navigate } = useNav();

  // Datos de usuario para "Datos de la cuenta" - GET /auth/me real, ya NO
  // usuarioActual (JWT decodificado). usuarioActual se conserva SOLO para
  // negocio_id (abajo) y lo que useAuth ya resolvia antes (sesion activa,
  // roles para gating en otras vistas) - nunca como fuente de estos campos.
  const [perfil, setPerfil] = useState(null);
  const [perfilLoading, setPerfilLoading] = useState(true);
  const [perfilError, setPerfilError] = useState(null);

  const cargarPerfil = useCallback(async () => {
    setPerfilLoading(true);
    setPerfilError(null);
    try {
      const res = await fetchAuth(`${API_BASE}/auth/me`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setPerfil(await res.json());
    } catch (e) {
      setPerfilError(e.message);
    } finally {
      setPerfilLoading(false);
    }
  }, []);

  useEffect(() => { cargarPerfil(); }, [cargarPerfil]);

  const negocioId = usuarioActual?.negocio_id;
  const [negocio, setNegocio] = useState(null);
  const [negocioLoading, setNegocioLoading] = useState(true);
  const [negocioError, setNegocioError] = useState(null);

  useEffect(() => {
    if (!negocioId) {
      setNegocioLoading(false);
      setNegocioError("No se pudo determinar el negocio del usuario.");
      return;
    }
    let cancelado = false;
    (async () => {
      setNegocioLoading(true);
      setNegocioError(null);
      try {
        const res = await fetchAuth(`${API_BASE}/admin/negocios/${negocioId}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        if (!cancelado) setNegocio(data);
      } catch (e) {
        if (!cancelado) setNegocioError(e.message);
      } finally {
        if (!cancelado) setNegocioLoading(false);
      }
    })();
    return () => { cancelado = true; };
  }, [negocioId]);

  // Resumen del mes (zg6k9Pw, Dashboard "Mi cuenta") - fetch independiente
  // del de /admin/negocios/{id} de arriba: son dos endpoints distintos
  // (este agrega datos de facturacion, con degradacion por campo si ese
  // servicio no responde - ver DashboardMiCuenta). Un solo fetch aqui,
  // las 4 tarjetas se reparten el resultado por props.
  const [resumen, setResumen] = useState(null);
  const [resumenLoading, setResumenLoading] = useState(true);
  const [resumenError, setResumenError] = useState(null);

  useEffect(() => {
    if (!negocioId) {
      setResumenLoading(false);
      setResumenError("No se pudo determinar el negocio del usuario.");
      return;
    }
    let cancelado = false;
    (async () => {
      setResumenLoading(true);
      setResumenError(null);
      try {
        const res = await fetchAuth(`${API_BASE}/admin/negocios/${negocioId}/resumen`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        if (!cancelado) setResumen(data);
      } catch (e) {
        if (!cancelado) setResumenError(e.message);
      } finally {
        if (!cancelado) setResumenLoading(false);
      }
    })();
    return () => { cancelado = true; };
  }, [negocioId]);

  const emisoresActivos = emisores.filter((e) => e.estado === "Activo").length;
  const miembroDesde = perfil ? formatMiembroDesde(perfil.created_at) : null;

  return (
    <div>
      <SectionTitle>Mi perfil</SectionTitle>
      <SectionSub>
        Elige un emisor para empezar a trabajar (facturar, generar tickets, ver reportes).
        Puedes cambiar de emisor cuando quieras desde el selector del encabezado o en Administración › Emisores.
      </SectionSub>

      <div style={{ display: "grid", gap: 16, maxWidth: 680 }}>
        <Card>
          <div style={{ fontSize: 13, fontWeight: 700, color: C.text, marginBottom: 4 }}>Datos de la cuenta</div>

          {perfilLoading && <SkeletonDatosCuenta />}

          {!perfilLoading && perfilError && (
            <div style={{ padding: "8px 0" }}>
              <div style={{ fontSize: 13, color: C.danger, marginBottom: 8 }}>
                No se pudo cargar tu perfil: {perfilError}
              </div>
              <Btn type="button" variant="secondary" style={{ fontSize: 12, padding: "6px 12px" }} onClick={cargarPerfil}>
                Reintentar
              </Btn>
            </div>
          )}

          {!perfilLoading && !perfilError && perfil && (
            <>
              <div style={fila}><span style={etiqueta}>Nombre</span><span style={valor}>{perfil.nombre || "—"}</span></div>
              <div style={fila}><span style={etiqueta}>RFC personal</span><span style={{ ...valor, fontFamily: "monospace" }}>{perfil.rfc_personal}</span></div>
              <div style={fila}><span style={etiqueta}>Correo</span><span style={valor}>{perfil.email}</span></div>
              <div style={fila}><span style={etiqueta}>Usuario</span><span style={valor}>{perfil.usuario || "No configurado"}</span></div>
              <div style={fila}><span style={etiqueta}>Rol</span><span style={valor}>{perfil.rol}</span></div>
              <div style={fila}><span style={etiqueta}>ID</span><span style={valor}><IdConCopiar id={perfil.id} /></span></div>
              {miembroDesde && (
                <div style={{ fontSize: 12, color: C.textMuted, marginTop: 8 }}>{miembroDesde}</div>
              )}
            </>
          )}
        </Card>

        <Card>
          <div style={{ fontSize: 13, fontWeight: 700, color: C.text, marginBottom: 4 }}>Plan del negocio</div>
          {negocioLoading && <div style={{ fontSize: 13, color: C.textMuted, padding: "8px 0" }}>Cargando plan…</div>}
          {negocioError && <div style={{ fontSize: 13, color: C.danger, padding: "8px 0" }}>No se pudo cargar el plan: {negocioError}</div>}
          {!negocioLoading && !negocioError && negocio && (
            <>
              <div style={fila}><span style={etiqueta}>Plan</span><span style={{ ...valor, textTransform: "capitalize" }}>{negocio.plan}</span></div>
              <div style={fila}>
                <span style={etiqueta}>Emisores</span>
                <span style={valor}>{emisoresActivos} de {negocio.limite_emisores}</span>
              </div>
            </>
          )}
        </Card>

        <div>
          <div style={{ fontSize: 13, fontWeight: 700, color: C.text, marginBottom: 10 }}>Resumen de este mes</div>
          <DashboardMiCuenta resumen={resumen} loading={resumenLoading} error={resumenError} />
        </div>

        <Card>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 4, gap: 8 }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: C.text }}>Emisores</div>
            <Btn type="button" variant="secondary" style={{ fontSize: 12, padding: "6px 12px" }} onClick={() => navigate("emisores")}>
              Ir a Emisores
            </Btn>
          </div>
          {loading && <div style={{ fontSize: 13, color: C.textMuted, padding: "8px 0" }}>Cargando emisores…</div>}
          {error && <div style={{ fontSize: 13, color: C.danger, padding: "8px 0" }}>No se pudieron cargar los emisores: {error}</div>}
          {!loading && !error && emisores.length === 0 && (
            <div style={{ fontSize: 13, color: C.textMuted, padding: "8px 0" }}>
              Todavía no hay emisores dados de alta. Agrega uno en Administración › Emisores.
            </div>
          )}
          {!loading && !error && emisores.map((e) => (
            <div key={e.rfc} style={{ ...fila, alignItems: "center" }}>
              <span style={{ minWidth: 0 }}>
                <span style={{ color: C.text, fontWeight: 600, display: "block", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{e.razon_social}</span>
                <span style={{ color: C.textMuted, fontFamily: "monospace", fontSize: 12 }}>
                  {e.rfc}{e.rfc === emisorActivoRfc ? " · activo ahora" : ""}
                </span>
              </span>
              {badgeEstado(e.estado)}
            </div>
          ))}
        </Card>

        {/* Dashboard multi-emisor (vigencia CSD + concentracion de
            facturas) - SOLO para negocios con mas de 1 emisor, chequeo
            explicito aqui en el frontend (no basta con que el backend
            devuelva una lista corta - ver EmisoresResumenDashboard.jsx). */}
        {!loading && !error && emisores.length > 1 && (
          <EmisoresResumenDashboard negocioId={negocioId} />
        )}

        <ConfiguracionMarca />
      </div>
    </div>
  );
}
