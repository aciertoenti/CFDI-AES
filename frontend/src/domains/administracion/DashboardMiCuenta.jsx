import { Card } from "../../shared/components/atoms";
import { C } from "../../shared/utils/format";

// Dashboard "Mi cuenta" (zg6k9Pw) - 4 tarjetas de metrica sobre GET
// /admin/negocios/{id}/resumen (una sola llamada, ya la hace Perfil.jsx y
// nos pasa el resultado por props - ver ese archivo).
//
// Degradacion por tarjeta, no por toda la vista: el backend devuelve
// facturas_mes/porcentaje_cancelacion_mes en null + advertencias si
// facturacion no respondio, pero limite_plan SIEMPRE esta disponible
// (vive en administracion). timbres_disponibles es SIEMPRE null hoy - no
// existe infraestructura de wallet/timbres todavia (zg3mu7Q, sin
// construir) - se muestra como "Proximamente", no como error.
//
// Trend vs. mes anterior: fuera de alcance (v2, ver zg6k9Pw).

const grid = { display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(min(260px,100%),1fr))", gap: 16 };
const etiqueta = { fontSize: 12, fontWeight: 600, color: C.textMuted, textTransform: "uppercase", letterSpacing: .3 };
const valorGrande = { fontSize: 28, fontWeight: 800, color: C.text, lineHeight: 1.15, marginTop: 6 };
const subtitulo = { fontSize: 12, color: C.textMuted, marginTop: 4 };

function TarjetaMetrica({ etiqueta: label, children }) {
  return (
    <Card style={{ padding: 18 }}>
      <div style={etiqueta}>{label}</div>
      {children}
    </Card>
  );
}

function Cargando() {
  return <div style={{ ...valorGrande, fontSize: 15, fontWeight: 600, color: C.textMuted }}>Cargando…</div>;
}

function NoDisponible() {
  return (
    <>
      <div style={{ ...valorGrande, fontSize: 15, fontWeight: 600, color: C.textMuted }}>No disponible</div>
      <div style={subtitulo}>No se pudo obtener datos de facturación en este momento.</div>
    </>
  );
}

// Barra horizontal simple, capeada visualmente en 100% aunque facturas_mes
// exceda limite_plan (el TEXTO arriba sigue mostrando el numero real, sin
// capear - solo la barra se limita para no desbordar el contenedor).
function BarraProgreso({ valor, maximo }) {
  const porcentaje = maximo > 0 ? Math.min(100, Math.round((valor / maximo) * 100)) : 0;
  return (
    <div style={{ height: 8, borderRadius: 999, background: C.border, overflow: "hidden", marginTop: 10 }}>
      <div style={{ height: "100%", width: `${porcentaje}%`, background: C.accent, borderRadius: 999 }} />
    </div>
  );
}

export default function DashboardMiCuenta({ resumen, loading, error }) {
  if (error) {
    return (
      <Card style={{ padding: 18 }}>
        <div style={{ fontSize: 13, color: C.danger }}>No se pudo cargar el resumen de la cuenta: {error}</div>
      </Card>
    );
  }

  if (loading) {
    return (
      <div style={grid}>
        <TarjetaMetrica etiqueta="Facturas este mes"><Cargando /></TarjetaMetrica>
        <TarjetaMetrica etiqueta="Consumo del plan"><Cargando /></TarjetaMetrica>
        <TarjetaMetrica etiqueta="Cancelación este mes"><Cargando /></TarjetaMetrica>
        <TarjetaMetrica etiqueta="Timbres disponibles"><Cargando /></TarjetaMetrica>
      </div>
    );
  }

  if (!resumen) return null;

  const { facturas_mes, limite_plan, porcentaje_cancelacion_mes, timbres_disponibles, advertencias } = resumen;
  const datosFacturacionCaidos = Array.isArray(advertencias) && advertencias.length > 0;
  const sinFacturasEsteMes = !datosFacturacionCaidos && facturas_mes === 0;

  return (
    <div style={grid}>
      <TarjetaMetrica etiqueta="Facturas este mes">
        {datosFacturacionCaidos ? (
          <NoDisponible />
        ) : sinFacturasEsteMes ? (
          <>
            <div style={{ ...valorGrande, fontSize: 15, fontWeight: 600, color: C.textMuted }}>
              Aún no has emitido facturas este mes
            </div>
            <div style={subtitulo}>Límite del plan: {limite_plan} al mes</div>
          </>
        ) : (
          <>
            <div style={valorGrande}>{facturas_mes}</div>
            {limite_plan != null && <div style={subtitulo}>de {limite_plan} incluidas en tu plan</div>}
          </>
        )}
      </TarjetaMetrica>

      <TarjetaMetrica etiqueta="Consumo del plan">
        {datosFacturacionCaidos ? (
          <NoDisponible />
        ) : (
          <>
            <div style={valorGrande}>
              {facturas_mes}{limite_plan != null ? ` / ${limite_plan}` : ""} facturas
            </div>
            {/* limite_plan null: plan sin limite definido - no hay contra que
                barrear ni que mostrar "/ null". Hoy PLAN_LIMITS siempre trae
                un valor (fallback a "basico"), asi que este caso no ocurre
                en la practica todavia - queda listo por si algun dia existe
                un plan sin tope. */}
            {limite_plan != null && <BarraProgreso valor={facturas_mes} maximo={limite_plan} />}
          </>
        )}
      </TarjetaMetrica>

      <TarjetaMetrica etiqueta="Cancelación este mes">
        {datosFacturacionCaidos ? (
          <NoDisponible />
        ) : sinFacturasEsteMes ? (
          <>
            <div style={{ ...valorGrande, fontSize: 15, fontWeight: 600, color: C.textMuted }}>
              Aún no has emitido facturas este mes
            </div>
            <div style={subtitulo}>No hay nada que cancelar todavía.</div>
          </>
        ) : (
          <>
            <div style={valorGrande}>{porcentaje_cancelacion_mes}%</div>
            <div style={subtitulo}>de las facturas emitidas este mes</div>
          </>
        )}
      </TarjetaMetrica>

      <TarjetaMetrica etiqueta="Timbres disponibles">
        {timbres_disponibles === null || timbres_disponibles === undefined ? (
          <>
            <div style={{ ...valorGrande, fontSize: 15, fontWeight: 600, color: C.textMuted }}>Próximamente</div>
            <div style={subtitulo}>No aplica a tu plan actual.</div>
          </>
        ) : (
          <div style={valorGrande}>{timbres_disponibles}</div>
        )}
      </TarjetaMetrica>
    </div>
  );
}
