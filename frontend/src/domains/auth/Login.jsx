import { useState } from "react";
import logoAcierto from "../../assets/logo-acierto.png";
import { Btn } from "../../shared/components/atoms";
import { C } from "../../shared/utils/format";

export default function Login({ onLogin, onIrARegistro, onIrAOlvide }) {
  const [identificador, setIdentificador] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  const submit = async e => {
    e.preventDefault();
    setLoading(true); setError(null);
    const r = await onLogin(identificador, password);
    setLoading(false);
    if (!r.ok) setError(r.error);
  };

  return (
    <div style={{minHeight:"100dvh",display:"flex",alignItems:"center",justifyContent:"center",background:C.surface,padding:20,boxSizing:"border-box"}}>
      <form onSubmit={submit} style={{background:C.card,padding:"28px 22px",borderRadius:12,width:340,maxWidth:"100%",boxShadow:"0 4px 24px rgba(0,0,0,.08)",border:`1px solid ${C.border}`,display:"flex",flexDirection:"column",alignItems:"center",boxSizing:"border-box"}}>
        <img src={logoAcierto} alt="Acierto" style={{width:120,maxWidth:"60%",borderRadius:8,display:"block",marginBottom:14}}/>
        <div style={{fontSize:14,color:C.textSec,marginBottom:22,textAlign:"center"}}>Inicia sesión para continuar</div>
        <div style={{marginBottom:14,width:"100%"}}>
          <label htmlFor="login-rfc" style={{fontSize:13,color:C.textSec,display:"block",marginBottom:5}}>RFC o USUARIO</label>
          <input id="login-rfc" type="text" required autoFocus maxLength={13} value={identificador}
            onChange={e=>setIdentificador(e.target.value.toUpperCase())} placeholder="RFC o USUARIO"
            style={{width:"100%",border:`1px solid ${C.border}`,borderRadius:8,padding:"11px 12px",fontSize:16,color:C.text,boxSizing:"border-box"}}/>
        </div>
        <div style={{marginBottom:10,width:"100%"}}>
          <label htmlFor="login-password" style={{fontSize:13,color:C.textSec,display:"block",marginBottom:5}}>Contraseña</label>
          <input id="login-password" type="password" required value={password} onChange={e=>setPassword(e.target.value)}
            style={{width:"100%",border:`1px solid ${C.border}`,borderRadius:8,padding:"11px 12px",fontSize:16,color:C.text,boxSizing:"border-box"}}/>
        </div>
        <button type="button" onClick={onIrAOlvide} style={{alignSelf:"flex-end",marginBottom:16,background:"none",border:"none",color:C.textSec,fontSize:12,cursor:"pointer",textDecoration:"underline"}}>¿Olvidaste tu contraseña?</button>
        {error && <div style={{fontSize:12,color:C.danger,marginBottom:14,padding:"8px 10px",background:C.dangerSoft,borderRadius:6,width:"100%",boxSizing:"border-box"}}>⚠ {error}</div>}
        <Btn style={{width:"100%",padding:"12px 18px"}} disabled={loading}>{loading ? "Ingresando…" : "Iniciar sesión"}</Btn>
        <button type="button" onClick={onIrARegistro} style={{marginTop:14,background:"none",border:"none",color:C.textSec,fontSize:12,cursor:"pointer",textDecoration:"underline"}}>¿No tienes cuenta? Crear una</button>
      </form>
    </div>
  );
}
