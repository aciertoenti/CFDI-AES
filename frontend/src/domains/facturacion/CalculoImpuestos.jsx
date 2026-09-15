import useEmisores from "../../shared/hooks/useEmisores";
import ContadorVirtual from "./ContadorVirtual";
import ContadorVirtualActEmpresarial from "./ContadorVirtualActEmpresarial";
import ContadorVirtualPlataformas from "./ContadorVirtualPlataformas";
import { Placeholder } from "../../shared/layout/AppShell";
import { SectionTitle, SectionSub } from "../../shared/components/atoms";

// Punto de entrada UNICO de "Cálculo de Impuestos" (zg1cYDU) - enruta
// internamente al motor correcto segun el regimen fiscal del emisor
// activo, sin que el usuario tenga que saber ni elegir nada.
//
// Origen: antes habia 2 items de sidebar separados (uno por Fase/motor)
// que el usuario elegia a mano - eso fue la causa real de una confusion
// reportada (Pedro entro al motor RESICO, que nunca calcula IVA por
// diseno, y penso que el calculo de IVA de Actividad Empresarial estaba
// roto - no lo estaba, era la pantalla equivocada). Este componente
// elimina esa eleccion manual por completo.
//
// Regimenes soportados hoy: 626 (RESICO PF, Fase 1), 612 (Actividad
// Empresarial y Profesional, Fase 2) y 625 (Plataformas Tecnologicas,
// Fase 3). Cualquier otro regimen -> mensaje honesto, nunca una pantalla
// en blanco ni un error generico.
const REGIMEN_RESICO = "626";
const REGIMEN_ACTIVIDAD_EMPRESARIAL = "612";
const REGIMEN_PLATAFORMAS = "625";

export default function CalculoImpuestos(){
  const {emisores,loading,error,emisorActivoRfc} = useEmisores();
  const emisor = emisores.find(e=>e.rfc===emisorActivoRfc);

  if (error) return <Placeholder title="Cálculo de impuestos" detail={`No se pudo conectar con administracion: ${error}`}/>;
  if (loading) return <Placeholder title="Cálculo de impuestos" detail="Cargando datos reales…"/>;
  if (!emisor) return <Placeholder title="Cálculo de impuestos" detail="Todavía no hay un emisor registrado."/>;

  if (emisor.regimen_fiscal === REGIMEN_RESICO) return <ContadorVirtual/>;
  if (emisor.regimen_fiscal === REGIMEN_ACTIVIDAD_EMPRESARIAL) return <ContadorVirtualActEmpresarial/>;
  if (emisor.regimen_fiscal === REGIMEN_PLATAFORMAS) return <ContadorVirtualPlataformas/>;

  return (
    <div>
      <SectionTitle>Cálculo de impuestos</SectionTitle>
      <SectionSub>
        El cálculo automático para tu régimen fiscal ({emisor.regimen_fiscal}) todavía no está disponible.
        Hoy cubrimos RESICO Personas Físicas ({REGIMEN_RESICO}), Actividad Empresarial y Profesional ({REGIMEN_ACTIVIDAD_EMPRESARIAL})
        y Actividades Empresariales via Plataformas Tecnológicas ({REGIMEN_PLATAFORMAS}).
      </SectionSub>
    </div>
  );
}
