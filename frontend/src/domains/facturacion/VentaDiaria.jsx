import { useMemo, useState } from "react";
import useBreakpoint from "../../shared/hooks/useBreakpoint";
import useEmisores from "../../shared/hooks/useEmisores";
import { useTickets } from "./hooks";
import { SectionTitle, KPIGrid, KPI, Card } from "../../shared/components/atoms";
import { Placeholder } from "../../shared/layout/AppShell";
import { C, fmt } from "../../shared/utils/format";

// Pantalla "Ventas del dia" (zg5sPJI, Sesion B): listado de tickets del POS
// ligero del dia (o de un dia elegido "en adelante"). Reutiliza el patron
// visual/tecnico de FacturasGeneradas.jsx: KPIs client-side, tabla con scroll
// horizontal, chips de estado y busqueda client-side, scopeado por el emisor
// activo. SIN paginador ni /count en v1 (ver zg5sPJI): trae hasta size=200 y
// muestra el conteo con tickets.length.

const TH = { padding: "9px 12px", textAlign: "left", fontSize: 10, fontWeight: 700, color: C.textMuted, textTransform: "uppercase", letterSpacing: "0.06em", whiteSpace: "nowrap" };
const TD = { padding: "10px 12px", color: C.text };

// Fecha local de hoy en YYYY-MM-DD (lo que espera <input type="date"> y el
// backend). toLocaleDateString("en-CA") ya devuelve formato ISO.
const hoyLocal = () => new Date().toLocaleDateString("en-CA");

// Estados de TicketVenta -> etiqueta + color. Badge propio (el atom <Badge>
// solo conoce estados de Factura: Vigente/Vencida/Cancelada).
const ESTADO_META = {
  pendiente:            { label: "Pendiente",   bg: C.warnSoft,   fg: C.warn },
  facturado_individual: { label: "Facturado",   bg: C.accentSoft, fg: C.accentBorder },
  procesando:           { label: "Procesando",  bg: C.infoSoft,   fg: C.info },
  consolidado:          { label: "Consolidado", bg: C.surface,    fg: C.textSec },
};
function BadgeTicket({ estado }) {
  const m = ESTADO_META[estado] || { label: estado, bg: C.surface, fg: C.textSec };
  return (
    <span style={{ background: m.bg, color: m.fg, fontSize: 11, fontWeight: 600, padding: "3px 10px", borderRadius: 20, whiteSpace: "nowrap" }}>
      {m.label}
    </span>
  );
}

// Chips: etiqueta visible -> valor de estado en la API (o null = "Todos").
const CHIPS = [
  ["Todos", null],
  ["Pendiente", "pendiente"],
  ["Facturado", "facturado_individual"],
  ["Procesando", "procesando"],
  ["Consolidado", "consolidado"],
];

export default function VentaDiaria() {
  const { isMobile } = useBreakpoint();
  const { emisorActivoRfc } = useEmisores();
  const [fecha, setFecha] = useState(hoyLocal());
  const { tickets, loading, error, recargar } = useTickets(emisorActivoRfc, fecha);

  const [q, setQ] = useState("");
  const [estadoFiltro, setEstadoFiltro] = useState(null);
  const esHoy = fecha === hoyLocal();

  const items = useMemo(() => {
    const t = q.trim().toLowerCase();
    return tickets.filter((tk) => {
      if (estadoFiltro && tk.estado !== estadoFiltro) return false;
      if (!t) return true;
      return tk.folio.toLowerCase().includes(t) || (tk.rfc_receptor || "").toLowerCase().includes(t);
    });
  }, [tickets, q, estadoFiltro]);

  const totalDia = tickets.reduce((s, tk) => s + tk.total, 0);
  const cuenta = (e) => tickets.filter((tk) => tk.estado === e).length;
  const nProcesando = cuenta("procesando");
  const nConsolidado = cuenta("consolidado");

  if (error) return <Placeholder title="Ventas del día" detail={`No se pudieron cargar los tickets: ${error}`} />;

  return (
    <div>
      <SectionTitle>Ventas del día</SectionTitle>

      <KPIGrid>
        <KPI label="Total del día" value={fmt(totalDia)} dark />
        <KPI label="Tickets" value={tickets.length} />
        <KPI label="Pendientes" value={cuenta("pendiente")} />
        <KPI label="Facturados" value={cuenta("facturado_individual")} />
        {nProcesando > 0 && <KPI label="Procesando" value={nProcesando} />}
        {nConsolidado > 0 && <KPI label="Consolidados" value={nConsolidado} />}
      </KPIGrid>

      <Card style={{ padding: 0, overflow: "hidden" }}>
        <div style={{ padding: "10px 12px", borderBottom: `1px solid ${C.border}`, display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: C.textSec, whiteSpace: "nowrap" }}>
            Desde
            <input type="date" value={fecha} max={hoyLocal()} onChange={(e) => setFecha(e.target.value || hoyLocal())}
              style={{ border: `1px solid ${C.border}`, borderRadius: 8, padding: "6px 9px", fontSize: 13, color: C.text, background: C.surface }} />
          </label>
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Buscar folio o RFC receptor…"
            style={{ flex: 1, minWidth: 120, border: `1px solid ${C.border}`, borderRadius: 8, padding: "7px 11px", fontSize: 13, color: C.text, background: C.surface }} />
          <div style={{ display: "flex", gap: 5, flexWrap: "wrap" }}>
            {CHIPS.map(([label, val]) => (
              <button key={label} onClick={() => setEstadoFiltro(val)}
                style={{ fontSize: 11, padding: "5px 10px", borderRadius: 12, border: `1px solid ${estadoFiltro === val ? C.accent : C.border}`,
                  background: estadoFiltro === val ? C.accentSoft : "transparent", color: estadoFiltro === val ? C.accentBorder : C.textSec, cursor: "pointer", whiteSpace: "nowrap" }}>
                {label}
              </button>
            ))}
          </div>
          <button onClick={recargar} title="Recargar" disabled={loading}
            style={{ fontSize: 11, padding: "5px 10px", borderRadius: 12, border: `1px solid ${C.border}`, background: "transparent", color: C.textSec, cursor: loading ? "not-allowed" : "pointer" }}>
            {loading ? "Cargando…" : "↻ Recargar"}
          </button>
        </div>

        <div style={{ overflowX: "auto", WebkitOverflowScrolling: "touch" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", minWidth: isMobile ? 340 : 620 }}>
            <thead>
              <tr style={{ background: C.surface }}>
                <th style={TH}>Folio</th>
                <th style={TH}>Fecha / hora</th>
                <th style={{ ...TH, textAlign: "right" }}>Total</th>
                <th style={{ ...TH, textAlign: "center" }}>Estado</th>
                {!isMobile && <th style={TH}>RFC receptor</th>}
                {!isMobile && <th style={{ ...TH, textAlign: "center" }}>Conceptos</th>}
                {!isMobile && <th style={TH}>N° cliente</th>}
              </tr>
            </thead>
            <tbody>
              {!loading && items.length === 0 && (
                <tr>
                  <td colSpan={isMobile ? 4 : 7} style={{ ...TD, textAlign: "center", color: C.textMuted, padding: "24px 12px" }}>
                    {tickets.length === 0
                      ? (esHoy ? "Todavía no hay tickets generados hoy." : "No hay tickets desde ese día.")
                      : "Sin resultados para ese filtro."}
                  </td>
                </tr>
              )}
              {items.map((tk, i) => (
                <tr key={tk.id} style={{ borderTop: `1px solid ${C.border}`, background: i % 2 === 0 ? "#fff" : C.surface }}>
                  <td style={TD}><span style={{ fontFamily: "monospace", fontSize: 12, fontWeight: 600, color: C.primary }}>{tk.folio}</span></td>
                  <td style={{ ...TD, color: C.textSec, fontSize: 12, whiteSpace: "nowrap" }}>{new Date(tk.fecha_hora).toLocaleString("es-MX")}</td>
                  <td style={{ ...TD, textAlign: "right", fontWeight: 600, fontSize: 13, whiteSpace: "nowrap" }}>{fmt(tk.total)}</td>
                  <td style={{ ...TD, textAlign: "center" }}><BadgeTicket estado={tk.estado} /></td>
                  {!isMobile && (
                    <td style={{ ...TD, fontSize: 13, fontFamily: "monospace", whiteSpace: "nowrap" }}>{tk.rfc_receptor || "—"}</td>
                  )}
                  {!isMobile && <td style={{ ...TD, textAlign: "center", fontSize: 13 }}>{tk.n_conceptos}</td>}
                  {!isMobile && (
                    <td style={{ ...TD, fontSize: 12, fontFamily: "monospace", color: C.textSec, whiteSpace: "nowrap" }}>{tk.numero_cliente || "—"}</td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <div style={{ fontSize: 11, color: C.textMuted, marginTop: 8 }}>
        El filtro de fecha trae los tickets <strong>desde ese día en adelante</strong> (no un día exacto).
        Muestra hasta 200 tickets; para un volumen mayor por día habrá que agregar paginación.
      </div>
    </div>
  );
}
