"use client";
import { useState } from "react";
type Msg = { role: "user"|"assistant"; text: string };
type ChatResp = { answer: string; sources: string[] };

export default function Page() {
  const [input, setInput] = useState("");
  const [history, setHistory] = useState<Msg[]>([]);

  async function send() {
    if (!input.trim()) return;
    const userMsg = input;
    setHistory((h) => [...h, { role: "user", text: userMsg }]);
    setInput("");
    const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8010";
    const r = await fetch(apiUrl + "/chat", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: userMsg })
    });
    const data: ChatResp = await r.json();
    const cited = data.sources?.length ? `\n\nSources: ${data.sources.join(", ")}` : "";
    setHistory((h) => [...h, { role: "assistant", text: data.answer + cited }]);
  }

  return (
    <main style={{maxWidth: 720, margin: "0 auto", padding: 24}}>
      <h1 style={{fontWeight: 600}}>K-Food Helpdesk</h1>
      <div style={{border:"1px solid #ddd", borderRadius:8, padding:12, height:350, overflowY:"auto", background:"#fff"}}>
        {history.map((m, i) => (
          <div key={i} style={{textAlign: m.role==="user"?"right":"left", marginBottom:8}}>
            <span style={{display:"inline-block", background:m.role==="user"?"#dbeafe":"#f3f4f6", padding:8, borderRadius:8}}>
              {m.text}
            </span>
          </div>
        ))}
      </div>
      <div style={{display:"flex", gap:8, marginTop:12}}>
        <input value={input} onChange={(e) => setInput(e.target.value)}
               placeholder="Ask about refunds, delivery, allergens…" style={{flex:1, border:"1px solid #ccc", borderRadius:6, padding:8}}/>
        <button onClick={send} style={{padding:"8px 16px", borderRadius:6, background:"#111", color:"#fff"}}>Send</button>
      </div>
    </main>
  );
}
