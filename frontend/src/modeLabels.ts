export const dataModeLabel=(mode:string)=>({sample:'합성 시연 자료',local:'현재 서버 자료'} as Record<string,string>)[mode]||'자료 모드 확인 필요';
export const llmModeLabel=(mode:string)=>({fake:'정해진 테스트 응답',live:'실제 모델 사용 설정'} as Record<string,string>)[mode]||'모델 실행 방식 확인 필요';
