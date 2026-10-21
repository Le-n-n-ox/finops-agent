import React, { useState } from 'react';

export const Policies: React.FC = () => {
  const [maxReduction, setMaxReduction] = useState(50);
  const [minCpu, setMinCpu] = useState(10);
  const [saved, setSaved] = useState(false);

  const handleSave = (e: React.FormEvent) => {
    e.preventDefault();
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  return (
    <div className="p-6 max-w-3xl mx-auto">
      <h1 className="text-2xl font-bold mb-6">Policy Settings</h1>
      <form onSubmit={handleSave} className="space-y-6 bg-white border rounded-lg shadow-sm p-6">
        <div>
          <label className="block font-medium mb-1">Maximum Request Reduction (%)</label>
          <p className="text-sm text-gray-500 mb-3">Hard cap on how much a workload's resources can be reduced in a single patch.</p>
          <input 
            type="number" 
            value={maxReduction} 
            onChange={(e) => setMaxReduction(Number(e.target.value))}
            className="w-full border rounded p-2"
          />
        </div>
        
        <div>
          <label className="block font-medium mb-1">Minimum CPU Floor (millicores)</label>
          <p className="text-sm text-gray-500 mb-3">Do not optimize CPU requests below this threshold.</p>
          <input 
            type="number" 
            value={minCpu} 
            onChange={(e) => setMinCpu(Number(e.target.value))}
            className="w-full border rounded p-2"
          />
        </div>

        <button type="submit" className="bg-blue-600 text-white px-4 py-2 rounded text-sm hover:bg-blue-700">
          {saved ? 'Saved!' : 'Save Policies'}
        </button>
      </form>
    </div>
  );
};