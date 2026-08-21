import { C } from "../../shared/utils/format";

export function SectionTitle({children}) { return <h2 style={{fontSize:20,fontWeight:700,color:C.text,marginBottom:4}}>{children}</h2>; }
export function SectionSub({children}) { return <p style={{color:C.textSec,fontSize:13,marginBottom:18,marginTop:2}}>{children}</p>; }
