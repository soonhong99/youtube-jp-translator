import React, { useEffect, useRef, useState } from 'react';
import { useLocation } from 'react-router-dom';
import ProcessingStatus from '../components/ProcessingStatus';
import AiAgentMonitor from '../components/AiAgentMonitor';
import CostAnalysisDashboard from '../components/CostAnalysisDashboard';
import ReactPlayer from 'react-player';
import axios from 'axios';

const TranslateResult = () => {
  const location = useLocation();
  const youtubeUrl = location.state?.youtubeUrl;
  const aiMode = location.state?.aiMode || 'standard';
  
  const [segments, setSegments] = useState([]);
  const [status, setStatus] = useState('처리 시작 중...');
  const [detailedStatus, setDetailedStatus] = useState('YouTube 오디오 추출 중...');
  const [progress, setProgress] = useState(null);
  const [videoUrl, setVideoUrl] = useState('');
  const [activeIndex, setActiveIndex] = useState(null);
  const [loading, setLoading] = useState(true);
  const [processingStep, setProcessingStep] = useState('EXTRACTING');
  const [apiUsage, setApiUsage] = useState(null);
  const [aiAgents, setAiAgents] = useState(null);
  const [progressDetail, setProgressDetail] = useState('');
  const [processingTime, setProcessingTime] = useState(0);
  const [startTime, setStartTime] = useState(null);
  const [showCostDashboard, setShowCostDashboard] = useState(false);
  const [sttStepDetail, setSttStepDetail] = useState('');
  const [estimatedRemaining, setEstimatedRemaining] = useState(null);
  
  const hasRequestedRef = useRef(false);
  const playerRef = useRef(null);
  const socketRef = useRef(null);

  // YouTube URL에서 비디오 ID 추출
  const extractVideoId = (url) => {
    const match = url.match(/(?:youtube\.com\/watch\?v=|youtu\.be\/)([^&\n?#]+)/);
    return match ? match[1] : null;
  };

  // 상태별 메시지 업데이트
  const updateProcessingState = (messageStatus, messageProgress) => {
    setProcessingStep(messageStatus);
    setProgress(messageProgress);
    
    switch (messageStatus) {
      case 'PROCESSING':
        setStatus('STT 음성 인식 처리 중...');
        setDetailedStatus('일본어 음성을 텍스트로 변환하고 있습니다...');
        break;
      case 'STT_COMPLETED':
        setStatus('STT 완료 - AI 번역 시작 중...');
        setDetailedStatus('음성 인식이 완료되었습니다. AI 번역을 시작합니다...');
        break;
      case 'STT_COMPLETED_SENTENCE_FIRST':
        setStatus('AI 문장 분할 처리 중...');
        setDetailedStatus('AI가 텍스트를 자연스러운 문장으로 분할하고 있습니다...');
        break;
      case 'AI_PROCESSING':
        setStatus('AI 번역 처리 중...');
        const detail = progressDetail ? ` - ${progressDetail}` : '';
        setDetailedStatus(`Gemini AI가 일본어를 한국어로 번역하고 있습니다${detail}`);
        break;
      case 'AI_PROCESSING_COMPLETED':
        setStatus('번역 완료!');
        setDetailedStatus('모든 처리가 완료되었습니다!');
        setProcessingStep('COMPLETED');
        setLoading(false);
        break;
      case 'COMPLETED':
        setStatus('처리 완료!');
        setDetailedStatus('자막과 번역이 준비되었습니다!');
        setLoading(false);
        break;
      case 'FAILED':
        setStatus('처리 실패');
        setDetailedStatus('처리 중 오류가 발생했습니다. 다시 시도해 주세요.');
        setLoading(false);
        break;
      default:
        break;
    }
  };

  useEffect(() => {
    if (!youtubeUrl || hasRequestedRef.current) return;
    hasRequestedRef.current = true;

    // 비디오 URL 설정
    setVideoUrl(youtubeUrl);

    const processVideo = async () => {
      try {
        // 1. YouTube 오디오 추출
        setProcessingStep('EXTRACTING');
        setDetailedStatus('YouTube 비디오에서 오디오를 추출하고 있습니다...');
        
        const taskId = `task-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
        
        const extractResponse = await axios.post(`${process.env.REACT_APP_API_GATEWAY_URL}/api/youtube/extract`, {
          url: youtubeUrl,
          task_id: taskId
        });

        if (!extractResponse.data.file_path) {
          throw new Error('오디오 추출에 실패했습니다.');
        }

        // 2. STT 처리 요청
        setProcessingStep('PROCESSING');
        updateProcessingState('PROCESSING', 10);
        
        await axios.post(`${process.env.REACT_APP_API_GATEWAY_URL}/api/stt/transcribe`, {
          wav_file_path: extractResponse.data.file_path,
          task_id: taskId,
          ai_mode: aiMode
        });

        // 3. WebSocket 연결
        const wsUrl = `${process.env.REACT_APP_WS_BASE_URL}/ws/${taskId}`;
        console.log('Connecting to WebSocket:', wsUrl);
        
        const ws = new WebSocket(wsUrl);
        socketRef.current = ws;

        ws.onopen = () => {
          console.log('WebSocket connected');
        };

        ws.onmessage = (event) => {
          const msg = JSON.parse(event.data);
          console.log('WebSocket message received:', msg);

          // 처리 시간 업데이트
          if (startTime) {
            setProcessingTime((Date.now() - startTime) / 1000);
          } else if (msg.status !== 'EXTRACTING') {
            setStartTime(Date.now());
          }

          // 상태 업데이트
          if (msg.status) {
            updateProcessingState(msg.status, msg.progress);
          }
          
          // 상세 진행 정보 업데이트
          if (msg.progress_detail) {
            setProgressDetail(msg.progress_detail);
          }
          
          // STT 상세 단계 정보 업데이트
          if (msg.step_detail) {
            setSttStepDetail(msg.step_detail);
          }
          
          // 예상 남은 시간 업데이트
          if (msg.estimated_remaining) {
            setEstimatedRemaining(msg.estimated_remaining);
          }

          // AI 에이전트 상태 처리
          if (msg.ai_agents) {
            console.log('AI Agents data received:', msg.ai_agents);
            setAiAgents(msg.ai_agents);
            
            // 실시간 API 사용량 업데이트
            if (msg.ai_agents.summary && msg.ai_agents.summary.real_time_api_usage) {
              setApiUsage(msg.ai_agents.summary.real_time_api_usage);
            }
          }

          // processing_info 메타데이터 처리
          if (msg.processing_info) {
            console.log('Processing info received:', msg.processing_info);
            
            // API 사용 통계 업데이트
            if (msg.processing_info.api_usage) {
              setApiUsage(msg.processing_info.api_usage);
            }
          }

          // 세그먼트 데이터 및 API 사용 통계 처리
          if (msg.data) {
            if (msg.status === 'COMPLETED' || msg.status === 'AI_PROCESSING_COMPLETED') {
              // 세그먼트 데이터 설정
              if (Array.isArray(msg.data)) {
                setSegments(msg.data);
              } else if (msg.data.segments && Array.isArray(msg.data.segments)) {
                setSegments(msg.data.segments);
              }
              setLoading(false);
            }
          }
        };

        ws.onerror = (error) => {
          console.error('WebSocket error:', error);
          setProcessingStep('FAILED');
          setStatus('WebSocket 연결 오류');
          setDetailedStatus('실시간 연결에 문제가 발생했습니다.');
        };

        ws.onclose = (event) => {
          console.log('WebSocket closed:', event.code, event.reason);
          if (event.code !== 1000 && loading) {
            setProcessingStep('FAILED');
            setStatus('연결 종료됨');
            setDetailedStatus('서버와의 연결이 종료되었습니다. 페이지를 새로고침해 주세요.');
          }
        };

      } catch (error) {
        console.error('Processing error:', error);
        setProcessingStep('FAILED');
        setStatus('처리 실패');
        setDetailedStatus(error.response?.data?.detail || error.message || '알 수 없는 오류가 발생했습니다.');
        setLoading(false);
      }
    };

    processVideo();

    // 컴포넌트 언마운트 시 WebSocket 정리
    return () => {
      if (socketRef.current) {
        socketRef.current.close();
      }
    };
  }, [youtubeUrl, aiMode]);

  // 비디오 ID 추출
  const videoId = extractVideoId(youtubeUrl || '');

  return (
    <div className="bg-gray-900 text-white min-h-screen px-4 py-8">
      <div className="max-w-6xl mx-auto">
        
        {/* 처리 상태 표시 */}
        {loading && (
          <div className="mb-6">
            <ProcessingStatus 
              status={status}
              detailedStatus={detailedStatus}
              progress={progress}
              processingStep={processingStep}
            />
            
            {/* 상세 진행 정보 */}
            <div className="bg-gray-800 rounded-lg p-4 mt-4">
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm text-gray-300">진행 상세:</span>
                <div className="text-right">
                  <div className="text-sm text-blue-300">{Math.floor(processingTime)}초 경과</div>
                  {estimatedRemaining && (
                    <div className="text-xs text-orange-300">~{Math.floor(estimatedRemaining)}초 남음</div>
                  )}
                </div>
              </div>
              
              {/* STT 단계별 상세 정보 */}
              <div className="space-y-2">
                {sttStepDetail && (
                  <div className="text-white font-medium flex items-center">
                    <span className="w-3 h-3 bg-blue-500 rounded-full mr-2 animate-pulse"></span>
                    {sttStepDetail}
                  </div>
                )}
                
                {progressDetail && progressDetail !== sttStepDetail && (
                  <div className="text-gray-300 text-sm flex items-center">
                    <span className="w-2 h-2 bg-gray-400 rounded-full mr-2"></span>
                    {progressDetail}
                  </div>
                )}
                
                {!sttStepDetail && !progressDetail && (
                  <div className="text-white font-medium">
                    처리 중...
                  </div>
                )}
              </div>
              
              {/* 처리 단계 시각화 */}
              <div className="mt-4">
                <div className="flex items-center justify-between text-xs text-gray-400 mb-2">
                  <span>추출</span>
                  <span>STT</span>
                  <span>AI 번역</span>
                  <span>완료</span>
                </div>
                <div className="w-full bg-gray-700 rounded-full h-2">
                  <div 
                    className="bg-gradient-to-r from-blue-500 to-green-500 h-2 rounded-full transition-all duration-300" 
                    style={{ width: `${Math.max(5, progress)}%` }}
                  ></div>
                </div>
                <div className="text-center text-sm text-gray-400 mt-1">
                  {progress}% 완료
                </div>
              </div>
              
              {/* 실시간 API 사용량 */}
              {apiUsage && (
                <div className="mt-3 pt-3 border-t border-gray-700">
                  <div className="text-xs text-gray-400 mb-2">실시간 API 사용량</div>
                  <div className="grid grid-cols-4 gap-4 text-center text-sm">
                    <div>
                      <div className="font-bold text-blue-300">{apiUsage.total_calls || 0}</div>
                      <div className="text-gray-400">API 호출</div>
                    </div>
                    <div>
                      <div className="font-bold text-green-300">{(apiUsage.total_tokens || 0).toLocaleString()}</div>
                      <div className="text-gray-400">토큰</div>
                    </div>
                    <div>
                      <div className="font-bold text-yellow-300">₩{Math.round(apiUsage.total_cost_krw || 0)}</div>
                      <div className="text-gray-400">비용</div>
                    </div>
                    <div>
                      <div className="font-bold text-red-300">{apiUsage.errors || 0}</div>
                      <div className="text-gray-400">오류</div>
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        {/* AI 에이전트 모니터 */}
        {loading && aiAgents && (
          <AiAgentMonitor aiAgents={aiAgents} />
        )}

        {/* 비디오 플레이어 */}
        {videoId && (
          <div className="mb-8">
            <div className="bg-black rounded-lg overflow-hidden">
              <ReactPlayer
                ref={playerRef}
                url={youtubeUrl}
                width="100%"
                height="480px"
                controls={true}
                playing={false}
              />
            </div>
          </div>
        )}

        {/* API 사용 통계 표시 */}
        {!loading && apiUsage && (
          <div className="bg-blue-800 rounded-lg p-6 mb-6">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-xl font-bold">🔥 Gemini API 사용 통계</h3>
              <button 
                onClick={() => setShowCostDashboard(true)}
                className="bg-green-600 hover:bg-green-700 text-white px-4 py-2 rounded text-sm font-medium"
              >
                📊 상세 분석 보기
              </button>
            </div>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-center">
              <div className="bg-blue-700 rounded-lg p-3">
                <div className="text-2xl font-bold text-blue-200">{apiUsage.total_calls}</div>
                <div className="text-sm text-blue-300">API 호출</div>
              </div>
              <div className="bg-blue-700 rounded-lg p-3">
                <div className="text-2xl font-bold text-blue-200">{apiUsage.total_tokens?.toLocaleString() || 0}</div>
                <div className="text-sm text-blue-300">총 토큰</div>
              </div>
              <div className="bg-blue-700 rounded-lg p-3">
                <div className="text-2xl font-bold text-green-300">₩{Math.round(apiUsage.total_cost_krw || 0)}</div>
                <div className="text-sm text-blue-300">총 비용</div>
              </div>
              <div className="bg-blue-700 rounded-lg p-3">
                <div className="text-2xl font-bold text-red-300">{apiUsage.errors || 0}</div>
                <div className="text-sm text-blue-300">오류 횟수</div>
              </div>
            </div>
            {apiUsage.calls_by_model && Object.keys(apiUsage.calls_by_model).length > 0 && (
              <div className="mt-4">
                <div className="text-sm text-blue-300 mb-2">모델별 사용량:</div>
                <div className="flex flex-wrap gap-2">
                  {Object.entries(apiUsage.calls_by_model).map(([model, stats]) => (
                    <span key={model} className="bg-blue-600 px-2 py-1 rounded text-xs">
                      {model}: {stats.calls}회 (₩{Math.round(stats.cost_krw || 0)})
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* 세그먼트 결과 표시 */}
        {!loading && segments.length > 0 && (
          <div className="bg-gray-800 rounded-lg p-6">
            <h2 className="text-2xl font-bold mb-6">번역 결과</h2>
            <div className="space-y-4">
              {segments.map((segment, index) => (
                <div
                  key={index}
                  className={`p-4 rounded-lg border ${
                    activeIndex === segment.start
                      ? 'bg-blue-600 border-blue-400'
                      : 'bg-gray-700 border-gray-600'
                  }`}
                >
                  <div className="text-sm text-gray-300 mb-2">
                    {Math.floor(segment.start / 60)}:{(segment.start % 60).toFixed(1).padStart(4, '0')} - {Math.floor(segment.end / 60)}:{(segment.end % 60).toFixed(1).padStart(4, '0')}
                  </div>
                  <div className="text-gray-300 mb-2">
                    <strong>일본어:</strong> {segment.text}
                  </div>
                  <div className="text-white">
                    <strong>한국어:</strong> {segment.korean_text || '번역 처리 중...'}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* 오류 상태 표시 */}
        {!loading && processingStep === 'FAILED' && (
          <div className="bg-red-600 rounded-lg p-6 text-center">
            <div className="text-4xl mb-4">❌</div>
            <h2 className="text-2xl font-bold mb-2">처리 실패</h2>
            <p className="text-red-100 mb-4">{detailedStatus}</p>
            <button 
              onClick={() => window.location.reload()}
              className="bg-white text-red-600 px-6 py-2 rounded-lg font-semibold hover:bg-gray-100"
            >
              다시 시도
            </button>
          </div>
        )}

        {/* 비용 분석 대시보드 모달 */}
        {showCostDashboard && (
          <CostAnalysisDashboard 
            taskId={`task-${Date.now()}`} 
            onClose={() => setShowCostDashboard(false)} 
          />
        )}
      </div>
    </div>
  );
};

export default TranslateResult;