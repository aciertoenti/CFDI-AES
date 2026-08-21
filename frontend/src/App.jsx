// ─── App.jsx ── CFDI-AES · Responsive + Toast + Table fix ─────────────────────
import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import logoAcierto from "./assets/logo-acierto.png";
import useAuth from "./shared/hooks/useAuth";
import useBreakpoint from "./shared/hooks/useBreakpoint";
import { API_BASE, fetchAuth } from "./shared/hooks/fetchAuth";
import useEmisores, { EmisoresProvider } from "./shared/hooks/useEmisores";
import useClientes from "./shared/hooks/useClientes";
import useResumenEjecutivo from "./shared/hooks/useResumenEjecutivo";
import { useToast, ToastProvider } from "./shared/layout/ToastProvider";
import AppShell, { Placeholder } from "./shared/layout/AppShell";
import { Badge, Card, Btn, TwoCol, KPI, KPIGrid } from "./shared/components/atoms";
import { C, fmt, detalleError } from "./shared/utils/format";
import Login from "./domains/auth/Login";
import OlvideContrasena from "./domains/auth/OlvideContrasena";
import ResetPassword from "./domains/auth/ResetPassword";
import CrearCuenta from "./domains/auth/CrearCuenta";
import Clientes from "./domains/administracion/Clientes";
import AltaEmisorForm from "./domains/administracion/AltaEmisorForm";
import Emisores from "./domains/administracion/Emisores";
import Series from "./domains/administracion/Series";
import Usuarios from "./domains/administracion/Usuarios";

// ═══════════════════════════════════════════════════════════════════════════════
// HOOKS IA
// ═══════════════════════════════════════════════════════════════════════════════
// Los 4 endpoints de IA ya pasan por el Gateway via API_BASE (13 ago 2026,
// rewiring de IA) - antes usaban IA_BASE directo al microservicio, sin JWT
// (ver #48/#65). useFiscalChat usa una ruta dedicada del Gateway
// (/ia/chat/stream) en vez del proxy generico, por el streaming SSE.
// FACTURACION_BASE/ADMINISTRACION_BASE/AUTH_BASE ya no se usan para fetch
// real (ver #48) - se dejan solo porque siguen apareciendo en textos de
// error (ej. "No se pudo conectar con administracion (${ADMINISTRACION_BASE})").
const FACTURACION_BASE = "http://localhost:8001";
const ADMINISTRACION_BASE = "http://localhost:8002";
const AUTH_BASE = "http://localhost:8005";

function useDocumentExtractor() {
  const [loading, setLoading] = useState(false);
  const [result,  setResult]  = useState(null);
  const [error,   setError]   = useState(null);
  const [steps,   setSteps]   = useState([]);
  const extraer = useCallback(async (file) => {
    setLoading(true); setError(null); setResult(null); setSteps([]);
    const labels = ["Leyendo documento…","IA identificando campos fiscales…","Validando RFC en SAT…","Construyendo borrador CFDI…"];
    labels.forEach((l, i) => setTimeout(() => setSteps(p => [...p, l]), i * 900));
    try {
      const fd = new FormData(); fd.append("file", file);
      const res = await fetchAuth(`${API_BASE}/ia/extraer-documento`, { method:"POST", body:fd });
      if (!res.ok) throw new Error((await res.json()).detail || "Error");
      const data = await res.json(); setResult(data); return data;
    } catch(e) { setError(e.message); } finally { setLoading(false); }
  }, []);
  return { extraer, loading, result, error, steps };
}

function useFiscalChat() {
  const [messages,  setMessages]  = useState([]);
  const [streaming, setStreaming] = useState(false);
  const abortRef = useRef(null);
  const send = useCallback(async (text, ctx = {}, modo = "cuenta") => {
    const history = [...messages, { role:"user", content:text }];
    setMessages([...history, { role:"assistant", content:"" }]);
    setStreaming(true);
    abortRef.current = new AbortController();
    try {
      // Ruta dedicada del Gateway (13 ago 2026, rewiring de IA) - no pasa por
      // el proxy() generico (StreamingResponse no funciona con resp.json()).
      // fetchAuth() sigue sirviendo tal cual: solo agrega el header
      // Authorization, la respuesta que devuelve es el mismo objeto Response
      // que fetch() normal, asi que res.body.getReader() de abajo no cambia.
      // modo "general" (20 ago 2026, tarjeta 2mSpU) - contexto_cuenta ni
      // siquiera se incluye en el body, no solo se manda vacio, para que
      // quede honesto en Network tab que no se envio nada de la cuenta.
      const res = await fetchAuth(`${API_BASE}/ia/chat/stream`, {
        method:"POST", headers:{"Content-Type":"application/json"},
        signal:abortRef.current.signal,
        body: JSON.stringify({
          messages:history,
          modo,
          ...(modo === "cuenta" ? { contexto_cuenta: ctx } : {}),
        }),
      });
      const reader = res.body.getReader(); const dec = new TextDecoder(); let buf = "";
      while (true) {
        const { done, value } = await reader.read(); if (done) break;
        buf += dec.decode(value, { stream:true });
        const lines = buf.split("\n"); buf = lines.pop();
        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const raw = line.slice(6).trim(); if (raw === "[DONE]") break;
          try { const { token } = JSON.parse(raw); setMessages(p => { const u=[...p]; u[u.length-1]={role:"assistant",content:u[u.length-1].content+token}; return u; }); } catch {}
        }
      }
    } catch(e) { if (e.name !== "AbortError") setMessages(p => p.slice(0,-1)); }
    finally { setStreaming(false); }
  }, [messages]);
  return { messages, send, streaming, reset:()=>setMessages([]), abort:()=>{ abortRef.current?.abort(); setStreaming(false); } };
}

function useFacturas(emisorRfc) {
  const [facturas, setFacturas] = useState([]);
  const [loading,  setLoading]  = useState(true);
  const [error,    setError]    = useState(null);
  const cargar = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      // emisorRfc opcional (#soporte multi-emisor) - sin el, comportamiento
      // identico al de siempre (todas las facturas del negocio). Se agrega
      // a las dependencias del useCallback a proposito: si cambia (ej. el
      // usuario cambia de emisor activo en el header/Emisores), cargar()
      // cambia de identidad y el useEffect de abajo vuelve a disparar el
      // fetch con el nuevo filtro.
      const url = emisorRfc ? `${API_BASE}/facturas?emisor_rfc=${encodeURIComponent(emisorRfc)}` : `${API_BASE}/facturas`;
      const res = await fetchAuth(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setFacturas(await res.json());
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  }, [emisorRfc]);
  useEffect(() => { cargar(); }, [cargar]);
  return { facturas, loading, error, recargar: cargar };
}

function useCostosResumen(emisorRfc) {
  const [datos,   setDatos]   = useState([]);
  const [loading, setLoading] = useState(true);
  const [error,   setError]   = useState(null);
  const cargar = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      // emisorRfc opcional (#soporte multi-emisor, mismo patron que
      // useFacturas) - el backend ya filtra por negocio de todos modos
      // (fix critico de aislamiento), esto es solo para el desglose del
      // emisor activo especifico cuando el negocio tiene varios.
      const url = emisorRfc ? `${API_BASE}/facturas/costos-resumen?emisor_rfc=${encodeURIComponent(emisorRfc)}` : `${API_BASE}/facturas/costos-resumen`;
      const res = await fetchAuth(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setDatos(await res.json());
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  }, [emisorRfc]);
  useEffect(() => { cargar(); }, [cargar]);
  return { datos, loading, error, recargar: cargar };
}

function useContadorVirtualISRResico(emisorRfc, anio, mes) {
  const [datos,   setDatos]   = useState(null);
  const [loading, setLoading] = useState(true);
  const [error,   setError]   = useState(null);
  useEffect(() => {
    if (!emisorRfc) { setLoading(false); return; }
    (async () => {
      setLoading(true); setError(null);
      try {
        const params = new URLSearchParams({ emisor_rfc: emisorRfc, anio: String(anio), mes: String(mes) });
        const res = await fetchAuth(`${API_BASE}/facturas/contador-virtual/isr-resico?${params}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        setDatos(await res.json());
      } catch (e) { setError(e.message); }
      finally { setLoading(false); }
    })();
  }, [emisorRfc, anio, mes]);
  return { datos, loading, error };
}

function useSeries() {
  const [series,  setSeries]  = useState([]);
  const [loading, setLoading] = useState(true);
  const [error,   setError]   = useState(null);
  useEffect(() => {
    (async () => {
      try {
        const res = await fetchAuth(`${API_BASE}/admin/series`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        setSeries(await res.json());
      } catch (e) { setError(e.message); }
      finally { setLoading(false); }
    })();
  }, []);
  return { series, loading, error };
}

function useUsuarios() {
  const [usuarios, setUsuarios] = useState([]);
  const [loading,  setLoading]  = useState(true);
  const [error,    setError]    = useState(null);
  useEffect(() => {
    (async () => {
      try {
        const res = await fetchAuth(`${API_BASE}/auth/usuarios`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        setUsuarios(await res.json());
      } catch (e) { setError(e.message); }
      finally { setLoading(false); }
    })();
  }, []);
  return { usuarios, loading, error };
}

function useAnomalias() {
  const [anomalias, setAnomalias] = useState([]);
  const [loading,   setLoading]   = useState(false);
  const [error,     setError]     = useState(null);
  const detectar = useCallback(async (facturas, pagos=[]) => {
    setLoading(true); setError(null);
    try {
      const res = await fetchAuth(`${API_BASE}/ia/anomalias`, {
        method:"POST", headers:{"Content-Type":"application/json"},
        body: JSON.stringify({ facturas, pagos_bancarios:pagos }),
      });
      if (!res.ok) {
        const errBody = await res.json().catch(() => ({}));
        throw new Error(errBody.detail || `HTTP ${res.status}`);
      }
      const data = await res.json(); setAnomalias(data); return data;
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  }, []);
  return { anomalias, detectar, loading, error };
}

// ═══════════════════════════════════════════════════════════════════════════════
// TOKENS & DATA
// ═══════════════════════════════════════════════════════════════════════════════
const FACTURAS = [
  {folio:"A-0127",receptor:"Coppel SA de CV",total:77600,fecha:"2025-05-19",estado:"Vigente",uuid:"WXY7-ZAB8"},
  {folio:"A-0126",receptor:"OXXO Gas SA de CV",total:32100,fecha:"2025-05-16",estado:"Vigente",uuid:"KLM3-NOP4"},
  {folio:"A-0041",receptor:"Walmart de México",total:89300,fecha:"2025-05-12",estado:"Alerta",uuid:"MNO5-PQR6"},
  {folio:"A-0039",receptor:"FEMSA",total:124750,fecha:"2025-03-14",estado:"Vencida",uuid:"ABC1-DEF2"},
  {folio:"A-0003",receptor:"Tiendas Chedraui",total:9800,fecha:"2025-05-14",estado:"Cancelada",uuid:"YZA9-BCD0"},
];
const CUENTA_CTX = {iva_pendiente:38640,facturas_vigentes:4,facturas_vencidas:1,total_mayo:302450,cuentas_por_cobrar:246150,proximo_vencimiento_iva:"2025-06-17"};
const NAV = [
  {id:"facturas",label:"Mis Facturas",icon:"📄",children:["nueva","generadas","recibidas","reporte","costos","contador"]},
  {id:"ia",label:"IA",icon:"🤖",children:["lector","chat","anomalias","conciliacion"]},
  {id:"admin",label:"Administración",icon:"⚙️",children:["emisores","clientes","usuarios","series"]},
  {id:"addenda",label:"Addenda AES",icon:"🔗",children:[]},
];
const LABELS = {
  nueva:"Nueva Factura",generadas:"Generadas",recibidas:"Recibidas",reporte:"Reporte Mensual",costos:"Dashboard de Costos",contador:"Contador Virtual",
  lector:"Lector de Documentos",chat:"Chat Fiscal",anomalias:"Anomalías IA",conciliacion:"Conciliación",
  emisores:"Emisores",clientes:"Clientes",usuarios:"Usuarios",series:"Series",addenda:"Addenda AES",
};
const SUGERENCIAS = [
  "¿Cuánto IVA tengo pendiente?","¿Qué clientes tienen RFC en riesgo?",
  "¿Cuánto me deben mis clientes?","Resumen ejecutivo de mayo",
];

function SectionTitle({children}){return <h2 style={{fontSize:20,fontWeight:700,color:C.text,marginBottom:4}}>{children}</h2>;}
function SectionSub({children}){return <p style={{color:C.textSec,fontSize:13,marginBottom:18,marginTop:2}}>{children}</p>;}

// ═══════════════════════════════════════════════════════════════════════════════
// VISTA: NUEVA FACTURA
// ═══════════════════════════════════════════════════════════════════════════════
function NuevaFactura(){
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

  const sub=(parseFloat(form.cantidad)||0)*(parseFloat(form.precio)||0);
  const total=sub*(1+(parseFloat(form.iva)||0)/100);

  const seleccionarCliente = rfc => {
    setResultado(null); setErrorTimbrado(null);
    if (!rfc) { setForm(f=>({...f,clienteRfc:"",receptor:"",rfc:"",domicilioFiscal:"",regimenFiscal:""})); return; }
    const c = clientes.find(c=>c.rfc===rfc);
    if (!c) return;
    setForm(f=>({...f,clienteRfc:rfc,receptor:c.nombre,rfc:c.rfc,usoCfdi:c.uso_cfdi_default||f.usoCfdi,domicilioFiscal:c.domicilio_fiscal||"",regimenFiscal:c.regimen_fiscal||""}));
  };

  const inp=(lbl,k,type="text")=>(
    <div style={{marginBottom:10}}>
      <label style={{fontSize:12,color:C.textSec,display:"block",marginBottom:3}}>{lbl}</label>
      <input type={type} value={form[k]} onChange={e=>setForm({...form,[k]:e.target.value})} placeholder={lbl}
        style={{width:"100%",border:`1px solid ${C.border}`,borderRadius:8,padding:"8px 11px",fontSize:13,color:C.text,background:"#fff",boxSizing:"border-box"}}/>
    </div>
  );

  const timbrar = async () => {
    if (!emisor) { toast("No hay ningún emisor registrado en Administración todavía","error"); return; }
    if (!form.receptor||!form.rfc||!form.domicilioFiscal||!form.concepto||!form.cantidad||!form.precio) {
      toast("Completa receptor, domicilio fiscal y los datos del concepto antes de timbrar","warning"); return;
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
          {inp("Cantidad","cantidad","number")}
          {inp("Precio unitario","precio","number")}
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

// ═══════════════════════════════════════════════════════════════════════════════
// VISTA: FACTURAS GENERADAS — tabla compacta con scroll horizontal
// ═══════════════════════════════════════════════════════════════════════════════
function FacturasGeneradas(){
  const {isMobile} = useBreakpoint();
  const toast = useToast();
  const { emisorActivoRfc } = useEmisores();
  const {facturas,loading,error,recargar} = useFacturas(emisorActivoRfc);
  const [q,setQ]=useState("");
  const [filtro,setFiltro]=useState("Todas");
  const items=facturas.filter(f=>(filtro==="Todas"||f.estado===filtro)&&
    (f.receptor_rfc.toLowerCase().includes(q.toLowerCase())||f.folio.includes(q)));

  if (error) return <Placeholder title="Facturas generadas" detail={`No se pudo conectar con facturacion (${FACTURACION_BASE}): ${error}`}/>;

  return (
    <div>
      <SectionTitle>Facturas generadas</SectionTitle>
      <KPIGrid>
        <KPI label="Total emitido" value={fmt(facturas.reduce((s,f)=>s+f.total,0))} dark/>
        <KPI label="Vigentes"   value={facturas.filter(f=>f.estado==="Vigente").length}/>
        <KPI label="Vencidas"   value={facturas.filter(f=>f.estado==="Vencida").length}/>
        <KPI label="Canceladas" value={facturas.filter(f=>f.estado==="Cancelada").length}/>
      </KPIGrid>

      <Card style={{padding:0,overflow:"hidden"}}>
        {/* Barra de búsqueda y filtros */}
        <div style={{padding:"10px 12px",borderBottom:`1px solid ${C.border}`,display:"flex",gap:8,flexWrap:"wrap",alignItems:"center"}}>
          <input value={q} onChange={e=>setQ(e.target.value)} placeholder="Buscar folio o RFC receptor…"
            style={{flex:1,minWidth:100,border:`1px solid ${C.border}`,borderRadius:8,padding:"7px 11px",fontSize:13,color:C.text,background:C.surface}}/>
          <div style={{display:"flex",gap:5,flexWrap:"wrap"}}>
            {["Todas","Vigente","Vencida","Cancelada"].map(f=>(
              <button key={f} onClick={()=>setFiltro(f)}
                style={{fontSize:11,padding:"5px 10px",borderRadius:12,border:`1px solid ${filtro===f?C.accent:C.border}`,
                  background:filtro===f?C.accentSoft:"transparent",color:filtro===f?C.accentBorder:C.textSec,cursor:"pointer",whiteSpace:"nowrap"}}>
                {f}
              </button>
            ))}
          </div>
          <button onClick={recargar} title="Recargar" disabled={loading}
            style={{fontSize:11,padding:"5px 10px",borderRadius:12,border:`1px solid ${C.border}`,background:"transparent",color:C.textSec,cursor:loading?"not-allowed":"pointer"}}>
            {loading?"Cargando…":"↻ Recargar"}
          </button>
        </div>

        {/* Tabla con scroll horizontal */}
        <div style={{overflowX:"auto",WebkitOverflowScrolling:"touch"}}>
          <table style={{width:"100%",borderCollapse:"collapse",minWidth:isMobile?360:540}}>
            <thead>
              <tr style={{background:C.surface}}>
                <th style={TH}>Folio</th>
                <th style={TH}>Receptor (RFC)</th>
                {!isMobile&&<th style={TH}>Fecha timbrado</th>}
                <th style={{...TH,textAlign:"right"}}>Total</th>
                <th style={{...TH,textAlign:"center"}}>Estado</th>
                {!isMobile&&<th style={TH}>Usuario</th>}
                {!isMobile&&<th style={TH}></th>}
              </tr>
            </thead>
            <tbody>
              {!loading && items.length===0 && (
                <tr><td colSpan={isMobile?4:7} style={{...TD,textAlign:"center",color:C.textMuted,padding:"24px 12px"}}>
                  {facturas.length===0 ? "Todavía no hay facturas timbradas." : "Sin resultados para ese filtro/búsqueda."}
                </td></tr>
              )}
              {items.map((f,i)=>(
                <tr key={f.uuid} style={{borderTop:`1px solid ${C.border}`,background:i%2===0?"#fff":C.surface,cursor:"pointer"}}
                  onClick={()=>!isMobile&&toast(`Factura ${f.folio} · UUID: ${f.uuid}`,"info")}>
                  <td style={TD}><span style={{fontFamily:"monospace",fontSize:12,fontWeight:600,color:C.primary}}>{f.folio}</span></td>
                  <td style={{...TD,maxWidth:isMobile?90:180}}><span style={{display:"block",overflow:"hidden",textOverflow:"ellipsis",whiteSpace:"nowrap",fontSize:13,fontFamily:"monospace"}}>{f.receptor_rfc}</span></td>
                  {!isMobile&&<td style={{...TD,color:C.textSec,fontSize:12,whiteSpace:"nowrap"}}>{new Date(f.fecha_timbrado).toLocaleString("es-MX")}</td>}
                  <td style={{...TD,textAlign:"right",fontWeight:600,fontSize:13,whiteSpace:"nowrap"}}>{fmt(f.total)}</td>
                  <td style={{...TD,textAlign:"center"}}><Badge estado={f.estado}/></td>
                  {!isMobile&&(
                    <td style={{...TD,color:C.textSec,fontSize:12,fontFamily:"monospace",whiteSpace:"nowrap"}}>
                      {(f.estado==="Cancelada" ? f.cancelado_por_rfc : f.creado_por_rfc) || "—"}
                    </td>
                  )}
                  {!isMobile&&(
                    <td style={{...TD,whiteSpace:"nowrap"}} onClick={e=>e.stopPropagation()}>
                      <a href={f.xml_url} target="_blank" rel="noreferrer"
                        style={{fontSize:11,padding:"3px 8px",borderRadius:6,border:`1px solid ${C.border}`,background:"transparent",cursor:"pointer",color:C.textSec,marginRight:4,textDecoration:"none",display:"inline-block"}}>XML</a>
                      <a href={f.pdf_url} target="_blank" rel="noreferrer"
                        style={{fontSize:11,padding:"3px 8px",borderRadius:6,border:`1px solid ${C.border}`,background:"transparent",cursor:"pointer",color:C.textSec,textDecoration:"none",display:"inline-block"}}>PDF</a>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
      <div style={{fontSize:11,color:C.textMuted,marginTop:8}}>
        Nota: las URLs de descarga apuntan a MinIO dentro de la red de Docker — hoy no son accesibles desde fuera de ese entorno (ver #8/#19/#20).
      </div>
    </div>
  );
}
const TH = {padding:"9px 12px",textAlign:"left",fontSize:10,fontWeight:700,color:C.textMuted,textTransform:"uppercase",letterSpacing:"0.06em",whiteSpace:"nowrap"};
const TD = {padding:"10px 12px",color:C.text};

// ═══════════════════════════════════════════════════════════════════════════════
// VISTA: LECTOR IA
// ═══════════════════════════════════════════════════════════════════════════════
function LectorDocumentos(){
  const toast = useToast();
  const {extraer,loading,result,error,steps}=useDocumentExtractor();
  const [dragging,setDragging]=useState(false);
  const [file,setFile]=useState(null);
  const inputRef=useRef();
  const handleFile=f=>{setFile(f);extraer(f);};
  const onDrop=e=>{e.preventDefault();setDragging(false);const f=e.dataTransfer.files[0];if(f)handleFile(f);};
  return (
    <div>
      <SectionTitle>Lector de documentos IA</SectionTitle>
      <SectionSub>Sube una orden de compra, cotización o nota — la IA extrae los datos y genera el CFDI.</SectionSub>
      {!file&&(
        <>
          <div onDrop={onDrop} onDragOver={e=>{e.preventDefault();setDragging(true);}} onDragLeave={()=>setDragging(false)}
            onClick={()=>inputRef.current.click()}
            style={{border:`2px dashed ${dragging?C.accent:C.border}`,borderRadius:12,padding:"40px 20px",textAlign:"center",cursor:"pointer",background:dragging?C.accentSoft:"transparent",transition:"all .2s"}}>
            <div style={{fontSize:36,marginBottom:10}}>📄</div>
            <div style={{fontSize:14,fontWeight:600,color:C.text,marginBottom:4}}>Arrastra tu documento aquí</div>
            <div style={{fontSize:12,color:C.textMuted}}>PDF · XML · JPG · PNG</div>
            <input ref={inputRef} type="file" accept=".pdf,.jpg,.jpeg,.png,.xml" style={{display:"none"}} onChange={e=>e.target.files[0]&&handleFile(e.target.files[0])}/>
          </div>
          <div style={{display:"grid",gridTemplateColumns:"repeat(auto-fit,minmax(100px,1fr))",gap:8,marginTop:10}}>
            {[["🛒","Orden de compra"],["📋","Cotización"],["🚚","Nota de entrega"]].map(([ic,lbl])=>(
              <div key={lbl} onClick={()=>inputRef.current.click()} style={{background:C.surface,border:`1px solid ${C.border}`,borderRadius:10,padding:"12px 8px",textAlign:"center",cursor:"pointer"}}>
                <div style={{fontSize:22,marginBottom:4}}>{ic}</div>
                <div style={{fontSize:11,color:C.textSec}}>{lbl}</div>
              </div>
            ))}
          </div>
        </>
      )}
      {loading&&(
        <Card style={{marginTop:14}}>
          <div style={{fontSize:12,color:C.textMuted,marginBottom:6}}>{file?.name}</div>
          <div style={{height:4,background:C.surface,borderRadius:2,overflow:"hidden",marginBottom:14}}>
            <div style={{height:"100%",background:C.accent,borderRadius:2,width:`${Math.min((steps.length/4)*100,95)}%`,transition:"width .5s"}}/>
          </div>
          {steps.map((s,i)=>(
            <div key={i} style={{display:"flex",alignItems:"center",gap:10,padding:"7px 0",borderBottom:`1px solid ${C.border}`}}>
              <span style={{color:C.accent}}>✓</span><span style={{fontSize:13,color:C.textSec}}>{s}</span>
            </div>
          ))}
        </Card>
      )}
      {error&&(
        <Card style={{marginTop:14,borderColor:C.danger,background:C.dangerSoft}}>
          <div style={{fontSize:13,color:C.danger}}>⚠ {error}</div>
          <Btn variant="secondary" onClick={()=>setFile(null)} style={{marginTop:10}}>Intentar con otro archivo</Btn>
        </Card>
      )}
      {result&&(
        <div style={{marginTop:14}}>
          <Card>
            <div style={{display:"flex",alignItems:"center",justifyContent:"space-between",marginBottom:14,flexWrap:"wrap",gap:8}}>
              <div style={{fontSize:12,fontWeight:700,color:C.text,textTransform:"uppercase",letterSpacing:"0.06em"}}>Datos extraídos por IA</div>
              <span style={{fontSize:11,fontWeight:600,color:"#0A6B4A"}}>✓ {Math.round((result.confianza?.general||.95)*100)}% confianza</span>
            </div>
            <div style={{display:"grid",gridTemplateColumns:"repeat(auto-fit,minmax(150px,1fr))",gap:10}}>
              {[["Receptor",result.receptor_nombre],["RFC",result.receptor_rfc],["Uso CFDI",result.receptor_uso_cfdi],["Método pago",result.metodo_pago],["Orden",result.numero_orden],["Addenda",result.addenda_detectada||"—"]].map(([l,v])=>(
                <div key={l} style={{background:C.surface,borderRadius:8,padding:"10px 12px",position:"relative"}}>
                  <div style={{fontSize:10,color:C.textMuted,textTransform:"uppercase",letterSpacing:"0.06em",marginBottom:3}}>{l}</div>
                  <div style={{fontSize:13,fontWeight:600,color:C.text}}>{v||"—"}</div>
                  <span style={{position:"absolute",top:8,right:8,fontSize:9,fontWeight:600,padding:"2px 6px",borderRadius:8,background:"#EBF8FF",color:C.info}}>IA</span>
                </div>
              ))}
            </div>
          </Card>
          <div style={{display:"grid",gridTemplateColumns:"repeat(auto-fit,minmax(150px,1fr))",gap:10,marginTop:10}}>
            <Btn onClick={()=>toast(`POST ${API_BASE}/facturas/timbrar — ${result.receptor_nombre}`,"api")}>Timbrar este CFDI →</Btn>
            <Btn variant="secondary" onClick={()=>setFile(null)}>Procesar otro documento</Btn>
          </div>
        </div>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// VISTA: CHAT FISCAL
// ═══════════════════════════════════════════════════════════════════════════════
function ChatFiscal(){
  const {isMobile}=useBreakpoint();
  const {messages,send,streaming,reset,abort}=useFiscalChat();
  const {emisores,emisorActivoRfc}=useEmisores();
  const emisorActual=emisores.find(e=>e.rfc===emisorActivoRfc);
  const [input,setInput]=useState("");
  // Modo del chat (20 ago 2026, tarjeta 2mSpU) - "cuenta" es el default para
  // no cambiar el comportamiento existente de nadie que ya use el chat.
  // Decorativo con useEmisores (header de abajo) no se toca: es independiente
  // del modo, solo muestra el RFC conectado.
  const [modo,setModo]=useState("cuenta");
  const bottomRef=useRef();
  useEffect(()=>{bottomRef.current?.scrollIntoView({behavior:"smooth"});},[messages]);
  const submit=()=>{if(!input.trim()||streaming)return;send(input.trim(),CUENTA_CTX,modo);setInput("");};
  return (
    <div style={{display:"flex",flexDirection:"column",height:isMobile?"calc(100dvh - 170px)":"calc(100vh - 155px)",gap:10}}>
      <div style={{display:"flex",alignItems:"center",justifyContent:"space-between",flexWrap:"wrap",gap:8}}>
        <div><SectionTitle>Chat fiscal IA</SectionTitle><p style={{fontSize:12,color:C.textSec,margin:0}}>Conectado · RFC {emisorActual?.rfc||"—"}</p></div>
        <div style={{display:"flex",gap:8}}>
          {streaming&&<Btn variant="secondary" onClick={abort} style={{fontSize:12,padding:"6px 12px"}}>Detener</Btn>}
          <Btn variant="secondary" onClick={reset} style={{fontSize:12,padding:"6px 12px"}}>Nueva conversación</Btn>
        </div>
      </div>
      <div style={{display:"flex",gap:6}}>
        {[["cuenta","Mi cuenta"],["general","Consulta general"]].map(([id,lbl])=>(
          <button key={id} onClick={()=>setModo(id)}
            style={{fontSize:11,padding:"5px 10px",borderRadius:12,border:`1px solid ${modo===id?C.accent:C.border}`,
              background:modo===id?C.accentSoft:"transparent",color:modo===id?C.accentBorder:C.textSec,cursor:"pointer",whiteSpace:"nowrap"}}>
            {lbl}
          </button>
        ))}
      </div>
      <Card style={{flex:1,overflowY:"auto",padding:14,display:"flex",flexDirection:"column",gap:10,minHeight:0}}>
        {messages.length===0&&(
          <div style={{display:"flex",flexDirection:"column",alignItems:"center",justifyContent:"center",height:"100%",gap:14,padding:"0 10px"}}>
            <div style={{width:48,height:48,borderRadius:14,background:C.primary,display:"flex",alignItems:"center",justifyContent:"center",fontSize:22}}>🤖</div>
            <div style={{fontSize:14,fontWeight:600,color:C.text,textAlign:"center"}}>¿En qué te ayudo hoy?</div>
            <div style={{display:"flex",flexWrap:"wrap",gap:8,justifyContent:"center"}}>
              {SUGERENCIAS.map(s=>(
                <button key={s} onClick={()=>send(s,CUENTA_CTX,modo)}
                  style={{fontSize:12,padding:"7px 12px",borderRadius:20,border:`1px solid ${C.border}`,background:C.surface,color:C.textSec,cursor:"pointer",textAlign:"left"}}>
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}
        {messages.map((m,i)=>(
          <div key={i} style={{display:"flex",gap:8,justifyContent:m.role==="user"?"flex-end":"flex-start",alignItems:"flex-start"}}>
            {m.role==="assistant"&&<div style={{width:26,height:26,borderRadius:8,background:C.primary,display:"flex",alignItems:"center",justifyContent:"center",fontSize:13,flexShrink:0,marginTop:2}}>🤖</div>}
            <div style={{maxWidth:"82%",padding:"10px 13px",borderRadius:m.role==="user"?"12px 4px 12px 12px":"4px 12px 12px 12px",background:m.role==="user"?C.primary:C.surface,color:m.role==="user"?"#E8F4FF":C.text,fontSize:13,lineHeight:1.6,whiteSpace:"pre-wrap",wordBreak:"break-word"}}>
              {m.content||<span style={{opacity:.4}}>●●●</span>}
            </div>
          </div>
        ))}
        <div ref={bottomRef}/>
      </Card>
      <div style={{display:"flex",gap:8}}>
        <input value={input} onChange={e=>setInput(e.target.value)} onKeyDown={e=>e.key==="Enter"&&submit()}
          placeholder="Pregunta sobre IVA, clientes, facturas…"
          style={{flex:1,border:`1px solid ${C.border}`,borderRadius:8,padding:"10px 13px",fontSize:13,color:C.text,background:C.card,minWidth:0}}/>
        <Btn onClick={submit} disabled={streaming} style={{padding:"10px 16px",flexShrink:0}}>→</Btn>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// VISTA: ANOMALÍAS
// ═══════════════════════════════════════════════════════════════════════════════
function Anomalias(){
  const {anomalias,detectar,loading,error}=useAnomalias();
  const [ran,setRan]=useState(false);
  const correr=async()=>{await detectar(FACTURAS,[]);setRan(true);};
  const sevColor={alta:{bg:C.dangerSoft,c:C.danger},media:{bg:C.warnSoft,c:C.warn},baja:{bg:"#EBF8FF",c:C.info}};
  return (
    <div>
      <div style={{display:"flex",alignItems:"flex-start",justifyContent:"space-between",marginBottom:16,gap:12,flexWrap:"wrap"}}>
        <div><SectionTitle>Anomalías IA</SectionTitle><SectionSub>Análisis automático de facturas y pagos en busca de riesgos.</SectionSub></div>
        <Btn onClick={correr} disabled={loading}>{loading?"Analizando…":"Analizar ahora →"}</Btn>
      </div>
      {!ran&&!loading&&!error&&<Card style={{textAlign:"center",padding:48}}><div style={{fontSize:36,marginBottom:10}}>🔍</div><div style={{fontSize:14,fontWeight:600,color:C.text}}>Sin análisis todavía</div></Card>}
      {loading&&<Card style={{textAlign:"center",padding:40}}><div style={{fontSize:13,color:C.textSec}}>⚙️ La IA está revisando tus facturas…</div></Card>}
      {error&&!loading&&<Card style={{borderColor:C.danger,background:C.dangerSoft}}><div style={{fontSize:13,color:C.danger}}>⚠ {error}</div></Card>}
      {ran&&!loading&&!error&&anomalias.length===0&&<Card style={{textAlign:"center",padding:48}}><div style={{fontSize:36,marginBottom:10}}>✅</div><div style={{fontSize:14,fontWeight:600,color:C.text}}>Sin anomalías detectadas</div></Card>}
      {anomalias.map((a,i)=>{
        const s=sevColor[a.severidad]||sevColor.baja;
        return (
          <Card key={i} style={{marginBottom:10,borderLeft:`3px solid ${s.c}`}}>
            <div style={{display:"flex",gap:12,flexWrap:"wrap"}}>
              <div style={{width:34,height:34,borderRadius:8,background:s.bg,display:"flex",alignItems:"center",justifyContent:"center",fontSize:16,flexShrink:0}}>
                {a.tipo==="pago_retrasado"?"⏰":a.tipo==="rfc_riesgo"?"🚫":a.tipo==="discrepancia_pago"?"⚡":"📋"}
              </div>
              <div style={{flex:1,minWidth:0}}>
                <div style={{display:"flex",alignItems:"center",gap:8,marginBottom:4,flexWrap:"wrap"}}>
                  <span style={{fontSize:13,fontWeight:700,color:C.text}}>{a.titulo}</span>
                  <span style={{fontSize:10,fontWeight:600,padding:"2px 8px",borderRadius:10,background:s.bg,color:s.c,whiteSpace:"nowrap"}}>{a.severidad.toUpperCase()}</span>
                </div>
                <div style={{fontSize:13,color:C.textSec,marginBottom:6}}>{a.descripcion}</div>
                <div style={{fontSize:12,color:C.info,background:"#EBF8FF",padding:"6px 10px",borderRadius:6}}>💡 {a.accion_recomendada}</div>
              </div>
              {a.monto_en_riesgo>0&&<div style={{textAlign:"right",flexShrink:0}}><div style={{fontSize:11,color:C.textMuted}}>En riesgo</div><div style={{fontSize:14,fontWeight:700,color:C.danger}}>{fmt(a.monto_en_riesgo)}</div></div>}
            </div>
          </Card>
        );
      })}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// VISTA: CLIENTES
// ═══════════════════════════════════════════════════════════════════════════════
// ═══════════════════════════════════════════════════════════════════════════════
// VISTA: REPORTE
// ═══════════════════════════════════════════════════════════════════════════════
const MESES_CORTOS=["Ene","Feb","Mar","Abr","May","Jun","Jul","Ago","Sep","Oct","Nov","Dic"];

function ReporteMensual(){
  const {facturas,loading,error} = useFacturas();
  const resumen = useResumenEjecutivo();

  if (error) return <Placeholder title="Reporte mensual" detail={`No se pudo conectar con facturacion (${FACTURACION_BASE}): ${error}`}/>;
  if (loading) return <Placeholder title="Reporte mensual" detail="Cargando datos reales…"/>;
  if (facturas.length===0) return <Placeholder title="Reporte mensual" detail="Todavía no hay facturas timbradas para reportar."/>;

  const porMes = {};
  for (const f of facturas) {
    const d = new Date(f.fecha_timbrado);
    const key = `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}`;
    porMes[key] = (porMes[key]||0) + f.total;
  }
  const meses = Object.keys(porMes).sort();
  const vals = meses.map(k=>porMes[k]);
  const maxV = Math.max(...vals, 1);
  const totalAcumulado = facturas.reduce((s,f)=>s+f.total,0);
  const rangoLabel = meses.length>1
    ? `${MESES_CORTOS[Number(meses[0].slice(5))-1]} ${meses[0].slice(0,4)} – ${MESES_CORTOS[Number(meses[meses.length-1].slice(5))-1]} ${meses[meses.length-1].slice(0,4)}`
    : `${MESES_CORTOS[Number(meses[0].slice(5))-1]} ${meses[0].slice(0,4)}`;

  return (
    <div>
      <SectionTitle>Reporte mensual</SectionTitle>
      <Card style={{marginTop:12}}>
        <div style={{fontSize:11,color:C.textMuted,marginBottom:12,textTransform:"uppercase",letterSpacing:"0.06em"}}>Facturación real · {rangoLabel}</div>
        <div style={{display:"flex",alignItems:"flex-end",gap:8,height:130,padding:"0 4px"}}>
          {meses.map((k,i)=>(
            <div key={k} style={{flex:1,display:"flex",flexDirection:"column",alignItems:"center",gap:4}}>
              <div style={{fontSize:9,color:C.textMuted,textAlign:"center"}}>{(vals[i]/1000).toFixed(1)}k</div>
              <div style={{width:"100%",background:i===meses.length-1?C.accent:C.primary,borderRadius:"5px 5px 0 0",height:`${(vals[i]/maxV)*100}px`,minHeight:2,opacity:i===meses.length-1?1:.7}}/>
              <div style={{fontSize:11,color:C.textSec,fontWeight:i===meses.length-1?700:400}}>{MESES_CORTOS[Number(k.slice(5))-1]}</div>
            </div>
          ))}
        </div>
        <div style={{borderTop:`1px solid ${C.border}`,marginTop:14,paddingTop:12,display:"flex",gap:20,flexWrap:"wrap"}}>
          {[["Total acumulado",fmt(totalAcumulado)],["CFDIs emitidos",String(facturas.length)],["Promedio",fmt(totalAcumulado/facturas.length)]].map(([l,v])=>(
            <div key={l}><div style={{fontSize:10,color:C.textMuted,marginBottom:3,textTransform:"uppercase"}}>{l}</div><div style={{fontSize:16,fontWeight:700,color:C.text}}>{v}</div></div>
          ))}
        </div>
        <Btn variant="secondary" style={{marginTop:12}} disabled={resumen.loading}
          onClick={()=>resumen.generar({
            periodo_inicio: `${meses[0]}-01`,
            periodo_fin: new Date().toISOString().slice(0,10),
            datos_facturacion: {
              total_acumulado: totalAcumulado,
              num_facturas: facturas.length,
              promedio: totalAcumulado/facturas.length,
              por_mes: porMes,
            },
            incluir_comparativo: meses.length>1,
          })}>
          {resumen.loading ? "Generando…" : "Generar resumen ejecutivo →"}
        </Btn>

        {resumen.error && (
          <div style={{marginTop:12,padding:"10px 12px",borderRadius:8,background:C.dangerSoft,color:C.danger,fontSize:12}}>
            ⚠ No se pudo generar el resumen: {resumen.error}. Revisa que ANTHROPIC_API_KEY esté configurada (ver #41).
          </div>
        )}

        {resumen.resultado && !resumen.resultado.texto_raw && (
          <div style={{marginTop:16,borderTop:`1px solid ${C.border}`,paddingTop:16}}>
            <div style={{fontSize:16,fontWeight:700,color:C.text,marginBottom:12}}>{resumen.resultado.titulo}</div>

            <KPIGrid>
              {(resumen.resultado.kpis_principales||[]).map((k,i)=>(
                <KPI key={i} label={k.nombre} value={k.valor}
                  sub={k.nota ? `${k.tendencia==="sube"?"↑":k.tendencia==="baja"?"↓":"→"} ${k.nota}` : undefined}/>
              ))}
            </KPIGrid>

            {resumen.resultado.texto_ejecutivo && (
              <p style={{fontSize:13,color:C.textSec,lineHeight:1.6,marginBottom:16}}>{resumen.resultado.texto_ejecutivo}</p>
            )}

            <TwoCol>
              {[["Hallazgos",resumen.resultado.hallazgos],["Riesgos",resumen.resultado.riesgos],["Recomendaciones",resumen.resultado.recomendaciones]].map(([titulo,items])=>(
                (items && items.length>0) && (
                  <Card key={titulo}>
                    <div style={{fontSize:11,color:C.textMuted,marginBottom:10,textTransform:"uppercase",letterSpacing:"0.06em"}}>{titulo}</div>
                    <ul style={{margin:0,paddingLeft:18,fontSize:13,color:C.textSec,lineHeight:1.7}}>
                      {items.map((it,i)=><li key={i}>{it}</li>)}
                    </ul>
                  </Card>
                )
              ))}
            </TwoCol>
          </div>
        )}
      </Card>
    </div>
  );
}

function DashboardCostos(){
  const { emisorActivoRfc } = useEmisores();
  const {datos,loading,error} = useCostosResumen(emisorActivoRfc);

  if (error) return <Placeholder title="Dashboard de costos" detail={`No se pudo conectar con facturacion (${FACTURACION_BASE}): ${error}`}/>;
  if (loading) return <Placeholder title="Dashboard de costos" detail="Cargando datos reales…"/>;

  const costoTotal = datos.reduce((s,d)=>s+d.costo_total,0);
  const timbresTotal = datos.reduce((s,d)=>s+d.num_timbres,0);
  const costoPromedio = timbresTotal>0 ? costoTotal/timbresTotal : 0;

  return (
    <div>
      <SectionTitle>Dashboard de costos</SectionTitle>
      <SectionSub>Costo real de Finkok por timbre (#6) · margen y costo de WhatsApp fuera de alcance por ahora (#7, #16)</SectionSub>

      <KPIGrid>
        <KPI label="Costo Finkok acumulado" value={fmt(costoTotal)} sub={`${timbresTotal} timbre${timbresTotal===1?"":"s"}`} dark/>
        <KPI label="Costo promedio por timbre" value={fmt(costoPromedio)}/>
        <KPI label="Costo WhatsApp por interacción" value="Pendiente" sub="Requiere #7 (en pausa)"/>
        <KPI label="Margen por negocio" value="Pendiente" sub="Requiere #7 + #16 (precios)"/>
      </KPIGrid>

      <Card>
        <div style={{fontSize:11,color:C.textMuted,marginBottom:12,textTransform:"uppercase",letterSpacing:"0.06em"}}>Desglose por mes y emisor</div>
        {datos.length===0 ? (
          <div style={{color:C.textMuted,fontSize:13,padding:"12px 0"}}>Todavía no hay timbres con costo registrado (#6 solo aplica a timbrados posteriores a su implementación).</div>
        ) : (
          <table style={{width:"100%",borderCollapse:"collapse",fontSize:13}}>
            <thead>
              <tr style={{textAlign:"left",color:C.textMuted,fontSize:11,textTransform:"uppercase"}}>
                <th style={{padding:"6px 8px 10px 0"}}>Periodo</th>
                <th style={{padding:"6px 8px 10px 0"}}>Emisor</th>
                <th style={{padding:"6px 8px 10px 0"}}>Timbres</th>
                <th style={{padding:"6px 8px 10px 0"}}>Costo total</th>
                <th style={{padding:"6px 8px 10px 0"}}>Costo promedio</th>
              </tr>
            </thead>
            <tbody>
              {datos.map((d,i)=>(
                <tr key={`${d.periodo}-${d.emisor_rfc}`} style={{borderTop:`1px solid ${C.border}`}}>
                  <td style={{padding:"8px 8px 8px 0",fontWeight:600,color:C.text}}>{d.periodo}</td>
                  <td style={{padding:"8px 8px 8px 0",color:C.textSec}}>{d.emisor_rfc}</td>
                  <td style={{padding:"8px 8px 8px 0",color:C.textSec}}>{d.num_timbres}</td>
                  <td style={{padding:"8px 8px 8px 0",color:C.text}}>{fmt(d.costo_total)}</td>
                  <td style={{padding:"8px 8px 8px 0",color:C.textSec}}>{fmt(d.costo_promedio)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <div style={{marginTop:14,padding:"10px 12px",borderRadius:8,background:C.warnSoft,color:C.warn,fontSize:12}}>
          ⏳ Pendiente: costo de conversación de WhatsApp (#7, en pausa) y cálculo de margen por negocio (#16, precios diferidos) — se agregarán a este dashboard cuando esas tarjetas se resuelvan. No se muestran como $0 para no dar una cifra falsa.
        </div>
      </Card>
    </div>
  );
}

function ContadorVirtual(){
  const {emisores,loading:loadingEmisores,error:errorEmisores,emisorActivoRfc} = useEmisores();
  const emisor = emisores.find(e=>e.rfc===emisorActivoRfc);
  const hoy = new Date();
  const [periodo,setPeriodo] = useState(`${hoy.getFullYear()}-${String(hoy.getMonth()+1).padStart(2,"0")}`);
  const [anio,mes] = periodo.split("-").map(Number);
  const {datos,loading,error} = useContadorVirtualISRResico(emisor?.rfc, anio, mes);

  if (errorEmisores) return <Placeholder title="Contador virtual" detail={`No se pudo conectar con administracion (${ADMINISTRACION_BASE}): ${errorEmisores}`}/>;
  if (loadingEmisores) return <Placeholder title="Contador virtual" detail="Cargando datos reales…"/>;
  if (!emisor) return <Placeholder title="Contador virtual" detail="Todavía no hay un emisor registrado."/>;

  return (
    <div>
      <SectionTitle>Contador virtual — ISR provisional (RESICO PF)</SectionTitle>
      <SectionSub>Fase 1 de #40: solo RESICO Personas Físicas, solo ingresos ya facturados con pago en una sola exhibición (PUE).</SectionSub>

      <Card style={{marginBottom:12}}>
        <label style={{fontSize:12,color:C.textSec,display:"block",marginBottom:6}}>Periodo</label>
        <input type="month" value={periodo} onChange={e=>setPeriodo(e.target.value)}
          style={{border:`1px solid ${C.border}`,borderRadius:8,padding:"8px 11px",fontSize:13,color:C.text,background:"#fff"}}/>
      </Card>

      {loading && <Placeholder title="Contador virtual" detail="Calculando…"/>}
      {!loading && error && <Placeholder title="Contador virtual" detail={`No se pudo conectar con facturacion (${FACTURACION_BASE}): ${error}`}/>}

      {!loading && !error && datos && !datos.aplica && (
        <Card>
          <div style={{fontSize:14,fontWeight:600,color:C.text,marginBottom:6}}>No aplica para tu régimen fiscal</div>
          <div style={{fontSize:13,color:C.textSec}}>{datos.motivo_no_aplica}</div>
        </Card>
      )}

      {!loading && !error && datos && datos.aplica && (
        <>
          <KPIGrid>
            <KPI label="Ingreso PUE del periodo" value={fmt(datos.ingreso_pue_incluido)} sub={`${datos.facturas_pue_incluidas.length} factura${datos.facturas_pue_incluidas.length===1?"":"s"}`} dark/>
            <KPI label="Tasa aplicada" value={`${(datos.tasa_aplicada*100).toFixed(2)}%`}/>
            <KPI label="ISR provisional estimado" value={fmt(datos.isr_estimado)}/>
          </KPIGrid>

          {datos.excede_tope_mensual && (
            <div style={{marginBottom:12,padding:"10px 12px",borderRadius:8,background:C.dangerSoft,color:C.danger,fontSize:12}}>
              ⚠ El ingreso del mes excede el tope mensual normal de RESICO (~$291,666.67, equivalente al tope anual de $3.5M) — se aplicó la tasa más alta como referencia, pero esto puede indicar que ya no calificas para este régimen.
            </div>
          )}

          <Card style={{marginBottom:12}}>
            <div style={{fontSize:11,color:C.textMuted,marginBottom:12,textTransform:"uppercase",letterSpacing:"0.06em"}}>CFDI PUE incluidos en el cálculo</div>
            {datos.facturas_pue_incluidas.length===0 ? (
              <div style={{color:C.textMuted,fontSize:13}}>Sin CFDI PUE en este periodo.</div>
            ) : (
              <table style={{width:"100%",borderCollapse:"collapse",fontSize:13}}>
                <tbody>
                  {datos.facturas_pue_incluidas.map(f=>(
                    <tr key={f.uuid} style={{borderTop:`1px solid ${C.border}`}}>
                      <td style={{padding:"6px 8px 6px 0",fontFamily:"monospace",fontWeight:600,color:C.primary}}>{f.folio}</td>
                      <td style={{padding:"6px 8px 6px 0",color:C.textSec}}>{f.receptor_rfc}</td>
                      <td style={{padding:"6px 8px 6px 0",textAlign:"right",color:C.text}}>{fmt(f.total)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>

          <Card style={{marginBottom:12}}>
            <div style={{fontSize:11,color:C.textMuted,marginBottom:12,textTransform:"uppercase",letterSpacing:"0.06em"}}>CFDI PPD excluidos del cálculo</div>
            {datos.facturas_ppd_excluidas.length===0 ? (
              <div style={{color:C.textMuted,fontSize:13}}>Sin CFDI PPD en este periodo.</div>
            ) : (
              <>
                <table style={{width:"100%",borderCollapse:"collapse",fontSize:13,marginBottom:10}}>
                  <tbody>
                    {datos.facturas_ppd_excluidas.map(f=>(
                      <tr key={f.uuid} style={{borderTop:`1px solid ${C.border}`}}>
                        <td style={{padding:"6px 8px 6px 0",fontFamily:"monospace",fontWeight:600,color:C.textSec}}>{f.folio}</td>
                        <td style={{padding:"6px 8px 6px 0",color:C.textSec}}>{f.receptor_rfc}</td>
                        <td style={{padding:"6px 8px 6px 0",textAlign:"right",color:C.textSec}}>{fmt(f.total)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <div style={{fontSize:12,color:C.textMuted}}>
                  Excluidos del cálculo — requieren complemento de pago para saber cuándo se cobraron realmente.
                </div>
              </>
            )}
          </Card>
        </>
      )}

      {!loading && !error && datos && (
        <div style={{marginTop:4,padding:"12px 14px",borderRadius:8,background:C.warnSoft,color:C.warn,fontSize:13,fontWeight:600}}>
          ⚠ {datos.disclaimer}
        </div>
      )}
    </div>
  );
}

const VIEWS={
  nueva:<NuevaFactura/>,generadas:<FacturasGeneradas/>,recibidas:<Placeholder title="Facturas recibidas"/>,
  reporte:<ReporteMensual/>,costos:<DashboardCostos/>,contador:<ContadorVirtual/>,lector:<LectorDocumentos/>,chat:<ChatFiscal/>,
  anomalias:<Anomalias/>,conciliacion:<Placeholder title="Conciliación bancaria"/>,
  emisores:<Emisores/>,clientes:<Clientes/>,
  usuarios:<Usuarios/>,series:<Series/>,
  addenda:<Placeholder title="Addenda AES"/>,
};

// ═══════════════════════════════════════════════════════════════════════════════
// ROOT — wrap con ToastProvider
// ═══════════════════════════════════════════════════════════════════════════════
function AuthGate(){
  const auth = useAuth();
  // Si la URL trae ?token=... (link del correo de recuperacion, ver
  // email_sender.py), arranca directo en "reset" sin pasar por "login" -
  // window.location.search se lee UNA vez al montar (useState con
  // funcion inicializadora), no en cada render. Sin react-router en el
  // proyecto: esto es deliberadamente el unico lugar que lee la URL.
  const [vista, setVista] = useState(() => (
    new URLSearchParams(window.location.search).get("token") ? "reset" : "login"
  )); // "login" | "registro" | "olvide" | "reset"
  const tokenReset = new URLSearchParams(window.location.search).get("token");
  if (!auth.isAuthenticated) {
    if (vista === "registro") return <CrearCuenta onRegistro={auth.registro} onIrALogin={()=>setVista("login")}/>;
    if (vista === "olvide") return <OlvideContrasena onSolicitar={auth.solicitarReset} onIrALogin={()=>setVista("login")}/>;
    if (vista === "reset") return <ResetPassword token={tokenReset} onConfirmar={auth.confirmarReset} onIrALogin={()=>setVista("login")}/>;
    return <Login onLogin={auth.login} onIrARegistro={()=>setVista("registro")} onIrAOlvide={()=>setVista("olvide")}/>;
  }
  // AuthGate nunca se desmonta entre login/logout (solo cambia que rama
  // renderiza), asi que "vista" sobrevive el logout tal cual quedo antes
  // de autenticarse - si el usuario paso por "Crear cuenta" antes de
  // loguearse, el logout regresaba ahi en vez de a "Iniciar sesion". Se
  // resetea aqui, no dentro de auth.logout() (useAuth no tiene ni debe
  // tener conocimiento del concepto de "vista", que es puramente de
  // AuthGate).
  const onLogout = () => { auth.logout(); setVista("login"); };
  return <EmisoresProvider><AppShell onLogout={onLogout} usuarioActual={auth.usuarioActual} views={VIEWS} labels={LABELS} nav={NAV}/></EmisoresProvider>;
}

export default function App(){
  return (
    <ToastProvider>
      <AuthGate/>
    </ToastProvider>
  );
}
