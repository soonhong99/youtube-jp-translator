import React from 'react';

const download = (segments, lang) => {
  const data = segments
    .map(s => {
      const text = lang === 'jp' ? s.text : (s.korean_text || '');
      return `[${s.start}s - ${s.end}s] ${text}`;
    })
    .join('\n');
  const blob = new Blob([data], { type: 'text/plain' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `${lang}_script.txt`;
  a.click();
};

const DownloadButtons = ({ segments }) => (
  <div className="flex justify-between mt-4 px-4">
    <button
      onClick={() => download(segments, 'jp')}
      className="bg-blue-600 text-white px-4 py-2 rounded shadow hover:bg-blue-700"
    >
      <span className="font-bold text-sm mr-1">JP</span> 일본어 자막 다운로드
    </button>
    <button
      onClick={() => download(segments, 'ko')}
      className="bg-green-600 text-white px-4 py-2 rounded shadow hover:bg-green-700"
    >
      <span className="font-bold text-sm mr-1">KR</span> 한국어 자막 다운로드
    </button>
  </div>
);

export default DownloadButtons;
