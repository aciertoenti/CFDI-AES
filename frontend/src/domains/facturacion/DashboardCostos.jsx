import useEmisores from "../../shared/hooks/useEmisores";
import { useCostosResumen } from "./hooks";
import { Placeholder } from "../../shared/layout/AppShell";
import { SectionTitle, SectionSub, Card, KPIGrid, KPI } from "../../shared/components/atoms";
import { C, fmt } from "../../shared/utils/format";

const FACTURACION_BASE = "http://localhost:8001";

export default function DashboardCostos(){
  const { emisorActivoRfc } = useEmisores();
  const {datos,loading,error} = useCostosResumen(emisorActivoRfc);

  if (error) return <Placeholder title="Dashboard de costos" detail={`No se pudo conectar con facturacion (${FACTURACION_BASE}): ${error}`}/>;
  if (loading) return <Placeholder title="Dashboard de costos" detail="Cargando datos reales…"/>;

  const costoTotal = datos.reduce((s,d)=>s+d.costo_total,0);
  const timbresTotal = datos.reduce((s,d)=>s+d.num_timbres,0);
  const costoPromedio = timbresTotal>0 ? costoTotal/timbresTotal : 0;

  return (
    <div>
      <SectionTitle>Dashboard de costos</SectionTitle>
      <SectionSub>Costo real de Finkok por timbre (#6) · margen y costo de WhatsApp fuera de alcance por ahora (#7, #16)</SectionSub>

      <KPIGrid>
        <KPI label="Costo Finkok acumulado" value={fmt(costoTotal)} sub={`${timbresTotal} timbre${timbresTotal===1?"":"s"}`} dark/>
        <KPI label="Costo promedio por timbre" value={fmt(costoPromedio)}/>
        <KPI label="Costo WhatsApp por interacción" value="Pendiente" sub="Requiere #7 (en pausa)"/>
        <KPI label="Margen por negocio" value="Pendiente" sub="Requiere #7 + #16 (precios)"/>
      </KPIGrid>

      <Card>
        <div style={{fontSize:11,color:C.textMuted,marginBottom:12,textTransform:"uppercase",letterSpacing:"0.06em"}}>Desglose por mes y emisor</div>
        {datos.length===0 ? (
          <div style={{color:C.textMuted,fontSize:13,padding:"12px 0"}}>Todavía no hay timbres con costo registrado (#6 solo aplica a timbrados posteriores a su implementación).</div>
        ) : (
          <table style={{width:"100%",borderCollapse:"collapse",fontSize:13}}>
            <thead>
              <tr style={{textAlign:"left",color:C.textMuted,fontSize:11,textTransform:"uppercase"}}>
                <th style={{padding:"6px 8px 10px 0"}}>Periodo</th>
                <th style={{padding:"6px 8px 10px 0"}}>Emisor</th>
                <th style={{padding:"6px 8px 10px 0"}}>Timbres</th>
                <th style={{padding:"6px 8px 10px 0"}}>Costo total</th>
                <th style={{padding:"6px 8px 10px 0"}}>Costo promedio</th>
              </tr>
            </thead>
            <tbody>
              {datos.map((d,i)=>(
                <tr key={`${d.periodo}-${d.emisor_rfc}`} style={{borderTop:`1px solid ${C.border}`}}>
                  <td style={{padding:"8px 8px 8px 0",fontWeight:600,color:C.text}}>{d.periodo}</td>
                  <td style={{padding:"8px 8px 8px 0",color:C.textSec}}>{d.emisor_rfc}</td>
                  <td style={{padding:"8px 8px 8px 0",color:C.textSec}}>{d.num_timbres}</td>
                  <td style={{padding:"8px 8px 8px 0",color:C.text}}>{fmt(d.costo_total)}</td>
                  <td style={{padding:"8px 8px 8px 0",color:C.textSec}}>{fmt(d.costo_promedio)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <div style={{marginTop:14,padding:"10px 12px",borderRadius:8,background:C.warnSoft,color:C.warn,fontSize:12}}>
          ⏳ Pendiente: costo de conversación de WhatsApp (#7, en pausa) y cálculo de margen por negocio (#16, precios diferidos) — se agregarán a este dashboard cuando esas tarjetas se resuelvan. No se muestran como $0 para no dar una cifra falsa.
        </div>
      </Card>
    </div>
  );
}
