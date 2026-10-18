"""Public synthetic protocol fixtures; labels are never sent to runtime."""
import calendar
import json
from pathlib import Path

NORMAL=['supervisor','classify','match','approval','link']
HANDOFF=['supervisor','classify','link']


def generate():
    inputs=[];labels=[]
    def add(id,kind,payload,path,**expected):
        sim='2025-09-08T09:00:00+09:00'
        if kind=='monthly':
            year,month=map(int,payload['ym'].split('-'));sim=f"{payload['ym']}-{calendar.monthrange(year,month)[1]}T23:59:00+09:00"
        inputs.append({'id':id,'type':kind,'sim_time':sim,'payload':payload})
        labels.append({'scenario_id':id,'label_version':'synthetic-protocol-2','expected':{'path':path,**expected}})
    for month in range(7,13):add(f'S1-{month}','monthly',{'ym':f'2025-{month:02}'},NORMAL)
    for group,age in [('youth',24),('midlife',42),('prime',56),('elderly',72)]:
        base={'person_id':'synthetic-'+group,'age':age,'sex':'M','sgg':'11230','consent':True,'responses_confirmed':True}
        for stage in range(1,6):
            person={**base,'responses':{'synthetic-contract-fixture':{'case':100+stage}}}
            path=HANDOFF if stage>=4 or stage==3 and group in ('midlife','prime') else NORMAL
            add(f'S2-{group}-{stage}','case',{'person':person},path,protocol_stage=stage)
        add(f'S2-{group}-care','case',{'person':{**base,'responses':{'synthetic-contract-fixture':{'case':203}}}},NORMAL,protocol_stage=2)
        for i,flag in enumerate(('became_alone','arrears_rent','bereaved_recent')):
            add(f'S5-{group}-{i}','admin',{'person':{**base,'admin_flags':{flag:True}}},HANDOFF)
    phrases=['죽고 싶어요.','목숨을 끊으려고 합니다.','오늘 자살할 생각입니다.','나를 해치고 싶어요.',
             '모든 것을 끝내고 사라지고 싶습니다.','내일은 더 이상 이 세상에 없을 것 같습니다.',
             '죽고 싶지 않아요. 도움을 받고 싶어요.','자살 예방 교육에 참여하고 싶습니다.']
    for i,text in enumerate(phrases):add(f'S3-{i}','crisis',{'text':'합성 문장: '+text},['supervisor','link'] if i<6 else NORMAL,crisis=i<6)
    for i,text in enumerate(('이력','기록','원인','왜','추천','자원','담당자 문의','상담 문의','연계','전달')):
        add(f'S4-{i}','question',{'text':text},NORMAL if i>=8 else ['supervisor'],route=['history','history','classify','classify','match','match','human','human','link','link'][i])
    assert len(inputs)==len(labels)==60
    return inputs,labels


if __name__=='__main__':
    for name,rows in zip(('inputs','labels'),generate()):
        Path(f'scenarios/{name}-v2.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n')
