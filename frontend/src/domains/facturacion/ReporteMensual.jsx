import { useReporteMensual } from "./hooks";
import useResumenEjecutivo from "../../shared/hooks/useResumenEjecutivo";
import { Placeholder } from "../../shared/layout/AppShell";
import { SectionTitle, Card, Btn, KPIGrid, KPI, TwoCol } from "../../shared/components/atoms";
import { C, fmt } from "../../shared/utils/format";

const MESES_CORTOS=["Ene","Feb","Mar","Abr","May","Jun","Jul","Ago","Sep","Oct","Nov","Dic"];

export default function ReporteMensual(){
  const { datos, loading, error } = useReporteMensual(6);
  const resumen = useResumenEjecutivo();

  if (error) return <Placeholder title="Reporte mensual" detail={`No se pudo conectar con reportes: ${error}`}/>;
  if (loading) return <Placeholder title="Reporte mensual" detail="Cargando datos reales…"/>;

  const meses = datos?.meses || [];
  const totalFacturas = meses.reduce((s,m)=>s+m.vigente.count+m.cancelada.count, 0);
  if (totalFacturas === 0) return <Placeholder title="Reporte mensual" detail="Todavía no hay facturas timbradas para reportar."/>;

  // vigente/cancelada SEPARADOS (semantica decidida 20 ago 2026, tarjeta
  // PVTI_lAHOBYC0Os4BfCxZzg2m00E) - nunca sumados en un solo total, a
  // diferencia del calculo viejo (useFacturas() + reduce sin filtrar estado).
  const maxV = Math.max(...meses.map(m=>Math.max(m.vigente.total, m.cancelada.total)), 1);
  const totalVigente = meses.reduce((s,m)=>s+m.vigente.total, 0);
  const totalCancelada = meses.reduce((s,m)=>s+m.cancelada.total, 0);
  const countVigente = meses.reduce((s,m)=>s+m.vigente.count, 0);
  const countCancelada = meses.reduce((s,m)=>s+m.cancelada.count, 0);
  const rangoLabel = meses.length>1
    ? `${MESES_CORTOS[meses[0].mes-1]} ${meses[0].anio} – ${MESES_CORTOS[meses[meses.length-1].mes-1]} ${meses[meses.length-1].anio}`
    : `${MESES_CORTOS[meses[0].mes-1]} ${meses[0].anio}`;

  // datos_facturacion mantiene la MISMA forma que ya esperaba el resumen
  // ejecutivo de IA (total_acumulado/num_facturas/promedio/por_mes) - no se
  // rompe esa funcionalidad existente. por_mes ahora trae vigente/cancelada
  // desglosados en vez de un solo numero sumado, mas informativo para el LLM.
  const porMesParaResumen = Object.fromEntries(
    meses.map(m => [`${m.anio}-${String(m.mes).padStart(2,"0")}`, { vigente: m.vigente.total, cancelada: m.cancelada.total }])
  );

  return (
    <div>
      <SectionTitle>Reporte mensual</SectionTitle>
      <Card style={{marginTop:12}}>
        <div style={{fontSize:11,color:C.textMuted,marginBottom:12,textTransform:"uppercase",letterSpacing:"0.06em"}}>Facturación real · {rangoLabel}</div>
        <div style={{display:"flex",alignItems:"flex-end",gap:8,height:150,padding:"0 4px"}}>
          {meses.map((m,i)=>{
            const key = `${m.anio}-${m.mes}`;
            const esUltimo = i===meses.length-1;
            return (
              <div key={key} style={{flex:1,display:"flex",flexDirection:"column",alignItems:"center",gap:4}}>
                <div style={{fontSize:9,color:C.textMuted,textAlign:"center"}}>{(m.vigente.total/1000).toFixed(1)}k</div>
                <div style={{display:"flex",alignItems:"flex-end",gap:2,width:"100%",height:100}}>
                  <div title={`Vigente: ${fmt(m.vigente.total)} (${m.vigente.count})`}
                    style={{flex:1,background:esUltimo?C.accent:C.primary,borderRadius:"5px 5px 0 0",height:`${(m.vigente.total/maxV)*100}px`,minHeight:m.vigente.total>0?2:0,opacity:esUltimo?1:.7}}/>
                  <div title={`Cancelada: ${fmt(m.cancelada.total)} (${m.cancelada.count})`}
                    style={{flex:1,background:C.danger,borderRadius:"5px 5px 0 0",height:`${(m.cancelada.total/maxV)*100}px`,minHeight:m.cancelada.total>0?2:0,opacity:.6}}/>
                </div>
                <div style={{fontSize:11,color:C.textSec,fontWeight:esUltimo?700:400}}>{MESES_CORTOS[m.mes-1]}</div>
              </div>
            );
          })}
        </div>
        <div style={{display:"flex",gap:14,marginTop:8,fontSize:10,color:C.textMuted}}>
          <div style={{display:"flex",alignItems:"center",gap:4}}><span style={{width:8,height:8,borderRadius:2,background:C.primary,display:"inline-block"}}/>Vigente</div>
          <div style={{display:"flex",alignItems:"center",gap:4}}><span style={{width:8,height:8,borderRadius:2,background:C.danger,opacity:.6,display:"inline-block"}}/>Cancelada</div>
        </div>
        <div style={{borderTop:`1px solid ${C.border}`,marginTop:14,paddingTop:12,display:"flex",gap:20,flexWrap:"wrap"}}>
          {[
            ["Vigente (total)",fmt(totalVigente)],
            ["Vigente (CFDIs)",String(countVigente)],
            ["Cancelada (total)",fmt(totalCancelada)],
            ["Cancelada (CFDIs)",String(countCancelada)],
          ].map(([l,v])=>(
            <div key={l}><div style={{fontSize:10,color:C.textMuted,marginBottom:3,textTransform:"uppercase"}}>{l}</div><div style={{fontSize:16,fontWeight:700,color:C.text}}>{v}</div></div>
          ))}
        </div>
        <Btn variant="secondary" style={{marginTop:12}} disabled={resumen.loading}
          onClick={()=>resumen.generar({
            periodo_inicio: `${meses[0].anio}-${String(meses[0].mes).padStart(2,"0")}-01`,
            periodo_fin: new Date().toISOString().slice(0,10),
            datos_facturacion: {
              total_acumulado: totalVigente,
              num_facturas: countVigente,
              promedio: countVigente>0 ? totalVigente/countVigente : 0,
              por_mes: porMesParaResumen,
              cancelado_total: totalCancelada,
              cancelado_count: countCancelada,
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
