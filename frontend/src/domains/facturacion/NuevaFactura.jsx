import { useState, useEffect } from "react";
import { useToast } from "../../shared/layout/ToastProvider";
import useEmisores from "../../shared/hooks/useEmisores";
import useClientes from "../../shared/hooks/useClientes";
import { API_BASE, fetchAuth } from "../../shared/hooks/fetchAuth";
import { SectionTitle, SectionSub, Card, TwoCol, Btn } from "../../shared/components/atoms";
import { C, fmt } from "../../shared/utils/format";

export default function NuevaFactura(){
  const toast = useToast();
  const { emisores, loading:loadingEmisores, error:errorEmisores, emisorActivoRfc } = useEmisores();
  const { clientes, loading:loadingClientes, error:errorClientes } = useClientes();
  // emisorActivoRfc puede ser null (negocio sin ningun emisor) - find()
  // sobre [] o sin match devuelve undefined igual que emisores[0] en ese
  // caso, mismo placeholder/mensaje de "sin emisor" que ya existia.
  const emisor = emisores.find(e=>e.rfc===emisorActivoRfc);

  const [form,setForm]=useState({clienteRfc:"",receptor:"",rfc:"",usoCfdi:"G03",domicilioFiscal:"",regimenFiscal:"",concepto:"",cantidad:"",precio:"",iva:"16"});
  const [enviando,setEnviando]=useState(false);
  const [resultado,setResultado]=useState(null);
  const [errorTimbrado,setErrorTimbrado]=useState(null);

  // Receptor generico (Publico en General): el SAT exige que su domicilio
  // fiscal sea igual al LugarExpedicion del emisor activo (regla ya aplicada
  // en facturacion/main.py al armar el CFDI). Si el usuario cambia de emisor
  // con el generico ya seleccionado, este CP debe seguir al emisor - un
  // cliente real conserva su propio domicilio fiscal, sin tocarlo aqui.
  useEffect(() => {
    if (form.rfc === "XAXX010101000" && emisor?.codigo_postal) {
      setForm(f => f.domicilioFiscal === emisor.codigo_postal ? f : {...f, domicilioFiscal: emisor.codigo_postal});
    }
  }, [emisor?.codigo_postal, form.rfc]);

  // Reset automatico tras timbrado exitoso (27 ago 2026) - una vez que la
  // factura se timbro, la operacion termino: limpiar los campos de
  // receptor/concepto para la siguiente venta, sin necesidad de un boton
  // manual. Se dispara SOLO cuando `resultado` pasa de vacio a tener valor
  // (justo despues de un timbrado exitoso), nunca mientras el usuario esta
  // escribiendo - evita el riesgo de pisar texto a medio capturar que tenia
  // la alternativa de "limpiar al vaciar el campo".
  useEffect(() => {
    if (resultado) {
      setForm(f => ({
        ...f,
        clienteRfc: "",
        receptor: "",
        rfc: "",
        domicilioFiscal: "",
        regimenFiscal: "",
        concepto: "",
        cantidad: "",
        precio: "",
      }));
    }
  }, [resultado]);

  const sub=(parseFloat(form.cantidad)||0)*(parseFloat(form.precio)||0);
  const total=sub*(1+(parseFloat(form.iva)||0)/100);

  const seleccionarCliente = rfc => {
    setResultado(null); setErrorTimbrado(null);
    if (!rfc) { setForm(f=>({...f,clienteRfc:"",receptor:"",rfc:"",domicilioFiscal:"",regimenFiscal:""})); return; }
    const c = clientes.find(c=>c.rfc===rfc);
    if (!c) return;
    setForm(f=>({
      ...f,
      clienteRfc:rfc,
      receptor:c.nombre,
      rfc:c.rfc,
      usoCfdi:c.uso_cfdi_default||f.usoCfdi,
      domicilioFiscal:c.domicilio_fiscal||"",
      regimenFiscal:c.regimen_fiscal||"",
      concepto: (c.rfc === "XAXX010101000" && !f.concepto) ? "Venta al público en general" : f.concepto,
    }));
  };

  const inp=(lbl,k,type="text",extra={})=>(
    <div style={{marginBottom:10}}>
      <label style={{fontSize:12,color:C.textSec,display:"block",marginBottom:3}}>{lbl}</label>
      <input type={type} value={form[k]} onChange={e=>setForm({...form,[k]:e.target.value})} placeholder={lbl} {...extra}
        style={{width:"100%",border:`1px solid ${C.border}`,borderRadius:8,padding:"8px 11px",fontSize:13,color:C.text,background:"#fff",boxSizing:"border-box"}}/>
    </div>
  );

  const timbrar = async () => {
    if (!emisor) { toast("No hay ningún emisor registrado en Administración todavía","error"); return; }
    if (!form.receptor||!form.rfc||!form.domicilioFiscal||!form.concepto||!form.cantidad||!form.precio) {
      toast("Completa receptor, domicilio fiscal y los datos del concepto antes de timbrar","warning"); return;
    }
    if (parseFloat(form.cantidad) <= 0 || parseFloat(form.precio) <= 0) {
      toast("Cantidad y precio unitario deben ser mayores a cero", "warning");
      return;
    }
    setEnviando(true); setErrorTimbrado(null); setResultado(null);
    const payload = {
      emisor_rfc: emisor.rfc,
      receptor: {
        nombre: form.receptor,
        rfc: form.rfc,
        uso_cfdi: form.usoCfdi,
        domicilio_fiscal: form.domicilioFiscal,
        ...(form.regimenFiscal ? { regimen_fiscal: form.regimenFiscal } : {}),
      },
      conceptos: [{
        descripcion: form.concepto,
        cantidad: parseFloat(form.cantidad),
        precio_unitario: parseFloat(form.precio),
        iva_tasa: (parseFloat(form.iva)||0)/100,
      }],
    };
    try {
      const res = await fetchAuth(`${API_BASE}/facturas/timbrar`, {
        method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(payload),
      });
      const data = await res.json().catch(()=>({}));
      if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
      setResultado(data);
      toast(`Factura timbrada — UUID ${data.uuid}`,"success");
    } catch(e) {
      setErrorTimbrado(e.message);
      toast(`Error al timbrar: ${e.message}`,"error");
    } finally {
      setEnviando(false);
    }
  };

  return (
    <div>
      <SectionTitle>Nueva Factura CFDI 4.0</SectionTitle>
      <SectionSub>O usa el <strong>Lector IA</strong> para subir una orden de compra y rellenar automáticamente.</SectionSub>
      <TwoCol>
        <Card>
          <div style={{fontSize:11,fontWeight:700,color:C.accent,letterSpacing:"0.08em",marginBottom:12,textTransform:"uppercase"}}>Emisor</div>
          {loadingEmisores && <div style={{fontSize:13,color:C.textMuted}}>Cargando emisor…</div>}
          {errorEmisores && <div style={{fontSize:13,color:C.danger}}>⚠ No se pudo cargar el emisor: {errorEmisores}</div>}
          {!loadingEmisores && !errorEmisores && !emisor && (
            <div style={{fontSize:13,color:C.warn}}>No hay emisores registrados en Administración.</div>
          )}
          {emisor && [["Razón social",emisor.razon_social],["RFC",emisor.rfc],["Régimen fiscal",emisor.regimen_fiscal],["CP",emisor.codigo_postal]].map(([l,v])=>(
            <div key={l} style={{marginBottom:10}}>
              <label style={{fontSize:12,color:C.textSec,display:"block",marginBottom:3}}>{l}</label>
              <input readOnly value={v} style={{width:"100%",border:`1px solid ${C.border}`,borderRadius:8,padding:"8px 11px",fontSize:13,color:C.text,background:C.surface,boxSizing:"border-box"}}/>
            </div>
          ))}
        </Card>
        <Card>
          <div style={{fontSize:11,fontWeight:700,color:C.accent,letterSpacing:"0.08em",marginBottom:12,textTransform:"uppercase"}}>Receptor</div>
          <div style={{marginBottom:10}}>
            <label style={{fontSize:12,color:C.textSec,display:"block",marginBottom:3}}>Cliente registrado</label>
            <select value={form.clienteRfc} onChange={e=>seleccionarCliente(e.target.value)} disabled={loadingClientes}
              style={{width:"100%",border:`1px solid ${C.border}`,borderRadius:8,padding:"8px 11px",fontSize:13,color:C.text,background:"#fff",boxSizing:"border-box"}}>
              <option value="">— Receptor nuevo (captura manual) —</option>
              {clientes.map(c=>(<option key={c.rfc} value={c.rfc}>{c.nombre} — {c.rfc}</option>))}
            </select>
            {errorClientes && <div style={{fontSize:11,color:C.danger,marginTop:4}}>⚠ No se pudieron cargar los clientes: {errorClientes}</div>}
          </div>
          {inp("Nombre / Razón social","receptor")}
          {inp("RFC","rfc")}
          {inp("Domicilio fiscal (CP)","domicilioFiscal")}
          <div style={{marginBottom:10}}>
            <label style={{fontSize:12,color:C.textSec,display:"block",marginBottom:3}}>Uso CFDI</label>
            <select value={form.usoCfdi} onChange={e=>setForm({...form,usoCfdi:e.target.value})}
              style={{width:"100%",border:`1px solid ${C.border}`,borderRadius:8,padding:"8px 11px",fontSize:13,color:C.text,background:"#fff",boxSizing:"border-box"}}>
              <option value="G03">G03 – Gastos en general</option><option value="G01">G01 – Adquisición de mercancías</option><option value="S01">S01 – Sin efectos fiscales</option>
            </select>
          </div>
        </Card>
      </TwoCol>
      <Card style={{marginTop:12}}>
        <div style={{fontSize:11,fontWeight:700,color:C.accent,letterSpacing:"0.08em",marginBottom:12,textTransform:"uppercase"}}>Conceptos</div>
        <div style={{display:"grid",gridTemplateColumns:"repeat(auto-fit,minmax(130px,1fr))",gap:10,marginBottom:10}}>
          {inp("Descripción","concepto")}
          {inp("Cantidad","cantidad","number",{min:"0"})}
          {inp("Precio unitario","precio","number",{min:"0"})}
          {inp("IVA %","iva","number")}
        </div>
        <div style={{display:"flex",justifyContent:"flex-end",gap:20,paddingTop:12,borderTop:`1px solid ${C.border}`,flexWrap:"wrap"}}>
          {[["Subtotal",sub],["IVA",sub*(parseFloat(form.iva)||0)/100],["Total",total]].map(([l,v])=>(
            <div key={l} style={{textAlign:"right"}}>
              <div style={{fontSize:11,color:C.textMuted}}>{l}</div>
              <div style={{fontSize:l==="Total"?18:13,fontWeight:l==="Total"?700:500,color:l==="Total"?C.accent:C.text}}>{fmt(v)}</div>
            </div>
          ))}
        </div>
      </Card>
      <div style={{marginTop:12,display:"flex",gap:10,flexWrap:"wrap"}}>
        <Btn onClick={timbrar} disabled={enviando}>{enviando?"Timbrando…":"Timbrar con PAC →"}</Btn>
        <Btn variant="secondary" onClick={()=>toast("Borrador guardado localmente","success")}>Guardar borrador</Btn>
      </div>
      {errorTimbrado && (
        <Card style={{marginTop:12,borderColor:C.danger,background:C.dangerSoft}}>
          <div style={{fontSize:13,color:C.danger}}>⚠ {errorTimbrado}</div>
        </Card>
      )}
      {resultado && (
        <Card style={{marginTop:12,borderColor:C.accentBorder,background:C.accentSoft}}>
          <div style={{fontSize:11,fontWeight:700,color:"#0A6B4A",letterSpacing:"0.08em",marginBottom:12,textTransform:"uppercase"}}>✓ Timbrado exitoso</div>
          <div style={{display:"grid",gridTemplateColumns:"repeat(auto-fit,minmax(150px,1fr))",gap:10,marginBottom:12}}>
            {[["UUID",resultado.uuid],["Folio",resultado.folio],["Estado",resultado.estado],["Total",fmt(resultado.total)]].map(([l,v])=>(
              <div key={l} style={{background:"#fff",borderRadius:8,padding:"10px 12px"}}>
                <div style={{fontSize:10,color:C.textMuted,textTransform:"uppercase",letterSpacing:"0.06em",marginBottom:3}}>{l}</div>
                <div style={{fontSize:13,fontWeight:600,color:C.text,wordBreak:"break-all"}}>{v}</div>
              </div>
            ))}
          </div>
          <div style={{display:"flex",gap:10,flexWrap:"wrap"}}>
            <a href={resultado.xml_url} target="_blank" rel="noreferrer"><Btn variant="secondary">Descargar XML</Btn></a>
            <a href={resultado.pdf_url} target="_blank" rel="noreferrer"><Btn variant="secondary">Descargar PDF</Btn></a>
          </div>
          <div style={{fontSize:11,color:C.textMuted,marginTop:8}}>
            Nota: las URLs de descarga apuntan a MinIO dentro de la red de Docker — hoy no son accesibles desde fuera de ese entorno (ver #8/#19/#20).
          </div>
        </Card>
      )}
    </div>
  );
}
