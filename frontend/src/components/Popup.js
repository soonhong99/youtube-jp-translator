import React from 'react';

const Popup = ({ message, onClose }) => (
  <div className="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-30">
    <div className="bg-white rounded-2xl px-8 py-6 shadow-lg flex flex-col items-center animate-fadeIn">
      <div className="text-2xl font-semibold text-blue-600 mb-2">🎉 완료!</div>
      <div className="mb-4 text-gray-800 text-lg">{message}</div>
      <button
        className="px-5 py-2 bg-blue-600 text-white font-bold rounded-lg shadow hover:bg-blue-700 transition"
        onClick={onClose}
      >
        확인
      </button>
    </div>
  </div>
);

export default Popup;