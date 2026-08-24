import { useState } from "react";
import logoAcierto from "../../assets/logo-acierto.png";
import useBreakpoint from "../hooks/useBreakpoint";
import useEmisores from "../hooks/useEmisores";
import { C } from "../utils/format";

export function Placeholder({title,detail}){
  return (
    <div style={{display:"flex",flexDirection:"column",alignItems:"center",justifyContent:"center",height:260,color:C.textMuted,padding:"0 16px",textAlign:"center"}}>
      <div style={{fontSize:36,marginBottom:12}}>🚧</div>
      <div style={{fontSize:15,fontWeight:600,color:C.textSec}}>{title}</div>
      <div style={{fontSize:12,marginTop:5}}>{detail || "Conecta el microservicio para habilitar esta vista"}</div>
    </div>
  );
}

export function SidebarNav({active,navigate,expanded,toggle,compact=false,nav,labels}){
  return (
    <>
      <div style={{padding:compact?"14px 0 12px":"20px 18px 14px",borderBottom:"1px solid rgba(255,255,255,.08)",textAlign:compact?"center":"left"}}>
        {compact
          ? <img src={logoAcierto} alt="Acierto" style={{width:28,height:28,borderRadius:6,display:"inline-block"}}/>
          : <>
              <img src={logoAcierto} alt="Acierto" style={{width:110,maxWidth:"100%",borderRadius:6,display:"block"}}/>
              <div style={{fontSize:13,fontWeight:600,color:"rgba(255,255,255,.9)",marginTop:6}}>Portal Inteligente</div>
            </>
        }
      </div>
      <nav style={{flex:1,padding:"8px 0",overflowY:"auto"}}>
        {nav.map(item=>(
          <div key={item.id}>
            <div onClick={()=>{if(item.children.length)toggle(item.id);else navigate(item.id);}}
              style={{display:"flex",alignItems:"center",gap:compact?0:9,padding:compact?"10px 0":"9px 18px",justifyContent:compact?"center":"flex-start",cursor:"pointer",color:"rgba(255,255,255,.7)",fontSize:13,fontWeight:600,userSelect:"none"}}>
              <span style={{fontSize:compact?18:15}}>{item.icon}</span>
              {!compact&&<span style={{flex:1}}>{item.label}</span>}
              {!compact&&item.id==="ia"&&<span style={{fontSize:9,padding:"2px 6px",borderRadius:8,background:"rgba(0,200,150,.2)",color:C.accent}}>IA</span>}
              {!compact&&item.children.length>0&&<span style={{fontSize:10,opacity:.5}}>{expanded[item.id]?"▾":"▸"}</span>}
            </div>
            {!compact&&item.id==="addenda"&&(
              <div onClick={()=>navigate("addenda")}
                style={{padding:"6px 18px 6px 38px",cursor:"pointer",fontSize:13,color:active==="addenda"?C.accent:"rgba(255,255,255,.55)",background:active==="addenda"?"rgba(0,200,150,.1)":"transparent",borderLeft:active==="addenda"?`2px solid ${C.accent}`:"2px solid transparent"}}>
                Addenda AES
              </div>
            )}
            {!compact&&expanded[item.id]&&item.children.map(child=>(
              <div key={child} onClick={()=>navigate(child)}
                style={{padding:"6px 18px 6px 38px",cursor:"pointer",fontSize:13,color:active===child?C.accent:"rgba(255,255,255,.55)",background:active===child?"rgba(0,200,150,.1)":"transparent",borderLeft:active===child?`2px solid ${C.accent}`:"2px solid transparent",transition:"all .15s"}}>
                {labels[child]}
              </div>
            ))}
          </div>
        ))}
      </nav>
      {!compact&&(
        <div style={{padding:"12px 18px",borderTop:"1px solid rgba(255,255,255,.08)"}}>
          <div style={{fontSize:10,color:"rgba(255,255,255,.3)"}}>v2.0 · 6 microservicios</div>
          <div style={{display:"flex",gap:4,marginTop:5,flexWrap:"wrap"}}>
            {["Facturación","Admin","IA","Auth"].map(s=>(
              <span key={s} style={{fontSize:9,padding:"2px 6px",borderRadius:6,background:"rgba(0,200,150,.15)",color:C.accent}}>{s}</span>
            ))}
          </div>
        </div>
      )}
    </>
  );
}

export default function AppShell({onLogout,onCambiarPassword,usuarioActual,views,labels,nav}){
  const {isMobile,isTablet}=useBreakpoint();
  const [active,setActive]=useState("generadas");
  const [expanded,setExpanded]=useState({facturas:true,ia:true,admin:false});
  const [drawerOpen,setDrawerOpen]=useState(false);
  const [mostrarPasswordModal,setMostrarPasswordModal]=useState(false);
  const [passwordActual,setPasswordActual]=useState("");
  const [nuevaPassword,setNuevaPassword]=useState("");
  const [confirmarPassword,setConfirmarPassword]=useState("");
  const [passwordError,setPasswordError]=useState(null);
  const [passwordLoading,setPasswordLoading]=useState(false);
  const [passwordSuccess,setPasswordSuccess]=useState(null);
  const toggle=id=>setExpanded(e=>({...e,[id]:!e[id]}));
  const navigate=id=>{setActive(id);setDrawerOpen(false);};
  const {emisores,loading:cargandoEmisor,emisorActivoRfc,setEmisorActivoRfc}=useEmisores();
  const emisorActual=emisores.find(e=>e.rfc===emisorActivoRfc)??emisores[0];
  const nombreEmisor=cargandoEmisor?"Cargando…":(emisorActual?.razon_social||"Sin emisor registrado");
  const inicialesEmisor=emisorActual?.razon_social
    ? emisorActual.razon_social.split(" ").filter(Boolean).slice(0,2).map(w=>w[0].toUpperCase()).join("")
    : "—";
  const sidebarW = isMobile ? 0 : isTablet ? 52 : 232;

  const submitCambiarPassword = async e => {
    e.preventDefault();
    setPasswordError(null); setPasswordSuccess(null);
    if (!passwordActual || !nuevaPassword || !confirmarPassword) {
      setPasswordError("Completa todos los campos.");
      return;
    }
    if (nuevaPassword.length < 8) {
      setPasswordError("La nueva contraseña debe tener al menos 8 caracteres.");
      return;
    }
    if (nuevaPassword !== confirmarPassword) {
      setPasswordError("La confirmación no coincide con la nueva contraseña.");
      return;
    }
    setPasswordLoading(true);
    const r = await onCambiarPassword(passwordActual, nuevaPassword);
    setPasswordLoading(false);
    if (!r.ok) {
      setPasswordError(r.error);
      return;
    }
    setPasswordSuccess(r.mensaje || "Contraseña actualizada correctamente.");
    setPasswordActual(""); setNuevaPassword(""); setConfirmarPassword("");
    setTimeout(() => setMostrarPasswordModal(false), 900);
  };

  return (
    <div style={{display:"flex",height:"100dvh",fontFamily:"'Inter',system-ui,sans-serif",background:C.surface,color:C.text,overflow:"hidden"}}>
      {isMobile&&drawerOpen&&(
        <div style={{position:"fixed",inset:0,zIndex:100,display:"flex"}}>
          <div style={{position:"absolute",inset:0,background:"rgba(0,0,0,.5)"}} onClick={()=>setDrawerOpen(false)}/>
          <aside style={{width:240,background:C.primary,display:"flex",flexDirection:"column",position:"relative",zIndex:1,flexShrink:0}}>
            <SidebarNav active={active} navigate={navigate} expanded={expanded} toggle={toggle} compact={false} nav={nav} labels={labels}/>
          </aside>
        </div>
      )}
      {!isMobile&&(
        <aside style={{width:sidebarW,background:C.primary,display:"flex",flexDirection:"column",flexShrink:0,transition:"width .2s"}}>
          <SidebarNav active={active} navigate={navigate} expanded={expanded} toggle={toggle} compact={isTablet} nav={nav} labels={labels}/>
        </aside>
      )}
      <main style={{flex:1,display:"flex",flexDirection:"column",overflow:"hidden",minWidth:0}}>
        <header style={{background:C.card,borderBottom:`1px solid ${C.border}`,padding:isMobile?"10px 14px":"12px 24px",display:"flex",alignItems:"center",justifyContent:"space-between",flexShrink:0,gap:8}}>
          <div style={{display:"flex",alignItems:"center",gap:10,minWidth:0}}>
            {isMobile&&(
              <button onClick={()=>setDrawerOpen(true)} aria-label="Abrir menú"
                style={{background:"transparent",border:"none",cursor:"pointer",fontSize:20,color:C.text,padding:0,lineHeight:1,flexShrink:0}}>☰</button>
            )}
            <div style={{minWidth:0}}>
              <div style={{fontSize:10,color:C.textMuted,overflow:"hidden",textOverflow:"ellipsis",whiteSpace:"nowrap"}}>Conectado como {usuarioActual?.nombre||usuarioActual?.sub||"—"}</div>
              <div style={{fontSize:isMobile?13:14,fontWeight:600,color:C.text,overflow:"hidden",textOverflow:"ellipsis",whiteSpace:"nowrap"}}>{nombreEmisor}</div>
            </div>
          </div>
          <div style={{display:"flex",gap:10,alignItems:"center",flexShrink:0}}>
            {!isMobile&&(emisores.length>1
              ? (
                <select value={emisorActivoRfc||""} onChange={e=>setEmisorActivoRfc(e.target.value)}
                  style={{fontSize:11,color:C.textMuted,background:"transparent",border:`1px solid ${C.border}`,borderRadius:6,padding:"3px 6px",maxWidth:220,cursor:"pointer"}}>
                  {emisores.map(e=>(<option key={e.rfc} value={e.rfc}>{e.razon_social} — {e.rfc}</option>))}
                </select>
              )
              : <div style={{fontSize:11,color:C.textMuted,whiteSpace:"nowrap"}}>Emisor: {cargandoEmisor?"…":(emisorActual?.rfc||"—")}</div>
            )}
            <div style={{position:"relative"}}>
              <div style={{width:7,height:7,borderRadius:"50%",background:C.danger,position:"absolute",top:-1,right:-1,border:"2px solid #fff"}}/>
              <span style={{fontSize:17,cursor:"pointer"}}>🔔</span>
            </div>
            <div style={{width:30,height:30,borderRadius:"50%",background:C.primary,display:"flex",alignItems:"center",justifyContent:"center",color:C.accent,fontWeight:700,fontSize:11,flexShrink:0}}>{inicialesEmisor}</div>
            <button onClick={()=>setMostrarPasswordModal(true)} title="Cambiar contraseña"
              style={{background:"transparent",border:`1px solid ${C.border}`,borderRadius:8,padding:"6px 10px",fontSize:12,color:C.textSec,cursor:"pointer",flexShrink:0}}>Cambiar contraseña</button>
            <button onClick={onLogout} title="Cerrar sesión"
              style={{background:"transparent",border:`1px solid ${C.border}`,borderRadius:8,padding:"6px 10px",fontSize:12,color:C.textSec,cursor:"pointer",flexShrink:0}}>Salir</button>
          </div>
        </header>
        {isMobile&&(
          <div style={{display:"flex",background:C.primary,borderTop:"1px solid rgba(255,255,255,.1)",flexShrink:0,order:1}}>
            {[["generadas","📄","Facturas"],["lector","📥","Lector IA"],["chat","🤖","Chat IA"],["clientes","👥","Clientes"]].map(([id,ic,lbl])=>(
              <button key={id} onClick={()=>navigate(id)}
                style={{flex:1,background:"transparent",border:"none",cursor:"pointer",padding:"7px 2px",display:"flex",flexDirection:"column",alignItems:"center",gap:2}}>
                <span style={{fontSize:17}}>{ic}</span>
                <span style={{fontSize:9,color:active===id?C.accent:"rgba(255,255,255,.45)",fontWeight:active===id?700:400}}>{lbl}</span>
              </button>
            ))}
          </div>
        )}
        <div style={{flex:1,overflowY:"auto",padding:isMobile?"14px 12px":"22px 26px",WebkitOverflowScrolling:"touch",order:0}}>
          {views[active]||<Placeholder title={labels[active]}/>} 
        </div>
        {mostrarPasswordModal && (
          <div style={{position:"fixed",inset:0,background:"rgba(3,6,18,.5)",display:"flex",alignItems:"center",justifyContent:"center",zIndex:120}} onClick={()=>setMostrarPasswordModal(false)}>
            <div style={{width:380,maxWidth:"calc(100vw - 24px)",background:C.card,borderRadius:12,padding:22,border:`1px solid ${C.border}`,boxShadow:"0 22px 60px rgba(0,0,0,.35)",position:"relative"}} onClick={e=>e.stopPropagation()}>
              <button type="button" onClick={()=>setMostrarPasswordModal(false)} style={{position:"absolute",top:12,right:12,background:"transparent",border:"none",fontSize:20,color:C.textMuted,cursor:"pointer"}}>×</button>
              <div style={{fontSize:18,fontWeight:700,color:C.text,marginBottom:18}}>Cambiar contraseña</div>
              <form onSubmit={submitCambiarPassword} style={{display:"grid",gap:12}}>
                <div>
                  <label style={{display:"block",fontSize:12,color:C.textSec,marginBottom:6}}>Contraseña actual</label>
                  <input type="password" value={passwordActual} onChange={e=>setPasswordActual(e.target.value)} style={{width:"100%",boxSizing:"border-box",padding:"10px 12px",border:`1px solid ${C.border}`,borderRadius:8,fontSize:14,color:C.text}} />
                </div>
                <div>
                  <label style={{display:"block",fontSize:12,color:C.textSec,marginBottom:6}}>Nueva contraseña</label>
                  <input type="password" value={nuevaPassword} onChange={e=>setNuevaPassword(e.target.value)} style={{width:"100%",boxSizing:"border-box",padding:"10px 12px",border:`1px solid ${C.border}`,borderRadius:8,fontSize:14,color:C.text}} />
                </div>
                <div>
                  <label style={{display:"block",fontSize:12,color:C.textSec,marginBottom:6}}>Confirmar contraseña</label>
                  <input type="password" value={confirmarPassword} onChange={e=>setConfirmarPassword(e.target.value)} style={{width:"100%",boxSizing:"border-box",padding:"10px 12px",border:`1px solid ${C.border}`,borderRadius:8,fontSize:14,color:C.text}} />
                </div>
                {passwordError && <div style={{fontSize:12,color:C.danger,background:C.dangerSoft,padding:"8px 10px",borderRadius:6}}>{passwordError}</div>}
                {passwordSuccess && <div style={{fontSize:12,color:C.accent,background:"rgba(0,200,150,.08)",padding:"8px 10px",borderRadius:6}}>{passwordSuccess}</div>}
                <button type="submit" disabled={passwordLoading} style={{padding:"12px 16px",borderRadius:8,border:"none",background:C.accent,color:"#fff",fontWeight:700,cursor:"pointer",opacity:passwordLoading?0.7:1}}>
                  {passwordLoading ? "Guardando…" : "Actualizar contraseña"}
                </button>
              </form>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
