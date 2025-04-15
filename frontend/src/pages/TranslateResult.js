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
//         };

//         ws.onerror = () => setStatus('WebSocket 오류 발생');
//         ws.onclose = () => console.log('WebSocket closed');
//       } catch (err) {
//         setStatus('에러 발생: ' + err.message);
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
//           <ReactPlayer
//             ref={playerRef}
//             url={videoUrl}
//             controls
//             width="100%"
//             height="360px"
//           />
//           <StatusBar status={status} progress={progress} />
//           <DownloadButtons segments={segments} />
//         </div>

//         {/* 📜 자막 영역 */}
//         <div className="flex-1 h-[360px] overflow-y-auto bg-gray-800 rounded-lg p-4 shadow-inner">
//           {segments.map((seg) => {
//             const isActive = activeIndex === seg.start;
//             return (
//               <div
//                 key={seg.start}
//                 id={`segment-${seg.start}`}
//                 className={`p-3 my-2 rounded-md text-sm transition-all duration-300 border ${
//                   isActive
//                     ? 'bg-yellow-400 text-black font-bold shadow-md scale-[1.03]'
//                     : 'bg-gray-700 text-white/90 hover:bg-gray-600 border-transparent'
//                 }`}
//               >
//                 <div className="text-xs text-blue-300 font-mono mb-1">
//                   [{seg.start.toFixed(2)}s - {seg.end.toFixed(2)}s]
//                 </div>
//                 <div>{seg.text}</div>
//               </div>
//             );
//           })}
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
//   const [loading, setLoading] = useState(true); // ✅ 로딩 상태 추가

//   const hasRequestedRef = useRef(false);
//   const playerRef = useRef(null);
//   const socketRef = useRef(null);

//   // 🎯 자막 싱크 추적 + 하이라이트 스크롤
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

//   // 📡 STT 처리 및 WebSocket
//   useEffect(() => {
//     const fetchAndTranscribe = async () => {
//       if (!youtubeUrl || hasRequestedRef.current) return;
//       hasRequestedRef.current = true;

//       try {
//         setStatus('오디오 추출 중...');
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
//           if (msg.status === 'COMPLETED') setLoading(false); // ✅ 완료 시 로딩 해제
//         };

//         ws.onerror = () => setStatus('WebSocket 오류 발생');
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

//       {loading ? (
//         <div className="flex justify-center items-center h-[300px]">
//           <div className="w-16 h-16 border-4 border-blue-500 border-t-transparent rounded-full animate-spin" />
//         </div>
//       ) : (
//         <div className="flex flex-col md:flex-row gap-8">
//           {/* 🎥 영상 + 상태 */}
//           <div className="flex-1 space-y-4">
//             <ReactPlayer
//               ref={playerRef}
//               url={videoUrl}
//               controls
//               width="100%"
//               height="360px"
//             />
//             <StatusBar status={status} progress={progress} />
//             <DownloadButtons segments={segments} />
//           </div>

//           {/* 📜 자막 영역 */}
//           <div className="flex-1 h-[360px] overflow-y-auto bg-gray-800 rounded-lg p-4 shadow-inner">
//             {segments.map((seg) => {
//               const isActive = activeIndex === seg.start;
//               return (
//                 <div
//                   key={seg.start}
//                   id={`segment-${seg.start}`}
//                   className={`p-3 my-2 rounded-md text-sm transition-all duration-300 border ${
//                     isActive
//                       ? 'bg-white text-blue-700 font-bold shadow-lg scale-[1.03]'
//                       : 'bg-gray-700 text-white/90 hover:bg-gray-600 border-transparent'
//                   }`}
//                 >
//                   <div className="text-xs text-blue-300 font-mono mb-1">
//                     [{seg.start.toFixed(2)}s - {seg.end.toFixed(2)}s]
//                   </div>
//                   <div>{seg.text}</div>
//                 </div>
//               );
//             })}
//           </div>
//         </div>
//       )}
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
  const [loading, setLoading] = useState(true); // ✅ 로딩 상태 추가

  const hasRequestedRef = useRef(false);
  const playerRef = useRef(null);
  const socketRef = useRef(null);

  // 자막 싱크 맞춰 하이라이팅 + 스크롤
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
        setLoading(true); // ✅ 로딩 시작

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

  return (
    <div className="min-h-screen bg-gray-900 text-white px-4 md:px-12 py-8">
      <h2 className="text-4xl font-extrabold text-center mb-6 text-white drop-shadow">
        🎬 번역 결과
      </h2>

      <div className="flex flex-col md:flex-row gap-8">
        {/* 🎥 영상 + 상태 */}
        <div className="flex-1 space-y-4">
          <ReactPlayer
            ref={playerRef}
            url={videoUrl}
            controls
            width="100%"
            height="360px"
          />
          <StatusBar status={status} progress={progress} loading={loading} />
          <DownloadButtons segments={segments} />
        </div>

        {/* 📜 자막 영역 */}
        <div className="flex-1 h-[360px] overflow-y-auto bg-gray-800 rounded-lg p-4 shadow-inner">
          {segments.map((seg) => {
            const isActive = activeIndex === seg.start;
            return (
              <div
                key={seg.start}
                id={`segment-${seg.start}`}
                className={`p-3 my-2 rounded-md text-sm transition-all duration-300 border ${
                  isActive
                    ? 'bg-white text-blue-700 font-bold shadow-lg scale-[1.03]'
                    : 'bg-gray-700 text-white/90 hover:bg-gray-600 border-transparent'
                }`}
              >
                <div className="text-xs text-blue-300 font-mono mb-1">
                  [{seg.start.toFixed(2)}s - {seg.end.toFixed(2)}s]
                </div>
                <div>{seg.text}</div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};

export default TranslateResult;
