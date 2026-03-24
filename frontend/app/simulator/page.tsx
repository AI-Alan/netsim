"use client";
import { useEffect, useRef, useState, useCallback } from "react";
import { useSimStore } from "@/lib/store";
import { connectWS } from "@/lib/websocket";
import { encodeSignal, ENC_COLORS, encodedLineBitCount4B5B } from "@/lib/encoding";
import type { DeviceNode, NetworkLink, DeviceType, MediumType, SimEvent } from "@/lib/types";
import {
  fetchBackendHealth,
  fetchSimOptions,
  FALLBACK_DATALINK,
  FALLBACK_ENCODINGS,
  labelDatalinkOption,
  type DatalinkApiOptions,
} from "@/lib/api";

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
  host:    { icon:"🖥",  color:"#3b82f6", tcpip:4 },
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

/** Light theme — readable text on soft gray / white chrome */
const UI={
  bg:"#dce3ed",
  text:"#0f172a",
  textMuted:"#475569",
  textSoft:"#64748b",
  border:"#cbd5e1",
  borderHi:"#94a3b8",
  panel:"#ffffff",
  panel2:"#f8fafc",
  panel3:"#f1f5f9",
  canvas:"#eef2f7",
  graphBg:"#ffffff",
  wavePanel:"#f1f5f9",
  ctxHover:"#e2e8f0",
} as const;

const pill:React.CSSProperties={
  background:"transparent",border:`1px solid ${UI.border}`,borderRadius:5,
  padding:"3px 10px",fontSize:11,cursor:"pointer",fontFamily:"inherit",
  transition:"all .12s",color:UI.textMuted,
};
const selSt:React.CSSProperties={
  background:UI.panel,border:`1px solid ${UI.borderHi}`,borderRadius:4,
  padding:"3px 7px",fontSize:11,color:UI.text,fontFamily:"inherit",cursor:"pointer",
};

function isDeviceType(s:string): s is DeviceType{
  return Object.prototype.hasOwnProperty.call(DEVICE_META,s);
}

const ACTIVE_DEVICE_TYPES: DeviceType[] = ["host","switch","hub"];
const COMING_SOON_DEVICE_TYPES: DeviceType[] = ["computer","server","router","laptop"];
type TopologyPreset="demo"|"star"|"bus"|"mesh";

function deviceLabel(type:DeviceType):string{
  const m=DEVICE_META[type];
  return `${m.icon} ${type[0].toUpperCase()+type.slice(1)}`;
}
function normalizeDeviceType(type:string):DeviceType{
  const t=String(type||"").toLowerCase();
  if(t==="switch"||t==="hub"||t==="host") return t as DeviceType;
  if(t==="computer"||t==="server"||t==="laptop"||t==="router"||t==="end_host") return "host";
  return "host";
}
function toBackendDeviceType(type:DeviceType):string{
  return type==="host" ? "end_host" : type;
}

function isLooseIPv4(s:string):boolean{
  const m=s.trim().match(/^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/);
  if(!m)return false;
  return m.slice(1).every(p=>{const n=+p;return n>=0&&n<=255;});
}
function isMac(s:string):boolean{
  return /^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$/.test(s.trim());
}

type PipelineSnapshot={
  mode:"physical"|"datalink";
  userData:string;
  framing?:Record<string,unknown>;
  frameSent?:Record<string,unknown>;
  flow?:Record<string,unknown>;
  errorDetected?:{scheme?:string;detail?:string;dropped?:boolean};
  frameDropped?:string;
  phyBits?:{encoding?:string;raw_bits?:string;clock_rate?:number};
  signal?:{encoding?:string;sample_rate?:number};
  received?:Record<string,unknown>;
};
type DomainStats={broadcast_domains:number;collision_domains:number};
type SwitchTableRow={mac:string;port:string;last_seen?:number};
type SwitchTables=Record<string,SwitchTableRow[]>;
type LearningRow={switch_id:string;mac:string;port:string;hop?:number;frame_kind?:string};
type SwitchPortRow={port:string;neighbor:string;medium:string};
type SwitchPorts=Record<string,SwitchPortRow[]>;
function isEndpointDeviceType(t:DeviceType):boolean{
  return normalizeDeviceType(t)==="host";
}
function learningSummaryText(rows:LearningRow[], devLabelFn:(id:string)=>string):string{
  if(!rows.length) return "";
  const bySwitch: Record<string, LearningRow[]> = {};
  for(const r of rows){
    const key=r.switch_id;
    bySwitch[key] = bySwitch[key] || [];
    bySwitch[key].push(r);
  }
  return Object.entries(bySwitch)
    .map(([sw, list])=>{
      const items=list
        .slice()
        .sort((a,b)=>(Number(a.hop??0)-Number(b.hop??0))||a.mac.localeCompare(b.mac))
        .map(x=>`${x.mac}→${x.port}${x.hop!==undefined?`@h${x.hop}`:""}`)
        .join(", ");
      return `${devLabelFn(sw)}: ${items}`;
    })
    .join(" | ");
}

function buildPipeline(events:unknown[],mode:"physical"|"datalink",userData:string):PipelineSnapshot{
  const snap:PipelineSnapshot={mode,userData};
  const list=Array.isArray(events)?events as {event_type:string;pdu?:{headers?:Record<string,unknown>}}[]:[];
  for(const ev of list){
    const h=ev.pdu?.headers||{};
    switch(ev.event_type){
      case"FRAMING_INFO":snap.framing={...h};break;
      case"FRAME_SENT":snap.frameSent={...h};break;
      case"FLOW_CONTROL":snap.flow={...h};break;
      case"ERROR_DETECTED":snap.errorDetected={
        scheme:String(h.scheme??""),detail:String(h.detail??""),dropped:!!h.dropped};break;
      case"FRAME_DROPPED":snap.frameDropped=String(h.reason??h.detail??"dropped");break;
      case"BITS_SENT":snap.phyBits={
        encoding:String(h.encoding??""),raw_bits:String(h.raw_bits??""),
        clock_rate:Number(h.clock_rate)};break;
      case"SIGNAL_DRAWN":snap.signal={
        encoding:String(h.encoding??""),sample_rate:Number(h.sample_rate)};break;
      case"FRAME_RECEIVED":snap.received={...h};break;
    }
  }
  return snap;
}

function ph(o:Record<string,unknown>|undefined,k:string):string{
  if(!o)return"";
  const v=o[k];
  if(v===undefined||v===null)return"";
  return String(v);
}

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
      setSz(Math.max(min,Math.min(max,s.startSz-delta)));
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
  const [fixedFrameSize,setFixedFrameSize]=useState(128);
  const [clockRate,setClockRate]=useState(1000);
  const [samplesPerBit,setSamplesPerBit]=useState(100);
  const [showAdvanced,setShowAdvanced]=useState(false);
  const [restOk,setRestOk]=useState<boolean|null>(null);
  const [apiDl,setApiDl]=useState<DatalinkApiOptions>(FALLBACK_DATALINK);
  const [encList,setEncList]=useState<string[]>([...FALLBACK_ENCODINGS]);

  /* sim mode */
  const [simMode,setSimMode]=useState<"physical"|"datalink">("datalink");
  const [showDLL,setShowDLL]=useState(false);
  const [activeLayer,setActiveLayer]=useState<string|null>(null);

  /* ui */
  const [draggingType,setDraggingType]=useState<DeviceType|null>(null);
  const paletteDragRef=useRef<DeviceType|null>(null);
  const [placePickType,setPlacePickType]=useState<DeviceType|null>(null);
  const [paletteDeviceType,setPaletteDeviceType]=useState<DeviceType>("host");
  const [topologyHint,setTopologyHint]=useState<string>("");
  const [presetSelectKey,setPresetSelectKey]=useState(0);
  const [connectFrom,setConnectFrom]=useState<string|null>(null);
  const [pendingMed,setPendingMed]=useState<MediumType>("wired");
  const [mousePos,setMousePos]=useState({x:0,y:0});
  const [ctxMenu,setCtxMenu]=useState<{x:number;y:number;devId:string}|null>(null);
  const [tooltip,setTooltip]=useState<{x:number;y:number;dev:DeviceNode}|null>(null);
  const [animPkts,setAnimPkts]=useState<{id:string;x:number;y:number;layer:string}[]>([]);
  const [activeLnkModes,setActiveLnkModes]=useState<Record<string,"flood"|"unicast"|null>>({});
  const [flashDev,setFlashDev]=useState<string|null>(null);
  const [log,setLog]=useState<{t:string;msg:string;layer:string}[]>([]);
  const [logFilter,setLogFilter]=useState("all");
  const [linkCtx,setLinkCtx]=useState<{x:number;y:number;linkId:string}|null>(null);
  const lastPathMediumLog=useRef<string>("");
  const connectFromRef=useRef<string|null>(null);
  connectFromRef.current=connectFrom;

  const [pipeline,setPipeline]=useState<PipelineSnapshot|null>(null);
  const [showPipeline,setShowPipeline]=useState(true);
  const [domainStats,setDomainStats]=useState<DomainStats|null>(null);
  const [topologyMode,setTopologyMode]=useState(false);
  const [switchTables,setSwitchTables]=useState<SwitchTables>({});
  const [switchPorts,setSwitchPorts]=useState<SwitchPorts>({});
  const [learningSummary,setLearningSummary]=useState<LearningRow[]>([]);
  const [resetLearning,setResetLearning]=useState(false);
  const [editTarget,setEditTarget]=useState<DeviceNode|null>(null);
  const [editLabel,setEditLabel]=useState("");
  const [editIp,setEditIp]=useState("");
  const [editMac,setEditMac]=useState("");
  const [editErr,setEditErr]=useState("");

  /* panel resize */
  const sidebar=useResize(340,200,580,"h");
  const wavePan=useResize(110,55,260,"v");

  const canvasRef=useRef<HTMLDivElement>(null);
  const waveRef=useRef<HTMLCanvasElement>(null);
  const waveWrapRef=useRef<HTMLDivElement>(null);
  const dragRef=useRef<{id:string;ox:number;oy:number}|null>(null);

  /* init */
  useEffect(()=>{
    setSession(sessionId);
    connectWS(sessionId,WS_URL);
    applyTopologyPreset("demo");
  },[]);

  useEffect(()=>{
    let cancel=false;
    (async()=>{
      const ok=await fetchBackendHealth();
      if(!cancel) setRestOk(ok);
      const opts=await fetchSimOptions();
      if(cancel||!opts) return;
      setApiDl(opts.datalink);
      setEncList(opts.encodings);
      if(opts.encodings.length&&!opts.encodings.includes(encoding))
        setEncoding(opts.encodings[0]);
    })();
    return()=>{cancel=true;};
  },[]);

  useEffect(()=>{
    const esc=(e:KeyboardEvent)=>{
      if(e.key==="Escape") setPlacePickType(null);
    };
    window.addEventListener("keydown",esc);
    return()=>window.removeEventListener("keydown",esc);
  },[]);

  useEffect(()=>{
    if(srcId&&dstId) setTopologyHint("");
  },[srcId,dstId]);

  useEffect(()=>{
    if(!apiDl.mac_proto.includes(macProto)) setMacProto(apiDl.mac_proto[0]??"csma_cd");
    if(!apiDl.flow.includes(flowCtrl)) setFlowCtrl(apiDl.flow[0]??"stop_and_wait");
    if(!apiDl.error.includes(errCtrl)) setErrCtrl(apiDl.error[0]??"crc32");
    if(!apiDl.framing.includes(framing)) setFraming(apiDl.framing[0]??"variable");
  },[apiDl]);

  useEffect(()=>{
    const bits=toPhyBits(msg,simMode);
    if(bits.length>0) drawWave(bits,encoding);
  },[msg,encoding,simMode,wavePan.sz]);

  useEffect(()=>{
    const wrap=waveWrapRef.current;
    if(!wrap) return;
    const ro=new ResizeObserver(()=>{
      const bits=toPhyBits(msg,simMode);
      if(bits.length>0) drawWave(bits,encoding);
    });
    ro.observe(wrap);
    return()=>ro.disconnect();
  },[msg,encoding,simMode,wavePan.sz]);

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

  function applyTopologyPreset(kind:TopologyPreset){
    idSeq=0; lnkSeq=0;
    setConnectFrom(null); setCtxMenu(null); setLinkCtx(null); setPlacePickType(null);
    setTopologyHint("");
    setDomainStats(null);
    setTopologyMode(false);
    setSwitchTables({});
    setSwitchPorts({});
    setLearningSummary([]);

    if(kind==="demo"){
      const d1=mkDev("host",130,195), d2=mkDev("switch",330,195);
      const d3=mkDev("host",530,195), d4=mkDev("hub",330,370);
      setDevices([d1,d2,d3,d4]);
      setLinks([
        {id:"lnk_1",src:d1.id,dst:d2.id,medium:"wired"},
        {id:"lnk_2",src:d2.id,dst:d3.id,medium:"wired"},
        {id:"lnk_3",src:d2.id,dst:d4.id,medium:"wireless"},
      ]);
      lnkSeq=3;
      setSrcId(d1.id); setDstId(d3.id);
      addLog("Loaded Demo topology","engine");
      return;
    }

    if(kind==="star"){
      const cx=380, cy=220, r=130;
      const center=mkDev("switch",cx,cy);
      const hostTypes:DeviceType[]=["host","host","host","host"];
      const hosts=hostTypes.map((t,i)=>{
        const ang=(i/hostTypes.length)*2*Math.PI-Math.PI/2;
        return mkDev(t,cx+r*Math.cos(ang),cy+r*Math.sin(ang));
      });
      setDevices([center,...hosts]);
      const L:NetworkLink[]=[];
      for(const h of hosts){
        L.push({id:"lnk_"+(++lnkSeq),src:h.id,dst:center.id,medium:"wired"});
      }
      setLinks(L);
      setSrcId(hosts[0].id); setDstId(hosts[2].id);
      addLog("Loaded Star topology (hosts ↔ central switch)","engine");
      return;
    }

    if(kind==="bus"){
      const y=220, gap=115, x0=120;
      const chain:DeviceType[]=["host","hub","switch","host","host"];
      const nodes=chain.map((t,i)=>mkDev(t,x0+i*gap,y));
      setDevices(nodes);
      const L:NetworkLink[]=[];
      for(let i=0;i<nodes.length-1;i++){
        L.push({id:"lnk_"+(++lnkSeq),src:nodes[i].id,dst:nodes[i+1].id,medium:"wired"});
      }
      setLinks(L);
      setSrcId(nodes[0].id); setDstId(nodes[nodes.length-1].id);
      addLog("Loaded Bus topology (linear chain)","engine");
      return;
    }

    /* mesh — full mesh of 4 end-capable nodes */
    const y1=160,y2=300,xl=200,xr=480;
    const a=mkDev("host",xl,y1), b=mkDev("host",xr,y1);
    const c=mkDev("host",xl,y2), d=mkDev("host",xr,y2);
    setDevices([a,b,c,d]);
    const pairs:[string,string][]=[
      [a.id,b.id],[a.id,c.id],[a.id,d.id],[b.id,c.id],[b.id,d.id],[c.id,d.id],
    ];
    const L:NetworkLink[]=pairs.map(([s,dst])=>({id:"lnk_"+(++lnkSeq),src:s,dst:dst,medium:"wired"}));
    setLinks(L);
    setSrcId(a.id); setDstId(d.id);
    addLog("Loaded Mesh topology (4 nodes, full mesh)","engine");
  }

  function mkDev(type:DeviceType,x:number,y:number):DeviceNode{
    const normalized=normalizeDeviceType(type);
    const id="dev_"+(++idSeq);
    return {id,type:normalized,x,y,layers:DEVICE_META[normalized].tcpip,
      label:normalized[0].toUpperCase()+normalized.slice(1)+"-"+idSeq,
      ip:"192.168.1."+(9+idSeq), mac:randMac()};
  }

  function handlePaletteDragOver(e:React.DragEvent){
    e.preventDefault();
    e.dataTransfer.dropEffect="copy";
  }
  function handlePaletteDrop(e:React.DragEvent){
    e.preventDefault();
    e.stopPropagation();
    const raw=e.dataTransfer.getData("text/plain").trim();
    const fromRef=paletteDragRef.current;
    const fromDt=isDeviceType(raw)?raw:null;
    const type=fromRef??fromDt??draggingType;
    if(!type)return;
    const normalized=normalizeDeviceType(type);
    if(!ACTIVE_DEVICE_TYPES.includes(normalized)){
      setTopologyHint(`'${type}' is coming soon. Use host/switch/hub for now.`);
      return;
    }
    const r=canvasRef.current?.getBoundingClientRect();
    if(!r)return;
    const dev=mkDev(normalized,e.clientX-r.left,e.clientY-r.top);
    setDevices(p=>{
      const next=[...p,dev];
      if(!srcId)setSrcId(dev.id);
      else if(!dstId)setDstId(dev.id);
      return next;
    });
    addLog(`Placed ${dev.label}`,"engine");
    paletteDragRef.current=null;
    setDraggingType(null);
    setPlacePickType(null);
  }

  function addLink(s:string,d:string,med:MediumType){
    if(s===d){
      addLog("Cannot link a device to itself.","engine");
      return;
    }
    if(links.some(l=>(l.src===s&&l.dst===d)||(l.src===d&&l.dst===s))){
      addLog("Link already exists between these devices.","engine");
      return;
    }
    const sl=getDevL(s),dl=getDevL(d);
    addLog(`Link: ${sl?.label} ↔ ${dl?.label} [${med}]`,"datalink");
    setLinks(p=>[...p,{id:"lnk_"+(++lnkSeq),src:s,dst:d,medium:med}]);
  }

  function updateLinkMedium(linkId:string,med:MediumType){
    const l=links.find(x=>x.id===linkId);
    const a=l?getDevL(l.src):undefined,b=l?getDevL(l.dst):undefined;
    addLog(`Link ${a?.label??"?"} ↔ ${b?.label??"?"} → ${med}`,"datalink");
    setLinks(p=>p.map(x=>x.id===linkId?{...x,medium:med}:x));
    setLinkCtx(null);
  }

  function removeLink(linkId:string){
    setLinks(p=>p.filter(l=>l.id!==linkId));
    addLog("Link removed","datalink");
    setLinkCtx(null);
  }

  function delDevice(id:string){
    setDevices(p=>p.filter(d=>d.id!==id));
    setLinks(p=>p.filter(l=>l.src!==id&&l.dst!==id));
    if(srcId===id)setSrcId(null);
    if(dstId===id)setDstId(null);
  }

  function getDevL(id:string,devs=devices):DeviceNode|undefined{return devs.find(d=>d.id===id);}
  function devLabel(id:string):string{return getDevL(id)?.label ?? id;}
  function isEndpointNodeId(id:string|null):boolean{
    if(!id) return false;
    const d=getDevL(id);
    return !!d&&isEndpointDeviceType(d.type);
  }
  function portCountFor(id:string,lnkList=links):number{
    return lnkList.filter(l=>l.src===id||l.dst===id).length;
  }

  function simulateDisabledReason():string|undefined{
    if(running) return "Simulation is still running.";
    if(!srcId||!dstId) return "Set SRC and DST: right-click a device → Set as Source / Destination.";
    if(srcId===dstId) return "Source and destination must be different devices.";
    if(!isEndpointNodeId(srcId)||!isEndpointNodeId(dstId)) return "SRC and DST must be end devices (computer/server/laptop/router), not switch/hub.";
    if(!getPath(srcId,dstId)) return "No route: connect SRC and DST with one or more links.";
    return undefined;
  }

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

  function canSim(){return !!(srcId&&dstId&&srcId!==dstId&&!running&&isEndpointNodeId(srcId)&&isEndpointNodeId(dstId)&&getPath(srcId,dstId));}

  /** PHY medium for API: first segment on SRC→DST path (single-hop model). */
  function firstHopMedium(lnkList=links):MediumType{
    if(!srcId||!dstId)return "wired";
    const path=getPath(srcId,dstId,lnkList);
    if(!path||path.length<2)return "wired";
    const a=path[0],b=path[1];
    const lnk=lnkList.find(l=>(l.src===a&&l.dst===b)||(l.src===b&&l.dst===a));
    return lnk?.medium??"wired";
  }

  useEffect(()=>{
    if(!srcId||!dstId||srcId===dstId){ lastPathMediumLog.current=""; return; }
    const path=getPath(srcId,dstId);
    if(!path||path.length<2)return;
    const meds:MediumType[]=[];
    for(let i=0;i<path.length-1;i++){
      const a=path[i],b=path[i+1];
      const lnk=links.find(l=>(l.src===a&&l.dst===b)||(l.src===b&&l.dst===a));
      meds.push(lnk?.medium??"wired");
    }
    const first=meds[0]??"wired";
    const key=path.join(">")+"|"+meds.join(",");
    const mixed=new Set(meds).size>1;
    if(mixed&&lastPathMediumLog.current!==key){
      lastPathMediumLog.current=key;
      const t=(performance.now()/1000).toFixed(3);
      setLog(p=>[{t,msg:"Path mixes copper + wireless — PHY simulation uses first hop ("+first+").",layer:"engine"},...p].slice(0,250));
    }
    if(!mixed) lastPathMediumLog.current="";
  },[srcId,dstId,links]);

  function toPhyBits(m:string,mode:string):number[]{
    if(mode==="physical") return m.replace(/[^01]/g,"").split("").map(Number);
    const bytes=m.split("").map(c=>c.charCodeAt(0));
    const bits:number[]=[];
    for(const b of bytes.slice(0,4)) for(let i=7;i>=0;i--) bits.push((b>>i)&1);
    return bits;
  }

  function openDeviceEdit(dev:DeviceNode){
    setEditTarget(dev); setEditLabel(dev.label); setEditIp(dev.ip); setEditMac(dev.mac); setEditErr("");
  }
  function saveDeviceEdit(){
    if(!editTarget)return;
    if(!editLabel.trim()){ setEditErr("Label required"); return; }
    if(!isLooseIPv4(editIp)){ setEditErr("Invalid IPv4 address"); return; }
    if(!isMac(editMac)){ setEditErr("MAC must be like aa:bb:cc:dd:ee:ff"); return; }
    setDevices(p=>p.map(d=>d.id===editTarget.id?{
      ...d,label:editLabel.trim(),ip:editIp.trim(),mac:editMac.trim().toLowerCase(),
    }:d));
    addLog(`Updated device ${editLabel.trim()}`,"engine");
    setEditTarget(null);
  }

  async function simulate(){
    if(!canSim())return;
    const path=getPath(srcId!,dstId!)!;
    const phyMedium=firstHopMedium();
    let backendEvents: SimEvent[] = [];
    let latestSwitchPorts: SwitchPorts = switchPorts;
    setPipeline(null);
    setRunning(true); setSimRunning(true); clearEvents();
    const src=getDevL(srcId!)!, dst=getDevL(dstId!)!;
    addLog("━━ Simulation start ━━","engine");
    addLog(`${src.label} → ${dst.label} | mode=${simMode} | ${encoding} | PHY ${phyMedium} (1st hop)`,"engine");

    try{
      const berF=parseFloat(ber);
      const endpoint=simMode==="datalink"?"/api/simulate/datalink":"/api/simulate/physical";
      const body=simMode==="datalink"?{
        session_id:sessionId, src_device_id:srcId!, dst_device_id:dstId!,
        message:msg||"Hello!", framing,
        framing_kwargs:framing==="fixed"?{frame_size:fixedFrameSize}:{},
        error_control:errCtrl, mac_protocol:macProto, flow_control:flowCtrl,
        window_size:winSz, encoding, medium:phyMedium,
        clock_rate:clockRate, samples_per_bit:samplesPerBit,
        medium_kwargs:berF>0?{ber:berF}:{},
        collision_prob:colProb, link_error_rate:berF, inject_error:injectErr,
        topology_devices: devices.map(d=>({id:d.id,type:toBackendDeviceType(d.type),label:d.label,mac:d.mac,ip:d.ip})),
        topology_links: links.map(l=>({id:l.id,src:l.src,dst:l.dst,medium:l.medium})),
        reset_learning: resetLearning,
      }:{
        session_id:sessionId, src_device_id:srcId!, dst_device_id:dstId!,
        bit_string:msg.replace(/[^01]/g,""), encoding, medium:phyMedium,
        clock_rate:clockRate, samples_per_bit:samplesPerBit,
        medium_kwargs:berF>0?{ber:berF}:{},
      };

      const resp=await fetch(BACKEND+endpoint,{method:"POST",
        headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
      if(resp.ok){
        setRestOk(true);
        const data=await resp.json();
        backendEvents=Array.isArray(data.events)?(data.events as SimEvent[]):[];
        setTopologyMode(!!data.topology_mode);
        if(data.domain_stats){
          setDomainStats({
            broadcast_domains:Number(data.domain_stats.broadcast_domains??0),
            collision_domains:Number(data.domain_stats.collision_domains??0),
          });
        } else {
          setDomainStats(null);
        }
        setSwitchTables((data.switch_tables??{}) as SwitchTables);
        latestSwitchPorts=(data.switch_ports??{}) as SwitchPorts;
        setSwitchPorts(latestSwitchPorts);
        setLearningSummary(Array.isArray(data.learning_summary)?data.learning_summary as LearningRow[]:[]);
        if(resetLearning) setResetLearning(false);
        setPipeline(buildPipeline(backendEvents,simMode,simMode==="datalink"?msg:msg.replace(/[^01]/g,"")));
        addLog(`Backend: ${data.events_emitted} events`,"engine");
        if(data.domain_stats){
          addLog(
            `Domains → broadcast=${data.domain_stats.broadcast_domains} · collision=${data.domain_stats.collision_domains}`,
            "engine",
          );
        }
        if(Array.isArray(data.learning_summary)&&data.learning_summary.length){
          const learned=learningSummaryText(data.learning_summary as LearningRow[],devLabel);
          addLog(`Learning: ${learned}`,"datalink");
        }
        for(const ev of backendEvents){
          const l=EVT_LAYER[ev.event_type]||ev.layer||"engine";
          const h=ev.pdu?.headers||{};
          if(h.steps&&Array.isArray(h.steps)){
            for(const s of(h.steps as string[]).slice(0,4)) addLog(`  ${s}`,l);
          } else {
            let detail:string=ev.event_type;
            if(h.forwarding_mode==="flood"){
              const srcId=String(ev.src_device??"");
              const egress=Array.isArray(h.egress_ports)?(h.egress_ports as string[]):[];
              const portRows=latestSwitchPorts[srcId]||[];
              const targetNames=egress.map(p=>{
                const row=portRows.find(r=>r.port===p);
                return row?devLabel(row.neighbor):p;
              }).filter(Boolean);
              const viaText=targetNames.length?` -> ${targetNames.join(", ")}`:"";
              detail=`BROADCAST ${String(h.frame_kind??"frame").toUpperCase()}${viaText}`.trim();
            } else if(h.forwarding_mode==="unicast"){
              const srcId=String(ev.src_device??"");
              const egress=Array.isArray(h.egress_ports)?(h.egress_ports as string[]):[];
              const portRows=latestSwitchPorts[srcId]||[];
              const targetNames=egress.map(p=>{
                const row=portRows.find(r=>r.port===p);
                return row?devLabel(row.neighbor):p;
              }).filter(Boolean);
              const viaText=targetNames.length?` -> ${targetNames.join(", ")}`:"";
              detail=`UNICAST ${String(h.frame_kind??"frame").toUpperCase()}${viaText}`.trim();
            } else if(h.scheme) detail+=` [${h.scheme}]`;
            else if(h.protocol) detail+=` [${h.protocol}]`;
            else if(h.detail) detail+=`: ${h.detail}`;
            addLog(`[${l.toUpperCase().slice(0,3)}] ${detail}`,l);
          }
          await delay(25);
        }
      } else {
        setRestOk(false);
        addLog(`Backend HTTP ${resp.status}`,"engine");
      }
    }catch(_){
      setRestOk(false);
      setDomainStats(null);
      setTopologyMode(false);
      setSwitchTables({});
      setSwitchPorts({});
      setLearningSummary([]);
      addLog("Backend offline — frontend-only animation","engine");
    }

    /* frontend animation */
    const bits=toPhyBits(msg,simMode);
    drawWave(bits,encoding);
    addLog(`[PHY] Signal drawn: ${encoding}`,"physical");

    if(simMode==="datalink"&&backendEvents.length){
      // Replay true backend forwarding edges so first-send flood is visible on canvas.
      const modeByDecisionKey: Record<string,"flood"|"unicast"|null> = {};
      const steps: {ts:number;from:string;to:string;linkId:string;mode:"flood"|"unicast"|null}[] = [];
      for(const ev of backendEvents){
        const h=ev.pdu?.headers||{};
        const srcNode=String(ev.src_device??"");
        const hop=Number(ev.timestamp??0);
        const frameKind=String(h.frame_kind??"");
        const k=`${srcNode}|${hop}|${frameKind}`;
        if(h.forwarding_mode==="flood"||h.forwarding_mode==="unicast"){
          modeByDecisionKey[k]=h.forwarding_mode as "flood"|"unicast";
        }
        const link=typeof h.link==="string"?String(h.link):"";
        if(!link||frameKind!=="data") continue;
        const [hs,hd]=link.split("->");
        if(!hs||!hd) continue;
        const lnk=links.find(l=>(l.src===hs&&l.dst===hd)||(l.src===hd&&l.dst===hs));
        if(!lnk) continue;
        steps.push({
          ts:Number(ev.timestamp??0),
          from:hs,
          to:hd,
          linkId:lnk.id,
          mode:modeByDecisionKey[k]??null,
        });
      }

      let i=0;
      while(i<steps.length){
        const ts=steps[i].ts;
        const batch: typeof steps = [];
        while(i<steps.length&&steps[i].ts===ts){
          batch.push(steps[i]);
          i++;
        }
        setActiveLnkModes(prev=>{
          const next={...prev};
          for(const s of batch) next[s.linkId]=s.mode;
          return next;
        });
        await Promise.all(batch.map(s=>animPkt2(s.from,s.to,simMode)));
        setActiveLnkModes(prev=>{
          const next={...prev};
          for(const s of batch) delete next[s.linkId];
          return next;
        });
        for(const s of batch){
          const via=getDevL(s.to);
          if(via) addLog(`[PHY] Received at ${via.label}`,"physical");
        }
        await delay(80);
      }
    } else {
      for(let i=0;i<path.length-1;i++){
        const hs=path[i],hd=path[i+1];
        const lnk=links.find(l=>(l.src===hs&&l.dst===hd)||(l.src===hd&&l.dst===hs));
        if(lnk){
          setActiveLnkModes(prev=>({...prev,[lnk.id]:null}));
          await animPkt2(hs,hd,simMode);
          setActiveLnkModes(prev=>{
            const next={...prev};
            delete next[lnk.id];
            return next;
          });
        }
        const via=getDevL(hd)!;
        addLog(`[PHY] Received at ${via.label}`,"physical");
        if(simMode==="datalink"){
          addLog(`[DLL] ${errCtrl.toUpperCase()} check · ${macProto} · ${flowCtrl}`,"datalink");
        }
        await delay(120);
      }
    }

    addLog(`✓ Delivered to ${dst.label}`,"engine");
    addLog("━━ Complete ━━","engine");
    setFlashDev(dstId!); setTimeout(()=>setFlashDev(null),900);
    setRunning(false); setSimRunning(false);
  }

  async function animPkt2(fromId:string,toId:string,mode:string){
    const from=getDevL(fromId)!, to=getDevL(toId)!;
    const layer=mode==="datalink"?"datalink":"physical";
    const id=`pkt-${fromId}-${toId}-${Date.now()}-${Math.random().toString(36).slice(2,7)}`;
    for(let i=0;i<=44;i++){
      const f=i/44;
      const x=from.x+(to.x-from.x)*f;
      const y=from.y+(to.y-from.y)*f;
      setAnimPkts(prev=>{
        const others=prev.filter(p=>p.id!==id);
        return [...others,{id,x,y,layer}];
      });
      await delay(11);
    }
    setAnimPkts(prev=>prev.filter(p=>p.id!==id));
  }

  function drawWave(bits:number[],enc:string){
    const canvas=waveRef.current; if(!canvas)return;
    const wrap=waveWrapRef.current;
    const H=Math.max(40,wavePan.sz-22);
    if(wrap&&wrap.clientWidth>0){
      const w=Math.floor(wrap.clientWidth);
      if(canvas.width!==w||canvas.height!==H){ canvas.width=w; canvas.height=H; }
    } else if(canvas.width<100){ canvas.width=600; canvas.height=H; }
    const ctx=canvas.getContext("2d")!;
    const W=canvas.width, H2=canvas.height;
    const plotTop=14;
    const bottomReserve=enc==="4B5B"?28:14;
    const plotBottom=H2-bottomReserve;
    const plotH=Math.max(plotBottom-plotTop,10);
    const midY=plotTop+plotH/2;
    const amp=Math.max(plotH/2-5,4);
    const yAt=(lv:number)=>midY-lv*amp;

    ctx.clearRect(0,0,W,H2);
    ctx.fillStyle=UI.graphBg; ctx.fillRect(0,0,W,H2);

    const bw=W/Math.max(bits.length,1);
    /* Half-bit lines (mid-cell): dashed, light — every encoding for a DSG-style timeline */
    ctx.setLineDash([2,4]);
    ctx.strokeStyle="#d1d5dc"; ctx.lineWidth=0.65;
    for(let i=0;i<bits.length;i++){
      const x=(i+0.5)*bw;
      ctx.beginPath(); ctx.moveTo(x,plotTop); ctx.lineTo(x,plotBottom); ctx.stroke();
    }
    ctx.setLineDash([]);
    /* Full bit boundaries: solid, stronger */
    ctx.strokeStyle="#64748b"; ctx.lineWidth=1.05;
    for(let i=0;i<=bits.length;i++){
      const x=i*bw;
      ctx.beginPath(); ctx.moveTo(x,plotTop); ctx.lineTo(x,plotBottom); ctx.stroke();
    }

    if(enc==="4B5B"){
      const nSym=encodedLineBitCount4B5B(bits);
      ctx.strokeStyle="#fca5a5"; ctx.lineWidth=0.45;
      for(let j=0;j<=nSym;j++){
        const x=j*(W/Math.max(nSym,1));
        ctx.beginPath(); ctx.moveTo(x,plotTop); ctx.lineTo(x,plotBottom); ctx.stroke();
      }
    }

    ctx.setLineDash([4,4]);
    ctx.strokeStyle="#94a3b8"; ctx.lineWidth=0.55;
    for(const lv of[-1,1] as const){
      const y=yAt(lv);
      ctx.beginPath(); ctx.moveTo(0,y); ctx.lineTo(W,y); ctx.stroke();
    }
    ctx.setLineDash([]);
    ctx.strokeStyle="#cbd5e1"; ctx.lineWidth=0.5;
    ctx.beginPath(); ctx.moveTo(0,midY); ctx.lineTo(W,midY); ctx.stroke();

    ctx.fillStyle=UI.textSoft; ctx.font="7px monospace";
    ctx.fillText("+1",2,Math.max(plotTop+7,yAt(1)-1));
    ctx.fillText("-1",2,Math.min(plotBottom-2,yAt(-1)+7));
    ctx.fillText("0",2,midY+7);

    ctx.strokeStyle="#64748b"; ctx.lineWidth=1;
    for(let i=0;i<=bits.length;i++){
      ctx.beginPath(); ctx.moveTo(i*bw,plotBottom); ctx.lineTo(i*bw,Math.min(plotBottom+5,H2-1)); ctx.stroke();
    }

    try{
      const samples=encodeSignal(bits,enc);
      const color=(ENC_COLORS as Record<string,string>)[enc]||"#34d399";
      const pw=W/Math.max(samples.length,1);
      ctx.strokeStyle=color; ctx.lineWidth=2;
      ctx.shadowColor=color; ctx.shadowBlur=5;
      ctx.beginPath();
      ctx.moveTo(0,yAt(samples[0]));
      for(let i=0;i<samples.length;i++){
        const x1=(i+1)*pw;
        ctx.lineTo(x1,yAt(samples[i]));
        if(i<samples.length-1&&samples[i]!==samples[i+1])
          ctx.lineTo(x1,yAt(samples[i+1]));
      }
      ctx.stroke();
      ctx.shadowBlur=0;

      ctx.fillStyle=color; ctx.font="bold 10px monospace";
      ctx.fillText(enc,4,11);
      if(enc==="4B5B"){
        ctx.fillStyle=UI.textSoft; ctx.font="8px monospace";
        ctx.fillText("Trace = 5B codewords + NRZ-I · red ticks = line symbols",4,H2-16);
      }
      ctx.fillStyle=color; ctx.font="9px monospace";
      bits.forEach((b,i)=>ctx.fillText(String(b),(i+0.5)*bw-3,H2-3));
    }catch(_){}
  }

  /* mouse events */
  useEffect(()=>{
    const mv=(e:MouseEvent)=>{
      const r=canvasRef.current?.getBoundingClientRect();
      if(r)setMousePos({x:e.clientX-r.left,y:e.clientY-r.top});
      if(connectFromRef.current){
        setPendingMed(e.shiftKey?"wireless":"wired");
      }
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
  const simBlockReason=simulateDisabledReason();
  const canvasRect=canvasRef.current?.getBoundingClientRect();
  const overlayBaseX=canvasRect?.left??0;
  const overlayBaseY=canvasRect?.top??0;

  /* ── RENDER ─────────────────────────────────────────────────────────── */
  return (
    <div style={{display:"flex",flexDirection:"column",height:"100vh",
      background:UI.bg,color:UI.text,
      fontFamily:"'JetBrains Mono','Fira Code',monospace",overflow:"hidden"}}>

      {/* ── TOP BAR ── */}
      <div style={{minHeight:48,background:UI.panel,borderBottom:`1px solid ${UI.border}`,
        display:"flex",alignItems:"center",flexWrap:"wrap",rowGap:6,padding:"8px 14px",gap:8,flexShrink:0,zIndex:50}}>

        {/* logo */}
        <div style={{display:"flex",alignItems:"center",gap:6,marginRight:8}}>
          <div style={{width:8,height:8,borderRadius:"50%",background:"#34d399",
            boxShadow:"0 0 10px #34d399"}}/>
          <span style={{color:"#34d399",fontWeight:700,fontSize:15,letterSpacing:3}}>NETSIM</span>
          <span style={{fontSize:9,color:UI.textSoft,marginLeft:2}}> TCP/IP</span>
        </div>
        <Div/>

        <div style={{display:"flex",alignItems:"center",gap:6}} title="Simulation depth">
          <span style={{fontSize:10,color:"#374151"}}>Mode:</span>
          {(["physical","datalink"] as const).map(m=>(
            <button key={m} onClick={()=>setSimMode(m)} style={{
              ...pill,
              background:simMode===m?rgba(m==="physical"?"#34d399":"#60a5fa",.15):"transparent",
              borderColor:simMode===m?(m==="physical"?"#34d399":"#60a5fa"):UI.border,
              color:simMode===m?(m==="physical"?"#34d399":"#60a5fa"):"#4b5563",
            }}>{m==="physical"?"⚡ PHY":"⚡ PHY + DLL"}</button>
          ))}
        </div>
        <Div/>

        <div style={{display:"flex",alignItems:"center",gap:8,flexWrap:"wrap",paddingLeft:8,marginLeft:2,
          borderLeft:`1px solid ${UI.border}`}} title="Line encoding for PHY simulation">
        <span style={{fontSize:10,color:"#374151"}}>Enc:</span>
        <select value={encoding} onChange={e=>setEncoding(e.target.value)} style={selSt}>
          {encList.map(e=>(<option key={e} value={e}>{e}</option>))}
        </select>

        <span style={{fontSize:10,color:"#374151"}}>BER:</span>
        <select value={ber} onChange={e=>setBer(e.target.value)} style={{...selSt,width:60}}>
          {[["0","0.0"],["0.01","1%"],["0.05","5%"],["0.1","10%"]].map(([v,l])=>(
            <option key={v} value={v}>{l}</option>
          ))}
        </select>
        </div>
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
            borderColor:showDLL?"#60a5fa":UI.border,
            color:showDLL?"#60a5fa":"#4b5563",
            background:showDLL?rgba("#60a5fa",.12):"transparent",
          }}>⚙ DLL Config</button>
        )}
        <button type="button" onClick={()=>setShowAdvanced(p=>!p)} title="Clock rate, samples/bit, lab presets"
          style={{
            ...pill,
            borderColor:showAdvanced?"#a78bfa":UI.border,
            color:showAdvanced?"#a78bfa":"#4b5563",
            background:showAdvanced?rgba("#a78bfa",.1):"transparent",
          }}>◇ Advanced</button>
        <Div/>
        <span style={{fontSize:10,color:"#374151"}}>SRC:</span>
        <select value={srcId??""}
          onChange={e=>setSrcId(e.target.value||null)}
          style={{...selSt,width:120}}
          title="Source device">
          <option value="">(select)</option>
          {devices.filter(d=>isEndpointDeviceType(d.type)).map(d=><option key={d.id} value={d.id}>{d.label}</option>)}
        </select>
        <button type="button" onClick={()=>{
          if(!srcId||!dstId)return;
          setSrcId(dstId); setDstId(srcId);
        }} style={{...pill,padding:"3px 8px"}} title="Swap source and destination">⇄</button>
        <span style={{fontSize:10,color:"#374151"}}>DST:</span>
        <select value={dstId??""}
          onChange={e=>setDstId(e.target.value||null)}
          style={{...selSt,width:120}}
          title="Destination device">
          <option value="">(select)</option>
          {devices.filter(d=>isEndpointDeviceType(d.type)).map(d=><option key={d.id} value={d.id}>{d.label}</option>)}
        </select>
        <Div/>

        {/* send */}
        <button type="button" onClick={simulate} disabled={!canSim()}
          title={simBlockReason ?? "Run simulation for SRC → DST"}
          style={{
          background:canSim()?"#34d399":UI.panel3,
          color:canSim()?"#000":UI.textSoft,
          border:"none",borderRadius:6,padding:"5px 20px",
          fontSize:12,fontWeight:700,cursor:canSim()?"pointer":"not-allowed",
          fontFamily:"inherit",transition:"all .15s",
          boxShadow:canSim()?"0 0 14px #34d39955":"none",
        }}>{running?"⏳ RUNNING…":"▶ SIMULATE"}</button>
        {!canSim()&&simBlockReason&&(
          <span style={{fontSize:9,color:"#6b7280",maxWidth:160,lineHeight:1.2}}>
            {simBlockReason}
          </span>
        )}
        <span style={{fontSize:9,color:"#6b7280"}}>
          Link highlight: <span style={{color:"#f59e0b"}}>flood</span> / <span style={{color:"#22c55e"}}>unicast</span>
        </span>

        <div style={{flex:1}}/>
        <Div/>
        <div style={{display:"flex",alignItems:"center",gap:10,fontSize:10}}>
          <div style={{display:"flex",alignItems:"center",gap:4}} title="REST API (simulation POST)">
            <div style={{width:7,height:7,borderRadius:"50%",
              background:restOk===null?"#374151":restOk?"#34d399":"#ef4444",
              boxShadow:restOk?"0 0 6px #34d399":restOk===false?"0 0 6px #ef444455":"none"}}/>
            <span style={{color:restOk===null?"#374151":restOk?"#34d399":"#f87171"}}>API</span>
          </div>
          <div style={{display:"flex",alignItems:"center",gap:4}} title="Live event stream">
            <div style={{width:7,height:7,borderRadius:"50%",
              background:wsConnected?"#34d399":"#374151",
              boxShadow:wsConnected?"0 0 6px #34d399":"none"}}/>
            <span style={{color:wsConnected?"#34d399":"#374151"}}>WS</span>
          </div>
        </div>
      </div>

      {/* ── ADVANCED (PHY timing + quick labs) ── */}
      {showAdvanced&&(
        <div style={{background:UI.panel2,borderBottom:`1px solid ${UI.border}`,
          padding:"8px 16px",display:"flex",flexWrap:"wrap",gap:16,alignItems:"center",flexShrink:0,zIndex:38}}>
          <div style={{display:"flex",alignItems:"center",gap:8}}>
            <span style={{fontSize:10,color:"#6b7280"}}>Clock (Hz)</span>
            <input type="number" min={200} max={8000} step={100} value={clockRate}
              onChange={e=>setClockRate(Math.max(200,Math.min(8000,parseInt(e.target.value,10)||1000)))}
              style={{...selSt,width:72}}/>
            <span style={{fontSize:10,color:"#6b7280"}}>Samples / bit</span>
            <input type="number" min={20} max={300} step={10} value={samplesPerBit}
              onChange={e=>setSamplesPerBit(Math.max(20,Math.min(300,parseInt(e.target.value,10)||100)))}
              style={{...selSt,width:56}}/>
            <span style={{fontSize:9,color:UI.textSoft,maxWidth:220,lineHeight:1.3}}>
              Higher samples → smoother waveform (heavier CPU).
            </span>
          </div>
          <Div/>
          <span style={{fontSize:10,color:"#374151"}}>Quick labs:</span>
          <button type="button" onClick={()=>{
            setSimMode("datalink"); setFraming("variable"); setErrCtrl("crc32"); setMacProto("csma_cd");
            setFlowCtrl("stop_and_wait"); setEncoding("Manchester"); setShowDLL(true);
            if(srcId&&dstId){
              const path=getPath(srcId,dstId);
              if(path&&path.length>=2){
                const a=path[0],b=path[1];
                setLinks(p=>p.map(l=>((l.src===a&&l.dst===b)||(l.src===b&&l.dst===a))?{...l,medium:"wired" as MediumType}:l));
              }
            }
            addLog("Preset: Classic shared-medium Ethernet + CRC","datalink");
          }} style={pill}>Ethernet + CRC</button>
          <button type="button" onClick={()=>{
            setSimMode("datalink"); setMacProto("csma_ca"); setErrCtrl("crc32");
            setFraming("variable"); setFlowCtrl("stop_and_wait"); setShowDLL(true);
            if(srcId&&dstId){
              const path=getPath(srcId,dstId);
              if(path&&path.length>=2){
                const a=path[0],b=path[1];
                setLinks(p=>p.map(l=>((l.src===a&&l.dst===b)||(l.src===b&&l.dst===a))?{...l,medium:"wireless" as MediumType}:l));
              }
            }
            addLog("Preset: Wi-Fi-style CSMA/CA on wireless medium","datalink");
          }} style={pill}>Wi‑Fi (CSMA/CA)</button>
          <button type="button" onClick={()=>{
            setSimMode("datalink"); setMacProto("pure_aloha"); setColProb(0.15); setShowDLL(true);
            addLog("Preset: Pure ALOHA — try raising collision probability","datalink");
          }} style={pill}>ALOHA chaos</button>
          <button type="button" onClick={()=>{
            setSimMode("physical"); setMsg("10110010"); setShowDLL(false);
            addLog("Preset: PHY-only — edit bit string in the bar","physical");
          }} style={pill}>PHY bit pattern</button>
          <button type="button" onClick={()=>{
            setSimMode("datalink"); setFlowCtrl("go_back_n"); setWinSz(4); setErrCtrl("crc32");
            setMacProto("csma_cd"); setShowDLL(true);
            addLog("Preset: Go-Back-N ARQ, window 4","datalink");
          }} style={pill}>Go-Back-N</button>
        </div>
      )}

      {/* ── DLL CONFIG BAR ── */}
      {simMode==="datalink"&&showDLL&&(
        <div style={{background:UI.panel,borderBottom:`1px solid ${UI.border}`,
          padding:"10px 16px",display:"flex",gap:18,flexWrap:"wrap",flexShrink:0,zIndex:40}}>

          <CfgGroup label="Framing" color="#60a5fa" value={framing} onChange={setFraming}
            opts={apiDl.framing.map(v=>({v,l:labelDatalinkOption("framing",v)}))}/>

          <CfgGroup label="Error Control" color="#f87171" value={errCtrl} onChange={setErrCtrl}
            opts={apiDl.error.map(v=>({v,l:labelDatalinkOption("error",v)}))}/>

          <CfgGroup label="MAC / Access Control" color="#fbbf24" value={macProto} onChange={setMacProto}
            opts={apiDl.mac_proto.map(v=>({v,l:labelDatalinkOption("mac_proto",v)}))}/>

          <CfgGroup label="Flow Control (ARQ)" color="#a78bfa" value={flowCtrl} onChange={setFlowCtrl}
            opts={apiDl.flow.map(v=>({v,l:labelDatalinkOption("flow",v)}))}/>

          {framing==="fixed"&&(
            <div>
              <div style={{fontSize:10,color:"#60a5fa",letterSpacing:1,marginBottom:5}}>FIXED FRAME SIZE (BYTES)</div>
              <div style={{display:"flex",alignItems:"center",gap:8}}>
                <input type="range" min={32} max={512} step={32} value={fixedFrameSize}
                  onChange={e=>setFixedFrameSize(parseInt(e.target.value,10))}
                  style={{width:120,accentColor:"#60a5fa"}}/>
                <span style={{fontSize:11,color:"#60a5fa",width:36}}>{fixedFrameSize}</span>
              </div>
              <div style={{fontSize:9,color:"#374151",marginTop:4,maxWidth:200}}>
                Short messages are zero-padded; long payloads truncate to one frame in this demo.
              </div>
            </div>
          )}

          {(flowCtrl==="go_back_n"||flowCtrl==="selective_repeat")&&(
            <div>
              <div style={{fontSize:10,color:"#a78bfa",letterSpacing:1,marginBottom:5}}>WINDOW SIZE</div>
              <div style={{display:"flex",gap:4}}>
                {[2,4,8,16].map(w=>(
                  <button key={w} onClick={()=>setWinSz(w)} style={{
                    ...pill,padding:"4px 10px",fontSize:11,
                    borderColor:winSz===w?"#a78bfa":UI.border,
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
                Inject bit error (backend flips a bit → ERROR_DETECTED / frame drop with CRC)
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
          <div style={{
            minWidth:260,
            maxWidth:380,
            border:`1px solid ${UI.border}`,
            borderRadius:6,
            padding:"7px 9px",
            background:UI.panel2,
          }}>
            <div style={{fontSize:10,color:"#374151",fontWeight:600,marginBottom:4}}>MAC realism notes</div>
            <div style={{fontSize:9,color:UI.textSoft,lineHeight:1.4}}>
              CSMA/CD, CSMA/CA and ALOHA are simulated as protocol-level steps with collision probability and
              retransmission/backoff events, not full PHY timing propagation. Great for learning access behavior,
              but not a bit-accurate Ethernet/Wi-Fi physical emulation.
            </div>
          </div>
        </div>
      )}

        {/* ── BODY: main workspace (topology + PHY plot) | sidebar (palette, layer status, future per-layer forms, log) ── */}
      <div style={{flex:1,display:"flex",overflow:"hidden",minHeight:0}}>

        {/* Main column — keep topology + waveform stacked; later: optional tabs per layer */}
        <div style={{flex:1,display:"flex",flexDirection:"column",overflow:"hidden",minWidth:0}}>

          {/* topology canvas */}
          <div ref={canvasRef}
            style={{flex:1,position:"relative",overflow:"hidden",background:UI.canvas,
              cursor:placePickType?"copy":connectFrom?"crosshair":"default"}}
            onDragOver={handlePaletteDragOver}
            onDrop={handlePaletteDrop}
            onMouseUp={e=>{
              if(!connectFrom||e.button!==0)return;
              if((e.target as HTMLElement).closest("[data-device-id]"))return;
              setConnectFrom(null);
            }}
            onClick={(e)=>{
              setCtxMenu(null); setLinkCtx(null);
              if(placePickType){
                const normalized=normalizeDeviceType(placePickType);
                if(!ACTIVE_DEVICE_TYPES.includes(normalized)){
                  setTopologyHint(`'${placePickType}' is coming soon. Use host/switch/hub for now.`);
                  return;
                }
                const r=canvasRef.current?.getBoundingClientRect();
                if(!r)return;
                const dev=mkDev(normalized,e.clientX-r.left,e.clientY-r.top);
                setDevices(p=>{
                  const next=[...p,dev];
                  if(!srcId)setSrcId(dev.id);
                  else if(!dstId)setDstId(dev.id);
                  return next;
                });
                addLog(`Placed ${dev.label}`,"engine");
                setPlacePickType(null);
                return;
              }
              if(connectFrom)setConnectFrom(null);
            }}>

            {/* dot grid background */}
            <svg style={{position:"absolute",inset:0,width:"100%",height:"100%",
              opacity:.35,pointerEvents:"none"}}>
              <defs>
                <pattern id="dots" width="24" height="24" patternUnits="userSpaceOnUse">
                  <circle cx="12" cy="12" r="0.8" fill="#94a3b8"/>
                </pattern>
              </defs>
              <rect width="100%" height="100%" fill="url(#dots)"/>
            </svg>

            {/* SVG: link visuals (no pointer capture) */}
            <svg style={{position:"absolute",inset:0,width:"100%",height:"100%",pointerEvents:"none"}}>
              <defs>
                <filter id="wirelessGlow" x="-40%" y="-40%" width="180%" height="180%">
                  <feGaussianBlur in="SourceGraphic" stdDeviation="3" result="blur"/>
                  <feMerge>
                    <feMergeNode in="blur"/>
                    <feMergeNode in="SourceGraphic"/>
                  </feMerge>
                </filter>
              </defs>
              {links.map(lnk=>{
                const s=getDevL(lnk.src),d=getDevL(lnk.dst);
                if(!s||!d)return null;
                const isWired=lnk.medium==="wired";
                const active=Object.prototype.hasOwnProperty.call(activeLnkModes,lnk.id);
                const linkMode=active?activeLnkModes[lnk.id]:null;
                const activeClr=
                  linkMode==="flood" ? "#f59e0b" :
                  linkMode==="unicast" ? "#22c55e" :
                  "#34d399";
                const clr=active?activeClr:isWired?"#60a5fa":"#fb923c";
                const sw=active?4:2.8;
                const op=active?1:0.88;
                return(
                  <g key={lnk.id} style={{pointerEvents:"none"}}>
                    {!isWired&&!active&&(
                      <line x1={s.x} y1={s.y} x2={d.x} y2={d.y}
                        stroke="#fb923c" strokeWidth={sw+5} strokeLinecap="round"
                        strokeDasharray="14 10" opacity={0.22}
                        style={{filter:"url(#wirelessGlow)"}}/>
                    )}
                    <line x1={s.x} y1={s.y} x2={d.x} y2={d.y}
                      stroke={clr} strokeWidth={sw}
                      strokeLinecap="round"
                      strokeDasharray={isWired?"none":"14 10"}
                      opacity={op}
                      style={active?{filter:`drop-shadow(0 0 10px ${clr})`}:isWired?{}:{filter:"drop-shadow(0 0 6px rgba(251,146,60,0.45))"}}/>
                  </g>
                );
              })}

              {connectFrom&&(()=>{
                const from=getDevL(connectFrom);
                if(!from)return null;
                const w=pendingMed==="wired";
                const clr=w?"#60a5fa":"#fb923c";
                return(
                  <g key="preview" style={{pointerEvents:"none"}}>
                    {!w&&(
                      <line x1={from.x} y1={from.y} x2={mousePos.x} y2={mousePos.y}
                        stroke="#fb923c" strokeWidth={8} strokeLinecap="round"
                        strokeDasharray="14 10" opacity={0.2}/>)}
                    <line x1={from.x} y1={from.y} x2={mousePos.x} y2={mousePos.y}
                      stroke={clr} strokeWidth={2.8} strokeLinecap="round"
                      strokeDasharray={w?"none":"14 10"} opacity={0.85}/>
                  </g>
                );
              })()}

              {animPkts.map(pkt=>{
                const clr=LAYER_CLR[pkt.layer]||"#34d399";
                return(
                  <g key={pkt.id} transform={`translate(${pkt.x},${pkt.y})`}>
                    <circle r={11} fill={clr} opacity={0.92}
                      style={{filter:`drop-shadow(0 0 10px ${clr})`}}/>
                    <text textAnchor="middle" y={4} fontSize={8} fill="#000" fontWeight="bold">
                      {pkt.layer==="datalink"?"FRM":"BIT"}
                    </text>
                  </g>
                );
              })}
            </svg>

            {/* Wide transparent strokes for right-click link editing (under device nodes) */}
            <svg style={{position:"absolute",inset:0,width:"100%",height:"100%",pointerEvents:"auto",zIndex:5}}
              onDragOver={handlePaletteDragOver}
              onDrop={handlePaletteDrop}>
              {links.map(lnk=>{
                const s=getDevL(lnk.src),d=getDevL(lnk.dst);
                if(!s||!d)return null;
                return(
                  <line key={"hit-"+lnk.id}
                    x1={s.x} y1={s.y} x2={d.x} y2={d.y}
                    stroke="transparent"
                    strokeWidth={22}
                    strokeLinecap="round"
                    style={{cursor:"context-menu",pointerEvents:"stroke"}}
                    onContextMenu={e=>{
                      e.preventDefault();
                      e.stopPropagation();
                      const r=canvasRef.current?.getBoundingClientRect();
                      setLinkCtx({x:e.clientX-(r?.left??0),y:e.clientY-(r?.top??0),linkId:lnk.id});
                      setCtxMenu(null);
                    }}/>
                );
              })}
            </svg>

            {/* device nodes */}
            {devices.map(dev=>{
              const meta=DEVICE_META[dev.type];
              const isSrc=dev.id===srcId, isDst=dev.id===dstId, flash=dev.id===flashDev;
              const bc=isSrc?"#34d399":isDst?"#f87171":meta.color;
              return(
                <div key={dev.id} data-device-id={dev.id} style={{
                  position:"absolute",left:dev.x-36,top:dev.y-34,width:72,height:68,
                  background:flash?rgba("#34d399",.18):rgba(meta.color,.12),
                  border:`1.5px solid ${bc}`,borderRadius:12,
                  display:"flex",flexDirection:"column",alignItems:"center",justifyContent:"center",
                  cursor:"grab",transition:"background .12s,box-shadow .12s",zIndex:10,userSelect:"none",
                  boxShadow:flash?`0 0 22px ${rgba("#34d399",.55)}`:
                    (isSrc||isDst)?`0 0 10px ${rgba(bc,.35)}`:"0 2px 8px rgba(15,23,42,0.08)",
                }}
                  onDragOver={handlePaletteDragOver}
                  onDrop={handlePaletteDrop}
                  onDoubleClick={e=>{
                    e.stopPropagation();
                    openDeviceEdit(dev);
                  }}
                  onMouseDown={e=>{
                    if(e.button!==0||connectFrom)return;
                    e.stopPropagation();e.preventDefault();
                    dragRef.current={id:dev.id,ox:e.clientX-dev.x,oy:e.clientY-dev.y};
                  }}
                  onMouseUp={e=>{
                    if(e.button!==0||!connectFrom)return;
                    const el=e.target as HTMLElement;
                    if(connectFrom===dev.id){
                      if(el.closest("[data-connect-port]"))return;
                      e.stopPropagation();
                      setConnectFrom(null);
                      return;
                    }
                    e.stopPropagation();
                    addLink(connectFrom,dev.id,pendingMed);
                    setConnectFrom(null);
                  }}
                  onClick={e=>{
                    e.stopPropagation();
                    if(connectFrom&&connectFrom!==dev.id){
                      addLink(connectFrom,dev.id,pendingMed);
                      setConnectFrom(null);
                      return;
                    }
                    if(!connectFrom&&dev.type==="switch"){
                      addLog(`Switch ${dev.label}: ${portCountFor(dev.id)} port(s) connected`,"engine");
                    }
                  }}
                  onContextMenu={e=>{
                    e.preventDefault();e.stopPropagation();
                    const r=canvasRef.current?.getBoundingClientRect();
                    setLinkCtx(null);
                    setCtxMenu({x:e.clientX-(r?.left??0),y:e.clientY-(r?.top??0),devId:dev.id});
                  }}
                  onMouseEnter={()=>setTooltip({x:dev.x+40,y:dev.y-40,dev})}
                  onMouseLeave={()=>setTooltip(null)}
                >
                  <div
                    data-connect-port=""
                    title="Connect: drag to another device, release · Shift = wireless link"
                    onMouseDown={e=>{
                      e.stopPropagation(); e.preventDefault();
                      setConnectFrom(dev.id);
                      setPendingMed(e.shiftKey?"wireless":"wired");
                      setCtxMenu(null); setLinkCtx(null);
                    }}
                    style={{
                      position:"absolute",right:-5,top:"50%",marginTop:-5,
                      width:10,height:10,borderRadius:"50%",background:meta.color,
                      border:`1.5px solid ${UI.borderHi}`,cursor:"crosshair",zIndex:12,
                      boxShadow:`0 0 8px ${rgba(meta.color,.6)}`,
                    }}/>
                  <div style={{fontSize:24,lineHeight:1}}>{meta.icon}</div>
                  <div style={{fontSize:9,color:UI.text,marginTop:2,maxWidth:66,
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
              <div style={{position:"fixed",left:overlayBaseX+tooltip.x,top:overlayBaseY+tooltip.y,
                background:UI.panel,border:`1px solid ${UI.borderHi}`,borderRadius:8,
                padding:"10px 14px",fontSize:11,pointerEvents:"none",zIndex:1200,
                lineHeight:1.9,boxShadow:"0 8px 28px rgba(15,23,42,0.12)",minWidth:185}}>
                <div style={{color:DEVICE_META[tooltip.dev.type].color,fontWeight:700,marginBottom:3}}>
                  {tooltip.dev.label}
                </div>
                <div style={{color:UI.textMuted}}>Type: <span style={{color:UI.text}}>{tooltip.dev.type}</span></div>
                <div style={{color:UI.textMuted}}>IP: <span style={{color:"#2563eb"}}>{tooltip.dev.ip}</span></div>
                <div style={{color:UI.textMuted}}>MAC: <span style={{color:"#7c3aed",fontSize:10}}>{tooltip.dev.mac}</span></div>
                <div style={{color:UI.textMuted}}>TCP/IP: <span style={{color:"#059669"}}>layers 0–{tooltip.dev.layers}</span></div>
                <div style={{color:UI.textMuted}}>Ports: <span style={{color:"#0f766e"}}>{portCountFor(tooltip.dev.id)}</span></div>
                {tooltip.dev.id===srcId&&<div style={{color:"#34d399",marginTop:3}}>📤 SOURCE</div>}
                {tooltip.dev.id===dstId&&<div style={{color:"#f87171",marginTop:3}}>📥 DESTINATION</div>}
              </div>
            )}

            {/* context menu */}
            {ctxMenu&&(
              <div style={{position:"fixed",left:overlayBaseX+ctxMenu.x,top:overlayBaseY+ctxMenu.y,
                background:UI.panel,border:`1px solid ${UI.borderHi}`,borderRadius:9,
                padding:4,zIndex:1300,minWidth:210,boxShadow:"0 8px 28px rgba(15,23,42,0.15)"}}
                onClick={e=>e.stopPropagation()}>
                <div style={{padding:"3px 10px 5px",color:UI.textSoft,fontSize:10,letterSpacing:1}}>
                  CONNECT USING
                </div>
                {([["wired","⬛ Wired","#3b82f6"],
                   ["wireless","〰 Wireless","#f59e0b"]] as const).map(([m,label,clr])=>(
                  <CtxItem key={m} label={label} color={clr} action={()=>{
                    setPendingMed(m as MediumType);
                    setConnectFrom(ctxMenu.devId);
                    setCtxMenu(null);
                  }}/>
                ))}
                <CtxSep/>
                <CtxItem label="✎ Edit device…" color={UI.text} action={()=>{
                  const d=getDevL(ctxMenu.devId);
                  if(d) openDeviceEdit(d);
                  setCtxMenu(null);
                }}/>
                <CtxSep/>
                <CtxItem label="📤 Set as Source" color="#34d399" action={()=>{
                  if(!isEndpointNodeId(ctxMenu.devId)){
                    addLog("Only end devices can be Source.","engine");
                    setCtxMenu(null);
                    return;
                  }
                  setSrcId(ctxMenu.devId);
                  addLog(`Source → ${getDevL(ctxMenu.devId)?.label}`,"engine");
                  setCtxMenu(null);
                }}/>
                <CtxItem label="📥 Set as Destination" color="#f87171" action={()=>{
                  if(!isEndpointNodeId(ctxMenu.devId)){
                    addLog("Only end devices can be Destination.","engine");
                    setCtxMenu(null);
                    return;
                  }
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

            {linkCtx&&(()=>{
              const lk=links.find(l=>l.id===linkCtx.linkId);
              const a=lk?getDevL(lk.src):undefined,b=lk?getDevL(lk.dst):undefined;
              return(
                <div style={{position:"fixed",left:overlayBaseX+linkCtx.x,top:overlayBaseY+linkCtx.y,
                  background:UI.panel,border:`1px solid ${UI.borderHi}`,borderRadius:9,
                  padding:4,zIndex:1300,minWidth:200,boxShadow:"0 8px 28px rgba(15,23,42,0.15)"}}
                  onClick={e=>e.stopPropagation()}>
                  <div style={{padding:"3px 10px 5px",color:UI.textSoft,fontSize:10,letterSpacing:1}}>
                    LINK · {a?.label??"?"} ↔ {b?.label??"?"}
                  </div>
                  <CtxItem label="⬛ Wired" color="#60a5fa" action={()=>{
                    if(lk) updateLinkMedium(lk.id,"wired");
                  }}/>
                  <CtxItem label="〰 Wireless" color="#fb923c" action={()=>{
                    if(lk) updateLinkMedium(lk.id,"wireless");
                  }}/>
                  <CtxSep/>
                  <CtxItem label="✕ Remove Link" color="#ef4444" action={()=>{
                    if(lk) removeLink(lk.id);
                  }} danger/>
                </div>
              );
            })()}
          </div>

          {/* ── WAVEFORM PANEL (resizable) ── */}
          <div style={{height:wavePan.sz,background:UI.wavePanel,
            borderTop:`1px solid ${UI.border}`,flexShrink:0,position:"relative"}}>
            {/* resize handle */}
            <div onMouseDown={wavePan.handle} style={{
              position:"absolute",top:-4,left:0,right:0,height:8,
              cursor:"ns-resize",zIndex:10,display:"flex",justifyContent:"center",alignItems:"center"}}>
              <div style={{width:44,height:3,background:UI.borderHi,borderRadius:2}}/>
            </div>
            <div style={{padding:"3px 12px 0",display:"flex",alignItems:"center",gap:8,height:20}}>
              <span style={{fontSize:9,letterSpacing:1,color:"#374151",textTransform:"uppercase"}}>
                Waveform
              </span>
              <span style={{fontSize:9,color:(ENC_COLORS as Record<string,string>)[encoding]||"#34d399"}}>
                {encoding}
              </span>
              <span style={{fontSize:9,color:"#374151"}} title="From Advanced">
                {clockRate} Hz · {samplesPerBit}/bit
              </span>
              <div style={{flex:1}}/>
            </div>
            <div ref={waveWrapRef} style={{width:"100%"}}>
              <canvas ref={waveRef} width={640} height={Math.max(40,wavePan.sz-22)}
                style={{width:"100%",height:wavePan.sz-22,display:"block"}}/>
            </div>
          </div>

          {/* Data path — derived from last successful simulate() response */}
          <div style={{
            borderTop:`1px solid ${UI.border}`,background:UI.panel2,flexShrink:0,
            maxHeight:showPipeline?220:32,minHeight:showPipeline?undefined:32,
            display:"flex",flexDirection:"column",overflow:"hidden",
          }}>
            <button type="button" onClick={()=>setShowPipeline(s=>!s)} style={{
              flexShrink:0,display:"flex",alignItems:"center",gap:8,
              padding:"6px 12px",background:"transparent",border:"none",borderBottom:showPipeline?`1px solid ${UI.border}`:"none",
              cursor:"pointer",fontFamily:"inherit",textAlign:"left",
              color:"#60a5fa",fontSize:10,letterSpacing:1,textTransform:"uppercase",
            }}>
              <span style={{width:12}}>{showPipeline?"▼":"▶"}</span>
              <span>Data path</span>
              {!pipeline&&<span style={{color:"#374151",textTransform:"none",letterSpacing:0,marginLeft:4}}>— run simulate</span>}
            </button>
            {showPipeline&&pipeline&&(
              <div style={{overflowY:"auto",padding:"8px 12px 12px",fontSize:10,lineHeight:1.55,color:UI.textMuted}}>
                <div style={{color:"#dc2626",marginBottom:6}}>Application / data</div>
                <div style={{fontFamily:"monospace",wordBreak:"break-all",color:UI.text,marginBottom:10}}>
                  {pipeline.mode==="datalink"?pipeline.userData:pipeline.userData||"(no bits)"}
                </div>

                {pipeline.framing&&(
                  <>
                    <div style={{color:"#2563eb",marginBottom:4}}>DLL · framing</div>
                    <div>scheme: {ph(pipeline.framing,"scheme")} · raw bytes: {ph(pipeline.framing,"raw_bytes")} · framed: {ph(pipeline.framing,"framed_bytes")}</div>
                    {ph(pipeline.framing,"payload_hex_preview")&&(
                      <div style={{marginTop:4,fontFamily:"monospace",fontSize:9,wordBreak:"break-all",color:"#1d4ed8"}}>
                        payload hex: {ph(pipeline.framing,"payload_hex_preview")}
                      </div>
                    )}
                    {ph(pipeline.framing,"framed_hex_preview")&&(
                      <div style={{marginTop:2,fontFamily:"monospace",fontSize:9,wordBreak:"break-all",color:"#1d4ed8"}}>
                        framed hex: {ph(pipeline.framing,"framed_hex_preview")}
                      </div>
                    )}
                  </>
                )}

                {pipeline.frameSent&&(
                  <>
                    <div style={{color:"#2563eb",marginTop:10,marginBottom:4}}>DLL · frame on wire (sent)</div>
                    <div>
                      framing: {ph(pipeline.frameSent,"framing_scheme")} · error: {ph(pipeline.frameSent,"error_scheme")} · MAC: {ph(pipeline.frameSent,"mac_protocol")} · ARQ: {ph(pipeline.frameSent,"arq_protocol")}
                    </div>
                    {ph(pipeline.frameSent,"protected_len")&&(
                      <div style={{marginTop:2}}>protected_len: {ph(pipeline.frameSent,"protected_len")}</div>
                    )}
                    {ph(pipeline.frameSent,"protected_hex_preview")&&(
                      <div style={{marginTop:4,fontFamily:"monospace",fontSize:9,wordBreak:"break-all",color:"#1d4ed8"}}>
                        protected hex: {ph(pipeline.frameSent,"protected_hex_preview")}
                      </div>
                    )}
                    {ph(pipeline.frameSent,"on_wire_hex_preview")&&(
                      <div style={{marginTop:2,fontFamily:"monospace",fontSize:9,wordBreak:"break-all",color:"#1d4ed8"}}>
                        on-wire hex: {ph(pipeline.frameSent,"on_wire_hex_preview")}
                      </div>
                    )}
                  </>
                )}

                {pipeline.flow&&(
                  <>
                    <div style={{color:"#6d28d9",marginTop:10,marginBottom:4}}>DLL · flow (ARQ)</div>
                    <div>protocol: {ph(pipeline.flow,"protocol")} · window: {ph(pipeline.flow,"window_size")} · sent: {ph(pipeline.flow,"frames_sent")} · retrans: {ph(pipeline.flow,"retransmissions")} · η: {ph(pipeline.flow,"efficiency")}</div>
                  </>
                )}

                {pipeline.errorDetected&&(
                  <>
                    <div style={{color:"#f87171",marginTop:10,marginBottom:4}}>DLL · error check</div>
                    <div>scheme: {pipeline.errorDetected.scheme} · dropped: {String(pipeline.errorDetected.dropped)}</div>
                    {pipeline.errorDetected.detail&&(
                      <div style={{marginTop:2,color:"#fca5a5"}}>{pipeline.errorDetected.detail}</div>
                    )}
                  </>
                )}

                {pipeline.frameDropped&&(
                  <div style={{color:"#f97316",marginTop:10}}>DLL · frame dropped: {pipeline.frameDropped}</div>
                )}

                {(pipeline.phyBits||pipeline.signal)&&(
                  <>
                    <div style={{color:"#047857",marginTop:10,marginBottom:4}}>PHY</div>
                    {pipeline.phyBits&&(
                      <div>
                        BITS_SENT · encoding: {pipeline.phyBits.encoding||"—"}
                        {pipeline.phyBits.clock_rate?` · clock ${pipeline.phyBits.clock_rate} Hz`:""}
                        {pipeline.phyBits.raw_bits?(
                          <span style={{display:"block",marginTop:4,fontFamily:"monospace",fontSize:9,wordBreak:"break-all",color:"#047857"}}>
                            bits: {pipeline.phyBits.raw_bits.length>120?pipeline.phyBits.raw_bits.slice(0,120)+"…":pipeline.phyBits.raw_bits}
                          </span>
                        ):null}
                      </div>
                    )}
                    {pipeline.signal&&(
                      <div style={{marginTop:4}}>SIGNAL_DRAWN · encoding: {pipeline.signal.encoding||"—"} · sample_rate: {pipeline.signal.sample_rate||"—"}</div>
                    )}
                  </>
                )}

                {pipeline.received&&(
                  <>
                    <div style={{color:"#047857",marginTop:10,marginBottom:4}}>Destination · frame received</div>
                    <div>payload_len: {ph(pipeline.received,"payload_len")}</div>
                    {ph(pipeline.received,"payload_text_preview")&&(
                      <div style={{marginTop:4,color:UI.text,whiteSpace:"pre-wrap",wordBreak:"break-word"}}>
                        text: {ph(pipeline.received,"payload_text_preview")}
                      </div>
                    )}
                    {ph(pipeline.received,"payload_hex_preview")&&(
                      <div style={{marginTop:4,fontFamily:"monospace",fontSize:9,wordBreak:"break-all",color:"#047857"}}>
                        payload hex: {ph(pipeline.received,"payload_hex_preview")}
                      </div>
                    )}
                    {ph(pipeline.received,"error_check")&&(
                      <div style={{marginTop:4,color:"#9ca3af"}}>check: {ph(pipeline.received,"error_check")}</div>
                    )}
                  </>
                )}

                {!pipeline.framing&&!pipeline.frameSent&&!pipeline.received&&!pipeline.errorDetected&&!pipeline.frameDropped&&pipeline.mode==="physical"&&(
                  <div style={{color:"#374151",marginTop:6}}>PHY-only run — DLL stages omitted. BITS_SENT / SIGNAL_DRAWN appear above when present.</div>
                )}
              </div>
            )}
            {showPipeline&&!pipeline&&(
              <div style={{padding:"4px 12px 10px",fontSize:10,color:"#374151"}}>
                Run a successful simulation to see data → DLL frame → PHY → receive.
              </div>
            )}
          </div>
        </div>

        {/* Sidebar — order: devices → layer strip → (insert Network/Transport/App panels here) → event log */}
        <div style={{width:sidebar.sz,background:UI.panel,borderLeft:`1px solid ${UI.border}`,
          display:"flex",flexDirection:"column",overflow:"hidden",flexShrink:0,position:"relative",minHeight:0}}>

          {/* sidebar resize handle */}
          <div onMouseDown={sidebar.handle} style={{
            position:"absolute",left:-4,top:0,bottom:0,width:8,
            cursor:"ew-resize",zIndex:20,display:"flex",alignItems:"center",justifyContent:"center"}}>
            <div style={{width:3,height:44,background:UI.borderHi,borderRadius:2}}/>
          </div>

          {/* device palette */}
          <SideSection title="Add Device">
            <label style={{fontSize:9,color:UI.textSoft,display:"block",marginBottom:4}}>Device type</label>
            <div style={{
              display:"flex",gap:8,alignItems:"center",padding:"6px 8px",
              borderRadius:6,border:`1px solid ${UI.border}`,background:UI.panel3,
            }}>
              <span title="Drag to canvas"
                draggable
                onDragStart={e=>{
                  const t=paletteDeviceType;
                  paletteDragRef.current=t;
                  setDraggingType(t);
                  e.dataTransfer.effectAllowed="copy";
                  e.dataTransfer.setData("text/plain",t);
                }}
                onDragEnd={()=>{
                  paletteDragRef.current=null;
                  setDraggingType(null);
                }}
                style={{
                  cursor:"grab",fontSize:16,lineHeight:1,color:UI.textSoft,userSelect:"none",
                  padding:"2px 4px",borderRadius:4,border:`1px dashed ${UI.borderHi}`,
                }} aria-hidden>⠿</span>
              <span style={{fontSize:22,lineHeight:1}} aria-hidden>{DEVICE_META[paletteDeviceType].icon}</span>
              <select value={paletteDeviceType}
                onChange={e=>{
                  const t=normalizeDeviceType(e.target.value as DeviceType);
                  setPaletteDeviceType(t);
                  setPlacePickType(t);
                }}
                style={{...selSt,flex:1,minWidth:0}}
                aria-label="Device type to place">
                {ACTIVE_DEVICE_TYPES.map(t=>(
                  <option key={t} value={t}>{deviceLabel(t)}</option>
                ))}
                {COMING_SOON_DEVICE_TYPES.map(t=>(
                  <option key={t} value={t} disabled>{deviceLabel(t)} (coming soon)</option>
                ))}
              </select>
            </div>
            <div style={{marginTop:7,fontSize:9,color:UI.textSoft}}>
              Supported now: <span style={{color:UI.text}}>host, switch, hub</span>
            </div>
            {placePickType&&(
              <div style={{fontSize:9,color:"#059669",marginTop:6,lineHeight:1.35}}>
                Click canvas to place <strong>{placePickType}</strong> · Esc cancels
              </div>
            )}
            {topologyHint&&(
              <div style={{fontSize:9,color:"#b45309",marginTop:6,lineHeight:1.35}}>{topologyHint}</div>
            )}
            <label style={{fontSize:9,color:UI.textSoft,display:"block",marginTop:10,marginBottom:4}}>Topology preset</label>
            <select key={presetSelectKey} defaultValue="demo"
              onChange={e=>applyTopologyPreset(e.target.value as TopologyPreset)}
              style={{...selSt,width:"100%",boxSizing:"border-box"}}
              aria-label="Load built-in topology">
              <option value="demo">Demo (sample lab)</option>
              <option value="star">Star</option>
              <option value="bus">Bus</option>
              <option value="mesh">Mesh (full)</option>
            </select>
            <button type="button" onClick={()=>{
              setDevices([]); setLinks([]); setSrcId(null); setDstId(null);
              setPlacePickType(null); setConnectFrom(null); setCtxMenu(null); setLinkCtx(null);
              lnkSeq=0; idSeq=0;
              setPresetSelectKey(k=>k+1);
              setTopologyHint("Right-click a device to set Source and Destination when you add nodes.");
              addLog("Canvas cleared — choose a device type, then click the canvas to place","engine");
            }} style={{
              ...pill,marginTop:10,width:"100%",fontSize:10,
              color:"#9a3412",borderColor:"#fdba74",background:rgba("#fb923c",.08),
            }}>
              Clear canvas (start fresh topology)
            </button>
          </SideSection>

          <SideSection title="TCP/IP stack">
            <p style={{margin:0,fontSize:10,color:UI.textMuted,lineHeight:1.5}}>
              Physical and Data Link are driven by the mode bar and DLL config. Application, Transport, and Network are not editable on this page yet (reserved for future work).
            </p>
            <div style={{display:"flex",flexWrap:"wrap",gap:"6px 10px",alignItems:"center",marginTop:8}}>
              {TCPIP_LAYERS.map(l=>(
                <span key={l.name} style={{display:"inline-flex",alignItems:"center",gap:4,fontSize:9,color:UI.textSoft}}>
                  <span style={{width:6,height:6,borderRadius:"50%",background:l.color,flexShrink:0}}/>
                  {l.name}{l.live?" (live)":""}
                </span>
              ))}
            </div>
            {activeLayer&&(
              <div style={{fontSize:9,color:UI.textSoft,marginTop:8}}>
                Last event layer:{" "}
                <span style={{color:UI.text}}>
                  {({physical:"Physical",datalink:"Data Link",network:"Network",
                    transport:"Transport",application:"Application",engine:"Engine"} as Record<string,string>)[activeLayer]||activeLayer}
                </span>
              </div>
            )}
          </SideSection>

          <SideSection title="ITL351 Matrix">
            <div style={{display:"grid",gap:4,fontSize:10,color:UI.textMuted}}>
              {[
                ["Topology editor + send/receive","done"],
                ["PHY encoding + waveform","done"],
                ["DLL error/access/flow protocols","done"],
                ["Switch learning + unknown flood","done"],
                ["Topology-aware backend forwarding",topologyMode?"done":"ready"],
                ["Broadcast/collision domain counts",domainStats?"done":"ready"],
              ].map(([name,state])=>(
                <div key={name} style={{display:"flex",alignItems:"center",gap:6}}>
                  <span style={{color:state==="done"?"#059669":"#b45309"}}>{state==="done"?"✓":"•"}</span>
                  <span>{name}</span>
                </div>
              ))}
            </div>
            {domainStats&&(
              <div style={{marginTop:8,fontSize:10,color:UI.textSoft}}>
                Domains: BD {domainStats.broadcast_domains} · CD {domainStats.collision_domains}
              </div>
            )}
          </SideSection>

          <SideSection title="Switch MAC Tables">
            <div style={{display:"flex",gap:6,alignItems:"center",marginBottom:8}}>
              <button
                type="button"
                onClick={()=>{
                  setResetLearning(true);
                  setSwitchTables({});
                  setLearningSummary([]);
                  addLog("MAC learning tables scheduled for reset on next simulate.","engine");
                }}
                style={{...pill,padding:"3px 8px",fontSize:10}}
                title="Reset persistent switch learning tables"
              >
                Reset tables
              </button>
              <span style={{fontSize:9,color:UI.textSoft}}>
                {topologyMode?"Persistent across runs":"Topology mode off"}
              </span>
            </div>
            {Object.keys(switchPorts).length===0?(
              <div style={{fontSize:10,color:UI.textSoft}}>No learned switch entries yet.</div>
            ):(
              <div style={{display:"grid",gap:8,maxHeight:280,overflowY:"auto",paddingRight:2}}>
                {Object.entries(switchPorts).map(([sw,ports])=>(
                  <div key={sw} style={{border:`1px solid ${UI.border}`,borderRadius:6,padding:6}}>
                    <div style={{fontSize:10,color:"#0f766e",marginBottom:4,fontWeight:600}}>
                      {devLabel(sw)}
                    </div>
                    {ports.length===0?(
                      <div style={{fontSize:9,color:UI.textSoft}}>empty</div>
                    ):(
                      <div style={{display:"grid",gridTemplateColumns:"1fr 1fr 1fr",rowGap:3,columnGap:8,fontSize:9,color:UI.textMuted}}>
                        <span style={{color:UI.textSoft}}>Port</span>
                        <span style={{color:UI.textSoft}}>Neighbor</span>
                        <span style={{color:UI.textSoft}}>Learned MAC</span>
                        {ports.map((p,idx)=>{
                          const mac=(switchTables[sw]||[]).find(r=>r.port===p.port)?.mac ?? "—";
                          return(
                          <div key={`${sw}-${p.port}-${idx}`} style={{display:"contents"}}>
                            <span style={{fontFamily:"monospace",color:"#0f766e"}}>{p.port.split(":").pop() ?? p.port}</span>
                            <span style={{fontFamily:"monospace",color:UI.textSoft}}>{devLabel(p.neighbor)}</span>
                            <span style={{fontFamily:"monospace",color:UI.text}}>{mac}</span>
                          </div>
                        );})}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
            {learningSummary.length>0&&(
              <div style={{marginTop:8,fontSize:9,color:UI.textSoft}}>
                Last learn: {learningSummaryText(learningSummary,devLabel)}
              </div>
            )}
          </SideSection>

          {/* event log */}
          <SideSection title={`Event Log (${filtLog.length})`} defaultOpen={false} style={{flex:1,display:"flex",flexDirection:"column",overflow:"hidden",borderTop:"1px solid #cbd5e1"}}>
            <div style={{padding:"0 0 3px",display:"flex",alignItems:"center",gap:6,flexShrink:0}}>
              <button onClick={()=>setLog([])} style={{...pill,padding:"2px 7px",fontSize:9,color:"#374151"}}>
                Clear
              </button>
            </div>
            <div style={{display:"flex",gap:3,padding:"0 0 5px",flexShrink:0,flexWrap:"wrap"}}>
              {["all","physical","datalink","network","transport","application","engine"].map(f=>{
                const clr=LAYER_CLR[f]||"#34d399";
                return(
                  <button key={f} onClick={()=>setLogFilter(f)} style={{
                    ...pill,padding:"2px 7px",fontSize:9,
                    borderColor:logFilter===f?clr:"#cbd5e1",
                    color:logFilter===f?clr:"#374151",
                    background:logFilter===f?rgba(clr,.12):"transparent",
                  }}>{f==="all"?"ALL":f.slice(0,3).toUpperCase()}</button>
                );
              })}
            </div>
            <div style={{flex:1,overflowY:"auto",padding:"2px 0",fontSize:10,lineHeight:1.55}}>
              {filtLog.map((e,i)=>(
                <div key={i} style={{padding:"2px 4px",borderRadius:2,marginBottom:1,
                  color:LAYER_CLR[e.layer]||"#4b5563",opacity:i>60?0.55:1}}>
                  <span style={{color:"#cbd5e1",fontSize:9}}>[{e.t}]</span> {e.msg}
                </div>
              ))}
              {filtLog.length===0&&(
                <div style={{color:"#cbd5e1",padding:"8px 4px",fontSize:10}}>
                  No events — run a simulation first
                </div>
              )}
            </div>
          </SideSection>
        </div>
      </div>

      {editTarget&&(
        <div role="dialog" aria-modal="true" aria-labelledby="device-edit-title"
          style={{position:"fixed",inset:0,background:"rgba(0,0,0,0.55)",zIndex:2000,
            display:"flex",alignItems:"center",justifyContent:"center"}}
          onClick={()=>{setEditTarget(null);setEditErr("");}}>
          <div style={{
            background:UI.panel,border:`1px solid ${UI.borderHi}`,borderRadius:12,padding:18,
            minWidth:300,maxWidth:"min(420px,92vw)",boxShadow:"0 24px 64px rgba(15,23,42,0.18)",
          }} onClick={e=>e.stopPropagation()}>
            <div id="device-edit-title" style={{fontSize:11,color:"#60a5fa",marginBottom:14,letterSpacing:1}}>
              EDIT DEVICE
            </div>
            <label style={{fontSize:9,color:"#6b7280",display:"block",marginBottom:3}}>Label</label>
            <input value={editLabel} onChange={e=>{setEditLabel(e.target.value);setEditErr("");}}
              style={{...selSt,width:"100%",marginBottom:10,boxSizing:"border-box"}} autoFocus/>
            <label style={{fontSize:9,color:"#6b7280",display:"block",marginBottom:3}}>IPv4</label>
            <input value={editIp} onChange={e=>{setEditIp(e.target.value);setEditErr("");}}
              placeholder="192.168.1.1"
              style={{...selSt,width:"100%",marginBottom:10,boxSizing:"border-box"}}/>
            <label style={{fontSize:9,color:"#6b7280",display:"block",marginBottom:3}}>MAC</label>
            <input value={editMac} onChange={e=>{setEditMac(e.target.value);setEditErr("");}}
              placeholder="aa:bb:cc:dd:ee:ff"
              style={{...selSt,width:"100%",marginBottom:10,boxSizing:"border-box",fontSize:10}}/>
            {editErr&&<div style={{color:"#f87171",fontSize:10,marginBottom:8}}>{editErr}</div>}
            <div style={{display:"flex",gap:8,marginTop:12,justifyContent:"flex-end"}}>
              <button type="button" onClick={()=>{setEditTarget(null);setEditErr("");}} style={pill}>Cancel</button>
              <button type="button" onClick={saveDeviceEdit} style={{
                ...pill,borderColor:"#34d399",color:"#34d399",background:rgba("#34d399",.1),
              }}>Save</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/* ── helper components ──────────────────────────────────────────────────── */
function Div(){return <div style={{width:1,height:22,background:UI.border,margin:"0 2px"}}/>;}
function SideSection({title,hint,children,defaultOpen=true,style}:{title:string;hint?:string;children:React.ReactNode;defaultOpen?:boolean;style?:React.CSSProperties}){
  const [open,setOpen]=useState(defaultOpen);
  return(
    <div style={{borderBottom:`1px solid ${UI.border}`,padding:"9px 10px",...style}}>
      <button type="button" onClick={()=>setOpen(o=>!o)} style={{
        width:"100%",display:"flex",gap:6,alignItems:"baseline",marginBottom:open?7:0,
        background:"transparent",border:"none",padding:0,cursor:"pointer",fontFamily:"inherit",textAlign:"left",
      }}>
        <span style={{fontSize:9,color:UI.textSoft,width:10,display:"inline-block"}}>{open?"▾":"▸"}</span>
        <span style={{fontSize:9,letterSpacing:1.5,color:UI.textMuted,textTransform:"uppercase"}}>{title}</span>
        {hint&&<span style={{fontSize:9,color:UI.textSoft}}>{hint}</span>}
      </button>
      {open&&children}
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
          border:`1px solid ${value===o.v?color:UI.border}`,
          borderRadius:5,padding:"5px 10px",fontSize:10,
          color:value===o.v?color:UI.textMuted,cursor:"pointer",
          textAlign:"left",fontFamily:"inherit",transition:"all .1s",
        }}>{o.l}</button>
      ))}
    </div>
  );
}
function CtxItem({label,action,color=UI.text,danger=false}:{
  label:string;action:()=>void;color?:string;danger?:boolean;}){
  return(
    <div style={{padding:"6px 12px",cursor:"pointer",borderRadius:5,
      color:danger?"#ef4444":color,transition:"background .1s",fontSize:11}}
      onMouseEnter={e=>(e.currentTarget.style.background=UI.ctxHover)}
      onMouseLeave={e=>(e.currentTarget.style.background="transparent")}
      onClick={action}>{label}</div>
  );
}
function CtxSep(){return <div style={{height:1,background:UI.border,margin:"3px 0"}}/>;}
