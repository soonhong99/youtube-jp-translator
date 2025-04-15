// import React from 'react';

// const download = (segments, lang) => {
//   const data = segments.map(s => `[${s.start}s - ${s.end}s] ${s[lang] || s.text}`).join('\n');
//   const blob = new Blob([data], { type: 'text/plain' });
//   const url = URL.createObjectURL(blob);
//   const a = document.createElement('a');
//   a.href = url;
//   a.download = `${lang}_script.txt`;
//   a.click();
// };

// const DownloadButtons = ({ segments }) => (
//   <div className="flex justify-between mt-4 px-4">
//     <button
//       onClick={() => download(segments, 'text')}
//       className="bg-blue-600 text-white px-4 py-2 rounded shadow hover:bg-blue-700"
//     >
//       일본어 자막 다운로드
//     </button>
//     <button
//       onClick={() => download(segments, 'translated')}
//       className="bg-green-600 text-white px-4 py-2 rounded shadow hover:bg-green-700"
//     >
//       한국어 자막 다운로드
//     </button>
//   </div>
// );

// export default DownloadButtons;

// components/DownloadButtons.js
import React from 'react';

const download = (segments, lang) => {
  const data = segments.map(s => `[${s.start}s - ${s.end}s] ${s[lang] || s.text}`).join('\n');
  const blob = new Blob([data], { type: 'text/plain' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `${lang}_script.txt`;
  a.click();
};

const DownloadButtons = ({ segments }) => (
  <div className="flex flex-col sm:flex-row justify-center sm:justify-between mt-4 gap-4">
    <button
      onClick={() => download(segments, 'text')}
      className="bg-blue-600 text-white px-5 py-2 rounded-md font-semibold shadow hover:bg-blue-700 transition"
    >
      🇯🇵 일본어 자막 다운로드
    </button>
    <button
      onClick={() => download(segments, 'translated')}
      className="bg-green-600 text-white px-5 py-2 rounded-md font-semibold shadow hover:bg-green-700 transition"
    >
      🇰🇷 한국어 자막 다운로드
    </button>
  </div>
);

export default DownloadButtons;
