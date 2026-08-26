import { useState } from "react";
import logoAcierto from "../../assets/logo-acierto.png";
import { Btn, Card } from "../../shared/components/atoms";
import { C, fmt } from "../../shared/utils/format";

const PLANS = [
  {
    id: "emprendedor",
    name: "Emprendedor@",
    audience: "Persona que empieza a facturar",
    emitters: 1,
    invoices: 10,
    monthly: 399,
    description: "Para comenzar a facturar con lo esencial y acompañamiento cercano.",
    features: ["1 usuario administrador", "Hasta 10 facturas al mes", "CFDI 4.0 estándar", "Soporte por WhatsApp"],
    featured: true,
  },
  {
    id: "basico",
    name: "Básico",
    audience: "Persona física / micro negocio",
    emitters: 1,
    invoices: 50,
    monthly: 799,
    description: "Para emitir CFDI con una operación sencilla y ordenada.",
    features: ["1 usuario administrador", "Hasta 50 facturas al mes", "CFDI 4.0 estándar", "Soporte por WhatsApp"],
  },
  {
    id: "contador",
    name: "Contador",
    audience: "Contador independiente con cartera pequeña",
    emitters: 5,
    invoices: 100,
    monthly: 1490,
    description: "Para administrar varios emisores desde un mismo espacio.",
    features: ["Hasta 100 facturas al mes", "20 facturas por emisor al mes", "3 a 5 usuarios", "Selector rápido de RFC", "Exportaciones básicas", "Soporte por WhatsApp"],
  },
  {
    id: "despacho",
    name: "Despacho",
    audience: "Despacho contable PyME",
    emitters: 10,
    invoices: 500,
    monthly: 2990,
    description: "Para equipos que necesitan control y operación multiempresa.",
    features: ["Hasta 500 facturas al mes", "50 facturas por emisor al mes", "Usuarios y roles", "Reportes consolidados por emisor", "Plantillas y catálogos avanzados", "Onboarding asistido y SLA"],
  },
];

export default function PlanesLanding({ onIrALogin, onIrARegistro, onIrAPrueba, onElegirPlan }) {
  const [annual, setAnnual] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const selectPlan = plan => onElegirPlan(plan.id, annual ? "annual" : "monthly");
  return (
    <main style={{minHeight:"100dvh",background:"linear-gradient(135deg,#071c31 0%,#0A2540 54%,#104d5d 100%)",color:"#fff",padding:"28px 20px 56px",boxSizing:"border-box"}}>
      <div style={{maxWidth:1160,margin:"0 auto"}}>
        <header style={{display:"flex",alignItems:"center",justifyContent:"flex-start",marginBottom:32,position:"relative"}}>
          <button type="button" aria-label={menuOpen ? "Cerrar menú" : "Abrir menú"} aria-expanded={menuOpen} onClick={()=>setMenuOpen(!menuOpen)} style={{width:46,height:42,border:"1px solid rgba(255,255,255,.34)",borderRadius:8,background:"rgba(255,255,255,.08)",color:"#fff",fontSize:24,lineHeight:1,cursor:"pointer"}}>{menuOpen ? "×" : "☰"}</button>
          {menuOpen && <nav aria-label="Menú principal" style={{position:"absolute",top:52,left:0,zIndex:2,minWidth:190,padding:8,display:"grid",gap:6,background:C.card,border:`1px solid ${C.border}`,borderRadius:8,boxShadow:"0 14px 30px rgba(0,0,0,.24)"}}>
            <Btn type="button" variant="secondary" onClick={()=>{setMenuOpen(false); onIrALogin();}} style={{width:"100%"}}>Iniciar sesión</Btn>
          </nav>}
        </header>

        <section style={{maxWidth:860,margin:"0 auto 42px",textAlign:"center"}}>
          <img src={logoAcierto} alt="Acierto" style={{width:"clamp(132px,32vw,190px)",height:"clamp(132px,32vw,190px)",objectFit:"contain",mixBlendMode:"screen",display:"block",margin:"0 auto 24px"}}/>
          <h1 style={{fontSize:"clamp(36px,6vw,72px)",lineHeight:1.02,margin:"0 0 20px",letterSpacing:0}}>Confianza para crecer sin límites.</h1>
          <p style={{color:C.accent,fontSize:12,fontWeight:700,textTransform:"uppercase",letterSpacing:".14em",margin:"0 0 16px"}}>Desde tu primer RFC hasta la gestión de múltiples cuentas</p>
          <p style={{fontSize:"clamp(16px,2vw,18px)",lineHeight:1.55,color:"rgba(255,255,255,.74)",maxWidth:650,margin:"0 auto"}}>Administra tus facturas emitidas y recibidas mes con mes en tiempo y forma, con un contador virtual desde un chat fiscal con IA, todo en una sola cuenta, mediante planes claros que te permiten crecer sin perder el control.</p>
          <Btn type="button" onClick={onIrALogin} style={{marginTop:24,padding:"13px 24px",maxWidth:"100%"}}>¡Accede ahora a la Facturación Inteligente!</Btn>
        </section>

        <section aria-label="Planes disponibles">
          <div style={{display:"flex",alignItems:"center",justifyContent:"space-between",gap:18,flexWrap:"wrap",marginBottom:18}}>
            <div>
              <h2 style={{fontSize:22,margin:"0 0 5px"}}>Elige cómo quieres operar</h2>
              <p style={{color:"rgba(255,255,255,.58)",margin:0,fontSize:13}}>Planes claros para crecer sin perder el control.</p>
            </div>
            <div role="group" aria-label="Periodicidad de pago" style={{display:"inline-flex",padding:4,border:"1px solid rgba(255,255,255,.22)",borderRadius:10,background:"rgba(255,255,255,.08)"}}>
              <button type="button" onClick={()=>setAnnual(false)} aria-pressed={!annual} style={{border:0,borderRadius:7,padding:"9px 13px",background:annual?"transparent":C.accent,color:annual?"#fff":C.primary,fontWeight:700,cursor:"pointer"}}>Mensual</button>
              <button type="button" onClick={()=>setAnnual(true)} aria-pressed={annual} style={{border:0,borderRadius:7,padding:"9px 13px",background:annual?C.accent:"transparent",color:annual?C.primary:"#fff",fontWeight:700,cursor:"pointer"}}>Anual · 2 meses gratis</button>
            </div>
          </div>

          <div style={{display:"grid",gridTemplateColumns:"repeat(auto-fit,minmax(260px,1fr))",gap:16,alignItems:"stretch",maxWidth:1080,margin:"0 auto"}}>
            {PLANS.map(plan => {
              const price = annual ? plan.monthly * 10 : plan.monthly;
              return <Card key={plan.id} style={{position:"relative",display:"flex",flexDirection:"column",alignItems:"center",textAlign:"center",padding:24,border:plan.featured?`2px solid ${C.accent}`:`1px solid ${C.border}`,boxShadow:plan.featured?"0 16px 40px rgba(0,200,150,.16)":"0 12px 28px rgba(0,0,0,.12)"}}>
                {plan.featured && <span style={{position:"absolute",top:-12,left:20,background:C.accent,color:C.primary,borderRadius:6,padding:"5px 10px",fontSize:11,fontWeight:800,textTransform:"uppercase",letterSpacing:".08em"}}>Más elegido</span>}
                <p style={{color:C.textMuted,fontSize:12,fontWeight:700,textTransform:"uppercase",letterSpacing:".08em",margin:"0 0 10px"}}>{plan.name}</p>
                <h3 style={{fontSize:25,margin:"0 0 8px",color:C.text}}>{plan.audience}</h3>
                <p style={{fontSize:14,lineHeight:1.45,color:C.textSec,minHeight:42,margin:"0 0 20px"}}>{plan.description}</p>
                <div style={{display:"flex",alignItems:"baseline",gap:5,marginBottom:4,flexWrap:"wrap",justifyContent:"center"}}><strong style={{fontSize:35,color:C.text}}>{fmt(price)}</strong><span style={{fontSize:13,color:C.textMuted}}>MXN {annual?"/año":"/mes"} con IVA incluido</span></div>
                <p style={{fontSize:13,color:C.accentBorder,fontWeight:700,margin:"0 0 20px"}}>{plan.emitters} {plan.emitters === 1 ? "emisor" : "emisores"}</p>
                <ul style={{padding:0,margin:"0 0 24px",listStyle:"none",display:"grid",gap:10,flex:1,justifyItems:"start",width:"100%"}}>{plan.features.map(feature=><li key={feature} style={{fontSize:13,color:C.textSec,display:"flex",gap:9,alignItems:"center",textAlign:"left"}}><span aria-hidden="true" style={{color:C.accentBorder,fontWeight:800,flexShrink:0}}>✓</span><span>{feature}</span></li>)}</ul>
                <Btn type="button" variant={plan.featured?"accent":"primary"} onClick={()=>selectPlan(plan)} style={{width:"100%"}}>Elegir {plan.name}</Btn>
              </Card>;
            })}
          </div>
        </section>

      </div>
    </main>
  );
}
