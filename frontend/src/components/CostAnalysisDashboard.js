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
      
      // 비용 요약 데이터 가져오기
      const [summaryRes, logsRes, alertsRes] = await Promise.all([
        axios.get(`${process.env.REACT_APP_API_GATEWAY_URL}/api/ai/cost/summary`),
        axios.get(`${process.env.REACT_APP_API_GATEWAY_URL}/api/ai/cost/logs`, {
          params: { task_id: taskId, hours: 24 }
        }),
        axios.get(`${process.env.REACT_APP_API_GATEWAY_URL}/api/ai/cost/alerts`)
      ]);

      setCostData(summaryRes.data);
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

          {/* 논문용 요약 통계 */}
          <div className="bg-gray-700 rounded-lg p-4">
            <h3 className="text-lg font-bold text-white mb-4">📝 논문 작성용 통계 요약</h3>
            
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              {/* 모델별 사용량 */}
              {costLogs.length > 0 && (
                <div>
                  <h4 className="font-medium text-gray-200 mb-2">모델별 사용 현황</h4>
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
                  <h4 className="font-medium text-gray-200 mb-2">에이전트별 사용 현황</h4>
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
            
            {/* 성능 메트릭 */}
            {costLogs.length > 0 && (
              <div className="mt-4 p-3 bg-blue-900 rounded">
                <h4 className="font-medium text-blue-200 mb-2">성능 메트릭</h4>
                <div className="grid grid-cols-3 gap-4 text-center text-sm">
                  <div>
                    <div className="text-blue-300 font-bold">
                      {Math.round(costLogs.reduce((sum, log) => sum + (log.processing_time_ms || 0), 0) / costLogs.length)}ms
                    </div>
                    <div className="text-blue-400">평균 응답시간</div>
                  </div>
                  <div>
                    <div className="text-blue-300 font-bold">
                      {Math.round(costLogs.filter(log => log.success).length / costLogs.length * 100)}%
                    </div>
                    <div className="text-blue-400">성공률</div>
                  </div>
                  <div>
                    <div className="text-blue-300 font-bold">
                      {Math.round(costLogs.reduce((sum, log) => sum + (log.total_tokens || 0), 0) / costLogs.length)}
                    </div>
                    <div className="text-blue-400">평균 토큰/호출</div>
                  </div>
                </div>
              </div>
            )}
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