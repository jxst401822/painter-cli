import json, numpy as np

with open('rabbit_trace.json') as f:
    data = json.load(f)
strokes = data['strokes']

print(f'Total: {len(strokes)} strokes')
for i, s in enumerate(strokes):
    pts = np.array(s['points'])
    x_min, x_max = pts[:,0].min(), pts[:,0].max()
    y_min, y_max = pts[:,1].min(), pts[:,1].max()
    crosses_axis = x_min <= 0 <= x_max
    length = sum(np.linalg.norm(np.diff(pts, axis=0), axis=1))
    ep0 = s['points'][0]
    ep1 = s['points'][-1]
    d0 = abs(ep0[0])
    d1 = abs(ep1[0])
    print(f'  {i}: {len(pts)}pts, bbox=({x_min:.0f},{y_min:.0f})-({x_max:.0f},{y_max:.0f}), len={length:.0f}px, crosses_axis={crosses_axis}, ep0_dist_axis={d0:.0f}, ep1_dist_axis={d1:.0f}')
    print(f'      ep0={ep0}, ep1={ep1}')
