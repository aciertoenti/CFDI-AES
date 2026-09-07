import useAuth from "../../shared/hooks/useAuth";
import useEmisores from "../../shared/hooks/useEmisores";
import { useNav } from "../../shared/layout/nav";
import { Card, Btn, SectionTitle, SectionSub } from "../../shared/components/atoms";
import { C } from "../../shared/utils/format";

// Vista de aterrizaje post-login para usuarios admin (zg5z04A, Parte A):
// una vista NEUTRAL, no ligada a un emisor concreto. Placeholder: solo
// muestra datos que el frontend YA tiene sin llamadas nuevas
//   - usuarioActual (claims del JWT via useAuth)
//   - emisores + su estado (contexto de useEmisores, ya cargado por AppShell)
// El plan del negocio y el limite de emisores del plan NO se muestran aqui:
// requieren consumir GET /admin/negocios/{id} (existe) y exponer PLAN_LIMITS
// desde el backend (no expuesto hoy) - queda para una iteracion posterior.
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

export default function Perfil() {
  const { usuarioActual } = useAuth();
  const { emisores, loading, error, emisorActivoRfc } = useEmisores();
  const { navigate } = useNav();

  const nombre = usuarioActual?.nombre || "—";
  const rfcPersonal = usuarioActual?.sub || "—";
  const email = usuarioActual?.email || "—";
  const roles = Array.isArray(usuarioActual?.roles) ? usuarioActual.roles.join(", ") : "—";

  return (
    <div>
      <SectionTitle>Mi perfil</SectionTitle>
      <SectionSub>
        Elige un emisor para empezar a trabajar (facturar, generar tickets, ver reportes).
        Puedes cambiar de emisor cuando quieras desde el selector del encabezado o en Administración › Emisores.
      </SectionSub>

      <div style={{ display: "grid", gap: 16, maxWidth: 560 }}>
        <Card>
          <div style={{ fontSize: 13, fontWeight: 700, color: C.text, marginBottom: 4 }}>Datos de la cuenta</div>
          <div style={fila}><span style={etiqueta}>Nombre</span><span style={valor}>{nombre}</span></div>
          <div style={fila}><span style={etiqueta}>RFC personal</span><span style={{ ...valor, fontFamily: "monospace" }}>{rfcPersonal}</span></div>
          <div style={fila}><span style={etiqueta}>Correo</span><span style={valor}>{email}</span></div>
          <div style={fila}><span style={etiqueta}>Rol</span><span style={valor}>{roles}</span></div>
        </Card>

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
      </div>
    </div>
  );
}
