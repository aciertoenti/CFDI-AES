import { useEffect, useState } from "react";
import { API_BASE, fetchAuth } from "../../shared/hooks/fetchAuth";
import { Card, SectionTitle, SectionSub } from "../../shared/components/atoms";
import { C } from "../../shared/utils/format";
import { Placeholder } from "../../shared/layout/AppShell";

export default function Usuarios() {
  const [usuarios,setUsuarios]=useState([]),[loading,setLoading]=useState(true),[error,setError]=useState(null);
  useEffect(()=>{(async()=>{try{const res=await fetchAuth(`${API_BASE}/auth/usuarios`);if(!res.ok)throw new Error(`HTTP ${res.status}`);setUsuarios(await res.json());}catch(e){setError(e.message);}finally{setLoading(false);}})();},[]);
  if(error)return <Placeholder title="Usuarios" detail={`No se pudo conectar con auth: ${error}`}/>;
  if(loading)return <Placeholder title="Usuarios" detail="Cargando datos reales…"/>;
  if(usuarios.length===0)return <Placeholder title="Usuarios" detail="Todavía no hay usuarios registrados."/>;
  return <div><SectionTitle>Usuarios</SectionTitle><SectionSub>Solo lectura — promover a admin y editar/eliminar quedan fuera hasta resolver el diseño de roles (ver #10).</SectionSub><Card><table style={{width:"100%",borderCollapse:"collapse",fontSize:13}}><thead><tr style={{textAlign:"left",color:C.textMuted,fontSize:11,textTransform:"uppercase"}}>{["Email","RFC","Nombre","Usuario","Rol","Creado"].map(label=><th key={label} style={{padding:"6px 8px 10px 0"}}>{label}</th>)}</tr></thead><tbody>{usuarios.map(user=><tr key={user.id} style={{borderTop:`1px solid ${C.border}`}}><td style={{padding:"8px 8px 8px 0",color:C.text}}>{user.email}</td><td style={{padding:"8px 8px 8px 0",color:C.textSec}}>{user.rfc_personal}</td><td style={{padding:"8px 8px 8px 0",color:C.textSec}}>{user.nombre||"—"}</td><td style={{padding:"8px 8px 8px 0",color:C.textSec}}>{user.usuario||"—"}</td><td style={{padding:"8px 8px 8px 0"}}><span style={{background:user.rol==="admin"?C.accentSoft:C.infoSoft,color:user.rol==="admin"?C.accentBorder:C.info,fontSize:11,fontWeight:600,padding:"3px 10px",borderRadius:20}}>{user.rol}</span></td><td style={{padding:"8px 8px 8px 0",color:C.textSec}}>{new Date(user.created_at).toLocaleDateString("es-MX")}</td></tr>)}</tbody></table></Card></div>;
}
