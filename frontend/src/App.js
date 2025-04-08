import React, { useState, useEffect, useRef, useCallback } from 'react';
import axios from 'axios'; // 또는 fetch 사용
import UrlInput from './UrlInput'; // 아래에서 만들 컴포넌트
import StatusBar from './StatusBar';   // 아래에서 만들 컴포넌트
import ResultsDisplay from './ResultsDisplay'; // 아래에서 만들 컴포넌트
import './App.css';

const EXTRACTOR_API_URL = process.env.REACT_APP_EXTRACTOR_API_URL || "http://127.0.0.1:8000";
const STT_API_URL = process.env.REACT_APP_STT_API_URL || "http://127.0.0.1:8001";
const WS_BASE_URL = process.env.REACT_APP_WS_BASE_URL || "ws://127.0.0.1:8001";

function App() {
  const [youtubeUrl, setYoutubeUrl] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [statusMessage, setStatusMessage] = useState('Enter a YouTube URL to start.');
  const [progress, setProgress] = useState(null);
  const [errorMessage, setErrorMessage] = useState('');
  const [taskId, setTaskId] = useState(null);
  const [segments, setSegments] = useState([]);
  const websocket = useRef(null);

  // WebSocket 메시지 처리 콜백
  const handleWebSocketMessage = useCallback((event) => {
    try {
      const message = JSON.parse(event.data);
      console.log('WS Message Received:', message);

      let currentStatus = message.status || 'Processing...';
      setStatusMessage(currentStatus); // 기본 상태 메시지 업데이트

      if (message.progress !== undefined) {
        setProgress(message.progress);
        currentStatus += ` (${message.progress}%)`; // 진행률 포함 상태
      } else {
        setProgress(null); // 진행률 정보 없으면 초기화
      }

       if (message.data?.message) {
           currentStatus += ` - ${message.data.message}`;
       }
       setStatusMessage(currentStatus); // 최종 상태 메시지 업데이트

      // 세그먼트 데이터 처리
      if (message.data && Array.isArray(message.data) && message.data.length > 0 && message.data[0].hasOwnProperty('start')) {
        setSegments(prevSegments => {
          // 간단히 합치기 (정렬이 필요하면 여기서 구현)
          const combined = [...prevSegments, ...message.data];
          // 예시: 시작 시간 기준으로 정렬
          // combined.sort((a, b) => a.start - b.start);
          // 예시: 중복 제거 (매우 단순한 방식, key 필요할 수 있음)
          // const uniqueSegments = Array.from(new Map(combined.map(item => [item.start + item.text, item])).values());
          // return uniqueSegments;
          return combined;
        });
      }

      // 최종 상태 처리
      if (message.status === 'COMPLETED') {
        setStatusMessage('Transcription Completed!');
        setProgress(100);
        if (websocket.current) websocket.current.close();
      } else if (message.status === 'FAILED' || message.status === 'CHUNK_FAILED') {
        setErrorMessage(`Error: ${message.error || 'Processing failed.'}`);
        setStatusMessage('Processing Failed.');
        setProgress(null);
        if (websocket.current) websocket.current.close();
      }
    } catch (error) {
      console.error("Failed to parse WebSocket message or update state:", error);
      setErrorMessage('Received an invalid message.');
    }
  }, [statusMessage]); // statusMessage 의존성 추가 (onclose 에서 사용)

  // WebSocket 연결 관리 Effect
  useEffect(() => {
      if (taskId) {
          // process.env에서 환경 변수를 읽거나, 파일 상단에 정의된 상수 사용
          const wsBase = process.env.REACT_APP_WS_BASE_URL || "ws://127.0.0.1:8001";
          // 템플릿 리터럴(백틱 `)을 사용하여 변수(taskId)를 올바르게 포함
          const wsUrl = `${wsBase}/ws/${taskId}`;

          console.log(`Connecting to WebSocket: ${wsUrl}`);
          setStatusMessage('Connecting to WebSocket...');
          setProgress(null); // 연결 시작 시 진행률 초기화

          try {
            const ws = new WebSocket(wsUrl); // 올바른 URL로 연결 시도
            websocket.current = ws;
  
            ws.onopen = () => {
                console.log('WebSocket Connected');
                setStatusMessage('WebSocket connected. Waiting for results...');
            };
  
            // 메시지 핸들러를 useEffect 내부에 정의하면 useCallback/의존성 관리가 단순해짐
            ws.onmessage = (event) => {
                try {
                    const message = JSON.parse(event.data);
                    console.log('WS Message Received:', message);
  
                    let currentStatus = message.status || 'Processing...';
                    // ... (이하 메시지 처리 로직은 이전 답변과 동일) ...
                    setStatusMessage(currentStatus); // 기본 상태 메시지 업데이트
  
                    if (message.progress !== undefined) {
                      setProgress(message.progress);
                      currentStatus += ` (${message.progress}%)`; // 진행률 포함 상태
                    } else {
                      setProgress(null); // 진행률 정보 없으면 초기화
                    }
  
                     if (message.data?.message) {
                         currentStatus += ` - ${message.data.message}`;
                     }
                     setStatusMessage(currentStatus); // 최종 상태 메시지 업데이트
  
                    // 세그먼트 데이터 처리
                    if (message.data && Array.isArray(message.data) && message.data.length > 0 && message.data[0].hasOwnProperty('start')) {
                      setSegments(prevSegments => {
                        const combined = [...prevSegments, ...message.data];
                        combined.sort((a, b) => a.start - b.start); // 시간순 정렬
                        // 간단한 중복 제거 (필요시 더 정교하게)
                        const uniqueMap = new Map();
                        combined.forEach(item => uniqueMap.set(`${item.start}-${item.end}-${item.text.slice(0,10)}`, item));
                        return Array.from(uniqueMap.values());
                      });
                    }
  
                    // 최종 상태 처리
                    if (message.status === 'COMPLETED') {
                      setStatusMessage('Transcription Completed!');
                      setProgress(100);
                      ws.close(); // 완료 시 연결 종료
                    } else if (message.status === 'FAILED' || message.status === 'CHUNK_FAILED') {
                      setErrorMessage(`Error: ${message.error || 'Processing failed.'}`);
                      setStatusMessage('Processing Failed.');
                      setProgress(null);
                      ws.close(); // 실패 시 연결 종료
                    }
                } catch (error) {
                    console.error("Failed to parse WebSocket message or update state:", error);
                    setErrorMessage('Received an invalid message.');
                }
            }; // onmessage 핸들러 끝
  
            ws.onerror = (error) => {
                // onerror 이벤트 객체는 직접적인 오류 메시지를 포함하지 않을 수 있음
                // 콘솔에 찍히는 추가 정보를 확인하는 것이 중요
                console.error('WebSocket Error event:', error);
                setErrorMessage('WebSocket connection failed or encountered an error. Check console.');
                setStatusMessage('WebSocket Error.');
                setTaskId(null); // 에러 시 Task ID 초기화
            };
  
            ws.onclose = (event) => {
                console.log('WebSocket Disconnected:', event.code, event.reason);
                // state 비교 대신 명시적인 완료/실패 상태 변수 사용이 더 좋음
                // if (event.code !== 1000 && !['Transcription Completed!', 'Processing Failed.'].includes(statusMessage)) {
                //     setStatusMessage('WebSocket disconnected.');
                // }
                websocket.current = null;
            };
  
        } catch (error) {
             // new WebSocket() 자체에서 오류 발생 시 (예: 잘못된 URL 형식)
             console.error("Failed to create WebSocket:", error);
             setErrorMessage(`Failed to initialize WebSocket connection: ${error.message}`);
             setStatusMessage('WebSocket Initialization Error.');
             setTaskId(null);
        }
  
  
        // Cleanup 함수
        return () => {
            if (websocket.current) {
                console.log('Closing WebSocket connection (Cleanup)...');
                websocket.current.onclose = null; // onclose 핸들러 중복 호출 방지
                websocket.current.onerror = null; // onerror 핸들러 중복 호출 방지
                websocket.current.close();
                websocket.current = null;
            }
        };
      }
  }, [taskId]); // 의존성 배열 확인

  // 제출 핸들러
  const handleSubmit = async (urlToProcess) => {
    if (!urlToProcess || isLoading) return;
    console.log("handleSubmit called with URL:", urlToProcess);

    setIsLoading(true);
    setErrorMessage('');
    setSegments([]);
    setTaskId(null); // 이전 Task 초기화
    setProgress(null);
    setStatusMessage('Starting process...');

    try {
      setStatusMessage('Extracting audio...');
      const extractRes = await axios.post(`${EXTRACTOR_API_URL}/extract`, {
        youtube_url: urlToProcess, output_format: "wav", sample_rate: 16000, channels: 1
      });
      const filePath = extractRes.data.file_path;
      if (!filePath) throw new Error('Extractor did not return a file path.');
      console.log("Audio extracted:", filePath);

      setStatusMessage('Requesting transcription...');
      const sttRes = await axios.post(`${STT_API_URL}/request_transcription`, {
        wav_file_path: filePath, language: "ja"
      });
      if (sttRes.status !== 202 || !sttRes.data.task_id) {
         throw new Error(`STT request failed with status ${sttRes.status}`);
      }
      console.log("Transcription requested:", sttRes.data);
      setTaskId(sttRes.data.task_id); // Trigger WebSocket connection

    } catch (error) {
      console.error('Error during handleSubmit:', error);
      let message = 'An error occurred.';
      if (error.response) { message = `Error ${error.response.status}: ${error.response.data?.detail || error.message}`; }
      else if (error.request) { message = 'Network error or backend service unavailable.'; }
      else { message = `Request setup error: ${error.message}`; }
      setErrorMessage(message);
      setStatusMessage('Error occurred.');
      setTaskId(null);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="App">
      <h1>YouTube Japanese STT</h1>
      <UrlInput onSubmit={handleSubmit} isLoading={isLoading} />
      <StatusBar status={statusMessage} progress={progress} error={errorMessage} />
      <ResultsDisplay segments={segments} />
    </div>
  );
}

export default App;