"use client";
import { useRouter } from "next/navigation";
export default function Home() {
  const router = useRouter();
  return (
    <main style={{minHeight:"100vh",background:"#dce3ed",display:"flex",alignItems:"center",justifyContent:"center"}}>
      <div style={{textAlign:"center",fontFamily:"Courier New, monospace"}}>
        <div style={{fontSize:48,fontWeight:700,color:"#16a34a",letterSpacing:4,marginBottom:12}}>NETSIM</div>
        <div style={{color:"#334155",marginBottom:6}}>5-Layer Network Simulator</div>
        <div style={{color:"#475569",fontSize:12,marginBottom:32}}>6th Semester Computer Networks Course</div>
        <button
          onClick={() => router.push("/simulator")}
          style={{background:"#22c55e",color:"#000",border:"none",borderRadius:6,padding:"10px 28px",fontSize:14,fontWeight:700,cursor:"pointer",fontFamily:"Courier New, monospace",letterSpacing:1}}
        >
          ▶ LAUNCH SIMULATOR
        </button>
      </div>
    </main>
  );
}
