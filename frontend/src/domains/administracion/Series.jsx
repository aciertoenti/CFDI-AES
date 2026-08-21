import { useEffect, useState } from "react";
import { API_BASE, fetchAuth } from "../../shared/hooks/fetchAuth";
import { Card } from "../../shared/components/atoms";
import { C } from "../../shared/utils/format";
import { Placeholder } from "../../shared/layout/AppShell";
import { SectionTitle, SectionSub } from "./shared";

export default function Series() {
  const [series,setSeries]=useState([]), [loading,setLoading]=useState(true), [error,setError]=useState(null);
  useEffect(()=>{(async()=>{try{const res=await fetchAuth(`${API_BASE}/admin/series`);if(!res.ok)throw new Error(`HTTP ${res.status}`);setSeries(await res.json());}catch(e){setError(e.message);}finally{setLoading(false);}})();},[]);
  if(error)return <Placeholder title="Series y folios" detail={`No se pudo conectar con administracion: ${error}`}/>;
  if(loading)return <Placeholder title="Series y folios" detail="Cargando datos reales…"/>;
  if(series.length===0)return <Placeholder title="Series y folios" detail="Todavía no hay series en uso — se crean automáticamente al primer timbrado."/>;
  return <div><SectionTitle>Series y folios</SectionTitle><SectionSub>Solo lectura — las series se crean automáticamente al primer timbrado, no hay alta manual todavía.</SectionSub><Card><table style={{width:"100%",borderCollapse:"collapse",fontSize:13}}><thead><tr style={{textAlign:"left",color:C.textMuted,fontSize:11,textTransform:"uppercase"}}><th style={{padding:"6px 8px 10px 0"}}>Emisor</th><th style={{padding:"6px 8px 10px 0"}}>Serie</th><th style={{padding:"6px 8px 10px 0"}}>Último folio</th></tr></thead><tbody>{series.map(item=><tr key={`${item.emisor_rfc}-${item.serie}`} style={{borderTop:`1px solid ${C.border}`}}><td style={{padding:"8px 8px 8px 0",color:C.textSec,fontFamily:"monospace"}}>{item.emisor_rfc}</td><td style={{padding:"8px 8px 8px 0",fontWeight:600,color:C.text}}>{item.serie}</td><td style={{padding:"8px 8px 8px 0",color:C.textSec}}>{item.ultimo_folio}</td></tr>)}</tbody></table></Card></div>;
}
