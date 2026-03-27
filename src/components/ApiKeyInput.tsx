import { useState } from 'react';
import { Eye, EyeOff, Key } from 'lucide-react';

interface Props {
  apiKey: string;
  onChange: (key: string) => void;
}

export default function ApiKeyInput({ apiKey, onChange }: Props) {
  const [show, setShow] = useState(false);

  return (
    <div className="flex items-center gap-2">
      <Key className="w-3.5 h-3.5 text-slate-500 shrink-0" />
      <div className="relative flex-1">
        <input
          type={show ? 'text' : 'password'}
          value={apiKey}
          onChange={(e) => onChange(e.target.value)}
          placeholder="OpenAI API key (optional)"
          className="w-full bg-slate-800 border border-slate-700 rounded-lg text-xs text-slate-300 px-3 py-1.5 pr-7 focus:outline-none focus:border-violet-500 placeholder:text-slate-600"
        />
        <button
          onClick={() => setShow(!show)}
          className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300"
        >
          {show ? <EyeOff className="w-3 h-3" /> : <Eye className="w-3 h-3" />}
        </button>
      </div>
      {apiKey && (
        <span className="text-[10px] text-emerald-400 shrink-0">✓ Set</span>
      )}
    </div>
  );
}
