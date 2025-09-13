import React, { useEffect, useState } from 'react';
import axios from 'axios';

const CostAnalysisDashboard = ({ taskId, onClose }) => {
  const [costData, setCostData] = useState(null);
  const [costLogs, setCostLogs] = useState([]);
  const [alerts, setAlerts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetchCostData();
  }, [taskId]);

  const fetchCostData = async () => {
    try {
      setLoading(true);
      
      // 확장된 비용 분석 데이터 가져오기
      const [summaryRes, logsRes, alertsRes, agentPerfRes, modeCompRes, researchRes] = await Promise.all([
        axios.get(`${process.env.REACT_APP_API_GATEWAY_URL}/api/ai/cost/summary`),
        axios.get(`${process.env.REACT_APP_API_GATEWAY_URL}/api/ai/cost/logs`, {
          params: { task_id: taskId, hours: 24 }
        }),
        axios.get(`${process.env.REACT_APP_API_GATEWAY_URL}/api/ai/cost/alerts`),
        axios.get(`${process.env.REACT_APP_API_GATEWAY_URL}/api/ai/cost/agent-performance`),
        axios.get(`${process.env.REACT_APP_API_GATEWAY_URL}/api/ai/cost/mode-comparison`),
        axios.get(`${process.env.REACT_APP_API_GATEWAY_URL}/api/ai/cost/research-stats`)
      ]);

      setCostData({
        ...summaryRes.data,
        agentPerformance: agentPerfRes.data,
        modeComparison: modeCompRes.data,
        researchStats: researchRes.data
      });
      setCostLogs(logsRes.data.logs || []);
      setAlerts(alertsRes.data.alerts || []);
      
    } catch (err) {
      console.error('Failed to fetch cost data:', err);
      setError(err.response?.data?.detail || err.message);
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
        <div className="bg-gray-800 rounded-lg p-6 max-w-md w-full mx-4">
          <div className="text-center">
            <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-500 mx-auto mb-4"></div>
            <p className="text-white">비용 데이터 로딩 중...</p>
          </div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
        <div className="bg-gray-800 rounded-lg p-6 max-w-md w-full mx-4">
          <div className="text-center">
            <div className="text-red-500 text-4xl mb-4">⚠️</div>
            <p className="text-white mb-4">비용 데이터 로드 실패</p>
            <p className="text-red-300 text-sm mb-4">{error}</p>
            <div className="flex space-x-4">
              <button 
                onClick={fetchCostData}
                className="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded"
              >
                다시 시도
              </button>
              <button 
                onClick={onClose}
                className="bg-gray-600 hover:bg-gray-700 text-white px-4 py-2 rounded"
              >
                닫기
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  }

  const currentStatus = costData?.summary || {};
  const todayKRW = (currentStatus.today_cost || 0) * 1350;
  const totalKRW = (currentStatus.total_cost || 0) * 1350;

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className="bg-gray-800 rounded-lg max-w-6xl w-full max-h-[90vh] overflow-y-auto mx-4">
        {/* 헤더 */}
        <div className="flex items-center justify-between p-6 border-b border-gray-700">
          <h2 className="text-2xl font-bold text-white">📊 Gemini API 비용 분석 대시보드</h2>
          <button 
            onClick={onClose}
            className="text-gray-400 hover:text-white text-2xl"
          >
            ✕
          </button>
        </div>

        <div className="p-6 space-y-6">
          {/* 알림 섹션 */}
          {alerts.length > 0 && (
            <div className="bg-red-900 rounded-lg p-4">
              <h3 className="text-lg font-bold text-red-300 mb-3">🚨 비용 알림</h3>
              <div className="space-y-2">
                {alerts.map((alert, index) => (
                  <div 
                    key={index}
                    className={`p-3 rounded ${
                      alert.severity === 'CRITICAL' 
                        ? 'bg-red-800 text-red-200' 
                        : 'bg-yellow-800 text-yellow-200'
                    }`}
                  >
                    <div className="font-medium">{alert.type}</div>
                    <div className="text-sm">{alert.message}</div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* 비용 요약 카드 */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div className="bg-blue-800 rounded-lg p-4 text-center">
              <div className="text-3xl font-bold text-blue-200">
                {currentStatus.total_calls || 0}
              </div>
              <div className="text-blue-300 text-sm">총 API 호출</div>
            </div>
            
            <div className="bg-green-800 rounded-lg p-4 text-center">
              <div className="text-3xl font-bold text-green-200">
                ₩{Math.round(totalKRW)}
              </div>
              <div className="text-green-300 text-sm">총 누적 비용</div>
            </div>
            
            <div className="bg-yellow-800 rounded-lg p-4 text-center">
              <div className="text-3xl font-bold text-yellow-200">
                ₩{Math.round(todayKRW)}
              </div>
              <div className="text-yellow-300 text-sm">오늘 비용</div>
            </div>
            
            <div className="bg-purple-800 rounded-lg p-4 text-center">
              <div className="text-3xl font-bold text-purple-200">
                {currentStatus.today_calls || 0}
              </div>
              <div className="text-purple-300 text-sm">오늘 호출 수</div>
            </div>
          </div>

          {/* 시간별 비용 */}
          {costData?.period && (
            <div className="bg-gray-700 rounded-lg p-4">
              <h3 className="text-lg font-bold text-white mb-3">⏰ 시간별 사용량</h3>
              <div className="grid grid-cols-3 gap-4 text-center">
                <div>
                  <div className="text-2xl font-bold text-orange-300">
                    ₩{Math.round((currentStatus.current_hour_cost || 0) * 1350)}
                  </div>
                  <div className="text-gray-300 text-sm">현재 시간</div>
                  <div className="text-xs text-gray-400">{costData.period.current_hour}</div>
                </div>
                <div>
                  <div className="text-2xl font-bold text-blue-300">
                    {currentStatus.current_hour_calls || 0}
                  </div>
                  <div className="text-gray-300 text-sm">시간당 호출</div>
                </div>
                <div>
                  <div className="text-2xl font-bold text-green-300">
                    {currentStatus.today_calls > 0 
                      ? Math.round(todayKRW / currentStatus.today_calls) 
                      : 0}원
                  </div>
                  <div className="text-gray-300 text-sm">호출당 평균 비용</div>
                </div>
              </div>
            </div>
          )}

          {/* 상세 API 호출 로그 */}
          {costLogs.length > 0 && (
            <div className="bg-gray-700 rounded-lg p-4">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-lg font-bold text-white">📋 API 호출 로그 (최근 24시간)</h3>
                <span className="text-sm text-gray-300">{costLogs.length}건</span>
              </div>
              
              <div className="max-h-96 overflow-y-auto">
                <div className="space-y-2">
                  {costLogs.slice(0, 20).map((log, index) => (
                    <div 
                      key={index} 
                      className={`p-3 rounded-lg ${
                        log.success ? 'bg-gray-600' : 'bg-red-900'
                      }`}
                    >
                      <div className="flex items-center justify-between">
                        <div className="flex items-center space-x-3">
                          <span className={`text-lg ${
                            log.success ? '✅' : '❌'
                          }`}>
                            {log.success ? '✅' : '❌'}
                          </span>
                          <div>
                            <div className="font-medium text-white">
                              {log.agent_name} - {log.function_name}
                            </div>
                            <div className="text-xs text-gray-300">
                              {log.model_name} | {new Date(log.timestamp).toLocaleString()}
                            </div>
                          </div>
                        </div>
                        
                        <div className="text-right">
                          <div className="text-white font-medium">
                            ₩{Math.round(log.estimated_cost_krw || 0)}
                          </div>
                          <div className="text-xs text-gray-300">
                            {log.total_tokens} 토큰
                          </div>
                          <div className="text-xs text-gray-400">
                            {Math.round(log.processing_time_ms)}ms
                          </div>
                        </div>
                      </div>
                      
                      {log.error_message && (
                        <div className="mt-2 text-red-300 text-sm bg-red-800 p-2 rounded">
                          오류: {log.error_message}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* 새로운 AI Agent 성능 분석 섹션 */}
          {costData?.agentPerformance && (
            <div className="bg-gray-700 rounded-lg p-4">
              <h3 className="text-lg font-bold text-white mb-4">🤖 AI Agent 성능 분석</h3>
              
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {Object.entries(costData.agentPerformance.agent_performance || {}).map(([agentName, perf]) => (
                  <div key={agentName} className="bg-gray-600 rounded-lg p-4">
                    <div className="flex items-center justify-between mb-2">
                      <h4 className="font-bold text-white">{agentName}</h4>
                      <span className={`px-2 py-1 rounded text-xs ${
                        perf.success_rate >= 0.95 ? 'bg-green-600 text-green-200' :
                        perf.success_rate >= 0.8 ? 'bg-yellow-600 text-yellow-200' :
                        'bg-red-600 text-red-200'
                      }`}>
                        {Math.round((perf.success_rate || 0) * 100)}% 성공률
                      </span>
                    </div>
                    
                    <div className="space-y-2 text-sm">
                      <div className="flex justify-between">
                        <span className="text-gray-300">총 호출:</span>
                        <span className="text-white">{perf.total_calls}</span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-gray-300">평균 비용:</span>
                        <span className="text-white">₩{Math.round(perf.avg_cost_per_call_krw || 0)}</span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-gray-300">평균 토큰:</span>
                        <span className="text-white">{Math.round(perf.avg_tokens_per_call || 0)}</span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-gray-300">평균 응답시간:</span>
                        <span className="text-white">{Math.round(perf.avg_processing_time_per_call_ms || 0)}ms</span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-gray-300">토큰당 비용:</span>
                        <span className="text-white">₩{(perf.cost_per_token_krw || 0).toFixed(4)}</span>
                      </div>
                    </div>
                    
                    {/* Function별 세부 정보 */}
                    {perf.functions && Object.keys(perf.functions).length > 0 && (
                      <div className="mt-3 pt-3 border-t border-gray-500">
                        <div className="text-xs text-gray-400 mb-2">Function별 통계:</div>
                        <div className="space-y-1">
                          {Object.entries(perf.functions).map(([funcName, funcStats]) => (
                            <div key={funcName} className="text-xs text-gray-300">
                              <span className="font-medium">{funcName}:</span> {funcStats.calls}회
                              {funcStats.avg_cost_krw > 0 && (
                                <span className="text-gray-400"> (₩{Math.round(funcStats.avg_cost_krw)})</span>
                              )}
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* 번역 모드별 비교 분석 */}
          {costData?.modeComparison && (
            <div className="bg-gray-700 rounded-lg p-4">
              <h3 className="text-lg font-bold text-white mb-4">🚀 번역 모드별 성능 비교</h3>
              
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                {Object.entries(costData.modeComparison.mode_comparison || {}).map(([mode, data]) => (
                  <div key={mode} className="bg-gradient-to-br from-gray-600 to-gray-700 rounded-lg p-4">
                    <div className="flex items-center justify-between mb-3">
                      <h4 className="font-bold text-white capitalize">{mode} Mode</h4>
                      <div className="text-xs px-2 py-1 bg-blue-600 text-blue-200 rounded">
                        {data.tasks} 작업
                      </div>
                    </div>
                    
                    {data.tasks > 0 ? (
                      <div className="space-y-2 text-sm">
                        <div className="flex justify-between">
                          <span className="text-gray-300">작업당 평균 비용:</span>
                          <span className="text-green-300 font-bold">₩{Math.round(data.avg_cost_per_task_krw || 0)}</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-gray-300">작업당 평균 토큰:</span>
                          <span className="text-white">{Math.round(data.avg_tokens_per_task || 0)}</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-gray-300">평균 처리시간:</span>
                          <span className="text-white">{Math.round(data.avg_processing_time_per_task_ms / 1000 || 0)}초</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-gray-300">평균 Agent 사용:</span>
                          <span className="text-blue-300">{data.avg_agents_used?.toFixed(1) || 0}개</span>
                        </div>
                        
                        {/* Agent 사용 분포 */}
                        {data.agents_breakdown && Object.keys(data.agents_breakdown).length > 0 && (
                          <div className="mt-3 pt-2 border-t border-gray-500">
                            <div className="text-xs text-gray-400 mb-1">사용된 Agent:</div>
                            <div className="flex flex-wrap gap-1">
                              {Object.keys(data.agents_breakdown).map((agent) => (
                                <span key={agent} className="text-xs px-2 py-1 bg-gray-800 text-gray-300 rounded">
                                  {agent.replace('Agent', '')}
                                </span>
                              ))}
                            </div>
                          </div>
                        )}
                      </div>
                    ) : (
                      <div className="text-gray-400 text-sm text-center py-4">
                        데이터 없음
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* 논문 작성용 연구 통계 */}
          {costData?.researchStats && (
            <div className="bg-gradient-to-br from-purple-900 to-blue-900 rounded-lg p-4">
              <h3 className="text-lg font-bold text-white mb-4">📊 논문 작성용 연구 통계</h3>
              
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
                <div className="text-center">
                  <div className="text-2xl font-bold text-purple-200">{costData.researchStats.total_api_calls}</div>
                  <div className="text-sm text-purple-300">총 API 호출</div>
                </div>
                <div className="text-center">
                  <div className="text-2xl font-bold text-blue-200">{costData.researchStats.unique_tasks}</div>
                  <div className="text-sm text-blue-300">처리된 작업</div>
                </div>
                <div className="text-center">
                  <div className="text-2xl font-bold text-green-200">
                    ₩{Math.round(costData.researchStats.total_cost_krw || 0)}
                  </div>
                  <div className="text-sm text-green-300">총 비용</div>
                </div>
                <div className="text-center">
                  <div className="text-2xl font-bold text-yellow-200">
                    {Math.round((costData.researchStats.success_rate || 0) * 100)}%
                  </div>
                  <div className="text-sm text-yellow-300">성공률</div>
                </div>
              </div>
              
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {/* 모델 효율성 */}
                <div className="bg-black bg-opacity-30 rounded-lg p-4">
                  <h4 className="font-medium text-white mb-3">모델 효율성</h4>
                  <div className="space-y-2">
                    {Object.entries(costData.researchStats.model_usage || {}).map(([model, stats]) => (
                      <div key={model} className="flex justify-between items-center">
                        <span className="text-sm text-gray-300">{model}:</span>
                        <div className="text-right">
                          <div className="text-white text-sm">{stats.calls}회</div>
                          <div className="text-xs text-gray-400">₩{(stats.cost_per_token_krw || 0).toFixed(4)}/토큰</div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
                
                {/* Agent 활용률 */}
                <div className="bg-black bg-opacity-30 rounded-lg p-4">
                  <h4 className="font-medium text-white mb-3">시스템 효율성</h4>
                  <div className="space-y-3">
                    <div className="flex justify-between">
                      <span className="text-gray-300">평균 응답시간:</span>
                      <span className="text-white">{Math.round(costData.researchStats.average_response_time_ms || 0)}ms</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-gray-300">성공 번역당 비용:</span>
                      <span className="text-white">₩{Math.round(costData.researchStats.cost_per_successful_translation || 0)}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-gray-300">원화당 토큰:</span>
                      <span className="text-white">{Math.round(costData.researchStats.tokens_per_krw || 0)}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-gray-300">Agent 활용률:</span>
                      <span className="text-white">
                        {Math.round(costData.researchStats.agent_utilization_rate?.utilization_percentage || 0)}%
                      </span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* 기존 논문용 요약 통계는 유지하되 축소 */}
          <div className="bg-gray-700 rounded-lg p-4">
            <h3 className="text-lg font-bold text-white mb-4">📝 실시간 호출 로그 분석</h3>
            
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              {/* 모델별 사용량 */}
              {costLogs.length > 0 && (
                <div>
                  <h4 className="font-medium text-gray-200 mb-2">모델별 사용 현황 (최근 24시간)</h4>
                  <div className="space-y-2">
                    {Object.entries(
                      costLogs.reduce((acc, log) => {
                        const model = log.model_name;
                        if (!acc[model]) {
                          acc[model] = { calls: 0, tokens: 0, cost: 0 };
                        }
                        acc[model].calls += 1;
                        acc[model].tokens += log.total_tokens;
                        acc[model].cost += log.estimated_cost_krw || 0;
                        return acc;
                      }, {})
                    ).map(([model, stats]) => (
                      <div key={model} className="bg-gray-600 p-2 rounded">
                        <div className="text-sm text-white font-medium">{model}</div>
                        <div className="text-xs text-gray-300">
                          {stats.calls}회 호출, {stats.tokens.toLocaleString()}토큰, ₩{Math.round(stats.cost)}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              
              {/* 에이전트별 사용량 */}
              {costLogs.length > 0 && (
                <div>
                  <h4 className="font-medium text-gray-200 mb-2">에이전트별 사용 현황 (최근 24시간)</h4>
                  <div className="space-y-2">
                    {Object.entries(
                      costLogs.reduce((acc, log) => {
                        const agent = log.agent_name;
                        if (!acc[agent]) {
                          acc[agent] = { calls: 0, tokens: 0, cost: 0 };
                        }
                        acc[agent].calls += 1;
                        acc[agent].tokens += log.total_tokens;
                        acc[agent].cost += log.estimated_cost_krw || 0;
                        return acc;
                      }, {})
                    ).map(([agent, stats]) => (
                      <div key={agent} className="bg-gray-600 p-2 rounded">
                        <div className="text-sm text-white font-medium">{agent}</div>
                        <div className="text-xs text-gray-300">
                          {stats.calls}회 호출, {stats.tokens.toLocaleString()}토큰, ₩{Math.round(stats.cost)}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* 푸터 */}
        <div className="flex items-center justify-between p-6 border-t border-gray-700">
          <div className="text-sm text-gray-400">
            마지막 업데이트: {costData?.last_updated ? new Date(costData.last_updated).toLocaleString() : '-'}
          </div>
          <div className="flex space-x-3">
            <button 
              onClick={fetchCostData}
              className="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded text-sm"
            >
              새로고침
            </button>
            <button 
              onClick={onClose}
              className="bg-gray-600 hover:bg-gray-700 text-white px-4 py-2 rounded text-sm"
            >
              닫기
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default CostAnalysisDashboard;