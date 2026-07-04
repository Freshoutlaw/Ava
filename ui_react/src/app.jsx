import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  Sparkles, Wifi, WifiOff, Heart, Mic, MicOff, Send,
  Wrench, Hexagon, Bell, Brain, Target, Camera, CameraOff
} from 'lucide-react';

const WS_URL = 'ws://127.0.0.1:7334';

export default function App() {
  const [connected, setConnected]   = useState(false);
  const [messages, setMessages]     = useState([]);
  const [typing, setTyping]         = useState(false);
  const [input, setInput]           = useState('');
  const [memory, setMemory]         = useState([]);
  const [notices, setNotices]       = useState([]);
  const [toolLog, setToolLog]       = useState([]);
  const [goal, setGoal]             = useState({ current: 0, target: 500000, pct: 0, deadline: '' });
  const [voice, setVoice]           = useState({ listening: false, speaking: false, transcript: '' });
  const [status, setStatus]         = useState({ model: 'llama-3.3-70b-versatile', heartbeat: true });
  const [webcamFrame, setWebcamFrame] = useState(null); // base64 jpeg, or null when not watching

  const wsRef        = useRef(null);
  const reconnectRef  = useRef(null);
  const chatEndRef    = useRef(null);
  const inputRef      = useRef(null);
  const webcamIdleRef = useRef(null);

  // ── WebSocket connection ────────────────────────────────────────────────
  const connect = useCallback(() => {
    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;

    ws.onopen = () => {
      setConnected(true);
      clearTimeout(reconnectRef.current);
    };

    ws.onclose = () => {
      setConnected(false);
      reconnectRef.current = setTimeout(connect, 2000);
    };

    ws.onerror = () => {};

    ws.onmessage = (e) => {
      let ev;
      try { ev = JSON.parse(e.data); } catch { return; }
      handleEvent(ev);
    };
  }, []);

  useEffect(() => {
    connect();
    return () => {
      clearTimeout(reconnectRef.current);
      wsRef.current?.close();
    };
  }, [connect]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, typing]);

  // ── Event router ─────────────────────────────────────────────────────────
  function handleEvent(ev) {
    const { type, data = {} } = ev;
    switch (type) {
      case 'message':
        setMessages(prev => [...prev, { role: data.role, content: data.content, ts: data.ts || nowStr() }]);
        setTyping(false);
        break;
      case 'typing':
        setTyping(!!data.active);
        break;
      case 'tool_call':
        setToolLog(prev => [{ name: data.name, result: data.result || '', agent: false, ts: nowStr() }, ...prev].slice(0, 30));
        break;
      case 'delegate':
        setToolLog(prev => [{ name: `${data.agent} agent`, result: `${data.result_len} chars returned`, agent: true, ts: nowStr() }, ...prev].slice(0, 30));
        break;
      case 'memory':
        setMemory(data.facts || []);
        break;
      case 'notice':
        setNotices(prev => [data, ...prev].slice(0, 20));
        break;
      case 'goal':
        setGoal(g => ({ ...g, ...data }));
        break;
      case 'voice':
        setVoice(v => ({ ...v, ...data }));
        break;
      case 'status':
        setStatus(s => ({ ...s, ...data }));
        break;
      case 'webcam_frame':
        // Live preview frame from vision.py's watch mode. Frames stop
        // arriving when watching is off, so we clear the preview if none
        // shows up for a bit (rather than freezing on the last frame).
        setWebcamFrame(data.image || null);
        clearTimeout(webcamIdleRef.current);
        webcamIdleRef.current = setTimeout(() => setWebcamFrame(null), 3000);
        break;
      case 'error':
        setMessages(prev => [...prev, { role: 'system', content: `⚠ ${data.message || 'Unknown error'}`, ts: nowStr() }]);
        break;
      default: break;
    }
  }

  function nowStr() {
    return new Date().toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
  }

  function sendMessage() {
    const text = input.trim();
    if (!text || !wsRef.current || wsRef.current.readyState !== 1) return;
    wsRef.current.send(JSON.stringify({ type: 'user_message', data: { content: text } }));
    setMessages(prev => [...prev, { role: 'user', content: text, ts: nowStr() }]);
    setTyping(true);
    setInput('');
  }

  function handleKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  }

  const goalCircumference = 2 * Math.PI * 42;
  const goalOffset = goalCircumference - (Math.min(100, goal.pct || 0) / 100) * goalCircumference;

  return (
    <div className="h-screen w-screen grid grid-rows-[52px_1fr_64px] bg-bg text-[#e8e8f0] text-sm select-none">

      {/* ── Top bar ──────────────────────────────────────────────────────── */}
      <header className="flex items-center gap-4 px-5 bg-surface border-b border-border">
        <div className="flex items-center gap-2">
          <Sparkles size={18} className="text-accent" />
          <span className="text-[17px] font-bold tracking-tight text-accent">Ava</span>
        </div>
        <span className="text-xs text-muted">Executive Assistant</span>
        <div className="flex-1" />

        <StatusPill icon={connected ? <Wifi size={12} /> : <WifiOff size={12} />}
                    label={connected ? 'Connected' : 'Reconnecting…'}
                    on={connected} warn={!connected} />
        <StatusPill icon={<Heart size={12} />} label="Heartbeat" on={status.heartbeat} />
        <StatusPill icon={null} label={(status.model || '').replace('llama-3.', 'L3.').replace('-versatile', '')} />
      </header>

      {/* ── Body ─────────────────────────────────────────────────────────── */}
      <div className="grid grid-cols-[230px_1fr_240px] overflow-hidden">

        {/* Left sidebar */}
        <aside className="bg-surface border-r border-border flex flex-col overflow-hidden">
          <div className="flex flex-col items-center py-5 px-4">
            <SectionLabel icon={<Target size={11} />} text="Revenue Goal" />
            <div className="relative w-[110px] h-[110px] mt-2">
              <svg viewBox="0 0 100 100" width="110" height="110" className="-rotate-90">
                <circle cx="50" cy="50" r="42" fill="none" stroke="#2a2a35" strokeWidth="8" />
                <circle cx="50" cy="50" r="42" fill="none" stroke="#00e5a0" strokeWidth="8"
                        strokeLinecap="round"
                        strokeDasharray={goalCircumference}
                        strokeDashoffset={goalOffset}
                        style={{ transition: 'stroke-dashoffset 0.6s ease' }} />
              </svg>
              <div className="absolute inset-0 flex items-center justify-center text-xl font-bold text-accent">
                {(goal.pct || 0).toFixed(1)}%
              </div>
            </div>
            <div className="text-[13px] font-semibold mt-2">
              ${(goal.current || 0).toLocaleString()} / ${(goal.target || 500000).toLocaleString()}
            </div>
            <div className="text-xs text-muted mt-0.5">by {goal.deadline || '—'}</div>
          </div>

          <div className="border-t border-border mt-1" />
          <SectionLabel icon={<Brain size={11} />} text="Memory" className="px-4 pt-3" />
          <div className="flex-1 overflow-y-auto px-3 pb-3 space-y-1.5">
            {memory.length === 0 && <EmptyHint text="No memories yet." />}
            {memory.map((f) => (
              <div key={f.id} className="bg-surface2 border border-border rounded-md px-2.5 py-1.5">
                <div className="text-[10px] text-muted mb-0.5">{f.id} · {f.saved || f.updated || ''}</div>
                <div className="text-xs leading-snug">{f.fact}</div>
              </div>
            ))}
          </div>
        </aside>

        {/* Center chat */}
        <main className="flex flex-col overflow-hidden bg-bg">
          <div className="flex-1 overflow-y-auto px-6 py-5 flex flex-col gap-4">
            {messages.length === 0 && (
              <div className="text-center text-muted text-xs py-8">Connecting to Ava…</div>
            )}
            {messages.map((m, i) => <Message key={i} {...m} />)}
            {typing && <TypingIndicator />}
            <div ref={chatEndRef} />
          </div>
        </main>

        {/* Right sidebar */}
        <aside className="bg-surface border-l border-border flex flex-col overflow-hidden">
          <SectionLabel icon={<Bell size={11} />} text="Notices" className="px-4 pt-4" />
          <div className="px-3 pb-2 space-y-1.5 max-h-[200px] overflow-y-auto">
            {notices.length === 0 && <EmptyHint text="No notices." />}
            {notices.map((n, i) => (
              <div key={i} className={`rounded-r-md pl-2.5 pr-2 py-1.5 border-l-[3px] bg-surface2 ${
                n.priority === 'critical' ? 'border-red-400' :
                n.priority === 'medium'   ? 'border-accent2' : 'border-muted'
              }`}>
                <div className="text-[10px] text-muted mb-0.5">{n.label} · {n.ts}</div>
                <div className="text-xs leading-snug">{n.message}</div>
              </div>
            ))}
          </div>

          <div className="border-t border-border mt-1" />
          <SectionLabel icon={<Wrench size={11} />} text="Tool Activity" className="px-4 pt-3" />
          <div className="flex-1 overflow-y-auto px-3 pb-3 space-y-1.5">
            {toolLog.length === 0 && <EmptyHint text="No tool calls yet." />}
            {toolLog.map((t, i) => (
              <div key={i} className="bg-surface2 border border-border rounded-md px-2.5 py-1.5">
                <div className={`text-[11px] font-semibold flex items-center gap-1 ${t.agent ? 'text-accent2' : 'text-accent'}`}>
                  {t.agent ? <Hexagon size={10} /> : <Wrench size={10} />}
                  {t.name}
                </div>
                <div className="text-[11px] text-muted mt-0.5 truncate">{t.result}</div>
              </div>
            ))}
          </div>
        </aside>
      </div>

      {/* ── Bottom bar ───────────────────────────────────────────────────── */}
      <div className="flex items-center gap-3 px-5 bg-surface border-t border-border">
        {/* Live webcam preview — only appears while start_watching is active */}
        <WebcamPreview frame={webcamFrame} />

        <VoiceIndicator listening={voice.listening} speaking={voice.speaking} />
        <span className="text-xs text-muted w-20 shrink-0">
          {voice.speaking ? 'Ava speaking' : voice.listening ? 'Listening…' : 'Voice off'}
        </span>
        {voice.transcript && (
          <span className="text-xs italic text-[#e8e8f0]/70 truncate flex-1 hidden md:block">
            "{voice.transcript}"
          </span>
        )}
        <div className="flex-1" />
        <input
          ref={inputRef}
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Type a message to Ava…"
          className="flex-1 max-w-md bg-surface2 border border-border rounded-lg px-3.5 py-2 text-sm outline-none focus:border-accent transition-colors"
        />
        <button
          onClick={sendMessage}
          className="flex items-center gap-1.5 bg-accent text-black font-semibold px-4 py-2 rounded-lg text-sm hover:opacity-85 transition-opacity"
        >
          <Send size={14} /> Send
        </button>
      </div>
    </div>
  );
}

// ── Subcomponents ──────────────────────────────────────────────────────────

function Message({ role, content, ts }) {
  const isAva = role === 'assistant' || role === 'ava';
  const isUser = role === 'user';
  const name = isAva ? 'Ava' : isUser ? 'You' : 'System';

  return (
    <div className={`msg-enter flex gap-2.5 ${isUser ? 'flex-row-reverse' : ''}`}>
      <div className={`w-7 h-7 rounded-full flex items-center justify-center text-[12px] font-bold shrink-0 mt-0.5 ${
        isUser
          ? 'bg-gradient-to-br from-accent2 to-[#8a6a2a] text-black'
          : 'bg-gradient-to-br from-accent to-[#006644] text-black'
      }`}>
        {isUser ? 'Y' : 'A'}
      </div>
      <div className={`max-w-[75%] ${isUser ? 'text-right' : ''}`}>
        <div className="text-[10px] text-muted mb-1">{name}</div>
        <div className={`inline-block text-left rounded-xl px-3.5 py-2.5 text-sm leading-relaxed whitespace-pre-wrap break-words ${
          isUser
            ? 'bg-surface border border-accent rounded-tr-sm'
            : 'bg-surface2 border border-border rounded-tl-sm'
        }`}>
          {content}
        </div>
        <div className="text-[10px] text-muted mt-1">{ts}</div>
      </div>
    </div>
  );
}

function TypingIndicator() {
  return (
    <div className="flex items-center gap-1.5 px-2">
      <div className="w-1.5 h-1.5 rounded-full bg-accent pulse-dot" style={{ animationDelay: '0s' }} />
      <div className="w-1.5 h-1.5 rounded-full bg-accent pulse-dot" style={{ animationDelay: '0.2s' }} />
      <div className="w-1.5 h-1.5 rounded-full bg-accent pulse-dot" style={{ animationDelay: '0.4s' }} />
      <span className="text-xs text-muted ml-1">Ava is thinking…</span>
    </div>
  );
}

function StatusPill({ icon, label, on, warn }) {
  const dotColor = warn ? 'bg-orange-400' : on ? 'bg-accent shadow-[0_0_6px_#00e5a0]' : 'bg-muted';
  return (
    <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full border border-border text-[11px] text-muted">
      {icon ?? <div className={`w-[7px] h-[7px] rounded-full ${dotColor}`} />}
      <span>{label}</span>
    </div>
  );
}

function SectionLabel({ icon, text, className = '' }) {
  return (
    <div className={`flex items-center gap-1.5 text-[10px] tracking-wider uppercase text-muted mb-2 ${className}`}>
      {icon}{text}
    </div>
  );
}

function EmptyHint({ text }) {
  return <div className="text-xs text-muted px-0.5">{text}</div>;
}

function VoiceIndicator({ listening, speaking }) {
  const color = speaking ? '#d4af5a' : listening ? '#00e5a0' : '#2a2a35';
  const animate = listening || speaking;
  return (
    <div className="flex items-center gap-[3px] h-6 w-20 shrink-0">
      {[0, 1, 2, 3].map(i => (
        <div
          key={i}
          className={animate ? 'wave-bar' : ''}
          style={{
            width: 3,
            height: animate ? undefined : 4,
            background: color,
            borderRadius: 2,
            animationDelay: `${i * 0.1}s`,
            animationDuration: speaking ? '0.3s' : '0.6s',
          }}
        />
      ))}
      {speaking ? <Mic size={14} className="ml-1 text-accent2" /> :
       listening ? <Mic size={14} className="ml-1 text-accent" /> :
       <MicOff size={14} className="ml-1 text-muted" />}
    </div>
  );
}

function WebcamPreview({ frame }) {
  // Small circular live preview. Only rendered while frames are actively
  // arriving (start_watching active on the backend) — otherwise collapses
  // to a quiet "camera off" icon so it doesn't take up space unnecessarily.
  if (!frame) {
    return (
      <div className="flex items-center justify-center w-8 h-8 rounded-full bg-surface2 border border-border shrink-0">
        <CameraOff size={13} className="text-muted" />
      </div>
    );
  }
  return (
    <div className="relative w-8 h-8 rounded-full overflow-hidden border-2 border-accent shrink-0 shadow-[0_0_8px_rgba(0,229,160,0.4)]">
      <img
        src={`data:image/jpeg;base64,${frame}`}
        alt="Live webcam"
        className="w-full h-full object-cover"
      />
      <div className="absolute -top-0.5 -right-0.5 w-2 h-2 rounded-full bg-accent border border-surface" />
    </div>
  );
}
