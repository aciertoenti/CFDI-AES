import { useEffect, useRef, useState } from "react";
import { useToast } from "../../shared/layout/ToastProvider";
import { API_BASE, fetchAuth } from "../../shared/hooks/fetchAuth";
import { Btn, Card } from "../../shared/components/atoms";
import SelectorArchivo from "../../shared/components/SelectorArchivo";
import { C, detalleError } from "../../shared/utils/format";

// Declaraciones anuales - modal de documentos (Parte B, 22 sep 2026).
// SOLO sube/lista/descarga/borra PDFs por emisor y ejercicio - NO captura
// montos, NO parsea el PDF (esa es la Parte A, diseño de captura
// estructurada, sin implementar todavia - ver reporte 182).
//
// Accesibilidad (WCAG 2.2 AA, pedido explicito - los modales existentes
// del proyecto, EditarEmisorModal/EliminarEmisorConfirm/ReemplazarCsdForm,
// NO implementan foco atrapado/Esc/aria-modal, asi que esto es NUEVO en
// el repo, no una copia de un patron ya probado): foco atrapado dentro
// del dialog, Escape cierra, el foco vuelve al boton que abrio el modal
// al cerrar, role="dialog" + aria-modal, aria-live en errores.
//
// Guardia de cambios sin guardar (corregido 22 sep 2026 - problema real
// encontrado en prueba manual: clic fuera del modal lo cerraba sin aviso
// y se perdia lo capturado): las 4 vias de cierre (fondo/Esc/X/Cancelar)
// pasan por solicitarCierre(), que intercepta con una confirmacion
// DENTRO del modal (role="alertdialog", nunca window.confirm) si el
// formulario esta "sucio" (algun campo distinto de FORM_INICIAL, o un
// archivo seleccionado). Ver seguirEditando()/descartar() abajo.

// Mismo limite que declaraciones_storage.EJERCICIO_MINIMO (backend) -
// duplicado a proposito (no hay endpoint dedicado solo para exponer este
// rango, evita una llamada de red extra para un dato estatico que rara
// vez cambia). Si el backend cambia este valor, actualizar aqui tambien.
// CORREGIDO 22 sep 2026 (reporte 185/C2): existen acuses reales del
// titular desde 2013 - 2014 los rechazaba. 2000 da margen amplio, mismo
// valor y mismo motivo que el backend.
const EJERCICIO_MINIMO = 2000;
const EJERCICIO_MAXIMO = new Date().getFullYear() - 1;
const AÑOS_VALIDOS = Array.from(
  { length: EJERCICIO_MAXIMO - EJERCICIO_MINIMO + 1 },
  (_, i) => EJERCICIO_MAXIMO - i,
);

const MAX_MB = 5; // mismo default que MAX_DECLARACION_PDF_BYTES del backend

const TIPOS_DOCUMENTO = [
  { value: "declaracion", label: "Declaración" },
  { value: "acuse", label: "Acuse" },
  { value: "comprobante_pago", label: "Comprobante de pago" },
];

// Extraido a constante (antes vivia inline, duplicado entre el useState
// inicial y el reset post-exito) - reutilizado tambien por el chequeo de
// "sucio" (M1) y por descartar() al confirmar Cancelar.
const FORM_INICIAL = {
  ejercicio: EJERCICIO_MAXIMO,
  tipo_declaracion: "normal",
  numero_complementaria: "",
  tipo_documento: "declaracion",
  archivo: null,
};

const inputStyle = {
  width: "100%", border: `1px solid ${C.border}`, borderRadius: 8,
  padding: "8px 11px", fontSize: 13, color: C.text, background: "#fff",
  boxSizing: "border-box",
};
const labelStyle = { fontSize: 12, color: C.textSec, display: "block", marginBottom: 3 };

function formatoBytes(n) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

function formatoFecha(iso) {
  try {
    return new Date(iso).toLocaleDateString("es-MX", { year: "numeric", month: "short", day: "numeric" });
  } catch {
    return iso;
  }
}

export default function DeclaracionesAnualesModal({ emisor, onCerrar }) {
  const toast = useToast();
  const overlayRef = useRef(null);
  const primerCampoRef = useRef(null);
  const elementoQueAbrioRef = useRef(null);
  // M1: id (no el nodo DOM - el formulario se remonta al volver de la
  // confirmacion) del campo que tenia el foco cuando se disparo la
  // confirmacion, para devolver el foco ahi en "Seguir editando".
  const idCampoEnfocadoRef = useRef(null);
  // M1: cual de las 4 vias de cierre disparo la confirmacion -
  // "cerrar" (fondo/Esc/X, cierra TODO el modal) vs "cancelar" (el
  // boton Cancelar del formulario, solo vuelve a la lista). Descartar()
  // se comporta distinto segun cual fue.
  const accionPendienteRef = useRef(null);

  const [documentos, setDocumentos] = useState(null); // null = cargando
  const [errorLista, setErrorLista] = useState(null);
  const [mostrandoForm, setMostrandoForm] = useState(false);
  const [mostrandoConfirmacion, setMostrandoConfirmacion] = useState(false);

  const [form, setForm] = useState({ ...FORM_INICIAL });
  const [subiendo, setSubiendo] = useState(false);
  const [errorForm, setErrorForm] = useState(null);
  const [errorEsDuplicado, setErrorEsDuplicado] = useState(false);

  // M1: "sucio" solo tiene sentido mientras el formulario esta abierto -
  // en la vista de lista no hay nada que se pueda perder al cerrar.
  const estaSucio = mostrandoForm && (
    form.ejercicio !== FORM_INICIAL.ejercicio ||
    form.tipo_declaracion !== FORM_INICIAL.tipo_declaracion ||
    form.numero_complementaria !== FORM_INICIAL.numero_complementaria ||
    form.tipo_documento !== FORM_INICIAL.tipo_documento ||
    form.archivo !== null
  );

  // ─── Carga inicial ──────────────────────────────────────────────────────
  const cargar = async () => {
    setErrorLista(null);
    try {
      const res = await fetchAuth(`${API_BASE}/admin/emisores/${emisor.id}/declaraciones-anuales/documentos`);
      const data = await res.json().catch(() => ([]));
      if (!res.ok) throw new Error(detalleError(data, res));
      setDocumentos(data);
    } catch (e) {
      setErrorLista(e.message);
    }
  };
  useEffect(() => { cargar(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, []);

  // ─── M1: cierre con guardia de cambios sin guardar ─────────────────────
  // Punto UNICO de entrada para las 4 vias de cierre (fondo/Esc/X/Cancelar).
  // Durante una subida, cerrar queda deshabilitado por completo (pedido
  // explicito: "no debe quedar una subida huerfana sin retroalimentacion") -
  // ni siquiera abre la confirmacion, simplemente no hace nada (el boton X
  // y Cancelar ademas quedan visualmente disabled, ver JSX).
  const solicitarCierre = (accion) => {
    if (subiendo) return;
    if (estaSucio) {
      idCampoEnfocadoRef.current = document.activeElement?.id || null;
      accionPendienteRef.current = accion;
      setMostrandoConfirmacion(true);
      return;
    }
    if (accion === "cancelar") {
      setMostrandoForm(false);
      setErrorForm(null);
    } else {
      onCerrar();
    }
  };

  const seguirEditando = () => setMostrandoConfirmacion(false);

  const descartar = () => {
    setMostrandoConfirmacion(false);
    if (accionPendienteRef.current === "cancelar") {
      setForm({ ...FORM_INICIAL });
      setMostrandoForm(false);
      setErrorForm(null);
    } else {
      onCerrar();
    }
  };

  // Devuelve el foco al campo donde estaba (por id, no por referencia al
  // nodo DOM - el formulario se remonta al pasar de confirmacion a form).
  useEffect(() => {
    if (!mostrandoConfirmacion && mostrandoForm && idCampoEnfocadoRef.current) {
      document.getElementById(idCampoEnfocadoRef.current)?.focus();
      idCampoEnfocadoRef.current = null;
    }
  }, [mostrandoConfirmacion, mostrandoForm]);

  // Foco por defecto en "Seguir editando" al abrir la confirmacion
  // (pedido explicito).
  useEffect(() => {
    if (mostrandoConfirmacion) {
      document.getElementById("da-confirmar-seguir-editando")?.focus();
    }
  }, [mostrandoConfirmacion]);

  // ─── Accesibilidad: captura de apertura + foco inicial + retorno ───────
  // Efecto de MONTAJE/DESMONTAJE unico, deps vacios a proposito - debe
  // correr solo una vez (al abrir/cerrar el modal completo), nunca en
  // cada cambio de mostrandoConfirmacion/subiendo/estaSucio (eso viviria
  // en el efecto de abajo) - si no, "el elemento que abrio esto" se
  // sobreescribiria con cualquier cosa que tuviera el foco en ese
  // momento, y el foco inicial se robaria cada vez que cambia el estado.
  useEffect(() => {
    elementoQueAbrioRef.current = document.activeElement;
    primerCampoRef.current?.focus();
    return () => {
      // Foco de vuelta al boton "Declaraciones anuales" que abrio esto.
      elementoQueAbrioRef.current?.focus?.();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ─── Accesibilidad: foco atrapado + Esc ────────────────────────────────
  // Efecto SEPARADO del de arriba - este SI debe re-registrarse cuando
  // cambian mostrandoConfirmacion/subiendo/estaSucio, para que el
  // handler de Esc siempre decida con el valor fresco (evita duplicar
  // estado en un ref-mirror solo para esto).
  useEffect(() => {
    const onKeyDown = (e) => {
      if (e.key === "Escape") {
        e.preventDefault();
        // Esc dentro de la confirmacion equivale a "Seguir editando"
        // (pedido explicito) - NO cierra nada.
        if (mostrandoConfirmacion) { seguirEditando(); return; }
        solicitarCierre("cerrar");
        return;
      }
      if (e.key !== "Tab" || !overlayRef.current) return;
      const focusables = overlayRef.current.querySelectorAll(
        'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
      );
      if (focusables.length === 0) return;
      const primero = focusables[0];
      const ultimo = focusables[focusables.length - 1];
      if (e.shiftKey && document.activeElement === primero) {
        e.preventDefault();
        ultimo.focus();
      } else if (!e.shiftKey && document.activeElement === ultimo) {
        e.preventDefault();
        primero.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mostrandoConfirmacion, subiendo, estaSucio]);

  // ─── Subir ──────────────────────────────────────────────────────────────
  const validarArchivoCliente = (archivo) => {
    if (!archivo) return "Selecciona un archivo";
    if (archivo.type !== "application/pdf" && !archivo.name.toLowerCase().endsWith(".pdf")) {
      return "Solo se aceptan archivos PDF";
    }
    if (archivo.size > MAX_MB * 1024 * 1024) return `El archivo no debe exceder ${MAX_MB}MB`;
    return null;
  };

  const submit = async (e) => {
    e.preventDefault();
    setErrorForm(null);
    setErrorEsDuplicado(false);

    const errorArchivo = validarArchivoCliente(form.archivo);
    if (errorArchivo) { setErrorForm(errorArchivo); return; }
    if (form.tipo_declaracion === "complementaria" && (!form.numero_complementaria || Number(form.numero_complementaria) < 1)) {
      setErrorForm("Indica el número de complementaria (1 o mayor)");
      return;
    }

    setSubiendo(true);
    try {
      const body = new FormData();
      body.append("ejercicio", String(form.ejercicio));
      body.append("tipo_declaracion", form.tipo_declaracion);
      if (form.tipo_declaracion === "complementaria") {
        body.append("numero_complementaria", String(form.numero_complementaria));
      }
      body.append("tipo_documento", form.tipo_documento);
      body.append("archivo", form.archivo);

      const res = await fetchAuth(`${API_BASE}/admin/emisores/${emisor.id}/declaraciones-anuales/documentos`, {
        method: "POST",
        body, // fetchAuth NO debe forzar Content-Type json aqui - FormData fija su propio boundary
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        if (res.status === 409) {
          setErrorEsDuplicado(true);
          setErrorForm("Este archivo ya estaba guardado");
        } else {
          throw new Error(detalleError(data, res));
        }
        return;
      }
      toast(`Declaración ${form.ejercicio} guardada`, "success");
      setMostrandoForm(false);
      // Tras guardar con exito, el formulario deja de estar "sucio" -
      // vuelve exactamente a FORM_INICIAL (pedido explicito).
      setForm({ ...FORM_INICIAL });
      cargar();
    } catch (e) {
      // Conserva los datos del formulario (pedido explicito) - no se
      // limpia `form` en el catch, solo se muestra el error.
      setErrorForm(e.message);
    } finally {
      setSubiendo(false);
    }
  };

  const descargar = async (doc) => {
    try {
      const res = await fetchAuth(`${API_BASE}/admin/emisores/${emisor.id}/declaraciones-anuales/documentos/${doc.id}/descarga`);
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(detalleError(data, res));
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = doc.nombre_archivo_original || "declaracion.pdf";
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      toast(`No se pudo descargar: ${e.message}`, "error");
    }
  };

  const borrar = async (doc) => {
    if (!window.confirm(`¿Borrar "${doc.nombre_archivo_original}"? Esta acción no se puede deshacer.`)) return;
    try {
      const res = await fetchAuth(`${API_BASE}/admin/emisores/${emisor.id}/declaraciones-anuales/documentos/${doc.id}`, { method: "DELETE" });
      if (!res.ok && res.status !== 204) {
        const data = await res.json().catch(() => ({}));
        throw new Error(detalleError(data, res));
      }
      toast("Documento eliminado", "success");
      cargar();
    } catch (e) {
      toast(`No se pudo borrar: ${e.message}`, "error");
    }
  };

  // Agrupado por ejercicio, mas reciente primero (la API ya devuelve el
  // orden correcto - aqui solo se arma la estructura de grupos).
  const grupos = [];
  if (documentos) {
    for (const doc of documentos) {
      let grupo = grupos.find(g => g.ejercicio === doc.ejercicio);
      if (!grupo) { grupo = { ejercicio: doc.ejercicio, docs: [] }; grupos.push(grupo); }
      grupo.docs.push(doc);
    }
  }

  return (
    <div
      ref={overlayRef}
      role="dialog"
      aria-modal="true"
      aria-labelledby="declaraciones-modal-titulo"
      style={{
        position: "fixed", inset: 0, background: "rgba(3,6,18,.5)",
        display: "flex", alignItems: "center", justifyContent: "center",
        zIndex: 120, padding: 12, boxSizing: "border-box",
      }}
      onClick={(e) => { if (e.target === overlayRef.current) solicitarCierre("cerrar"); }}
    >
      <Card
        style={{
          width: 480, maxWidth: "calc(100vw - 24px)", maxHeight: "calc(100dvh - 24px)",
          display: "flex", flexDirection: "column", overflow: "hidden", padding: 0,
        }}
      >
        <div style={{ padding: "16px 20px 12px", borderBottom: `1px solid ${C.border}`, display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexShrink: 0 }}>
          <div>
            <div id="declaraciones-modal-titulo" style={{ fontSize: 16, fontWeight: 700, color: C.text }}>Declaraciones anuales</div>
            <div style={{ fontSize: 12, color: C.textMuted, fontFamily: "monospace", marginTop: 2 }}>{emisor.rfc}</div>
          </div>
          <button
            ref={!mostrandoForm ? primerCampoRef : undefined}
            type="button"
            aria-label="Cerrar"
            disabled={subiendo}
            onClick={() => solicitarCierre("cerrar")}
            style={{ background: "none", border: "none", fontSize: 20, lineHeight: 1, color: C.textMuted, cursor: subiendo ? "not-allowed" : "pointer", opacity: subiendo ? .5 : 1, padding: 4, minWidth: 44, minHeight: 44 }}
          >
            ×
          </button>
        </div>

        <div style={{ flex: 1, overflowY: "auto", padding: "14px 20px" }}>
          {mostrandoConfirmacion ? (
            // M1: confirmacion DENTRO del modal (nunca window.confirm) -
            // role="alertdialog" (mas preciso que aria-live para un
            // dialogo que pide una decision, se anuncia automaticamente
            // al recibir el foco). Reemplaza al formulario en vez de
            // superponerse - reutiliza el MISMO foco-atrapado de arriba
            // sin cambios, porque los campos del formulario simplemente
            // no estan en el DOM mientras esto se muestra.
            <div role="alertdialog" aria-modal="true" aria-labelledby="da-confirmar-titulo" aria-describedby="da-confirmar-texto">
              <div id="da-confirmar-titulo" style={{ fontSize: 15, fontWeight: 700, color: C.text, marginBottom: 8 }}>
                Tienes cambios sin guardar
              </div>
              <div id="da-confirmar-texto" style={{ fontSize: 13, color: C.textSec, marginBottom: 18 }}>
                ¿Descartarlos?
              </div>
              <div style={{ display: "flex", gap: 8 }}>
                {/* boton nativo, no <Btn> - Btn no reenvia id/ref al
                    <button> real, y este necesita id para el foco por
                    defecto (ver useEffect de arriba) */}
                <button
                  id="da-confirmar-seguir-editando"
                  type="button"
                  onClick={seguirEditando}
                  style={{ flex: 1, minHeight: 44, borderRadius: 8, padding: "10px 18px", fontSize: 13, fontWeight: 600, cursor: "pointer", border: "none", background: C.primary, color: C.accent }}
                >
                  Seguir editando
                </button>
                <Btn type="button" variant="secondary" style={{ minHeight: 44, color: C.danger, borderColor: C.danger }} onClick={descartar}>
                  Descartar
                </Btn>
              </div>
            </div>
          ) : !mostrandoForm ? (
            <>
              <Btn type="button" style={{ width: "100%", marginBottom: 14, minHeight: 44 }} onClick={() => setMostrandoForm(true)}>
                + Subir declaración
              </Btn>

              {documentos === null && !errorLista && (
                <div style={{ fontSize: 13, color: C.textMuted, textAlign: "center", padding: "20px 0" }}>Cargando…</div>
              )}
              {errorLista && (
                <div role="alert" aria-live="assertive" style={{ fontSize: 12, color: C.danger, background: C.dangerSoft, borderRadius: 6, padding: "8px 10px", marginBottom: 10 }}>
                  ⚠ No se pudo cargar: {errorLista}
                </div>
              )}
              {documentos !== null && documentos.length === 0 && !errorLista && (
                <div style={{ fontSize: 13, color: C.textMuted, textAlign: "center", padding: "20px 0" }}>
                  Aún no has subido declaraciones.
                </div>
              )}
              {grupos.map(grupo => (
                <div key={grupo.ejercicio} style={{ marginBottom: 14 }}>
                  <div style={{ fontSize: 12, fontWeight: 700, color: C.textSec, marginBottom: 6, textTransform: "uppercase", letterSpacing: ".04em" }}>
                    Ejercicio {grupo.ejercicio}
                  </div>
                  {grupo.docs.map(doc => (
                    <div key={doc.id} style={{ border: `1px solid ${C.border}`, borderRadius: 8, padding: "8px 10px", marginBottom: 6 }}>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 8 }}>
                        <div style={{ minWidth: 0 }}>
                          <div style={{ fontSize: 13, color: C.text, fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                            {doc.nombre_archivo_original}
                          </div>
                          <div style={{ fontSize: 11, color: C.textMuted, marginTop: 2 }}>
                            {TIPOS_DOCUMENTO.find(t => t.value === doc.tipo_documento)?.label || doc.tipo_documento}
                            {" · "}
                            {doc.tipo_declaracion === "complementaria" ? `Complementaria ${doc.numero_complementaria}` : "Normal"}
                            {" · "}{formatoBytes(doc.tamano_bytes)}{" · "}{formatoFecha(doc.creado_en)}
                          </div>
                        </div>
                      </div>
                      <div style={{ display: "flex", gap: 6, marginTop: 8 }}>
                        <Btn type="button" variant="secondary" style={{ flex: 1, fontSize: 12, padding: "6px 10px", minHeight: 44 }} onClick={() => descargar(doc)}>
                          Descargar
                        </Btn>
                        <Btn type="button" variant="secondary" style={{ flex: 1, fontSize: 12, padding: "6px 10px", minHeight: 44, color: C.danger, borderColor: C.danger }} onClick={() => borrar(doc)}>
                          Borrar
                        </Btn>
                      </div>
                    </div>
                  ))}
                </div>
              ))}
            </>
          ) : (
            <form onSubmit={submit}>
              <div style={{ marginBottom: 12 }}>
                <label htmlFor="da-ejercicio" style={labelStyle}>Ejercicio</label>
                <select
                  id="da-ejercicio"
                  ref={primerCampoRef}
                  value={form.ejercicio}
                  onChange={e => setForm({ ...form, ejercicio: Number(e.target.value) })}
                  style={inputStyle}
                >
                  {AÑOS_VALIDOS.map(a => <option key={a} value={a}>{a}</option>)}
                </select>
              </div>

              <div style={{ marginBottom: 12 }}>
                <label htmlFor="da-tipo-decl" style={labelStyle}>Tipo de declaración</label>
                <select
                  id="da-tipo-decl"
                  value={form.tipo_declaracion}
                  onChange={e => setForm({ ...form, tipo_declaracion: e.target.value, numero_complementaria: "" })}
                  style={inputStyle}
                >
                  <option value="normal">Normal</option>
                  <option value="complementaria">Complementaria</option>
                </select>
              </div>

              {form.tipo_declaracion === "complementaria" && (
                <div style={{ marginBottom: 12 }}>
                  {/* Sin tope superior (corregido 22 sep 2026, reporte
                      185/C3) - el limite general de Art. 32 CFF (3
                      modificaciones) tiene excepciones reales, un
                      <select> fijo 1-3 las bloqueaba. Input numerico
                      libre, min=1, sin max. */}
                  <label htmlFor="da-numero-comp" style={labelStyle}>Número de complementaria</label>
                  <input
                    id="da-numero-comp"
                    type="number"
                    min="1"
                    step="1"
                    value={form.numero_complementaria}
                    onChange={e => setForm({ ...form, numero_complementaria: e.target.value })}
                    placeholder="Ej. 1"
                    style={inputStyle}
                  />
                </div>
              )}

              <div style={{ marginBottom: 12 }}>
                <label htmlFor="da-tipo-doc" style={labelStyle}>Tipo de documento</label>
                <select
                  id="da-tipo-doc"
                  value={form.tipo_documento}
                  onChange={e => setForm({ ...form, tipo_documento: e.target.value })}
                  style={inputStyle}
                >
                  {TIPOS_DOCUMENTO.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
                </select>
              </div>

              <div style={{ marginBottom: 14 }}>
                <SelectorArchivo
                  id="da-archivo"
                  label={`Archivo PDF (máx. ${MAX_MB}MB)`}
                  accept="application/pdf,.pdf"
                  archivo={form.archivo}
                  onChange={archivo => setForm({ ...form, archivo })}
                  textoBoton="Seleccionar PDF"
                />
              </div>

              {errorForm && (
                <div role="alert" aria-live="assertive" style={{ fontSize: 12, color: errorEsDuplicado ? C.warn : C.danger, background: errorEsDuplicado ? C.warnSoft : C.dangerSoft, borderRadius: 6, padding: "8px 10px", marginBottom: 12 }}>
                  ⚠ {errorForm}
                </div>
              )}

              <div style={{ display: "flex", gap: 8 }}>
                <Btn disabled={subiendo} style={{ flex: 1, minHeight: 44 }}>{subiendo ? "Subiendo…" : "Guardar"}</Btn>
                <Btn type="button" variant="secondary" style={{ minHeight: 44 }} disabled={subiendo} onClick={() => solicitarCierre("cancelar")}>
                  Cancelar
                </Btn>
              </div>
            </form>
          )}
        </div>
      </Card>
    </div>
  );
}
