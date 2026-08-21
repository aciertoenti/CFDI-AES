import { useEffect, useState } from "react";
import useEmisores from "../../shared/hooks/useEmisores";
import { Btn, Card, TwoCol, SectionTitle, SectionSub } from "../../shared/components/atoms";
import { C } from "../../shared/utils/format";
import { Placeholder } from "../../shared/layout/AppShell";
import AltaEmisorForm from "./AltaEmisorForm";

export default function Emisores() {
  const {emisores,loading,error,recargar,emisorActivoRfc,setEmisorActivoRfc}=useEmisores();
  const [mostrandoFormulario,setMostrandoFormulario]=useState(null);
  useEffect(()=>{if(!loading&&mostrandoFormulario===null)setMostrandoFormulario(emisores.length===0);},[loading,emisores,mostrandoFormulario]);
  if(error)return <Placeholder title="Emisores" detail={`No se pudo conectar con administracion: ${error}`}/>;
  if(loading||mostrandoFormulario===null)return <Placeholder title="Emisores" detail="Cargando datos reales…"/>;
  if(mostrandoFormulario)return <AltaEmisorForm onCreado={()=>{recargar();setMostrandoFormulario(false);}} onCancelar={emisores.length>0?()=>setMostrandoFormulario(false):undefined}/>;
  return <div><div style={{display:"flex",justifyContent:"space-between",alignItems:"flex-start",gap:12,flexWrap:"wrap"}}><div><SectionTitle>Emisores</SectionTitle><SectionSub>Solo lectura por ahora — editar queda fuera de alcance hoy. Clic en una tarjeta para cambiar el emisor activo.</SectionSub></div><Btn type="button" variant="secondary" onClick={()=>setMostrandoFormulario(true)}>+ Agregar otro emisor</Btn></div><TwoCol>{emisores.map(emisor=>{const activo=emisor.rfc===emisorActivoRfc;return <Card key={emisor.rfc} style={{cursor:"pointer",border:`1px solid ${activo?C.accent:C.border}`}} onClick={()=>setEmisorActivoRfc(emisor.rfc)}><div style={{display:"flex",justifyContent:"space-between",alignItems:"flex-start",marginBottom:10,gap:8}}><div style={{minWidth:0}}><div style={{fontSize:14,fontWeight:600,color:C.text,overflow:"hidden",textOverflow:"ellipsis",whiteSpace:"nowrap"}}>{emisor.razon_social}</div><div style={{fontSize:12,color:C.textMuted,fontFamily:"monospace",marginTop:2}}>{emisor.rfc}</div></div><div style={{display:"flex",flexDirection:"column",gap:4,alignItems:"flex-end",flexShrink:0}}>{activo&&<span style={{background:C.accentSoft,color:C.accentBorder,fontSize:11,fontWeight:600,padding:"3px 10px",borderRadius:20}}>✓ Seleccionado</span>}<span style={{background:emisor.estado==="Activo"?C.accentSoft:C.dangerSoft,color:emisor.estado==="Activo"?C.accentBorder:C.danger,fontSize:11,fontWeight:600,padding:"3px 10px",borderRadius:20}}>{emisor.estado}</span></div></div><div style={{fontSize:13,color:C.textSec,marginBottom:4}}>Régimen fiscal: <strong style={{color:C.text}}>{emisor.regimen_fiscal}</strong></div><div style={{fontSize:13,color:C.textSec,marginBottom:4}}>CP expedición: <strong style={{color:C.text}}>{emisor.codigo_postal}</strong></div><div style={{fontSize:13,color:C.textSec}}>Dado de alta por: <strong style={{color:C.text}}>{emisor.creado_por_rfc||"—"}</strong></div></Card>;})}</TwoCol></div>;
}
