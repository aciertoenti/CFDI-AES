import { useRef } from "react";
import { C } from "../utils/format";

// Selector de archivo accesible y en español (22 sep 2026, corrección de
// DeclaracionesAnualesModal.jsx). El <input type="file"> nativo muestra
// texto del NAVEGADOR ("Choose File"/"No file chosen" en Chrome en
// ingles, u otra variante segun el navegador/idioma del SO) - ese texto
// no es controlable por CSS/HTML, la unica forma real de tenerlo en
// español es ocultar el input nativo y construir la UI a mano.
//
// Reutilizable a proposito: el mismo problema (texto nativo del
// navegador, sin texto en español) ya existe en otros 4 inputs de
// archivo del proyecto (AltaEmisorForm.jsx x2 - .cer/.key,
// ReemplazarCsdForm.jsx x2 - .cer/.key, ConfiguracionMarca.jsx x1 -
// logo) - NINGUNO de esos 4 se toco en este cambio (fuera de alcance de
// esta tarea, que es solo DeclaracionesAnualesModal.jsx), pero este
// componente queda listo para que una tarea futura los migre sin
// duplicar la logica.
//
// El input nativo NO se oculta con display:none (eso lo saca del arbol
// de accesibilidad, un lector de pantalla dejaria de anunciarlo) - se
// oculta VISUALMENTE con la tecnica estandar "clip" (position:absolute,
// 1x1px, overflow:hidden, clip:rect(0,0,0,0)) - sigue siendo enfocable
// y anunciable, solo invisible en pantalla. El boton visible dispara
// el selector nativo programaticamente (inputRef.current.click()) - un
// <button> real es focuseable y operable con Enter/Espacio por
// comportamiento nativo del navegador, sin necesitar manejar teclas a mano.
const ocultoVisualmente = {
  position: "absolute", width: 1, height: 1, padding: 0, margin: -1,
  overflow: "hidden", clip: "rect(0,0,0,0)", whiteSpace: "nowrap", border: 0,
};

export default function SelectorArchivo({
  id,
  label,
  accept,
  archivo,
  onChange,
  textoBoton = "Seleccionar archivo",
  textoVacio = "Ningún archivo seleccionado",
}) {
  const inputRef = useRef(null);
  const labelId = `${id}-label`;

  return (
    <div>
      <label id={labelId} htmlFor={id} style={{ fontSize: 12, color: C.textSec, display: "block", marginBottom: 3 }}>
        {label}
      </label>
      <input
        ref={inputRef}
        id={id}
        type="file"
        accept={accept}
        aria-labelledby={labelId}
        onChange={e => onChange(e.target.files?.[0] || null)}
        style={ocultoVisualmente}
      />
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        {/* boton nativo, no <Btn> - Btn (shared/components/atoms.jsx) no
            reenvia `id` al <button> real (solo desestructura variant/
            onClick/style/disabled/type). Este necesita un id ESTABLE
            para que el modal que lo use pueda restaurar el foco aqui
            despues de "Seguir editando" (guardia de cambios sin
            guardar) - por eso se recrea el estilo del variant
            "secondary" a mano en vez de importar Btn. */}
        <button
          type="button"
          id={`${id}-boton`}
          onClick={() => inputRef.current?.click()}
          style={{
            minHeight: 44, minWidth: 44, flexShrink: 0, borderRadius: 8,
            padding: "10px 18px", fontSize: 13, fontWeight: 600, cursor: "pointer",
            background: "transparent", color: C.textSec, border: `1px solid ${C.border}`,
          }}
        >
          {textoBoton}
        </button>
        <span
          style={{
            fontSize: 13, color: archivo ? C.text : C.textMuted, minWidth: 0,
            overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
          }}
          title={archivo ? archivo.name : undefined}
        >
          {archivo ? archivo.name : textoVacio}
        </span>
      </div>
    </div>
  );
}
