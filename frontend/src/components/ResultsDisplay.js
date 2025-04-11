// components/ResultsDisplay.js
import React from 'react';

const ResultsDisplay = ({ segments, activeRef }) => {
  return (
    <div className="space-y-2">
      {segments.length === 0 ? (
        <p className="text-gray-500">자막이 아직 없습니다.</p>
      ) : (
        segments.map((seg, i) => (
          <div
            id={`segment-${seg.start}`}
            key={i}
            className={`p-3 rounded-md transition border border-gray-200 ${activeRef === seg.start ? 'bg-blue-100 font-bold' : 'hover:bg-blue-50'}`}
          >
            <p className="text-sm text-blue-600 font-mono mb-1">
              [{seg.start.toFixed(2)}s - {seg.end.toFixed(2)}s]
            </p>
            <p className="text-gray-800 font-medium">{seg.text}</p>
          </div>
        ))
      )}
    </div>
  );
};

export default ResultsDisplay;
