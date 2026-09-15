import { useEffect, useState } from "react";
import { API_BASE, fetchAuth } from "../../shared/hooks/fetchAuth";
import { Card } from "../../shared/components/atoms";
import { C } from "../../shared/utils/format";

// Dashboard multi-emisor (vigencia CSD + concentracion de facturas por
// emisor) - Perfil.jsx lo renderiza SOLO si emisores.length > 1 (chequeo
// explicito en el FRONTEND, no solo confiar en que el backend devuelva
// una lista corta - un negocio con 1 solo emisor no debe ver esta seccion
// aunque el endpoint la sirva igual). Sin libreria de graficas nueva: el
// proyecto no usa ninguna (confirmado por grep antes de escribir esto) -
// la barra horizontal es CSS puro, mismo criterio "sin dependencia
// injustificada" que csd_rfc.py documenta para el backend.
//
// CSD y e.firma se muestran como DOS FILAS SEPARADAS y explicitamente
// etiquetadas (hallazgo real del 15-sep: un usuario subio su e.firma en
// el formulario de CSD - con una sola fila de "vigencia" generica, esa
// confusion era invisible. Con las dos filas separadas, ambas fechas
// identicas quedan visibles de inmediato - ver alertaMismaFecha abajo,
// que ademas lo senala de forma explicita, no solo lo deja implicito en
// la coincidencia de los dos renglones).
const UMBRAL_ROJO_DIAS = 30;
const UMBRAL_NARANJA_DIAS = 90;

function tagVigencia(diasRestantes) {
  if (diasRestantes === null || diasRestantes === undefined) return null;
  if (diasRestantes < 0) return { texto: "Vencido", bg: C.dangerSoft, color: C.danger };
  if (diasRestantes < UMBRAL_ROJO_DIAS) return { texto: `${diasRestantes} días`, bg: C.dangerSoft, color: C.danger };
  if (diasRestantes < UMBRAL_NARANJA_DIAS) return { texto: `${diasRestantes} días`, bg: C.warnSoft, color: C.warn };
  return { texto: `${diasRestantes} días`, bg: C.accentSoft, color: C.accentBorder };
}

// Fila de vigencia (CSD o FIEL) - misma logica de tag por urgencia para
// ambas, solo cambia el texto de "sin registrar" y el color del tipo.
function FilaVigencia({ tipo, colorTipo, vigenciaHasta, diasRestantes, textoSinDato }) {
  const tag = tagVigencia(diasRestantes);
  return (
    <tr style={{ borderTop: `1px solid ${C.border}` }}>
      <td style={{ padding: "6px 8px 6px 0" }}>
        <span style={{ background: colorTipo.bg, color: colorTipo.color, fontSize: 10, fontWeight: 700, padding: "2px 8px", borderRadius: 20, whiteSpace: "nowrap" }}>
          {tipo}
        </span>
      </td>
      <td style={{ padding: "6px 0" }}>
        {vigenciaHasta ? (
          <>
            <span style={{ background: tag.bg, color: tag.color, fontSize: 11, fontWeight: 600, padding: "3px 10px", borderRadius: 20, whiteSpace: "nowrap" }}>
              {tag.texto}
            </span>
            <span style={{ fontSize: 11, color: C.textMuted, marginLeft: 8 }}>{vigenciaHasta}</span>
          </>
        ) : (
          <span style={{ fontSize: 12, color: C.textMuted }}>{textoSinDato}</span>
        )}
      </td>
    </tr>
  );
}

export default function EmisoresResumenDashboard({ negocioId }) {
  const [datos, setDatos] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!negocioId) { setLoading(false); return; }
    let cancelado = false;
    (async () => {
      setLoading(true); setError(null);
      try {
        const res = await fetchAuth(`${API_BASE}/admin/negocios/${negocioId}/emisores-resumen`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        if (!cancelado) setDatos(data);
      } catch (e) {
        if (!cancelado) setError(e.message);
      } finally {
        if (!cancelado) setLoading(false);
      }
    })();
    return () => { cancelado = true; };
  }, [negocioId]);

  if (loading) {
    return <Card><div style={{ fontSize: 13, color: C.textMuted, padding: "8px 0" }}>Cargando vigencia y concentración por emisor…</div></Card>;
  }
  if (error) {
    return <Card><div style={{ fontSize: 13, color: C.danger, padding: "8px 0" }}>No se pudo cargar el detalle por emisor: {error}</div></Card>;
  }
  if (!datos || datos.length === 0) return null;

  const maxFacturas = Math.max(1, ...datos.map((d) => d.facturas_mes ?? 0));

  return (
    <Card>
      <div style={{ fontSize: 13, fontWeight: 700, color: C.text, marginBottom: 10 }}>Vigencia de certificados por emisor</div>
      <div style={{ display: "grid", gap: 14 }}>
        {datos.map((e) => {
          const mismaVigencia = !!e.vigencia_csd_hasta && !!e.vigencia_efirma_hasta && e.vigencia_csd_hasta === e.vigencia_efirma_hasta;
          return (
            <div key={e.rfc} style={{ border: `1px solid ${C.border}`, borderRadius: 8, padding: "10px 12px" }}>
              <div style={{ color: C.text, fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{e.razon_social}</div>
              <div style={{ color: C.textMuted, fontFamily: "monospace", fontSize: 12, marginBottom: 4 }}>{e.rfc}</div>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
                <tbody>
                  <FilaVigencia
                    tipo="CSD" colorTipo={{ bg: C.infoSoft, color: C.info }}
                    vigenciaHasta={e.vigencia_csd_hasta} diasRestantes={e.dias_restantes}
                    textoSinDato="Sin CSD registrado"
                  />
                  <FilaVigencia
                    tipo="FIEL" colorTipo={{ bg: "#F3E8FF", color: "#7C3AED" }}
                    vigenciaHasta={e.vigencia_efirma_hasta} diasRestantes={e.dias_restantes_efirma}
                    textoSinDato="Sin e.firma registrada"
                  />
                </tbody>
              </table>
              {mismaVigencia && (
                <div style={{ marginTop: 8, padding: "6px 10px", borderRadius: 6, background: C.warnSoft, color: C.warn, fontSize: 11, fontWeight: 600 }}>
                  ⚠ El CSD y la e.firma tienen la MISMA fecha de vigencia — revisa que no se haya subido el archivo equivocado (son certificados distintos).
                </div>
              )}
            </div>
          );
        })}
      </div>

      <div style={{ fontSize: 13, fontWeight: 700, color: C.text, margin: "18px 0 10px" }}>Facturas de este mes por emisor</div>
      <div style={{ display: "grid", gap: 8 }}>
        {datos.map((e) => {
          const valor = e.facturas_mes;
          const sinDato = valor === null || valor === undefined;
          const pct = sinDato ? 0 : Math.round((valor / maxFacturas) * 100);
          return (
            <div key={e.rfc}>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, color: C.textSec, marginBottom: 3, gap: 8 }}>
                <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{e.razon_social}</span>
                <span style={{ fontWeight: 600, color: C.text, flexShrink: 0 }}>{sinDato ? "No disponible" : valor}</span>
              </div>
              <div style={{ background: C.surface, borderRadius: 6, height: 10, overflow: "hidden" }}>
                <div style={{ width: `${pct}%`, height: "100%", background: C.accent, borderRadius: 6, transition: "width .2s" }} />
              </div>
            </div>
          );
        })}
      </div>
    </Card>
  );
}
