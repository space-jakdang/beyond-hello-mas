from io import BytesIO
import zipfile
from uuid import uuid4
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pypdf import PdfReader
from tests.test_graph import service
from tests.test_alternative_review import sample,change
from backend.policy.alternative_review import update
from backend.policy.alternative_export import router,sections,render_pdf,render_docx


def test_pdf_docx_fixed_revision_and_no_calls(service,monkeypatch):
    body=sample(service);owner=body['owner_id'];dong=body['dong_cd']
    app=FastAPI();app.include_router(router(service.store));client=TestClient(app)
    monkeypatch.setattr(service.agents,'call',lambda *args:(_ for _ in ()).throw(AssertionError('export must not call model')))
    base=f'/policy-proposals/{owner}/{dong}/download/'
    params={'version':body['version'],'revision':0}
    pdf=client.get(base+'pdf',params=params);assert pdf.status_code==200 and pdf.content.startswith(b'%PDF')
    text='\n'.join(p.extract_text() for p in PdfReader(BytesIO(pdf.content)).pages)
    assert '검증동' in text and '기본 구상안' in text and '검토 대기' in text and '정책안 검토 승인' not in text
    approved=update(service.store,owner,dong,change(body))
    word=client.get(base+'docx',params={**params,'revision':1});assert word.status_code==200
    with zipfile.ZipFile(BytesIO(word.content)) as z:
        xml=z.read('word/document.xml').decode()
        assert '정책안 검토 승인' in xml and '검증동' in xml
        assert not any('externalLink' in name for name in z.namelist())
    assert client.get(base+'pdf',params={**params,'version':'wrong'}).status_code==409
    assert client.get(base+'pdf',params={**params,'alternative_id':str(uuid4())}).status_code==404
    assert client.get(base+'html',params=params).status_code==422


def test_long_korean_and_markup_remain_text(service,tmp_path):
    body=sample(service);a=body['alternatives'][0]
    a['operator_notes']='<img src="file:///etc/passwd"/> & <script>alert(1)</script> '+('한글 긴 문서 줄바꿈 검증 ' * 800)
    content=sections(body,a['id']);raw=render_pdf(content);reader=PdfReader(BytesIO(raw))
    assert len(reader.pages)>1
    text=''.join(page.extract_text() for page in reader.pages)
    assert '<script>alert(1)</script>' in text and '한글' in text
    assert b'/FontFile2' in raw
    docx=render_docx(content)
    with zipfile.ZipFile(BytesIO(docx)) as z:
        xml=z.read('word/document.xml').decode();assert '&lt;script&gt;' in xml
