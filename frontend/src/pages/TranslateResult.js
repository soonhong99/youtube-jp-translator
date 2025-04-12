// // TranslateResult.js
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
//   const [activeIndex, setActiveIndex] = useState(null); // ✅ 현재 자막 인덱스

//   const hasRequestedRef = useRef(false);
//   const playerRef = useRef(null);
//   const socketRef = useRef(null);

//   // 🎯 현재 재생 중인 자막 하이라이트 + 스크롤
//   useEffect(() => {
//     const interval = setInterval(() => {
//       const currentTime = playerRef.current?.getCurrentTime?.() || 0;
//       const current = segments.find(seg => currentTime >= seg.start && currentTime <= seg.end);
//       if (current && activeIndex !== current.start) {
//         setActiveIndex(current.start); // 상태 업데이트로 강제 렌더링
//         const el = document.getElementById(`segment-${current.start}`);
//         if (el) {
//           el.scrollIntoView({ behavior: 'smooth', block: 'center' });
//         }
//       }
//     }, 500);
//     return () => clearInterval(interval);
//   }, [segments, activeIndex]);

//   // STT 요청 + WebSocket 수신 처리
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
//     <div className="min-h-screen bg-gray-50 px-4 md:px-12 py-6">
//       <h2 className="text-3xl font-bold text-center mb-6 text-blue-700">🎬 번역 결과</h2>

//       <div className="flex flex-col md:flex-row gap-6">
//         {/* 🎥 영상 영역 */}
//         <div className="flex-1 min-w-[300px] space-y-4">
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
//         <div className="flex-1 min-w-[300px] h-[360px] overflow-y-auto bg-white rounded-lg shadow-md p-4">
//           {segments.map((seg) => {
//             const isActive = activeIndex === seg.start;
//             return (
//               <div
//                 key={seg.start}
//                 id={`segment-${seg.start}`}
//                 className={`p-3 my-2 text-center rounded transition-all duration-300 ${isActive
//                     ? 'highlight-segment' // ✨ 여기!
//                     : 'hover:bg-gray-100 border border-transparent'
//                   }`}
//               >

//                 <div className="text-blue-600 text-xs font-mono mb-1">
//                   [{seg.start.toFixed(2)}s - {seg.end.toFixed(2)}s]
//                 </div>
//                 <div className="text-sm">{seg.text}</div>
//               </div>
//             );
//           })}
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
        };

        ws.onerror = () => setStatus('WebSocket 오류 발생');
        ws.onclose = () => console.log('WebSocket closed');
      } catch (err) {
        setStatus('에러 발생: ' + err.message);
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
          <StatusBar status={status} progress={progress} />
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
                    ? 'bg-yellow-400 text-black font-bold shadow-md scale-[1.03]'
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
