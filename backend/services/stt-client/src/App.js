import React, { useState, useEffect, useRef, useCallback } from 'react';
import axios from 'axios'; // axios 사용 시
import './App.css';

// 백엔드 API 주소 설정
const EXTRACTOR_API_URL = "http://127.0.0.1:8000"; // IPv4 사용 권장
const STT_API_URL = "http://127.0.0.1:8001";     // IPv4 사용 권장
const WS_BASE_URL = "ws://127.0.0.1:8001";      // WebSocket 주소

function App() {
  const [youtubeUrl, setYoutubeUrl] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [statusMessage, setStatusMessage] = useState('Enter a YouTube URL to start.');
  const [errorMessage, setErrorMessage] = useState('');
  const [taskId, setTaskId] = useState(null);
  const [segments, setSegments] = useState([]); // STT 결과 세그먼트 저장
  const websocket = useRef(null); // WebSocket 객체 저장용 ref

  // WebSocket 메시지 처리 함수
  const handleWebSocketMessage = useCallback((event) => {
    try {
      const message = JSON.parse(event.data);
      console.log('WebSocket Message:', message);

      let statusText = message.status || 'Processing...';
      if (message.progress !== undefined) {
        statusText += ` (${message.progress}%)`;
      }
      if (message.data?.message) { // 작업 진행 메시지 (예: 'Splitting chunks...')
          statusText += ` - ${message.data.message}`;
      }
      setStatusMessage(statusText);

      // 부분 결과(세그먼트) 처리
      if (message.data && Array.isArray(message.data) && message.data.length > 0 && message.data[0].hasOwnProperty('start')) {
        // 청크별 offset 계산은 현재 프론트엔드에서는 어려움
        // 백엔드에서 offset을 포함하거나, 프론트엔드에서 순서대로 합치기
        setSegments(prevSegments => [...prevSegments, ...message.data]);
      }

      // 최종 상태 처리
      if (message.status === 'COMPLETED') {
        setStatusMessage('Transcription Completed!');
        if (websocket.current) {
          websocket.current.close();
        }
      } else if (message.status === 'FAILED' || message.status === 'CHUNK_FAILED') {
        setErrorMessage(`Error: ${message.error || 'An unknown error occurred during processing.'}`);
        setStatusMessage('Processing Failed.');
        if (websocket.current) {
          websocket.current.close();
        }
      }
    } catch (error) {
      console.error("Failed to parse WebSocket message or update state:", error);
      setErrorMessage('Received an invalid message from the server.');
    }
  }, []); // useCallback으로 감싸 불필요한 재선언 방지

  // WebSocket 연결 및 해제 로직 (taskId 변경 시 실행)
  useEffect(() => {
    if (taskId) {
      const wsUrl = `${WS_BASE_URL}/ws/${taskId}`;
      console.log(`Attempting to connect to WebSocket: ${wsUrl}`);
      setStatusMessage('Connecting to WebSocket...');

      // 이전 연결이 있다면 정리
      if (websocket.current) {
          websocket.current.close();
      }

      const ws = new WebSocket(wsUrl);
      websocket.current = ws; // ref에 WebSocket 객체 저장

      ws.onopen = () => {
        console.log('WebSocket Connected');
        setStatusMessage('WebSocket connected. Waiting for transcription progress...');
      };

      ws.onmessage = handleWebSocketMessage; // 메시지 처리 함수 연결

      ws.onerror = (error) => {
        console.error('WebSocket Error:', error);
        setErrorMessage('WebSocket connection error. Please check the console.');
        setStatusMessage('WebSocket Error.');
        setTaskId(null); // 에러 시 Task ID 초기화 고려
      };

      ws.onclose = (event) => {
        console.log('WebSocket Disconnected:', event.reason, event.code);
        // 상태가 완료/실패가 아닐 때만 연결 종료 메시지 표시
        if (!['Transcription Completed!', 'Processing Failed.'].includes(statusMessage)) {
             setStatusMessage('WebSocket disconnected.');
        }
        websocket.current = null; // 연결 종료 시 ref 초기화
      };

      // 컴포넌트 언마운트 또는 taskId 변경 시 WebSocket 연결 해제
      return () => {
        if (ws && ws.readyState === WebSocket.OPEN) {
          console.log('Closing WebSocket connection...');
          ws.close();
          websocket.current = null;
        }
      };
    }
  }, [taskId, handleWebSocketMessage]); // taskId 또는 메시지 핸들러 변경 시 effect 재실행


  // 제출 버튼 클릭 시 처리 함수
  const handleSubmit = async (event) => {
    event.preventDefault();
    if (!youtubeUrl || isLoading) {
      return;
    }

    setIsLoading(true);
    setErrorMessage('');
    setSegments([]); // 이전 결과 초기화
    setTaskId(null); // 이전 Task ID 초기화
    setStatusMessage('Starting process...');

    try {
      // 1. 오디오 추출 요청
      setStatusMessage('Extracting audio...');
      console.log('Requesting audio extraction for:', youtubeUrl);
      const extractResponse = await axios.post(`${EXTRACTOR_API_URL}/extract`, {
        youtube_url: youtubeUrl,
        output_format: "wav",
        sample_rate: 16000,
        channels: 1
      });
      console.log('Extraction response:', extractResponse.data);

      if (!extractResponse.data || !extractResponse.data.file_path) {
        throw new Error('Failed to get audio file path from extractor.');
      }
      const filePath = extractResponse.data.file_path;

      // 2. STT 작업 요청
      setStatusMessage('Requesting transcription...');
      console.log('Requesting transcription for file path:', filePath);
      const sttResponse = await axios.post(`${STT_API_URL}/request_transcription`, {
        wav_file_path: filePath,
        language: "ja" // 필요시 언어 변경
      });
      console.log('STT request response:', sttResponse.data);

      if (!sttResponse.data || !sttResponse.data.task_id || !sttResponse.data.websocket_url) {
        throw new Error('Failed to get task ID or WebSocket URL from STT service.');
      }

      // Task ID 설정 -> useEffect 트리거되어 WebSocket 연결 시작
      setTaskId(sttResponse.data.task_id);

    } catch (error) {
      console.error('Error during process:', error);
      let message = 'An error occurred.';
      if (error.response) {
        // 백엔드 API 에러 응답 처리
        message = `Error ${error.response.status}: ${error.response.data.detail || error.message}`;
      } else if (error.request) {
        // 요청은 보냈으나 응답 받지 못함 (네트워크 오류 등)
        message = 'Could not connect to the backend service. Is it running?';
      } else {
        // 요청 설정 중 에러
        message = `Request setup error: ${error.message}`;
      }
      setErrorMessage(message);
      setStatusMessage('Error occurred.');
      setTaskId(null); // 에러 시 Task ID 초기화
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="App">
      <h1>YouTube STT Service</h1>
      <form onSubmit={handleSubmit}>
        <input
          type="text"
          value={youtubeUrl}
          onChange={(e) => setYoutubeUrl(e.target.value)}
          placeholder="Enter YouTube URL"
          disabled={isLoading}
          required
        />
        <button type="submit" disabled={isLoading}>
          {isLoading ? 'Processing...' : 'Start Transcription'}
        </button>
      </form>

      <div className="status-area">
        <h2>Status</h2>
        <p id="status-message">{statusMessage}</p>
        {errorMessage && <p className="error-message">Error: {errorMessage}</p>}
      </div>

      <div className="results-area">
        <h2>Transcription Results</h2>
        {segments.length === 0 && !isLoading && <p>No results yet.</p>}
        {segments.map((seg, index) => (
          // 청크별 offset 조정이 안되어 start/end 시간은 청크 기준임
          <p key={index}>
            [{seg.start?.toFixed(2)}s - {seg.end?.toFixed(2)}s] {seg.text}
          </p>
        ))}
      </div>
    </div>
  );
}

export default App;