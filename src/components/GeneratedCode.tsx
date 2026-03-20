import { useState } from 'react';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism';
import { Copy, Check, Download } from 'lucide-react';
import type { CodeTab, GeneratedFiles } from '../types';

const TABS: { key: CodeTab; label: string; fileName: (op: string) => string }[] = [
  { key: 'controller',       label: 'Controller',    fileName: (op) => `${op}Controller.java` },
  { key: 'serviceInterface', label: 'Service',        fileName: (op) => `${op}Service.java` },
  { key: 'serviceImpl',      label: 'ServiceImpl',    fileName: (op) => `${op}ServiceImpl.java` },
  { key: 'transformer',      label: 'Transformer',    fileName: (op) => `${op}Transformer.java` },
  { key: 'requestDto',       label: 'RequestDTO',     fileName: (op) => `${op}Request.java` },
  { key: 'responseDto',      label: 'ResponseDTO',    fileName: (op) => `${op}Response.java` },
];

interface Props {
  files: GeneratedFiles;
  operationName: string;
}

export default function GeneratedCode({ files, operationName }: Props) {
  const [activeTab, setActiveTab] = useState<CodeTab>('controller');
  const [copied, setCopied] = useState(false);

  const currentTab = TABS.find((t) => t.key === activeTab)!;
  const code = files[activeTab];

  const copyCode = async () => {
    await navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const downloadFile = () => {
    const blob = new Blob([code], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = currentTab.fileName(operationName);
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="flex flex-col h-full">
      {/* Tab bar */}
      <div className="flex gap-1 overflow-x-auto pb-1 shrink-0">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={`shrink-0 px-3 py-1.5 rounded-t-lg text-xs font-medium transition-colors ${
              activeTab === tab.key
                ? 'bg-slate-800 text-violet-300 border border-b-0 border-slate-700'
                : 'text-slate-500 hover:text-slate-300'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Code block */}
      <div className="flex-1 relative rounded-b-lg rounded-tr-lg overflow-hidden border border-slate-700 bg-[#1e1e1e]">
        {/* Toolbar */}
        <div className="flex items-center justify-between px-3 py-2 border-b border-slate-700/60 bg-slate-800/60">
          <span className="text-xs text-slate-400 font-mono">
            {currentTab.fileName(operationName)}
          </span>
          <div className="flex gap-2">
            <button
              onClick={downloadFile}
              title="Download file"
              className="p-1 rounded text-slate-400 hover:text-slate-200 hover:bg-slate-700 transition-colors"
            >
              <Download className="w-3.5 h-3.5" />
            </button>
            <button
              onClick={copyCode}
              title="Copy to clipboard"
              className="p-1 rounded text-slate-400 hover:text-slate-200 hover:bg-slate-700 transition-colors"
            >
              {copied ? (
                <Check className="w-3.5 h-3.5 text-emerald-400" />
              ) : (
                <Copy className="w-3.5 h-3.5" />
              )}
            </button>
          </div>
        </div>

        {/* Syntax highlighted code */}
        <div className="overflow-auto h-full max-h-[440px]">
          <SyntaxHighlighter
            language="java"
            style={vscDarkPlus}
            customStyle={{
              margin: 0,
              padding: '12px 16px',
              background: 'transparent',
              fontSize: '12px',
              lineHeight: '1.6',
            }}
            showLineNumbers
            lineNumberStyle={{ color: '#4a5568', fontSize: '11px', minWidth: '2.5em' }}
          >
            {code}
          </SyntaxHighlighter>
        </div>
      </div>
    </div>
  );
}
