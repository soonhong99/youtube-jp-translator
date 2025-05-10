// import React, { useEffect, useRef, useState } from 'react';
// import { useLocation } from 'react-router-dom';
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
//   const [loading, setLoading] = useState(true); // ✅ 로딩 상태 추가

//   const hasRequestedRef = useRef(false);
//   const playerRef = useRef(null);
//   const socketRef = useRef(null);

//   // 자막 싱크 맞춰 하이라이팅 + 스크롤
//   useEffect(() => {
//     const interval = setInterval(() => {
//       const currentTime = playerRef.current?.getCurrentTime?.() || 0;
//       const current = segments.find(seg => currentTime >= seg.start && currentTime <= seg.end);
//       if (current && activeIndex !== current.start) {
//         setActiveIndex(current.start);
//         const el = document.getElementById(`segment-${current.start}`);
//         if (el) {
//           el.scrollIntoView({ behavior: 'smooth', block: 'center' });
//         }
//       }
//     }, 500);
//     return () => clearInterval(interval);
//   }, [segments, activeIndex]);

//   useEffect(() => {
//     const fetchAndTranscribe = async () => {
//       if (!youtubeUrl || hasRequestedRef.current) return;
//       hasRequestedRef.current = true;

//       try {
//         setStatus('오디오 추출 중...');
//         setLoading(true); // ✅ 로딩 시작

//         const extractRes = await axios.post(`${process.env.REACT_APP_EXTRACTOR_API_URL}/extract`, {
//           youtube_url: youtubeUrl,
//           output_format: 'wav',
//           sample_rate: 16000,
//           channels: 1,
//         });

//         const filePath = extractRes.data.file_path;
//         setVideoUrl(youtubeUrl);

//         setStatus('자막 생성 중...');
//         const sttRes = await axios.post(`${process.env.REACT_APP_STT_API_URL}/request_transcription`, {
//           wav_file_path: filePath,
//           language: 'ja',
//         });

//         const taskId = sttRes.data.task_id;
//         const ws = new WebSocket(`${process.env.REACT_APP_WS_BASE_URL}/ws/${taskId}`);
//         socketRef.current = ws;

//         ws.onmessage = (event) => {
//           const msg = JSON.parse(event.data);
//           if (msg.data && Array.isArray(msg.data)) {
//             setSegments(prev => [...prev, ...msg.data]);
//           }
//           if (msg.progress !== undefined) setProgress(msg.progress);
//           if (msg.status) setStatus(msg.status);
//           if (msg.status === 'COMPLETED') setLoading(false);
//         };

//         ws.onerror = () => {
//           setStatus('WebSocket 오류 발생');
//           setLoading(false);
//         };
//         ws.onclose = () => console.log('WebSocket closed');
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

//   return (
//     <div className="min-h-screen bg-gray-900 text-white px-4 md:px-12 py-8">
//       <h2 className="text-4xl font-extrabold text-center mb-6 text-white drop-shadow">
//         🎬 번역 결과
//       </h2>

//       <div className="flex flex-col md:flex-row gap-8">
//         {/* 🎥 영상 + 상태 */}
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
//               <p className="mt-4 text-sm text-gray-300">영상 생성 중...</p> {/* ✅ 스피너 "아래" */}
//             </div>
//           )}

//           <StatusBar status={status} progress={progress} loading={loading} />
//           <DownloadButtons segments={segments} />
//         </div>

//         {/* 📜 자막 영역 */}
//         <div className="flex-1 h-[360px] overflow-y-auto bg-gray-800 rounded-lg p-4 shadow-inner">

//           {segments.length === 0 && loading ? (
//             <div className="h-full flex flex-col items-center justify-center">
//               <div className="w-8 h-8 border-4 border-white border-t-transparent rounded-full animate-spin" />
//               <p className="mt-4 text-sm text-gray-300">스크립트 생성 중...</p> {/* ✅ 스피너 "아래" */}
//             </div>
//           ) : (
//             segments.map((seg) => {
//               const isActive = activeIndex === seg.start;
//               return (
//                 <div
//                   key={seg.start}
//                   id={`segment-${seg.start}`}
//                   className={`p-3 my-2 rounded-md text-sm transition-all duration-300 border ${isActive
//                       ? 'bg-white text-blue-700 font-bold shadow-lg scale-[1.03]'
//                       : 'bg-gray-700 text-white/90 hover:bg-gray-600 border-transparent'
//                     }`}
//                 >
//                   <div className="text-xs text-blue-300 font-mono mb-1">
//                     [{seg.start.toFixed(2)}s - {seg.end.toFixed(2)}s]
//                   </div>
//                   <div>{seg.text}</div>
//                 </div>
//               );
//             })
//           )}
//         </div>


//       </div>
//     </div>
//   );
// };


// export default TranslateResult;


// import React, { useEffect, useRef, useState } from 'react';
// import { useLocation } from 'react-router-dom';
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

//   const hasRequestedRef = useRef(false);
//   const playerRef = useRef(null);
//   const socketRef = useRef(null);

//   useEffect(() => {
//     const interval = setInterval(() => {
//       const currentTime = playerRef.current?.getCurrentTime?.() || 0;
//       const current = segments.find(seg => currentTime >= seg.start && currentTime <= seg.end);
//       if (current && activeIndex !== current.start) {
//         setActiveIndex(current.start);
//         const el = document.getElementById(`segment-${current.start}`);
//         if (el) {
//           el.scrollIntoView({ behavior: 'smooth', block: 'center' });
//         }
//       }
//     }, 500);
//     return () => clearInterval(interval);
//   }, [segments, activeIndex]);

//   useEffect(() => {
//     const fetchAndTranscribe = async () => {
//       if (!youtubeUrl || hasRequestedRef.current) return;
//       hasRequestedRef.current = true;

//       try {
//         setStatus('오디오 추출 중...');
//         setLoading(true);

//         const extractRes = await axios.post(`${process.env.REACT_APP_EXTRACTOR_API_URL}/extract`, {
//           youtube_url: youtubeUrl,
//           output_format: 'wav',
//           sample_rate: 16000,
//           channels: 1,
//         });

//         const filePath = extractRes.data.file_path;
//         setVideoUrl(youtubeUrl);

//         setStatus('자막 생성 중...');
//         const sttRes = await axios.post(`${process.env.REACT_APP_STT_API_URL}/request_transcription`, {
//           wav_file_path: filePath,
//           language: 'ja',
//         });

//         const taskId = sttRes.data.task_id;
//         const ws = new WebSocket(`${process.env.REACT_APP_WS_BASE_URL}/ws/${taskId}`);
//         socketRef.current = ws;

//         ws.onmessage = (event) => {
//           const msg = JSON.parse(event.data);
//           if (msg.data && Array.isArray(msg.data)) {
//             setSegments(prev => [...prev, ...msg.data]);
//           }
//           if (msg.progress !== undefined) setProgress(msg.progress);
//           if (msg.status) setStatus(msg.status);
//           if (msg.status === 'COMPLETED') setLoading(false);
//         };

//         ws.onerror = () => {
//           setStatus('WebSocket 오류 발생');
//           setLoading(false);
//         };
//         ws.onclose = () => console.log('WebSocket closed');
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

//   return (
//     <div className="min-h-screen bg-gray-900 text-white px-4 md:px-12 py-8">
//       <h2 className="text-4xl font-extrabold text-center mb-6 text-white drop-shadow">🎬 번역 결과</h2>

//       {/* ✅ 모바일과 데스크탑을 구분 */}
//       <div className="flex flex-col xl:flex-row gap-8">
//         {/* 왼쪽: 영상 + 상태 */}
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

//           <StatusBar status={status} progress={progress} loading={loading} />

//           {/* 데스크탑에서는 왼쪽에 다운로드 버튼 */}
//           <div className="hidden xl:block">
//             <DownloadButtons segments={segments} />
//           </div>
//         </div>

//         {/* 오른쪽: 자막 영역 */}
//         <div className="flex-1">
//           <div className="h-[360px] overflow-y-auto bg-gray-800 rounded-lg p-4 shadow-inner">
//             {segments.length === 0 && loading ? (
//               <div className="h-full flex flex-col items-center justify-center">
//                 <div className="w-8 h-8 border-4 border-white border-t-transparent rounded-full animate-spin" />
//                 <p className="mt-4 text-sm text-gray-300">스크립트 생성 중...</p>
//               </div>
//             ) : (
//               segments.map((seg) => {
//                 const isActive = activeIndex === seg.start;
//                 return (
//                   <div
//                     key={seg.start}
//                     id={`segment-${seg.start}`}
//                     className={`p-3 my-2 rounded-md text-sm transition-all duration-300 border ${isActive
//                         ? 'bg-white text-blue-700 font-bold shadow-lg scale-[1.03]'
//                         : 'bg-gray-700 text-white/90 hover:bg-gray-600 border-transparent'
//                       }`}
//                   >
//                     <div className="text-xs text-blue-300 font-mono mb-1">
//                       [{seg.start.toFixed(2)}s - {seg.end.toFixed(2)}s]
//                     </div>
//                     <div>{seg.text}</div>
//                   </div>
//                 );
//               })
//             )}
//           </div>

//           {/* ✅ 모바일에서만 다운로드 버튼 아래 고정 */}
//           <div className="block xl:hidden mt-4">
//             <DownloadButtons segments={segments} />
//           </div>
//         </div>
//       </div>
//     </div>
//   );
// };

// export default TranslateResult;



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

        ws.onmessage = (event) => {
          const msg = JSON.parse(event.data);
          if (msg.data && Array.isArray(msg.data)) {
            setSegments(prev => [...prev, ...msg.data]);
          }
          if (msg.progress !== undefined) setProgress(msg.progress);
          if (msg.status) setStatus(msg.status);
          if (msg.status === 'COMPLETED') setLoading(false);
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
                return (
                  <div
                    key={seg.start}
                    id={`segment-${seg.start}`}
                    onClick={() => playerRef.current?.seekTo(seg.start, 'seconds')}
                    className={`p-3 my-2 rounded-md text-sm transition-all duration-300 border cursor-pointer ${isActive
                        ? 'bg-white text-blue-700 font-bold shadow-lg scale-[1.03]'
                        : 'bg-gray-700 text-white/90 hover:bg-gray-600 border-transparent'
                      }`}
                  >
                    <div className="text-xs text-blue-300 font-mono mb-1">
                      [{formatTimestamp(seg.start)} - {formatTimestamp(seg.end)}]
                    </div>
                    <div>{seg.text}</div>
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
