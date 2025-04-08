// src/ResultsDisplay.js
import React from 'react';

function ResultsDisplay({ segments }) {
  return (
    <div className="results-area">
      <h2>Transcription Results</h2>
      {segments.length === 0 && <p>No results yet.</p>}
      {/* 결과를 시간 순서대로 정렬하여 표시 (선택적이지만 권장) */}
      {segments
        .slice() // 원본 배열 변경 방지
        .sort((a, b) => a.start - b.start) // 시작 시간 기준 정렬
        .map((seg, index) => (
          <p key={`<span class="math-inline">\{seg\.start\}\-</span>{index}`}> {/* key 안정성 개선 필요시 */}
            <span>
              [{seg.start?.toFixed(2)}s - {seg.end?.toFixed(2)}s]
            </span>
             {seg.text}
          </p>
      ))}
    </div>
  );
}

export default ResultsDisplay;