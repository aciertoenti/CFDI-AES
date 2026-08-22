import { useToast } from "../../shared/layout/ToastProvider";
import useClientes from "../../shared/hooks/useClientes";
import { API_BASE } from "../../shared/hooks/fetchAuth";
import { Btn, Card, TwoCol, SectionTitle } from "../../shared/components/atoms";
import { C, fmt } from "../../shared/utils/format";
import { Placeholder } from "../../shared/layout/AppShell";

export default function Clientes() {
  const toast = useToast();
  const { clientes, loading, error } = useClientes();
  if (error) return <Placeholder title="Clientes" detail={`No se pudo conectar con administracion: ${error}`} />;
  if (loading) return <Placeholder title="Clientes" detail="Cargando datos reales…" />;
  if (clientes.length === 0) return <Placeholder title="Clientes" detail="Todavía no hay clientes registrados." />;
  return <div>
    <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:16,flexWrap:"wrap",gap:10}}>
      <SectionTitle>Clientes</SectionTitle>
      <Btn onClick={() => toast(`POST ${API_BASE}/admin/clientes`, "api")}>+ Nuevo cliente</Btn>
    </div>
    <TwoCol>{clientes.map(cliente => <Card key={cliente.rfc}>
      <div style={{display:"flex",justifyContent:"space-between",alignItems:"flex-start",marginBottom:10,gap:8}}>
        <div style={{minWidth:0}}><div style={{fontSize:14,fontWeight:600,color:C.text,overflow:"hidden",textOverflow:"ellipsis",whiteSpace:"nowrap"}}>{cliente.nombre}</div><div style={{fontSize:12,color:C.textMuted,fontFamily:"monospace",marginTop:2}}>{cliente.rfc}</div></div>
        <span style={{background:C.accentSoft,color:C.accentBorder,fontSize:11,fontWeight:600,padding:"3px 10px",borderRadius:20,flexShrink:0}}>Activo</span>
      </div>
      <div style={{fontSize:13,color:C.textSec,marginBottom:6,overflow:"hidden",textOverflow:"ellipsis",whiteSpace:"nowrap"}}>✉ {cliente.email || "—"}</div>
      <div style={{fontSize:13,color:C.textSec}}>Crédito: <strong style={{color:C.text}}>{fmt(cliente.credito_limite || 0)}</strong></div>
      <div style={{marginTop:12,display:"flex",gap:8,flexWrap:"wrap"}}>
        <button onClick={() => toast(`PUT ${API_BASE}/admin/clientes/${cliente.rfc}`, "api")} style={{fontSize:12,padding:"6px 12px",borderRadius:7,border:`1px solid ${C.border}`,background:"transparent",cursor:"pointer",color:C.textSec}}>Editar</button>
        <button onClick={() => toast(`GET ${API_BASE}/facturas?receptor=${cliente.rfc}`, "api")} style={{fontSize:12,padding:"6px 12px",borderRadius:7,border:`1px solid ${C.accentBorder}`,background:C.accentSoft,cursor:"pointer",color:C.accentBorder}}>Ver facturas</button>
      </div>
    </Card>)}</TwoCol>
  </div>;
}
