import { useState } from "react";
import logoAcierto from "../../assets/logo-acierto.png";
import { Btn } from "../../shared/components/atoms";
import { C } from "../../shared/utils/format";

export default function CrearCuenta({ onRegistro, onIrALogin, onIrAHome, subtitulo = "Crea tu cuenta", plan }) {
  const [nombreNegocio, setNombreNegocio] = useState("");
  const [nombre, setNombre] = useState("");
  const [email, setEmail] = useState("");
  const [rfcPersonal, setRfcPersonal] = useState("");
  const [usuario, setUsuario] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const submit = async e => {
    e.preventDefault(); setLoading(true); setError(null);
    const r = await onRegistro(nombreNegocio, email, rfcPersonal, password, nombre, usuario, plan);
    setLoading(false);
    if (!r.ok) setError(r.error);
  };
  const field = (id, label, value, setValue, options = {}) => (
    <div style={{marginBottom:14,width:"100%"}}>
      <label htmlFor={id} style={{fontSize:13,color:"rgba(255,255,255,.78)",display:"block",marginBottom:5}}>{label}</label>
      <input id={id} type={options.type || "text"} required minLength={options.minLength} maxLength={options.maxLength} autoFocus={options.autoFocus} value={value} onChange={e=>setValue(options.upper ? e.target.value.toUpperCase() : e.target.value)} placeholder={options.placeholder} style={{width:"100%",border:"1px solid rgba(255,255,255,.2)",borderRadius:8,padding:"11px 12px",fontSize:16,color:C.text,background:"#fff",boxSizing:"border-box"}}/>
    </div>
  );
  return (
    <div style={{minHeight:"100dvh",display:"flex",alignItems:"center",justifyContent:"center",background:"linear-gradient(135deg,#071c31 0%,#0A2540 54%,#104d5d 100%)",padding:20,boxSizing:"border-box"}}>
      <form onSubmit={submit} style={{background:C.primary,padding:"28px 22px",borderRadius:12,width:340,maxWidth:"100%",boxShadow:"0 16px 40px rgba(0,0,0,.22)",border:"1px solid rgba(255,255,255,.14)",display:"flex",flexDirection:"column",alignItems:"center",boxSizing:"border-box"}}>
        <div style={{alignSelf:"stretch",display:"flex",justifyContent:"flex-end",marginBottom:18,position:"relative"}}>
          <button type="button" aria-label={menuOpen ? "Cerrar menú" : "Abrir menú"} aria-expanded={menuOpen} onClick={()=>setMenuOpen(!menuOpen)} style={{width:42,height:38,border:"1px solid rgba(255,255,255,.34)",borderRadius:8,background:"rgba(255,255,255,.08)",color:"#fff",fontSize:22,lineHeight:1,cursor:"pointer"}}>{menuOpen ? "×" : "☰"}</button>
          {menuOpen && <nav aria-label="Menú principal" style={{position:"absolute",top:46,right:0,zIndex:2,minWidth:170,padding:8,display:"grid",gap:6,background:C.card,border:`1px solid ${C.border}`,borderRadius:8,boxShadow:"0 14px 30px rgba(0,0,0,.24)"}}>
            <Btn type="button" onClick={()=>{setMenuOpen(false);onIrAHome();}} style={{width:"100%"}}>Inicio</Btn>
            <Btn type="button" variant="secondary" onClick={()=>{setMenuOpen(false);onIrALogin();}} style={{width:"100%"}}>Iniciar sesión</Btn>
          </nav>}
        </div>
        <img src={logoAcierto} alt="Acierto" style={{width:170,height:170,objectFit:"contain",mixBlendMode:"screen",marginBottom:14}}/>
        <div style={{fontSize:14,color:"rgba(255,255,255,.72)",marginBottom:22,textAlign:"center"}}>{subtitulo}</div>
        {field("reg-negocio","Nombre del negocio",nombreNegocio,setNombreNegocio,{autoFocus:true})}
        {field("reg-nombre","Tu nombre",nombre,setNombre)}
        {field("reg-email","Email",email,setEmail,{type:"email"})}
        {field("reg-rfc","RFC",rfcPersonal,setRfcPersonal,{maxLength:13,upper:true,placeholder:"AAAA000101AAA"})}
        {field("reg-usuario","Usuario",usuario,setUsuario,{minLength:6,maxLength:10,upper:true,placeholder:"6-10 caracteres"})}
        {field("reg-password","Contraseña",password,setPassword,{type:"password",minLength:8})}
        {error && <div style={{fontSize:12,color:C.danger,marginBottom:14,padding:"8px 10px",background:C.dangerSoft,borderRadius:6,width:"100%",boxSizing:"border-box"}}>⚠ {error}</div>}
        <Btn variant="accent" style={{width:"100%",padding:"12px 18px"}} disabled={loading}>{loading ? "Creando cuenta…" : "Crear cuenta"}</Btn>
        <button type="button" onClick={onIrALogin} style={{marginTop:14,background:"none",border:"none",color:C.textSec,fontSize:12,cursor:"pointer",textDecoration:"underline"}}>¿Ya tienes cuenta? Inicia sesión</button>
      </form>
    </div>
  );
}
