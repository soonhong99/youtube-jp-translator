import React, { useEffect, useRef, useState } from 'react';
import { useLocation } from 'react-router-dom';
import StatusBar from '../components/StatusBar';
import DownloadButtons from '../components/DownloadButtons';
import ReactPlayer from 'react-player';
import axios from 'axios';

const TranslateResult = () => {
  // React Router를 통해 전달된 YouTube URL
  const location = useLocation();
  const youtubeUrl = location.state?.youtubeUrl;

  // 상태 변수들
  const [segments, setSegments] = useState([]);          // STT로 생성된 자막 세그먼트
  const [status, setStatus] = useState('STT 진행 중...'); // 현재 처리 상태 표시용 텍스트
  const [progress, setProgress] = useState(null);         // 진행률 (0~100)
  const [videoUrl, setVideoUrl] = useState('');           // ReactPlayer에 들어갈 YouTube URL
  const [activeIndex, setActiveIndex] = useState(null);   // 현재 재생 구간 세그먼트 시작 시간
  const [loading, setLoading] = useState(true);           // 로딩 상태

  // Ref 객체들
  const hasRequestedRef = useRef(false);  // 중복 요청 방지
  const playerRef = useRef(null);         // ReactPlayer 참조
  const socketRef = useRef(null);         // WebSocket 참조

  // 🔊 TTS 요청 및 음성 재생 함수
  const speak = async (text) => {
    try {
      // TTS 백엔드에 텍스트 요청
      await axios.post('http://localhost:8010/synthesize_audio', { text });
      // 생성된 output.wav 경로로 오디오 재생
      const audio = new Audio('http://localhost:8010/audio/output.wav');
      audio.play();
    } catch (err) {
      console.error("TTS 요청 실패:", err);
    }
  };

  // 🎯 영상 재생 시간에 맞춰 자막 자동 하이라이팅 및 스크롤
  useEffect(() => {
    const interval = setInterval(() => {
      const currentTime = playerRef.current?.getCurrentTime?.() || 0;
      const current = segments.find(
        (seg) => currentTime >= seg.start && currentTime <= seg.end
      );
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

  // 🔄 YouTube URL 변경 시 STT 및 WebSocket 처리
  useEffect(() => {
    const fetchAndTranscribe = async () => {
      if (!youtubeUrl || hasRequestedRef.current) return;
      hasRequestedRef.current = true;

      try {
        // 1) 오디오 추출 요청
        setStatus('오디오 추출 중...');
        setLoading(true);
        const extractRes = await axios.post(
          `${process.env.REACT_APP_EXTRACTOR_API_URL}/extract`,
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
          `${process.env.REACT_APP_STT_API_URL}/request_transcription`,
          {
            wav_file_path: filePath,
            language: 'ja',
          }
        );
        const taskId = sttRes.data.task_id;

        // 3) WebSocket 연결하여 실시간 자막 수신
        const ws = new WebSocket(
          `${process.env.REACT_APP_WS_BASE_URL}/ws/${taskId}`
        );
        socketRef.current = ws;

        ws.onmessage = (event) => {
          const msg = JSON.parse(event.data);
          if (msg.data && Array.isArray(msg.data)) {
            setSegments((prev) => [...prev, ...msg.data]);
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

  // 자막의 초(second)를 [MM:SS] 형식으로 반환
  function formatTimestamp(seconds) {
    const totalSeconds = Math.floor(seconds);
    const h = Math.floor(totalSeconds / 3600);
    const m = Math.floor((totalSeconds % 3600) / 60);
    const s = totalSeconds % 60;
    return h > 0
      ? `${h}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`
      : `${m}:${s.toString().padStart(2, '0')}`;
  }

  return (
    <div className="min-h-screen bg-gray-900 text-white px-4 md:px-12 py-8">
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

          {/* STT 진행 상태바 (진행률이 100%가 아닐 때만 표시) */}
          {progress !== 100 && (
            <StatusBar status={status} progress={progress} loading={loading} />
          )}

          {/* 다운로드 버튼 (데스크탑에만 보여줌) */}
          <div className="hidden xl:block">
            <DownloadButtons segments={segments} />
          </div>
        </div>

        {/* 오른쪽: 자막 목록 + TTS 버튼 */}
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
                    onClick={() =>
                      playerRef.current?.seekTo(seg.start, 'seconds')
                    }
                    className={`p-3 my-2 rounded-md text-sm transition-all duration-300 border cursor-pointer ${
                      isActive
                        ? 'bg-white text-blue-700 font-bold shadow-lg scale-[1.03]'
                        : 'bg-gray-700 text-white/90 hover:bg-gray-600 border-transparent'
                    }`}
                  >
                    <div className="flex justify-between items-center">
                      {/* 좌측: [타임스탬프] */}
                      <div className="text-xs text-blue-300 font-mono">
                        [{formatTimestamp(seg.start)} -{' '}
                        {formatTimestamp(seg.end)}]
                      </div>

                      {/* 우측: 🔊 TTS 재생 버튼 */}
                      <button
                        onClick={(e) => {
                          e.stopPropagation(); // 자막 클릭 시 영상 이동 막기
                          speak(seg.text); // TTS 요청 및 재생
                        }}
                        className="text-blue-400 text-xs hover:text-blue-200"
                      >
                        🔊
                      </button>
                    </div>

                    {/* 자막 텍스트 */}
                    <div>{seg.text}</div>
                  </div>
                );
              })
            )}
          </div>

          {/* 다운로드 버튼 (모바일에만 보여줌) */}
          <div className="block xl:hidden mt-4">
            <DownloadButtons segments={segments} />
          </div>
        </div>
      </div>
    </div>
  );
};

export default TranslateResult;
