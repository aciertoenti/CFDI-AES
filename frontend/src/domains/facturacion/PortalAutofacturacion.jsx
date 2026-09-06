// ─── PortalAutofacturacion.jsx ── CFDI-AES · zg5b-ZE pieza 5 ─────────────────
// Portal PUBLICO de autofacturacion individual de un ticket de venta (POS
// ligero). Lo abre quien escaneo el QR impreso en el ticket - SIN sesion,
// SIN JWT: por eso usa fetch() plano (como useAuth.js para login/registro),
// no fetchAuth, y se monta ANTES de AuthGate en App.jsx (ver rutaPublicaFactura).
//
// Backend (ya commiteado, d5b4b8a / 07d45c4 / 0f45f4e):
//   GET  /facturas/tickets/{qr_token}            -> estado + resumen del ticket
//   POST /facturas/tickets/{qr_token}/facturar   -> timbra y devuelve FacturaResponse
//
// Mismo sistema visual que el resto del front: estilos inline + paleta C +
// atoms (Card/Btn) + fmt(). NO hay Tailwind en el proyecto.
import { useEffect, useMemo, useRef, useState } from "react";
import { C, fmt, detalleError } from "../../shared/utils/format";
import { Card, Btn } from "../../shared/components/atoms";
import { API_BASE } from "../../shared/hooks/fetchAuth";
import { CATALOGO_REGIMEN_FISCAL } from "./catalogoRegimenFiscal";
import { CATALOGO_USO_CFDI, usosValidosParaRegimen } from "./catalogoUsoCfdi";

// Mismos 3 usos de la V1 que ya ofrece NuevaFactura.jsx (USOS_V1 alla).
const USOS_V1 = ["G03", "G01", "S01"];

const POLL_MS = 6000;
const POLL_LENTO_TRAS = 10; // ~60s -> cambia el mensaje, NO detiene el polling

// Estados de la maquina (un solo string en state.fase):
//   cargando | pendiente | procesando | facturado | consolidado
//   error_ticket | exito | error_submit
const FORM_VACIO = { rfc: "", nombre: "", regimenFiscal: "", usoCfdi: "", domicilioFiscal: "" };

// ── Estilos estaticos (no dependen de estado) a nivel de modulo ──────────────
const wrap = { maxWidth: 480, margin: "0 auto", padding: 16, minWidth: 0, boxSizing: "border-box" };
const brand = { fontSize: 12, fontWeight: 700, color: C.accent, letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 12 };
const h1 = { fontSize: 20, fontWeight: 700, color: C.text, margin: "0 0 4px" };
const p = { color: C.textSec, fontSize: 13, margin: "0 0 16px" };
const label = { fontSize: 12, color: C.textSec, display: "block", marginBottom: 4, fontWeight: 600 };
const field = { width: "100%", border: `1px solid ${C.border}`, borderRadius: 8, padding: "11px 12px", fontSize: 14, color: C.text, background: "#fff", boxSizing: "border-box", minHeight: 44 };
const fieldGroup = { marginBottom: 14 };
const msgBox = (kind) => ({
  borderRadius: 10, padding: "12px 14px", fontSize: 13, lineHeight: 1.45,
  background: kind === "error" ? C.dangerSoft : kind === "ok" ? C.accentSoft : C.infoSoft,
  color: kind === "error" ? C.danger : kind === "ok" ? "#0A6B4A" : C.info,
  border: `1px solid ${kind === "error" ? "#FEB2B2" : kind === "ok" ? C.accentBorder : "#BEE3F8"}`,
});

// ── ResumenTicket y Formulario: A NIVEL DE MODULO, no dentro del cuerpo de ────
// PortalAutofacturacion. Si se declaran dentro (const Formulario = () => ...),
// cada re-render - y hay uno por CADA TECLA, porque onChange actualiza `form` -
// crea una funcion NUEVA. React ve <Formulario/> como un tipo de componente
// distinto al del render anterior, DESMONTA el <input> y monta uno nuevo: el
// foco se pierde en cada pulsacion (bug real, confirmado en teclado de celular
// Android/Chrome). A nivel de modulo la referencia del componente es estable,
// asi que un re-render solo actualiza el value del mismo <input> y el foco se
// conserva. Reciben por props todo lo que antes leian del closure.
function ResumenTicket({ ticket }) {
  if (!ticket) return null;
  return (
    <Card style={{ marginBottom: 16 }}>
      <div style={{ fontSize: 10, fontWeight: 700, color: C.accent, letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 10 }}>Ticket de venta</div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(130px,1fr))", gap: 8, marginBottom: 10 }}>
        {[["Folio", ticket.folio], ["Fecha", new Date(ticket.fecha_hora).toLocaleString("es-MX")], ["Emisor (RFC)", ticket.emisor_rfc]].map(([l, v]) => (
          <div key={l} style={{ background: C.surface, borderRadius: 8, padding: "8px 10px" }}>
            <div style={{ fontSize: 10, color: C.textMuted, textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 2 }}>{l}</div>
            <div style={{ fontSize: 13, fontWeight: 600, color: C.text, wordBreak: "break-word" }}>{v}</div>
          </div>
        ))}
      </div>
      <div style={{ borderTop: `1px solid ${C.border}`, paddingTop: 8 }}>
        {(ticket.conceptos || []).map((c, i) => (
          <div key={i} style={{ display: "flex", justifyContent: "space-between", gap: 10, fontSize: 13, color: C.textSec, padding: "3px 0" }}>
            <span style={{ minWidth: 0, wordBreak: "break-word" }}>{c.cantidad} × {c.descripcion}</span>
            <span style={{ whiteSpace: "nowrap" }}>{fmt((parseFloat(c.cantidad) || 0) * (parseFloat(c.precio_unitario) || 0))}</span>
          </div>
        ))}
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 12, marginTop: 8, fontSize: 16, fontWeight: 700, color: C.accent }}>
          <span style={{ color: C.textMuted, fontSize: 12, alignSelf: "center" }}>Total</span>{fmt(ticket.total)}
        </div>
      </div>
    </Card>
  );
}

function Formulario({ form, setCampo, usosDisponibles, formCompleto, enviando, errorMsg, fase, onSubmit }) {
  return (
    <form onSubmit={onSubmit} noValidate>
      <div style={fieldGroup}>
        <label htmlFor="pa-rfc" style={label}>RFC</label>
        <input id="pa-rfc" style={field} value={form.rfc} autoCapitalize="characters" autoCorrect="off" spellCheck={false}
          onChange={(e) => setCampo("rfc", e.target.value.toUpperCase())} placeholder="XAXX010101000" />
      </div>
      <div style={fieldGroup}>
        <label htmlFor="pa-nombre" style={label}>Nombre / Razón social</label>
        <input id="pa-nombre" style={field} value={form.nombre}
          onChange={(e) => setCampo("nombre", e.target.value)} placeholder="Como aparece en tu Constancia de Situación Fiscal" />
      </div>
      <div style={fieldGroup}>
        <label htmlFor="pa-regimen" style={label}>Régimen fiscal</label>
        <select id="pa-regimen" style={field} value={form.regimenFiscal}
          onChange={(e) => setCampo("regimenFiscal", e.target.value)}>
          <option value="">Elige tu régimen…</option>
          {Object.entries(CATALOGO_REGIMEN_FISCAL).map(([cod, { desc }]) => (
            <option key={cod} value={cod}>{cod} — {desc}</option>
          ))}
        </select>
      </div>
      <div style={fieldGroup}>
        <label htmlFor="pa-uso" style={label}>Uso de CFDI</label>
        <select id="pa-uso" style={field} value={form.usoCfdi} disabled={!form.regimenFiscal}
          onChange={(e) => setCampo("usoCfdi", e.target.value)}>
          <option value="">{form.regimenFiscal ? "Elige el uso…" : "Elige primero tu régimen"}</option>
          {usosDisponibles.map((clave) => (
            <option key={clave} value={clave}>{clave} — {CATALOGO_USO_CFDI[clave].desc}</option>
          ))}
        </select>
        {form.regimenFiscal && usosDisponibles.length === 0 && (
          <div style={{ fontSize: 12, color: C.warn, marginTop: 4 }}>
            Ninguno de los usos disponibles ({USOS_V1.join(", ")}) aplica a tu régimen fiscal. Verifica el régimen.
          </div>
        )}
      </div>
      <div style={fieldGroup}>
        <label htmlFor="pa-cp" style={label}>Código Postal (domicilio fiscal)</label>
        <input id="pa-cp" style={field} value={form.domicilioFiscal} inputMode="numeric" maxLength={5}
          onChange={(e) => setCampo("domicilioFiscal", e.target.value.replace(/\D/g, ""))} placeholder="00000" />
      </div>

      {fase === "error_submit" && errorMsg && (
        <div style={{ ...msgBox("error"), marginBottom: 14 }} role="alert" aria-live="assertive">{errorMsg}</div>
      )}

      <Btn type="submit" variant="accent" disabled={!formCompleto || enviando}
        style={{ width: "100%", padding: "13px 18px", fontSize: 15, minHeight: 48 }}>
        {enviando ? "Generando factura…" : "Solicitar mi factura"}
      </Btn>
      <div style={{ fontSize: 11, color: C.textMuted, marginTop: 10, textAlign: "center" }}>
        Tus datos solo se usan para timbrar esta factura ante el SAT.
      </div>
    </form>
  );
}

export default function PortalAutofacturacion({ qrToken }) {
  const [fase, setFase] = useState("cargando");
  const [ticket, setTicket] = useState(null);     // respuesta del GET
  const [resultado, setResultado] = useState(null); // FacturaResponse del POST exitoso
  const [errorMsg, setErrorMsg] = useState("");
  const [form, setForm] = useState({ ...FORM_VACIO });
  const [enviando, setEnviando] = useState(false);
  const [pollCount, setPollCount] = useState(0);

  const pollTimer = useRef(null);
  const montado = useRef(true);
  useEffect(() => () => { montado.current = false; if (pollTimer.current) clearInterval(pollTimer.current); }, []);

  // ── GET del ticket ────────────────────────────────────────────────────────
  const aplicarEstado = (data, res) => {
    if (res && res.status === 404) { setFase("error_ticket"); return; }
    if (!res || !res.ok || !data) {
      setErrorMsg("No se pudo cargar el ticket. Revisa tu conexión y recarga la página.");
      setFase("error_ticket");
      return;
    }
    setTicket(data);
    switch (data.estado) {
      case "pendiente": setFase("pendiente"); break;
      case "procesando": setFase("procesando"); break;
      case "facturado_individual": setFase("facturado"); break;
      case "consolidado": setFase("consolidado"); break;
      default:
        // El backend solo devuelve esos 4; cualquier otra cosa es un
        // contrato roto - no arriesgar a mostrar un formulario que no aplica.
        setErrorMsg("No se pudo determinar el estado de este ticket. Recarga la página en un momento.");
        setFase("error_ticket");
    }
  };

  const cargarTicket = async () => {
    try {
      const res = await fetch(`${API_BASE}/facturas/tickets/${encodeURIComponent(qrToken)}`);
      let data = null;
      try { data = await res.json(); } catch { /* respuesta sin cuerpo JSON */ }
      if (!montado.current) return;
      aplicarEstado(data, res);
    } catch {
      if (!montado.current) return;
      setErrorMsg("No se pudo cargar el ticket. Revisa tu conexión y recarga la página.");
      setFase("error_ticket");
    }
  };

  useEffect(() => { cargarTicket(); /* al montar */ }, [qrToken]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Polling mientras 'procesando' ─────────────────────────────────────────
  useEffect(() => {
    if (fase !== "procesando") {
      if (pollTimer.current) { clearInterval(pollTimer.current); pollTimer.current = null; }
      return;
    }
    setPollCount(0);
    pollTimer.current = setInterval(async () => {
      setPollCount((n) => n + 1);
      try {
        const res = await fetch(`${API_BASE}/facturas/tickets/${encodeURIComponent(qrToken)}`);
        let data = null;
        try { data = await res.json(); } catch { /* noop */ }
        if (!montado.current) return;
        if (res.ok && data && data.estado && data.estado !== "procesando") {
          // pendiente (claim liberado / huerfano), facturado_individual, o consolidado
          aplicarEstado(data, res);
        }
      } catch { /* red intermitente: el siguiente tick reintenta */ }
    }, POLL_MS);
    return () => { if (pollTimer.current) { clearInterval(pollTimer.current); pollTimer.current = null; } };
  }, [fase, qrToken]);

  // ── Formulario ───────────────────────────────────────────────────────────
  const usosDisponibles = useMemo(
    () => usosValidosParaRegimen(form.regimenFiscal, USOS_V1),
    [form.regimenFiscal],
  );

  const setCampo = (campo, valor) => {
    setForm((f) => {
      const next = { ...f, [campo]: valor };
      // Si cambia el regimen y el uso ya elegido deja de ser valido, se limpia.
      if (campo === "regimenFiscal") {
        const validos = usosValidosParaRegimen(valor, USOS_V1);
        if (next.usoCfdi && !validos.includes(next.usoCfdi)) next.usoCfdi = "";
      }
      return next;
    });
  };

  const formCompleto =
    form.rfc.trim() && form.nombre.trim() && form.regimenFiscal &&
    form.usoCfdi && form.domicilioFiscal.trim();

  const enviarFactura = async (e) => {
    e.preventDefault();
    if (!formCompleto || enviando) return;
    setEnviando(true);
    setErrorMsg("");
    try {
      const res = await fetch(`${API_BASE}/facturas/tickets/${encodeURIComponent(qrToken)}/facturar`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          rfc: form.rfc.trim().toUpperCase(),
          nombre: form.nombre.trim(),
          regimen_fiscal: form.regimenFiscal,
          uso_cfdi: form.usoCfdi,
          domicilio_fiscal: form.domicilioFiscal.trim(),
        }),
      });
      let data = null;
      try { data = await res.json(); } catch { /* noop */ }
      if (!montado.current) return;

      if (res.ok && data) {
        setResultado(data);
        setFase("exito");
        return;
      }

      const detail = detalleError(data || {}, res);
      let msg;
      if (res.status === 400) msg = `Revisa tus datos fiscales: ${detail}`;
      else if (res.status === 409) msg = "Este ticket ya fue facturado o está en proceso.";
      else if (res.status === 429) msg = "Demasiados intentos, espera unos minutos.";
      else if (res.status === 502) msg = `El SAT rechazó la factura: ${detail}`;
      else msg = "No se pudo generar la factura, intenta de nuevo en unos minutos.";
      setErrorMsg(msg);
      setFase("error_submit");

      // En 409 reintentar el formulario solo daria 409 otra vez: además del
      // mensaje, se re-consulta el ticket para llevar al usuario a la vista
      // terminal real (facturado / procesando / consolidado).
      if (res.status === 409) cargarTicket();
    } catch {
      if (!montado.current) return;
      setErrorMsg("No se pudo generar la factura, intenta de nuevo en unos minutos.");
      setFase("error_submit");
    } finally {
      if (montado.current) setEnviando(false);
    }
  };

  // Props comunes del formulario - se arman una vez por render, pero Formulario
  // es un componente de modulo (tipo estable) asi que esto NO lo remonta.
  const formularioProps = {
    form, setCampo, usosDisponibles, formCompleto, enviando, errorMsg, fase,
    onSubmit: enviarFactura,
  };

  // ── UI ───────────────────────────────────────────────────────────────────
  return (
    <div style={{ background: C.surface, minHeight: "100vh" }}>
      {/* Spinner keyframes: contenido propio, no toca index.css */}
      <style>{`@keyframes pa-spin{to{transform:rotate(360deg)}}`}</style>
      <div style={wrap}>
        <div style={brand}>CFDI-AES · Autofacturación</div>

        {fase === "cargando" && (
          <Card>
            <div style={{ display: "flex", alignItems: "center", gap: 12 }} role="status" aria-live="polite">
              <span style={{ width: 20, height: 20, border: `3px solid ${C.border}`, borderTopColor: C.accent, borderRadius: "50%", display: "inline-block", animation: "pa-spin .8s linear infinite" }} aria-hidden="true" />
              <span style={{ color: C.textSec, fontSize: 14 }}>Cargando tu ticket…</span>
            </div>
          </Card>
        )}

        {fase === "error_ticket" && (
          <Card>
            <h1 style={h1}>No encontramos este ticket</h1>
            <p style={p}>{errorMsg || "El enlace puede estar mal escrito o el ticket ya no está disponible. Verifica el QR impreso en tu ticket."}</p>
          </Card>
        )}

        {fase === "pendiente" && (
          <>
            <h1 style={h1}>Solicita tu factura</h1>
            <p style={p}>Completa tus datos fiscales para generar la factura de esta compra.</p>
            <ResumenTicket ticket={ticket} />
            <Card><Formulario {...formularioProps} /></Card>
          </>
        )}

        {fase === "error_submit" && (
          <>
            <h1 style={h1}>Solicita tu factura</h1>
            <p style={p}>Revisa el mensaje y vuelve a intentarlo. Tus datos siguen aquí.</p>
            <ResumenTicket ticket={ticket} />
            <Card><Formulario {...formularioProps} /></Card>
          </>
        )}

        {fase === "procesando" && (
          <Card>
            <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 10 }}>
              <span style={{ width: 20, height: 20, border: `3px solid ${C.border}`, borderTopColor: C.accent, borderRadius: "50%", display: "inline-block", animation: "pa-spin .8s linear infinite" }} aria-hidden="true" />
              <h1 style={{ ...h1, margin: 0 }}>Generando tu factura</h1>
            </div>
            <div style={msgBox("info")} role="status" aria-live="polite">
              {pollCount < POLL_LENTO_TRAS
                ? "Tu factura se está generando. Esta página se actualizará sola en unos segundos, no la cierres."
                : "Esto está tardando más de lo normal. Por favor recarga la página en un momento."}
            </div>
          </Card>
        )}

        {fase === "facturado" && (
          <Card>
            <div style={{ fontSize: 10, fontWeight: 700, color: "#0A6B4A", letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 8 }}>✓ Ya facturado</div>
            <h1 style={h1}>Este ticket ya fue facturado</h1>
            <p style={p}>
              {ticket?.folio ? <>Folio del ticket: <strong style={{ color: C.text }}>{ticket.folio}</strong>. </> : null}
              Si necesitas el archivo de tu factura y no lo recibiste, contacta al comercio donde compraste.
            </p>
          </Card>
        )}

        {fase === "consolidado" && (
          <Card>
            <h1 style={h1}>Este ticket ya fue incluido en una factura</h1>
            <p style={p}>La venta de este ticket forma parte de una factura consolidada de "Público en General". No es necesario (ni posible) generar una factura individual para él.</p>
          </Card>
        )}

        {fase === "exito" && resultado && (
          <Card style={{ borderColor: C.accentBorder, background: C.accentSoft }}>
            <div style={{ fontSize: 10, fontWeight: 700, color: "#0A6B4A", letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 8 }}>✓ Factura generada</div>
            <h1 style={h1}>¡Listo! Tu factura ya está timbrada</h1>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(140px,1fr))", gap: 8, margin: "12px 0" }}>
              {[["Folio", resultado.folio], ["Total", fmt(resultado.total)], ["UUID", resultado.uuid]].map(([l, v]) => (
                <div key={l} style={{ background: "#fff", borderRadius: 8, padding: "10px 12px" }}>
                  <div style={{ fontSize: 10, color: C.textMuted, textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 3 }}>{l}</div>
                  <div style={{ fontSize: 13, fontWeight: 600, color: C.text, wordBreak: "break-all" }}>{v}</div>
                </div>
              ))}
            </div>
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
              {resultado.pdf_url && (
                <a href={resultado.pdf_url} target="_blank" rel="noreferrer" style={{ textDecoration: "none" }}>
                  <Btn type="button" variant="primary" style={{ minHeight: 44 }}>Descargar PDF</Btn>
                </a>
              )}
              {resultado.xml_url && (
                <a href={resultado.xml_url} target="_blank" rel="noreferrer" style={{ textDecoration: "none" }}>
                  <Btn type="button" variant="secondary" style={{ minHeight: 44 }}>Descargar XML</Btn>
                </a>
              )}
            </div>
            <div style={{ fontSize: 11, color: C.textMuted, marginTop: 12 }}>
              Guarda ambos archivos. El PDF es tu comprobante visual; el XML es el documento fiscal válido ante el SAT.
            </div>
          </Card>
        )}
      </div>
    </div>
  );
}
