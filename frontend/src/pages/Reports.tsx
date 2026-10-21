import React, { useEffect, useState } from 'react';
import { api } from '../services/api';
import { AnalysisResponse } from '../types/api';

export const Reports: React.FC = () => {
  const [data, setData] = useState<AnalysisResponse | null>(null);

  useEffect(() => {
    api.analyze().then(setData);
  }, []);

  if (!data) return <div className="p-8 text-center text-gray-500">Loading audit history...</div>;

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-2xl font-bold">Reports & Audit</h1>
        <button className="bg-blue-600 text-white px-4 py-2 rounded text-sm hover:bg-blue-700">
          Export JSON
        </button>
      </div>
      <div className="p-6 bg-white border rounded-lg shadow-sm">
        <div className="mb-4">
          <span className="font-semibold">Analysis ID:</span> <span className="font-mono text-sm ml-2">{data.analysis_id}</span>
        </div>
        <div className="mb-4">
          <span className="font-semibold">Generated:</span> <span className="text-sm ml-2">{new Date(data.generated_at).toLocaleString()}</span>
        </div>
        <div className="mb-6">
          <span className="font-semibold">Mode:</span> <span className="uppercase text-xs bg-gray-200 px-2 py-1 rounded ml-2">{data.mode}</span>
        </div>
        
        <h3 className="font-semibold border-b pb-2 mb-4">Audit Trail</h3>
        <ul className="space-y-4">
          {data.results.map(r => (
            <li key={r.workload_id} className="text-sm">
              <span className="text-gray-500">{new Date(data.generated_at).toLocaleTimeString()}</span> — 
              <span className="font-medium ml-2">{r.workload_id}</span> transitioned to <span className="font-bold">{r.decision}</span>. 
              <span className="text-gray-600 block mt-1">{r.reason}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
};