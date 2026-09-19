import { useEffect, useState } from "react";
import { API_BASE, fetchAuth } from "../../shared/hooks/fetchAuth";
import { Btn, Card } from "../../shared/components/atoms";
import { C, fmt, detalleError } from "../../shared/utils/format";

// Resuelve "el periodo vencido actual" - MISMA logica exacta que el backend
// (facturacion/main.py, consolidar_publico_general) usa cuando no se manda
// fecha_desde/fecha_hasta explicito. Si se toca una, hay que tocar la otra -
// documentado en ambos lados.
function periodoActual(periodicidad) {
  const hoy = new Date();
  const hoyStr = hoy.toISOString().slice(0, 10);
  if (periodicidad === "diario") return { desde: hoyStr, hasta: hoyStr };
  const primerDiaMes = new Date(hoy.getFullYear(), hoy.getMonth(), 1).toISOString().slice(0, 10);
  return { desde: primerDiaMes, hasta: hoyStr };
}

export default function ConsolidarPublicoGeneralModal({ emisor, onCerrar, recargar }) {
  const periodicidad = emisor.periodicidad_consolidacion;
  const { desde, hasta } = periodoActual(periodicidad);

  // Rango manual (opcional, colapsado por default) - caso real que lo
  // motiva: backlog de tickets pendientes de semanas atras que nunca
  // entran en el periodo "vencido actual" (diario=hoy). Inicializado UNA
  // vez con el periodo automatico (useState lazy, no se resetea si el
  // usuario colapsa/expande el toggle - no se le pierde lo que ya
  // escribio). Mientras rangoManualActivo es false, el comportamiento es
  // IDENTICO al de antes (sin regresion): mismas fechas automaticas,
  // mismo POST sin fecha_desde/fecha_hasta.
  const [mostrarRangoManual, setMostrarRangoManual] = useState(false);
  const [desdeManual, setDesdeManual] = useState(() => desde);
  const [hastaManual, setHastaManual] = useState(() => hasta);
  const rangoInvalido = mostrarRangoManual && hastaManual < desdeManual;

  const desdeEfectivo = mostrarRangoManual ? desdeManual : desde;
  const hastaEfectivo = mostrarRangoManual ? hastaManual : hasta;

  const [cargando, setCargando] = useState(true);
  const [tickets, setTickets] = useState([]);
  const [errorPreview, setErrorPreview] = useState(null);
  const [consolidando, setConsolidando] = useState(false);
  const [resultado, setResultado] = useState(null);
  const [errorConsolidar, setErrorConsolidar] = useState(null);

  useEffect(() => {
    // Rango manual invalido (hasta < desde): no se consulta el preview -
    // mismo error que rechazaria el backend, mostrado antes de gastar una
    // llamada de red.
    if (rangoInvalido) { setTickets([]); setCargando(false); setErrorPreview(null); return; }
    let cancelado = false;
    (async () => {
      setCargando(true); setErrorPreview(null);
      try {
        // GET /facturas/tickets (endpoint preexistente, reutilizado tal cual
        // para el preview) compara fecha_hasta contra fecha_hora con <=
        // literal - Postgres lo trata como medianoche exacta de ese dia, NO
        // como "todo el dia" (a diferencia del endpoint nuevo de
        // consolidar, que SI usa un limite exclusivo de +1 dia). Para que
        // el preview cuente lo mismo que el POST real va a consolidar, se
        // pide fecha_hasta+1 dia aqui tambien - mismo ajuste, aplicado del
        // lado del cliente porque no se toca listar_tickets (fuera de
        // alcance de g5b-kc). Se aplica igual sobre hastaEfectivo (automatico
        // o manual, el que este activo).
        const hastaSiguienteDia = new Date(`${hastaEfectivo}T00:00:00Z`);
        hastaSiguienteDia.setUTCDate(hastaSiguienteDia.getUTCDate() + 1);
        const hastaParaQuery = hastaSiguienteDia.toISOString().slice(0, 10);
        const url = `${API_BASE}/facturas/tickets?emisor_rfc=${encodeURIComponent(emisor.rfc)}&estado=pendiente&fecha_desde=${desdeEfectivo}&fecha_hasta=${hastaParaQuery}&size=200`;
        const res = await fetchAuth(url);
        const data = await res.json().catch(() => ([]));
        if (!res.ok) throw new Error(detalleError(data, res));
        if (!cancelado) setTickets(data);
      } catch (e) {
        if (!cancelado) setErrorPreview(e.message);
      } finally {
        if (!cancelado) setCargando(false);
      }
    })();
    return () => { cancelado = true; };
  }, [emisor.rfc, desdeEfectivo, hastaEfectivo, rangoInvalido]);

  const totalPendiente = tickets.reduce((acc, t) => acc + t.total, 0);

  const confirmar = async () => {
    if (rangoInvalido) return; // guard extra - el boton ya queda disabled
    setConsolidando(true); setErrorConsolidar(null);
    try {
      // Sin rango manual activo: NO se manda fecha_desde/fecha_hasta a
      // proposito (comportamiento identico a antes de este cambio) - el
      // backend resuelve el MISMO periodo que este modal ya mostro en el
      // preview (misma logica exacta, ver periodoActual arriba), sin
      // arriesgar un desfase si el reloj del cliente difiere del servidor.
      // CON rango manual activo: se manda el rango explicito elegido - el
      // backend lo usa tal cual, ganando sobre el calculo automatico
      // (ya implementado en g5b-kc, sin cambios de backend para esto).
      const body = mostrarRangoManual
        ? { emisor_rfc: emisor.rfc, fecha_desde: desdeManual, fecha_hasta: hastaManual }
        : { emisor_rfc: emisor.rfc };
      const res = await fetchAuth(`${API_BASE}/facturas/consolidar-publico-general`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(detalleError(data, res));
      setResultado(data);
      if (data.consolidado) recargar?.();
    } catch (e) {
      setErrorConsolidar(e.message);
    } finally {
      setConsolidando(false);
    }
  };

  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(3,6,18,.5)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 120 }} onClick={onCerrar}>
      <Card style={{ width: 420, maxWidth: "calc(100vw - 24px)", maxHeight: "calc(100vh - 40px)", overflowY: "auto", position: "relative" }} onClick={e => e.stopPropagation()}>
        <div style={{ fontSize: 16, fontWeight: 700, color: C.text, marginBottom: 4 }}>Consolidar Público en General</div>
        <div style={{ fontSize: 12, color: C.textMuted, fontFamily: "monospace", marginBottom: 16 }}>{emisor.rfc}</div>

        {!resultado && (
          <>
            <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 8, padding: "10px 12px", marginBottom: 12, fontSize: 13 }}>
              <div style={{ color: C.textSec, marginBottom: 4 }}>
                Periodo ({mostrarRangoManual ? "rango manual" : (periodicidad === "diario" ? "diario" : "mensual")}): <strong style={{ color: C.text }}>{desdeEfectivo}</strong> a <strong style={{ color: C.text }}>{hastaEfectivo}</strong>
              </div>
              {rangoInvalido && <div style={{ color: C.danger }}>⚠ La fecha "hasta" no puede ser anterior a "desde".</div>}
              {!rangoInvalido && cargando && <div style={{ color: C.textMuted }}>Cargando tickets pendientes…</div>}
              {!rangoInvalido && errorPreview && <div style={{ color: C.danger }}>⚠ {errorPreview}</div>}
              {!rangoInvalido && !cargando && !errorPreview && (
                <div style={{ color: C.text }}>
                  <strong>{tickets.length}</strong> ticket{tickets.length === 1 ? "" : "s"} pendiente{tickets.length === 1 ? "" : "s"} · Total: <strong>{fmt(totalPendiente)}</strong>
                </div>
              )}
            </div>

            {!mostrarRangoManual ? (
              <button
                type="button"
                onClick={() => setMostrarRangoManual(true)}
                style={{ background: "none", border: "none", padding: 0, marginBottom: 16, fontSize: 12, color: C.textMuted, textDecoration: "underline", cursor: "pointer" }}
              >
                Elegir un rango de fechas distinto
              </button>
            ) : (
              <div style={{ marginBottom: 16 }}>
                <div style={{ display: "flex", gap: 8, marginBottom: 6 }}>
                  <label style={{ flex: 1, fontSize: 12, color: C.textSec }}>
                    Desde
                    <input
                      type="date"
                      value={desdeManual}
                      onChange={e => setDesdeManual(e.target.value)}
                      style={{ display: "block", width: "100%", marginTop: 3, padding: "6px 8px", borderRadius: 6, border: `1px solid ${C.border}`, fontSize: 13, boxSizing: "border-box" }}
                    />
                  </label>
                  <label style={{ flex: 1, fontSize: 12, color: C.textSec }}>
                    Hasta
                    <input
                      type="date"
                      value={hastaManual}
                      onChange={e => setHastaManual(e.target.value)}
                      style={{ display: "block", width: "100%", marginTop: 3, padding: "6px 8px", borderRadius: 6, border: `1px solid ${C.border}`, fontSize: 13, boxSizing: "border-box" }}
                    />
                  </label>
                </div>
                <button
                  type="button"
                  onClick={() => setMostrarRangoManual(false)}
                  style={{ background: "none", border: "none", padding: 0, fontSize: 12, color: C.textMuted, textDecoration: "underline", cursor: "pointer" }}
                >
                  Usar periodo automático ({periodicidad === "diario" ? "diario" : "mensual"})
                </button>
              </div>
            )}

            {errorConsolidar && <div style={{ fontSize: 12, color: C.danger, marginBottom: 14, padding: "8px 10px", background: C.dangerSoft, borderRadius: 6 }}>⚠ {errorConsolidar}</div>}

            <div style={{ display: "flex", gap: 8 }}>
              <Btn onClick={confirmar} disabled={rangoInvalido || cargando || consolidando || tickets.length === 0} style={{ flex: 1 }}>
                {consolidando ? "Consolidando…" : `Consolidar ${tickets.length || ""} ticket${tickets.length === 1 ? "" : "s"}`.trim()}
              </Btn>
              <Btn type="button" variant="secondary" onClick={onCerrar} disabled={consolidando}>Cancelar</Btn>
            </div>
          </>
        )}

        {resultado && !resultado.consolidado && (
          <>
            <div style={{ fontSize: 13, color: C.textSec, marginBottom: 16, padding: "8px 10px", background: C.surface, borderRadius: 6 }}>
              {resultado.mensaje || "Sin tickets pendientes en el periodo."}
            </div>
            <Btn onClick={onCerrar} style={{ width: "100%" }}>Cerrar</Btn>
          </>
        )}

        {resultado && resultado.consolidado && (
          <Card style={{ borderColor: C.accentBorder, background: C.accentSoft }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: "#0A6B4A", letterSpacing: "0.08em", marginBottom: 12, textTransform: "uppercase" }}>✓ Consolidado exitosamente</div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(140px,1fr))", gap: 10, marginBottom: 12 }}>
              {[["UUID", resultado.factura?.uuid], ["Folio", resultado.factura?.folio], ["Tickets incluidos", resultado.n_tickets], ["Total (IVA incluido)", fmt(resultado.total)]].map(([l, v]) => (
                <div key={l} style={{ background: "#fff", borderRadius: 8, padding: "10px 12px" }}>
                  <div style={{ fontSize: 10, color: C.textMuted, textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 3 }}>{l}</div>
                  <div style={{ fontSize: 13, fontWeight: 600, color: C.text, wordBreak: "break-all" }}>{v}</div>
                </div>
              ))}
            </div>
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
              {resultado.factura?.xml_url && <a href={resultado.factura.xml_url} target="_blank" rel="noreferrer"><Btn variant="secondary">Descargar XML</Btn></a>}
              {resultado.factura?.pdf_url && <a href={resultado.factura.pdf_url} target="_blank" rel="noreferrer"><Btn variant="secondary">Descargar PDF</Btn></a>}
              <Btn variant="secondary" onClick={onCerrar}>Cerrar</Btn>
            </div>
          </Card>
        )}
      </Card>
    </div>
  );
}
