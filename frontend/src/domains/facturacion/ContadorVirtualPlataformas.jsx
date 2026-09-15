import { useState } from "react";
import useEmisores from "../../shared/hooks/useEmisores";
import { useContadorVirtualISRPlataformas } from "./hooks";
import { Placeholder } from "../../shared/layout/AppShell";
import { SectionTitle, SectionSub, Card, KPIGrid, KPI, DetalleExpandible, FilaDetalle } from "../../shared/components/atoms";
import { C, fmt } from "../../shared/utils/format";

// Contador Virtual Fase 3 (zg1cYDU/zg645h8) - ISR/IVA retenido por
// Actividades Empresariales via Plataformas Tecnologicas (regimen 625,
// Art. 113-A LISR). NO acumulado (a diferencia de Fase 2/Art. 106) - cada
// mes se calcula aislado, retencion simple sobre el ingreso de ese mes.
//
// Alcance deliberadamente reducido a 3 categorias de actividad (confirmado
// con Pedro): "venta de bienes/prestacion de servicios" queda fuera porque
// su tasa de retencion no coincidio entre las fuentes consultadas - no se
// va a mostrar una tasa sin verificar contra una fuente oficial.
//
// Selector de actividad MANUAL, sin preseleccion (confirmado con Pedro) -
// el sistema no tiene forma de saber en que categoria cae cada factura del
// emisor, y adivinar mal produciria una tasa de retencion incorrecta.
const ACTIVIDADES = [
  { value: "transporte", label: "Transporte de pasajeros o entrega de bienes" },
  { value: "hospedaje", label: "Servicios de hospedaje" },
  { value: "contenido_digital", label: "Enajenación de bienes y prestación de servicios (contenido digital)" },
];

export default function ContadorVirtualPlataformas(){
  const {emisores,loading:loadingEmisores,error:errorEmisores,emisorActivoRfc} = useEmisores();
  const emisor = emisores.find(e=>e.rfc===emisorActivoRfc);
  const hoy = new Date();
  const [periodo,setPeriodo] = useState(`${hoy.getFullYear()}-${String(hoy.getMonth()+1).padStart(2,"0")}`);
  const [anio,mes] = periodo.split("-").map(Number);
  const [actividad,setActividad] = useState("");
  const {datos,loading,error} = useContadorVirtualISRPlataformas(emisor?.rfc, anio, mes, actividad || null);

  if (errorEmisores) return <Placeholder title="Cálculo de impuestos — Plataformas Tecnológicas" detail={`No se pudo conectar con administracion: ${errorEmisores}`}/>;
  if (loadingEmisores) return <Placeholder title="Cálculo de impuestos — Plataformas Tecnológicas" detail="Cargando datos reales…"/>;
  if (!emisor) return <Placeholder title="Cálculo de impuestos — Plataformas Tecnológicas" detail="Todavía no hay un emisor registrado."/>;

  return (
    <div>
      <SectionTitle>Cálculo de impuestos — Retención de ISR e IVA (Plataformas Tecnológicas)</SectionTitle>
      <SectionSub>Fase 3 de #40: régimen 625, retención mensual (Art. 113-A LISR) sobre ingresos ya facturados. Sin acumulación entre meses.</SectionSub>

      <div style={{marginBottom:12,padding:"12px 14px",borderRadius:8,background:C.warnSoft,color:C.warn,fontSize:13,fontWeight:600}}>
        ⚠ Este cálculo no evalúa si calificas para pago definitivo (Art. 113-B LISR, límite $300,000 anuales combinando plataformas + sueldos)
        — asume que ya estás en el esquema de pago provisional. El sistema no tiene acceso a tus ingresos por sueldos para hacer esa evaluación.
      </div>

      <Card style={{marginBottom:12}}>
        <label style={{fontSize:12,color:C.textSec,display:"block",marginBottom:6}}>Periodo</label>
        <input type="month" value={periodo} onChange={e=>setPeriodo(e.target.value)}
          style={{border:`1px solid ${C.border}`,borderRadius:8,padding:"8px 11px",fontSize:13,color:C.text,background:"#fff",marginBottom:14}}/>

        <label style={{fontSize:12,color:C.textSec,display:"block",marginBottom:6}}>Actividad (elige la que corresponde a tus ingresos de este periodo)</label>
        <select value={actividad} onChange={e=>setActividad(e.target.value)}
          style={{border:`1px solid ${C.border}`,borderRadius:8,padding:"8px 11px",fontSize:13,color:C.text,background:"#fff",width:"100%",maxWidth:420}}>
          <option value="">Selecciona una actividad…</option>
          {ACTIVIDADES.map(a=><option key={a.value} value={a.value}>{a.label}</option>)}
        </select>
      </Card>

      {!actividad && (
        <Card>
          <div style={{fontSize:13,color:C.textSec}}>Elige una actividad arriba para calcular la retención estimada del periodo.</div>
        </Card>
      )}

      {actividad && loading && <Placeholder title="Cálculo de impuestos" detail="Calculando…"/>}
      {actividad && !loading && error && <Placeholder title="Cálculo de impuestos" detail={`No se pudo conectar con facturacion: ${error}`}/>}

      {actividad && !loading && !error && datos && !datos.aplica && (
        <Card>
          <div style={{fontSize:14,fontWeight:600,color:C.text,marginBottom:6}}>No aplica para tu régimen fiscal</div>
          <div style={{fontSize:13,color:C.textSec}}>{datos.motivo_no_aplica}</div>
        </Card>
      )}

      {actividad && !loading && !error && datos && datos.aplica && (
        <>
          <KPIGrid>
            <KPI label="Ingresos del mes" value={fmt(datos.ingresos_mes)} dark/>
            <KPI label="ISR retenido este mes" value={fmt(datos.isr_retenido_mes)}/>
            <KPI label="IVA retenido este mes" value={fmt(datos.iva_retenido_mes)}/>
          </KPIGrid>

          <DetalleExpandible>
            <FilaDetalle etiqueta="Ingresos del mes" valor={fmt(datos.ingresos_mes)}/>
            <FilaDetalle etiqueta={`Tasa de ISR aplicada (${ACTIVIDADES.find(a=>a.value===datos.actividad)?.label ?? datos.actividad})`} valor={`${(datos.tasa_isr_aplicada*100).toFixed(2)}%`}/>
            <FilaDetalle etiqueta="ISR retenido = Ingresos del mes × tasa" valor={fmt(datos.isr_retenido_mes)} tipo="resultado"/>
            <FilaDetalle etiqueta="IVA retenido = Ingresos del mes × 8% (RFC en el CFDI)" valor={fmt(datos.iva_retenido_mes)} tipo="resultado"/>
          </DetalleExpandible>
        </>
      )}

      {actividad && !loading && !error && datos && (
        <div style={{marginTop:8,fontSize:12,color:C.textMuted}}>
          {datos.disclaimer}
        </div>
      )}
    </div>
  );
}
