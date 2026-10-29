import { useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { McpAppCard } from "@/components/thread/activity/McpApp";
import { initializeI18n } from "@/i18n";
import "../src/globals.css";

const html = `<style>body{font:15px system-ui;margin:24px;color:#25402d}h1{font-size:22px}button{padding:10px 18px;border:0;border-radius:8px;background:#21543b;color:white}output{display:block;margin:12px 0}</style>
<h1>Weather dashboard</h1><output id="weather">Connecting…</output><output id="isolation"></output><output id="network"></output><button id="filter">Show northern stations</button><button id="cancel">Cancel request</button><output id="result"></output>
<script>
try { parent.document.body; document.getElementById('isolation').textContent='Parent access allowed'; } catch { document.getElementById('isolation').textContent='Parent access blocked'; }
fetch('https://mcp-app-network-probe.invalid/').then(()=>document.getElementById('network').textContent='Network allowed').catch(()=>document.getElementById('network').textContent='Network blocked');
const send=(message)=>parent.postMessage({jsonrpc:'2.0',...message},'*');
addEventListener('message',(event)=>{
 if(event.source!==parent)return;
 const message=event.data;
 if(message.id===1 && message.result){send({method:'ui/notifications/initialized'});}
 if(message.method==='ui/notifications/tool-result'){document.getElementById('weather').textContent='Temperature: '+message.params.structuredContent.temperature+'°C';}
 if(message.id===2){document.getElementById('result').textContent=message.error?'Call failed':message.result?.content?.[0]?.text??'No output';}
});
document.getElementById('filter').onclick=()=>send({id:2,method:'tools/call',params:{name:'filter',arguments:{region:'north'}}});
document.getElementById('cancel').onclick=()=>send({method:'notifications/cancelled',params:{requestId:2,reason:'Cancelled before approval'}});
send({id:1,method:'ui/initialize',params:{protocolVersion:'2026-01-26',appInfo:{name:'Weather',version:'1'},appCapabilities:{}}});
</script>`;

function Fixture() {
  const [executed, setExecuted] = useState(0);
  const transport = useMemo(() => ({
    async requestMutation<T>(action: string, payload?: Record<string, unknown>): Promise<T> {
      if (action === "mcp_apps.open") return {
        html, arguments: { city: "Paris" }, result: { content: [], structuredContent: { temperature: 23 } },
      } as T;
      if (action === "mcp_apps.prepare") return { approval_id: "fixture", name: "filter", arguments: { region: "north" } } as T;
      if (!payload?.approved) return { isError: true, content: [{ type: "text", text: "Declined" }] } as T;
      setExecuted((count) => count + 1);
      return { content: [{ type: "text", text: "Northern stations selected" }] } as T;
    },
  }), []);
  return <main className="mx-auto max-w-2xl p-6">
    <h1 className="mb-5 text-lg font-semibold">MCP App host</h1>
    <div data-testid="executed">Executed: {executed}</div>
    <McpAppCard host={{ transport, sessionKey: "websocket:fixture" }} appId={"a".repeat(32)} title="Weather" />
  </main>;
}

await initializeI18n();
createRoot(document.getElementById("root")!).render(<Fixture />);
