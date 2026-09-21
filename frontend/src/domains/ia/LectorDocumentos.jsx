import { useState, useRef, useEffect } from "react";
import { API_BASE, fetchAuth } from "../../shared/hooks/fetchAuth";
import { useDocumentExtractor } from "./hooks";
import { useToast } from "../../shared/layout/ToastProvider";
import useEmisores from "../../shared/hooks/useEmisores";
import { Card, Btn, SectionTitle, SectionSub } from "../../shared/components/atoms";
import { C, fmt } from "../../shared/utils/format";

// ═══════════════════════════════════════════════════════════════════════════════
// VISTA: LECTOR IA
// ═══════════════════════════════════════════════════════════════════════════════
export default function LectorDocumentos(){
  const toast = useToast();
  const {extraer,loading,result,error,steps}=useDocumentExtractor();
  const {emisorActivoRfc}=useEmisores();
  const [dragging,setDragging]=useState(false);
  const [file,setFile]=useState(null);
  const inputRef=useRef();

  // Timbrado real desde el Lector IA (g4VVTs, 17 sep 2026) - antes el botón
  // "Timbrar este CFDI" solo disparaba un toast decorativo (toast(`POST
  // ${API_BASE}/facturas/timbrar — ...`)), nunca llamaba al backend.
  // X-Idempotency-Key: se genera UNA vez por documento extraído (result
  // nuevo), no en cada click - un reintento tras error de red reutiliza la
  // misma key (mismo patrón ya usado en NuevaFactura.jsx), evitando
  // timbrar el mismo CFDI dos veces por un doble-click o un reintento.
  const [idempotencyKey,setIdempotencyKey]=useState(()=>crypto.randomUUID());
  // Revisión editable + umbral de confianza (g7gsWQ, 21 sep 2026) - "result"
  // (del hook, useDocumentExtractor) queda intacto como la extracción cruda
  // de la IA; "editado" es la copia que el usuario puede corregir y la que
  // de verdad alimenta el payload de timbrado. Se re-siembra cada vez que
  // llega un "result" nuevo (documento nuevo), junto con idempotencyKey -
  // mismo effect, mismo disparador.
  const [editado,setEditado]=useState(null);
  const [tocado,setTocado]=useState(false);
  useEffect(()=>{
    if(result){
      setIdempotencyKey(crypto.randomUUID());
      setEditado({
        receptor_nombre:result.receptor_nombre,
        receptor_rfc:result.receptor_rfc,
        receptor_uso_cfdi:result.receptor_uso_cfdi,
        receptor_regimen_fiscal:result.receptor_regimen_fiscal,
        receptor_domicilio_fiscal:result.receptor_domicilio_fiscal,
        conceptos:(result.conceptos||[]).map(c=>({...c})),
      });
      setTocado(false);
    }
  },[result]);
  const actualizarCampo=(campo,valor)=>{setEditado(prev=>({...prev,[campo]:valor}));setTocado(true);};
  const actualizarConcepto=(idx,campo,valor)=>{
    setEditado(prev=>({...prev,conceptos:prev.conceptos.map((c,i)=>i===idx?{...c,[campo]:valor}:c)}));
    setTocado(true);
  };
  // Umbral de partida (no es un valor final - ajustar cuando haya datos
  // reales de qué tan calibrada está result.confianza.general, que hoy la
  // IA reporta de 0 a 1). Sin campo de confianza en la respuesta ->
  // confianzaBaja queda en false a propósito (degradar a "sin bloqueo" en
  // vez de romper o bloquear por un dato ausente, mismo criterio usado toda
  // la sesión para campos opcionales sin fuente).
  const UMBRAL_CONFIANZA=0.70;
  const confianzaGeneral=result?.confianza?.general;
  const confianzaBaja=typeof confianzaGeneral==="number"&&confianzaGeneral<UMBRAL_CONFIANZA;
  const timbrarBloqueado=confianzaBaja&&!tocado;
  const [timbrando,setTimbrando]=useState(false);
  const [timbrado,setTimbrado]=useState(null);
  const [errorTimbrado,setErrorTimbrado]=useState(null);

  const handleFile=f=>{setFile(f);setTimbrado(null);setErrorTimbrado(null);extraer(f);};
  const onDrop=e=>{e.preventDefault();setDragging(false);const f=e.dataTransfer.files[0];if(f)handleFile(f);};

  const timbrar=async()=>{
    if(!emisorActivoRfc){setErrorTimbrado("No hay ningún emisor activo seleccionado — elige un emisor antes de timbrar.");return;}
    setTimbrando(true);setErrorTimbrado(null);
    // Reshape: ExtractionResult es plano (receptor_nombre, receptor_rfc, ...),
    // FacturaCreate espera receptor como objeto anidado. conceptos NO se
    // transforma - mismos 6 campos/nombres que Concepto en el backend.
    // emisor_rfc NO viene del Lector IA (una orden de compra ajena no trae
    // el RFC propio) - sale del emisor activo de la app, igual que el resto
    // de los flujos de facturación.
    // "editado" (no "result") alimenta el payload (g7gsWQ) - si el usuario
    // corrigió algo en la revisión, el CFDI timbrado refleja el valor
    // corregido, nunca el original crudo de la IA.
    const payload={
      emisor_rfc:emisorActivoRfc,
      receptor:{
        nombre:editado.receptor_nombre,
        rfc:editado.receptor_rfc,
        uso_cfdi:editado.receptor_uso_cfdi,
        regimen_fiscal:editado.receptor_regimen_fiscal,
        domicilio_fiscal:editado.receptor_domicilio_fiscal,
      },
      conceptos:editado.conceptos,
    };
    try{
      const res=await fetchAuth(`${API_BASE}/facturas/timbrar`,{
        method:"POST",
        headers:{"Content-Type":"application/json","X-Idempotency-Key":idempotencyKey},
        body:JSON.stringify(payload),
      });
      const data=await res.json().catch(()=>({}));
      if(!res.ok) throw new Error(data.detail||`HTTP ${res.status}`);
      setTimbrado(data);
      toast(`Factura timbrada — UUID ${data.uuid}`,"success");
    }catch(e){
      setErrorTimbrado(e.message);
      toast(`Error al timbrar: ${e.message}`,"error");
    }finally{
      setTimbrando(false);
    }
  };

  const procesarOtro=()=>{setFile(null);setTimbrado(null);setErrorTimbrado(null);};

  return (
    <div>
      <SectionTitle>Lector de documentos IA</SectionTitle>
      <SectionSub>Sube una orden de compra, cotización o nota — la IA extrae los datos y genera el CFDI.</SectionSub>
      {!file&&(
        <>
          <div onDrop={onDrop} onDragOver={e=>{e.preventDefault();setDragging(true);}} onDragLeave={()=>setDragging(false)}
            onClick={()=>inputRef.current.click()}
            style={{border:`2px dashed ${dragging?C.accent:C.border}`,borderRadius:12,padding:"40px 20px",textAlign:"center",cursor:"pointer",background:dragging?C.accentSoft:"transparent",transition:"all .2s"}}>
            <div style={{fontSize:36,marginBottom:10}}>📄</div>
            <div style={{fontSize:14,fontWeight:600,color:C.text,marginBottom:4}}>Arrastra tu documento aquí</div>
            <div style={{fontSize:12,color:C.textMuted}}>PDF · XML · JPG · PNG</div>
            <input ref={inputRef} type="file" accept=".pdf,.jpg,.jpeg,.png,.xml" style={{display:"none"}} onChange={e=>e.target.files[0]&&handleFile(e.target.files[0])}/>
          </div>
          <div style={{display:"grid",gridTemplateColumns:"repeat(auto-fit,minmax(100px,1fr))",gap:8,marginTop:10}}>
            {[["🛒","Orden de compra"],["📋","Cotización"],["🚚","Nota de entrega"]].map(([ic,lbl])=>(
              <div key={lbl} onClick={()=>inputRef.current.click()} style={{background:C.surface,border:`1px solid ${C.border}`,borderRadius:10,padding:"12px 8px",textAlign:"center",cursor:"pointer"}}>
                <div style={{fontSize:22,marginBottom:4}}>{ic}</div>
                <div style={{fontSize:11,color:C.textSec}}>{lbl}</div>
              </div>
            ))}
          </div>
        </>
      )}
      {loading&&(
        <Card style={{marginTop:14}}>
          <div style={{fontSize:12,color:C.textMuted,marginBottom:6}}>{file?.name}</div>
          <div style={{height:4,background:C.surface,borderRadius:2,overflow:"hidden",marginBottom:14}}>
            <div style={{height:"100%",background:C.accent,borderRadius:2,width:`${Math.min((steps.length/4)*100,95)}%`,transition:"width .5s"}}/>
          </div>
          {steps.map((s,i)=>(
            <div key={i} style={{display:"flex",alignItems:"center",gap:10,padding:"7px 0",borderBottom:`1px solid ${C.border}`}}>
              <span style={{color:C.accent}}>✓</span><span style={{fontSize:13,color:C.textSec}}>{s}</span>
            </div>
          ))}
        </Card>
      )}
      {error&&(
        <Card style={{marginTop:14,borderColor:C.danger,background:C.dangerSoft}}>
          <div style={{fontSize:13,color:C.danger}}>⚠ {error}</div>
          <Btn variant="secondary" onClick={()=>setFile(null)} style={{marginTop:10}}>Intentar con otro archivo</Btn>
        </Card>
      )}
      {result&&editado&&!timbrado&&(
        <div style={{marginTop:14}}>
          <Card>
            <div style={{display:"flex",alignItems:"center",justifyContent:"space-between",marginBottom:14,flexWrap:"wrap",gap:8}}>
              <div style={{fontSize:12,fontWeight:700,color:C.text,textTransform:"uppercase",letterSpacing:"0.06em"}}>Datos extraídos por IA — revisa y corrige antes de timbrar</div>
              <span style={{fontSize:11,fontWeight:600,color:confianzaBaja?C.danger:"#0A6B4A"}}>{confianzaBaja?"⚠":"✓"} {Math.round((confianzaGeneral??.95)*100)}% confianza</span>
            </div>
            {/* Campos editables (g7gsWQ, 21 sep 2026) - antes eran texto de
                solo lectura; regimen_fiscal y domicilio_fiscal ni siquiera se
                mostraban (se mandaban "a ciegas" en el payload de timbrado
                sin que el usuario los viera). "editado" alimenta estos
                inputs, nunca "result" directo - result queda intacto como
                referencia de lo que la IA extrajo originalmente. */}
            <div style={{display:"grid",gridTemplateColumns:"repeat(auto-fit,minmax(150px,1fr))",gap:10}}>
              {[
                ["receptor_nombre","Receptor"],
                ["receptor_rfc","RFC"],
                ["receptor_uso_cfdi","Uso CFDI"],
                ["receptor_regimen_fiscal","Régimen fiscal receptor"],
                ["receptor_domicilio_fiscal","Domicilio fiscal (CP)"],
              ].map(([campo,l])=>(
                <div key={campo} style={{background:C.surface,borderRadius:8,padding:"10px 12px",position:"relative"}}>
                  <div style={{fontSize:10,color:C.textMuted,textTransform:"uppercase",letterSpacing:"0.06em",marginBottom:3}}>{l}</div>
                  <input value={editado[campo]||""} onChange={e=>actualizarCampo(campo,e.target.value)}
                    style={{width:"100%",border:"none",background:"transparent",fontSize:13,fontWeight:600,color:C.text,padding:0,paddingRight:26}}/>
                  <span style={{position:"absolute",top:8,right:8,fontSize:9,fontWeight:600,padding:"2px 6px",borderRadius:8,background:"#EBF8FF",color:C.info}}>IA</span>
                </div>
              ))}
              {[["Método pago",result.metodo_pago],["Orden",result.numero_orden],["Addenda",result.addenda_detectada||"—"]].map(([l,v])=>(
                <div key={l} style={{background:C.surface,borderRadius:8,padding:"10px 12px"}}>
                  <div style={{fontSize:10,color:C.textMuted,textTransform:"uppercase",letterSpacing:"0.06em",marginBottom:3}}>{l}</div>
                  <div style={{fontSize:13,fontWeight:600,color:C.text}}>{v||"—"}</div>
                </div>
              ))}
            </div>
            {/* Conceptos (g7gsWQ) - antes no se mostraban en absoluto, se
                mandaban directo de result.conceptos al payload sin que el
                usuario los viera ni pudiera corregirlos. */}
            <div style={{fontSize:10,color:C.textMuted,textTransform:"uppercase",letterSpacing:"0.06em",margin:"16px 0 8px"}}>Conceptos</div>
            <div style={{display:"flex",flexDirection:"column",gap:8}}>
              {editado.conceptos.map((c,idx)=>(
                <div key={idx} style={{background:C.surface,borderRadius:8,padding:"10px 12px",display:"grid",gridTemplateColumns:"repeat(auto-fit,minmax(110px,1fr))",gap:8}}>
                  {[
                    ["descripcion","Descripción","text"],
                    ["cantidad","Cantidad","number"],
                    ["precio_unitario","Precio unitario","number"],
                    ["clave_prod_serv","Clave prod/serv","text"],
                    ["clave_unidad","Clave unidad","text"],
                    ["iva_tasa","Tasa IVA","number"],
                  ].map(([campo,l,tipo])=>(
                    <div key={campo}>
                      <div style={{fontSize:9,color:C.textMuted,textTransform:"uppercase",letterSpacing:"0.06em",marginBottom:2}}>{l}</div>
                      <input type={tipo} step={tipo==="number"?"any":undefined} value={c[campo]??""}
                        onChange={e=>actualizarConcepto(idx,campo,tipo==="number"?(e.target.value===""?"":Number(e.target.value)):e.target.value)}
                        style={{width:"100%",border:`1px solid ${C.border}`,borderRadius:6,background:"#fff",fontSize:12,color:C.text,padding:"4px 6px",boxSizing:"border-box"}}/>
                    </div>
                  ))}
                </div>
              ))}
            </div>
          </Card>
          {confianzaBaja&&(
            <Card style={{marginTop:10,borderColor:timbrarBloqueado?C.danger:C.accentBorder,background:timbrarBloqueado?C.dangerSoft:C.accentSoft}}>
              <div style={{fontSize:13,color:timbrarBloqueado?C.danger:"#0A6B4A"}}>
                {timbrarBloqueado
                  ?`⚠ Confianza baja (${Math.round(confianzaGeneral*100)}%) - revisa los datos antes de timbrar. Toca al menos un campo para confirmar que los revisaste.`
                  :`✓ Datos revisados - puedes timbrar aunque la confianza reportada sea baja (${Math.round(confianzaGeneral*100)}%).`}
              </div>
            </Card>
          )}
          {errorTimbrado&&(
            <Card style={{marginTop:10,borderColor:C.danger,background:C.dangerSoft}}>
              <div style={{fontSize:13,color:C.danger}}>⚠ {errorTimbrado}</div>
            </Card>
          )}
          <div style={{display:"grid",gridTemplateColumns:"repeat(auto-fit,minmax(150px,1fr))",gap:10,marginTop:10}}>
            <Btn onClick={timbrar} disabled={timbrando||timbrarBloqueado}>{timbrando?"Timbrando…":"Timbrar este CFDI →"}</Btn>
            <Btn variant="secondary" onClick={procesarOtro} disabled={timbrando}>Procesar otro documento</Btn>
          </div>
        </div>
      )}
      {timbrado&&(
        <Card style={{marginTop:14,borderColor:C.accentBorder,background:C.accentSoft}}>
          <div style={{fontSize:11,fontWeight:700,color:"#0A6B4A",letterSpacing:"0.08em",marginBottom:12,textTransform:"uppercase"}}>✓ Timbrado exitoso</div>
          <div style={{display:"grid",gridTemplateColumns:"repeat(auto-fit,minmax(150px,1fr))",gap:10,marginBottom:12}}>
            {[["UUID",timbrado.uuid],["Folio",timbrado.folio],["Estado",timbrado.estado],["Total (IVA incluido)",fmt(timbrado.total)]].map(([l,v])=>(
              <div key={l} style={{background:"#fff",borderRadius:8,padding:"10px 12px"}}>
                <div style={{fontSize:10,color:C.textMuted,textTransform:"uppercase",letterSpacing:"0.06em",marginBottom:3}}>{l}</div>
                <div style={{fontSize:13,fontWeight:600,color:C.text,wordBreak:"break-all"}}>{v}</div>
              </div>
            ))}
          </div>
          <div style={{display:"flex",gap:10,flexWrap:"wrap"}}>
            <a href={timbrado.xml_url} target="_blank" rel="noreferrer"><Btn variant="secondary">Descargar XML</Btn></a>
            <a href={timbrado.pdf_url} target="_blank" rel="noreferrer"><Btn variant="secondary">Descargar PDF</Btn></a>
            <Btn variant="secondary" onClick={procesarOtro}>Procesar otro documento</Btn>
          </div>
        </Card>
      )}
    </div>
  );
}
