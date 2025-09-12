import React from 'react';

const ProcessingStatus = ({ status, progress, detailedStatus, processingStep }) => {
  // 상태별 메시지와 이모지 매핑
  const getStatusInfo = (step) => {
    const statusMap = {
      'EXTRACTING': { 
        emoji: '🎬', 
        title: 'YouTube 오디오 추출',
        description: '비디오에서 오디오를 추출하고 있습니다...'
      },
      'PROCESSING': { 
        emoji: '🎙️', 
        title: 'STT 음성 인식 처리',
        description: '일본어 음성을 텍스트로 변환하고 있습니다...'
      },
      'STT_COMPLETED': { 
        emoji: '✅', 
        title: 'STT 완료',
        description: '음성 인식이 완료되었습니다. AI 번역을 시작합니다...'
      },
      'STT_COMPLETED_SENTENCE_FIRST': { 
        emoji: '🔄', 
        title: 'AI 문장 분할 처리',
        description: 'AI가 텍스트를 자연스러운 문장으로 분할하고 있습니다...'
      },
      'AI_PROCESSING': { 
        emoji: '🤖', 
        title: 'AI 번역 처리',
        description: 'Gemini AI가 일본어를 한국어로 번역하고 있습니다...'
      },
      'AI_PROCESSING_COMPLETED': { 
        emoji: '🎉', 
        title: '번역 완료',
        description: '모든 처리가 완료되었습니다!'
      },
      'COMPLETED': { 
        emoji: '✨', 
        title: '처리 완료',
        description: '자막과 번역이 준비되었습니다!'
      },
      'FAILED': { 
        emoji: '❌', 
        title: '처리 실패',
        description: '처리 중 오류가 발생했습니다. 다시 시도해 주세요.'
      }
    };
    
    return statusMap[step] || {
      emoji: '⏳',
      title: '처리 중',
      description: detailedStatus || '처리가 진행 중입니다...'
    };
  };

  const statusInfo = getStatusInfo(processingStep);

  return (
    <div className="bg-white rounded-lg shadow-lg p-6 max-w-md mx-auto mb-6">
      <div className="text-center">
        {/* 이모지 */}
        <div className="text-4xl mb-4 animate-pulse">
          {statusInfo.emoji}
        </div>
        
        {/* 제목 */}
        <h3 className="text-xl font-semibold text-gray-800 mb-2">
          {statusInfo.title}
        </h3>
        
        {/* 상세 설명 */}
        <p className="text-gray-600 mb-4">
          {statusInfo.description}
        </p>
        
        {/* 진행률 바 (있는 경우) */}
        {progress !== null && (
          <div className="w-full bg-gray-200 rounded-full h-3 mb-4">
            <div
              className="bg-blue-600 h-3 rounded-full transition-all duration-300 ease-out"
              style={{ width: `${progress}%` }}
            ></div>
          </div>
        )}
        
        {/* 진행률 텍스트 */}
        {progress !== null && (
          <p className="text-sm text-gray-500">
            {progress}% 완료
          </p>
        )}
        
        {/* 로딩 애니메이션 */}
        {processingStep !== 'COMPLETED' && processingStep !== 'FAILED' && (
          <div className="flex justify-center mt-4">
            <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-blue-600"></div>
          </div>
        )}
      </div>
    </div>
  );
};

export default ProcessingStatus;