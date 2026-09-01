import { useState, useEffect, useRef } from "react";
import useBreakpoint from "../../shared/hooks/useBreakpoint";
import useEmisores from "../../shared/hooks/useEmisores";
import { useFiscalChat } from "./hooks";
import { Card, Btn, SectionTitle } from "../../shared/components/atoms";
import { C } from "../../shared/utils/format";

// Tarjeta PVTI_lAHOBYC0Os4BfCxZzg3aTVM - CUENTA_CTX es un mock hardcodeado,
// no datos reales de la cuenta. Se mueve tal cual, sin arreglar.
const CUENTA_CTX = {iva_pendiente:38640,facturas_vigentes:4,facturas_vencidas:1,total_mayo:302450,cuentas_por_cobrar:246150,proximo_vencimiento_iva:"2025-06-17"};
const SUGERENCIAS = [
  "¿Cuánto IVA tengo pendiente?","¿Qué clientes tienen RFC en riesgo?",
  "¿Cuánto me deben mis clientes?","Resumen ejecutivo de mayo",
];

// ═══════════════════════════════════════════════════════════════════════════════
// VISTA: CHAT FISCAL
// ═══════════════════════════════════════════════════════════════════════════════
export default function ChatFiscal(){
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
        <div><SectionTitle>Asistente de IA</SectionTitle><p style={{fontSize:12,color:C.textSec,margin:0}}>Conectado · RFC {emisorActual?.rfc||"—"}</p></div>
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
