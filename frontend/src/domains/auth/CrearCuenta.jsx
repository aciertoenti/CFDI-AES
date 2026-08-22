import { useState } from "react";
import logoAcierto from "../../assets/logo-acierto.png";
import { Btn } from "../../shared/components/atoms";
import { C } from "../../shared/utils/format";

export default function CrearCuenta({ onRegistro, onIrALogin }) {
  const [nombreNegocio, setNombreNegocio] = useState("");
  const [nombre, setNombre] = useState("");
  const [email, setEmail] = useState("");
  const [rfcPersonal, setRfcPersonal] = useState("");
  const [usuario, setUsuario] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const submit = async e => {
    e.preventDefault(); setLoading(true); setError(null);
    const r = await onRegistro(nombreNegocio, email, rfcPersonal, password, nombre, usuario);
    setLoading(false);
    if (!r.ok) setError(r.error);
  };
  const field = (id, label, value, setValue, options = {}) => (
    <div style={{marginBottom:14,width:"100%"}}>
      <label htmlFor={id} style={{fontSize:13,color:C.textSec,display:"block",marginBottom:5}}>{label}</label>
      <input id={id} type={options.type || "text"} required minLength={options.minLength} maxLength={options.maxLength} autoFocus={options.autoFocus} value={value} onChange={e=>setValue(options.upper ? e.target.value.toUpperCase() : e.target.value)} placeholder={options.placeholder} style={{width:"100%",border:`1px solid ${C.border}`,borderRadius:8,padding:"11px 12px",fontSize:16,color:C.text,boxSizing:"border-box"}}/>
    </div>
  );
  return (
    <div style={{minHeight:"100dvh",display:"flex",alignItems:"center",justifyContent:"center",background:C.surface,padding:20,boxSizing:"border-box"}}>
      <form onSubmit={submit} style={{background:C.card,padding:"28px 22px",borderRadius:12,width:340,maxWidth:"100%",boxShadow:"0 4px 24px rgba(0,0,0,.08)",border:`1px solid ${C.border}`,display:"flex",flexDirection:"column",alignItems:"center",boxSizing:"border-box"}}>
        <img src={logoAcierto} alt="Acierto" style={{width:120,maxWidth:"60%",borderRadius:8,display:"block",marginBottom:14}}/>
        <div style={{fontSize:14,color:C.textSec,marginBottom:22,textAlign:"center"}}>Crea tu cuenta</div>
        {field("reg-negocio","Nombre del negocio",nombreNegocio,setNombreNegocio,{autoFocus:true})}
        {field("reg-nombre","Tu nombre",nombre,setNombre)}
        {field("reg-email","Email",email,setEmail,{type:"email"})}
        {field("reg-rfc","RFC",rfcPersonal,setRfcPersonal,{maxLength:13,upper:true,placeholder:"AAAA000101AAA"})}
        {field("reg-usuario","Usuario",usuario,setUsuario,{minLength:6,maxLength:10,upper:true,placeholder:"6-10 caracteres"})}
        {field("reg-password","Contraseña",password,setPassword,{type:"password",minLength:8})}
        {error && <div style={{fontSize:12,color:C.danger,marginBottom:14,padding:"8px 10px",background:C.dangerSoft,borderRadius:6,width:"100%",boxSizing:"border-box"}}>⚠ {error}</div>}
        <Btn style={{width:"100%",padding:"12px 18px"}} disabled={loading}>{loading ? "Creando cuenta…" : "Crear cuenta"}</Btn>
        <button type="button" onClick={onIrALogin} style={{marginTop:14,background:"none",border:"none",color:C.textSec,fontSize:12,cursor:"pointer",textDecoration:"underline"}}>¿Ya tienes cuenta? Inicia sesión</button>
      </form>
    </div>
  );
}
