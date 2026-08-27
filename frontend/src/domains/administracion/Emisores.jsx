import { useEffect, useState } from "react";
import useEmisores from "../../shared/hooks/useEmisores";
import { useToast } from "../../shared/layout/ToastProvider";
import { API_BASE, fetchAuth } from "../../shared/hooks/fetchAuth";
import { Btn, Card, TwoCol, SectionTitle, SectionSub } from "../../shared/components/atoms";
import { C, detalleError } from "../../shared/utils/format";
import { Placeholder } from "../../shared/layout/AppShell";
import AltaEmisorForm from "./AltaEmisorForm";
import EditarEmisorModal from "./EditarEmisorModal";
import ReemplazarCsdForm from "./ReemplazarCsdForm";
import EliminarEmisorConfirm from "./EliminarEmisorConfirm";

export default function Emisores() {
  const {emisores,loading,error,recargar,emisorActivoRfc,setEmisorActivoRfc}=useEmisores();
  const toast=useToast();
  const [mostrandoFormulario,setMostrandoFormulario]=useState(null);
  const [accionActiva,setAccionActiva]=useState(null); // {tipo:'editar'|'csd'|'eliminar', emisor} | null
  const [togglingRfc,setTogglingRfc]=useState(null); // rfc del emisor cuyo Inactivar/Activar esta en curso
  useEffect(()=>{if(!loading&&mostrandoFormulario===null)setMostrandoFormulario(emisores.length===0);},[loading,emisores,mostrandoFormulario]);
  if(error)return <Placeholder title="Emisores" detail={`No se pudo conectar con administracion: ${error}`}/>;
  if(loading||mostrandoFormulario===null)return <Placeholder title="Emisores" detail="Cargando datos reales…"/>;
  if(mostrandoFormulario)return <AltaEmisorForm onCreado={()=>{recargar();setMostrandoFormulario(false);}} onCancelar={emisores.length>0?()=>setMostrandoFormulario(false):undefined}/>;
  const cerrarAccion=()=>setAccionActiva(null);
  // Inactivar/Activar es reversible (un click mas): accion directa via PATCH,
  // sin modal ni confirmacion por texto (a diferencia de Eliminar).
  const toggleEstado=async emisor=>{
    const nuevo=emisor.estado==="Activo"?"Inactivo":"Activo";
    setTogglingRfc(emisor.rfc);
    try{
      const res=await fetchAuth(`${API_BASE}/admin/emisores/${emisor.rfc}`,{method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify({estado:nuevo})});
      const data=await res.json().catch(()=>({}));
      if(!res.ok)throw new Error(detalleError(data,res));
      toast(`Emisor ${emisor.rfc} ${nuevo==="Inactivo"?"inactivado":"activado"}`,"success");
      recargar();
    }catch(e){
      toast(`Error al cambiar el estado: ${e.message}`,"error");
    }finally{
      setTogglingRfc(null);
    }
  };
  return <div><div style={{display:"flex",justifyContent:"space-between",alignItems:"flex-start",gap:12,flexWrap:"wrap"}}><div><SectionTitle>Emisores</SectionTitle><SectionSub>Clic en una tarjeta para cambiar el emisor activo.</SectionSub></div><Btn type="button" variant="secondary" onClick={()=>setMostrandoFormulario(true)}>+ Agregar otro emisor</Btn></div><TwoCol>{emisores.map(emisor=>{const activo=emisor.rfc===emisorActivoRfc;return <Card key={emisor.rfc} style={{cursor:"pointer",border:`1px solid ${activo?C.accent:C.border}`}} onClick={()=>setEmisorActivoRfc(emisor.rfc)}><div style={{display:"flex",justifyContent:"space-between",alignItems:"flex-start",marginBottom:10,gap:8}}><div style={{minWidth:0}}><div style={{fontSize:14,fontWeight:600,color:C.text,overflow:"hidden",textOverflow:"ellipsis",whiteSpace:"nowrap"}}>{emisor.razon_social}</div><div style={{fontSize:12,color:C.textMuted,fontFamily:"monospace",marginTop:2}}>{emisor.rfc}</div></div><div style={{display:"flex",flexDirection:"column",gap:4,alignItems:"flex-end",flexShrink:0}}>{activo&&<span style={{background:C.accentSoft,color:C.accentBorder,fontSize:11,fontWeight:600,padding:"3px 10px",borderRadius:20}}>✓ Seleccionado</span>}<span style={{background:emisor.estado==="Activo"?C.accentSoft:C.dangerSoft,color:emisor.estado==="Activo"?C.accentBorder:C.danger,fontSize:11,fontWeight:600,padding:"3px 10px",borderRadius:20}}>{emisor.estado}</span></div></div><div style={{fontSize:13,color:C.textSec,marginBottom:4}}>Régimen fiscal: <strong style={{color:C.text}}>{emisor.regimen_fiscal}</strong></div><div style={{fontSize:13,color:C.textSec,marginBottom:4}}>CP expedición: <strong style={{color:C.text}}>{emisor.codigo_postal}</strong></div><div style={{fontSize:13,color:C.textSec,marginBottom:4}}>Dado de alta por: <strong style={{color:C.text}}>{emisor.creado_por_rfc||"—"}</strong></div><div style={{fontSize:13,color:C.textSec,marginBottom:10}}>Modificado por: <strong style={{color:C.text}}>{emisor.modificado_por_rfc||"—"}</strong></div><div style={{display:"flex",gap:6,flexWrap:"wrap"}}><Btn type="button" variant="secondary" style={{flex:"1 1 45%",fontSize:12,padding:"6px 10px"}} onClick={e=>{e.stopPropagation();setAccionActiva({tipo:"editar",emisor});}}>Editar</Btn><Btn type="button" variant="secondary" style={{flex:"1 1 45%",fontSize:12,padding:"6px 10px"}} onClick={e=>{e.stopPropagation();setAccionActiva({tipo:"csd",emisor});}}>Reemplazar certificado</Btn><Btn type="button" variant="secondary" disabled={togglingRfc===emisor.rfc} style={{flex:"1 1 45%",fontSize:12,padding:"6px 10px"}} onClick={e=>{e.stopPropagation();toggleEstado(emisor);}}>{togglingRfc===emisor.rfc?"…":(emisor.estado==="Activo"?"Inactivar":"Activar")}</Btn><Btn type="button" variant="secondary" style={{flex:"1 1 45%",fontSize:12,padding:"6px 10px",color:C.danger,borderColor:C.danger}} onClick={e=>{e.stopPropagation();setAccionActiva({tipo:"eliminar",emisor});}}>Eliminar</Btn></div></Card>;})}</TwoCol>
    {accionActiva?.tipo==="editar"&&<EditarEmisorModal emisor={accionActiva.emisor} onCerrar={cerrarAccion} recargar={recargar}/>}
    {accionActiva?.tipo==="csd"&&<ReemplazarCsdForm emisor={accionActiva.emisor} onCerrar={cerrarAccion} recargar={recargar}/>}
    {accionActiva?.tipo==="eliminar"&&<EliminarEmisorConfirm emisor={accionActiva.emisor} onCerrar={cerrarAccion} recargar={recargar}/>}
  </div>;
}
