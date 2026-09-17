import { useState, useEffect, useRef } from "react";
import useBreakpoint from "../../shared/hooks/useBreakpoint";
import useEmisores from "../../shared/hooks/useEmisores";
import { useFiscalChat } from "./hooks";
import { useFacturas, useReporteMensual } from "../facturacion/hooks";
import { Card, Btn, SectionTitle } from "../../shared/components/atoms";
import { C } from "../../shared/utils/format";

const SUGERENCIAS = [
  "¿Cuánto IVA tengo pendiente?","¿Qué clientes tienen RFC en riesgo?",
  "¿Cuánto me deben mis clientes?","Resumen ejecutivo de mayo",
];

// Vencimiento de IVA para régimen 625 (Plataformas Tecnológicas): día 17
// del mes siguiente al actual - calculo puro de fecha, sin llamada a
// backend (Fase 1 de zg3aTVM, 17 sep 2026).
function calcularProximoVencimientoIVA() {
  const hoy = new Date();
  const anioSig = hoy.getMonth() === 11 ? hoy.getFullYear() + 1 : hoy.getFullYear();
  const mesSig = (hoy.getMonth() + 1) % 12; // Date usa mes 0-indexado
  const fecha = new Date(anioSig, mesSig, 17);
  return `${fecha.getFullYear()}-${String(fecha.getMonth() + 1).padStart(2, "0")}-${String(fecha.getDate()).padStart(2, "0")}`;
}

// ═══════════════════════════════════════════════════════════════════════════════
// VISTA: CHAT FISCAL
// ═══════════════════════════════════════════════════════════════════════════════
export default function ChatFiscal(){
  const {isMobile}=useBreakpoint();
  const {messages,send,streaming,reset,abort}=useFiscalChat();
  const {emisores,emisorActivoRfc}=useEmisores();
  const emisorActual=emisores.find(e=>e.rfc===emisorActivoRfc);
  // Fase 1 de zg3aTVM (17 sep 2026): fuentes reales para el contexto del
  // modo "cuenta", en vez del mock CUENTA_CTX que vivia aqui hasta ahora.
  const {facturas,loading:loadingFacturas}=useFacturas(emisorActivoRfc);
  // useReporteMensual(1) trae solo el mes en curso. OJO: GET /reportes/mensual
  // agrega por NEGOCIO completo (no acepta emisor_rfc) - a diferencia de
  // facturas_vigentes/vencidas (por emisor activo), total_mes_actual queda
  // a nivel negocio porque no existe hoy un endpoint de reporte por-emisor.
  const {datos:reporteMensual,loading:loadingReporte}=useReporteMensual(1);
  const [input,setInput]=useState("");
  // Modo del chat (20 ago 2026, tarjeta 2mSpU) - "cuenta" es el default para
  // no cambiar el comportamiento existente de nadie que ya use el chat.
  // Decorativo con useEmisores (header de abajo) no se toca: es independiente
  // del modo, solo muestra el RFC conectado.
  const [modo,setModo]=useState("cuenta");
  const bottomRef=useRef();
  useEffect(()=>{bottomRef.current?.scrollIntoView({behavior:"smooth"});},[messages]);

  // contextoCuenta real (Fase 1 de zg3aTVM, 17 sep 2026 - reemplaza el mock
  // CUENTA_CTX que vivia hardcodeado aqui). Campos resueltos con fuente
  // real y segura:
  //   - facturas_vigentes: facturas.filter(estado==="Vigente").length,
  //     via useFacturas(emisorActivoRfc) - mismo hook/patron que el resto
  //     de la app (Generadas, DashboardCostos, Anomalias).
  //   - total_mes_actual: GET /reportes/mensual (vigente.total del mes en
  //     curso) - NUNCA se suma vigente+cancelada (regla explicita del
  //     propio endpoint, ver reportes/main.py), asi que este numero
  //     representa solo lo vigente, no lo cancelado.
  //   - proximo_vencimiento_iva: calculo puro de fecha (dia 17 del mes
  //     siguiente, regla del regimen 625), sin backend.
  // Campos en null a proposito, SIN fuente real hoy (confirmado con grep
  // en todo backend/microservices/**/*.py y con SELECT DISTINCT estado
  // contra Postgres real) - ver g7gg8k (Fase 2) para la decision de
  // producto/fiscal pendiente antes de implementarlos:
  //   - facturas_vencidas: Factura.estado nunca toma el valor "Vencida"
  //     en el backend real (no hay columna de fecha de vencimiento) - el
  //     filtro equivalente en FacturasGeneradas.jsx es codigo muerto hoy
  //     (siempre 0). Reportar 0 aqui seria tan enganoso como el mock
  //     original, asi que queda en null en vez de un 0 que aparente ser
  //     un calculo real.
  //   - iva_pendiente / cuentas_por_cobrar: sin calculo fiscal equivalente
  //     en ningun microservicio hoy.
  // JSON.stringify (en useFiscalChat) serializa null como el literal
  // `null`, no como undefined - el backend (ia/main.py, contexto_cuenta:
  // Optional[dict]) lo acepta sin romper y lo muestra tal cual en el
  // prompt real a Claude (confirmado leyendo _construir_system_prompt).
  const cuentaCtxListo = !loadingFacturas && !loadingReporte;
  const contextoCuenta = {
    facturas_vigentes: facturas.filter(f=>f.estado==="Vigente").length,
    facturas_vencidas: null,
    total_mes_actual: reporteMensual?.meses?.[0]?.vigente?.total ?? null,
    proximo_vencimiento_iva: calcularProximoVencimientoIVA(),
    iva_pendiente: null,
    cuentas_por_cobrar: null,
  };

  // Mientras loading de facturas o del reporte mensual sigan en true, el
  // modo "cuenta" no debe mandar un contexto a medio calcular (ej.
  // facturas_vigentes en 0 porque useFacturas todavia no respondio, no
  // porque de verdad sean 0) - mismo criterio de "esperar antes de
  // habilitar el envio" que ya usa Anomalias.jsx con loadingFacturas.
  // El modo "general" nunca manda contexto_cuenta (ver hooks.js), asi que
  // no depende de este flag.
  const bloqueadoPorCarga = modo==="cuenta" && !cuentaCtxListo;
  const enviar = (texto) => { if(!texto.trim()||streaming||bloqueadoPorCarga) return; send(texto.trim(),contextoCuenta,modo); };
  const submit=()=>{ enviar(input); setInput(""); };
  return (
    <div style={{display:"flex",flexDirection:"column",height:isMobile?"calc(100dvh - 170px)":"calc(100vh - 155px)",gap:10}}>
      <div style={{display:"flex",alignItems:"center",justifyContent:"space-between",flexWrap:"wrap",gap:8}}>
        <div><SectionTitle>Asistente de IA</SectionTitle><p style={{fontSize:12,color:C.textSec,margin:0}}>Conectado · RFC {emisorActual?.rfc||"—"}</p></div>
        <div style={{display:"flex",gap:8}}>
          {streaming&&<Btn variant="secondary" onClick={abort} style={{fontSize:12,padding:"6px 12px"}}>Detener</Btn>}
          <Btn variant="secondary" onClick={reset} style={{fontSize:12,padding:"6px 12px"}}>Nueva conversación</Btn>
        </div>
      </div>
      <div style={{display:"flex",alignItems:"center",gap:6,flexWrap:"wrap"}}>
        {[["cuenta","Mi cuenta"],["general","Consulta general"]].map(([id,lbl])=>(
          <button key={id} onClick={()=>setModo(id)}
            style={{fontSize:11,padding:"5px 10px",borderRadius:12,border:`1px solid ${modo===id?C.accent:C.border}`,
              background:modo===id?C.accentSoft:"transparent",color:modo===id?C.accentBorder:C.textSec,cursor:"pointer",whiteSpace:"nowrap"}}>
            {lbl}
          </button>
        ))}
        {bloqueadoPorCarga&&<span style={{fontSize:11,color:C.textMuted}}>Cargando datos de tu cuenta…</span>}
      </div>
      <Card style={{flex:1,overflowY:"auto",padding:14,display:"flex",flexDirection:"column",gap:10,minHeight:0}}>
        {messages.length===0&&(
          <div style={{display:"flex",flexDirection:"column",alignItems:"center",justifyContent:"center",height:"100%",gap:14,padding:"0 10px"}}>
            <div style={{width:48,height:48,borderRadius:14,background:C.primary,display:"flex",alignItems:"center",justifyContent:"center",fontSize:22}}>🤖</div>
            <div style={{fontSize:14,fontWeight:600,color:C.text,textAlign:"center"}}>¿En qué te ayudo hoy?</div>
            <div style={{display:"flex",flexWrap:"wrap",gap:8,justifyContent:"center"}}>
              {SUGERENCIAS.map(s=>(
                <button key={s} onClick={()=>enviar(s)} disabled={bloqueadoPorCarga}
                  style={{fontSize:12,padding:"7px 12px",borderRadius:20,border:`1px solid ${C.border}`,background:C.surface,color:C.textSec,cursor:bloqueadoPorCarga?"default":"pointer",textAlign:"left",opacity:bloqueadoPorCarga?.5:1}}>
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
        <Btn onClick={submit} disabled={streaming||bloqueadoPorCarga} style={{padding:"10px 16px",flexShrink:0}}>→</Btn>
      </div>
    </div>
  );
}
