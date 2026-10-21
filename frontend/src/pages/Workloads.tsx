import React, { useEffect, useState } from 'react';
import { api } from '../services/api';
import { AnalysisResponse } from '../types/api';

export const Workloads: React.FC = () => {
  const [data, setData] = useState<AnalysisResponse | null>(null);

  useEffect(() => {
    api.analyze().then(setData);
  }, []);

  if (!data) return <div className="p-8 text-center text-gray-500">Loading workloads...</div>;

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <h1 className="text-2xl font-bold mb-6">Workloads</h1>
      <div className="overflow-x-auto bg-white border rounded-lg shadow-sm">
        <table className="w-full text-left border-collapse">
          <thead className="bg-gray-50 border-b">
            <tr>
              <th className="p-4 font-semibold text-sm">Workload</th>
              <th className="p-4 font-semibold text-sm">Namespace</th>
              <th className="p-4 font-semibold text-sm">Status</th>
              <th className="p-4 font-semibold text-sm">Risk</th>
              <th className="p-4 font-semibold text-sm">Savings</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {data.results.map((res) => (
              <tr key={res.workload_id} className="hover:bg-gray-50">
                <td className="p-4 font-medium">{res.workload_id}</td>
                <td className="p-4 text-gray-500">{res.namespace}</td>
                <td className="p-4">
                  <span className={`px-2 py-1 rounded text-xs font-semibold ${
                    res.decision === 'APPROVED' ? 'bg-green-100 text-green-800' : 'bg-yellow-100 text-yellow-800'
                  }`}>
                    {res.decision}
                  </span>
                </td>
                <td className="p-4 text-sm">{res.risk_level}</td>
                <td className="p-4 text-sm font-medium text-green-600">
                  ${res.proposal.estimated_monthly_saving_usd.toFixed(2)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};