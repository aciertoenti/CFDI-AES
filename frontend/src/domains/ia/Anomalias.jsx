import { useState } from "react";
import { useAnomalias } from "./hooks";
import { Card, Btn, SectionTitle, SectionSub } from "../../shared/components/atoms";
import { C, fmt } from "../../shared/utils/format";

// Tarjeta PVTI_lAHOBYC0Os4BfCxZzg3aAWM - FACTURAS es un mock hardcodeado en
// vez de useFacturas() real. Se mueve tal cual, sin arreglar.
const FACTURAS = [
  {folio:"A-0127",receptor:"Coppel SA de CV",total:77600,fecha:"2025-05-19",estado:"Vigente",uuid:"WXY7-ZAB8"},
  {folio:"A-0126",receptor:"OXXO Gas SA de CV",total:32100,fecha:"2025-05-16",estado:"Vigente",uuid:"KLM3-NOP4"},
  {folio:"A-0041",receptor:"Walmart de México",total:89300,fecha:"2025-05-12",estado:"Alerta",uuid:"MNO5-PQR6"},
  {folio:"A-0039",receptor:"FEMSA",total:124750,fecha:"2025-03-14",estado:"Vencida",uuid:"ABC1-DEF2"},
  {folio:"A-0003",receptor:"Tiendas Chedraui",total:9800,fecha:"2025-05-14",estado:"Cancelada",uuid:"YZA9-BCD0"},
];

// ═══════════════════════════════════════════════════════════════════════════════
// VISTA: ANOMALÍAS
// ═══════════════════════════════════════════════════════════════════════════════
export default function Anomalias(){
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
