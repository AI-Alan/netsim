"use client";
import { useEffect, useRef, useState, useCallback } from "react";
import { useSimStore } from "@/lib/store";
import { connectWS } from "@/lib/websocket";
import { encodeSignal, ENC_COLORS } from "@/lib/encoding";
import type { DeviceNode, NetworkLink, DeviceType, MediumType } from "@/lib/types";

const BACKEND = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";
const WS_URL  = process.env.NEXT_PUBLIC_WS_URL      ?? "ws://localhost:8000";

/* ── TCP/IP 4-layer model ───────────────────────────────────────────────── */
const TCPIP_LAYERS = [
  { name:"Application", note:"HTTP · DNS · ICMP + Session + Presentation", color:"#f87171", live:false },
  { name:"Transport",   note:"TCP · UDP · ARQ state machine",               color:"#a78bfa", live:false },
  { name:"Network",     note:"IP · Routing · TTL",                          color:"#fbbf24", live:false },
  { name:"Data Link",   note:"Ethernet · MAC · ARQ · CRC",                 color:"#60a5fa", live:true  },
  { name:"Physical",    note:"NRZ · Manchester · AMI · 4B5B",               color:"#34d399", live:true  },
];

const DEVICE_META: Record<DeviceType,{icon:string;color:string;tcpip:number}> = {
  computer:{ icon:"🖥",  color:"#3b82f6", tcpip:4 },
  server:  { icon:"🗄",  color:"#a855f7", tcpip:4 },
  router:  { icon:"📡",  color:"#f59e0b", tcpip:2 },
  switch:  { icon:"🔀",  color:"#14b8a6", tcpip:1 },
  hub:     { icon:"⬡",   color:"#6b7280", tcpip:0 },
  laptop:  { icon:"💻",  color:"#22c55e", tcpip:4 },
};

const LAYER_CLR: Record<string,string> = {
  physical:"#34d399", datalink:"#60a5fa", network:"#fbbf24",
  transport:"#a78bfa", application:"#f87171", engine:"#6b7280",
};

const EVT_LAYER: Record<string,string> = {
  BITS_SENT:"physical", SIGNAL_DRAWN:"physical", BITS_RECEIVED:"physical",
  FRAMING_INFO:"datalink", ERROR_DETECTED:"datalink", ACCESS_CONTROL:"datalink",
  FLOW_CONTROL:"datalink", FRAME_SENT:"datalink", FRAME_RECEIVED:"datalink",
  FRAME_DROPPED:"datalink", ARP_REQUEST:"datalink", ARP_REPLY:"datalink",
  PACKET_SENT:"network", PACKET_RECEIVED:"network", ROUTING_LOOKUP:"network", TTL_EXPIRED:"network",
  SEGMENT_SENT:"transport", SEGMENT_RECEIVED:"transport", TCP_STATE:"transport",
  APP_REQUEST:"application", APP_RESPONSE:"application",
  APP_ENCODING:"application", SESSION_INFO:"application",
};

let idSeq=0, lnkSeq=0;
const randMac=()=>Array.from({length:6},()=>Math.floor(Math.random()*256).toString(16).padStart(2,"0")).join(":");
const delay=(ms:number)=>new Promise(r=>setTimeout(r,ms));
const rgba=(hex:string,a:number)=>{
  const r=parseInt(hex.slice(1,3),16),g=parseInt(hex.slice(3,5),16),b=parseInt(hex.slice(5,7),16);
  return `rgba(${r},${g},${b},${a})`;
};

/* ── resizable panel hook ───────────────────────────────────────────────── */
function useResize(init:number,min:number,max:number,dir:"h"|"v"="h"){
  const [sz,setSz]=useState(init);
  const state=useRef({dragging:false,start:0,startSz:init});
  const handle=useCallback((e:React.MouseEvent)=>{
    e.preventDefault();
    const s=state.current;
    s.dragging=true; s.start=dir==="h"?e.clientX:e.clientY; s.startSz=sz;
    const mv=(ev:MouseEvent)=>{
      if(!s.dragging)return;
      const delta=(dir==="h"?ev.clientX:ev.clientY)-s.start;
      setSz(Math.max(min,Math.min(max,s.startSz+(dir==="h"?-delta:delta))));
    };
    const up=()=>{ s.dragging=false; window.removeEventListener("mousemove",mv); window.removeEventListener("mouseup",up); };
    window.addEventListener("mousemove",mv);
    window.addEventListener("mouseup",up);
  },[sz,min,max,dir]);
  return {sz,handle};
}

export default function SimulatorPage(){
  const {wsConnected,events,clearEvents,setSimRunning,setSession}=useSimStore();

  /* state */
  const [devices,setDevices]=useState<DeviceNode[]>([]);
  const [links,setLinks]=useState<NetworkLink[]>([]);
  const [srcId,setSrcId]=useState<string|null>(null);
  const [dstId,setDstId]=useState<string|null>(null);
  const [running,setRunning]=useState(false);
  const [sessionId]=useState(()=>"sess-"+Date.now());

  /* phy config */
  const [encoding,setEncoding]=useState("Manchester");
  const [medium,setMedium]=useState<MediumType>("wired");
  const [ber,setBer]=useState("0");
  const [msg,setMsg]=useState("Hello NetSim!");

  /* dll config */
  const [framing,setFraming]=useState("variable");
  const [errCtrl,setErrCtrl]=useState("crc32");
  const [macProto,setMacProto]=useState("csma_cd");
  const [flowCtrl,setFlowCtrl]=useState("stop_and_wait");
  const [winSz,setWinSz]=useState(4);
  const [injectErr,setInjectErr]=useState(false);
  const [colProb,setColProb]=useState(0.02);

  /* sim mode */
  const [simMode,setSimMode]=useState<"physical"|"datalink">("datalink");
  const [showDLL,setShowDLL]=useState(false);
  const [activeLayer,setActiveLayer]=useState<string|null>(null);

  /* ui */
  const [draggingType,setDraggingType]=useState<DeviceType|null>(null);
  const [connectFrom,setConnectFrom]=useState<string|null>(null);
  const [pendingMed,setPendingMed]=useState<MediumType>("wired");
  const [mousePos,setMousePos]=useState({x:0,y:0});
  const [ctxMenu,setCtxMenu]=useState<{x:number;y:number;devId:string}|null>(null);
  const [tooltip,setTooltip]=useState<{x:number;y:number;dev:DeviceNode}|null>(null);
  const [animPkt,setAnimPkt]=useState<{x:number;y:number;vis:boolean;layer:string}>({x:0,y:0,vis:false,layer:"physical"});
  const [activeLnk,setActiveLnk]=useState<string|null>(null);
  const [flashDev,setFlashDev]=useState<string|null>(null);
  const [log,setLog]=useState<{t:string;msg:string;layer:string}[]>([]);
  const [logFilter,setLogFilter]=useState("all");
  const [inspectedEvt,setInspectedEvt]=useState<typeof events[0]|null>(null);

  /* panel resize */
  const sidebar=useResize(340,200,580,"h");
  const wavePan=useResize(110,55,260,"v");

  const canvasRef=useRef<HTMLDivElement>(null);
  const waveRef=useRef<HTMLCanvasElement>(null);
  const dragRef=useRef<{id:string;ox:number;oy:number}|null>(null);

  /* init */
  useEffect(()=>{
    setSession(sessionId);
    connectWS(sessionId,WS_URL);
    initTopology();
  },[]);

  useEffect(()=>{
    const bits=toPhyBits(msg,simMode);
    if(bits.length>0) drawWave(bits,encoding);
  },[msg,encoding,simMode]);

  /* flash active layer from WS events */
  useEffect(()=>{
    if(!events.length)return;
    const l=EVT_LAYER[events[0].event_type]||events[0].layer;
    setActiveLayer(l);
    const t=setTimeout(()=>setActiveLayer(null),700);
    return ()=>clearTimeout(t);
  },[events.length]);

  function addLog(message:string,layer="engine"){
    const t=(performance.now()/1000).toFixed(3);
    setLog(p=>[{t,msg:message,layer},...p].slice(0,250));
  }

  function initTopology(){
    const d1=mkDev("computer",130,195); const d2=mkDev("switch",330,195);
    const d3=mkDev("server",530,195);   const d4=mkDev("router",330,370);
    setDevices([d1,d2,d3,d4]);
    setLinks([
      {id:"lnk_1",src:d1.id,dst:d2.id,medium:"wired"},
      {id:"lnk_2",src:d2.id,dst:d3.id,medium:"wired"},
      {id:"lnk_3",src:d2.id,dst:d4.id,medium:"wireless"},
    ]);
    lnkSeq=3;
    setSrcId(d1.id); setDstId(d3.id);
    addLog("Topology loaded — Computer ↔ Switch ↔ Server (wired)","engine");
    addLog("Switch ↔ Router (wireless — dashed orange)","engine");
    addLog("TCP/IP model: Session+Presentation merged into Application","application");
    addLog("Phase 2: Data Link LIVE — configure with ⚙ DLL Config","datalink");
  }

  function mkDev(type:DeviceType,x:number,y:number):DeviceNode{
    const id="dev_"+(++idSeq);
    return {id,type,x,y,layers:DEVICE_META[type].tcpip,
      label:type[0].toUpperCase()+type.slice(1)+"-"+idSeq,
      ip:"192.168.1."+(9+idSeq), mac:randMac()};
  }

  function addLink(s:string,d:string,med:MediumType){
    setLinks(p=>{
      if(p.some(l=>(l.src===s&&l.dst===d)||(l.src===d&&l.dst===s)))return p;
      const sl=getDevL(s,p),dl=getDevL(d,p);
      addLog(`Link: ${sl?.label} ↔ ${dl?.label} [${med}]`,"datalink");
      return [...p,{id:"lnk_"+(++lnkSeq),src:s,dst:d,medium:med}];
    });
  }

  function delDevice(id:string){
    setDevices(p=>p.filter(d=>d.id!==id));
    setLinks(p=>p.filter(l=>l.src!==id&&l.dst!==id));
    if(srcId===id)setSrcId(null);
    if(dstId===id)setDstId(null);
  }

  function getDevL(id:string,devs=devices):DeviceNode|undefined{return devs.find(d=>d.id===id);}

  function getPath(a:string,b:string,lnkList=links):string[]|null{
    const q:string[][]=[[a]],vis=new Set([a]);
    while(q.length){
      const p=q.shift()!,last=p[p.length-1];
      if(last===b)return p;
      lnkList.filter(l=>l.src===last||l.dst===last)
        .map(l=>l.src===last?l.dst:l.src)
        .filter(n=>!vis.has(n))
        .forEach(n=>{vis.add(n);q.push([...p,n]);});
    }return null;
  }

  function canSim(){return !!(srcId&&dstId&&srcId!==dstId&&!running&&getPath(srcId,dstId));}

  function toPhyBits(m:string,mode:string):number[]{
    if(mode==="physical") return m.replace(/[^01]/g,"").split("").map(Number);
    const bytes=m.split("").map(c=>c.charCodeAt(0));
    const bits:number[]=[];
    for(const b of bytes.slice(0,4)) for(let i=7;i>=0;i--) bits.push((b>>i)&1);
    return bits;
  }

  async function simulate(){
    if(!canSim())return;
    const path=getPath(srcId!,dstId!)!;
    setRunning(true); setSimRunning(true); clearEvents();
    const src=getDevL(srcId!)!, dst=getDevL(dstId!)!;
    addLog("━━ Simulation start ━━","engine");
    addLog(`${src.label} → ${dst.label} | mode=${simMode} | ${encoding} | ${medium}`,"engine");

    try{
      const berF=parseFloat(ber);
      const endpoint=simMode==="datalink"?"/api/simulate/datalink":"/api/simulate/physical";
      const body=simMode==="datalink"?{
        session_id:sessionId, src_device_id:srcId!, dst_device_id:dstId!,
        message:msg||"Hello!", framing, error:errCtrl,
        mac_proto:macProto, flow:flowCtrl, encoding, medium,
        medium_kwargs:berF>0?{ber:berF}:{},
        flow_kwargs:(flowCtrl==="go_back_n"||flowCtrl==="selective_repeat")?{window:winSz}:{},
        channel_busy:false, collision_prob:colProb,
        link_error_rate:berF, inject_error:injectErr,
      }:{
        session_id:sessionId, src_device_id:srcId!, dst_device_id:dstId!,
        bit_string:msg.replace(/[^01]/g,""), encoding, medium,
        medium_kwargs:berF>0?{ber:berF}:{},
      };

      const resp=await fetch(BACKEND+endpoint,{method:"POST",
        headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
      if(resp.ok){
        const data=await resp.json();
        addLog(`Backend: ${data.events_emitted} events`,"engine");
        for(const ev of(data.events||[])){
          const l=EVT_LAYER[ev.event_type]||ev.layer||"engine";
          const h=ev.pdu?.headers||{};
          if(h.steps&&Array.isArray(h.steps)){
            for(const s of(h.steps as string[]).slice(0,4)) addLog(`  ${s}`,l);
          } else {
            let detail=ev.event_type;
            if(h.scheme) detail+=` [${h.scheme}]`;
            else if(h.protocol) detail+=` [${h.protocol}]`;
            else if(h.detail) detail+=`: ${h.detail}`;
            addLog(`[${l.toUpperCase().slice(0,3)}] ${detail}`,l);
          }
          await delay(25);
        }
      } else { addLog(`Backend HTTP ${resp.status}`,"engine"); }
    }catch(_){
      addLog("Backend offline — frontend-only animation","engine");
    }

    /* frontend animation */
    const bits=toPhyBits(msg,simMode);
    drawWave(bits,encoding);
    addLog(`[PHY] Signal drawn: ${encoding}`,"physical");

    for(let i=0;i<path.length-1;i++){
      const hs=path[i],hd=path[i+1];
      const lnk=links.find(l=>(l.src===hs&&l.dst===hd)||(l.src===hd&&l.dst===hs));
      if(lnk){ setActiveLnk(lnk.id); await animPkt2(hs,hd,simMode); setActiveLnk(null); }
      const via=getDevL(hd)!;
      addLog(`[PHY] Received at ${via.label}`,"physical");
      if(simMode==="datalink"){
        addLog(`[DLL] ${errCtrl.toUpperCase()} check · ${macProto} · ${flowCtrl}`,"datalink");
      }
      await delay(120);
    }

    addLog(`✓ Delivered to ${dst.label}`,"engine");
    addLog("━━ Complete ━━","engine");
    setFlashDev(dstId!); setTimeout(()=>setFlashDev(null),900);
    setRunning(false); setSimRunning(false);
  }

  async function animPkt2(fromId:string,toId:string,mode:string){
    const from=getDevL(fromId)!, to=getDevL(toId)!;
    const layer=mode==="datalink"?"datalink":"physical";
    for(let i=0;i<=44;i++){
      const f=i/44;
      setAnimPkt({x:from.x+(to.x-from.x)*f, y:from.y+(to.y-from.y)*f, vis:true, layer});
      await delay(11);
    }
    setAnimPkt(p=>({...p,vis:false}));
  }

  function drawWave(bits:number[],enc:string){
    const canvas=waveRef.current; if(!canvas)return;
    const ctx=canvas.getContext("2d")!;
    const W=canvas.width, H=canvas.height;
    ctx.clearRect(0,0,W,H);
    ctx.fillStyle="#080b12"; ctx.fillRect(0,0,W,H);
    /* grid */
    ctx.strokeStyle="#1a2030"; ctx.lineWidth=0.5;
    const bw=W/Math.max(bits.length,1);
    for(let i=0;i<=bits.length;i++){ctx.beginPath();ctx.moveTo(i*bw,0);ctx.lineTo(i*bw,H);ctx.stroke();}
    ctx.beginPath();ctx.moveTo(0,H/2);ctx.lineTo(W,H/2);ctx.stroke();
    /* signal */
    try{
      const samples=encodeSignal(bits,enc);
      const color=(ENC_COLORS as Record<string,string>)[enc]||"#34d399";
      ctx.shadowColor=color; ctx.shadowBlur=8;
      ctx.strokeStyle=color; ctx.lineWidth=2.2;
      ctx.beginPath();
      const pw=W/samples.length, amp=(H/2)-7;
      samples.forEach((s,i)=>{const x=i*pw,y=H/2-s*amp; i===0?ctx.moveTo(x,y):ctx.lineTo(x,y);});
      ctx.stroke(); ctx.shadowBlur=0;
      /* bit labels */
      ctx.fillStyle=color+"66"; ctx.font="9px monospace";
      bits.forEach((b,i)=>ctx.fillText(String(b),(i+0.5)*bw-3,H-3));
      /* legend */
      ctx.fillStyle=color+"99"; ctx.font="bold 10px monospace";
      ctx.fillText(enc,4,13);
    }catch(_){}
  }

  /* mouse events */
  useEffect(()=>{
    const mv=(e:MouseEvent)=>{
      const r=canvasRef.current?.getBoundingClientRect();
      if(r)setMousePos({x:e.clientX-r.left,y:e.clientY-r.top});
      if(dragRef.current){
        const {id,ox,oy}=dragRef.current;
        setDevices(p=>p.map(d=>d.id===id?{...d,x:e.clientX-ox,y:e.clientY-oy}:d));
      }
    };
    const up=()=>{dragRef.current=null;};
    window.addEventListener("mousemove",mv);
    window.addEventListener("mouseup",up);
    return()=>{window.removeEventListener("mousemove",mv);window.removeEventListener("mouseup",up);};
  },[]);

  const filtLog=logFilter==="all"?log:log.filter(e=>e.layer===logFilter);

  /* ── RENDER ─────────────────────────────────────────────────────────── */
  return (
    <div style={{display:"flex",flexDirection:"column",height:"100vh",
      background:"#080b12",color:"#e2e8f0",
      fontFamily:"'JetBrains Mono','Fira Code',monospace",overflow:"hidden"}}>

      {/* ── TOP BAR ── */}
      <div style={{height:48,background:"#0d1117",borderBottom:"1px solid #1a2030",
        display:"flex",alignItems:"center",padding:"0 14px",gap:8,flexShrink:0,zIndex:50}}>

        {/* logo */}
        <div style={{display:"flex",alignItems:"center",gap:6,marginRight:8}}>
          <div style={{width:8,height:8,borderRadius:"50%",background:"#34d399",
            boxShadow:"0 0 10px #34d399"}}/>
          <span style={{color:"#34d399",fontWeight:700,fontSize:15,letterSpacing:3}}>NETSIM</span>
          <span style={{fontSize:9,color:"#1a2030",marginLeft:2}}>v2 · TCP/IP</span>
        </div>
        <Div/>

        {/* mode pills */}
        <span style={{fontSize:10,color:"#374151"}}>Mode:</span>
        {(["physical","datalink"] as const).map(m=>(
          <button key={m} onClick={()=>setSimMode(m)} style={{
            ...pill,
            background:simMode===m?rgba(m==="physical"?"#34d399":"#60a5fa",.15):"transparent",
            borderColor:simMode===m?(m==="physical"?"#34d399":"#60a5fa"):"#1a2030",
            color:simMode===m?(m==="physical"?"#34d399":"#60a5fa"):"#4b5563",
          }}>{m==="physical"?"⚡ PHY":"⚡ PHY + DLL"}</button>
        ))}
        <Div/>

        {/* encoding */}
        <span style={{fontSize:10,color:"#374151"}}>Enc:</span>
        <select value={encoding} onChange={e=>setEncoding(e.target.value)} style={selSt}>
          {["NRZ-L","NRZ-I","Manchester","Differential Manchester","AMI","4B5B"].map(e=>(
            <option key={e}>{e}</option>
          ))}
        </select>

        {/* medium buttons */}
        <span style={{fontSize:10,color:"#374151"}}>Medium:</span>
        <button onClick={()=>setMedium("wired")} style={{
          ...pill,
          background:medium==="wired"?rgba("#3b82f6",.15):"transparent",
          borderColor:medium==="wired"?"#3b82f6":"#1a2030",
          color:medium==="wired"?"#3b82f6":"#4b5563",
        }}>⬛ Wired</button>
        <button onClick={()=>setMedium("wireless")} style={{
          ...pill,
          background:medium==="wireless"?rgba("#f59e0b",.15):"transparent",
          borderColor:medium==="wireless"?"#f59e0b":"#1a2030",
          color:medium==="wireless"?"#f59e0b":"#4b5563",
        }}>〰 Wireless</button>

        {/* BER */}
        <span style={{fontSize:10,color:"#374151"}}>BER:</span>
        <select value={ber} onChange={e=>setBer(e.target.value)} style={{...selSt,width:60}}>
          {[["0","0.0"],["0.01","1%"],["0.05","5%"],["0.1","10%"]].map(([v,l])=>(
            <option key={v} value={v}>{l}</option>
          ))}
        </select>
        <Div/>

        {/* message / bits */}
        <span style={{fontSize:10,color:"#374151"}}>{simMode==="datalink"?"Msg:":"Bits:"}</span>
        <input value={msg}
          onChange={e=>setMsg(simMode==="datalink"
            ?e.target.value.slice(0,40)
            :e.target.value.replace(/[^01]/g,"").slice(0,16))}
          placeholder={simMode==="datalink"?"Hello NetSim!":"10110100"}
          style={{...selSt,width:120,color:"#34d399"}}/>

        {/* DLL config toggle */}
        {simMode==="datalink"&&(
          <button onClick={()=>setShowDLL(p=>!p)} style={{
            ...pill,
            borderColor:showDLL?"#60a5fa":"#1a2030",
            color:showDLL?"#60a5fa":"#4b5563",
            background:showDLL?rgba("#60a5fa",.12):"transparent",
          }}>⚙ DLL Config</button>
        )}
        <Div/>

        {/* send */}
        <button onClick={simulate} disabled={!canSim()} style={{
          background:canSim()?"#34d399":"#1a2030",
          color:canSim()?"#000":"#374151",
          border:"none",borderRadius:6,padding:"5px 20px",
          fontSize:12,fontWeight:700,cursor:canSim()?"pointer":"not-allowed",
          fontFamily:"inherit",transition:"all .15s",
          boxShadow:canSim()?"0 0 14px #34d39955":"none",
        }}>{running?"⏳ RUNNING…":"▶ SIMULATE"}</button>

        <div style={{flex:1}}/>
        <span style={{fontSize:10,color:"#1a2030"}}>
          {connectFrom?`Click device to connect [${pendingMed}]…`:"Drag to place · Right-click to connect/set src-dst"}
        </span>
        <Div/>
        <div style={{display:"flex",alignItems:"center",gap:4,fontSize:10}}>
          <div style={{width:7,height:7,borderRadius:"50%",
            background:wsConnected?"#34d399":"#374151",
            boxShadow:wsConnected?"0 0 6px #34d399":"none"}}/>
          <span style={{color:wsConnected?"#34d399":"#374151"}}>WS</span>
        </div>
      </div>

      {/* ── DLL CONFIG BAR ── */}
      {simMode==="datalink"&&showDLL&&(
        <div style={{background:"#0d1117",borderBottom:"1px solid #1a2030",
          padding:"10px 16px",display:"flex",gap:18,flexWrap:"wrap",flexShrink:0,zIndex:40}}>

          <CfgGroup label="Framing" color="#60a5fa" value={framing} onChange={setFraming} opts={[
            {v:"variable",l:"Variable — Bit-oriented (HDLC / PPP flag stuffing)"},
            {v:"fixed",   l:"Fixed Size (N-byte frames, zero-padded)"},
          ]}/>

          <CfgGroup label="Error Control" color="#f87171" value={errCtrl} onChange={setErrCtrl} opts={[
            {v:"crc32",    l:"CRC-32 (IEEE 802.3 — detects burst ≤32 bit)"},
            {v:"checksum", l:"Checksum-16 (RFC-1071 Internet ones-complement)"},
            {v:"none",     l:"None"},
          ]}/>

          <CfgGroup label="MAC / Access Control" color="#fbbf24" value={macProto} onChange={setMacProto} opts={[
            {v:"csma_cd",       l:"CSMA/CD — Binary Exp. Backoff (Ethernet 802.3)"},
            {v:"csma_ca",       l:"CSMA/CA — DCF + RTS/CTS (WiFi 802.11)"},
            {v:"csma",          l:"CSMA — 1-persistent"},
            {v:"pure_aloha",    l:"Pure ALOHA — transmit any time"},
            {v:"slotted_aloha", l:"Slotted ALOHA — slot-aligned"},
          ]}/>

          <CfgGroup label="Flow Control (ARQ)" color="#a78bfa" value={flowCtrl} onChange={setFlowCtrl} opts={[
            {v:"stop_and_wait",   l:"Stop-and-Wait ARQ (W=1)"},
            {v:"go_back_n",       l:"Go-Back-N ARQ"},
            {v:"selective_repeat",l:"Selective Repeat ARQ"},
          ]}/>

          {(flowCtrl==="go_back_n"||flowCtrl==="selective_repeat")&&(
            <div>
              <div style={{fontSize:10,color:"#a78bfa",letterSpacing:1,marginBottom:5}}>WINDOW SIZE</div>
              <div style={{display:"flex",gap:4}}>
                {[2,4,8,16].map(w=>(
                  <button key={w} onClick={()=>setWinSz(w)} style={{
                    ...pill,padding:"4px 10px",fontSize:11,
                    borderColor:winSz===w?"#a78bfa":"#1a2030",
                    color:winSz===w?"#a78bfa":"#4b5563",
                    background:winSz===w?rgba("#a78bfa",.15):"transparent",
                  }}>{w}</button>
                ))}
              </div>
            </div>
          )}

          <div>
            <div style={{fontSize:10,color:"#6b7280",letterSpacing:1,marginBottom:5}}>OPTIONS</div>
            <div style={{display:"flex",flexDirection:"column",gap:6}}>
              <label style={{fontSize:11,color:injectErr?"#f87171":"#4b5563",
                cursor:"pointer",display:"flex",gap:5,alignItems:"center"}}>
                <input type="checkbox" checked={injectErr} onChange={e=>setInjectErr(e.target.checked)}
                  style={{accentColor:"#f87171"}}/>
                Inject bit error (demo CRC/Checksum detection)
              </label>
              <div style={{display:"flex",alignItems:"center",gap:7}}>
                <span style={{fontSize:10,color:"#4b5563"}}>Collision prob:</span>
                <input type="range" min={0} max={0.5} step={0.01} value={colProb}
                  onChange={e=>setColProb(parseFloat(e.target.value))}
                  style={{width:80,accentColor:"#fbbf24"}}/>
                <span style={{fontSize:11,color:"#fbbf24",width:32}}>{(colProb*100).toFixed(0)}%</span>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ── BODY ── */}
      <div style={{flex:1,display:"flex",overflow:"hidden"}}>

        {/* ── CANVAS COLUMN ── */}
        <div style={{flex:1,display:"flex",flexDirection:"column",overflow:"hidden",minWidth:0}}>

          {/* topology canvas */}
          <div ref={canvasRef}
            style={{flex:1,position:"relative",overflow:"hidden",background:"#080b12",
              cursor:connectFrom?"crosshair":"default"}}
            onDragOver={e=>e.preventDefault()}
            onDrop={e=>{
              e.preventDefault();
              if(!draggingType)return;
              const r=canvasRef.current?.getBoundingClientRect();
              if(!r)return;
              const dev=mkDev(draggingType,e.clientX-r.left,e.clientY-r.top);
              setDevices(p=>{
                const next=[...p,dev];
                if(!srcId)setSrcId(dev.id);
                else if(!dstId)setDstId(dev.id);
                return next;
              });
              addLog(`Placed ${dev.label}`,"engine");
              setDraggingType(null);
            }}
            onClick={()=>{if(connectFrom)setConnectFrom(null); setCtxMenu(null);}}>

            {/* dot grid background */}
            <svg style={{position:"absolute",inset:0,width:"100%",height:"100%",
              opacity:.35,pointerEvents:"none"}}>
              <defs>
                <pattern id="dots" width="24" height="24" patternUnits="userSpaceOnUse">
                  <circle cx="12" cy="12" r="0.8" fill="#1a2030"/>
                </pattern>
              </defs>
              <rect width="100%" height="100%" fill="url(#dots)"/>
            </svg>

            {/* SVG overlay: links + anim */}
            <svg style={{position:"absolute",inset:0,width:"100%",height:"100%",pointerEvents:"none"}}>
              {links.map(lnk=>{
                const s=getDevL(lnk.src),d=getDevL(lnk.dst);
                if(!s||!d)return null;
                const isWired=lnk.medium==="wired";
                const active=lnk.id===activeLnk;
                const clr=active?"#34d399":isWired?"#3b82f6":"#f59e0b";
                const mx=(s.x+d.x)/2, my=(s.y+d.y)/2;
                const angle=Math.atan2(d.y-s.y,d.x-s.x)*180/Math.PI;
                return(
                  <g key={lnk.id}>
                    <line x1={s.x} y1={s.y} x2={d.x} y2={d.y}
                      stroke={clr} strokeWidth={active?3:1.5}
                      strokeDasharray={isWired?"none":"9 5"}
                      opacity={active?1:0.55}
                      style={active?{filter:`drop-shadow(0 0 7px ${clr})`}:{}}/>
                    {/* medium badge */}
                    <g transform={`translate(${mx},${my})`}>
                      <rect x={-22} y={-9} width={44} height={14}
                        rx={4} fill="#0d1117" stroke={clr} strokeWidth={0.8} opacity={0.85}/>
                      <text textAnchor="middle" y={3} fontSize={8}
                        fill={clr} style={{userSelect:"none"}}>
                        {isWired?"⬛ wired":"〰 wifi"}
                      </text>
                    </g>
                  </g>
                );
              })}

              {/* connect preview */}
              {connectFrom&&(()=>{
                const from=getDevL(connectFrom);
                if(!from)return null;
                const clr=pendingMed==="wired"?"#3b82f6":"#f59e0b";
                return(
                  <line x1={from.x} y1={from.y} x2={mousePos.x} y2={mousePos.y}
                    stroke={clr} strokeWidth={1.5}
                    strokeDasharray={pendingMed==="wired"?"none":"9 5"} opacity={0.65}/>
                );
              })()}

              {/* animated packet */}
              {animPkt.vis&&(()=>{
                const clr=LAYER_CLR[animPkt.layer]||"#34d399";
                return(
                  <g transform={`translate(${animPkt.x},${animPkt.y})`}>
                    <circle r={11} fill={clr} opacity={0.92}
                      style={{filter:`drop-shadow(0 0 10px ${clr})`}}/>
                    <text textAnchor="middle" y={4} fontSize={8} fill="#000" fontWeight="bold">
                      {animPkt.layer==="datalink"?"FRM":"BIT"}
                    </text>
                  </g>
                );
              })()}
            </svg>

            {/* device nodes */}
            {devices.map(dev=>{
              const meta=DEVICE_META[dev.type];
              const isSrc=dev.id===srcId, isDst=dev.id===dstId, flash=dev.id===flashDev;
              const bc=isSrc?"#34d399":isDst?"#f87171":meta.color;
              return(
                <div key={dev.id} style={{
                  position:"absolute",left:dev.x-36,top:dev.y-34,width:72,height:68,
                  background:flash?rgba("#34d399",.22):rgba(meta.color,.07),
                  border:`1.5px solid ${bc}`,borderRadius:12,
                  display:"flex",flexDirection:"column",alignItems:"center",justifyContent:"center",
                  cursor:"grab",transition:"background .12s,box-shadow .12s",zIndex:10,userSelect:"none",
                  boxShadow:flash?`0 0 22px ${rgba("#34d399",.55)}`:
                    (isSrc||isDst)?`0 0 10px ${rgba(bc,.35)}`:"none",
                }}
                  onMouseDown={e=>{
                    if(e.button!==0||connectFrom)return;
                    e.stopPropagation();e.preventDefault();
                    dragRef.current={id:dev.id,ox:e.clientX-dev.x,oy:e.clientY-dev.y};
                  }}
                  onClick={e=>{
                    e.stopPropagation();
                    if(connectFrom&&connectFrom!==dev.id){
                      addLink(connectFrom,dev.id,pendingMed);
                      setConnectFrom(null);
                    }
                  }}
                  onContextMenu={e=>{
                    e.preventDefault();e.stopPropagation();
                    const r=canvasRef.current?.getBoundingClientRect();
                    setCtxMenu({x:e.clientX-(r?.left??0),y:e.clientY-(r?.top??0),devId:dev.id});
                  }}
                  onMouseEnter={()=>setTooltip({x:dev.x+40,y:dev.y-40,dev})}
                  onMouseLeave={()=>setTooltip(null)}
                >
                  <div style={{fontSize:24,lineHeight:1}}>{meta.icon}</div>
                  <div style={{fontSize:9,color:"#e2e8f0",marginTop:2,maxWidth:66,
                    overflow:"hidden",textOverflow:"ellipsis",whiteSpace:"nowrap",textAlign:"center"}}>
                    {dev.label}
                  </div>
                  {(isSrc||isDst)&&(
                    <div style={{fontSize:8,color:bc,fontWeight:700}}>{isSrc?"SRC":"DST"}</div>
                  )}
                </div>
              );
            })}

            {/* tooltip */}
            {tooltip&&(
              <div style={{position:"absolute",left:tooltip.x,top:tooltip.y,
                background:"#0d1117",border:"1px solid #1a2030",borderRadius:8,
                padding:"10px 14px",fontSize:11,pointerEvents:"none",zIndex:200,
                lineHeight:1.9,boxShadow:"0 6px 24px #00000099",minWidth:185}}>
                <div style={{color:DEVICE_META[tooltip.dev.type].color,fontWeight:700,marginBottom:3}}>
                  {tooltip.dev.label}
                </div>
                <div style={{color:"#4b5563"}}>Type: <span style={{color:"#e2e8f0"}}>{tooltip.dev.type}</span></div>
                <div style={{color:"#4b5563"}}>IP: <span style={{color:"#60a5fa"}}>{tooltip.dev.ip}</span></div>
                <div style={{color:"#4b5563"}}>MAC: <span style={{color:"#a78bfa",fontSize:10}}>{tooltip.dev.mac}</span></div>
                <div style={{color:"#4b5563"}}>TCP/IP: <span style={{color:"#34d399"}}>layers 0–{tooltip.dev.layers}</span></div>
                {tooltip.dev.id===srcId&&<div style={{color:"#34d399",marginTop:3}}>📤 SOURCE</div>}
                {tooltip.dev.id===dstId&&<div style={{color:"#f87171",marginTop:3}}>📥 DESTINATION</div>}
              </div>
            )}

            {/* context menu */}
            {ctxMenu&&(
              <div style={{position:"absolute",left:ctxMenu.x,top:ctxMenu.y,
                background:"#0d1117",border:"1px solid #1a2030",borderRadius:9,
                padding:4,zIndex:300,minWidth:210,boxShadow:"0 6px 28px #000000aa"}}
                onClick={e=>e.stopPropagation()}>
                <div style={{padding:"3px 10px 5px",color:"#1a2030",fontSize:10,letterSpacing:1}}>
                  CONNECT USING
                </div>
                {([["wired","⬛ Wired (solid blue)","#3b82f6"],
                   ["wireless","〰 Wireless (dashed orange)","#f59e0b"]] as const).map(([m,label,clr])=>(
                  <CtxItem key={m} label={label} color={clr} action={()=>{
                    setPendingMed(m as MediumType);
                    setConnectFrom(ctxMenu.devId);
                    setCtxMenu(null);
                  }}/>
                ))}
                <CtxSep/>
                <CtxItem label="📤 Set as Source" color="#34d399" action={()=>{
                  setSrcId(ctxMenu.devId);
                  addLog(`Source → ${getDevL(ctxMenu.devId)?.label}`,"engine");
                  setCtxMenu(null);
                }}/>
                <CtxItem label="📥 Set as Destination" color="#f87171" action={()=>{
                  setDstId(ctxMenu.devId);
                  addLog(`Dest → ${getDevL(ctxMenu.devId)?.label}`,"engine");
                  setCtxMenu(null);
                }}/>
                <CtxSep/>
                <CtxItem label="✕ Delete Device" color="#ef4444" action={()=>{
                  delDevice(ctxMenu.devId); setCtxMenu(null);
                }} danger/>
              </div>
            )}
          </div>

          {/* ── WAVEFORM PANEL (resizable) ── */}
          <div style={{height:wavePan.sz,background:"#0a0e18",
            borderTop:"1px solid #1a2030",flexShrink:0,position:"relative"}}>
            {/* resize handle */}
            <div onMouseDown={wavePan.handle} style={{
              position:"absolute",top:-4,left:0,right:0,height:8,
              cursor:"ns-resize",zIndex:10,display:"flex",justifyContent:"center",alignItems:"center"}}>
              <div style={{width:44,height:3,background:"#1a2030",borderRadius:2}}/>
            </div>
            <div style={{padding:"3px 12px 0",display:"flex",alignItems:"center",gap:8,height:20}}>
              <span style={{fontSize:9,letterSpacing:1.5,color:"#1a2030",textTransform:"uppercase"}}>
                Physical Layer — Signal Waveform
              </span>
              <span style={{fontSize:9,color:(ENC_COLORS as Record<string,string>)[encoding]||"#34d399"}}>
                {encoding}
              </span>
              <div style={{flex:1}}/>
              <span style={{fontSize:9,color:"#1a2030"}}>↕ drag to resize</span>
            </div>
            <canvas ref={waveRef} width={900} height={wavePan.sz-22}
              style={{width:"100%",height:wavePan.sz-22,display:"block"}}/>
          </div>
        </div>

        {/* ── SIDEBAR (resizable) ── */}
        <div style={{width:sidebar.sz,background:"#0d1117",borderLeft:"1px solid #1a2030",
          display:"flex",flexDirection:"column",overflow:"hidden",flexShrink:0,position:"relative"}}>

          {/* sidebar resize handle */}
          <div onMouseDown={sidebar.handle} style={{
            position:"absolute",left:-4,top:0,bottom:0,width:8,
            cursor:"ew-resize",zIndex:20,display:"flex",alignItems:"center",justifyContent:"center"}}>
            <div style={{width:3,height:44,background:"#1a2030",borderRadius:2}}/>
          </div>

          {/* device palette */}
          <SideSection title="Add Device" hint="drag to canvas">
            <div style={{display:"grid",gridTemplateColumns:"1fr 1fr 1fr",gap:5}}>
              {(Object.entries(DEVICE_META) as [DeviceType,typeof DEVICE_META[DeviceType]][]).map(([type,meta])=>(
                <div key={type} draggable
                  onDragStart={()=>setDraggingType(type)}
                  onDragEnd={()=>setDraggingType(null)}
                  style={{
                    background:draggingType===type?rgba(meta.color,.18):"#111827",
                    border:`1px solid ${draggingType===type?meta.color:"#1a2030"}`,
                    borderRadius:6,padding:"7px 4px",cursor:"grab",
                    textAlign:"center",transition:"all .12s",
                  }}
                  onMouseEnter={e=>(e.currentTarget.style.borderColor=meta.color)}
                  onMouseLeave={e=>{if(draggingType!==type)e.currentTarget.style.borderColor="#1a2030";}}>
                  <div style={{fontSize:21,marginBottom:2}}>{meta.icon}</div>
                  <div style={{fontSize:9,color:"#9ca3af"}}>{type}</div>
                </div>
              ))}
            </div>
          </SideSection>

          {/* TCP/IP stack */}
          <SideSection title="TCP/IP Stack" hint="Session+Presentation → Application">
            {TCPIP_LAYERS.map(l=>{
              const lkey=l.name==="Data Link"?"datalink":l.name.toLowerCase();
              const isActive=activeLayer===lkey;
              return(
                <div key={l.name} style={{
                  display:"flex",alignItems:"center",gap:7,padding:"5px 8px",
                  borderRadius:6,marginBottom:3,transition:"all .2s",
                  background:isActive?rgba(l.color,.12):"transparent",
                  border:`1px solid ${isActive?l.color:l.live?rgba(l.color,.25):"#1a2030"}`,
                  boxShadow:isActive?`0 0 10px ${rgba(l.color,.25)}`:"none",
                }}>
                  <div style={{width:9,height:9,borderRadius:"50%",background:l.color,flexShrink:0,
                    boxShadow:isActive?`0 0 8px ${l.color}`:"none"}}/>
                  <div style={{flex:1,minWidth:0}}>
                    <div style={{color:l.color,fontSize:11,fontWeight:600}}>{l.name}</div>
                    <div style={{color:"#374151",fontSize:9,overflow:"hidden",
                      textOverflow:"ellipsis",whiteSpace:"nowrap"}}>{l.note}</div>
                  </div>
                  <span style={{fontSize:9,color:l.live?l.color:"#374151",flexShrink:0,
                    fontWeight:l.live?700:400}}>
                    {l.live?"✓ LIVE":"soon"}
                  </span>
                </div>
              );
            })}
          </SideSection>

          {/* DLL active config summary */}
          {simMode==="datalink"&&(
            <SideSection title="Active DLL Config">
              <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:4}}>
                {[
                  {label:"Framing",   value:framing,   color:"#60a5fa"},
                  {label:"Error",     value:errCtrl,   color:"#f87171"},
                  {label:"MAC",       value:macProto,  color:"#fbbf24"},
                  {label:"ARQ/Flow",  value:flowCtrl,  color:"#a78bfa"},
                ].map(x=>(
                  <div key={x.label} style={{
                    background:"#111827",border:`1px solid ${rgba(x.color,.25)}`,
                    borderRadius:5,padding:"4px 7px"}}>
                    <div style={{fontSize:8,color:"#374151",letterSpacing:.5}}>{x.label}</div>
                    <div style={{fontSize:10,color:x.color,overflow:"hidden",
                      textOverflow:"ellipsis",whiteSpace:"nowrap"}}>{x.value}</div>
                  </div>
                ))}
              </div>
              {(flowCtrl==="go_back_n"||flowCtrl==="selective_repeat")&&(
                <div style={{marginTop:5,fontSize:10,color:"#a78bfa"}}>
                  Window size: <b>{winSz}</b>
                  {" "}· seq bits: <b>{Math.ceil(Math.log2(winSz+1))}</b>
                </div>
              )}
              {injectErr&&(
                <div style={{marginTop:4,fontSize:10,color:"#f87171"}}>
                  ⚠ Error injection ON — {errCtrl.toUpperCase()} will detect
                </div>
              )}
            </SideSection>
          )}

          {/* event log */}
          <div style={{flex:1,display:"flex",flexDirection:"column",overflow:"hidden",
            borderTop:"1px solid #1a2030"}}>
            <div style={{padding:"6px 10px 3px",display:"flex",alignItems:"center",gap:6,flexShrink:0}}>
              <span style={{fontSize:9,letterSpacing:1.5,color:"#374151",textTransform:"uppercase",flex:1}}>
                Event Log ({filtLog.length})
              </span>
              <button onClick={()=>setLog([])} style={{...pill,padding:"2px 7px",fontSize:9,color:"#374151"}}>
                Clear
              </button>
            </div>
            <div style={{display:"flex",gap:3,padding:"0 8px 5px",flexShrink:0,flexWrap:"wrap"}}>
              {["all","physical","datalink","network","transport","application","engine"].map(f=>{
                const clr=LAYER_CLR[f]||"#34d399";
                return(
                  <button key={f} onClick={()=>setLogFilter(f)} style={{
                    ...pill,padding:"2px 7px",fontSize:9,
                    borderColor:logFilter===f?clr:"#1a2030",
                    color:logFilter===f?clr:"#374151",
                    background:logFilter===f?rgba(clr,.12):"transparent",
                  }}>{f==="all"?"ALL":f.slice(0,3).toUpperCase()}</button>
                );
              })}
            </div>
            <div style={{flex:1,overflowY:"auto",padding:"2px 8px",fontSize:10,lineHeight:1.55}}>
              {filtLog.map((e,i)=>(
                <div key={i} style={{padding:"2px 4px",borderRadius:2,marginBottom:1,
                  color:LAYER_CLR[e.layer]||"#4b5563",opacity:i>60?0.55:1}}>
                  <span style={{color:"#1a2030",fontSize:9}}>[{e.t}]</span> {e.msg}
                </div>
              ))}
              {filtLog.length===0&&(
                <div style={{color:"#1a2030",padding:"8px 4px",fontSize:10}}>
                  No events — run a simulation first
                </div>
              )}
            </div>
          </div>

          {/* stats bar */}
          <div style={{display:"flex",gap:10,padding:"5px 10px",
            borderTop:"1px solid #1a2030",fontSize:10,color:"#374151",flexShrink:0}}>
            <span>Devices: <b style={{color:"#e2e8f0"}}>{devices.length}</b></span>
            <span>Links: <b style={{color:"#e2e8f0"}}>{links.length}</b></span>
            <span>Log: <b style={{color:"#e2e8f0"}}>{log.length}</b></span>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ── helper components ──────────────────────────────────────────────────── */
function Div(){return <div style={{width:1,height:22,background:"#1a2030",margin:"0 2px"}}/>;}
function SideSection({title,hint,children}:{title:string;hint?:string;children:React.ReactNode}){
  return(
    <div style={{borderBottom:"1px solid #1a2030",padding:"9px 10px"}}>
      <div style={{display:"flex",gap:5,alignItems:"baseline",marginBottom:7}}>
        <span style={{fontSize:9,letterSpacing:1.5,color:"#374151",textTransform:"uppercase"}}>{title}</span>
        {hint&&<span style={{fontSize:9,color:"#1a2030"}}>{hint}</span>}
      </div>
      {children}
    </div>
  );
}
function CfgGroup({label,color,value,onChange,opts}:{
  label:string;color:string;value:string;onChange:(v:string)=>void;
  opts:{v:string;l:string}[];
}){
  const rgba2=(hex:string,a:number)=>{
    const r=parseInt(hex.slice(1,3),16),g=parseInt(hex.slice(3,5),16),b=parseInt(hex.slice(5,7),16);
    return `rgba(${r},${g},${b},${a})`;
  };
  return(
    <div style={{display:"flex",flexDirection:"column",gap:5,minWidth:200}}>
      <div style={{fontSize:9,color,letterSpacing:1,textTransform:"uppercase"}}>{label}</div>
      {opts.map(o=>(
        <button key={o.v} onClick={()=>onChange(o.v)} style={{
          background:value===o.v?rgba2(color,.14):"transparent",
          border:`1px solid ${value===o.v?color:"#1a2030"}`,
          borderRadius:5,padding:"5px 10px",fontSize:10,
          color:value===o.v?color:"#4b5563",cursor:"pointer",
          textAlign:"left",fontFamily:"inherit",transition:"all .1s",
        }}>{o.l}</button>
      ))}
    </div>
  );
}
function CtxItem({label,action,color="#e2e8f0",danger=false}:{
  label:string;action:()=>void;color?:string;danger?:boolean;}){
  return(
    <div style={{padding:"6px 12px",cursor:"pointer",borderRadius:5,
      color:danger?"#ef4444":color,transition:"background .1s",fontSize:11}}
      onMouseEnter={e=>(e.currentTarget.style.background="#1a2030")}
      onMouseLeave={e=>(e.currentTarget.style.background="transparent")}
      onClick={action}>{label}</div>
  );
}
function CtxSep(){return <div style={{height:1,background:"#1a2030",margin:"3px 0"}}/>;}

/* ── style constants ────────────────────────────────────────────────────── */
const pill:React.CSSProperties={
  background:"transparent",border:"1px solid #1a2030",borderRadius:5,
  padding:"3px 10px",fontSize:11,cursor:"pointer",fontFamily:"inherit",
  transition:"all .12s",color:"#4b5563",
};
const selSt:React.CSSProperties={
  background:"#111827",border:"1px solid #1a2030",borderRadius:4,
  padding:"3px 7px",fontSize:11,color:"#e2e8f0",fontFamily:"inherit",cursor:"pointer",
};
