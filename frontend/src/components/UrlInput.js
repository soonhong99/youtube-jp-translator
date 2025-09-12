import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';

function UrlInput({ redirectOnSubmit = false, onSubmit, isLoading, selectedMode = 'standard', customSettings = null }) {
  const [url, setUrl] = useState('');
  const navigate = useNavigate();

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!url || isLoading) return;
    if (onSubmit) onSubmit(url);
    if (redirectOnSubmit) {
      navigate('/translate', { 
        state: { 
          youtubeUrl: url,
          aiMode: selectedMode,
          customSettings: customSettings
        } 
      });
    }
  };

  return (
    <form onSubmit={handleSubmit} className="flex flex-col md:flex-row w-full max-w-3xl gap-4">
      <input
        type="url"
        value={url}
        onChange={(e) => setUrl(e.target.value)}
        placeholder="YouTube URL을 입력하세요"
        required
        disabled={isLoading}
        className="flex-1 px-4 py-3 rounded-md border border-blue-300 shadow focus:outline-none 
             focus:ring-2 focus:ring-blue-400 bg-white text-gray-800 placeholder-gray-400"
      />


      <button
        type="submit"
        disabled={isLoading}
        className="px-6 py-3 rounded-md bg-blue-600 text-white font-semibold hover:bg-blue-700 transition duration-300"
      >
        {isLoading ? '처리 중...' : '스크립트 생성'}
      </button>
    </form>
  );
}

export default UrlInput;
