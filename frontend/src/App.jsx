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
import NuevaFactura from "./domains/facturacion/NuevaFactura";
import FacturasGeneradas from "./domains/facturacion/FacturasGeneradas";
import ReporteMensual from "./domains/facturacion/ReporteMensual";
import DashboardCostos from "./domains/facturacion/DashboardCostos";
import ContadorVirtual from "./domains/facturacion/ContadorVirtual";


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
