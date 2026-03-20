import { useState } from 'react';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism';
import { Copy, Check, Download } from 'lucide-react';
import type { CodeTab, GeneratedFiles, Language } from '../types';

interface TabDef {
  key: CodeTab;
  label: string;
  javaFileName: (op: string) => string;
  pythonFileName: (op: string) => string;
}

const TABS: TabDef[] = [
  {
    key: 'controller',
    label: 'Controller',
    javaFileName: (op) => `${op}Controller.java`,
    pythonFileName: (op) => `${op.toLowerCase()}_router.py`,
  },
  {
    key: 'serviceInterface',
    label: 'Service',
    javaFileName: (op) => `${op}Service.java`,
    pythonFileName: (op) => `${op.toLowerCase()}_service_base.py`,
  },
  {
    key: 'serviceImpl',
    label: 'ServiceImpl',
    javaFileName: (op) => `${op}ServiceImpl.java`,
    pythonFileName: (op) => `${op.toLowerCase()}_service.py`,
  },
  {
    key: 'transformer',
    label: 'Transformer',
    javaFileName: (op) => `${op}Transformer.java`,
    pythonFileName: (op) => `${op.toLowerCase()}_transformer.py`,
  },
  {
    key: 'requestDto',
    label: 'RequestDTO',
    javaFileName: (op) => `${op}Request.java`,
    pythonFileName: (op) => `${op.toLowerCase()}_request.py`,
  },
  {
    key: 'responseDto',
    label: 'ResponseDTO',
    javaFileName: (op) => `${op}Response.java`,
    pythonFileName: (op) => `${op.toLowerCase()}_response.py`,
  },
];

interface Props {
  files: GeneratedFiles;
  operationName: string;
  language: Language;
}

export default function GeneratedCode({ files, operationName, language }: Props) {
  const [activeTab, setActiveTab] = useState<CodeTab>('controller');
  const [copied, setCopied] = useState(false);

  const currentTab = TABS.find((t) => t.key === activeTab)!;
  const code = files[activeTab];
  const fileName =
    language === 'java'
      ? currentTab.javaFileName(operationName)
      : currentTab.pythonFileName(operationName);
  const syntaxLang = language === 'java' ? 'java' : 'python';

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
    a.download = fileName;
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
          <span className="text-xs text-slate-400 font-mono">{fileName}</span>
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
            language={syntaxLang}
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
