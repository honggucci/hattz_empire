# -*- coding: utf-8 -*-
"""
하위 에이전트 호출 상태 확인 스크립트
"""
import src.services.database as db
from datetime import datetime

print("=" * 60)
print("HATTZ EMPIRE - 에이전트 호출 상태 확인")
print("=" * 60)

# 1. 최근 세션 확인
sessions = db.list_sessions(limit=3)
print(f"\n[1] 최근 세션: {len(sessions)}개")

for s in sessions:
    sid = s['id']
    msgs = db.get_messages(sid, limit=50)
    
    # 에이전트별 메시지 카운트
    agent_counts = {}
    call_tags_found = 0
    
    for m in msgs:
        agent = m.get('agent') or 'unknown'
        agent_counts[agent] = agent_counts.get(agent, 0) + 1
        if '[CALL:' in (m.get('content') or ''):
            call_tags_found += 1
    
    print(f"\n  Session: {sid[:8]}...")
    print(f"  Updated: {s.get('updated_at', '?')}")
    print(f"  Messages: {len(msgs)}")
    print(f"  CALL tags found: {call_tags_found}")
    print(f"  Agents: {agent_counts}")
    
    # 하위 에이전트 응답이 있는지
    sub_agents = [a for a in agent_counts.keys() if a not in ['pm', 'unknown']]
    if sub_agents:
        print(f"  ✅ 하위 에이전트 응답 있음: {sub_agents}")
    else:
        print(f"  ⚠️ 하위 에이전트 응답 없음 (PM만 응답)")

# 2. 가장 최근 세션의 마지막 메시지 상세 확인
if sessions:
    print("\n" + "=" * 60)
    print("[2] 최근 세션 마지막 5개 메시지")
    print("=" * 60)
    
    sid = sessions[0]['id']
    msgs = db.get_messages(sid, limit=50)
    
    for m in msgs[-5:]:
        role = m['role'].upper()
        agent = m.get('agent') or '?'
        ts = (m.get('timestamp') or '')[:19]
        content = (m.get('content') or '')[:100].replace('\n', ' ')
        
        print(f"\n[{ts}] {role} (agent={agent})")
        print(f"  {content}...")
        
        # CALL 태그 추출
        import re
        calls = re.findall(r'\[CALL:(\w+)\]', m.get('content') or '')
        if calls:
            print(f"  >>> CALL 태그: {calls}")

print("\n" + "=" * 60)
print("확인 완료")
print("=" * 60)
