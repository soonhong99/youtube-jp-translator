import React, { useEffect, useRef, useState } from 'react';
import { useLocation } from 'react-router-dom';
import StatusBar from '../components/StatusBar';
import DownloadButtons from '../components/DownloadButtons';
import ReactPlayer from 'react-player';
import axios from 'axios';

const TranslateResult = () => {
  const location = useLocation();
  const youtubeUrl = location.state?.youtubeUrl;

  const [segments, setSegments] = useState([]);
  const [status, setStatus] = useState('STT 진행 중...');
  const [progress, setProgress] = useState(null);
  const [videoUrl, setVideoUrl] = useState('');
  const [activeIndex, setActiveIndex] = useState(null);
  const [loading, setLoading] = useState(true);

  const hasRequestedRef = useRef(false);
  const playerRef = useRef(null);
  const socketRef = useRef(null);

  useEffect(() => {
    const interval = setInterval(() => {
      const currentTime = playerRef.current?.getCurrentTime?.() || 0;
      const current = segments.find(seg => currentTime >= seg.start && currentTime <= seg.end);
      if (current && activeIndex !== current.start) {
        setActiveIndex(current.start);
        const el = document.getElementById(`segment-${current.start}`);
        if (el) {
          el.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
      }
    }, 500);
    return () => clearInterval(interval);
  }, [segments, activeIndex]);

  useEffect(() => {
    const fetchAndTranscribe = async () => {
      if (!youtubeUrl || hasRequestedRef.current) return;
      hasRequestedRef.current = true;

      try {
        setStatus('오디오 추출 중...');
        setLoading(true);

        const extractRes = await axios.post(`${process.env.REACT_APP_EXTRACTOR_API_URL}/extract`, {
          youtube_url: youtubeUrl,
          output_format: 'wav',
          sample_rate: 16000,
          channels: 1,
        });

        const filePath = extractRes.data.file_path;
        setVideoUrl(youtubeUrl);

        setStatus('자막 생성 중...');
        const sttRes = await axios.post(`${process.env.REACT_APP_STT_API_URL}/request_transcription`, {
          wav_file_path: filePath,
          language: 'ja',
        });

        const taskId = sttRes.data.task_id;
        const ws = new WebSocket(`${process.env.REACT_APP_WS_BASE_URL}/ws/${taskId}`);
        socketRef.current = ws;

        // ws.onmessage = (event) => {
        //   const msg = JSON.parse(event.data);
        //   if (msg.data && Array.isArray(msg.data)) {
        //     setSegments(prev => [...prev, ...msg.data]);
        //   }
        //   if (msg.progress !== undefined) setProgress(msg.progress);
        //   if (msg.status) setStatus(msg.status);
        //   if (msg.status === 'COMPLETED') setLoading(false);
        // };

        // TranslateResult.js - useEffect 내 ws.onmessage 수정 (개선안)

        ws.onmessage = (event) => {
          const msg = JSON.parse(event.data);
          console.log("WebSocket Message Received:", msg);

          if (msg.status) setStatus(msg.status);
          if (msg.progress !== undefined) setProgress(msg.progress);

          if (msg.data && Array.isArray(msg.data)) {
            if (msg.status === 'COMPLETED') {
              // 최종 "COMPLETED" 메시지 수신: 기존 세그먼트에 한국어 번역 업데이트
              setSegments(prevSegments => {
                // 새로운 번역 데이터를 Map으로 만들어 빠르게 조회 (key: start-end)
                const translatedDataMap = new Map(
                  msg.data.map(translatedSeg => [`${translatedSeg.start}-${translatedSeg.end}`, translatedSeg])
                );

                // 기존 세그먼트 배열을 순회하며, 번역된 텍스트로 업데이트
                const updatedSegments = prevSegments.map(existingSeg => {
                  const key = `${existingSeg.start}-${existingSeg.end}`;
                  const translatedSegData = translatedDataMap.get(key);

                  if (translatedSegData && translatedSegData.korean_text) {
                    // 기존 세그먼트 객체에 korean_text 필드를 추가/업데이트하여 새 객체 반환
                    // 이렇게 하면 React가 변경을 감지하고 해당 세그먼트만 효율적으로 업데이트
                    return { ...existingSeg, korean_text: translatedSegData.korean_text };
                  }
                  // 번역 데이터가 없거나 korean_text가 없으면 기존 세그먼트 유지
                  return existingSeg;
                });
                
                // 만약 COMPLETED 메시지의 msg.data가 항상 모든 세그먼트를 포함하고,
                // 이전 PROCESSING 메시지의 세그먼트와 정확히 일치한다면 (순서나 개수가 다를 수 있음),
                // 아래와 같이 msg.data를 기준으로 prevSegments를 업데이트할 수도 있습니다.
                // 이는 msg.data가 최종적이고 완전한 상태라고 가정합니다.
                /*
                const finalSegments = msg.data.map(finalSeg => {
                    const key = `${finalSeg.start}-${finalSeg.end}`;
                    const existingSegment = prevSegments.find(pSeg => `${pSeg.start}-${pSeg.end}` === key);
                    // 기존 정보(예: active 상태 등 프론트엔드 전용 상태)가 있다면 유지하고,
                    // 서버에서 온 데이터(text, korean_text)로 덮어쓰기
                    return { ...(existingSegment || {}), ...finalSeg };
                });
                return finalSegments.sort((a,b) => a.start - b.start);
                */
              // 위 예시 중 첫번째(prevSegments.map) 방식이 더 '업데이트'에 가깝습니다.
                return updatedSegments.sort((a,b) => a.start - b.start);
              });
              setLoading(false);
              console.log("Segments updated with translations:", msg.data);

            } else if (msg.status === 'PROCESSING' || msg.status === 'STT_COMPLETED_ALL_SEGMENTS') {
              // 중간 STT 결과 (일본어만) 또는 STT 전체 완료 (번역 전)
              setSegments(prevSegments => {
                const newSegmentsMap = new Map(prevSegments.map(s => [`${s.start}-${s.end}`, s]));
                msg.data.forEach(newSeg => {
                  const key = `${newSeg.start}-${newSeg.end}`;
                  // 기존에 없던 세그먼트이거나, 기존 세그먼트에 korean_text가 아직 없는데 새로운 데이터에 text만 있다면 추가/업데이트
                  // (korean_text가 있는 최종 데이터는 COMPLETED에서 처리)
                  if (!newSegmentsMap.has(key) || !newSegmentsMap.get(key).korean_text) {
                    newSegmentsMap.set(key, { ...newSegmentsMap.get(key), ...newSeg }); // 기존 정보에 새 정보 병합
                  }
                });
                return Array.from(newSegmentsMap.values()).sort((a, b) => a.start - b.start);
              });
              console.log("Intermediate STT segments (JP only) updated/added.");
            }
          } else if (msg.data && msg.data.message) {
            console.log("Status message from backend:", msg.data.message);
          }

          if (msg.status === 'COMPLETED' || msg.status === 'FAILED' || msg.status?.includes('FAILED')) {
            setLoading(false);
            if (socketRef.current) {
                socketRef.current.close();
                socketRef.current = null;
                console.log("WebSocket closed by client on task completion/failure.");
            }
          }
        };

        ws.onerror = () => {
          setStatus('WebSocket 오류 발생');
          setLoading(false);
        };
        ws.onclose = () => console.log('WebSocket closed');
      } catch (err) {
        setStatus('에러 발생: ' + err.message);
        setLoading(false);
      }
    };

    fetchAndTranscribe();
    return () => {
      if (socketRef.current) {
        socketRef.current.close();
        socketRef.current = null;
      }
    };
  }, [youtubeUrl]);

    function formatTimestamp(seconds) {
      const totalSeconds = Math.floor(seconds);
      const h = Math.floor(totalSeconds / 3600);
      const m = Math.floor((totalSeconds % 3600) / 60);
      const s = totalSeconds % 60;
    
      if (h > 0) {
        return `${h}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
      } else {
        return `${m}:${s.toString().padStart(2, '0')}`;
      }
    }
  

  return (
    <div className="min-h-screen bg-gray-900 text-white px-4 md:px-12 py-8">
      <h2 className="text-4xl font-extrabold text-center mb-6 text-white drop-shadow">🎬 번역 결과</h2>

      <div className="flex flex-col xl:flex-row gap-8">
        {/* 왼쪽: 영상 + 상태 */}
        <div className="flex-1 space-y-4">
          {videoUrl ? (
            <ReactPlayer
              ref={playerRef}
              url={videoUrl}
              controls
              width="100%"
              height="360px"
            />
          ) : (
            <div className="w-full h-[360px] flex flex-col items-center justify-center bg-gray-800 rounded-md">
              <div className="w-10 h-10 border-4 border-white border-t-transparent rounded-full animate-spin" />
              <p className="mt-4 text-sm text-gray-300">영상 생성 중...</p>
            </div>
          )}

          {/* ✅ 100% 아니면 상태바 보여주기 */}
          {progress !== 100 && (
            <StatusBar status={status} progress={progress} loading={loading} />
          )}

          {/* 데스크탑: 다운로드 버튼 */}
          <div className="hidden xl:block">
            <DownloadButtons segments={segments} />
          </div>
        </div>

        {/* 오른쪽: 자막 영역 */}
        <div className="flex-1">
          <div className="h-[360px] overflow-y-auto bg-gray-800 rounded-lg p-4 shadow-inner">
            {segments.length === 0 && loading ? (
              <div className="h-full flex flex-col items-center justify-center">
                <div className="w-8 h-8 border-4 border-white border-t-transparent rounded-full animate-spin" />
                <p className="mt-4 text-sm text-gray-300">스크립트 생성 중...</p>
              </div>
            ) : (
              segments.map((seg) => {
                const isActive = activeIndex === seg.start;
                // key 값을 좀 더 안정적으로, 예를 들어 start와 end 시간 조합 또는 고유 ID가 있다면 그것 사용
                const segmentKey = `${seg.start}-${seg.end}-${seg.text?.slice(0,5)}`; // 예시
              
                return (
                  <div
                    key={segmentKey} // 수정된 key 사용
                    id={`segment-${segmentKey}`} // id도 key와 일치시키는 것이 좋음
                    onClick={() => playerRef.current?.seekTo(seg.start, 'seconds')}
                    className={`p-3 my-2 rounded-md text-sm transition-all duration-300 border cursor-pointer ${
                      isActive
                        ? 'bg-white text-blue-700 font-bold shadow-lg scale-[1.03]' // 기존 활성 스타일
                        : 'bg-gray-700 text-white/90 hover:bg-gray-600 border-transparent'
                    }`}
                  >
                    <div className="text-xs text-blue-300 font-mono mb-1">
                      [{formatTimestamp(seg.start)} - {formatTimestamp(seg.end)}]
                    </div>
                    {/* 일본어 텍스트 */}
                    <div className="mb-1"> {/* 일본어 텍스트와 한국어 텍스트 사이에 간격을 주기 위해 mb-1 추가 */}
                      <strong className="text-sky-400">JP:</strong> {seg.text}
                    </div>
                    {/* 한국어 번역 텍스트 (korean_text 필드가 있고, 내용이 있고, 플레이스홀더가 아닐 때만 표시) */}
                    {seg.korean_text && seg.korean_text.trim() !== "" && !seg.korean_text.startsWith("[") && (
                      <div className="text-green-400"> {/* 한국어 텍스트 스타일 */}
                        <strong className="text-green-300">KO:</strong> {seg.korean_text}
                      </div>
                    )}
                    {/* (선택적) 번역 오류 또는 플레이스홀더 메시지 처리 */}
                    {seg.korean_text && seg.korean_text.startsWith("[") && (
                         <div className="text-xs text-yellow-500 italic mt-1"> {/* 오류/플레이스홀더 스타일 */}
                             KO: {seg.korean_text}
                         </div>
                    )}
                  </div>
                );
              })
            )}
          </div>

          {/* 모바일: 다운로드 버튼 */}
          <div className="block xl:hidden mt-4">
            <DownloadButtons segments={segments} />
          </div>
        </div>
      </div>
    </div>
  );
};

export default TranslateResult;
