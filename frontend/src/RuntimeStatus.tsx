import {useEffect,useState} from 'react';
import {api} from './api';
type Readiness={ready:boolean;data_mode:string;llm_mode:string;storage:string;warnings:string[];analysis:{status:string;geometry?:string;coverage?:{matched:number;total:number}};catalog:{status:string}};
export function RuntimeStatus(){
 const [data,setData]=useState<Readiness>(),[error,setError]=useState(''),[attempt,setAttempt]=useState(0);
 useEffect(()=>{let active=true;setError('');api<Readiness>('/readiness').then(r=>{if(active)setData(r);}).catch(e=>{if(active){setData(undefined);setError(String(e));}});return()=>{active=false;};},[attempt]);
 if(error)return <aside className="runtime-status" aria-label="서버 준비 상태"><p role="alert">자료 준비 상태를 확인하지 못했습니다. {error}</p><button onClick={()=>setAttempt(a=>a+1)}>서버 상태 다시 확인</button></aside>;
 if(!data)return <aside className="runtime-status" aria-label="서버 준비 상태"><p role="status">자료 준비 상태 확인 중…</p></aside>;
 const map=data.analysis.geometry==='administrative_boundaries'?'실제 행정동 경계':data.analysis.geometry==='synthetic_grid'?'합성 격자':'자료 미준비';
 return <aside className="runtime-status" aria-label="서버 준비 상태"><p role="status"><strong>자료: {data.data_mode==='local'?(data.analysis.status==='unavailable'?'실제 자료 모드 (입력 확인 필요)':'실제 지역 집계'):'합성 시연 자료'}</strong> · 지도: {map} · {data.llm_mode==='live'?'실제 모델 사용 설정':'정해진 테스트 응답'}</p>
 {!data.ready&&<p>분석 입력 또는 자원 목록이 준비되지 않았습니다. 아래 서버 확인 항목을 먼저 확인하세요.</p>}
 <details><summary>자료·저장소 확인 항목{data.warnings.length?` (${data.warnings.length})`:''}</summary><p>분석 자료: {data.analysis.status==='ready'?'준비됨':data.analysis.status==='incomplete_geometry'?'일부 경계 연결 누락':'입력 확인 필요'} · 자원 목록: {data.catalog.status==='ready'?'준비됨':'입력 확인 필요'}</p>{data.analysis.coverage&&<p>경계 연결 {data.analysis.coverage.matched} / {data.analysis.coverage.total}동</p>}<p>저장소: {data.storage==='temporary_instance'?'인스턴스별 임시 저장':data.storage==='configured_directory'?'별도 서버 디렉터리':'로컬 디렉터리'} · 단일 인스턴스로 운영하며 영속성은 서버 운영 설정에서 확인해야 합니다.</p><ul>{data.warnings.map(w=><li key={w}>{w}</li>)}</ul><p>운영자 확인: 실제 자료는 DATA_MODE=local과 승인된 입력 연결이 필요하며, 합성동의 이름만 실제 동으로 바꾸지 않습니다.</p></details></aside>;
}
