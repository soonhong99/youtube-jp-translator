// src/StatusBar.js
import React from 'react';

function StatusBar({ status, progress, error }) {
  return (
    <div className="status-area">
      <h2>Status</h2>
      <p id="status-message">{status}</p>
      {/* 진행률 표시 바 */}
      {progress !== null && progress >= 0 && ( // 0%도 표시하도록 수정
        <div style={{
          width: '100%',
          backgroundColor: '#e9ecef', // 배경색 변경
          borderRadius: '4px',
          margin: '10px 0',
          overflow: 'hidden' // 내부 요소가 넘치지 않도록
        }}>
          <div style={{
                width: `${progress}%`,
                height: '24px', // 높이 조정
                backgroundColor: '#007bff', // 진행 바 색상
                borderRadius: '4px',
                textAlign: 'center',
                color: 'white',
                lineHeight: '24px', // 높이에 맞게 조정
                fontWeight: 'bold', // 글자 굵게
                fontSize: '0.9em', // 글자 크기 조정
                transition: 'width 0.5s ease-out' // 부드러운 전환 효과
               }}>
            {progress}%
          </div>
        </div>
      )}
      {error && <p className="error-message">Error: {error}</p>}
    </div>
  );
}

export default StatusBar;