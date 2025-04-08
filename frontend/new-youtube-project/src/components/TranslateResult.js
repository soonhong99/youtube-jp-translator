import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';

function TranslateResult() {
  // 예시 데이터 (나중에 실제 API 연결 시 대체할 예정)
  const exampleScript = [
    { time: "00:00:15", jp: "おはようございます。", kr: "안녕하세요." },
    { time: "00:00:20", jp: "今日は東京に来ています。", kr: "오늘은 도쿄에 와 있습니다." },
    { time: "00:00:30", jp: "朝ごはんは近くのカフェです。", kr: "아침밥은 근처 카페입니다." },
    { time: "00:00:40", jp: "美味しそうなトーストがあります。", kr: "맛있어 보이는 토스트가 있어요." }
  ];

  const navigate = useNavigate();


  return (
    <div style={styles.container}>
      <div style={styles.videoSection}>
        {/* 유튜브 영상 임베드 영역 (임시) */}
        <iframe
          width="100%"
          height="550"
          src="https://www.youtube.com/embed/dQw4w9WgXcQ"
          title="YouTube video player"
          frameBorder="0"
          allowFullScreen
          style={{ borderRadius: '8px' }}
        ></iframe>
      </div>

      <div style={styles.scriptSection}>

      <div style={{ marginTop: '20px'}}>
          
          <button
            onClick={() => navigate('/download')}
            style={{
              backgroundColor: '#28a745',
              color: 'white',
              padding: '10px 20px',
              border: 'none',
              borderRadius: '5px',
              fontSize: '1rem',
              cursor: 'pointer'
            }}
          >
            📄 전체 스크립트 보기 & 스크립트 저장
          </button>
        </div>

        <h2 style={{ marginBottom: '10px' }}>📑 번역된 스크립트 결과</h2>
        <div style={styles.scriptContainer}>
          {exampleScript.map((line, index) => (
            <div key={index} style={styles.scriptLine}>
              <span style={styles.time}>{line.time}</span>
              <p style={styles.jp}><strong>🇯🇵 일본어:</strong> {line.jp}</p>
              <p style={styles.kr}><strong>🇰🇷 한국어:</strong> {line.kr}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// CSS 스타일 (인라인 스타일 사용)
const styles = {
  container: {
    display: 'flex',
    flexDirection: 'row',
    justifyContent: 'space-between',
    padding: '20px',
    gap: '20px',
    minHeight: '100vh',
    backgroundColor: '#f0f4f8',
    fontFamily: 'sans-serif'
  },
  videoSection: {
    flex: 1,
    backgroundColor: '#fff',
    padding: '10px',
    borderRadius: '8px',
    boxShadow: '0 4px 8px rgba(0,0,0,0.1)'
  },
  scriptSection: {
    flex: 1,
    backgroundColor: '#fff',
    padding: '20px',
    borderRadius: '8px',
    boxShadow: '0 4px 8px rgba(0,0,0,0.1)',
    overflowY: 'auto'
  },
  scriptContainer: {
    maxHeight: '70vh'
  },
  scriptLine: {
    marginBottom: '15px',
    paddingBottom: '10px',
    borderBottom: '1px solid #ddd'
  },
  time: {
    display: 'inline-block',
    marginBottom: '5px',
    backgroundColor: '#007bff',
    color: '#fff',
    padding: '3px 8px',
    borderRadius: '4px',
    fontSize: '0.8rem'
  },
  jp: {
    color: '#333',
    margin: '4px 0'
  },
  kr: {
    color: '#555',
    margin: '4px 0'
  }
};

export default TranslateResult;
