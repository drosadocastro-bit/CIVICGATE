"""Disposable source clone; production gate never changed. No network or real keys."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HELPER = r"""
import json,socket
import httpx
KEY='FAKE_E2E71_CANARY_NOT_REAL'
FAULT='none'
def install():
    from civicgate import windows_dpapi
    class FakeStore:
        def __init__(self,path):pass
        def get_secret(self,name):
            assert name in ('CIVICGATE_NVIDIA_API_KEY','CIVICGATE_OPENAI_JUDGE_API_KEY')
            return KEY
    windows_dpapi.WindowsDPAPIStore=FakeStore
    def handler(request):
        from chat_v3 import util71 as p,fixtures
        from chat_v3.public_read_v11.contract import expected_proposal
        from demo_models_v1.fixtures import judge_fixture
        if request.url.host=='api.usaspending.gov':
            if FAULT=='public_partial_page':return httpx.Response(200,json={'results':[],'page_metadata':{'hasNext':False}})
            return httpx.Response(200,json={'spending_level':'awards','limit':5,'results':[
                {'internal_id':i,'generated_internal_id':f'CONT_AWD_E2E71_{i}','Award ID':f'E2E71_{i}',
                 'Recipient Name':f'CONTRACTOR {i}','Award Amount':str(600000-i*10000),'Awarding Agency':'Department of Defense'} for i in range(1,6)],
                 'page_metadata':{'page':1,'hasNext':True}})
        payload=json.loads(request.content)
        if request.url.host=='api.openai.com':return judge_fixture('none').handle_request(request)
        assert request.url.host=='integrate.api.nvidia.com'
        if payload.get('tools'):
            if FAULT=='planner_timeout':raise httpx.ReadTimeout('fixture timeout')
            return fixtures.planner_response('nemotron',p.QUESTION,expected_proposal(p.QUESTION).model_dump(mode='json')).handle_request(request)
        wire=json.loads(payload['messages'][1]['content'])
        envelope=fixture_envelope({'question':p.QUESTION,'records':wire['record_facts']})
        envelope['choices'][0]['message']['content']=envelope['choices'][0]['message']['content'].replace('historical page','fresh same-turn page')
        return httpx.Response(200,json=envelope)
    httpx.AsyncHTTPTransport=lambda **kwargs:httpx.MockTransport(handler)
    def forbidden(*a,**k):raise AssertionError('NO_EXTERNAL_DNS')
    socket.getaddrinfo=forbidden
"""
HELPER += (Path(__file__).parent / "wire_fixtures71.py").read_text()
DRIVER = r"""
import asyncio,json,sys,time
from pathlib import Path
candidate=Path(sys.argv[1]);work=Path(sys.argv[2]);sys.path.insert(0,str(candidate))
from bootstrap_v3 import initialize
initialize(offline=False)
import test_transport71
test_transport71.install()
from chat_v3 import util71 as p,common,fresh_host71 as host,host_runtime71 as runtime
from chat_v3.transport_profile_v1 import ChatProfile
work.mkdir();root=work/'run';registry=work/'registry';registry.mkdir()
(registry/'registry.json').write_bytes(p.canonical({'schema':'HOST71_REAL_CHAIN_REGISTRY_V1'}))
profile=ChatProfile.model_validate({'experiment':'CHAT03_HOST71_TEST_ONLY','planner':'nemotron','custody_root':str(root/'read'),
 'planner_attempt_limit':1,'judge_attempt_limit':1,'observation_limit':1,'backend':'USASPENDING_FIXED_READ_V11',
 'public_api_attempt_limit':1,'smoke_read_only':True,'allowed_request_sha256':p.sha(p.QUESTION.encode()),
 'source_inventory_sha256':p.sha(p.read(candidate/'chat-source-inventory-v1.json')),
 'catalog_sha256':p.sha(p.read(candidate/'guided-catalog-v1.json'))})
now=time.time();anchor=work/'test-read-anchor.json';chain=work/'test-chain-anchor.json'
anchor.write_bytes(p.canonical({'decision':'HUMAN_APPROVED_CHAT03_LIVE','profile_sha256':profile.digest,
 'source_inventory_sha256':profile.source_inventory_sha256,'experiment':profile.experiment,'expires_unix':now+300,
 'provider_account_access_verified':True,'cloud_billing_risk_explicitly_accepted':True,'runtime_identity_checked':True}))
chain.write_bytes(p.canonical({'decision':'HUMAN_APPROVED_HOST71_FRESH_CHAIN','profile_sha256':profile.digest,
 'source_inventory_sha256':profile.source_inventory_sha256,'question':p.QUESTION,'counts':runtime.COUNTS,'limits':runtime.LIMITS,
 'issued_at':now,'expires_at':now+300,'nvidia_free_only':True,'judge_max_usd':'0.05','billing_risk_accepted':True,'no_retry_no_fallback':True}))
result=asyncio.run(host.execute_host(root,profile,anchor,chain,work/'NO_REAL_SECRET_STORE',registry))
(work/'test-result.json').write_bytes(p.canonical({'test_only':True,'actual_external_requests':0,'result':result}))
print(result.get('state'))
if sys.argv[3]=='none':
    assert result['state']=='HOST71_REVIEW_REQUIRED', result
    assert result['stage_counts']==runtime.COUNTS
    assert host.read_host(root)['state']=='HOST71_REVIEW_REQUIRED'
    terminal=root/'host-terminal.json';saved=terminal.read_bytes();changed=p.parse(saved)
    changed['read_proof']['observation']='OTHER_TURN';terminal.write_bytes(p.canonical(changed))
    assert host.read_host(root)['state']=='UNKNOWN_CONSUMED'
    terminal.write_bytes(saved)
    for field,value in [('release_allowed',True),('publication_allowed',True),('verified_answer',True),('write_allowed',True),('stage_counts',{'planner':2}),('stage_counts',{'planner':True,'judge':True,'public_read':True,'answer':True}),('source_inventory_sha256','0'*64)]:
        changed=p.parse(saved);changed[field]=value;terminal.write_bytes(p.canonical(changed))
        assert host.read_host(root)['state']=='UNKNOWN_CONSUMED'
    terminal.write_bytes(saved)
    unknown=root/'host-unknown.json';unknown.write_bytes(b'{}')
    assert host.read_host(root)['state']=='UNKNOWN_CONSUMED'
    unknown.unlink()
    source=candidate/'chat_v3/capture_binding71.py';original=source.read_bytes();source.write_bytes(original+b'\n# changed')
    assert host.read_host(root)['state']=='UNKNOWN_CONSUMED'
    source.write_bytes(original)
    assert host.read_host(root)['state']=='HOST71_REVIEW_REQUIRED'
    from chat_v3 import host_final71
    response=root/'answer/response.bin';response_saved=response.read_bytes();response.write_bytes(b'{}')
    changed=p.parse(saved)
    changed['answer']=host_final71.read_run(root/'answer',changed['read_proof']['payload'],changed['read_proof'])
    terminal.write_bytes(p.canonical(changed))
    assert host.read_host(root)['state']=='UNKNOWN_CONSUMED'
    terminal.write_bytes(saved);response.write_bytes(response_saved)
    fence=registry/(p.sha(p.QUESTION.encode())+'.consumed.json');fence_saved=fence.read_bytes()
    fence.write_bytes(b'{}');assert host.read_host(root)['state']=='UNKNOWN_CONSUMED';fence.write_bytes(fence_saved)
    assert host.read_host(root)['state']=='HOST71_REVIEW_REQUIRED'
    anchor_saved=chain.read_bytes();chain.write_bytes(b'{}');assert host.read_host(root)['state']=='UNKNOWN_CONSUMED';chain.write_bytes(anchor_saved)
    before={str(f):p.sha(f.read_bytes()) for f in work.rglob('*') if f.is_file()}
    assert host.read_host(root)['state']=='HOST71_REVIEW_REQUIRED'
    assert before=={str(f):p.sha(f.read_bytes()) for f in work.rglob('*') if f.is_file()}
else:
    assert result['state']=='UNKNOWN_CONSUMED',result
    assert not (root/'answer').exists()
    assert (registry/(p.sha(p.QUESTION.encode())+'.consumed.json')).exists()
    try:
        asyncio.run(host.execute_host(root,profile,anchor,chain,work/'NO_REAL_SECRET_STORE',registry))
        raise AssertionError('RETRY_NOT_REJECTED')
    except ValueError:pass
"""


@pytest.mark.parametrize("fault", ["none", "planner_timeout", "public_partial_page"])
def test_disposable_real_branch_full_chain(tmp_path, fault):
    src = Path(__file__).resolve().parents[1]
    candidate = tmp_path / "release/host71"
    shutil.copytree(src, candidate, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    gate = candidate / "chat_v3/host_gate71.py"
    gate.write_text(gate.read_text().replace("return False", "return True"))
    (candidate / "test_transport71.py").write_text(
        HELPER.replace("FAULT='none'", "FAULT=" + repr(fault))
    )
    entry = candidate / "entry_host71.py"
    entry.write_text(
        entry.read_text().replace(
            "initialize(offline=False)",
            "initialize(offline=False)\n    import test_transport71\n    test_transport71.install()",
        )
    )
    import hashlib

    files = {
        str(f.relative_to(candidate)).replace("\\", "/"): {
            "sha256": hashlib.sha256(f.read_bytes()).hexdigest(),
            "bytes": f.stat().st_size,
        }
        for f in candidate.rglob("*")
        if f.is_file() and f.name != "chat-source-inventory-v1.json"
    }
    (candidate / "chat-source-inventory-v1.json").write_text(
        json.dumps({"version": "HOST71_TEST_ONLY", "files": files})
    )
    driver = tmp_path / "driver.py"
    driver.write_text(DRIVER)
    done = subprocess.run(
        [sys.executable, "-B", str(driver), str(candidate), str(tmp_path / "work"), fault],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert done.returncode == 0, done.stdout + "\n" + done.stderr
    assert (
        json.loads((tmp_path / "work/test-result.json").read_bytes())["actual_external_requests"]
        == 0
    )
