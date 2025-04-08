import React from 'react';

export default function About() {
  return (
    <div style={{ padding: '20px', fontFamily: 'sans-serif' }}>
      <h2>📖 서비스 소개</h2>
      <p>
        본 서비스는 일본어 유튜브 영상의 음성을 자동으로 텍스트로 변환하고,  
        이를 자연스러운 한국어로 번역하여 제공합니다.
      </p>
      <ul>
        <li>🔹 유튜브 영상의 URL 입력</li>
        <li>🔹 일본어 음성 자동 분석 및 텍스트 변환(STT)</li>
        <li>🔹 자연스러운 한국어 번역 제공</li>
        <li>🔹 스크립트 다운로드 및 관리 기능</li>
      </ul>
    </div>
  );
}
