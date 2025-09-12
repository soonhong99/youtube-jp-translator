import React, { useState } from 'react';
import UrlInput from '../components/UrlInput';
import AiModeSelector from '../components/AiModeSelector';
import '../styles/animations.css';

const Home = () => {
  const [selectedMode, setSelectedMode] = useState('standard');
  const [customSettings, setCustomSettings] = useState(null);
  
  return (
    <div className="bg-gray-900 text-white min-h-screen px-4 py-8">
      <div className="max-w-6xl w-full mx-auto">
        
        {/* 메인 헤더 섹션 */}
        <div className="text-center py-12 mb-8">
        
      <h1 className="text-4xl sm:text-5xl font-extrabold mb-6 leading-tight">
  일본어 유튜브 자막, 자동으로 추출하고 번역까지!
</h1>
<p className="text-gray-300 text-lg mb-10">
  일본어 영상을 이해하고 싶은 당신을 위해 <br />
  실시간 자막 분석 및 번역을 제공합니다.
</p>

{/* 입력창 컴포넌트 */}
<UrlInput 
  redirectOnSubmit 
  selectedMode={selectedMode}
  customSettings={customSettings}
/>
        </div>

        {/* AI 모드 선택 섹션 */}
        <AiModeSelector
          selectedMode={selectedMode}
          onModeChange={setSelectedMode}
          onCustomSettingsChange={setCustomSettings}
        />

        {/* 기능 소개 */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 text-white text-center mt-12">
          <div>
            <div className="text-4xl mb-2">🎙️</div>
            <h3 className="text-xl font-semibold mb-1">STT 변환</h3>
            <p className="text-sm text-gray-300">일본어 음성을 텍스트로 변환합니다.</p>
          </div>
          <div>
            <div className="text-4xl mb-2">🌐</div>
            <h3 className="text-xl font-semibold mb-1">AI 번역</h3>
            <p className="text-sm text-gray-300">다양한 모드로 지능적 번역을 제공합니다.</p>
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

