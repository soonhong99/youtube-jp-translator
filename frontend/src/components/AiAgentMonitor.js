import React from 'react';

const AiAgentMonitor = ({ aiAgents }) => {
  if (!aiAgents) return null;

  const { agents, summary, current_stage, stage_details, processing_metrics } = aiAgents;

  const getStatusColor = (status) => {
    switch (status) {
      case 'completed': return 'text-green-400 bg-green-900/20 border-green-600';
      case 'processing': return 'text-yellow-400 bg-yellow-900/20 border-yellow-600';
      case 'waiting': return 'text-gray-400 bg-gray-800/20 border-gray-600';
      default: return 'text-gray-400 bg-gray-800/20 border-gray-600';
    }
  };

  const getStatusIcon = (status) => {
    switch (status) {
      case 'completed': return '✅';
      case 'processing': return '⚡';
      case 'waiting': return '⏳';
      default: return '❓';
    }
  };

  return (
    <div className="bg-gray-800 rounded-lg p-6 mb-6">
      {/* 헤더 */}
      <div className="flex items-center justify-between mb-6">
        <h3 className="text-xl font-bold text-white flex items-center">
          🤖 AI 에이전트 모니터
          <span className="text-sm font-normal text-gray-400 ml-2">
            ({Object.keys(agents || {}).length}개 에이전트)
          </span>
        </h3>
        <div className="text-sm text-gray-400">
          {processing_metrics && processing_metrics.elapsed_time && (
            <span>경과: {Math.floor(processing_metrics.elapsed_time)}초</span>
          )}
        </div>
      </div>

      {/* 현재 진행 상황 */}
      <div className="bg-blue-900/20 border border-blue-600 rounded-lg p-4 mb-4">
        <div className="flex items-center justify-between">
          <div>
            <div className="text-blue-300 font-semibold">현재 작업</div>
            <div className="text-white">{current_stage || '준비 중...'}</div>
            {stage_details && stage_details.message && (
              <div className="text-sm text-gray-400 mt-1">{stage_details.message}</div>
            )}
          </div>
          <div className="text-right">
            {summary && summary.progress !== undefined && (
              <div className="text-2xl font-bold text-blue-300">{summary.progress}%</div>
            )}
          </div>
        </div>
      </div>

      {/* AI 에이전트 리스트 */}
      {agents && Object.keys(agents).length > 0 && (
        <div className="space-y-3 mb-4">
          {Object.entries(agents).map(([agentId, agent]) => (
            <div 
              key={agentId}
              className={`border rounded-lg p-3 transition-all duration-300 ${getStatusColor(agent.status)}`}
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center space-x-3">
                  <div className="text-2xl">{agent.icon || '🤖'}</div>
                  <div>
                    <div className="font-semibold">{agent.name}</div>
                    <div className="text-sm opacity-75">{agent.description}</div>
                  </div>
                </div>
                <div className="flex items-center space-x-2">
                  <span className="text-lg">{getStatusIcon(agent.status)}</span>
                  <div className="text-right">
                    <div className="font-bold">{agent.progress || 0}%</div>
                    <div className="text-xs uppercase">{agent.status}</div>
                  </div>
                </div>
              </div>
              
              {/* 진행률 바 */}
              {agent.status === 'processing' && agent.progress > 0 && (
                <div className="mt-2">
                  <div className="w-full bg-gray-700 rounded-full h-2">
                    <div 
                      className="bg-current h-2 rounded-full transition-all duration-500"
                      style={{ width: `${agent.progress || 0}%` }}
                    ></div>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* 실시간 통계 */}
      {summary && summary.real_time_api_usage && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-4">
          <div className="bg-purple-900/20 border border-purple-600 rounded-lg p-3 text-center">
            <div className="text-2xl font-bold text-purple-300">
              {summary.real_time_api_usage.total_calls}
            </div>
            <div className="text-sm text-purple-400">API 호출</div>
          </div>
          
          <div className="bg-green-900/20 border border-green-600 rounded-lg p-3 text-center">
            <div className="text-2xl font-bold text-green-300">
              {Math.round(summary.real_time_api_usage.total_cost_krw || 0)}원
            </div>
            <div className="text-sm text-green-400">실시간 비용</div>
          </div>

          <div className="bg-blue-900/20 border border-blue-600 rounded-lg p-3 text-center">
            <div className="text-2xl font-bold text-blue-300">
              {(summary.real_time_api_usage.total_tokens || 0).toLocaleString()}
            </div>
            <div className="text-sm text-blue-400">토큰 사용</div>
          </div>

          <div className="bg-red-900/20 border border-red-600 rounded-lg p-3 text-center">
            <div className="text-2xl font-bold text-red-300">
              {summary.real_time_api_usage.errors || 0}
            </div>
            <div className="text-sm text-red-400">오류 발생</div>
          </div>
        </div>
      )}

      {/* 작업 세부 정보 */}
      {stage_details && Object.keys(stage_details).some(key => stage_details[key]) && (
        <div className="mt-4 bg-gray-700/30 rounded-lg p-3">
          <div className="text-sm text-gray-400 mb-2">작업 세부 정보</div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
            {stage_details.segment_count > 0 && (
              <div>
                <span className="text-gray-400">세그먼트:</span>
                <span className="text-white ml-1">{stage_details.segment_count}개</span>
              </div>
            )}
            {stage_details.group_count > 0 && (
              <div>
                <span className="text-gray-400">그룹:</span>
                <span className="text-white ml-1">{stage_details.group_count}개</span>
              </div>
            )}
            {stage_details.success_count > 0 && (
              <div>
                <span className="text-gray-400">완료:</span>
                <span className="text-white ml-1">{stage_details.success_count}개</span>
              </div>
            )}
            {stage_details.estimated_cost > 0 && (
              <div>
                <span className="text-gray-400">예상 비용:</span>
                <span className="text-white ml-1">₩{Math.round(stage_details.estimated_cost)}</span>
              </div>
            )}
          </div>
          
          {stage_details.quota_exceeded && (
            <div className="mt-2 text-red-400 text-sm font-semibold">
              ⚠️ API 할당량이 초과되었습니다
            </div>
          )}
        </div>
      )}

      {/* 모델별 API 사용량 */}
      {summary && summary.real_time_api_usage && summary.real_time_api_usage.calls_by_model && Object.keys(summary.real_time_api_usage.calls_by_model).length > 0 && (
        <div className="mt-4">
          <div className="text-sm text-gray-400 mb-2">모델별 API 사용량</div>
          <div className="flex flex-wrap gap-2">
            {Object.entries(summary.real_time_api_usage.calls_by_model).map(([model, stats]) => (
              <span key={model} className="bg-gray-700 px-2 py-1 rounded text-xs">
                {model}: {stats.calls}회
                {stats.cost_krw && ` (₩${Math.round(stats.cost_krw)})`}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

export default AiAgentMonitor;