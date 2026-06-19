#!/usr/bin/env python3
"""End-to-end test: LLM -> TTS -> MuseTalk -> Video"""
import urllib.request, json, time, re, sys

BASE = 'http://localhost:8000'

def post(path, data_dict):
    body = json.dumps(data_dict).encode()
    req = urllib.request.Request(BASE + path, data=body, method='POST')
    req.add_header('Content-Type', 'application/json')
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())

def post_form(path, data_dict):
    import urllib.parse
    body = urllib.parse.urlencode(data_dict).encode()
    req = urllib.request.Request(BASE + path, data=body, method='POST')
    req.add_header('Content-Type', 'application/x-www-form-urlencoded')
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read())

def get(path):
    with urllib.request.urlopen(BASE + path, timeout=10) as r:
        return json.loads(r.read())

# Step 1: Agent LLM
print('=== Step 1: Agent LLM ===')
t0 = time.time()
resp = post('/agent/chat', {'user_id':'e2e','text':'hello','render_video':False})
t_llm = time.time() - t0
print(f'Time: {t_llm:.1f}s')
txt = resp.get('response_text','')
print(f'Response({len(txt)} chars):')
# Print safely
for ch in txt[:80]:
    try:
        print(ch, end='')
    except:
        print('?', end='')
print()

# Step 2: Render
print()
print('=== Step 2: Render (text-to-video) ===')
t1 = time.time()
resp2 = post_form('/api/v1/generate-text-only', {'text':'hello'})
task_id = resp2['task_id']
print(f'Task: {task_id}')

for i in range(50):
    time.sleep(4)
    d = get(f'/api/v1/generate/{task_id}')
    status = d['status']
    if status in ('completed','failed'):
        t_total = time.time() - t1
        print(f'Status: {status} ({t_total:.0f}s total)')
        if d.get('video_url'):
            url = BASE + d['video_url']
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=10) as vr:
                vd = vr.read()
            print(f'Video: HTTP 200, {len(vd)} bytes')
            print(f'URL: {d["video_url"]}')
        if d.get('error'):
            print(f'Error: {d["error"][:200]}')
        break
    if i % 3 == 0:
        p = d.get('progress',{})
        print(f'[{(i+1)*4}s] {p.get("audio_synthesis","")} | muse={p.get("musetalk","")}')

# Step 3: Timing
print()
print('=== Step 3: Timing Breakdown ===')
with open('/data/Her/server.log') as f:
    log = f.read()

# Get latest run timing
lines = log.split('\n')
timing_lines = [l.strip() for l in lines if '[TIMING]' in l or '[WTIMING]' in l]
# Show last 12 lines
for l in timing_lines[-12:]:
    print(f'  {l}')

# Parse numbers
timing = {}
for l in timing_lines[-12:]:
    m = re.search(r'(\w+)\((\d+)f\):\s+CACHED', l)
    if m:
        timing[m.group(1) + '_cached'] = True
    m = re.search(r'(\w+)\((\d+)f\):\s+([\d.]+)s', l)
    if m:
        timing[m.group(1)] = float(m.group(3))
        timing['frames'] = int(m.group(2))
    m = re.search(r'\[TIMING\] (\w+):\s+([\d.]+)s', l)
    if m:
        timing[m.group(1)] = float(m.group(2))

fb_count = log.count('frame_batch')

print()
print('=== Summary ===')
print(f'  LLM:              {t_llm:.1f}s')
print(f'  TTS:              {timing.get("audio_synthesis",0):.1f}s')
print(f'  MuseTalk UNet:    {timing.get("unet_gen",0):.1f}s ({timing.get("frames","?")}f)')
print(f'  MuseTalk blend:   {timing.get("blend_parse",0):.1f}s')
print(f'  MuseTalk total:   {timing.get("musetalk",0):.1f}s')
print(f'  frame_batch evts: {fb_count}')
total_render = timing.get('audio_synthesis',0) + timing.get('musetalk',0)
print(f'  Render total:     {total_render:.1f}s')
print(f'  E2E (LLM+Render): {t_llm+total_render:.1f}s')
