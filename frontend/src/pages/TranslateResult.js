import React, { useEffect, useRef, useState } from 'react';
import { useLocation } from 'react-router-dom';
import StatusBar from '../components/StatusBar';
import DownloadButtons from '../components/DownloadButtons';
import ReactPlayer from 'react-player';
import axios from 'axios';

const TranslateResult = () => {
  // 📌 전달된 YouTube URL을 라우터 상태에서 추출
  const location = useLocation();
  const youtubeUrl = location.state?.youtubeUrl;

  // 📦 상태값 정의
  const [segments, setSegments] = useState([]);             // 자막 세그먼트들
  const [status, setStatus] = useState('STT 진행 중...');   // 상태 메시지
  const [progress, setProgress] = useState(null);           // 진행률 표시
  const [videoUrl, setVideoUrl] = useState('');             // 플레이어에 넣을 유튜브 URL

  // 📌 요청 중복 방지용 Ref (StrictMode에서도 초기화되지 않음!)
  const hasRequestedRef = useRef(false);

  // 🎥 ReactPlayer와 연결할 Ref
  const playerRef = useRef(null);

  // 📍 현재 자막 싱크 추적용 Ref
  const activeRef = useRef(null);

  // 🔌 WebSocket 연결 추적용 Ref
  const socketRef = useRef(null);

  // 🎯 영상 싱크에 맞춰 자막 자동 스크롤
  useEffect(() => {
    const interval = setInterval(() => {
      const currentTime = playerRef.current?.getCurrentTime?.() || 0;
      const current = segments.find(seg => currentTime >= seg.start && currentTime <= seg.end);
      if (current && activeRef.current !== current.start) {
        activeRef.current = current.start;
        const el = document.getElementById(`segment-${current.start}`);
        if (el) {
          el.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
      }
    }, 500);
    return () => clearInterval(interval);
  }, [segments]);

  // 🔁 STT 요청 및 WebSocket 연결
  useEffect(() => {
    const fetchAndTranscribe = async () => {
      // ✅ 이미 요청했으면 더 이상 실행하지 않음
      if (!youtubeUrl || hasRequestedRef.current) return;

      // ✅ 최초 요청이면 true로 설정해서 재요청 방지
      hasRequestedRef.current = true;

      try {
        // 🎤 오디오 추출
        setStatus('오디오 추출 중...');
        const extractRes = await axios.post(`${process.env.REACT_APP_EXTRACTOR_API_URL}/extract`, {
          youtube_url: youtubeUrl,
          output_format: 'wav',
          sample_rate: 16000,
          channels: 1,
        });

        const filePath = extractRes.data.file_path;
        setVideoUrl(youtubeUrl);  // 🎬 영상 URL 세팅

        // 🧠 STT 시작
        setStatus('자막 생성 중...');
        const sttRes = await axios.post(`${process.env.REACT_APP_STT_API_URL}/request_transcription`, {
          wav_file_path: filePath,
          language: 'ja',
        });

        const taskId = sttRes.data.task_id;

        // 🔌 WebSocket 연결
        const ws = new WebSocket(`${process.env.REACT_APP_WS_BASE_URL}/ws/${taskId}`);
        socketRef.current = ws;

        ws.onmessage = (event) => {
          const msg = JSON.parse(event.data);

          // ✅ 자막 세그먼트 수신
          if (msg.data && Array.isArray(msg.data)) {
            setSegments(prev => [...prev, ...msg.data]);
          }

          // 📊 진행률 수신
          if (msg.progress !== undefined) setProgress(msg.progress);

          // 📌 상태 수신
          if (msg.status) setStatus(msg.status);
        };

        ws.onerror = () => setStatus('WebSocket 오류 발생');
        ws.onclose = () => console.log('WebSocket closed');
      } catch (err) {
        setStatus('에러 발생: ' + err.message);
      }
    };

    fetchAndTranscribe();

    // 🧹 컴포넌트 언마운트 시 WebSocket 정리
    return () => {
      if (socketRef.current) {
        socketRef.current.close();
        socketRef.current = null;
      }
    };
  }, [youtubeUrl]); // ✅ 오직 youtubeUrl이 변경될 때만 실행

  return (
    <div className="min-h-screen bg-gray-50 px-4 md:px-12 py-6">
      <h2 className="text-3xl font-bold text-center mb-6 text-blue-700">🎬 번역 결과</h2>

      <div className="flex flex-col md:flex-row gap-6">
        {/* 🎥 영상 영역 */}
        <div className="flex-1 min-w-[300px] space-y-4">
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
        <div className="flex-1 min-w-[300px] h-[360px] overflow-y-auto bg-white rounded-lg shadow-md p-4">
          {segments.map((seg) => {
            const isActive = activeRef.current === seg.start;
            return (
              <div
                key={seg.start}
                id={`segment-${seg.start}`}
                className={`p-3 my-2 text-center rounded transition-all duration-300 border ${
                  isActive
                    ? 'bg-yellow-200 font-semibold shadow-md border-yellow-400'
                    : 'hover:bg-gray-100 border-transparent'
                }`}
              >
                <div className="text-blue-600 text-xs font-mono mb-1">
                  [{seg.start.toFixed(2)}s - {seg.end.toFixed(2)}s]
                </div>
                <div className="text-sm">{seg.text}</div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};

export default TranslateResult;
