export type Segment={ym:string;dong_cd:string;age_band:string;stage:number|null;score:number|null;missing:string[];blind_flag:boolean;change_flag:boolean;score_change:number|null;indicators:Record<string,number|null>;components:Record<string,number>};
export type Dong={dong_cd:string;dong_nm:string;sgg:string};
export type Geometry={type:'Polygon';coordinates:number[][][]}|{type:'MultiPolygon';coordinates:number[][][][]};
export type Analysis={data_mode:string;months:string[];neighborhoods:Dong[];segments:Segment[];geometry:{features:{properties:Dong;geometry:Geometry}[]};geography:{version:string;crs:string;attribution:string;source_url?:string};coverage:{matched:number;total:number;unmatched_codes:string[]};metadata:{rule_version:string;input_hash:string;normalization:string;staging:string;indicators:{name:string;direction:string;spatial_unit:string}[]}};
export const ages=['10s','20s','30s','40s','50s','60plus'];
export const ageName=(age:string)=>age==='all'?'전체 연령 (최대 단계)':age==='60plus'?'60세 이상':age.replace('s','대');
export function stageOf(rows:{stage:number|null}[]){const stages=rows.flatMap(r=>r.stage===null?[]:[r.stage]);return stages.length?Math.max(...stages):null;}
