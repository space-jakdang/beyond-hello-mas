export async function api<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(path, body === undefined ? undefined : {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
  if (!response.ok) throw new Error(`${response.status}: ${await response.text()}`);
  return response.json();
}
export type Run = {id: string; scenario_id: string; status: string; data_mode: string; llm_mode: string; model_version: string; started_at: string};
export type Trace = {run_id: string; seq: number; agent: string; kind: string; sim_ts: string; wall_ts: string; latency_ms: number; tokens_in: number; tokens_out: number; payload: Record<string, unknown>};
export const statusText: Record<string, string> = {running: '실행 중', awaiting_approval: '승인 대기', completed: '완료', rejected: '반려', failed: '실패'};
export const scenarios = [
  {id: 'case-pending', type: 'case', sim_time: '2025-07-01T09:00:00+09:00', payload: {text: '합성 사례: 외로워서 상담을 요청합니다.'}},
  {id: 'crisis-direct', type: 'crisis', sim_time: '2025-07-01T09:00:00+09:00', payload: {text: '합성 위기: 죽고 싶어요.'}},
  ...['07','08','09','10','11','12'].map(month => ({id: `monthly-${month}`, type: 'monthly', sim_time: `2025-${month}-01T09:00:00+09:00`, payload: {ym: `2025-${month}`}})),
  {id:'admin-synthetic',type:'admin',sim_time:'2025-07-01T09:00:00+09:00',payload:{person:{person_id:'synthetic-01',age:45,sgg:'11230',admin_flags:{became_alone:true}}}},
  {id:'case-handoff-synthetic',type:'case',sim_time:'2025-07-01T09:00:00+09:00',payload:{person:{person_id:'synthetic-02',age:24,sgg:'11230',consent:true,responses_confirmed:true,responses:{'synthetic-contract-fixture':{case:201}}}}},
  {id: 'question-history', type: 'question', sim_time: '2025-12-01T09:00:00+09:00', payload: {text: '이력을 보여 주세요.'}},
];
