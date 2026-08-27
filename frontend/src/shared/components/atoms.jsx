import { C } from "../utils/format";

export function Badge({estado}){
  const map={Vigente:{bg:"#E6FAF5",c:"#0A6B4A"},Vencida:{bg:"#FFF5F5",c:"#9B2C2C"},
    Cancelada:{bg:"#FFF5F5",c:"#9B2C2C"},Pendiente:{bg:"#FFFAF0",c:"#744210"},Alerta:{bg:"#FFFAF0",c:"#744210"}};
  const s=map[estado]||map.Pendiente;
  return <span style={{background:s.bg,color:s.c,fontSize:11,fontWeight:600,padding:"3px 10px",borderRadius:20,whiteSpace:"nowrap"}}>{estado}</span>;
}
export function Card({children,style={},onClick}){
  return <div style={{background:C.card,border:`1px solid ${C.border}`,borderRadius:12,padding:16,minWidth:0,maxWidth:"100%",boxSizing:"border-box",...style}} onClick={onClick}>{children}</div>;
}
export function Btn({children,variant="primary",onClick,style={},disabled,type="submit"}){
  const base={borderRadius:8,padding:"10px 18px",fontSize:13,fontWeight:600,cursor:disabled?"not-allowed":"pointer",border:"none",opacity:disabled?.5:1,...style};
  const s={primary:{...base,background:C.primary,color:C.accent},secondary:{...base,background:"transparent",color:C.textSec,border:`1px solid ${C.border}`},accent:{...base,background:C.accent,color:"#fff"}};
  return <button type={type} disabled={disabled} aria-disabled={disabled} style={s[variant]||s.primary} onClick={disabled?undefined:onClick}>{children}</button>;
}
export function TwoCol({children,minCol=260}){return <div style={{display:"grid",gridTemplateColumns:`repeat(auto-fit,minmax(${minCol}px,1fr))`,gap:12,minWidth:0,width:"100%"}}>{children}</div>;}
export function KPIGrid({children}){return <div style={{display:"grid",gridTemplateColumns:"repeat(auto-fit,minmax(120px,1fr))",gap:10,marginBottom:16,minWidth:0,width:"100%"}}>{children}</div>;}
export function KPI({label,value,sub,dark}){
  return (
    <div style={{background:dark?C.primary:C.card,border:`1px solid ${dark?"transparent":C.border}`,borderRadius:12,padding:"14px 14px",minWidth:0,maxWidth:"100%",boxSizing:"border-box"}}>
      <div style={{fontSize:10,color:dark?"rgba(255,255,255,.5)":C.textMuted,marginBottom:5,textTransform:"uppercase",letterSpacing:"0.06em",overflowWrap:"anywhere",wordBreak:"break-word",whiteSpace:"normal"}}>{label}</div>
      <div style={{fontSize:22,fontWeight:700,color:dark?C.accent:C.text,lineHeight:1,overflowWrap:"anywhere",wordBreak:"break-word",whiteSpace:"nowrap"}}>{value}</div>
      {sub&&<div style={{fontSize:11,color:dark?"rgba(255,255,255,.4)":C.textMuted,marginTop:3}}>{sub}</div>}
    </div>
  );
}

export function SectionTitle({children}){return <h2 style={{fontSize:20,fontWeight:700,color:C.text,marginBottom:4}}>{children}</h2>;}
export function SectionSub({children}){return <p style={{color:C.textSec,fontSize:13,marginBottom:18,marginTop:2}}>{children}</p>;}
