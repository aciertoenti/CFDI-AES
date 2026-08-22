import { useState, useRef } from "react";
import { API_BASE } from "../../shared/hooks/fetchAuth";
import { useDocumentExtractor } from "./hooks";
import { useToast } from "../../shared/layout/ToastProvider";
import { Card, Btn, SectionTitle, SectionSub } from "../../shared/components/atoms";
import { C } from "../../shared/utils/format";

// ═══════════════════════════════════════════════════════════════════════════════
// VISTA: LECTOR IA
// ═══════════════════════════════════════════════════════════════════════════════
export default function LectorDocumentos(){
  const toast = useToast();
  const {extraer,loading,result,error,steps}=useDocumentExtractor();
  const [dragging,setDragging]=useState(false);
  const [file,setFile]=useState(null);
  const inputRef=useRef();
  const handleFile=f=>{setFile(f);extraer(f);};
  const onDrop=e=>{e.preventDefault();setDragging(false);const f=e.dataTransfer.files[0];if(f)handleFile(f);};
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
      {result&&(
        <div style={{marginTop:14}}>
          <Card>
            <div style={{display:"flex",alignItems:"center",justifyContent:"space-between",marginBottom:14,flexWrap:"wrap",gap:8}}>
              <div style={{fontSize:12,fontWeight:700,color:C.text,textTransform:"uppercase",letterSpacing:"0.06em"}}>Datos extraídos por IA</div>
              <span style={{fontSize:11,fontWeight:600,color:"#0A6B4A"}}>✓ {Math.round((result.confianza?.general||.95)*100)}% confianza</span>
            </div>
            <div style={{display:"grid",gridTemplateColumns:"repeat(auto-fit,minmax(150px,1fr))",gap:10}}>
              {[["Receptor",result.receptor_nombre],["RFC",result.receptor_rfc],["Uso CFDI",result.receptor_uso_cfdi],["Método pago",result.metodo_pago],["Orden",result.numero_orden],["Addenda",result.addenda_detectada||"—"]].map(([l,v])=>(
                <div key={l} style={{background:C.surface,borderRadius:8,padding:"10px 12px",position:"relative"}}>
                  <div style={{fontSize:10,color:C.textMuted,textTransform:"uppercase",letterSpacing:"0.06em",marginBottom:3}}>{l}</div>
                  <div style={{fontSize:13,fontWeight:600,color:C.text}}>{v||"—"}</div>
                  <span style={{position:"absolute",top:8,right:8,fontSize:9,fontWeight:600,padding:"2px 6px",borderRadius:8,background:"#EBF8FF",color:C.info}}>IA</span>
                </div>
              ))}
            </div>
          </Card>
          <div style={{display:"grid",gridTemplateColumns:"repeat(auto-fit,minmax(150px,1fr))",gap:10,marginTop:10}}>
            <Btn onClick={()=>toast(`POST ${API_BASE}/facturas/timbrar — ${result.receptor_nombre}`,"api")}>Timbrar este CFDI →</Btn>
            <Btn variant="secondary" onClick={()=>setFile(null)}>Procesar otro documento</Btn>
          </div>
        </div>
      )}
    </div>
  );
}
