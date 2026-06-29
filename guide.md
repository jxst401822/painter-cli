这种现象（面部五官、胡须、爪子细节全部丢失）是由原本代码中几个**核心算法参数过于激进**以及**缺乏对实体填充区域（如猫眼）的轮廓保护**导致的。

### 🔍 核心问题分析

1. **过度的骨架剪枝 (`max_spur=15`)**
原本默认执行 15 次剪枝。在每一步剪枝中，所有端点都会被剥离。像胡须、脚趾这种一端或两端悬空的短线段，只要长度小于 30 像素，就会在 15 次循环中被**彻底擦除**。
2. **分辨率过低 (`max_dim=200`) 与平滑过度 (`sigma=4.0`)**
将图像强行压缩到 200px 后，细节本就模糊。再配合高强度的高斯平滑（$\sigma=4.0$ 的窗口半径接近 12 像素），直接将胡须和脚部的小转角融化掉了。
3. **实体填充坍塌（眼睛丢失）**
猫眼在原图中是**实心填充**的圆形。张苏恩（Zhang-Suen）骨架提取算法在处理实心圆时，会将其收缩为一个点或一条极短的线，随后在剪枝阶段被当成噪声直接干掉。对于糖画而言，实心区域应当被转化为**空心轮廓线条**来绘制。

---

### 🛠️ 优化后的完整代码

我在代码中引入了**基于距离变换（Distance Transform）的厚度自适应空心化函数 `hollow_thick_blobs**`。它能自动识别出比普通线条厚的实体区域（如眼睛），将其精准转化为中空的闭合轮廓，同时调优了整体分辨率与平滑参数：

```python
"""
Enhanced image-to-trajectory pipeline for sugar painting.

Two processing modes:
  - lineart: Otsu threshold + skeletonize (for clean line drawings)
  - photo:   bilateral filter + adaptive threshold + Canny + morph cleanup (for photos)
  - auto:    auto-detect source type

All modes share the back-end: skeletonize → extract paths → smooth → simplify →
scale → enforce connectivity → output JSON.
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

# ─── Mode-specific default parameters ───────────────────────────────────────
# Optimized resolutions and smoothed window ratios to preserve fine details
MODE_DEFAULTS = {
    "lineart": {
        "sigma": 1.2,      # Reduced to keep sharp transitions and whiskers
        "eps": 0.6,        # Precision threshold for Douglas-Peucker
        "max_dim": 500,    # Increased resolution to capture small features
        "resample": 150, 
        "threshold": None,
        "prune": 2,        # Safe lower value for clean digital art
    },
    "photo": {
        "sigma": 2.0, 
        "eps": 1.0, 
        "max_dim": 500,
        "resample": 150, 
        "threshold": None,
        "prune": 4,
    },
}

COLORS = [
    "#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4",
    "#42d4f4", "#f032e6", "#bfef45", "#fabed4", "#469990",
    "#dcbeff", "#9A6324", "#800000", "#aaffc3", "#808000",
    "#ffd8b1", "#000075", "#a9a9a9", "#fffac8", "#7cb342",
]

# ─── Image Loading ──────────────────────────────────────────────────────────

def load_and_resize(image_path, max_dim):
    """Load image as grayscale, resize to fit max_dim. Returns (array, orig_size)."""
    img = Image.open(image_path).convert("L")
    ow, oh = img.size
    ratio = max_dim / max(ow, oh)
    nw, nh = int(ow * ratio), int(oh * ratio)
    img = img.resize((nw, nh), Image.LANCZOS)
    arr = np.array(img)
    print(f"Image: {ow}x{oh} → {nw}x{nh}")
    return arr, (ow, oh)


# ─── Source Type Detection ──────────────────────────────────────────────────

def detect_source_type(gray_arr):
    """Auto-detect 'lineart' vs 'photo' based on edge density and variance."""
    if not HAS_CV2:
        print("  (cv2 not available, defaulting to lineart)")
        return "lineart"

    edges = cv2.Canny(gray_arr, 50, 150)
    edge_density = np.count_nonzero(edges) / edges.size
    variance = np.var(gray_arr.astype(np.float64))
    unique = len(np.unique(gray_arr))

    mode = "lineart"
    if edge_density >= 0.08 or variance < 500:
        mode = "photo"
    if unique < 15:
        mode = "lineart"

    print(f"  Detection: edge_density={edge_density:.4f}, variance={variance:.0f}, "
          f"unique={unique} → {mode}")
    return mode


# ─── Binarization: Line Art Mode ────────────────────────────────────────────

def binarize_lineart(gray_arr, threshold=None):
    """Otsu auto-threshold (or manual) + Gaussian blur + morph open."""
    img = gray_arr.copy()

    if HAS_CV2:
        img = cv2.GaussianBlur(img, (3, 3), 0)
        if threshold is not None:
            _, binary = cv2.threshold(img, threshold, 255, cv2.THRESH_BINARY_INV)
        else:
            _, binary = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        kernel = np.ones((2, 2), np.uint8)
        binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)
    else:
        if threshold is None:
            threshold = 150
        binary = ((img < threshold) * 255).astype(np.uint8)

    result = (binary > 0).astype(np.uint8)
    print(f"  Line pixels: {np.count_nonzero(result)}")
    return result


# ─── Binarization: Photo Mode ──────────────────────────────────────────────

def binarize_photo(gray_arr, min_contour_area=50):
    """OpenCV photo pipeline: sharpen + bilateral + adaptive + Canny + contour filter."""
    if not HAS_CV2:
        print("  ERROR: Photo mode requires opencv-python (cv2)")
        return binarize_lineart(gray_arr)

    blurred = cv2.GaussianBlur(gray_arr, (0, 0), 3)
    sharpened = cv2.addWeighted(gray_arr, 2.0, blurred, -1.0, 0)
    sharpened = np.clip(sharpened, 0, 255).astype(np.uint8)

    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    sharpened = clahe.apply(sharpened)

    filtered = cv2.bilateralFilter(sharpened, d=9, sigmaColor=75, sigmaSpace=75)
    filtered = cv2.bilateralFilter(filtered, d=9, sigmaColor=75, sigmaSpace=75)

    adaptive = cv2.adaptiveThreshold(
        filtered, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV, blockSize=15, C=3
    )

    median = np.median(filtered.astype(np.float64))
    low = max(0, int(median * 0.5))
    high = min(255, int(median * 1.5))
    canny = cv2.Canny(filtered, low, high)

    kernel_close = np.ones((3, 3), np.uint8)
    canny = cv2.morphologyEx(canny, cv2.MORPH_CLOSE, kernel_close, iterations=1)

    kernel_open = np.ones((2, 2), np.uint8)
    canny = cv2.morphologyEx(canny, cv2.MORPH_OPEN, kernel_open, iterations=1)

    kernel_dilate = np.ones((2, 2), np.uint8)
    canny = cv2.dilate(canny, kernel_dilate, iterations=1)

    merged = cv2.bitwise_or(adaptive, canny)

    contours, _ = cv2.findContours(merged, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for cnt in contours:
        if cv2.contourArea(cnt) < min_contour_area:
            cv2.drawContours(merged, [cnt], -1, 0, -1)

    kernel_final = np.ones((3, 3), np.uint8)
    merged = cv2.morphologyEx(merged, cv2.MORPH_CLOSE, kernel_final, iterations=2)

    result = (merged > 0).astype(np.uint8)
    print(f"  Photo edge pixels: {np.count_nonzero(result)}")
    return result


# ─── Feature Preservation Layer ─────────────────────────────────────────────

def hollow_thick_blobs(binary, max_line_thickness=3.5):
    """
    Finds regions in the binary mask that are thicker than typical lines (like filled eyes)
    and hollows them out into outlines so skeletonization preserves their shape as loops.
    """
    if not HAS_CV2:
        return binary
        
    contour_img = (binary * 255).astype(np.uint8)
    contours, _ = cv2.findContours(contour_img, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    refined = binary.copy()
    
    for cnt in contours:
        mask = np.zeros_like(binary, dtype=np.uint8)
        cv2.drawContours(mask, [cnt], -1, 1, thickness=-1)
        
        # Calculate local thickness using Distance Transform
        dist = cv2.distanceTransform(mask, cv2.DIST_L2, 3)
        _, max_val, _, _ = cv2.minMaxLoc(dist)
        
        # If it exceeds line thickness threshold, it is an filled area (e.g. Cat eyes)
        if max_val > max_line_thickness:
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
            eroded = cv2.erode(mask, kernel, iterations=1)
            boundary = cv2.bitwise_xor(mask, eroded)
            
            # Hollow out this region in final mask
            refined[mask > 0] = 0
            refined[boundary > 0] = 1
            
    return refined


# ─── Skeletonization (Zhang-Suen, vectorized) ──────────────────────────────

def skeletonize(binary):
    """Vectorized Zhang-Suen thinning."""
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


def prune_skeleton(skel, max_spur=2):
    """Remove short dead-end branches gently."""
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


# ─── Path Extraction (DFS with heading-aware traversal) ─────────────────────

def extract_all_paths(skel):
    """Extract ordered paths from skeleton using DFS traversal."""
    h, w = skel.shape
    fg = set()
    ys, xs = np.where(skel > 0)
    for y, x in zip(ys.tolist(), xs.tolist()):
        fg.add((y, x))

    if not fg:
        return []

    def get_neighbours(y, x, exclude=None):
        result = []
        for dy in [-1,0,1]:
            for dx in [-1,0,1]:
                if dy==0 and dx==0: continue
                ny, nx = y+dy, x+dx
                if (ny,nx) in fg and (exclude is None or (ny,nx) not in exclude):
                    result.append((ny, nx))
        return result

    endpoints = []
    for y, x in fg:
        n = len(get_neighbours(y, x))
        if n == 1:
            endpoints.append((y, x))

    print(f"  Skeleton graph: {len(endpoints)} endpoints, {len(fg)} pixels")

    visited = set()
    all_paths = []

    def trace_from(start, prev=None):
        path = [(start[1], start[0])]
        visited.add(start)
        current = start
        heading = None
        while True:
            neighbours = [n for n in get_neighbours(current[0], current[1])
                          if n not in visited]
            if not neighbours:
                break
            if heading and len(neighbours) > 1:
                best = None; best_dot = -float('inf')
                for ny, nx in neighbours:
                    dy_n = ny - current[0]; dx_n = nx - current[1]
                    dot = dy_n * heading[0] + dx_n * heading[1]
                    if dot > best_dot:
                        best_dot = dot; best = (ny, nx)
                next_pt = best
            else:
                next_pt = neighbours[0]
            heading = (next_pt[0] - current[0], next_pt[1] - current[1])
            path.append((next_pt[1], next_pt[0]))
            visited.add(next_pt)
            current = next_pt
        return path

    for ep in sorted(endpoints, key=lambda p: p[0]*w + p[1]):
        if ep in visited: continue
        path = trace_from(ep)
        if len(path) >= 3:
            all_paths.append(path)

    while True:
        remaining = fg - visited
        if not remaining: break
        start = min(remaining, key=lambda p: abs(p[0]-h//2) + abs(p[1]-w//2))
        path = trace_from(start)
        if len(path) >= 3:
            all_paths.append(path)
        else:
            visited.add(start)

    result = [np.array(path, dtype=np.float64) for path in all_paths]
    result.sort(key=lambda a: -len(a))
    return result


# ─── Smoothing, Simplification, Resampling ──────────────────────────────────

def gaussian_smooth_1d(values, sigma=2.0):
    n = len(values)
    if n < 3: return values
    r = int(sigma * 3)
    k = np.exp(-0.5 * (np.arange(-r, r+1) / sigma)**2)
    k /= k.sum()
    return np.convolve(np.pad(values, r, mode='edge'), k, mode='valid')[:n]

def smooth_path(pts, sigma=5.0):
    if len(pts) < 5: return pts
    return np.column_stack((gaussian_smooth_1d(pts[:,0], sigma),
                            gaussian_smooth_1d(pts[:,1], sigma)))

def resample_uniform(pts, target_n=100):
    n = len(pts)
    if n < 3: return pts
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
    if len(pts) <= 2: return pts
    p0, pn = pts[0], pts[-1]
    line = pn - p0; ll = np.linalg.norm(line)
    if ll == 0:
        d = np.linalg.norm(pts - p0, axis=1)
    else:
        d = np.abs(np.cross(line, pts - p0)) / ll
    mi = int(np.argmax(d[1:-1])) + 1
    if d[mi] > eps:
        return np.vstack([douglas_peucker(pts[:mi+1], eps)[:-1],
                          douglas_peucker(pts[mi:], eps)])
    return np.array([pts[0], pts[-1]])


# ─── Coordinate Scaling ────────────────────────────────────────────────────

def scale_to_canvas(strokes_raw, simplify_eps, resample_n):
    all_pts = np.vstack(strokes_raw)
    cx = (all_pts[:,0].min() + all_pts[:,0].max()) / 2
    cy = (all_pts[:,1].min() + all_pts[:,1].max()) / 2
    xr = all_pts[:,0].max() - all_pts[:,0].min()
    yr = all_pts[:,1].max() - all_pts[:,1].min()
    s = (480 * 0.85) / max(xr, yr) if max(xr, yr) > 0 else 1

    strokes = []
    for pts in strokes_raw:
        simp = douglas_peucker(pts, simplify_eps)
        if len(simp) < 2: continue
        smooth = resample_uniform(simp, resample_n) if len(simp) >= 3 else simp
        scaled = []
        for p in smooth:
            nx = max(-240, min(240, int(round((p[0]-cx)*s))))
            ny = max(-240, min(240, int(round(-(p[1]-cy)*s))))
            scaled.append([nx, ny])
        d = [scaled[0]]
        for p in scaled[1:]:
            if p != d[-1]: d.append(p)
        if len(d) >= 2:
            strokes.append({"points": d})
    return strokes


# --- Stroke Order Optimization (Nearest-Neighbor TSP) -----------------------

def optimize_stroke_order(strokes):
    if len(strokes) <= 1:
        return strokes
    
    remaining = []
    for s in strokes:
        pts = s["points"]
        remaining.append({
            "points": list(pts),
            "start": np.array(pts[0]),
            "end": np.array(pts[-1]),
        })
    
    ordered = []
    stick = np.array([0.0, 0.0])
    best_idx = 0
    best_dist = float('inf')
    for i, s in enumerate(remaining):
        d_start = np.linalg.norm(s["start"] - stick)
        d_end = np.linalg.norm(s["end"] - stick)
        d = min(d_start, d_end)
        if d < best_dist:
            best_dist = d
            best_idx = i
    
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
            d_forward = np.linalg.norm(s["start"] - current_end)
            d_reverse = np.linalg.norm(s["end"] - current_end)
            
            if d_forward < best_dist:
                best_dist = d_forward
                best_idx = i
                best_reverse = False
            if d_reverse < best_dist:
                best_dist = d_reverse
                best_idx = i
                best_reverse = True
        
        chosen = remaining.pop(best_idx)
        if best_reverse:
            chosen["points"].reverse()
            chosen["start"], chosen["end"] = chosen["end"], chosen["start"]
        ordered.append(chosen)
    
    total_travel = 0.0
    for i in range(1, len(ordered)):
        total_travel += np.linalg.norm(ordered[i]["start"] - ordered[i-1]["end"])
    
    orig_travel = 0.0
    for i in range(1, len(strokes)):
        orig_travel += np.linalg.norm(
            np.array(strokes[i]["points"][0]) - np.array(strokes[i-1]["points"][-1])
        )
    
    print(f"  Stroke order optimized: travel {orig_travel:.0f} -> {total_travel:.0f} "
          f"({(1 - total_travel/orig_travel)*100:.0f}% reduction)")
    
    return [{"points": s["points"]} for s in ordered]


# --- Connectivity Enforcement ------------------------------------------------

def enforce_connectivity(strokes, connect_threshold=25):
    if not strokes:
        return strokes
    bridges = []
    max_iterations = 20
    for iteration in range(max_iterations):
        n = len(strokes)
        connected = [[False]*n for _ in range(n)]
        for i in range(n):
            connected[i][i] = True
            pi = np.array(strokes[i]["points"])
            for j in range(i+1, n):
                pj = np.array(strokes[j]["points"])
                min_dist = float('inf')
                for p in pi:
                    for q in pj:
                        d = abs(p[0]-q[0]) + abs(p[1]-q[1])
                        if d < min_dist: min_dist = d
                if min_dist <= connect_threshold:
                    connected[i][j] = True; connected[j][i] = True
        parent = list(range(n))
        def find(x):
            while parent[x] != x: parent[x] = parent[parent[x]]; x = parent[x]
            return x
        def union(a, b):
            a, b = find(a), find(b)
            if a != b: parent[b] = a
        for i in range(n):
            for j in range(i+1, n):
                if connected[i][j]: union(i, j)
        components = {}
        for i in range(n):
            root = find(i)
            components.setdefault(root, []).append(i)
        if len(components) == 1:
            print(f"  All {n} strokes connected (threshold={connect_threshold})")
            break
        main_root = max(components, key=lambda r: len(components[r]))
        main_indices = set(components[main_root])
        print(f"  Iteration {iteration+1}: {len(components)} components, adding bridges...")
        new_bridges = []
        for root, indices in components.items():
            if root == main_root: continue
            best_dist = float('inf'); best_from = best_to = None
            for i in indices:
                pi = np.array(strokes[i]["points"])
                for j in main_indices:
                    pj = np.array(strokes[j]["points"])
                    for p in pi:
                        for q in pj:
                            d = abs(p[0]-q[0]) + abs(p[1]-q[1])
                            if d < best_dist:
                                best_dist = d
                                best_from = [int(p[0]), int(p[1])]
                                best_to = [int(q[0]), int(q[1])]
            if best_from and best_to:
                bridge = {"points": [best_from, best_to]}
                new_bridges.append(bridge); bridges.append(bridge)
                print(f"    Bridge: {best_from} -> {best_to} (dist={best_dist:.0f})")
                main_indices.update(indices)
        if not new_bridges: break
        strokes = strokes + new_bridges
    touches_stick = any(
        any(abs(p[0]) <= 2 for p in st["points"]) for st in strokes
    )
    if not touches_stick:
        best_stroke = 0; best_dist = float('inf'); best_point = None
        for idx, st in enumerate(strokes):
            for p in st["points"]:
                d = abs(p[0])
                if d < best_dist:
                    best_dist = d; best_stroke = idx; best_point = p
        anchor = [0, best_point[1]]
        strokes[best_stroke]["points"] = [anchor] + strokes[best_stroke]["points"]
        print(f"  Stick root added: {anchor}")
    else:
        print(f"  Stick adhesion: OK")
    if bridges:
        print(f"  Total bridges added: {len(bridges)}")
    return strokes


# --- Output Writing ----------------------------------------------------------

def build_plan(strokes, description=""):
    return {"description": description, "strokes": strokes}


def write_outputs(plan, output_path):
    strokes = plan["strokes"]
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(plan, f, indent=2)
    print(f"Written: {output_path}")
    try:
        from PIL import ImageDraw
        sz = 600
        img_out = Image.new('RGB', (sz, sz), 'white')
        draw = ImageDraw.Draw(img_out)
        for i, st in enumerate(strokes):
            pts = st['points']; c = COLORS[i % len(COLORS)]
            for j in range(len(pts)-1):
                x1 = int((pts[j][0]+240)/480*(sz-60))+30
                y1 = int((240-pts[j][1])/480*(sz-60))+30
                x2 = int((pts[j+1][0]+240)/480*(sz-60))+30
                y2 = int((240-pts[j+1][1])/480*(sz-60))+30
                draw.line([(x1,y1),(x2,y2)], fill=c, width=3)
            x1 = int((pts[0][0]+240)/480*(sz-60))+30
            y1 = int((240-pts[0][1])/480*(sz-60))+30
            draw.ellipse([x1-5,y1-5,x1+5,y1+5], fill=c)
        png_path = output_path.replace('.json', '.png')
        img_out.save(png_path)
        print(f"PNG: {png_path}")
    except Exception: pass
    ax = [p[0] for st in strokes for p in st["points"]]
    ay = [p[1] for st in strokes for p in st["points"]]
    if ax:
        mnx,mxx = min(ax),max(ax); mny,mxy = min(ay),max(ay)
        pad=30; w=mxx-mnx+pad*2; h=mxy-mny+pad*2
        L=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}">']
        L.append(f'<rect width="{w}" height="{h}" fill="white"/>')
        for i,st in enumerate(strokes):
            c=COLORS[i%len(COLORS)]
            dd=" ".join(f"{'M' if j==0 else 'L'} {p[0]-mnx+pad:.1f} {mxy-p[1]+pad:.1f}"
                        for j,p in enumerate(st["points"]))
            L.append(f'<path d="{dd}" fill="none" stroke="{c}" stroke-width="2.5" '
                     f'stroke-linecap="round" stroke-linejoin="round"/>')
        L.append("</svg>")
        svg_path = output_path.replace(".json", ".svg")
        with open(svg_path,"w") as f: f.write("\n".join(L))
        print(f"SVG: {svg_path}")


# --- Debug Output ------------------------------------------------------------

def save_debug_images(binary, skel, output_path):
    base = output_path.replace('.json', '')
    bin_img = Image.fromarray((binary * 255).astype(np.uint8))
    bin_img.save(f"{base}_debug_binary.png")
    print(f"  Debug: {base}_debug_binary.png")
    if HAS_CV2:
        skel_color = np.zeros((*skel.shape, 3), dtype=np.uint8)
        skel_color[skel > 0] = [0, 255, 0]
        cv2.imwrite(f"{base}_debug_skeleton.png", skel_color)
    else:
        skel_img = Image.fromarray((skel * 255).astype(np.uint8))
        skel_img.save(f"{base}_debug_skeleton.png")
    print(f"  Debug: {base}_debug_skeleton.png")


# --- Comparison Mode ---------------------------------------------------------

def _render_panel(draw, strokes, x_offset, sz, label):
    for i, st in enumerate(strokes):
        pts = st['points']; c = COLORS[i % len(COLORS)]
        for j in range(len(pts)-1):
            x1 = x_offset + int((pts[j][0]+240)/480*(sz-60))+30
            y1 = int((240-pts[j][1])/480*(sz-60))+30
            x2 = x_offset + int((pts[j+1][0]+240)/480*(sz-60))+30
            y2 = int((240-pts[j+1][1])/480*(sz-60))+30
            draw.line([(x1,y1),(x2,y2)], fill=c, width=3)
    n = len(strokes); p = sum(len(s["points"]) for s in strokes)
    draw.text((x_offset + 10, 8), f"{label} ({n} strokes, {p} pts)", fill="#666")


def _run_single_pipeline(gray_arr, mode, threshold=None, min_contour_area=50, prune=None):
    defaults = MODE_DEFAULTS[mode]
    p_val = prune if prune is not None else defaults["prune"]
    
    if mode == "lineart":
        binary = binarize_lineart(gray_arr, threshold=threshold)
    else:
        binary = binarize_photo(gray_arr, min_contour_area=min_contour_area)
    
    # Apply feature preservation
    binary = hollow_thick_blobs(binary)
        
    skel = skeletonize(binary)
    print(f"  Skeleton: {np.count_nonzero(skel)} pixels")
    if p_val > 0:
        skel = prune_skeleton(skel, max_spur=p_val)
        print(f"  Pruned: {np.count_nonzero(skel)} pixels")
    paths = extract_all_paths(skel)
    if not paths:
        return [], {}
    smoothed = [smooth_path(s, sigma=defaults["sigma"]) for s in paths]
    strokes = scale_to_canvas(smoothed, defaults["eps"], defaults["resample"])
    strokes = enforce_connectivity(strokes)
    strokes = optimize_stroke_order(strokes)
    return strokes, defaults


def run_comparison(gray_arr, output_path, lineart_threshold=None, min_contour_area=50, prune=None):
    from PIL import ImageDraw
    print("\n== Line Art Mode ==")
    strokes_la, _ = _run_single_pipeline(gray_arr, "lineart", threshold=lineart_threshold, prune=prune)
    plan_la = build_plan(strokes_la, "Line art mode")
    print("\n== Photo Mode ==")
    strokes_ph, _ = _run_single_pipeline(gray_arr, "photo", min_contour_area=min_contour_area, prune=prune)
    plan_ph = build_plan(strokes_ph, "Photo mode")
    base = output_path.replace('.json', '')
    write_outputs(plan_la, f"{base}_lineart.json")
    write_outputs(plan_ph, f"{base}_photo.json")
    sz = 600; gap = 20
    img = Image.new('RGB', (sz * 2 + gap, sz), 'white')
    draw = ImageDraw.Draw(img)
    _render_panel(draw, strokes_la, 0, sz, "Line Art")
    _render_panel(draw, strokes_ph, sz + gap, sz, "Photo")
    div_x = sz + gap // 2
    draw.line([(div_x, 30), (div_x, sz - 30)], fill="#ccc", width=1)
    cmp_path = f"{base}_compare.png"
    img.save(cmp_path)
    pts_la = sum(len(s["points"]) for s in strokes_la)
    pts_ph = sum(len(s["points"]) for s in strokes_ph)
    print(f"\nComparison: {cmp_path}")
    print(f"  Line art: {len(strokes_la)} strokes, {pts_la} points")
    print(f"  Photo:    {len(strokes_ph)} strokes, {pts_ph} points")


# --- Main Pipeline -----------------------------------------------------------

def main(image_path, output_path, mode="auto", max_dim=None,
         smooth_sigma=None, simplify_eps=None, resample_n=None,
         threshold=None, min_contour_area=50, prune=None, compare=False, debug=False):
    if mode == "auto":
        img_tmp = Image.open(image_path).convert("L")
        arr_tmp = np.array(img_tmp)
        mode = detect_source_type(arr_tmp)
        print(f"Auto-detected: {mode}")
        
    defaults = MODE_DEFAULTS[mode]
    max_dim = max_dim or defaults["max_dim"]
    smooth_sigma = smooth_sigma if smooth_sigma is not None else defaults["sigma"]
    simplify_eps = simplify_eps if simplify_eps is not None else defaults["eps"]
    resample_n = resample_n if resample_n is not None else defaults["resample"]
    p_val = prune if prune is not None else defaults["prune"]
    
    gray_arr, orig_size = load_and_resize(image_path, max_dim)
    if compare:
        run_comparison(gray_arr, output_path, lineart_threshold=threshold, min_contour_area=min_contour_area, prune=p_val)
        return
        
    print(f"Mode: {mode} | sigma={smooth_sigma} eps={simplify_eps} "
          f"resample={resample_n} max_dim={max_dim} prune={p_val}")
          
    print("Binarizing...")
    if mode == "lineart":
        binary = binarize_lineart(gray_arr, threshold=threshold)
    else:
        binary = binarize_photo(gray_arr, min_contour_area=min_contour_area)
        
    # Hollow thick blobs before skeletonization
    print("Preserving internal dense features...")
    binary = hollow_thick_blobs(binary)
        
    print("Skeletonizing...")
    skel = skeletonize(binary)
    print(f"Skeleton: {np.count_nonzero(skel)} pixels")
    if p_val > 0:
        skel = prune_skeleton(skel, max_spur=p_val)
        print(f"Pruned: {np.count_nonzero(skel)} pixels (max_spur={p_val})")
    if debug:
        save_debug_images(binary, skel, output_path)
        
    print("Tracing skeleton graph...")
    strokes_raw = extract_all_paths(skel)
    print(f"Extracted {len(strokes_raw)} paths")
    if not strokes_raw:
        print("No strokes found!"); return
        
    print(f"Smoothing (sigma={smooth_sigma})...")
    strokes_smooth = [smooth_path(s, sigma=smooth_sigma) for s in strokes_raw]
    strokes = scale_to_canvas(strokes_smooth, simplify_eps, resample_n)
    
    total = sum(len(st["points"]) for st in strokes)
    print(f"Before connectivity: {len(strokes)} strokes, {total} points")
    
    print("Enforcing connectivity...")
    strokes = enforce_connectivity(strokes, connect_threshold=25)
    
    print(f"Optimizing stroke order...")
    strokes = optimize_stroke_order(strokes)
    
    total = sum(len(st["points"]) for st in strokes)
    print(f"Final: {len(strokes)} strokes, {total} points")
    plan = build_plan(strokes, f"{mode} ({len(strokes)} strokes)")
    write_outputs(plan, output_path)


# --- CLI ---------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(
        description="Image to sugar painting trajectory converter",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("input", help="Input image path")
    parser.add_argument("output", nargs="?", default=None, help="Output JSON")
    parser.add_argument("--mode", choices=["auto", "lineart", "photo"], default="auto")
    parser.add_argument("--sigma", type=float, default=None)
    parser.add_argument("--eps", type=float, default=None)
    parser.add_argument("--max-dim", type=int, default=None, dest="max_dim")
    parser.add_argument("--resample", type=int, default=None)
    parser.add_argument("--prune", type=int, default=None, help="Skeleton pruning iterations")
    parser.add_argument("--min-contour", type=int, default=50, dest="min_contour_area")
    parser.add_argument("--threshold", type=int, default=None)
    parser.add_argument("--compare", action="store_true")
    parser.add_argument("--debug", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    out = args.output or args.input.rsplit(".", 1)[0] + "_trace.json"
    main(
        args.input, out,
        mode=args.mode,
        max_dim=args.max_dim,
        smooth_sigma=args.sigma,
        simplify_eps=args.eps,
        resample_n=args.resample,
        threshold=args.threshold,
        min_contour_area=args.min_contour_area,
        prune=args.prune,
        compare=args.compare,
        debug=args.debug,
    )

```