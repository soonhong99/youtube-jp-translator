// import React, { useEffect, useRef, useState } from 'react';
// import { useLocation } from 'react-router-dom';
// import Popup from '../components/Popup';   // 추가
// import StatusBar from '../components/StatusBar';
// import DownloadButtons from '../components/DownloadButtons';
// import ReactPlayer from 'react-player';
// import axios from 'axios';

// const TranslateResult = () => {
//   const location = useLocation();
//   const youtubeUrl = location.state?.youtubeUrl;

//   const [segments, setSegments] = useState([]);
//   const [status, setStatus] = useState('STT 진행 중...');
//   const [progress, setProgress] = useState(null);
//   const [videoUrl, setVideoUrl] = useState('');
//   const [activeIndex, setActiveIndex] = useState(null);
//   const [loading, setLoading] = useState(true);

//   // 팝업 상태
//   const [showPopup, setShowPopup] = useState(false);

//   const hasRequestedRef = useRef(false);
//   const playerRef = useRef(null);
//   const socketRef = useRef(null);

//   // TTS 오디오 태그 관리용 ref
//   const audioRefs = useRef({});
//   const [playingIndex, setPlayingIndex] = useState(null);

//   // ─── 재생 시 자막 하이라이트 & 스크롤 ───
//   useEffect(() => {
//     const interval = setInterval(() => {
//       const currentTime = playerRef.current?.getCurrentTime?.() || 0;
//       const currentSegment = segments.find(
//         (seg) => currentTime >= seg.start && currentTime <= seg.end
//       );
//       if (currentSegment && activeIndex !== currentSegment.start) {
//         setActiveIndex(currentSegment.start);
//         const el = document.getElementById(`segment-${currentSegment.start}-${currentSegment.end}`);
//         if (el) {
//           el.scrollIntoView({ behavior: 'smooth', block: 'center' });
//         }
//       }
//     }, 500);
//     return () => clearInterval(interval);
//   }, [segments, activeIndex]);

//   // ─── STT + 번역 요청 & WebSocket ───
//   useEffect(() => {
//     const fetchAndTranscribe = async () => {
//       if (!youtubeUrl || hasRequestedRef.current) return;
//       hasRequestedRef.current = true;

//       try {
//         setStatus('오디오 추출 중...');
//         setLoading(true);

//         // 1) 오디오 추출
//         const extractRes = await axios.post(
//           `${process.env.REACT_APP_EXTRACTOR_API_URL}/extract`,
//           {
//             youtube_url: youtubeUrl,
//             output_format: 'wav',
//             sample_rate: 16000,
//             channels: 1,
//           }
//         );
//         const filePath = extractRes.data.file_path;
//         setVideoUrl(youtubeUrl);

//         // 2) STT 요청
//         setStatus('자막 생성 중...');
//         const sttRes = await axios.post(
//           `${process.env.REACT_APP_STT_API_URL}/request_transcription`,
//           {
//             wav_file_path: filePath,
//             language: 'ja',
//           }
//         );
//         const taskId = sttRes.data.task_id;

//         // 3) WebSocket 연결
//         const ws = new WebSocket(`${process.env.REACT_APP_WS_BASE_URL}/ws/${taskId}`);
//         socketRef.current = ws;

//         ws.onmessage = (event) => {
//           const msg = JSON.parse(event.data);

//           if (msg.status) setStatus(msg.status);
//           if (msg.progress !== undefined) setProgress(msg.progress);

//           if (msg.data && Array.isArray(msg.data)) {
//             if (msg.status === 'COMPLETED') {
//               setSegments((prevSegments) => {
//                 const translatedMap = new Map(
//                   msg.data.map((translatedSeg) => [
//                     `${translatedSeg.start}-${translatedSeg.end}`,
//                     translatedSeg.korean_text || ''
//                   ])
//                 );
//                 return prevSegments.map((origSeg) => {
//                   const key = `${origSeg.start}-${origSeg.end}`;
//                   if (translatedMap.has(key)) {
//                     return {
//                       ...origSeg,
//                       korean_text: translatedMap.get(key)
//                     };
//                   }
//                   return origSeg;
//                 });
//               });
//               setLoading(false);
//               setShowPopup(true); // 팝업 표시!
//             } else {
//               setSegments((prevSegments) => {
//                 const existingMap = new Map(
//                   prevSegments.map((s) => [`${s.start}-${s.end}`, s])
//                 );
//                 msg.data.forEach((newSeg) => {
//                   const key = `${newSeg.start}-${newSeg.end}`;
//                   if (!existingMap.has(key)) {
//                     existingMap.set(key, { ...newSeg });
//                   }
//                 });
//                 return Array.from(existingMap.values()).sort((a, b) => a.start - b.start);
//               });
//             }
//           }

//           if (
//             msg.status === 'COMPLETED' ||
//             msg.status === 'FAILED' ||
//             (msg.status && msg.status.includes('FAILED'))
//           ) {
//             setLoading(false);
//             if (socketRef.current) {
//               socketRef.current.close();
//               socketRef.current = null;
//             }
//           }
//         };

//         ws.onerror = () => {
//           setStatus('WebSocket 오류 발생');
//           setLoading(false);
//         };
//         ws.onclose = () => {};
//       } catch (err) {
//         setStatus('에러 발생: ' + err.message);
//         setLoading(false);
//       }
//     };

//     fetchAndTranscribe();
//     return () => {
//       if (socketRef.current) {
//         socketRef.current.close();
//         socketRef.current = null;
//       }
//     };
//   }, [youtubeUrl]);

//   function formatTimestamp(seconds) {
//     const totalSeconds = Math.floor(seconds);
//     const h = Math.floor(totalSeconds / 3600);
//     const m = Math.floor((totalSeconds % 3600) / 60);
//     const s = totalSeconds % 60;
//     if (h > 0) {
//       return `${h}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
//     } else {
//       return `${m}:${s.toString().padStart(2, '0')}`;
//     }
//   }

//   return (
//     <div className="min-h-screen bg-gray-900 text-white px-4 md:px-12 py-8">
      
//       <h2 className="text-4xl font-extrabold text-center mb-6 text-white drop-shadow">
//         🎬 번역 결과
//       </h2>

//       <div className="flex flex-col xl:flex-row gap-8">
//         {/* 왼쪽: 영상 + 상태바 */}
//         <div className="flex-1 space-y-4">
//           {videoUrl ? (
//             <ReactPlayer
//               ref={playerRef}
//               url={videoUrl}
//               controls
//               width="100%"
//               height="360px"
//             />
//           ) : (
//             <div className="w-full h-[360px] flex flex-col items-center justify-center bg-gray-800 rounded-md">
//               <div className="w-10 h-10 border-4 border-white border-t-transparent rounded-full animate-spin" />
//               <p className="mt-4 text-sm text-gray-300">영상 생성 중...</p>
//             </div>
//           )}

//           {progress !== 100 && (
//             <StatusBar status={status} progress={progress} loading={loading} />
//           )}

//           <div className="hidden xl:block">
//             <DownloadButtons segments={segments} />
//           </div>
//         </div>

//         {/* 오른쪽: 자막 + 번역 영역 */}
//         <div className="flex-1">
//           <div className="h-[360px] overflow-y-auto bg-gray-800 rounded-lg p-4 shadow-inner">
//             {segments.length === 0 && loading ? (
//               <div className="h-full flex flex-col items-center justify-center">
//                 <div className="w-8 h-8 border-4 border-white border-t-transparent rounded-full animate-spin" />
//                 <p className="mt-4 text-sm text-gray-300">스크립트 생성 중...</p>
//               </div>
//             ) : (
//               segments.map((seg, idx) => {
//                 const key = `${seg.start}-${seg.end}`;
//                 const isActive = activeIndex === seg.start;
//                 return (
//                   <div
//                     key={key}
//                     id={`segment-${key}`}
//                     onClick={() => playerRef.current?.seekTo(seg.start, 'seconds')}
//                     className={`p-3 my-2 rounded-md text-sm transition-all duration-300 border cursor-pointer ${
//                       isActive
//                         ? 'bg-white text-blue-700 font-bold shadow-lg scale-[1.03]'
//                         : 'bg-gray-700 text-white/90 hover:bg-gray-600 border-transparent'
//                     }`}
//                   >
//                     {/* 타임스탬프 */}
//                     <div className="text-xs text-blue-300 font-mono mb-1">
//                       [{formatTimestamp(seg.start)} - {formatTimestamp(seg.end)}]
//                     </div>

//                     {/* 일본어 원문 + TTS 버튼 */}
//                     <div className="mb-1 flex items-center">
//                       <strong className="text-sky-400">JP:</strong>&nbsp;{seg.text}
//                       <button
//                         className="ml-2 p-1 hover:bg-sky-600 rounded"
//                         onClick={async (e) => {
//                           e.stopPropagation();
//                           setPlayingIndex(idx);
//                           try {
//                             const res = await axios.post(
//                               `${process.env.REACT_APP_TTS_API_URL}/synthesize_tts`,
//                               { text: seg.text }
//                             );
//                             const audioUrl = res.data.audio_url.startsWith("http")
//                               ? res.data.audio_url
//                               : `${process.env.REACT_APP_TTS_API_URL}${res.data.audio_url}`;
//                             if (audioRefs.current[idx]) {
//                               audioRefs.current[idx].src = audioUrl;
//                               audioRefs.current[idx].play();
//                             }
//                           } catch (err) {
//                             alert("TTS 재생 실패!");
//                           }
//                         }}
//                         title="일본어 TTS 재생"
//                       >
//                         <span role="img" aria-label="재생">🔊</span>
//                       </button>
//                       <audio
//                         ref={el => (audioRefs.current[idx] = el)}
//                         onEnded={() => setPlayingIndex(null)}
//                       />
//                     </div>

//                     {/* 한국어 번역 */}
//                     {seg.korean_text && (
//                       <div className="text-green-400">
//                         <strong className="text-green-300">KO:</strong> {seg.korean_text}
//                       </div>
//                     )}
//                   </div>
//                 );
//               })
//             )}
//           </div>

//           <div className="block xl:hidden mt-4">
//             <DownloadButtons segments={segments} />
//           </div>
//         </div>
//       </div>
//       {showPopup && (
//         <Popup
//           message="스크립트가 성공적으로 생성되었습니다! 번역 결과와 다양한 기능들을 지금 바로 이용해보세요."
//           onClose={() => setShowPopup(false)}
//         />
//       )}
//     </div>
//   );
// };

// export default TranslateResult;

import React, { useEffect, useRef, useState } from 'react';
import { useLocation } from 'react-router-dom';
import Popup from '../components/Popup';
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

  // 팝업 상태
  const [showPopup, setShowPopup] = useState(false);

  // 자동스크롤 상태
  const [autoScroll, setAutoScroll] = useState(true);

  const hasRequestedRef = useRef(false);
  const playerRef = useRef(null);
  const socketRef = useRef(null);

  // TTS 오디오 태그 관리용 ref
  const audioRefs = useRef({});
  const [playingIndex, setPlayingIndex] = useState(null);

  // 스크립트 영역 ref
  const scrollRef = useRef(null);

  // ─── 재생 시 자막 하이라이트 & 자동 스크롤 ───
  useEffect(() => {
    let interval = null;
    if (autoScroll) {
      interval = setInterval(() => {
        const currentTime = playerRef.current?.getCurrentTime?.() || 0;
        const currentSegment = segments.find(
          (seg) => currentTime >= seg.start && currentTime <= seg.end
        );
        if (currentSegment && activeIndex !== currentSegment.start) {
          setActiveIndex(currentSegment.start);
          const el = document.getElementById(`segment-${currentSegment.start}-${currentSegment.end}`);
          if (el) {
            el.scrollIntoView({ behavior: 'smooth', block: 'center' });
          }
        }
      }, 500);
    }
    return () => interval && clearInterval(interval);
  }, [segments, activeIndex, autoScroll]);

  // ─── 사용자가 스크롤 하면 자동스크롤 해제 ───
  useEffect(() => {
    const onScroll = () => {
      if (autoScroll && scrollRef.current) {
        setAutoScroll(false);
      }
    };
    const scrollArea = scrollRef.current;
    if (scrollArea) {
      scrollArea.addEventListener('wheel', onScroll);
      scrollArea.addEventListener('touchmove', onScroll);
    }
    return () => {
      if (scrollArea) {
        scrollArea.removeEventListener('wheel', onScroll);
        scrollArea.removeEventListener('touchmove', onScroll);
      }
    };
  }, [autoScroll, segments]);

  // ─── STT + 번역 요청 & WebSocket ───
  useEffect(() => {
    const fetchAndTranscribe = async () => {
      if (!youtubeUrl || hasRequestedRef.current) return;
      hasRequestedRef.current = true;

      try {
        setStatus('오디오 추출 중...');
        setLoading(true);

        // 1) 오디오 추출
        const extractRes = await axios.post(
          `${process.env.REACT_APP_API_GATEWAY_URL}/api/youtube/extract`,
          {
            youtube_url: youtubeUrl,
            output_format: 'wav',
            sample_rate: 16000,
            channels: 1,
          }
        );
        const filePath = extractRes.data.file_path;
        setVideoUrl(youtubeUrl);

        // 2) STT 요청
        setStatus('자막 생성 중...');
        const sttRes = await axios.post(
          `${process.env.REACT_APP_API_GATEWAY_URL}/api/stt/transcribe`,
          {
            wav_file_path: filePath,
            language: 'ja',
          }
        );
        const taskId = sttRes.data.task_id;

        // 3) WebSocket 연결
        const ws = new WebSocket(
          `${process.env.REACT_APP_WS_BASE_URL}/ws/${taskId}`
        );
        socketRef.current = ws;

        ws.onmessage = (event) => {
          const msg = JSON.parse(event.data);

          if (msg.status) setStatus(msg.status);
          if (msg.progress !== undefined) setProgress(msg.progress);

          if (msg.data && Array.isArray(msg.data)) {
            if (msg.status === 'COMPLETED') {
              // 백엔드에서 완전한 세그먼트 데이터(일본어 + 한국어)를 받으므로 직접 설정
              setSegments(msg.data);
              setLoading(false);
              setShowPopup(true);
            } else {
              setSegments((prevSegments) => {
                const existingMap = new Map(
                  prevSegments.map((s) => [`${s.start}-${s.end}`, s])
                );
                msg.data.forEach((newSeg) => {
                  const key = `${newSeg.start}-${newSeg.end}`;
                  if (!existingMap.has(key)) {
                    existingMap.set(key, { ...newSeg });
                  }
                });
                return Array.from(existingMap.values()).sort((a, b) => a.start - b.start);
              });
            }
          }

          if (
            msg.status === 'COMPLETED' ||
            msg.status === 'FAILED' ||
            (msg.status && msg.status.includes('FAILED'))
          ) {
            setLoading(false);
            if (socketRef.current) {
              socketRef.current.close();
              socketRef.current = null;
            }
          }
        };

        ws.onerror = () => {
          setStatus('WebSocket 오류 발생');
          setLoading(false);
        };
        ws.onclose = () => {};
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

  // 현재위치(자동스크롤) 버튼 클릭 시 동작
  const handleAutoScroll = () => {
    setAutoScroll(true);
    // 현재 activeIndex 위치로 이동
    if (segments.length > 0 && activeIndex !== null) {
      const seg = segments.find(s => s.start === activeIndex);
      if (seg) {
        const el = document.getElementById(`segment-${seg.start}-${seg.end}`);
        if (el) {
          el.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
      }
    }
  };

  return (
    <div className="min-h-screen bg-gray-900 text-white px-4 md:px-12 py-8">
      {/* 네비게이션 컴포넌트(예: <Navbar />)는 여기 추가 */}
      <h2 className="text-4xl font-extrabold text-center mb-6 text-white drop-shadow">
        🎬 번역 결과
      </h2>

      <div className="flex flex-col xl:flex-row gap-8">
        {/* 왼쪽: 영상 + 상태바 */}
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

          {progress !== 100 && (
            <StatusBar status={status} progress={progress} loading={loading} />
          )}

          <div className="hidden xl:block">
            <DownloadButtons segments={segments} />
          </div>
        </div>

        {/* 오른쪽: 자막 + 번역 영역 */}
        <div className="flex-1">
          {/* 자동스크롤 해제시 안내 & 현재위치 버튼 */}
          {!autoScroll && (
            <div className="flex justify-end mb-2">
              <button
                className="bg-blue-500 text-white px-3 py-1 rounded shadow hover:bg-blue-600 transition"
                onClick={handleAutoScroll}
              >
                현재위치로 이동
              </button>
            </div>
          )}
          <div
            className="h-[360px] overflow-y-auto bg-gray-800 rounded-lg p-4 shadow-inner"
            ref={scrollRef}
          >
            {segments.length === 0 && loading ? (
              <div className="h-full flex flex-col items-center justify-center">
                <div className="w-8 h-8 border-4 border-white border-t-transparent rounded-full animate-spin" />
                <p className="mt-4 text-sm text-gray-300">스크립트 생성 중...</p>
              </div>
            ) : (
              segments.map((seg, idx) => {
                const key = `${seg.start}-${seg.end}`;
                const isActive = activeIndex === seg.start;
                return (
                  <div
                    key={key}
                    id={`segment-${key}`}
                    onClick={() => playerRef.current?.seekTo(seg.start, 'seconds')}
                    className={`p-3 my-2 rounded-md text-sm transition-all duration-300 border cursor-pointer ${
                      isActive
                        ? 'bg-white text-blue-700 font-bold shadow-lg scale-[1.03]'
                        : 'bg-gray-700 text-white/90 hover:bg-gray-600 border-transparent'
                    }`}
                  >
                    {/* 타임스탬프 */}
                    <div className="text-xs text-blue-300 font-mono mb-1">
                      [{formatTimestamp(seg.start)} - {formatTimestamp(seg.end)}]
                    </div>

                    {/* 일본어 원문 + TTS 버튼 */}
                    <div className="mb-1 flex items-center">
                      <strong className="text-sky-400">JP:</strong>&nbsp;{seg.text}
                      <button
                        className="ml-2 p-1 hover:bg-sky-600 rounded"
                        onClick={async (e) => {
                          e.stopPropagation();
                          setPlayingIndex(idx);
                          try {
                            const res = await axios.post(
                              `${process.env.REACT_APP_TTS_API_URL}/synthesize_tts`,
                              { text: seg.text }
                            );
                            const audioUrl = res.data.audio_url.startsWith("http")
                              ? res.data.audio_url
                              : `${process.env.REACT_APP_TTS_API_URL}${res.data.audio_url}`;
                            if (audioRefs.current[idx]) {
                              audioRefs.current[idx].src = audioUrl;
                              audioRefs.current[idx].play();
                            }
                          } catch (err) {
                            alert("TTS 재생 실패!");
                          }
                        }}
                        title="일본어 TTS 재생"
                      >
                        <span role="img" aria-label="재생">🔊</span>
                      </button>
                      <audio
                        ref={el => (audioRefs.current[idx] = el)}
                        onEnded={() => setPlayingIndex(null)}
                      />
                    </div>

                    {/* 한국어 번역 */}
                    {seg.korean_text && (
                      <div className="text-green-400">
                        <strong className="text-green-300">KO:</strong> {seg.korean_text}
                      </div>
                    )}
                  </div>
                );
              })
            )}
          </div>
          <div className="block xl:hidden mt-4">
            <DownloadButtons segments={segments} />
          </div>
        </div>
      </div>
      {showPopup && (
        <Popup
          message="스크립트가 성공적으로 생성되었습니다! 번역 결과와 다양한 기능들을 지금 바로 이용해보세요."
          onClose={() => setShowPopup(false)}
        />
      )}
    </div>
  );
};

export default TranslateResult;
