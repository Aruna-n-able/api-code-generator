import { useState } from 'react';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism';
import { Copy, Check, Download, Loader2, FlaskConical, Bot } from 'lucide-react';
import type { TestTab, WsdlOperation, GeneratedFiles, Language } from '../types';
import { generateUnitTests, generateRobotTests } from '../services/codeGenerator';
import { pyUnitTests, pyRobotTests } from '../services/pythonCodeGenerator';
import { generateTestsWithAI } from '../services/openaiService';

interface Props {
  operation: WsdlOperation;
  files: GeneratedFiles;
  apiKey: string;
  language: Language;
}

export default function TestGenerator({ operation, files, apiKey, language }: Props) {
  const [activeTab, setActiveTab] = useState<TestTab>('unit');
  const [unitTests, setUnitTests] = useState('');
  const [robotTests, setRobotTests] = useState('');
  const [loading, setLoading] = useState(false);
  const [copied, setCopied] = useState(false);
  const [useAI, setUseAI] = useState(false);
  const [error, setError] = useState('');

  const hasApiKey = !!apiKey.trim();
  const hasTests = !!(activeTab === 'unit' ? unitTests : robotTests);

  const generateTests = async () => {
    setError('');
    setLoading(true);
    try {
      if (useAI && hasApiKey) {
        const currentCode: Record<string, string> = {
          controller: files.controller,
          serviceInterface: files.serviceInterface,
          serviceImpl: files.serviceImpl,
          transformer: files.transformer,
          requestDto: files.requestDto,
          responseDto: files.responseDto,
        };
        const result = await generateTestsWithAI(apiKey, operation.name, currentCode, language);
        if (result.unitTests) setUnitTests(result.unitTests);
        if (result.robotTests) setRobotTests(result.robotTests);
      } else if (language === 'python') {
        setUnitTests(pyUnitTests(operation));
        setRobotTests(pyRobotTests(operation));
      } else {
        setUnitTests(generateUnitTests(operation));
        setRobotTests(generateRobotTests(operation));
      }
    } catch (e) {
      setError(`Test generation failed: ${(e as Error).message}`);
    } finally {
      setLoading(false);
    }
  };

  const isPython = language === 'python';
  const currentCode = activeTab === 'unit' ? unitTests : robotTests;
  const unitLang = isPython ? 'python' : 'java';
  const language2 = activeTab === 'unit' ? unitLang : 'robotframework';
  const unitFileName = isPython
    ? `test_${operation.name.toLowerCase()}_service.py`
    : `${operation.name}ServiceImplTest.java`;
  const robotFileName = `${operation.name}Tests.robot`;
  const fileName = activeTab === 'unit' ? unitFileName : robotFileName;

  const copy = async () => {
    await navigator.clipboard.writeText(currentCode);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const download = () => {
    const blob = new Blob([currentCode], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = fileName;
    a.click();
    URL.revokeObjectURL(url);
  };

  const unitTabLabel = isPython ? 'pytest Tests' : 'Unit Tests (JUnit 5 / Mockito)';

  return (
    <div className="flex flex-col gap-4">
      {/* Header + generate button */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-2">
          <FlaskConical className="w-5 h-5 text-emerald-400" />
          <h3 className="text-sm font-semibold text-white">Test Generation</h3>
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-700 text-slate-400">
            {isPython ? '🐍 pytest + Robot' : '☕ JUnit 5 + Robot'}
          </span>
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          {hasApiKey && (
            <label className="flex items-center gap-1.5 text-xs text-slate-400 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={useAI}
                onChange={(e) => setUseAI(e.target.checked)}
                className="accent-violet-500"
              />
              <Bot className="w-3.5 h-3.5" />
              AI-enhanced
            </label>
          )}

          <button
            onClick={generateTests}
            disabled={loading}
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-emerald-700 hover:bg-emerald-600 disabled:opacity-50 text-white text-sm font-medium transition-colors"
          >
            {loading ? (
              <><Loader2 className="w-4 h-4 animate-spin" /> Generating…</>
            ) : (
              <><FlaskConical className="w-4 h-4" /> Generate Tests</>
            )}
          </button>
        </div>
      </div>

      {error && (
        <div className="text-xs text-red-300 bg-red-900/30 border border-red-700/50 rounded-lg px-3 py-2">
          {error}
        </div>
      )}

      {/* Tabs */}
      {(unitTests || robotTests) && (
        <>
          <div className="flex gap-1">
            {([['unit', unitTabLabel], ['robot', 'Robot Framework Tests']] as const).map(([key, label]) => (
              <button
                key={key}
                onClick={() => setActiveTab(key)}
                className={`px-3 py-1.5 rounded-t-lg text-xs font-medium transition-colors ${
                  activeTab === key
                    ? 'bg-slate-800 text-emerald-300 border border-b-0 border-slate-700'
                    : 'text-slate-500 hover:text-slate-300'
                }`}
              >
                {label}
              </button>
            ))}
          </div>

          <div className="rounded-b-lg rounded-tr-lg border border-slate-700 overflow-hidden bg-[#1e1e1e]">
            {/* Toolbar */}
            <div className="flex items-center justify-between px-3 py-2 border-b border-slate-700/60 bg-slate-800/60">
              <span className="text-xs text-slate-400 font-mono">{fileName}</span>
              {hasTests && (
                <div className="flex gap-2">
                  <button onClick={download} title="Download" className="p-1 rounded text-slate-400 hover:text-slate-200 hover:bg-slate-700 transition-colors">
                    <Download className="w-3.5 h-3.5" />
                  </button>
                  <button onClick={copy} title="Copy" className="p-1 rounded text-slate-400 hover:text-slate-200 hover:bg-slate-700 transition-colors">
                    {copied ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
                  </button>
                </div>
              )}
            </div>

            <div className="overflow-auto max-h-80">
              <SyntaxHighlighter
                language={language2}
                style={vscDarkPlus}
                customStyle={{ margin: 0, padding: '12px 16px', background: 'transparent', fontSize: '12px', lineHeight: '1.6' }}
                showLineNumbers
                lineNumberStyle={{ color: '#4a5568', fontSize: '11px', minWidth: '2.5em' }}
              >
                {currentCode || '# Click "Generate Tests" to create test files'}
              </SyntaxHighlighter>
            </div>
          </div>
        </>
      )}

      {!unitTests && !robotTests && !loading && (
        <div className="text-center py-6 text-slate-500 text-sm">
          <FlaskConical className="w-8 h-8 mx-auto mb-2 opacity-30" />
          <p>Click <strong className="text-slate-400">Generate Tests</strong> to create{' '}
            {isPython ? 'pytest' : 'JUnit 5'} unit tests and Robot Framework tests.</p>
          {!hasApiKey && (
            <p className="text-xs mt-1 text-slate-600">Add an OpenAI API key to enable AI-enhanced test generation.</p>
          )}
        </div>
      )}
    </div>
  );
}
