import React from 'react';
import UrlInput from '../components/UrlInput';
import '../styles/animations.css';

const Home = () => {
  return (
    <div className="bg-gray-900 text-white min-h-screen flex items-center justify-center px-4">
      <div className="max-w-3xl w-full text-center py-20">
        
      <h1 className="text-4xl sm:text-5xl font-extrabold mb-6 leading-tight">
  일본어 유튜브 자막, 자동으로 추출하고 번역까지!
</h1>
<p className="text-gray-300 text-lg mb-10">
  일본어 영상을 이해하고 싶은 당신을 위해 <br />
  실시간 자막 분석 및 번역을 제공합니다.
</p>

{/* 입력창 컴포넌트 */}
<UrlInput redirectOnSubmit />

{/* 기능 소개 */}
<div className="mt-16 grid grid-cols-1 md:grid-cols-3 gap-6 text-white text-center">
  <div>
    <div className="text-4xl mb-2">🎙️</div>
    <h3 className="text-xl font-semibold mb-1">STT 변환</h3>
    <p className="text-sm text-gray-300">일본어 음성을 텍스트로 변환합니다.</p>
  </div>
  <div>
    <div className="text-4xl mb-2">🌐</div>
    <h3 className="text-xl font-semibold mb-1">자동 번역</h3>
    <p className="text-sm text-gray-300">일본어 텍스트를 한국어로 번역합니다.</p>
  </div>
  <div>
    <div className="text-4xl mb-2">📄</div>
    <h3 className="text-xl font-semibold mb-1">스크립트 저장</h3>
    <p className="text-sm text-gray-300">한국어·일본어 자막을 다운로드하세요.</p>
  </div>
</div>

        
      </div>
    </div>
  );
};

export default Home;

