import json, numpy as np, sys

path = sys.argv[1] if len(sys.argv) > 1 else 'rabbit_trace.json'
with open(path) as f:
    data = json.load(f)
strokes = data['strokes']
print('Long jump check:')
max_jump = 0
for i, s in enumerate(strokes):
    pts = np.array(s['points'])
    diffs = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    mj = diffs.max()
    if mj > max_jump:
        max_jump = mj
    if mj > 30:
        idx = diffs.argmax()
        print(f'  stroke {i}: max_jump={mj:.0f}px')
print(f'Overall max jump: {max_jump:.0f}px')
total_pts = sum(len(s['points']) for s in strokes)
print(f'Strokes: {len(strokes)}, total pts: {total_pts}')
for i, s in enumerate(strokes):
    print(f'  {i}: {len(s["points"])}pts')
