import { useState } from "react";
import logoAcierto from "../../assets/logo-acierto.png";
import { Btn } from "../../shared/components/atoms";
import { C } from "../../shared/utils/format";

export default function OlvideContrasena({ onSolicitar, onIrALogin }) {
  const [email, setEmail] = useState("");
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [enviado, setEnviado] = useState(false);
  const submit = async e => {
    e.preventDefault();
    setLoading(true); setError(null);
    const r = await onSolicitar(email);
    setLoading(false);
    if (r.ok) setEnviado(true); else setError(r.error);
  };
  return (
    <div style={{minHeight:"100dvh",display:"flex",alignItems:"center",justifyContent:"center",background:C.surface,padding:20,boxSizing:"border-box"}}>
      <div style={{background:C.card,padding:"28px 22px",borderRadius:12,width:340,maxWidth:"100%",boxShadow:"0 4px 24px rgba(0,0,0,.08)",border:`1px solid ${C.border}`,display:"flex",flexDirection:"column",alignItems:"center",boxSizing:"border-box"}}>
        <img src={logoAcierto} alt="Acierto" style={{width:120,maxWidth:"60%",borderRadius:8,display:"block",marginBottom:14}}/>
        {enviado ? <>
          <div style={{fontSize:14,color:C.text,marginBottom:22,textAlign:"center",lineHeight:1.5}}>Si <strong>{email}</strong> está registrado, te enviamos un enlace para recuperar tu contraseña. Revisa tu bandeja de entrada (y spam).</div>
          <button type="button" onClick={onIrALogin} style={{background:"none",border:"none",color:C.textSec,fontSize:12,cursor:"pointer",textDecoration:"underline"}}>Volver a iniciar sesión</button>
        </> : <form onSubmit={submit} style={{width:"100%",display:"flex",flexDirection:"column",alignItems:"center"}}>
          <div style={{fontSize:14,color:C.textSec,marginBottom:22,textAlign:"center"}}>¿Olvidaste tu contraseña? Escribe tu correo y te mandamos un enlace para recuperarla.</div>
          <div style={{marginBottom:20,width:"100%"}}>
            <label htmlFor="olvide-email" style={{fontSize:13,color:C.textSec,display:"block",marginBottom:5}}>Correo electrónico</label>
            <input id="olvide-email" type="email" required autoFocus value={email} onChange={e=>setEmail(e.target.value)} style={{width:"100%",border:`1px solid ${C.border}`,borderRadius:8,padding:"11px 12px",fontSize:16,color:C.text,boxSizing:"border-box"}}/>
          </div>
          {error && <div style={{fontSize:12,color:C.danger,marginBottom:14,padding:"8px 10px",background:C.dangerSoft,borderRadius:6,width:"100%",boxSizing:"border-box"}}>⚠ {error}</div>}
          <Btn style={{width:"100%",padding:"12px 18px"}} disabled={loading}>{loading ? "Enviando…" : "Enviar enlace"}</Btn>
          <button type="button" onClick={onIrALogin} style={{marginTop:14,background:"none",border:"none",color:C.textSec,fontSize:12,cursor:"pointer",textDecoration:"underline"}}>Volver a iniciar sesión</button>
        </form>}
      </div>
    </div>
  );
}
