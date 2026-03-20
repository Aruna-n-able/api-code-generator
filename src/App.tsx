import { useState, useCallback } from 'react';
import {
  Code2,
  Zap,
  ChevronDown,
  ChevronUp,
  Loader2,
  RotateCcw,
  MessageSquare,
  FlaskConical,
  GitBranch,
} from 'lucide-react';
import WsdlUploader from './components/WsdlUploader';
import OperationsList from './components/OperationsList';
import OperationDetail from './components/OperationDetail';
import GeneratedCode from './components/GeneratedCode';
import ChatInterface from './components/ChatInterface';
import TestGenerator from './components/TestGenerator';
import ApiKeyInput from './components/ApiKeyInput';
import LanguageSelector from './components/LanguageSelector';
import { generateAllFiles } from './services/codeGenerator';
import { pyGenerateAllFiles } from './services/pythonCodeGenerator';
import type { WsdlInfo, WsdlOperation, GeneratedFiles, ChatMessage, Language } from './types';

type Stage = 'idle' | 'generating' | 'generated' | 'satisfied';

export default function App() {
  // WSDL state
  const [wsdlInfo, setWsdlInfo] = useState<WsdlInfo | null>(null);
  const [selectedOp, setSelectedOp] = useState<WsdlOperation | null>(null);

  // Language selection
  const [language, setLanguage] = useState<Language>('java');

  // Generation state
  const [stage, setStage] = useState<Stage>('idle');
  const [files, setFiles] = useState<GeneratedFiles | null>(null);

  // Chat state
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);

  // Settings
  const [apiKey, setApiKey] = useState('');
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);

  const handleWsdlParsed = useCallback((info: WsdlInfo) => {
    setWsdlInfo(info);
    setSelectedOp(null);
    setStage('idle');
    setFiles(null);
    setChatMessages([]);
  }, []);

  const handleSelectOp = useCallback((op: WsdlOperation) => {
    setSelectedOp(op);
    setStage('idle');
    setFiles(null);
    setChatMessages([]);
  }, []);

  // When language changes, reset generation so user re-generates for the new language
  const handleLanguageChange = useCallback((lang: Language) => {
    setLanguage(lang);
    setStage('idle');
    setFiles(null);
    setChatMessages([]);
  }, []);

  const handleGenerate = useCallback(() => {
    if (!selectedOp) return;
    setStage('generating');
    setTimeout(() => {
      const generated =
        language === 'python'
          ? pyGenerateAllFiles(selectedOp)
          : generateAllFiles(selectedOp);
      setFiles(generated);
      setStage('generated');
      setChatMessages([]);
    }, 600);
  }, [selectedOp, language]);

  const handleFilesUpdate = useCallback((updates: Partial<GeneratedFiles>) => {
    setFiles((prev) => (prev ? { ...prev, ...updates } : prev));
  }, []);

  const handleReset = useCallback(() => {
    setWsdlInfo(null);
    setSelectedOp(null);
    setStage('idle');
    setFiles(null);
    setChatMessages([]);
  }, []);

  const isGenerated = stage === 'generated' || stage === 'satisfied';
  const isSatisfied = stage === 'satisfied';

  const langLabel = language === 'java' ? '☕ Java' : '🐍 Python';
  const langDesc =
    language === 'java'
      ? 'Spring Boot 3 · Lombok · Jakarta EE'
      : 'FastAPI · Pydantic v2 · zeep';

  return (
    <div className="min-h-screen bg-slate-950 text-slate-200 flex flex-col">
      {/* ── Header ──────────────────────────────────────────────────────── */}
      <header className="shrink-0 border-b border-slate-800 bg-slate-900/80 backdrop-blur-sm sticky top-0 z-10">
        <div className="max-w-screen-2xl mx-auto px-4 h-14 flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-violet-600 flex items-center justify-center shrink-0">
              <Code2 className="w-4.5 h-4.5 text-white" />
            </div>
            <div>
              <h1 className="text-sm font-semibold text-white leading-tight">API Code Generator</h1>
              <p className="text-[10px] text-slate-500 leading-tight">N-Central WSDL → {langLabel} REST</p>
            </div>
          </div>

          <div className="flex items-center gap-3">
            {wsdlInfo && (
              <div className="hidden sm:flex items-center gap-2 text-xs text-slate-400">
                <GitBranch className="w-3.5 h-3.5" />
                <span className="font-medium text-slate-300">{wsdlInfo.serviceName}</span>
                <span className="text-slate-600">·</span>
                <span>{wsdlInfo.operations.length} operations</span>
                <span className="text-slate-600">·</span>
                <span className="text-violet-400">{langLabel}</span>
              </div>
            )}

            <button
              onClick={() => setSettingsOpen(!settingsOpen)}
              className="text-xs px-3 py-1.5 rounded-lg bg-slate-800 border border-slate-700 hover:border-slate-600 text-slate-400 hover:text-slate-200 transition-colors"
            >
              Settings
            </button>

            {wsdlInfo && (
              <button
                onClick={handleReset}
                className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg bg-slate-800 border border-slate-700 hover:border-red-700/50 text-slate-400 hover:text-red-300 transition-colors"
              >
                <RotateCcw className="w-3 h-3" />
                Reset
              </button>
            )}
          </div>
        </div>

        {/* Settings panel */}
        {settingsOpen && (
          <div className="border-t border-slate-800 bg-slate-900 px-4 py-3 max-w-screen-2xl mx-auto">
            <div className="max-w-sm">
              <p className="text-xs text-slate-500 mb-2">
                Provide an OpenAI API key to enable AI-powered code refinement and test generation.
                The key is stored only in memory for this session.
              </p>
              <ApiKeyInput apiKey={apiKey} onChange={setApiKey} />
            </div>
          </div>
        )}
      </header>

      <div className="flex-1 flex overflow-hidden max-w-screen-2xl mx-auto w-full">
        {/* ── Sidebar ─────────────────────────────────────────────────── */}
        <aside
          className={`shrink-0 border-r border-slate-800 bg-slate-900 flex flex-col transition-all duration-200 ${
            sidebarCollapsed ? 'w-10' : 'w-72'
          }`}
        >
          <div className="flex items-center justify-between px-3 py-3 border-b border-slate-800">
            {!sidebarCollapsed && (
              <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                WSDL Operations
              </span>
            )}
            <button
              onClick={() => setSidebarCollapsed(!sidebarCollapsed)}
              className="ml-auto text-slate-500 hover:text-slate-300 p-1 rounded"
            >
              {sidebarCollapsed ? (
                <ChevronDown className="w-4 h-4 rotate-90" />
              ) : (
                <ChevronUp className="w-4 h-4 -rotate-90" />
              )}
            </button>
          </div>

          {!sidebarCollapsed && (
            <div className="flex-1 overflow-y-auto p-3 flex flex-col gap-4">
              {/* Language selector — always visible at top of sidebar */}
              <LanguageSelector value={language} onChange={handleLanguageChange} />

              <WsdlUploader onParsed={handleWsdlParsed} />

              {wsdlInfo && (
                <div className="flex flex-col gap-2">
                  <div className="text-xs text-slate-500 px-1">
                    {wsdlInfo.operations.length} operation{wsdlInfo.operations.length !== 1 ? 's' : ''} found
                  </div>
                  <OperationsList
                    operations={wsdlInfo.operations}
                    selected={selectedOp}
                    onSelect={handleSelectOp}
                  />
                </div>
              )}
            </div>
          )}
        </aside>

        {/* ── Main panel ──────────────────────────────────────────────── */}
        <main className="flex-1 overflow-y-auto p-6">
          {!wsdlInfo ? (
            /* Welcome screen */
            <div className="flex flex-col items-center justify-center min-h-full gap-6 text-center py-16">
              <div className="w-16 h-16 rounded-2xl bg-violet-600/20 border border-violet-500/30 flex items-center justify-center">
                <Code2 className="w-8 h-8 text-violet-400" />
              </div>
              <div>
                <h2 className="text-2xl font-bold text-white mb-2">
                  N-Central API Code Generator
                </h2>
                <p className="text-slate-400 max-w-md">
                  Upload a WSDL file from the N-Central repository to list available
                  operations, then generate a REST API implementation in{' '}
                  <strong className="text-slate-300">Java (Spring Boot)</strong> or{' '}
                  <strong className="text-slate-300">Python (FastAPI)</strong>.
                </p>
              </div>

              {/* Language pills in welcome */}
              <div className="flex gap-3 flex-wrap justify-center">
                {([
                  { key: 'java' as Language, icon: '☕', title: 'Java / Spring Boot', desc: 'Spring Boot 3 · Lombok · Jakarta EE · Swagger' },
                  { key: 'python' as Language, icon: '🐍', title: 'Python / FastAPI', desc: 'FastAPI · Pydantic v2 · zeep SOAP client' },
                ]).map((l) => (
                  <button
                    key={l.key}
                    onClick={() => setLanguage(l.key)}
                    className={`flex items-center gap-3 px-4 py-3 rounded-xl border text-left transition-all ${
                      language === l.key
                        ? 'bg-violet-600/20 border-violet-500/60 text-white'
                        : 'bg-slate-800/50 border-slate-700/50 text-slate-400 hover:border-slate-600'
                    }`}
                  >
                    <span className="text-2xl">{l.icon}</span>
                    <div>
                      <p className="text-sm font-medium">{l.title}</p>
                      <p className="text-xs text-slate-500">{l.desc}</p>
                    </div>
                  </button>
                ))}
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 max-w-2xl text-left">
                {[
                  { icon: '📄', title: 'Upload WSDL', desc: 'Parse N-Central WSDL to extract all operations with request/response structures' },
                  { icon: '⚡', title: 'Generate Code', desc: 'Create Controller, Service, Transformer, and DTO classes in Java or Python' },
                  { icon: '🧪', title: 'Generate Tests', desc: 'Produce JUnit 5 / pytest unit tests and Robot Framework acceptance tests' },
                ].map((item) => (
                  <div key={item.title} className="rounded-xl bg-slate-800/50 border border-slate-700/50 p-4">
                    <div className="text-2xl mb-2">{item.icon}</div>
                    <h3 className="text-sm font-semibold text-white mb-1">{item.title}</h3>
                    <p className="text-xs text-slate-400">{item.desc}</p>
                  </div>
                ))}
              </div>
            </div>
          ) : !selectedOp ? (
            /* No operation selected */
            <div className="flex flex-col items-center justify-center min-h-full gap-4 text-center py-16">
              <Zap className="w-10 h-10 text-slate-600" />
              <div>
                <h2 className="text-lg font-semibold text-white">Select an operation</h2>
                <p className="text-slate-400 text-sm mt-1">
                  Choose one of the {wsdlInfo.operations.length} operations from the sidebar.
                </p>
              </div>
              <div className="text-xs text-slate-500 bg-slate-800/50 border border-slate-700/50 rounded-lg px-4 py-2">
                Generating {langLabel} · {langDesc}
              </div>
            </div>
          ) : (
            /* Operation detail + code generation */
            <div className="flex flex-col gap-6 max-w-4xl">
              {/* Operation detail */}
              <div className="rounded-xl bg-slate-800/50 border border-slate-700/50 p-5">
                <OperationDetail operation={selectedOp} />
              </div>

              {/* Implement REST API button */}
              {!isGenerated && (
                <div className="flex flex-col items-center gap-2">
                  <button
                    onClick={handleGenerate}
                    disabled={stage === 'generating'}
                    className="flex items-center gap-3 px-8 py-3.5 rounded-xl bg-violet-600 hover:bg-violet-500 disabled:opacity-60 disabled:cursor-not-allowed text-white font-semibold text-base shadow-lg shadow-violet-900/40 transition-all hover:shadow-violet-700/40 hover:scale-[1.02] active:scale-[0.99]"
                  >
                    {stage === 'generating' ? (
                      <>
                        <Loader2 className="w-5 h-5 animate-spin" />
                        Generating {langLabel} implementation…
                      </>
                    ) : (
                      <>
                        <Zap className="w-5 h-5" />
                        Implement REST API
                      </>
                    )}
                  </button>
                  <p className="text-xs text-slate-500">
                    Will generate {langLabel} · {langDesc}
                  </p>
                </div>
              )}

              {/* Generated code + chat + tests */}
              {isGenerated && files && (
                <>
                  {/* Re-generate button */}
                  <div className="flex items-center justify-between">
                    <h2 className="text-sm font-semibold text-white flex items-center gap-2">
                      <Zap className="w-4 h-4 text-violet-400" />
                      Generated Implementation
                      <span className="text-xs text-slate-400 font-normal">({langLabel})</span>
                    </h2>
                    <button
                      onClick={handleGenerate}
                      className="flex items-center gap-1.5 text-xs text-slate-400 hover:text-slate-200 transition-colors"
                    >
                      <RotateCcw className="w-3 h-3" />
                      Regenerate
                    </button>
                  </div>

                  {/* Code viewer */}
                  <div className="rounded-xl bg-slate-800/50 border border-slate-700/50 p-5">
                    <GeneratedCode
                      files={files}
                      operationName={selectedOp.name}
                      language={language}
                    />
                  </div>

                  {/* Chat refinement */}
                  <div className="rounded-xl bg-slate-800/50 border border-slate-700/50 p-5">
                    <div className="flex items-center gap-2 mb-4">
                      <MessageSquare className="w-4 h-4 text-violet-400" />
                      <h3 className="text-sm font-semibold text-white">Refine with AI</h3>
                      {!apiKey && (
                        <span className="text-xs text-amber-500/70 ml-1">
                          (add OpenAI API key to enable)
                        </span>
                      )}
                    </div>
                    <ChatInterface
                      messages={chatMessages}
                      files={files}
                      operationName={selectedOp.name}
                      apiKey={apiKey}
                      language={language}
                      onMessagesChange={setChatMessages}
                      onFilesUpdate={handleFilesUpdate}
                      onSatisfied={() => setStage('satisfied')}
                      isSatisfied={isSatisfied}
                    />
                  </div>

                  {/* Test generation (enabled once satisfied) */}
                  {isSatisfied ? (
                    <div className="rounded-xl bg-slate-800/50 border border-emerald-700/30 p-5">
                      <TestGenerator
                        operation={selectedOp}
                        files={files}
                        apiKey={apiKey}
                        language={language}
                      />
                    </div>
                  ) : (
                    <div className="rounded-xl bg-slate-900/60 border border-slate-700/30 p-5 flex items-center gap-3 opacity-60 cursor-not-allowed select-none">
                      <FlaskConical className="w-5 h-5 text-slate-600" />
                      <div>
                        <p className="text-sm font-medium text-slate-500">Test generation locked</p>
                        <p className="text-xs text-slate-600 mt-0.5">
                          Click &ldquo;I&apos;m satisfied&rdquo; in the chat panel above to unlock.
                        </p>
                      </div>
                    </div>
                  )}
                </>
              )}
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
