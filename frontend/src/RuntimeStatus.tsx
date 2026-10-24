import {useEffect,useState} from 'react';
import {api} from './api';
import {ApiErrorNotice} from './ApiErrorNotice';
import {dataModeLabel,llmModeLabel} from './modeLabels';
type Readiness={ready:boolean;data_mode:string;llm_mode:string;storage:string;warnings:string[];analysis:{status:string;geometry?:string;coverage?:{matched:number;total:number}};catalog:{status:string}};
export function RuntimeStatus(){
 const [data,setData]=useState<Readiness>(),[error,setError]=useState(''),[attempt,setAttempt]=useState(0);
 useEffect(()=>{let active=true;setError('');api<Readiness>('/readiness').then(r=>{if(active)setData(r);}).catch(e=>{if(active){setData(undefined);setError(String(e));}});return()=>{active=false;};},[attempt]);
 if(error)return <aside className="runtime-status" aria-label="서버 준비 상태"><ApiErrorNotice message="자료 준비 상태를 확인하지 못했습니다. 연결 상태를 확인하고 다시 시도하세요." detail={error}/><button onClick={()=>setAttempt(a=>a+1)}>서버 상태 다시 확인</button></aside>;
 if(!data)return <aside className="runtime-status" aria-label="서버 준비 상태"><p role="status">자료 준비 상태 확인 중…</p></aside>;
 const dataMode=data.data_mode==='local'?({ready:'실제 지역 집계',incomplete_geometry:'실제 지역 자료 (일부 경계 누락)',unavailable:'실제 자료 모드 (입력 확인 필요)'} as Record<string,string>)[data.analysis.status]||'실제 자료 모드 (상태 확인 필요)':dataModeLabel(data.data_mode);
 const map=({administrative_boundaries:'실제 행정동 경계',synthetic_grid:'합성 격자'} as Record<string,string>)[data.analysis.geometry||'']||(data.analysis.status==='unavailable'?'자료 미준비':'자료 유형 확인 필요');
 const analysisStatus=({ready:'준비됨',incomplete_geometry:'일부 경계 연결 누락',unavailable:'입력 확인 필요'} as Record<string,string>)[data.analysis.status]||'자료 상태 확인 필요';
 const catalogStatus=({ready:'준비됨',unavailable:'입력 확인 필요'} as Record<string,string>)[data.catalog.status]||'자료 상태 확인 필요';
 const storage=({temporary_instance:'인스턴스별 임시 저장',configured_directory:'별도 서버 디렉터리',local_directory:'서버 로컬 디렉터리'} as Record<string,string>)[data.storage]||'운영 환경에서 확인 필요';
 return <aside className="runtime-status" aria-label="서버 준비 상태"><p role="status"><strong>자료: {dataMode}</strong> · 지도: {map} · {llmModeLabel(data.llm_mode)}</p>
 {!data.ready&&<p>분석 입력 또는 자원 목록이 준비되지 않았습니다. 아래 서버 확인 항목을 먼저 확인하세요.</p>}
 <details><summary>자료·저장소 확인 항목{data.warnings.length?` (${data.warnings.length})`:''}</summary><p>분석 자료: {analysisStatus} · 자원 목록: {catalogStatus}</p>{data.analysis.coverage&&<p>경계 연결 {data.analysis.coverage.matched} / {data.analysis.coverage.total}동</p>}<p>저장소: {storage} · 단일 인스턴스로 운영하며 영속성은 서버 운영 설정에서 확인해야 합니다.</p><p>기술 코드: 자료 {data.data_mode} · 모델 {data.llm_mode} · 분석 {data.analysis.status} · 자원 {data.catalog.status} · 저장소 {data.storage}</p><ul>{data.warnings.map(w=><li key={w}>{w}</li>)}</ul><p>운영자 확인: 실제 자료는 DATA_MODE=local과 승인된 입력 연결이 필요하며, 합성동의 이름만 실제 동으로 바꾸지 않습니다.</p></details></aside>;
}
