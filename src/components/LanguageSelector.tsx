import type { Language } from '../types';

interface Props {
  value: Language;
  onChange: (lang: Language) => void;
}

const LANGS: { key: Language; label: string; icon: string; desc: string }[] = [
  {
    key: 'java',
    label: 'Java',
    icon: '☕',
    desc: 'Spring Boot 3 · Lombok · Jakarta EE',
  },
  {
    key: 'python',
    label: 'Python',
    icon: '🐍',
    desc: 'FastAPI · Pydantic v2 · zeep',
  },
];

export default function LanguageSelector({ value, onChange }: Props) {
  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider px-0.5">
        Target Language
      </span>
      <div className="flex rounded-lg overflow-hidden border border-slate-700 text-sm">
        {LANGS.map((lang) => {
          const active = value === lang.key;
          return (
            <button
              key={lang.key}
              onClick={() => onChange(lang.key)}
              title={lang.desc}
              className={`flex-1 flex items-center justify-center gap-1.5 py-2 px-3 font-medium transition-colors ${
                active
                  ? 'bg-violet-600 text-white'
                  : 'bg-slate-800 text-slate-400 hover:text-slate-200 hover:bg-slate-700/60'
              }`}
            >
              <span className="text-base leading-none">{lang.icon}</span>
              <span>{lang.label}</span>
            </button>
          );
        })}
      </div>
      <p className="text-[10px] text-slate-600 px-0.5">
        {LANGS.find((l) => l.key === value)?.desc}
      </p>
    </div>
  );
}
