import React, { useEffect, useRef, useState } from 'react';
import StatusBar from '../components/StatusBar';
import ResultsDisplay from '../components/ResultsDisplay';
import DownloadButtons from '../components/DownloadButtons';
import ReactPlayer from 'react-player';
import '../styles/animations.css';

const TranslateResult = () => {
  const [segments, setSegments] = useState([]);
  const [status, setStatus] = useState('STT 진행 중...');
  const [progress, setProgress] = useState(null);
  const [videoUrl, setVideoUrl] = useState(''); // 실제 데이터 연동 필요
  const playerRef = useRef(null);
  const activeRef = useRef(null);

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

  return (
    <div className="px-4 md:px-12 py-6">
      <h2 className="text-3xl font-semibold mb-4">번역 결과</h2>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div className="shadow-xl rounded-lg overflow-hidden">
          <ReactPlayer ref={playerRef} url={videoUrl} controls width="100%" height="360px" />
          <StatusBar status={status} progress={progress} />
          <DownloadButtons segments={segments} />
        </div>
        <div className="h-[400px] overflow-y-scroll bg-white rounded-lg shadow-inner p-4">
          <ResultsDisplay segments={segments} />
        </div>
      </div>
    </div>
  );
};

export default TranslateResult;