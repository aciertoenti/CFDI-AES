import { useState } from "react";
import logoAcierto from "../../assets/logo-acierto.png";
import { Btn } from "../../shared/components/atoms";
import { C } from "../../shared/utils/format";

export default function Login({ onLogin, onIrARegistro, onIrAOlvide, onIrAHome }) {
  const [identificador, setIdentificador] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);

  const submit = async e => {
    e.preventDefault();
    setLoading(true); setError(null);
    const r = await onLogin(identificador, password);
    setLoading(false);
    if (!r.ok) setError(r.error);
  };

  return (
    <div style={{minHeight:"100dvh",display:"flex",alignItems:"center",justifyContent:"center",background:"linear-gradient(135deg,#071c31 0%,#0A2540 54%,#104d5d 100%)",padding:20,boxSizing:"border-box"}}>
      <form onSubmit={submit} style={{background:C.primary,padding:"28px 22px",borderRadius:12,width:340,maxWidth:"100%",boxShadow:"0 16px 40px rgba(0,0,0,.22)",border:"1px solid rgba(255,255,255,.14)",display:"flex",flexDirection:"column",alignItems:"center",boxSizing:"border-box",position:"relative"}}>
        <div style={{alignSelf:"stretch",display:"flex",justifyContent:"flex-end",marginBottom:18,position:"relative"}}>
          <button type="button" aria-label={menuOpen ? "Cerrar menú" : "Abrir menú"} aria-expanded={menuOpen} onClick={()=>setMenuOpen(!menuOpen)} style={{width:42,height:38,border:"1px solid rgba(255,255,255,.34)",borderRadius:8,background:"rgba(255,255,255,.08)",color:"#fff",fontSize:22,lineHeight:1,cursor:"pointer"}}>{menuOpen ? "×" : "☰"}</button>
          {menuOpen && <nav aria-label="Menú principal" style={{position:"absolute",top:46,right:0,zIndex:2,minWidth:170,padding:8,display:"grid",gap:6,background:C.card,border:`1px solid ${C.border}`,borderRadius:8,boxShadow:"0 14px 30px rgba(0,0,0,.24)"}}>
            <Btn type="button" onClick={()=>{setMenuOpen(false);onIrAHome();}} style={{width:"100%"}}>Inicio</Btn>
          </nav>}
        </div>
        <img src={logoAcierto} alt="Acierto" style={{width:170,height:170,objectFit:"contain",mixBlendMode:"screen",marginBottom:14}}/>
        <div style={{fontSize:14,color:"rgba(255,255,255,.72)",marginBottom:22,textAlign:"center"}}>Inicia sesión para continuar</div>
        <div style={{marginBottom:14,width:"100%"}}>
          <label htmlFor="login-rfc" style={{fontSize:13,color:"rgba(255,255,255,.78)",display:"block",marginBottom:5}}>RFC o USUARIO</label>
          <input id="login-rfc" type="text" required autoFocus maxLength={13} value={identificador}
            onChange={e=>setIdentificador(e.target.value.toUpperCase())} placeholder="RFC o USUARIO"
            style={{width:"100%",border:"1px solid rgba(255,255,255,.2)",borderRadius:8,padding:"11px 12px",fontSize:16,color:C.text,background:"#fff",boxSizing:"border-box"}}/>
        </div>
        <div style={{marginBottom:10,width:"100%"}}>
          <label htmlFor="login-password" style={{fontSize:13,color:"rgba(255,255,255,.78)",display:"block",marginBottom:5}}>Contraseña</label>
          <input id="login-password" type="password" required value={password} onChange={e=>setPassword(e.target.value)}
            style={{width:"100%",border:"1px solid rgba(255,255,255,.2)",borderRadius:8,padding:"11px 12px",fontSize:16,color:C.text,background:"#fff",boxSizing:"border-box"}}/>
        </div>
        <button type="button" onClick={onIrAOlvide} style={{alignSelf:"flex-end",marginBottom:16,background:"none",border:"none",color:"rgba(255,255,255,.7)",fontSize:12,cursor:"pointer",textDecoration:"underline"}}>¿Olvidaste tu contraseña?</button>
        {error && <div style={{fontSize:12,color:C.danger,marginBottom:14,padding:"8px 10px",background:C.dangerSoft,borderRadius:6,width:"100%",boxSizing:"border-box"}}>⚠ {error}</div>}
        <Btn variant="accent" style={{width:"100%",padding:"12px 18px"}} disabled={loading}>{loading ? "Ingresando…" : "Iniciar sesión"}</Btn>
        <button type="button" onClick={onIrARegistro} style={{marginTop:14,background:"none",border:"none",color:"rgba(255,255,255,.7)",fontSize:12,cursor:"pointer",textDecoration:"underline"}}>¿No tienes cuenta? Crear una</button>
      </form>
    </div>
  );
}
