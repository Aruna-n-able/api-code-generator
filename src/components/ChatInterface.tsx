import { useRef, useState } from 'react';
import { Send, Bot, User, Loader2, AlertCircle, Lightbulb } from 'lucide-react';
import type { ChatMessage, GeneratedFiles, Language } from '../types';
import { refineWithAI } from '../services/openaiService';

const JAVA_QUICK_PROMPTS = [
  'Add comprehensive input validation with @NotNull and @NotBlank annotations',
  'Add custom exception handling with @ExceptionHandler and a global error response',
  'Add caching with @Cacheable on the service method',
  'Add pagination support to the response',
  'Add @Transactional annotation and proper transaction management',
  'Improve logging with structured MDC context',
  'Add retry logic with @Retryable for SOAP client failures',
];

const PYTHON_QUICK_PROMPTS = [
  'Add Pydantic field validators and custom error messages',
  'Add a global exception handler with FastAPI ExceptionHandler',
  'Add Redis caching with fastapi-cache2',
  'Add pagination using limit/offset query parameters',
  'Add structured logging with structlog or loguru',
  'Add retry logic with tenacity for SOAP client failures',
  'Add rate limiting with slowapi',
];

interface Props {
  messages: ChatMessage[];
  files: GeneratedFiles;
  operationName: string;
  apiKey: string;
  language: Language;
  onMessagesChange: (msgs: ChatMessage[]) => void;
  onFilesUpdate: (updates: Partial<GeneratedFiles>) => void;
  onSatisfied: () => void;
  isSatisfied: boolean;
}

export default function ChatInterface({
  messages,
  files,
  operationName,
  apiKey,
  language,
  onMessagesChange,
  onFilesUpdate,
  onSatisfied,
  isSatisfied,
}: Props) {
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const endRef = useRef<HTMLDivElement>(null);

  const hasApiKey = !!apiKey.trim();
  const quickPrompts = language === 'python' ? PYTHON_QUICK_PROMPTS : JAVA_QUICK_PROMPTS;

  const send = async (userText: string) => {
    if (!userText.trim() || loading) return;
    setError('');

    const userMsg: ChatMessage = { role: 'user', content: userText };
    const newHistory = [...messages, userMsg];
    onMessagesChange(newHistory);
    setInput('');
    setLoading(true);

    if (!hasApiKey) {
      // No API key: give a helpful template-based response
      const assistantMsg: ChatMessage = {
        role: 'assistant',
        content:
          '⚠️ **No OpenAI API key provided.**\n\nTo enable AI-powered code refinement, add your OpenAI API key in the settings panel (top right).\n\nOnce added, I can refine the generated code, add features, fix issues, and answer questions based on your specific requirements.',
      };
      onMessagesChange([...newHistory, assistantMsg]);
      setLoading(false);
      return;
    }

    try {
      const currentCode: Record<string, string> = {
        controller: files.controller,
        serviceInterface: files.serviceInterface,
        serviceImpl: files.serviceImpl,
        transformer: files.transformer,
        requestDto: files.requestDto,
        responseDto: files.responseDto,
      };

      const result = await refineWithAI(apiKey, {
        userMessage: userText,
        history: messages,
        currentCode,
        operationName,
        language,
      });

      const assistantMsg: ChatMessage = {
        role: 'assistant',
        content: result.assistantMessage,
      };
      onMessagesChange([...newHistory, assistantMsg]);

      if (result.updatedCode) {
        const mapped: Partial<GeneratedFiles> = {};
        if (result.updatedCode.controller) mapped.controller = result.updatedCode.controller;
        if (result.updatedCode.service) mapped.serviceInterface = result.updatedCode.service;
        if (result.updatedCode.serviceImpl) mapped.serviceImpl = result.updatedCode.serviceImpl;
        if (result.updatedCode.transformer) mapped.transformer = result.updatedCode.transformer;
        if (result.updatedCode.requestDto) mapped.requestDto = result.updatedCode.requestDto;
        if (result.updatedCode.responseDto) mapped.responseDto = result.updatedCode.responseDto;
        if (Object.keys(mapped).length) onFilesUpdate(mapped);
      }
    } catch (e) {
      setError(`AI request failed: ${(e as Error).message}`);
    } finally {
      setLoading(false);
      setTimeout(() => endRef.current?.scrollIntoView({ behavior: 'smooth' }), 100);
    }
  };

  const renderMessageContent = (content: string) => {
    // Simple inline code and bold rendering
    const parts = content.split(/(`[^`]+`|\*\*[^*]+\*\*)/g);
    return parts.map((part, i) => {
      if (part.startsWith('`') && part.endsWith('`')) {
        return (
          <code key={i} className="bg-slate-700 px-1 py-0.5 rounded text-violet-300 text-xs font-mono">
            {part.slice(1, -1)}
          </code>
        );
      }
      if (part.startsWith('**') && part.endsWith('**')) {
        return <strong key={i} className="text-white">{part.slice(2, -2)}</strong>;
      }
      // Preserve newlines
      return part.split('\n').map((line, j) => (
        <span key={`${i}-${j}`}>{line}{j < part.split('\n').length - 1 && <br />}</span>
      ));
    });
  };

  return (
    <div className="flex flex-col h-full gap-3">
      {/* Message list */}
      <div className="flex-1 overflow-y-auto flex flex-col gap-3 min-h-0 max-h-64 pr-1">
        {messages.length === 0 && (
          <div className="text-center py-6 text-slate-500 text-sm">
            <Bot className="w-8 h-8 mx-auto mb-2 opacity-40" />
            <p>Ask me to improve or refactor the generated code.</p>
            {!hasApiKey && (
              <p className="text-amber-500/70 text-xs mt-2">
                ⚠️ Add your OpenAI API key to enable AI responses.
              </p>
            )}
          </div>
        )}
        {messages.map((msg, i) => (
          <div
            key={i}
            className={`flex gap-2.5 ${msg.role === 'user' ? 'flex-row-reverse' : ''}`}
          >
            <div
              className={`w-7 h-7 rounded-full shrink-0 flex items-center justify-center ${
                msg.role === 'user' ? 'bg-violet-600' : 'bg-slate-700'
              }`}
            >
              {msg.role === 'user' ? (
                <User className="w-3.5 h-3.5 text-white" />
              ) : (
                <Bot className="w-3.5 h-3.5 text-slate-300" />
              )}
            </div>
            <div
              className={`max-w-[85%] rounded-lg px-3 py-2 text-sm leading-relaxed ${
                msg.role === 'user'
                  ? 'bg-violet-600/20 text-slate-200 border border-violet-600/30'
                  : 'bg-slate-800 text-slate-300 border border-slate-700'
              }`}
            >
              {renderMessageContent(msg.content)}
            </div>
          </div>
        ))}
        {loading && (
          <div className="flex gap-2.5">
            <div className="w-7 h-7 rounded-full bg-slate-700 flex items-center justify-center">
              <Bot className="w-3.5 h-3.5 text-slate-300" />
            </div>
            <div className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2.5">
              <Loader2 className="w-4 h-4 animate-spin text-slate-400" />
            </div>
          </div>
        )}
        <div ref={endRef} />
      </div>

      {/* Quick prompts */}
      {messages.length === 0 && (
        <div className="flex flex-col gap-1.5">
          <div className="flex items-center gap-1.5 text-xs text-slate-500">
            <Lightbulb className="w-3 h-3" />
            <span>Quick suggestions</span>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {quickPrompts.slice(0, 4).map((p) => (
              <button
                key={p}
                onClick={() => send(p)}
                className="text-xs px-2.5 py-1 rounded-full bg-slate-800 border border-slate-700 text-slate-400 hover:border-violet-500/50 hover:text-slate-200 transition-colors"
              >
                {p.length > 50 ? p.slice(0, 48) + '…' : p}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="flex items-center gap-2 rounded-lg bg-red-900/30 border border-red-700/50 p-2 text-red-300 text-xs">
          <AlertCircle className="w-3.5 h-3.5 shrink-0" />
          {error}
        </div>
      )}

      {/* Input row */}
      <div className="flex gap-2 shrink-0">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && send(input)}
          placeholder={hasApiKey ? 'Ask to refine the code…' : 'Add API key to enable AI chat…'}
          className="flex-1 rounded-lg bg-slate-800 border border-slate-700 text-sm text-slate-200 px-3 py-2 focus:outline-none focus:border-violet-500 placeholder:text-slate-600"
        />
        <button
          onClick={() => send(input)}
          disabled={!input.trim() || loading}
          className="px-3 py-2 rounded-lg bg-violet-600 hover:bg-violet-500 disabled:opacity-40 disabled:cursor-not-allowed text-white transition-colors"
        >
          <Send className="w-4 h-4" />
        </button>
      </div>

      {/* Satisfied button */}
      {!isSatisfied && (
        <button
          onClick={onSatisfied}
          className="w-full py-2 rounded-lg bg-emerald-700 hover:bg-emerald-600 text-white text-sm font-medium transition-colors"
        >
          ✅ I&apos;m satisfied — enable test generation
        </button>
      )}
      {isSatisfied && (
        <div className="text-center text-xs text-emerald-400 py-1">
          ✅ Satisfied! Scroll down to generate tests.
        </div>
      )}
    </div>
  );
}
