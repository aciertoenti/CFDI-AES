import { useState } from "react";
import useEmisores from "../../shared/hooks/useEmisores";
import { useContadorVirtualISRActEmpresarial } from "./hooks";
import { Placeholder } from "../../shared/layout/AppShell";
import { SectionTitle, SectionSub, Card, KPIGrid, KPI, DetalleExpandible, FilaDetalle } from "../../shared/components/atoms";
import { C, fmt } from "../../shared/utils/format";

// Contador Virtual Fase 2 (zg1cYDU) - ISR Art. 106 (Actividad Empresarial
// y Profesional, regimen 612), acumulado desde enero + IVA simple del mes.
// NO reutiliza ContadorVirtual.jsx (Fase 1, RESICO) - mecanica de calculo
// distinta (tarifa progresiva acumulada vs tasa unica sobre el mes).
//
// Advertencia de gastos en $0 SIEMPRE visible (no en tooltip, decision de
// Pedro) - el ISR mostrado sobre-estima el real hasta que exista CFDI
// recibidos (zg55DWY/zg6P6HE).
export default function ContadorVirtualActEmpresarial(){
  const {emisores,loading:loadingEmisores,error:errorEmisores,emisorActivoRfc} = useEmisores();
  const emisor = emisores.find(e=>e.rfc===emisorActivoRfc);
  const hoy = new Date();
  const [periodo,setPeriodo] = useState(`${hoy.getFullYear()}-${String(hoy.getMonth()+1).padStart(2,"0")}`);
  const [anio,mes] = periodo.split("-").map(Number);
  const {datos,loading,error} = useContadorVirtualISRActEmpresarial(emisor?.rfc, anio, mes);

  if (errorEmisores) return <Placeholder title="Cálculo de impuestos — Actividad Empresarial" detail={`No se pudo conectar con administracion: ${errorEmisores}`}/>;
  if (loadingEmisores) return <Placeholder title="Cálculo de impuestos — Actividad Empresarial" detail="Cargando datos reales…"/>;
  if (!emisor) return <Placeholder title="Cálculo de impuestos — Actividad Empresarial" detail="Todavía no hay un emisor registrado."/>;

  return (
    <div>
      <SectionTitle>Cálculo de impuestos — ISR provisional (Actividad Empresarial y Profesional)</SectionTitle>
      <SectionSub>Fase 2 de #40: régimen 612, ISR acumulado desde enero (Art. 106 LISR) + IVA del mes. Solo ingresos ya facturados.</SectionSub>

      <Card style={{marginBottom:12,borderColor:C.warn,background:C.warnSoft}}>
        <div style={{fontSize:13,color:C.warn,fontWeight:600}}>
          ⚠ Gastos deducibles: $0.00 — pendiente conectar CFDI recibidos
        </div>
        <div style={{fontSize:12,color:C.textSec,marginTop:4}}>
          Esto NO significa que tu negocio no tuvo gastos reales — el sistema todavía no descuenta ningún gasto porque
          la conexión con CFDI recibidos (facturas que te emiten tus proveedores) sigue sin construirse. El ISR de abajo
          está <strong>sobre-estimado</strong> respecto al real hasta que eso exista.
        </div>
      </Card>

      <Card style={{marginBottom:12}}>
        <label style={{fontSize:12,color:C.textSec,display:"block",marginBottom:6}}>Periodo</label>
        <input type="month" value={periodo} onChange={e=>setPeriodo(e.target.value)}
          style={{border:`1px solid ${C.border}`,borderRadius:8,padding:"8px 11px",fontSize:13,color:C.text,background:"#fff"}}/>
      </Card>

      {loading && <Placeholder title="Cálculo de impuestos" detail="Calculando…"/>}
      {!loading && error && <Placeholder title="Cálculo de impuestos" detail={`No se pudo conectar con facturacion: ${error}`}/>}

      {!loading && !error && datos && !datos.aplica && (
        <Card>
          <div style={{fontSize:14,fontWeight:600,color:C.text,marginBottom:6}}>No aplica para tu régimen fiscal</div>
          <div style={{fontSize:13,color:C.textSec}}>{datos.motivo_no_aplica}</div>
        </Card>
      )}

      {!loading && !error && datos && datos.aplica && (
        <>
          <KPIGrid>
            <KPI label="Ingresos del mes" value={fmt(datos.ingresos_mes)} dark/>
            <KPI label="ISR a pagar este mes" value={fmt(datos.isr_a_pagar_mes)}/>
            <KPI label="IVA a pagar este mes" value={fmt(datos.iva_a_pagar_mes)}/>
          </KPIGrid>

          <DetalleExpandible>
            <FilaDetalle etiqueta="Ingresos del mes" valor={fmt(datos.ingresos_mes)}/>
            <FilaDetalle etiqueta="Gastos del mes" valor={`${fmt(datos.gastos_mes)} — pendiente CFDI recibidos`}/>
            <FilaDetalle etiqueta="Base gravable acumulada (ene–este mes)" valor={fmt(datos.base_gravable_acumulada)} tipo="resultado"/>
            <FilaDetalle etiqueta="ISR acumulado del ejercicio (tarifa Art. 96/106 escalada)" valor={fmt(datos.isr_acumulado)} tipo="resultado"/>
            <FilaDetalle etiqueta="(−) ISR ya pagado en meses anteriores" valor={fmt(datos.isr_pagado_meses_anteriores)}/>
            <FilaDetalle etiqueta="ISR a pagar este mes" valor={fmt(datos.isr_a_pagar_mes)} tipo="resultado"/>
            <FilaDetalle etiqueta="IVA a pagar este mes = Ingresos del mes × 16%" valor={fmt(datos.iva_a_pagar_mes)} tipo="resultado"/>
          </DetalleExpandible>
        </>
      )}

      {!loading && !error && datos && (
        <div style={{marginTop:4,padding:"12px 14px",borderRadius:8,background:C.warnSoft,color:C.warn,fontSize:13,fontWeight:600}}>
          ⚠ {datos.advertencia}
        </div>
      )}
      {!loading && !error && datos && (
        <div style={{marginTop:8,fontSize:12,color:C.textMuted}}>
          {datos.disclaimer}
        </div>
      )}
    </div>
  );
}
