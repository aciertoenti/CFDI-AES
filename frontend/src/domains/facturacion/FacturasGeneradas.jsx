import { useState } from "react";
import useBreakpoint from "../../shared/hooks/useBreakpoint";
import { useToast } from "../../shared/layout/ToastProvider";
import useEmisores from "../../shared/hooks/useEmisores";
import { useFacturas } from "./hooks";
import { SectionTitle, KPIGrid, KPI, Card, Badge } from "../../shared/components/atoms";
import { Placeholder } from "../../shared/layout/AppShell";
import { C, fmt } from "../../shared/utils/format";

const FACTURACION_BASE = "http://localhost:8001";
const TH = {padding:"9px 12px",textAlign:"left",fontSize:10,fontWeight:700,color:C.textMuted,textTransform:"uppercase",letterSpacing:"0.06em",whiteSpace:"nowrap"};
const TD = {padding:"10px 12px",color:C.text};

export default function FacturasGeneradas(){
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
