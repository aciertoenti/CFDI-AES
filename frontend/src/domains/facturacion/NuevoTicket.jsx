import { useState } from "react";
import { useToast } from "../../shared/layout/ToastProvider";
import useEmisores from "../../shared/hooks/useEmisores";
import { API_BASE, fetchAuth } from "../../shared/hooks/fetchAuth";
import { SectionTitle, SectionSub, Card, Btn } from "../../shared/components/atoms";
import { C, fmt } from "../../shared/utils/format";

// Sin bloque de Receptor a proposito (zg5b-ZE, POS ligero): el ticket no
// captura nada del cliente - ver el diseno confirmado. cantidad=1 por
// default (caso comun: una pieza), precio_unitario=0 (no hay default
// razonable de precio).
const FILA_VACIA = { descripcion: "", cantidad: 1, precio_unitario: 0 };

export default function NuevoTicket(){
  const toast = useToast();
  // Sin selector de emisor: el ticket siempre es del emisor activo actual
  // (mismo guard de Inactivo que ya usa NuevaFactura.jsx).
  const { emisorActivo: emisor, emisorInactivo } = useEmisores();

  const [conceptos, setConceptos] = useState([{ ...FILA_VACIA }]);
  const [enviando, setEnviando] = useState(false);
  const [resultado, setResultado] = useState(null);

  const actualizarFila = (i, campo, valor) => {
    setConceptos(cs => cs.map((c, idx) => idx === i ? { ...c, [campo]: valor } : c));
  };
  const agregarFila = () => setConceptos(cs => [...cs, { ...FILA_VACIA }]);
  // Nunca deja la lista vacia - si length===1 el boton de quitar ya viene
  // disabled desde el render, esto es la segunda barrera.
  const quitarFila = i => setConceptos(cs => (cs.length === 1 ? cs : cs.filter((_, idx) => idx !== i)));

  // Total en vivo solo para mostrar - el backend recalcula igual y es la
  // fuente de verdad real (mismo principio que timbrar_factura/Factura).
  // Sin desglose de IVA: TicketVenta.total es una suma flat, un ticket no
  // es un documento fiscal.
  const total = conceptos.reduce(
    (acc, c) => acc + (parseFloat(c.cantidad) || 0) * (parseFloat(c.precio_unitario) || 0),
    0,
  );

  const crearTicket = async () => {
    if (!emisor) { toast("No hay ningún emisor registrado en Administración todavía", "error"); return; }
    if (emisorInactivo) { toast("El emisor activo está Inactivo y no puede generar tickets. Reactívalo en Administración › Emisores.", "error"); return; }
    const incompleto = conceptos.some(c => !c.descripcion.trim() || !(parseFloat(c.cantidad) > 0) || !(parseFloat(c.precio_unitario) > 0));
    if (incompleto) {
      toast("Completa descripción, cantidad y precio en todos los conceptos", "warning");
      return;
    }
    setEnviando(true); setResultado(null);
    try {
      const res = await fetchAuth(`${API_BASE}/facturas/tickets`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          emisor_rfc: emisor.rfc,
          conceptos: conceptos.map(c => ({
            descripcion: c.descripcion,
            cantidad: parseFloat(c.cantidad),
            precio_unitario: parseFloat(c.precio_unitario),
          })),
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
      setResultado(data);
      toast(`Ticket generado — folio ${data.folio}`, "success");
    } catch (e) {
      toast(`Error al generar el ticket: ${e.message}`, "error");
    } finally {
      setEnviando(false);
    }
  };

  const otroTicket = () => { setConceptos([{ ...FILA_VACIA }]); setResultado(null); };

  return (
    <div>
      <SectionTitle>Nueva Venta (Ticket)</SectionTitle>
      <SectionSub>Genera un ticket de venta de mostrador — el cliente puede pedir su factura después escaneando el QR del recibo.</SectionSub>
      {emisor && (
        <div style={{fontSize:12,color:C.textSec,marginBottom:12}}>
          Emisor: <strong style={{color:C.text}}>{emisor.razon_social}</strong> ({emisor.rfc})
        </div>
      )}
      {emisorInactivo && (
        <Card style={{marginBottom:12,borderColor:C.danger,background:C.dangerSoft}}>
          <div style={{fontSize:13,color:C.danger,fontWeight:600}}>
            ⚠ El emisor <strong>{emisor.razon_social}</strong> ({emisor.rfc}) está <strong>Inactivo</strong> y no puede generar tickets.
          </div>
          <div style={{fontSize:12,color:C.textSec,marginTop:4}}>
            Ve a <strong>Administración › Emisores</strong> para reactivarlo, o selecciona otro emisor activo en el menú superior.
          </div>
        </Card>
      )}
      <Card>
        <div style={{fontSize:11,fontWeight:700,color:C.accent,letterSpacing:"0.08em",marginBottom:12,textTransform:"uppercase"}}>Conceptos</div>
        {conceptos.map((c, i) => {
          const importe = (parseFloat(c.cantidad) || 0) * (parseFloat(c.precio_unitario) || 0);
          return (
            <div key={i} style={{display:"grid",gridTemplateColumns:"2fr 1fr 1fr 1fr auto",gap:10,marginBottom:10,alignItems:"end"}}>
              <div>
                <label style={{fontSize:12,color:C.textSec,display:"block",marginBottom:3}}>Descripción</label>
                <input value={c.descripcion} onChange={e=>actualizarFila(i,"descripcion",e.target.value)} placeholder="Descripción"
                  style={{width:"100%",border:`1px solid ${C.border}`,borderRadius:8,padding:"8px 11px",fontSize:13,color:C.text,background:"#fff",boxSizing:"border-box"}}/>
              </div>
              <div>
                <label style={{fontSize:12,color:C.textSec,display:"block",marginBottom:3}}>Cantidad</label>
                <input type="number" min="0" value={c.cantidad} onChange={e=>actualizarFila(i,"cantidad",e.target.value)}
                  style={{width:"100%",border:`1px solid ${C.border}`,borderRadius:8,padding:"8px 11px",fontSize:13,color:C.text,background:"#fff",boxSizing:"border-box"}}/>
              </div>
              <div>
                <label style={{fontSize:12,color:C.textSec,display:"block",marginBottom:3}}>Precio unitario</label>
                <input type="number" min="0" value={c.precio_unitario} onChange={e=>actualizarFila(i,"precio_unitario",e.target.value)}
                  style={{width:"100%",border:`1px solid ${C.border}`,borderRadius:8,padding:"8px 11px",fontSize:13,color:C.text,background:"#fff",boxSizing:"border-box"}}/>
              </div>
              <div>
                <label style={{fontSize:12,color:C.textSec,display:"block",marginBottom:3}}>Importe</label>
                <div style={{border:`1px solid ${C.border}`,borderRadius:8,padding:"8px 11px",fontSize:13,color:C.textSec,background:C.surface,boxSizing:"border-box"}}>{fmt(importe)}</div>
              </div>
              <Btn variant="secondary" type="button" disabled={conceptos.length===1} onClick={()=>quitarFila(i)} style={{color:C.danger,padding:"8px 12px"}}>×</Btn>
            </div>
          );
        })}
        <Btn variant="secondary" type="button" onClick={agregarFila}>+ Agregar concepto</Btn>
        <div style={{display:"flex",justifyContent:"flex-end",paddingTop:16,marginTop:16,borderTop:`1px solid ${C.border}`}}>
          <div style={{textAlign:"right"}}>
            <div style={{fontSize:11,color:C.textMuted}}>Total</div>
            <div style={{fontSize:22,fontWeight:700,color:C.accent}}>{fmt(total)}</div>
          </div>
        </div>
      </Card>
      <div style={{marginTop:12,display:"flex",gap:10,flexWrap:"wrap"}}>
        <Btn onClick={crearTicket} disabled={enviando||emisorInactivo}>{enviando?"Generando…":(emisorInactivo?"Emisor Inactivo — no se puede generar":"Generar ticket →")}</Btn>
        {resultado && <Btn variant="secondary" type="button" onClick={otroTicket}>Crear otro ticket</Btn>}
      </div>
      {resultado && (
        <Card style={{marginTop:12,borderColor:C.accentBorder,background:C.accentSoft}}>
          <div style={{fontSize:11,fontWeight:700,color:"#0A6B4A",letterSpacing:"0.08em",marginBottom:12,textTransform:"uppercase"}}>✓ Ticket generado</div>
          <div style={{display:"grid",gridTemplateColumns:"repeat(auto-fit,minmax(150px,1fr))",gap:10,marginBottom:12}}>
            {[["Folio",resultado.folio],["Total",fmt(resultado.total)],["Token QR",resultado.qr_token]].map(([l,v])=>(
              <div key={l} style={{background:"#fff",borderRadius:8,padding:"10px 12px"}}>
                <div style={{fontSize:10,color:C.textMuted,textTransform:"uppercase",letterSpacing:"0.06em",marginBottom:3}}>{l}</div>
                <div style={{fontSize:13,fontWeight:600,color:C.text,wordBreak:"break-all"}}>{v}</div>
              </div>
            ))}
          </div>
          {resultado.pdf_url ? (
            <a href={resultado.pdf_url} target="_blank" rel="noreferrer"><Btn variant="secondary" type="button">Descargar PDF</Btn></a>
          ) : (
            <div style={{fontSize:11,color:C.textMuted}}>
              El PDF no se pudo generar automáticamente — el ticket ya quedó registrado (folio {resultado.folio}).
            </div>
          )}
        </Card>
      )}
    </div>
  );
}
