import { useState, useEffect } from "react";
import { useToast } from "../../shared/layout/ToastProvider";
import useEmisores from "../../shared/hooks/useEmisores";
import useClientes from "../../shared/hooks/useClientes";
import { API_BASE, fetchAuth } from "../../shared/hooks/fetchAuth";
import { useNav } from "../../shared/layout/nav";
import { SectionTitle, SectionSub, Card, TwoCol, Btn } from "../../shared/components/atoms";
import { C, fmt, detalleError } from "../../shared/utils/format";
import { CATALOGO_USO_CFDI, usosValidosParaRegimen } from "./catalogoUsoCfdi";

const FORM_VACIO = {clienteRfc:"",receptor:"",rfc:"",usoCfdi:"G03",domicilioFiscal:"",regimenFiscal:"",concepto:"",cantidad:"",precio:"",iva:"16"};
// v1: solo estos 3 usos en el dropdown (el catálogo trae los 24, listos para
// cuando se expanda). El dropdown se filtra según el régimen del receptor
// cuando se conoce (cliente registrado); con receptor manual se muestran los 3.
const USOS_V1 = ["G03", "G01", "S01"];

export default function NuevaFactura(){
  const toast = useToast();
  const nav = useNav();
  const { emisores, loading:loadingEmisores, error:errorEmisores, emisorActivoRfc, emisorActivo:emisor, emisorInactivo } = useEmisores();
  const { clientes, loading:loadingClientes, error:errorClientes } = useClientes();
  // emisor y emisorInactivo vienen de useEmisores() (fuente unica). El guard
  // de UI ahora es central en AppShell: cuando el emisor activo esta
  // Inactivo, bloquea TODAS las vistas salvo Administracion > Emisores. El
  // banner + boton deshabilitado de abajo quedan como defensa en profundidad
  // (por si "nueva" dejara de estar bloqueada centralmente).

  const [form,setForm]=useState(FORM_VACIO);
  const [enviando,setEnviando]=useState(false);
  const [guardandoBorrador,setGuardandoBorrador]=useState(false);
  // id del borrador que se abrio con "Abrir" desde la lista - si viene, se
  // elimina tras timbrar con exito para que no quede duplicado en la lista.
  const [borradorId,setBorradorId]=useState(null);
  const [resultado,setResultado]=useState(null);
  const [errorTimbrado,setErrorTimbrado]=useState(null);

  // Cargar un borrador entregado por la navegacion ("Abrir" en Generadas >
  // Borradores). Se hace en un effect (no en el initializer de useState)
  // porque esta vista NO se re-monta al navegar - es un elemento estatico
  // en VIEWS. Se consume el payload una sola vez (nav.setPayload(null)).
  const borradorEntrante = nav?.payload?.borrador;
  useEffect(() => {
    if (!borradorEntrante) return;
    try {
      const datos = JSON.parse(borradorEntrante.datos_json);
      setForm({ ...FORM_VACIO, ...datos });
      setBorradorId(borradorEntrante.id);
      setResultado(null);
      setErrorTimbrado(null);
      toast(`Borrador #${borradorEntrante.id} cargado`, "info");
    } catch {
      toast("El borrador está dañado y no se pudo abrir", "error");
    }
    nav.setPayload(null);
  }, [borradorEntrante]);
  // Idempotencia real de timbrado (27 ago 2026) - una key por "sesion de
  // captura", generada una sola vez (no en cada render/click). Un reintento
  // de la MISMA operacion (ej. tras un timeout de red) reusa esta misma key,
  // asi el backend detecta el duplicado y devuelve la factura ya existente
  // en vez de timbrar dos veces. Solo se regenera cuando el formulario se
  // resetea de verdad (timbrado exitoso), nunca al editar campos ni al
  // fallar un intento.
  const [idempotencyKey,setIdempotencyKey]=useState(() => crypto.randomUUID());

  // Receptor generico (Publico en General): el SAT exige que su domicilio
  // fiscal sea igual al LugarExpedicion del emisor activo (regla ya aplicada
  // en facturacion/main.py al armar el CFDI). Si el usuario cambia de emisor
  // con el generico ya seleccionado, este CP debe seguir al emisor - un
  // cliente real conserva su propio domicilio fiscal, sin tocarlo aqui.
  useEffect(() => {
    if (form.rfc === "XAXX010101000" && emisor?.codigo_postal) {
      setForm(f => f.domicilioFiscal === emisor.codigo_postal ? f : {...f, domicilioFiscal: emisor.codigo_postal});
    }
  }, [emisor?.codigo_postal, form.rfc]);

  // Reset automatico tras timbrado exitoso (27 ago 2026) - una vez que la
  // factura se timbro, la operacion termino: limpiar los campos de
  // receptor/concepto para la siguiente venta, sin necesidad de un boton
  // manual. Se dispara SOLO cuando `resultado` pasa de vacio a tener valor
  // (justo despues de un timbrado exitoso), nunca mientras el usuario esta
  // escribiendo - evita el riesgo de pisar texto a medio capturar que tenia
  // la alternativa de "limpiar al vaciar el campo".
  useEffect(() => {
    if (resultado) {
      setForm(f => ({
        ...f,
        clienteRfc: "",
        receptor: "",
        rfc: "",
        domicilioFiscal: "",
        regimenFiscal: "",
        concepto: "",
        cantidad: "",
        precio: "",
      }));
      setIdempotencyKey(crypto.randomUUID());
      // Si se timbro desde un borrador, borrarlo: la operacion termino, ya
      // existe una factura real, dejarlo en la lista solo confundiria.
      // best-effort: si el DELETE falla el usuario puede borrarlo a mano.
      if (borradorId) {
        fetchAuth(`${API_BASE}/facturas/borradores/${borradorId}?motivo=post_timbrado`, { method: "DELETE" }).catch(() => {});
        setBorradorId(null);
      }
    }
  }, [resultado]);

  // Uso CFDI válidos para el régimen del receptor. Si no hay régimen (receptor
  // manual sin cliente), usosValidosParaRegimen regresa los 3 sin filtrar.
  const usosDisponibles = usosValidosParaRegimen(form.regimenFiscal, USOS_V1);
  // Si el régimen cambió y el Uso CFDI seleccionado ya no es válido para él,
  // moverlo a la primera opción válida - no dejar un valor inválido puesto en
  // silencio (era la causa del rechazo CFDI40161: G03 con régimen 616).
  useEffect(() => {
    if (usosDisponibles.length && !usosDisponibles.includes(form.usoCfdi)) {
      setForm(f => ({ ...f, usoCfdi: usosDisponibles[0] }));
    }
  }, [form.regimenFiscal]); // eslint-disable-line react-hooks/exhaustive-deps

  const sub=(parseFloat(form.cantidad)||0)*(parseFloat(form.precio)||0);
  const total=sub*(1+(parseFloat(form.iva)||0)/100);

  const seleccionarCliente = rfc => {
    setResultado(null); setErrorTimbrado(null);
    if (!rfc) { setForm(f=>({...f,clienteRfc:"",receptor:"",rfc:"",domicilioFiscal:"",regimenFiscal:""})); return; }
    const c = clientes.find(c=>c.rfc===rfc);
    if (!c) return;
    setForm(f=>({
      ...f,
      clienteRfc:rfc,
      receptor:c.nombre,
      rfc:c.rfc,
      usoCfdi:c.uso_cfdi_default||f.usoCfdi,
      domicilioFiscal:c.domicilio_fiscal||"",
      regimenFiscal:c.regimen_fiscal||"",
      concepto: (c.rfc === "XAXX010101000" && !f.concepto) ? "Venta al público en general" : f.concepto,
    }));
  };

  const inp=(lbl,k,type="text",extra={})=>(
    <div style={{marginBottom:10}}>
      <label style={{fontSize:12,color:C.textSec,display:"block",marginBottom:3}}>{lbl}</label>
      <input type={type} value={form[k]} onChange={e=>setForm({...form,[k]:e.target.value})} placeholder={lbl} {...extra}
        style={{width:"100%",border:`1px solid ${C.border}`,borderRadius:8,padding:"8px 11px",fontSize:13,color:C.text,background:"#fff",boxSizing:"border-box"}}/>
    </div>
  );

  const guardarBorrador = async () => {
    setGuardandoBorrador(true);
    try {
      const res = await fetchAuth(`${API_BASE}/facturas/borradores`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          emisor_rfc: emisor?.rfc || null,
          datos_json: JSON.stringify(form),
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(detalleError(data, res));
      // Si se guarda un borrador NUEVO desde uno abierto, el que ya existia
      // sigue en la lista - se "desengancha" para no borrarlo al timbrar.
      setBorradorId(null);
      toast(`Borrador guardado (#${data.id})`, "success");
    } catch (e) {
      toast(`Error al guardar borrador: ${e.message}`, "error");
    } finally {
      setGuardandoBorrador(false);
    }
  };

  const timbrar = async () => {
    if (!emisor) { toast("No hay ningún emisor registrado en Administración todavía","error"); return; }
    if (emisorInactivo) { toast("El emisor activo está Inactivo y no puede timbrar. Reactívalo en Administración › Emisores.","error"); return; }
    if (!form.receptor||!form.rfc||!form.domicilioFiscal||!form.concepto||!form.cantidad||!form.precio) {
      toast("Completa receptor, domicilio fiscal y los datos del concepto antes de timbrar","warning"); return;
    }
    if (parseFloat(form.cantidad) <= 0 || parseFloat(form.precio) <= 0) {
      toast("Cantidad y precio unitario deben ser mayores a cero", "warning");
      return;
    }
    setEnviando(true); setErrorTimbrado(null); setResultado(null);
    const payload = {
      emisor_rfc: emisor.rfc,
      receptor: {
        nombre: form.receptor,
        rfc: form.rfc,
        uso_cfdi: form.usoCfdi,
        domicilio_fiscal: form.domicilioFiscal,
        ...(form.regimenFiscal ? { regimen_fiscal: form.regimenFiscal } : {}),
      },
      conceptos: [{
        descripcion: form.concepto,
        cantidad: parseFloat(form.cantidad),
        precio_unitario: parseFloat(form.precio),
        iva_tasa: (parseFloat(form.iva)||0)/100,
      }],
    };
    try {
      const res = await fetchAuth(`${API_BASE}/facturas/timbrar`, {
        method:"POST",
        headers:{"Content-Type":"application/json","X-Idempotency-Key":idempotencyKey},
        body:JSON.stringify(payload),
      });
      const data = await res.json().catch(()=>({}));
      if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
      setResultado(data);
      toast(`Factura timbrada — UUID ${data.uuid}`,"success");
    } catch(e) {
      setErrorTimbrado(e.message);
      toast(`Error al timbrar: ${e.message}`,"error");
    } finally {
      setEnviando(false);
    }
  };

  return (
    <div>
      <SectionTitle>Nueva Factura CFDI 4.0</SectionTitle>
      <SectionSub>O usa el <strong>Lector IA</strong> para subir una orden de compra y rellenar automáticamente.</SectionSub>
      {emisorInactivo && (
        <Card style={{marginBottom:12,borderColor:C.danger,background:C.dangerSoft}}>
          <div style={{fontSize:13,color:C.danger,fontWeight:600}}>
            ⚠ El emisor <strong>{emisor.razon_social}</strong> ({emisor.rfc}) está <strong>Inactivo</strong> y no puede timbrar facturas.
          </div>
          <div style={{fontSize:12,color:C.textSec,marginTop:4}}>
            Ve a <strong>Administración › Emisores</strong> para reactivarlo, o selecciona otro emisor activo en el menú superior.
          </div>
        </Card>
      )}
      <TwoCol>
        <Card>
          <div style={{fontSize:11,fontWeight:700,color:C.accent,letterSpacing:"0.08em",marginBottom:12,textTransform:"uppercase"}}>Emisor</div>
          {loadingEmisores && <div style={{fontSize:13,color:C.textMuted}}>Cargando emisor…</div>}
          {errorEmisores && <div style={{fontSize:13,color:C.danger}}>⚠ No se pudo cargar el emisor: {errorEmisores}</div>}
          {!loadingEmisores && !errorEmisores && !emisor && (
            <div style={{fontSize:13,color:C.warn}}>No hay emisores registrados en Administración.</div>
          )}
          {emisor && [["Razón social",emisor.razon_social],["RFC",emisor.rfc],["Régimen fiscal",emisor.regimen_fiscal],["CP",emisor.codigo_postal],["Estado",emisor.estado]].map(([l,v])=>(
            <div key={l} style={{marginBottom:10}}>
              <label style={{fontSize:12,color:C.textSec,display:"block",marginBottom:3}}>{l}</label>
              <input readOnly value={v} style={{width:"100%",border:`1px solid ${l==="Estado"&&emisorInactivo?C.danger:C.border}`,borderRadius:8,padding:"8px 11px",fontSize:13,color:l==="Estado"&&emisorInactivo?C.danger:C.text,fontWeight:l==="Estado"&&emisorInactivo?700:400,background:C.surface,boxSizing:"border-box"}}/>
            </div>
          ))}
        </Card>
        <Card>
          <div style={{fontSize:11,fontWeight:700,color:C.accent,letterSpacing:"0.08em",marginBottom:12,textTransform:"uppercase"}}>Receptor</div>
          <div style={{marginBottom:10}}>
            <label style={{fontSize:12,color:C.textSec,display:"block",marginBottom:3}}>Cliente registrado</label>
            <select value={form.clienteRfc} onChange={e=>seleccionarCliente(e.target.value)} disabled={loadingClientes}
              style={{width:"100%",border:`1px solid ${C.border}`,borderRadius:8,padding:"8px 11px",fontSize:13,color:C.text,background:"#fff",boxSizing:"border-box"}}>
              <option value="">— Receptor nuevo (captura manual) —</option>
              {clientes.map(c=>(<option key={c.rfc} value={c.rfc}>{c.nombre} — {c.rfc}</option>))}
            </select>
            {errorClientes && <div style={{fontSize:11,color:C.danger,marginTop:4}}>⚠ No se pudieron cargar los clientes: {errorClientes}</div>}
          </div>
          {inp("Nombre / Razón social","receptor")}
          {inp("RFC","rfc")}
          {inp("Domicilio fiscal (CP)","domicilioFiscal")}
          <div style={{marginBottom:10}}>
            <label style={{fontSize:12,color:C.textSec,display:"block",marginBottom:3}}>Uso CFDI</label>
            {usosDisponibles.length === 0 ? (
              <div style={{fontSize:12,color:C.danger,border:`1px solid ${C.danger}`,borderRadius:8,padding:"8px 11px",background:"#fff"}}>
                ⚠ Ninguno de los usos disponibles ({USOS_V1.join(", ")}) es válido para el régimen fiscal {form.regimenFiscal} del receptor. Elige un cliente con otro régimen o corrige el régimen del cliente.
              </div>
            ) : (
              <select value={form.usoCfdi} onChange={e=>setForm({...form,usoCfdi:e.target.value})}
                style={{width:"100%",border:`1px solid ${C.border}`,borderRadius:8,padding:"8px 11px",fontSize:13,color:C.text,background:"#fff",boxSizing:"border-box"}}>
                {usosDisponibles.map(clave=>(
                  <option key={clave} value={clave}>{clave} – {CATALOGO_USO_CFDI[clave].desc.replace(/\.$/,"")}</option>
                ))}
              </select>
            )}
            {!form.regimenFiscal && (
              <div style={{fontSize:11,color:C.textMuted,marginTop:4}}>
                Se muestran todas las opciones. Filtrar por régimen fiscal requiere elegir un cliente registrado.
              </div>
            )}
          </div>
        </Card>
      </TwoCol>
      <Card style={{marginTop:12}}>
        <div style={{fontSize:11,fontWeight:700,color:C.accent,letterSpacing:"0.08em",marginBottom:12,textTransform:"uppercase"}}>Conceptos</div>
        <div style={{display:"grid",gridTemplateColumns:"repeat(auto-fit,minmax(130px,1fr))",gap:10,marginBottom:10}}>
          {inp("Descripción","concepto")}
          {inp("Cantidad","cantidad","number",{min:"0"})}
          {inp("Precio unitario","precio","number",{min:"0"})}
          {inp("IVA %","iva","number")}
        </div>
        <div style={{display:"flex",justifyContent:"flex-end",gap:20,paddingTop:12,borderTop:`1px solid ${C.border}`,flexWrap:"wrap"}}>
          {[["Subtotal",sub],["IVA",sub*(parseFloat(form.iva)||0)/100],["Total",total]].map(([l,v])=>(
            <div key={l} style={{textAlign:"right"}}>
              <div style={{fontSize:11,color:C.textMuted}}>{l}</div>
              <div style={{fontSize:l==="Total"?18:13,fontWeight:l==="Total"?700:500,color:l==="Total"?C.accent:C.text}}>{fmt(v)}</div>
            </div>
          ))}
        </div>
      </Card>
      <div style={{marginTop:12,display:"flex",gap:10,flexWrap:"wrap"}}>
        <Btn onClick={timbrar} disabled={enviando||emisorInactivo}>{enviando?"Timbrando…":(emisorInactivo?"Emisor Inactivo — no se puede timbrar":"Timbrar con PAC →")}</Btn>
        <Btn variant="secondary" onClick={guardarBorrador} disabled={guardandoBorrador}>{guardandoBorrador?"Guardando…":(borradorId?"Guardar como nuevo borrador":"Guardar borrador")}</Btn>
        {borradorId && <span style={{fontSize:12,color:C.textMuted,alignSelf:"center"}}>Editando borrador #{borradorId} — al timbrar se elimina</span>}
      </div>
      {errorTimbrado && (
        <Card style={{marginTop:12,borderColor:C.danger,background:C.dangerSoft}}>
          <div style={{fontSize:13,color:C.danger}}>⚠ {errorTimbrado}</div>
        </Card>
      )}
      {resultado && (
        <Card style={{marginTop:12,borderColor:C.accentBorder,background:C.accentSoft}}>
          <div style={{fontSize:11,fontWeight:700,color:"#0A6B4A",letterSpacing:"0.08em",marginBottom:12,textTransform:"uppercase"}}>✓ Timbrado exitoso</div>
          <div style={{display:"grid",gridTemplateColumns:"repeat(auto-fit,minmax(150px,1fr))",gap:10,marginBottom:12}}>
            {[["UUID",resultado.uuid],["Folio",resultado.folio],["Estado",resultado.estado],["Total",fmt(resultado.total)]].map(([l,v])=>(
              <div key={l} style={{background:"#fff",borderRadius:8,padding:"10px 12px"}}>
                <div style={{fontSize:10,color:C.textMuted,textTransform:"uppercase",letterSpacing:"0.06em",marginBottom:3}}>{l}</div>
                <div style={{fontSize:13,fontWeight:600,color:C.text,wordBreak:"break-all"}}>{v}</div>
              </div>
            ))}
          </div>
          <div style={{display:"flex",gap:10,flexWrap:"wrap"}}>
            <a href={resultado.xml_url} target="_blank" rel="noreferrer"><Btn variant="secondary">Descargar XML</Btn></a>
            <a href={resultado.pdf_url} target="_blank" rel="noreferrer"><Btn variant="secondary">Descargar PDF</Btn></a>
          </div>
          <div style={{fontSize:11,color:C.textMuted,marginTop:8}}>
            Nota: las URLs de descarga apuntan a MinIO dentro de la red de Docker — hoy no son accesibles desde fuera de ese entorno (ver #8/#19/#20).
          </div>
        </Card>
      )}
    </div>
  );
}
