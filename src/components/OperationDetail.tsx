import type { WsdlField, WsdlOperation } from '../types';

interface FieldTableProps {
  title: string;
  fields: WsdlField[];
  colorClass: string;
}

function FieldTable({ title, fields, colorClass }: FieldTableProps) {
  return (
    <div>
      <h4 className={`text-xs font-semibold uppercase tracking-wider mb-2 ${colorClass}`}>
        {title}
      </h4>
      {fields.length === 0 ? (
        <p className="text-slate-500 text-xs italic">No fields extracted from WSDL.</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-slate-700/60">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-slate-700/60 bg-slate-800/50">
                <th className="text-left py-2 px-3 text-slate-400 font-medium">Field</th>
                <th className="text-left py-2 px-3 text-slate-400 font-medium">Java Type</th>
                <th className="text-left py-2 px-3 text-slate-400 font-medium">Required</th>
                <th className="text-left py-2 px-3 text-slate-400 font-medium">Max</th>
              </tr>
            </thead>
            <tbody>
              {fields.map((f, i) => (
                <tr
                  key={f.name}
                  className={`border-b border-slate-800 ${i % 2 === 0 ? '' : 'bg-slate-800/20'}`}
                >
                  <td className="py-2 px-3 font-mono text-slate-200">{f.name}</td>
                  <td className="py-2 px-3 font-mono text-violet-300">{f.type}</td>
                  <td className="py-2 px-3">
                    {f.required ? (
                      <span className="text-emerald-400">✓</span>
                    ) : (
                      <span className="text-slate-600">—</span>
                    )}
                  </td>
                  <td className="py-2 px-3 text-slate-400">{f.maxOccurs ?? '1'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

interface Props {
  operation: WsdlOperation;
}

export default function OperationDetail({ operation }: Props) {
  return (
    <div className="flex flex-col gap-4">
      {/* Header */}
      <div>
        <h2 className="text-xl font-semibold text-white">{operation.name}</h2>
        {operation.documentation && (
          <p className="text-slate-400 text-sm mt-1">{operation.documentation}</p>
        )}
      </div>

      {/* Message names */}
      {(operation.inputMessageName || operation.outputMessageName) && (
        <div className="flex gap-4 text-xs">
          {operation.inputMessageName && (
            <div className="flex items-center gap-1.5">
              <span className="text-slate-500">Input message:</span>
              <code className="bg-slate-800 px-2 py-0.5 rounded text-blue-300">
                {operation.inputMessageName}
              </code>
            </div>
          )}
          {operation.outputMessageName && (
            <div className="flex items-center gap-1.5">
              <span className="text-slate-500">Output message:</span>
              <code className="bg-slate-800 px-2 py-0.5 rounded text-emerald-300">
                {operation.outputMessageName}
              </code>
            </div>
          )}
        </div>
      )}

      {/* Field tables */}
      <FieldTable
        title="Request Structure (Input)"
        fields={operation.inputFields}
        colorClass="text-blue-400"
      />
      <FieldTable
        title="Response Structure (Output)"
        fields={operation.outputFields}
        colorClass="text-emerald-400"
      />
    </div>
  );
}
