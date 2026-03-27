import { useCallback, useRef, useState } from 'react';
import { Upload, FileCode, AlertCircle, X } from 'lucide-react';
import { parseWsdl, isValidWsdl } from '../services/wsdlParser';
import type { WsdlInfo } from '../types';

interface Props {
  onParsed: (info: WsdlInfo, rawXml: string) => void;
}

export default function WsdlUploader({ onParsed }: Props) {
  const [dragging, setDragging] = useState(false);
  const [text, setText] = useState('');
  const [error, setError] = useState('');
  const [tab, setTab] = useState<'upload' | 'paste'>('upload');
  const inputRef = useRef<HTMLInputElement>(null);

  const process = useCallback(
    (xml: string) => {
      setError('');
      if (!isValidWsdl(xml)) {
        setError('The provided content does not appear to be a valid WSDL file.');
        return;
      }
      try {
        const info = parseWsdl(xml);
        if (!info.operations.length) {
          setError('No operations were found in the WSDL. Please check the file.');
          return;
        }
        onParsed(info, xml);
      } catch (e) {
        setError(`Failed to parse WSDL: ${(e as Error).message}`);
      }
    },
    [onParsed],
  );

  const handleFile = (file: File) => {
    if (!file.name.endsWith('.wsdl') && !file.name.endsWith('.xml')) {
      setError('Please upload a .wsdl or .xml file.');
      return;
    }
    const reader = new FileReader();
    reader.onload = (e) => process(e.target?.result as string);
    reader.readAsText(file);
  };

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragging(false);
      const file = e.dataTransfer.files[0];
      if (file) handleFile(file);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [process],
  );

  return (
    <div className="flex flex-col gap-4">
      {/* Tab switcher */}
      <div className="flex rounded-lg overflow-hidden border border-slate-700 text-sm">
        {(['upload', 'paste'] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`flex-1 py-2 font-medium transition-colors ${
              tab === t
                ? 'bg-violet-600 text-white'
                : 'bg-slate-800 text-slate-400 hover:text-slate-200'
            }`}
          >
            {t === 'upload' ? 'Upload File' : 'Paste XML'}
          </button>
        ))}
      </div>

      {tab === 'upload' ? (
        <div
          onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          onClick={() => inputRef.current?.click()}
          className={`flex flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed p-8 cursor-pointer transition-colors ${
            dragging
              ? 'border-violet-500 bg-violet-900/20'
              : 'border-slate-600 bg-slate-800/50 hover:border-violet-500/60 hover:bg-slate-800'
          }`}
        >
          <Upload className="w-8 h-8 text-slate-400" />
          <div className="text-center">
            <p className="text-slate-300 font-medium">Drop your WSDL file here</p>
            <p className="text-slate-500 text-xs mt-1">or click to browse (.wsdl, .xml)</p>
          </div>
          <input
            ref={inputRef}
            type="file"
            accept=".wsdl,.xml"
            className="hidden"
            onChange={(e) => { const f = e.target.files?.[0]; if (f) handleFile(f); }}
          />
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Paste WSDL XML here…"
            className="h-40 w-full rounded-lg bg-slate-900 border border-slate-700 text-slate-300 text-xs font-mono p-3 resize-none focus:outline-none focus:border-violet-500"
          />
          <button
            onClick={() => process(text)}
            disabled={!text.trim()}
            className="py-2 rounded-lg bg-violet-600 hover:bg-violet-500 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm font-medium transition-colors flex items-center justify-center gap-2"
          >
            <FileCode className="w-4 h-4" />
            Parse WSDL
          </button>
        </div>
      )}

      {error && (
        <div className="flex items-start gap-2 rounded-lg bg-red-900/30 border border-red-700/50 p-3 text-red-300 text-sm">
          <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
          <span className="flex-1">{error}</span>
          <button onClick={() => setError('')}>
            <X className="w-4 h-4 opacity-60 hover:opacity-100" />
          </button>
        </div>
      )}
    </div>
  );
}
