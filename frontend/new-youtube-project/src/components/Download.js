import React, { useEffect, useState } from 'react';
import axios from 'axios';


export default function Download() {
  const [script, setScript] = useState([]);

  useEffect(() => {
    // 백엔드에서 스크립트 불러오기
    axios.get('http://localhost:5000/api/full-script')  // <- URL은 실제 API 경로에 맞게!
      .then(response => {
        setScript(response.data);
      })
      .catch(error => {
        console.error('스크립트 불러오기 실패:', error);
      });
  }, []);

  const downloadScript = (language) => {
    let text = script.map(line => line[language]).join('\n');
    const blob = new Blob([text], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = language === 'jp' ? 'script_japanese.txt' : 'script_korean.txt';
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div style={{ padding: '20px', fontFamily: 'sans-serif' }}>
      <h2>📥 스크립트 다운로드</h2>
      <button style={styles.button} onClick={() => downloadScript('jp')}>
        🇯🇵 일본어 스크립트 다운로드
      </button>
      <button style={styles.button} onClick={() => downloadScript('kr')}>
        🇰🇷 한국어 스크립트 다운로드
      </button>

      <div style={{ marginTop: '30px' }}>
        <h3>전체 스크립트 보기:</h3>
        {script.map((line, index) => (
          <div key={index} style={styles.line}>
            <p><strong>🇯🇵:</strong> {line.jp}</p>
            <p><strong>🇰🇷:</strong> {line.kr}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

const styles = {
  button: {
    padding: '10px 15px',
    marginRight: '10px',
    backgroundColor: '#007bff',
    color: 'white',
    border: 'none',
    borderRadius: '5px',
    cursor: 'pointer'
  },
  line: {
    borderBottom: '1px solid #ccc',
    padding: '5px 0'
  }
};
