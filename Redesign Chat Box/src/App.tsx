import { useState, useRef, useEffect } from 'react';

interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
}

interface Conversation {
  id: string;
  title: string;
  messages: Message[];
}

const INITIAL_CONVERSATIONS: Conversation[] = [
  {
    id: '1',
    title: 'Getting started with React',
    messages: [
      { id: 'm1', role: 'user', content: 'How do I get started with React?' },
      { id: 'm2', role: 'assistant', content: 'React is a JavaScript library for building user interfaces. To get started:\n\n1. **Create a new project** using Vite:\n   ```\n   npm create vite@latest my-app -- --template react\n   ```\n2. **Install dependencies** with `npm install`\n3. **Start the dev server** with `npm run dev`\n\nYou\'ll be building components in JSX, managing state with hooks like `useState`, and composing your UI from reusable pieces.' },
    ],
  },
  {
    id: '2',
    title: 'CSS Grid vs Flexbox',
    messages: [
      { id: 'm3', role: 'user', content: 'When should I use CSS Grid vs Flexbox?' },
      { id: 'm4', role: 'assistant', content: 'Great question! Both are powerful but serve different purposes:\n\n**Flexbox** — one-dimensional layout (row OR column). Best for:\n- Navigation bars\n- Centering items\n- Distributing space in a single axis\n\n**Grid** — two-dimensional layout (rows AND columns). Best for:\n- Page-level layouts\n- Card grids\n- Anything with alignment across both axes\n\nA common pattern: use Grid for the overall page structure and Flexbox for the components inside each grid area.' },
    ],
  },
  {
    id: '3',
    title: 'TypeScript tips',
    messages: [],
  },
];

const PLACEHOLDER_RESPONSES = [
  "That's an interesting question. Let me think through it carefully.\n\nBased on what you've shared, I'd suggest approaching this step by step — start with the simplest version that could work, then iterate. The key is to avoid over-engineering before you understand the problem deeply.",
  "Here's what I know about that topic:\n\n1. **First principle** — understand the core concept before the implementation details.\n2. **Second principle** — test your assumptions early and often.\n3. **Third principle** — keep your solution as simple as possible, but no simpler.\n\nWould you like me to go deeper on any of these points?",
  "Good question! The short answer is: it depends on your specific use case.\n\nFor most situations, the standard approach works well. But if you're dealing with edge cases or performance constraints, you may want to consider alternatives. What's your current setup?",
];

function MarkdownText({ text }: { text: string }) {
  const lines = text.split('\n');
  const elements: React.ReactNode[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    if (line.startsWith('```')) {
      const codeLines: string[] = [];
      i++;
      while (i < lines.length && !lines[i].startsWith('```')) {
        codeLines.push(lines[i]);
        i++;
      }
      elements.push(
        <pre key={i} className="bg-black/30 rounded-lg p-3 my-2 overflow-x-auto text-sm font-mono">
          <code>{codeLines.join('\n')}</code>
        </pre>
      );
    } else if (line.startsWith('**') && line.endsWith('**') && line.length > 4) {
      elements.push(<strong key={i} className="font-semibold">{line.slice(2, -2)}</strong>);
      elements.push(<br key={`br-${i}`} />);
    } else if (line.match(/^\d+\.\s/)) {
      elements.push(<div key={i} className="ml-4">{renderInline(line)}</div>);
    } else if (line.startsWith('- ')) {
      elements.push(<div key={i} className="ml-4">• {renderInline(line.slice(2))}</div>);
    } else if (line === '') {
      elements.push(<br key={i} />);
    } else {
      elements.push(<span key={i}>{renderInline(line)}</span>);
      if (i < lines.length - 1 && lines[i + 1] !== '') {
        elements.push(<br key={`br-${i}`} />);
      }
    }
    i++;
  }

  return <div className="leading-7">{elements}</div>;
}

function renderInline(text: string): React.ReactNode {
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g);
  return parts.map((part, i) => {
    if (part.startsWith('**') && part.endsWith('**')) {
      return <strong key={i} className="font-semibold">{part.slice(2, -2)}</strong>;
    }
    if (part.startsWith('`') && part.endsWith('`')) {
      return <code key={i} className="bg-black/30 px-1.5 py-0.5 rounded text-sm font-mono">{part.slice(1, -1)}</code>;
    }
    return part;
  });
}

function SendIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
      <path d="M8 1L8 15M8 1L3 6M8 1L13 6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  );
}

function PlusIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
      <path d="M8 2V14M2 8H14" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
    </svg>
  );
}

function BotIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
      <rect x="2" y="4" width="12" height="9" rx="2" stroke="currentColor" strokeWidth="1.5"/>
      <circle cx="6" cy="8.5" r="1" fill="currentColor"/>
      <circle cx="10" cy="8.5" r="1" fill="currentColor"/>
      <path d="M8 1V4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
      <path d="M5 13V15M11 13V15" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
    </svg>
  );
}

export default function App() {
  const [conversations, setConversations] = useState<Conversation[]>(INITIAL_CONVERSATIONS);
  const [activeId, setActiveId] = useState<string>('1');
  const [input, setInput] = useState('');
  const [isThinking, setIsThinking] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const activeConversation = conversations.find(c => c.id === activeId)!;

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [activeConversation?.messages, isThinking]);

  function adjustTextarea() {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 200) + 'px';
  }

  function newConversation() {
    const id = Date.now().toString();
    setConversations(prev => [
      { id, title: 'New conversation', messages: [] },
      ...prev,
    ]);
    setActiveId(id);
    setInput('');
  }

  async function sendMessage() {
    const text = input.trim();
    if (!text || isThinking) return;

    const userMsg: Message = { id: Date.now().toString(), role: 'user', content: text };
    setInput('');
    if (textareaRef.current) textareaRef.current.style.height = 'auto';
    setIsThinking(true);

    setConversations(prev => prev.map(c =>
      c.id === activeId
        ? {
            ...c,
            title: c.messages.length === 0 ? text.slice(0, 40) : c.title,
            messages: [...c.messages, userMsg],
          }
        : c
    ));

    await new Promise(r => setTimeout(r, 900 + Math.random() * 600));

    const reply = PLACEHOLDER_RESPONSES[Math.floor(Math.random() * PLACEHOLDER_RESPONSES.length)];
    const assistantMsg: Message = { id: (Date.now() + 1).toString(), role: 'assistant', content: reply };

    setConversations(prev => prev.map(c =>
      c.id === activeId ? { ...c, messages: [...c.messages, assistantMsg] } : c
    ));
    setIsThinking(false);
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  }

  return (
    <div className="flex h-dvh overflow-hidden" style={{ background: 'var(--background)', color: 'var(--foreground)' }}>
      {/* Sidebar */}
      <aside
        className="flex flex-col shrink-0 transition-all duration-300 overflow-hidden"
        style={{
          width: sidebarOpen ? '260px' : '0px',
          background: 'var(--sidebar)',
          borderRight: sidebarOpen ? '1px solid var(--border)' : 'none',
        }}
      >
        <div className="flex flex-col h-full min-w-[260px]">
          {/* Sidebar header */}
          <div className="flex items-center justify-between px-3 pt-3 pb-2">
            <button
              onClick={newConversation}
              className="flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium w-full transition-colors"
              style={{ color: 'var(--foreground)' }}
              onMouseEnter={e => (e.currentTarget.style.background = 'var(--border)')}
              onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
            >
              <PlusIcon />
              New chat
            </button>
          </div>

          {/* Conversation list */}
          <div className="scrollable flex-1 px-2 py-1">
            <p className="px-2 py-1 text-xs font-medium uppercase tracking-wider" style={{ color: 'var(--muted-foreground)' }}>
              Recent
            </p>
            {conversations.map(conv => (
              <button
                key={conv.id}
                onClick={() => setActiveId(conv.id)}
                className="w-full text-left px-3 py-2 rounded-lg text-sm truncate transition-colors mb-0.5"
                style={{
                  background: conv.id === activeId ? 'var(--card)' : 'transparent',
                  color: conv.id === activeId ? 'var(--foreground)' : 'var(--muted-foreground)',
                }}
                onMouseEnter={e => {
                  if (conv.id !== activeId) e.currentTarget.style.background = 'var(--card)';
                  e.currentTarget.style.color = 'var(--foreground)';
                }}
                onMouseLeave={e => {
                  if (conv.id !== activeId) {
                    e.currentTarget.style.background = 'transparent';
                    e.currentTarget.style.color = 'var(--muted-foreground)';
                  }
                }}
              >
                {conv.title}
              </button>
            ))}
          </div>

          {/* User area */}
          <div className="px-3 py-3 border-t" style={{ borderColor: 'var(--border)' }}>
            <div className="flex items-center gap-2 px-2 py-1.5 rounded-lg">
              <div className="w-7 h-7 rounded-full flex items-center justify-center text-xs font-semibold" style={{ background: 'var(--primary)', color: 'var(--primary-foreground)' }}>
                U
              </div>
              <span className="text-sm" style={{ color: 'var(--muted-foreground)' }}>User</span>
            </div>
          </div>
        </div>
      </aside>

      {/* Main chat area */}
      <div className="flex flex-col flex-1 min-w-0 overflow-hidden">
        {/* Top bar */}
        <header className="flex items-center gap-3 px-4 py-3 shrink-0" style={{ borderBottom: '1px solid var(--border)' }}>
          <button
            onClick={() => setSidebarOpen(o => !o)}
            className="p-2 rounded-lg transition-colors"
            style={{ color: 'var(--muted-foreground)' }}
            onMouseEnter={e => { e.currentTarget.style.background = 'var(--card)'; e.currentTarget.style.color = 'var(--foreground)'; }}
            onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = 'var(--muted-foreground)'; }}
            title="Toggle sidebar"
          >
            <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
              <rect x="2" y="4" width="14" height="1.5" rx="0.75" fill="currentColor"/>
              <rect x="2" y="8.25" width="14" height="1.5" rx="0.75" fill="currentColor"/>
              <rect x="2" y="12.5" width="14" height="1.5" rx="0.75" fill="currentColor"/>
            </svg>
          </button>
          <span className="text-sm font-medium truncate" style={{ color: 'var(--foreground)' }}>
            {activeConversation?.title || 'New chat'}
          </span>
        </header>

        {/* Messages area — scrolls internally */}
        <div className="scrollable flex-1 overflow-y-auto">
          {activeConversation?.messages.length === 0 && !isThinking ? (
            <div className="flex flex-col items-center justify-center h-full gap-6 px-4">
              <div className="flex items-center justify-center w-12 h-12 rounded-2xl" style={{ background: 'var(--primary)' }}>
                <BotIcon />
              </div>
              <div className="text-center">
                <h1 className="text-2xl font-semibold mb-2">How can I help you today?</h1>
                <p className="text-sm" style={{ color: 'var(--muted-foreground)' }}>Ask me anything — code, writing, analysis, ideas.</p>
              </div>
              <div className="grid grid-cols-2 gap-2 w-full max-w-lg">
                {['Explain a concept', 'Write some code', 'Summarize a topic', 'Brainstorm ideas'].map(s => (
                  <button
                    key={s}
                    onClick={() => { setInput(s); textareaRef.current?.focus(); }}
                    className="text-left px-4 py-3 rounded-xl text-sm transition-colors"
                    style={{ background: 'var(--card)', color: 'var(--muted-foreground)', border: '1px solid var(--border)' }}
                    onMouseEnter={e => { e.currentTarget.style.color = 'var(--foreground)'; e.currentTarget.style.borderColor = 'var(--muted-foreground)'; }}
                    onMouseLeave={e => { e.currentTarget.style.color = 'var(--muted-foreground)'; e.currentTarget.style.borderColor = 'var(--border)'; }}
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="max-w-3xl mx-auto px-4 py-6 space-y-6">
              {activeConversation?.messages.map(msg => (
                <div key={msg.id} className={`flex gap-3 ${msg.role === 'user' ? 'flex-row-reverse' : 'flex-row'}`}>
                  {msg.role === 'assistant' && (
                    <div className="shrink-0 w-8 h-8 rounded-full flex items-center justify-center mt-0.5" style={{ background: 'var(--primary)' }}>
                      <BotIcon />
                    </div>
                  )}
                  <div
                    className={`max-w-[85%] px-4 py-3 rounded-2xl text-sm ${msg.role === 'user' ? 'rounded-br-sm' : 'rounded-bl-sm'}`}
                    style={msg.role === 'user'
                      ? { background: 'var(--card)', color: 'var(--foreground)' }
                      : { background: 'transparent', color: 'var(--foreground)' }
                    }
                  >
                    <MarkdownText text={msg.content} />
                  </div>
                </div>
              ))}
              {isThinking && (
                <div className="flex gap-3">
                  <div className="shrink-0 w-8 h-8 rounded-full flex items-center justify-center" style={{ background: 'var(--primary)' }}>
                    <BotIcon />
                  </div>
                  <div className="px-4 py-3 rounded-2xl rounded-bl-sm text-sm flex items-center gap-1.5">
                    {[0, 1, 2].map(i => (
                      <span
                        key={i}
                        className="w-2 h-2 rounded-full animate-bounce"
                        style={{ background: 'var(--muted-foreground)', animationDelay: `${i * 150}ms` }}
                      />
                    ))}
                  </div>
                </div>
              )}
              <div ref={messagesEndRef} />
            </div>
          )}
        </div>

        {/* Input area — fixed at bottom */}
        <div className="shrink-0 px-4 py-4" style={{ borderTop: '1px solid var(--border)' }}>
          <div className="max-w-3xl mx-auto">
            <div
              className="flex items-end gap-3 rounded-2xl px-4 py-3 transition-all"
              style={{
                background: 'var(--card)',
                border: '1px solid var(--border)',
              }}
            >
              <textarea
                ref={textareaRef}
                value={input}
                onChange={e => { setInput(e.target.value); adjustTextarea(); }}
                onKeyDown={handleKeyDown}
                placeholder="Message..."
                rows={1}
                className="flex-1 resize-none bg-transparent outline-none text-sm leading-6 placeholder:text-sm"
                style={{
                  color: 'var(--foreground)',
                  maxHeight: '200px',
                  fontFamily: 'inherit',
                }}
              />
              <button
                onClick={sendMessage}
                disabled={!input.trim() || isThinking}
                className="shrink-0 w-8 h-8 rounded-lg flex items-center justify-center transition-all"
                style={{
                  background: input.trim() && !isThinking ? 'var(--primary)' : 'var(--border)',
                  color: input.trim() && !isThinking ? 'var(--primary-foreground)' : 'var(--muted-foreground)',
                  cursor: input.trim() && !isThinking ? 'pointer' : 'not-allowed',
                }}
              >
                <SendIcon />
              </button>
            </div>
            <p className="text-center text-xs mt-2" style={{ color: 'var(--muted-foreground)' }}>
              Press Enter to send · Shift+Enter for new line
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
