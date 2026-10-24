export function ApiErrorNotice({message,detail}:{message:string;detail:string}){
 return <div className="card" role="alert"><p>{message}</p><details><summary>기술 오류 상세</summary><pre style={{overflowWrap:'anywhere',whiteSpace:'pre-wrap'}}>{detail}</pre></details></div>;
}
