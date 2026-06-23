"""
Strict image-to-trajectory pipeline for sugar painting (High Fidelity Edition).
Optimized for precise pixel tracking on skeleton images.
"""
import argparse
import json
import sys
import numpy as np
from PIL import Image

try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False

MODE_DEFAULTS = {
    "lineart": {
        "sigma": 0.0, "eps": 0.0, "max_dim": 400,  # 默认关闭平滑与简化以保证绝对保真
        "resample": 0, "threshold": None,          # resample=0 表示保留原始像素点
    },
    "photo": {
        "sigma": 4.0, "eps": 1.5, "max_dim": 300,
        "resample": 120, "threshold": None,
    },
}

COLORS = [
    "#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4",
    "#42d4f4", "#f032e6", "#bfef45", "#fabed4", "#469990",
    "#dcbeff", "#9A6324", "#800000", "#aaffc3", "#808000",
]

# ─── Image Loading ──────────────────────────────────────────────────────────

def load_and_resize(image_path, max_dim):
    img = Image.open(image_path).convert("L")
    ow, oh = img.size
    ratio = max_dim / max(ow, oh)
    nw, nh = int(ow * ratio), int(oh * ratio)
    img = img.resize((nw, nh), Image.LANCZOS)
    arr = np.array(img)
    print(f"Image: {ow}x{oh} → {nw}x{nh}")
    return arr, (ow, oh)

# ─── Binarization ──────────────────────────────────────────────────────────

def binarize_lineart(gray_arr, threshold=None):
    img = gray_arr.copy()
    if HAS_CV2:
        if threshold is not None:
            _, binary = cv2.threshold(img, threshold, 255, cv2.THRESH_BINARY)
        else:
            # 如果输入已经是黑底白字或黑底绿字，自适应判定
            if np.mean(img) > 127:
                _, binary = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
            else:
                _, binary = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    else:
        if threshold is None: threshold = 50
        binary = ((img > threshold) * 255).astype(np.uint8)
    
    result = (binary > 0).astype(np.uint8)
    print(f"  Line pixels: {np.count_nonzero(result)}")
    return result

# ─── Skeletonization (Keep existing or pass-through if already skeleton) ───

def skeletonize(binary):
    # 如果输入的已经是单像素骨架（如debug图），此处可作为无损传递
    img = binary.copy().astype(np.uint8)
    img[img > 0] = 1
    h, w = img.shape
    while True:
        changed = False
        for pn in range(2):
            p2=img[0:h-2,1:w-1]; p3=img[0:h-2,2:w]; p4=img[1:h-1,2:w]
            p5=img[2:h,2:w]; p6=img[2:h,1:w-1]; p7=img[2:h,0:w-2]
            p8=img[1:h-1,0:w-2]; p9=img[0:h-2,0:w-2]
            c = img[1:h-1,1:w-1]
            fg = c == 1
            ns = p2+p3+p4+p5+p6+p7+p8+p9
            cs = (ns>=2)&(ns<=6)
            a = np.stack([p2,p3,p4,p5,p6,p7,p8,p9,p2],axis=0)
            tr = np.sum((a[:-1]==0)&(a[1:]==1),axis=0)==1
            if pn==0:
                ca = (p2*p4*p6)==0; cb = (p4*p6*p8)==0
            else:
                ca = (p2*p4*p8)==0; cb = (p2*p6*p8)==0
            mask = fg & cs & tr & ca & cb
            if np.any(mask):
                r = np.zeros_like(img); r[1:h-1,1:w-1] = mask
                img[r==1] = 0; changed = True
        if not changed: break
    return img

def prune_skeleton(skel, max_spur=10):
    if max_spur <= 0: return skel
    img = skel.copy()
    h, w = img.shape
    for _ in range(max_spur):
        ys, xs = np.where(img > 0)
        if len(xs) == 0: break
        fg = img > 0
        n = np.zeros_like(img, dtype=np.int32)
        for dy in [-1,0,1]:
            for dx in [-1,0,1]:
                if dy==0 and dx==0: continue
                sy = max(0,-dy); ey = min(h,h-dy)
                sx = max(0,-dx); ex = min(w,w-dx)
                ty = max(0,dy);  tty = ty+(ey-sy)
                tx = max(0,dx);  ttx = tx+(ex-sx)
                n[sy:ey,sx:ex] += fg[ty:tty,tx:ttx].astype(np.int32)
        endpoints = fg & (n == 1)
        if not np.any(endpoints): break
        img[endpoints] = 0
    return img

# ─── 核心升级：基于图论交叉点的高保真路径提取 ──────────────────────────

def extract_all_paths_strict(skel):
    """严格基于端点和交叉节点拆分骨架线，杜绝交叉口乱拐弯"""
    h, w = skel.shape
    fg = set(zip(*np.where(skel > 0)))
    if not fg: return []

    def get_neighbors(y, x):
        res = []
        for dy in [-1,0,1]:
            for dx in [-1,0,1]:
                if dy == 0 and dx == 0: continue
                ny, nx = y+dy, x+dx
                if (ny, nx) in fg: res.append((ny, nx))
        return res

    # 1. 分类像素点：端点(邻居=1) 和 交叉点(邻居>2)
    endpoints = set()
    junctions = set()
    for y, x in fg:
        n = len(get_neighbors(y, x))
        if n == 1: endpoints.add((y, x))
        elif n > 2: junctions.add((y, x))

    visited = set()
    all_paths = []

    def trace_segment(start):
        path = [(start[1], start[0])] # 转换为 X, Y 输出
        curr = start
        visited.add(curr)
        while True:
            neighbors = [n for n in get_neighbors(*curr) if n not in visited]
            if not neighbors: break
            
            # 优先检查下一步是否会直接撞上交叉点
            next_pt = None
            for n in neighbors:
                if n in junctions:
                    next_pt = n
                    break
            if not next_pt: next_pt = neighbors[0]
            
            path.append((next_pt[1], next_pt[0]))
            if next_pt in junctions:
                # 走到交叉点即刻闭合此线条，但不将其加入全局 visited，允许其他分支未来连接它
                break
            visited.add(next_pt)
            curr = next_pt
        return path

    # 优先从各独立端点开始追踪
    for ep in sorted(endpoints):
        if ep not in visited:
            path = trace_segment(ep)
            if len(path) >= 2: all_paths.append(np.array(path, dtype=np.float64))

    # 从交叉点开始向外追踪残余的分支
    for jc in sorted(junctions):
        neighbors = [n for n in get_neighbors(*jc) if n not in visited]
        for n in neighbors:
            path = [(jc[1], jc[0]), (n[1], n[0])]
            visited.add(n)
            curr = n
            if n in junctions:
                all_paths.append(np.array(path, dtype=np.float64))
                continue
            while True:
                next_ns = [nn for nn in get_neighbors(*curr) if nn not in visited]
                if not next_ns: break
                nxt = None
                for nn in next_ns:
                    if nn in junctions: nxt = nn; break
                if not nxt: nxt = next_ns[0]
                path.append((nxt[1], nxt[0]))
                if nxt in junctions: break
                visited.add(nxt)
                curr = nxt
            if len(path) >= 2: all_paths.append(np.array(path, dtype=np.float64))

    # 追踪纯闭合绝缘环（如悬空的猫眼圈，无端点无交叉）
    for pt in sorted(fg):
        if pt not in visited:
            path = trace_segment(pt)
            if len(path) >= 2: all_paths.append(np.array(path, dtype=np.float64))

    return all_paths

# ─── Smoothing & Simplification (With Bypass) ──────────────────────────────

def gaussian_smooth_1d(values, sigma=2.0):
    n = len(values)
    if n < 3 or sigma <= 0: return values
    r = int(sigma * 3)
    k = np.exp(-0.5 * (np.arange(-r, r+1) / sigma)**2)
    k /= k.sum()
    return np.convolve(np.pad(values, r, mode='edge'), k, mode='valid')[:n]

def smooth_path(pts, sigma=5.0):
    if len(pts) < 5 or sigma <= 0: return pts
    return np.column_stack((gaussian_smooth_1d(pts[:,0], sigma),
                            gaussian_smooth_1d(pts[:,1], sigma)))

def resample_uniform(pts, target_n=100):
    n = len(pts)
    if n < 3 or target_n <= 0: return pts
    diffs = np.diff(pts, axis=0)
    seg_lens = np.sqrt(np.sum(diffs**2, axis=1))
    cum = np.concatenate([[0], np.cumsum(seg_lens)])
    total = cum[-1]
    if total < 1e-6: return pts
    target_n = min(target_n, max(n * 2, 10))
    new_t = np.linspace(0, total, target_n)
    result = []; si = 0
    for t in new_t:
        while si < len(seg_lens) - 1 and cum[si+1] < t: si += 1
        s0 = cum[si]; s1 = cum[min(si+1, len(cum)-1)]
        frac = min(1.0, max(0.0, (t - s0) / max(s1 - s0, 1e-6)))
        p = pts[si] * (1-frac) + pts[min(si+1, n-1)] * frac
        result.append(p)
    return np.array(result)

def douglas_peucker(pts, eps):
    if len(pts) <= 2 or eps <= 0: return pts
    p0, pn = pts[0], pts[-1]
    line = pn - p0; ll = np.linalg.norm(line)
    if ll == 0: d = np.linalg.norm(pts - p0, axis=1)
    else: d = np.abs(np.cross(line, pts - p0)) / ll
    mi = int(np.argmax(d[1:-1])) + 1
    if d[mi] > eps:
        return np.vstack([douglas_peucker(pts[:mi+1], eps)[:-1],
                          douglas_peucker(pts[mi:], eps)])
    return np.array([pts[0], pts[-1]])

def scale_to_canvas(strokes_raw, simplify_eps, resample_n):
    all_pts = np.vstack(strokes_raw)
    cx = (all_pts[:,0].min() + all_pts[:,0].max()) / 2
    cy = (all_pts[:,1].min() + all_pts[:,1].max()) / 2
    xr = all_pts[:,0].max() - all_pts[:,0].min()
    yr = all_pts[:,1].max() - all_pts[:,1].min()
    s = (480 * 0.90) / max(xr, yr) if max(xr, yr) > 0 else 1

    strokes = []
    for pts in strokes_raw:
        if simplify_eps <= 0 or len(pts) <= 5: simp = pts
        else: simp = douglas_peucker(pts, simplify_eps)
        
        if len(simp) < 2: continue
        smooth = resample_uniform(simp, resample_n) if (resample_n > 0 and len(simp) >= 3) else simp
        
        scaled = []
        for p in smooth:
            nx = max(-240, min(240, int(round((p[0]-cx)*s))))
            ny = max(-240, min(240, int(round(-(p[1]-cy)*s))))
            scaled.append([nx, ny])
        d = [scaled[0]]
        for p in scaled[1:]:
            if p != d[-1]: d.append(p)
        if len(d) >= 2: strokes.append({"points": d})
    return strokes

# --- Stroke Order Optimization -----------------------------------------------

def optimize_stroke_order(strokes):
    if len(strokes) <= 1: return strokes
    remaining = []
    for s in strokes:
        pts = s["points"]
        remaining.append({"points": list(pts), "start": np.array(pts[0]), "end": np.array(pts[-1])})
    
    ordered = []
    stick = np.array([0.0, -240.0]) # 从底部木棍中心出发
    best_idx = 0
    best_dist = float('inf')
    for i, s in enumerate(remaining):
        d = min(np.linalg.norm(s["start"] - stick), np.linalg.norm(s["end"] - stick))
        if d < best_dist: best_dist = d; best_idx = i
        
    first = remaining.pop(best_idx)
    if np.linalg.norm(first["end"] - stick) < np.linalg.norm(first["start"] - stick):
        first["points"].reverse()
        first["start"], first["end"] = first["end"], first["start"]
    ordered.append(first)
    
    while remaining:
        current_end = ordered[-1]["end"]
        best_idx = 0
        best_dist = float('inf')
        best_reverse = False
        for i, s in enumerate(remaining):
            d_f = np.linalg.norm(s["start"] - current_end)
            d_r = np.linalg.norm(s["end"] - current_end)
            if d_f < best_dist: best_dist = d_f; best_idx = i; best_reverse = False
            if d_r < best_dist: best_dist = d_r; best_idx = i; best_reverse = True
        chosen = remaining.pop(best_idx)
        if best_reverse:
            chosen["points"].reverse()
        ordered.append(chosen)
        
    return [{"points": s["points"]} for s in ordered]

# --- Connectivity Enforcement ------------------------------------------------

def enforce_connectivity(strokes, connect_threshold=15):
    # 保留底层的底座木棍粘连安全检查，但不盲目拉伸内部精细组件
    if not strokes: return strokes
    STICK_TOL = 4
    def crosses_stick(stroke): return any(abs(p[0]) <= STICK_TOL for p in stroke["points"])
    if not any(crosses_stick(st) for st in strokes):
        best_stroke = 0; best_dist = float('inf'); best_point = None
        for idx, st in enumerate(strokes):
            for p in st["points"]:
                d = abs(p[0])
                if d < best_dist: best_dist = d; best_stroke = idx; best_point = p
        anchor = [0, int(best_point[1])]
        strokes[best_stroke]["points"] = [anchor] + strokes[best_stroke]["points"]
    return strokes

# --- Output Writing ----------------------------------------------------------

def write_outputs(strokes, output_path):
    plan = {"description": f"Strict Trace ({len(strokes)} strokes)", "strokes": strokes}
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(plan, f, indent=2)
    print(f"Successfully saved JSON: {output_path}")
    
    # 导出可视化 SVG
    ax = [p[0] for st in strokes for p in st["points"]]
    ay = [p[1] for st in strokes for p in st["points"]]
    if ax:
        mnx, mxx, mny, mxy = min(ax), max(ax), min(ay), max(ay)
        pad = 20; w = mxx - mnx + pad*2; h = mxy - mny + pad*2
        L = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" style="background:#111;">']
        for i, st in enumerate(strokes):
            c = COLORS[i % len(COLORS)]
            dd = " ".join(f"{'M' if j==0 else 'L'} {p[0]-mnx+pad:.1f} {mxy-p[1]+pad:.1f}" for j, p in enumerate(st["points"]))
            L.append(f'<path d="{dd}" fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round"/>')
        L.append("</svg>")
        with open(output_path.replace(".json", ".svg"), "w") as f: f.write("\n".join(L))

# --- Main --------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", help="Input skeleton image path")
    parser.add_argument("output", nargs="?", default=None)
    parser.add_argument("--sigma", type=float, default=0.0, help="Smooth radius (0=Strict)")
    parser.add_argument("--eps", type=float, default=0.0, help="Simplify tolerance (0=Strict)")
    parser.add_argument("--resample", type=int, default=0, help="Points target per stroke (0=Keep original)")
    parser.add_argument("--max-dim", type=int, default=500, help="Resolution limit")
    parser.add_argument("--no-connect", action="store_true", help="Disable structural feature bridging")
    args = parser.parse_args()

    out_path = args.output or args.input.rsplit(".", 1)[0] + "_trajectory.json"
    
    # 1. 加载并转换图像
    gray_arr, _ = load_and_resize(args.input, args.max_dim)
    
    # 2. 二值化
    binary = binarize_lineart(gray_arr, threshold=50)
    
    # 3. 严格分叉追踪
    print("Tracing paths using strict junction logic...")
    strokes_raw = extract_all_paths_strict(binary)
    print(f"  Extracted segments: {len(strokes_raw)}")
    
    # 4. 平滑与映射
    print("Scaling and applying threshold filters...")
    strokes = scale_to_canvas(strokes_raw, args.eps, args.resample)
    
    # 5. 结构粘连（可选）
    if not args.no_connect:
        strokes = enforce_connectivity(strokes)
        
    # 6. 行进路径拓扑优化（减少空行程飞线距离）
    strokes = optimize_stroke_order(strokes)
    
    # 7. 保存
    write_outputs(strokes, out_path)

if __name__ == "__main__":
    main()