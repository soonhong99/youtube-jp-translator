import React from 'react';

function StatusBar({ status, progress, error }) {
  return (
    <div className="bg-gray-100 p-4 mt-4 rounded-md shadow-inner">
      <h3 className="text-lg font-semibold mb-2">진행 상태</h3>
      <p className="text-gray-800">{status}</p>
      {progress !== null && (
        <div className="w-full bg-gray-300 rounded-full h-4 mt-3">
          <div
            className="bg-blue-600 h-4 text-xs text-white text-center rounded-full transition-all duration-300"
            style={{ width: `${progress}%` }}
          >
            {progress}%
          </div>
        </div>
      )}
      {error && <p className="text-red-600 mt-2">오류: {error}</p>}
    </div>
  );
}

export default StatusBar;