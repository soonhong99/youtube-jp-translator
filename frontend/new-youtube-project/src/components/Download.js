import React from 'react';

export default function Download() {
  const exampleScript = [
    // 예시 데이터 (나중에 실제 API 연결 시 대체할 예정)
    { jp: "おはようございます。", kr: "안녕하세요." },
    { jp: "今日は東京に来ています。", kr: "오늘은 도쿄에 와 있습니다." },
    { jp: "朝ごはんは近くのカフェです。", kr: "아침밥은 근처 카페입니다." },
    { jp: "美味しそうなトーストがあります。", kr: "맛있어 보이는 토스트가 있어요." }
  ];

  const downloadScript = (language) => {
    let text = exampleScript.map(line => line[language]).join('\n');
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
        {exampleScript.map((line, index) => (
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
