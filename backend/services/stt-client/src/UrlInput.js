// src/UrlInput.js
import React, { useState } from 'react';

function UrlInput({ onSubmit, isLoading }) {
  const [url, setUrl] = useState('');

  const handleSubmit = (event) => {
    event.preventDefault();
    if (url && !isLoading) {
      onSubmit(url); // App.js의 handleSubmit 호출
    }
  };

  return (
    <form onSubmit={handleSubmit}>
      <input
        type="url" // url 타입 사용
        value={url}
        onChange={(e) => setUrl(e.target.value)}
        placeholder="Enter YouTube URL (e.g., https://www.youtube.com/...)"
        disabled={isLoading}
        required
        style={{ width: 'calc(100% - 180px)', marginRight: '10px' }} // 너비 조정
      />
      <button type="submit" disabled={isLoading} style={{ width: '170px' }}> {/* 너비 고정 */}
        {isLoading ? 'Processing...' : 'Start Transcription'}
      </button>
    </form>
  );
}

export default UrlInput;