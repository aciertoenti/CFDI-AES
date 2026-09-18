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
  const [cargando, setCargando] = useState(true);
  const [tickets, setTickets] = useState([]);
  const [errorPreview, setErrorPreview] = useState(null);
  const [consolidando, setConsolidando] = useState(false);
  const [resultado, setResultado] = useState(null);
  const [errorConsolidar, setErrorConsolidar] = useState(null);

  useEffect(() => {
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
        // alcance de g5b-kc).
        const hastaSiguienteDia = new Date(`${hasta}T00:00:00Z`);
        hastaSiguienteDia.setUTCDate(hastaSiguienteDia.getUTCDate() + 1);
        const hastaParaQuery = hastaSiguienteDia.toISOString().slice(0, 10);
        const url = `${API_BASE}/facturas/tickets?emisor_rfc=${encodeURIComponent(emisor.rfc)}&estado=pendiente&fecha_desde=${desde}&fecha_hasta=${hastaParaQuery}&size=200`;
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
  }, [emisor.rfc, desde, hasta]);

  const totalPendiente = tickets.reduce((acc, t) => acc + t.total, 0);

  const confirmar = async () => {
    setConsolidando(true); setErrorConsolidar(null);
    try {
      // Sin fecha_desde/fecha_hasta a proposito: el backend resuelve el
      // MISMO periodo que este modal ya mostro en el preview (misma logica
      // exacta, ver periodoActual arriba) - no se manda lo ya calculado
      // aqui para no arriesgar un desfase si el reloj del cliente difiere
      // del servidor.
      const res = await fetchAuth(`${API_BASE}/facturas/consolidar-publico-general`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ emisor_rfc: emisor.rfc }),
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
            <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 8, padding: "10px 12px", marginBottom: 16, fontSize: 13 }}>
              <div style={{ color: C.textSec, marginBottom: 4 }}>
                Periodo ({periodicidad === "diario" ? "diario" : "mensual"}): <strong style={{ color: C.text }}>{desde}</strong> a <strong style={{ color: C.text }}>{hasta}</strong>
              </div>
              {cargando && <div style={{ color: C.textMuted }}>Cargando tickets pendientes…</div>}
              {errorPreview && <div style={{ color: C.danger }}>⚠ {errorPreview}</div>}
              {!cargando && !errorPreview && (
                <div style={{ color: C.text }}>
                  <strong>{tickets.length}</strong> ticket{tickets.length === 1 ? "" : "s"} pendiente{tickets.length === 1 ? "" : "s"} · Total: <strong>{fmt(totalPendiente)}</strong>
                </div>
              )}
            </div>

            {errorConsolidar && <div style={{ fontSize: 12, color: C.danger, marginBottom: 14, padding: "8px 10px", background: C.dangerSoft, borderRadius: 6 }}>⚠ {errorConsolidar}</div>}

            <div style={{ display: "flex", gap: 8 }}>
              <Btn onClick={confirmar} disabled={cargando || consolidando || tickets.length === 0} style={{ flex: 1 }}>
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
