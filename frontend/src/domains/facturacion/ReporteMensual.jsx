import { useFacturas } from "./hooks";
import useResumenEjecutivo from "../../shared/hooks/useResumenEjecutivo";
import { Placeholder } from "../../shared/layout/AppShell";
import { SectionTitle, Card, Btn, KPIGrid, KPI, TwoCol } from "../../shared/components/atoms";
import { C, fmt } from "../../shared/utils/format";

const FACTURACION_BASE = "http://localhost:8001";
const MESES_CORTOS=["Ene","Feb","Mar","Abr","May","Jun","Jul","Ago","Sep","Oct","Nov","Dic"];

export default function ReporteMensual(){
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
