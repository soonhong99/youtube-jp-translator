import React, { useState } from 'react';

const AiModeSelector = ({ selectedMode, onModeChange, onCustomSettingsChange }) => {
  const [showCustomSettings, setShowCustomSettings] = useState(false);
  const [customSettings, setCustomSettings] = useState({
    enableSummary: true,
    enableKeywords: true,
    enableSentiment: false,
    enableSpeakerDetection: false,
    enableFormatting: true,
    enableReview: false
  });

  const modes = [
    {
      id: 'fast',
      name: '빠른 모드',
      icon: '⚡',
      time: '~30초',
      cost: '약 4원',
      description: '기본 번역만 제공',
      features: ['일본어 → 한국어 번역'],
      recommended: '빠른 확인용',
      bgColor: 'bg-gradient-to-r from-blue-500 to-blue-600',
      hoverColor: 'hover:from-blue-600 hover:to-blue-700'
    },
    {
      id: 'standard',
      name: '표준 모드',
      icon: '🎯',
      time: '~60초',
      cost: '약 15원',
      description: '번역 + 기본 분석',
      features: ['번역', '요약', '키워드 추출'],
      recommended: '일반 사용자',
      bgColor: 'bg-gradient-to-r from-green-500 to-green-600',
      hoverColor: 'hover:from-green-600 hover:to-green-700'
    },
    {
      id: 'premium',
      name: '프리미엄 모드',
      icon: '✨',
      time: '~120초',
      cost: '약 30원',
      description: '모든 AI 기능 포함',
      features: ['번역', '요약', '키워드', '감정분석', '화자구분', '품질검토'],
      recommended: '전문적 분석',
      bgColor: 'bg-gradient-to-r from-purple-500 to-purple-600',
      hoverColor: 'hover:from-purple-600 hover:to-purple-700'
    },
    {
      id: 'custom',
      name: '커스텀 모드',
      icon: '🔧',
      time: '가변적',
      cost: '설정에 따라',
      description: '원하는 기능만 선택',
      features: ['사용자 맞춤 설정'],
      recommended: '고급 사용자',
      bgColor: 'bg-gradient-to-r from-orange-500 to-orange-600',
      hoverColor: 'hover:from-orange-600 hover:to-orange-700'
    }
  ];

  const handleModeSelect = (modeId) => {
    onModeChange(modeId);
    if (modeId === 'custom') {
      setShowCustomSettings(true);
    } else {
      setShowCustomSettings(false);
    }
  };

  const handleCustomSettingChange = (setting, value) => {
    const newSettings = { ...customSettings, [setting]: value };
    setCustomSettings(newSettings);
    onCustomSettingsChange && onCustomSettingsChange(newSettings);
  };

  return (
    <div className="w-full max-w-6xl mx-auto mt-8 mb-6">
      {/* 모드 선택 헤더 */}
      <div className="text-center mb-6">
        <h3 className="text-2xl font-bold text-white mb-2">AI 번역 모드 선택</h3>
        <p className="text-gray-300">번역 품질과 처리 시간을 고려해 모드를 선택하세요</p>
      </div>

      {/* 모드 카드 그리드 */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        {modes.map((mode) => (
          <div
            key={mode.id}
            onClick={() => handleModeSelect(mode.id)}
            className={`
              relative cursor-pointer rounded-lg p-4 transition-all duration-300 transform hover:scale-105 border-2
              ${selectedMode === mode.id 
                ? 'border-yellow-400 shadow-lg shadow-yellow-400/20' 
                : 'border-transparent hover:border-white/20'}
              ${mode.bgColor} ${mode.hoverColor}
            `}
          >
            {/* 선택됨 표시 */}
            {selectedMode === mode.id && (
              <div className="absolute top-2 right-2">
                <div className="w-6 h-6 bg-yellow-400 rounded-full flex items-center justify-center">
                  <span className="text-xs text-black font-bold">✓</span>
                </div>
              </div>
            )}

            <div className="text-center text-white">
              <div className="text-3xl mb-2">{mode.icon}</div>
              <h4 className="font-bold text-lg mb-1">{mode.name}</h4>
              <div className="text-sm opacity-90 mb-2">
                <div>{mode.time}</div>
                <div>{mode.cost}</div>
              </div>
              <p className="text-xs opacity-80 mb-3">{mode.description}</p>
              
              {/* 기능 리스트 */}
              <div className="text-xs">
                {mode.features.map((feature, idx) => (
                  <div key={idx} className="opacity-75">• {feature}</div>
                ))}
              </div>
              
              <div className="mt-3 pt-2 border-t border-white/20">
                <span className="text-xs font-semibold">{mode.recommended}</span>
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* 커스텀 모드 설정 */}
      {showCustomSettings && selectedMode === 'custom' && (
        <div className="bg-gray-800 rounded-lg p-6 border border-orange-500/30">
          <h4 className="text-lg font-bold text-white mb-4 flex items-center">
            🔧 커스텀 모드 설정
          </h4>
          
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* AI 기능 토글들 */}
            <div className="space-y-3">
              <h5 className="text-white font-semibold">AI 분석 기능</h5>
              
              <label className="flex items-center space-x-3 cursor-pointer">
                <input
                  type="checkbox"
                  checked={customSettings.enableSummary}
                  onChange={(e) => handleCustomSettingChange('enableSummary', e.target.checked)}
                  className="w-4 h-4 text-orange-500 rounded focus:ring-orange-500"
                />
                <span className="text-white">내용 요약 생성</span>
              </label>
              
              <label className="flex items-center space-x-3 cursor-pointer">
                <input
                  type="checkbox"
                  checked={customSettings.enableKeywords}
                  onChange={(e) => handleCustomSettingChange('enableKeywords', e.target.checked)}
                  className="w-4 h-4 text-orange-500 rounded focus:ring-orange-500"
                />
                <span className="text-white">키워드 추출</span>
              </label>
              
              <label className="flex items-center space-x-3 cursor-pointer">
                <input
                  type="checkbox"
                  checked={customSettings.enableSentiment}
                  onChange={(e) => handleCustomSettingChange('enableSentiment', e.target.checked)}
                  className="w-4 h-4 text-orange-500 rounded focus:ring-orange-500"
                />
                <span className="text-white">감정 분석</span>
              </label>
            </div>
            
            <div className="space-y-3">
              <h5 className="text-white font-semibold">고급 기능</h5>
              
              <label className="flex items-center space-x-3 cursor-pointer">
                <input
                  type="checkbox"
                  checked={customSettings.enableSpeakerDetection}
                  onChange={(e) => handleCustomSettingChange('enableSpeakerDetection', e.target.checked)}
                  className="w-4 h-4 text-orange-500 rounded focus:ring-orange-500"
                />
                <span className="text-white">화자 구분</span>
              </label>
              
              <label className="flex items-center space-x-3 cursor-pointer">
                <input
                  type="checkbox"
                  checked={customSettings.enableFormatting}
                  onChange={(e) => handleCustomSettingChange('enableFormatting', e.target.checked)}
                  className="w-4 h-4 text-orange-500 rounded focus:ring-orange-500"
                />
                <span className="text-white">자막 서식 개선</span>
              </label>
              
              <label className="flex items-center space-x-3 cursor-pointer">
                <input
                  type="checkbox"
                  checked={customSettings.enableReview}
                  onChange={(e) => handleCustomSettingChange('enableReview', e.target.checked)}
                  className="w-4 h-4 text-orange-500 rounded focus:ring-orange-500"
                />
                <span className="text-white">번역 품질 검토</span>
              </label>
            </div>
          </div>
          
          {/* 예상 처리 시간 및 비용 */}
          <div className="mt-4 p-3 bg-gray-700 rounded-md">
            <div className="text-sm text-gray-300">
              <span className="font-semibold">예상 처리 시간:</span> 
              {Object.values(customSettings).filter(Boolean).length * 20 + 30}초 |
              <span className="font-semibold ml-2">예상 비용:</span> 
              약 {Object.values(customSettings).filter(Boolean).length * 5 + 4}원
            </div>
          </div>
        </div>
      )}

      {/* 도움말 섹션 */}
      <div className="mt-6 p-4 bg-gray-800/50 rounded-lg border border-gray-600">
        <h5 className="text-white font-semibold mb-2">💡 모드 선택 가이드</h5>
        <div className="text-sm text-gray-300 space-y-1">
          <p><strong>빠른 모드:</strong> 단순히 내용을 이해하고 싶을 때</p>
          <p><strong>표준 모드:</strong> 일반적인 학습이나 업무용으로 추천</p>
          <p><strong>프리미엄 모드:</strong> 전문적 분석이나 상세한 정보가 필요할 때</p>
          <p><strong>커스텀 모드:</strong> 특정 기능만 필요하거나 비용을 조절하고 싶을 때</p>
        </div>
      </div>
    </div>
  );
};

export default AiModeSelector;