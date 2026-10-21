import React, { useEffect, useState } from 'react';
import { api } from '../services/api';
import { AnalysisResponse } from '../types/api';

export const Overview: React.FC = () => {
  const [data, setData] = useState<AnalysisResponse | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.analyze().then(setData).finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="p-8 text-center text-gray-500">Loading dashboard...</div>;
  if (!data) return null;

  const { summary } = data;

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <h1 className="text-2xl font-bold mb-6">FinOps Overview</h1>
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-8">
        <div className="p-4 bg-white border rounded-lg shadow-sm">
          <div className="text-sm text-gray-500 font-medium">Monthly Savings</div>
          <div className="text-2xl font-bold text-green-600">${summary.estimated_monthly_savings_usd.toFixed(2)}</div>
        </div>
        <div className="p-4 bg-white border rounded-lg shadow-sm">
          <div className="text-sm text-gray-500 font-medium">Workloads Analyzed</div>
          <div className="text-2xl font-bold">{summary.workloads_evaluated}</div>
        </div>
        <div className="p-4 bg-white border rounded-lg shadow-sm">
          <div className="text-sm text-gray-500 font-medium">Approved</div>
          <div className="text-2xl font-bold text-green-600">{summary.approved}</div>
        </div>
        <div className="p-4 bg-white border rounded-lg shadow-sm">
          <div className="text-sm text-gray-500 font-medium">Deferred / Blocked</div>
          <div className="text-2xl font-bold text-yellow-600">{summary.deferred} / {summary.rejected}</div>
        </div>
      </div>
    </div>
  );
};