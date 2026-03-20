import { ChevronRight, Code2 } from 'lucide-react';
import type { WsdlOperation } from '../types';

interface Props {
  operations: WsdlOperation[];
  selected: WsdlOperation | null;
  onSelect: (op: WsdlOperation) => void;
}

/** Colour badge based on inferred HTTP method */
function methodBadge(name: string) {
  const n = name.toLowerCase();
  if (n.startsWith('get') || n.startsWith('list') || n.startsWith('find') || n.startsWith('fetch') || n.startsWith('query') || n.startsWith('search'))
    return <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-emerald-900/60 text-emerald-400 border border-emerald-700/50">GET</span>;
  if (n.startsWith('delete') || n.startsWith('remove'))
    return <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-red-900/60 text-red-400 border border-red-700/50">DEL</span>;
  if (n.startsWith('update') || n.startsWith('modify') || n.startsWith('change') || n.startsWith('set'))
    return <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-amber-900/60 text-amber-400 border border-amber-700/50">PUT</span>;
  return <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-blue-900/60 text-blue-400 border border-blue-700/50">POST</span>;
}

export default function OperationsList({ operations, selected, onSelect }: Props) {
  if (!operations.length) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 py-8 text-slate-500 text-sm">
        <Code2 className="w-8 h-8 opacity-40" />
        <p>No operations found</p>
      </div>
    );
  }

  return (
    <ul className="flex flex-col gap-1">
      {operations.map((op) => {
        const isSelected = selected?.name === op.name;
        return (
          <li key={op.name}>
            <button
              onClick={() => onSelect(op)}
              className={`w-full text-left flex items-center gap-2 px-3 py-2.5 rounded-lg transition-all group ${
                isSelected
                  ? 'bg-violet-600/20 border border-violet-500/40 text-violet-300'
                  : 'hover:bg-slate-700/50 text-slate-300 border border-transparent hover:border-slate-600/50'
              }`}
            >
              <span className="shrink-0">{methodBadge(op.name)}</span>
              <span className="flex-1 text-sm font-medium truncate">{op.name}</span>
              <ChevronRight
                className={`w-3.5 h-3.5 shrink-0 transition-transform ${
                  isSelected ? 'opacity-100 translate-x-0.5' : 'opacity-0 group-hover:opacity-60'
                }`}
              />
            </button>
          </li>
        );
      })}
    </ul>
  );
}
