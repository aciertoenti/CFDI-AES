import { useState } from "react";
import useEmisores from "../../shared/hooks/useEmisores";
import { useContadorVirtualISRResico } from "./hooks";
import { Placeholder } from "../../shared/layout/AppShell";
import { SectionTitle, SectionSub, Card, KPIGrid, KPI } from "../../shared/components/atoms";
import { C, fmt } from "../../shared/utils/format";

const ADMINISTRACION_BASE = "http://localhost:8002";
const FACTURACION_BASE = "http://localhost:8001";

export default function ContadorVirtual(){
  const {emisores,loading:loadingEmisores,error:errorEmisores,emisorActivoRfc} = useEmisores();
  const emisor = emisores.find(e=>e.rfc===emisorActivoRfc);
  const hoy = new Date();
  const [periodo,setPeriodo] = useState(`${hoy.getFullYear()}-${String(hoy.getMonth()+1).padStart(2,"0")}`);
  const [anio,mes] = periodo.split("-").map(Number);
  const {datos,loading,error} = useContadorVirtualISRResico(emisor?.rfc, anio, mes);

  if (errorEmisores) return <Placeholder title="Cálculo de impuestos" detail={`No se pudo conectar con administracion (${ADMINISTRACION_BASE}): ${errorEmisores}`}/>;
  if (loadingEmisores) return <Placeholder title="Cálculo de impuestos" detail="Cargando datos reales…"/>;
  if (!emisor) return <Placeholder title="Cálculo de impuestos" detail="Todavía no hay un emisor registrado."/>;

  return (
    <div>
      <SectionTitle>Cálculo de impuestos — ISR provisional (RESICO PF)</SectionTitle>
      <SectionSub>Fase 1 de #40: solo RESICO Personas Físicas, solo ingresos ya facturados con pago en una sola exhibición (PUE).</SectionSub>

      <Card style={{marginBottom:12}}>
        <label style={{fontSize:12,color:C.textSec,display:"block",marginBottom:6}}>Periodo</label>
        <input type="month" value={periodo} onChange={e=>setPeriodo(e.target.value)}
          style={{border:`1px solid ${C.border}`,borderRadius:8,padding:"8px 11px",fontSize:13,color:C.text,background:"#fff"}}/>
      </Card>

      {loading && <Placeholder title="Cálculo de impuestos" detail="Calculando…"/>}
      {!loading && error && <Placeholder title="Cálculo de impuestos" detail={`No se pudo conectar con facturacion (${FACTURACION_BASE}): ${error}`}/>}

      {!loading && !error && datos && !datos.aplica && (
        <Card>
          <div style={{fontSize:14,fontWeight:600,color:C.text,marginBottom:6}}>No aplica para tu régimen fiscal</div>
          <div style={{fontSize:13,color:C.textSec}}>{datos.motivo_no_aplica}</div>
        </Card>
      )}

      {!loading && !error && datos && datos.aplica && (
        <>
          <KPIGrid>
            <KPI label="Ingreso PUE del periodo" value={fmt(datos.ingreso_pue_incluido)} sub={`${datos.facturas_pue_incluidas.length} factura${datos.facturas_pue_incluidas.length===1?"":"s"}`} dark/>
            <KPI label="Tasa aplicada" value={`${(datos.tasa_aplicada*100).toFixed(2)}%`}/>
            <KPI label="ISR provisional estimado" value={fmt(datos.isr_estimado)}/>
          </KPIGrid>

          {datos.excede_tope_mensual && (
            <div style={{marginBottom:12,padding:"10px 12px",borderRadius:8,background:C.dangerSoft,color:C.danger,fontSize:12}}>
              ⚠ El ingreso del mes excede el tope mensual normal de RESICO (~$291,666.67, equivalente al tope anual de $3.5M) — se aplicó la tasa más alta como referencia, pero esto puede indicar que ya no calificas para este régimen.
            </div>
          )}

          <Card style={{marginBottom:12}}>
            <div style={{fontSize:11,color:C.textMuted,marginBottom:12,textTransform:"uppercase",letterSpacing:"0.06em"}}>CFDI PUE incluidos en el cálculo</div>
            {datos.facturas_pue_incluidas.length===0 ? (
              <div style={{color:C.textMuted,fontSize:13}}>Sin CFDI PUE en este periodo.</div>
            ) : (
              <table style={{width:"100%",borderCollapse:"collapse",fontSize:13}}>
                <tbody>
                  {datos.facturas_pue_incluidas.map(f=>(
                    <tr key={f.uuid} style={{borderTop:`1px solid ${C.border}`}}>
                      <td style={{padding:"6px 8px 6px 0",fontFamily:"monospace",fontWeight:600,color:C.primary}}>{f.folio}</td>
                      <td style={{padding:"6px 8px 6px 0",color:C.textSec}}>{f.receptor_rfc}</td>
                      <td style={{padding:"6px 8px 6px 0",textAlign:"right",color:C.text}}>{fmt(f.total)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>

          <Card style={{marginBottom:12}}>
            <div style={{fontSize:11,color:C.textMuted,marginBottom:12,textTransform:"uppercase",letterSpacing:"0.06em"}}>CFDI PPD excluidos del cálculo</div>
            {datos.facturas_ppd_excluidas.length===0 ? (
              <div style={{color:C.textMuted,fontSize:13}}>Sin CFDI PPD en este periodo.</div>
            ) : (
              <>
                <table style={{width:"100%",borderCollapse:"collapse",fontSize:13,marginBottom:10}}>
                  <tbody>
                    {datos.facturas_ppd_excluidas.map(f=>(
                      <tr key={f.uuid} style={{borderTop:`1px solid ${C.border}`}}>
                        <td style={{padding:"6px 8px 6px 0",fontFamily:"monospace",fontWeight:600,color:C.textSec}}>{f.folio}</td>
                        <td style={{padding:"6px 8px 6px 0",color:C.textSec}}>{f.receptor_rfc}</td>
                        <td style={{padding:"6px 8px 6px 0",textAlign:"right",color:C.textSec}}>{fmt(f.total)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <div style={{fontSize:12,color:C.textMuted}}>
                  Excluidos del cálculo — requieren complemento de pago para saber cuándo se cobraron realmente.
                </div>
              </>
            )}
          </Card>
        </>
      )}

      {!loading && !error && datos && (
        <div style={{marginTop:4,padding:"12px 14px",borderRadius:8,background:C.warnSoft,color:C.warn,fontSize:13,fontWeight:600}}>
          ⚠ {datos.disclaimer}
        </div>
      )}
    </div>
  );
}
