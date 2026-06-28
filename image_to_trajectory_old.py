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

MODE_DEFAULTS = {
    "lineart": {
        "sigma": 2.0, "eps": 1.0, "max_dim": 400,
        "resample": 150, "threshold": None,
    },
    "photo": {
        "sigma": 6.0, "eps": 2.5, "max_dim": 250,
        "resample": 120, "threshold": None,
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


def is_dark_background(gray_arr):
    """Detect if image has a dark background (lines are lighter than background)."""
    return float(np.mean(gray_arr)) < 128


# ─── Binarization: Line Art Mode ────────────────────────────────────────────

def binarize_lineart(gray_arr, threshold=None, invert=None):
    """Otsu auto-threshold (or manual) — minimal pre-processing to preserve thin lines.

    invert: None = auto-detect dark background, True = force invert, False = no invert
    """
    img = gray_arr.copy()

    if invert is None:
        invert = is_dark_background(gray_arr)
        if invert:
            print("  Dark background detected — inverting")

    if invert:
        img = 255 - img

    if HAS_CV2:
        if threshold is not None:
            _, binary = cv2.threshold(img, threshold, 255,
                                       cv2.THRESH_BINARY_INV)
        else:
            _, binary = cv2.threshold(img, 0, 255,
                                       cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
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

    # 1. Sharpen — unsharp mask to enhance edges before detection
    blurred = cv2.GaussianBlur(gray_arr, (0, 0), 3)
    sharpened = cv2.addWeighted(gray_arr, 2.0, blurred, -1.0, 0)
    sharpened = np.clip(sharpened, 0, 255).astype(np.uint8)

    # 1b. CLAHE — contrast enhancement for facial features in low-contrast images
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    sharpened = clahe.apply(sharpened)

    # 2. Bilateral filter (2 passes) — edge-preserving denoising
    filtered = cv2.bilateralFilter(sharpened, d=9, sigmaColor=75, sigmaSpace=75)
    filtered = cv2.bilateralFilter(filtered, d=9, sigmaColor=75, sigmaSpace=75)

    # 3. Adaptive threshold — handles uneven lighting
    adaptive = cv2.adaptiveThreshold(
        filtered, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV, blockSize=15, C=3
    )

    # 4. Canny edge detection — auto-tuned thresholds
    median = np.median(filtered.astype(np.float64))
    low = max(0, int(median * 0.5))
    high = min(255, int(median * 1.5))
    canny = cv2.Canny(filtered, low, high)

    # 5. Morphological cleanup on Canny
    kernel_close = np.ones((3, 3), np.uint8)
    canny = cv2.morphologyEx(canny, cv2.MORPH_CLOSE, kernel_close, iterations=1)

    kernel_open = np.ones((2, 2), np.uint8)
    canny = cv2.morphologyEx(canny, cv2.MORPH_OPEN, kernel_open, iterations=1)

    kernel_dilate = np.ones((2, 2), np.uint8)
    canny = cv2.dilate(canny, kernel_dilate, iterations=1)

    # 6. Merge adaptive + Canny
    merged = cv2.bitwise_or(adaptive, canny)

    # 7. Remove small noise contours (keep only significant edges)
    contours, _ = cv2.findContours(merged, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for cnt in contours:
        if cv2.contourArea(cnt) < min_contour_area:
            cv2.drawContours(merged, [cnt], -1, 0, -1)

    # 8. Final morphological close to bridge small gaps
    kernel_final = np.ones((3, 3), np.uint8)
    merged = cv2.morphologyEx(merged, cv2.MORPH_CLOSE, kernel_final, iterations=2)

    # Convert to 0/1
    result = (merged > 0).astype(np.uint8)
    print(f"  Photo edge pixels: {np.count_nonzero(result)}")
    return result


# ─── Thin Feature (Whisker) Extraction ─────────────────────────────────────

def extract_thin_features(binary, min_length=10, aspect_ratio_min=3.0, thin_width=4):
    """Detect thin elongated features (whiskers, thin lines) directly from binary.

    These features often get lost during skeletonization because they're only
    1-3px wide and may not survive Zhang-Suen thinning well.

    Returns (thin_strokes, cleaned_binary) where thin_strokes are path arrays
    and cleaned_binary has the thin features removed.
    """
    if not HAS_CV2:
        return [], binary.copy()

    cleaned = binary.copy()
    thin_strokes = []

    # Create mask of thin pixels (distance from edge < thin_width)
    dist = cv2.distanceTransform(binary, cv2.DIST_L2, 5)
    thin_mask = ((dist > 0) & (dist <= thin_width)).astype(np.uint8) * 255

    # Also include pixels that are on thin lines (skeleton-like)
    # Use morphological gradient to find edges of thin structures
    kernel = np.ones((3, 3), np.uint8)
    eroded = cv2.erode(binary, kernel, iterations=1)
    dilated = cv2.dilate(binary, kernel, iterations=1)
    gradient = cv2.subtract(dilated, eroded)
    thin_mask = cv2.bitwise_or(thin_mask, gradient)

    # Clean up thin mask
    thin_mask = cv2.morphologyEx(thin_mask, cv2.MORPH_CLOSE, kernel, iterations=1)

    # Find connected components in thin mask
    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(
        thin_mask, connectivity=8
    )

    for i in range(1, num_labels):
        area = stats[i, cv2.CC_STAT_AREA]
        w = stats[i, cv2.CC_STAT_WIDTH]
        h = stats[i, cv2.CC_STAT_HEIGHT]

        # Calculate aspect ratio
        if min(w, h) == 0:
            continue
        ar = max(w, h) / min(w, h)

        # Check if this is an elongated thin feature
        if ar >= aspect_ratio_min and max(w, h) >= min_length:
            # Extract path from this component's pixels
            component_mask = (labels == i).astype(np.uint8) * 255
            contours, _ = cv2.findContours(
                component_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )
            if not contours:
                continue

            cnt = max(contours, key=cv2.contourArea)
            # Simplify contour to get a clean path
            epsilon = 0.02 * cv2.arcLength(cnt, True)
            approx = cv2.approxPolyDP(cnt, epsilon)

            pts = approx.squeeze()
            if pts.ndim != 2 or len(pts) < 3:
                continue

            pts = pts.astype(np.float64)
            thin_strokes.append(pts)
            # Remove from binary to avoid duplicate skeleton strokes
            cleaned[labels == i] = 0
            print(f"    Thin feature #{i}: {w}x{h}, ar={ar:.1f}, area={area} → stroke")

    return thin_strokes, cleaned

def extract_filled_regions(binary, min_area=30, max_area=800, roundness_thresh=0.5):
    """Detect small filled components (e.g. cat eyes) and extract their contours.

    Returns (contour_strokes, cleaned_binary) where contour_strokes is a list of
    Nx2 numpy arrays (closed contours) and cleaned_binary has the filled regions
    removed so skeletonize doesn't create noise.
    """
    if not HAS_CV2:
        return [], binary.copy()

    cleaned = binary.copy()
    contour_strokes = []

    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(
        binary, connectivity=8
    )

    for i in range(1, num_labels):  # skip background
        area = stats[i, cv2.CC_STAT_AREA]
        if area < min_area or area > max_area:
            continue

        mask = (labels == i).astype(np.uint8) * 255
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            continue

        cnt = max(contours, key=cv2.contourArea)
        peri = cv2.arcLength(cnt, True)
        if peri < 1e-6:
            continue
        circularity = 4 * np.pi * area / (peri * peri)

        if circularity >= roundness_thresh:
            pts = cnt.squeeze()
            if pts.ndim != 2:
                continue
            pts = pts.astype(np.float64)
            # Close the contour
            pts = np.vstack([pts, pts[0:1]])
            contour_strokes.append(pts)
            cleaned[labels == i] = 0
            print(f"    Filled region #{i}: area={area}, circularity={circularity:.2f} → contour stroke")

    return contour_strokes, cleaned


# ─── Adaptive Pruning (length-aware) ──────────────────────────────────────

def prune_skeleton_adaptive(skel, max_spur=5, min_component_pixels=15):
    """Remove short dead-end branches, but preserve small independent components.

    Before pruning, identify connected components smaller than min_component_pixels.
    These are likely features like whisker tips or small details — skip pruning on them.
    """
    img = skel.copy()
    h, w = img.shape

    if HAS_CV2:
        num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(img, connectivity=8)
        small_mask = np.zeros_like(img, dtype=bool)
        for i in range(1, num_labels):
            if stats[i, cv2.CC_STAT_AREA] <= min_component_pixels:
                small_mask |= (labels == i)
    else:
        small_mask = np.zeros_like(img, dtype=bool)

    for _ in range(max_spur):
        ys, xs = np.where(img > 0)
        if len(xs) == 0:
            break
        fg = img > 0
        n = np.zeros_like(img, dtype=np.int32)
        for dy in [-1, 0, 1]:
            for dx in [-1, 0, 1]:
                if dy == 0 and dx == 0:
                    continue
                sy = max(0, -dy); ey = min(h, h - dy)
                sx = max(0, -dx); ex = min(w, w - dx)
                ty = max(0, dy);  tty = ty + (ey - sy)
                tx = max(0, dx);  ttx = tx + (ex - sx)
                n[sy:ey, sx:ex] += fg[ty:tty, tx:ttx].astype(np.int32)
        endpoints = fg & (n == 1) & (~small_mask)
        if not np.any(endpoints):
            break
        img[endpoints] = 0
    return img


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


def prune_skeleton(skel, max_spur=10):
    """Remove short dead-end branches."""
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
    """Scale paths to ±240 canvas, simplify, resample."""
    all_pts = np.vstack(strokes_raw)
    cx = (all_pts[:,0].min() + all_pts[:,0].max()) / 2
    cy = (all_pts[:,1].min() + all_pts[:,1].max()) / 2
    xr = all_pts[:,0].max() - all_pts[:,0].min()
    yr = all_pts[:,1].max() - all_pts[:,1].min()
    s = (480 * 0.85) / max(xr, yr) if max(xr, yr) > 0 else 1

    strokes = []
    for pts in strokes_raw:
        if len(pts) <= 5:
            simp = pts
        else:
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
    """Reorder strokes to minimize travel distance between consecutive strokes.
    
    Uses greedy nearest-neighbor heuristic with stroke reversal consideration.
    Starts from the stroke closest to X=0 (the stick).
    """
    if len(strokes) <= 1:
        return strokes
    
    # Work with copies so we don't mutate originals
    remaining = []
    for s in strokes:
        pts = s["points"]
        remaining.append({
            "points": list(pts),
            "start": np.array(pts[0]),
            "end": np.array(pts[-1]),
        })
    
    ordered = []
    
    # 1. Start from stroke closest to X=0 (stick)
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
    
    # Add first stroke (reverse if end is closer to stick than start)
    first = remaining.pop(best_idx)
    if np.linalg.norm(first["end"] - stick) < np.linalg.norm(first["start"] - stick):
        first["points"].reverse()
        first["start"], first["end"] = first["end"], first["start"]
    ordered.append(first)
    
    # 2. Greedily pick nearest unvisited stroke
    while remaining:
        current_end = ordered[-1]["end"]
        best_idx = 0
        best_dist = float('inf')
        best_reverse = False
        
        for i, s in enumerate(remaining):
            # Distance if we use stroke as-is (start -> end)
            d_forward = np.linalg.norm(s["start"] - current_end)
            # Distance if we reverse stroke (end -> start)
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
    
    # Calculate total travel distance for reporting
    total_travel = 0.0
    for i in range(1, len(ordered)):
        total_travel += np.linalg.norm(ordered[i]["start"] - ordered[i-1]["end"])
    
    # Calculate original travel distance for comparison
    orig_travel = 0.0
    for i in range(1, len(strokes)):
        orig_travel += np.linalg.norm(
            np.array(strokes[i]["points"][0]) - np.array(strokes[i-1]["points"][-1])
        )
    
    print(f"  Stroke order optimized: travel {orig_travel:.0f} -> {total_travel:.0f} "
          f"({(1 - total_travel/orig_travel)*100:.0f}% reduction)")
    
    return [{"points": s["points"]} for s in ordered]


# --- Connectivity Enforcement ------------------------------------------------

def enforce_connectivity(strokes, connect_threshold=15):
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


def _run_single_pipeline(gray_arr, mode, threshold=None, min_contour_area=50, prune=15):
    defaults = MODE_DEFAULTS[mode]
    if mode == "lineart":
        binary = binarize_lineart(gray_arr, threshold=threshold)
    else:
        binary = binarize_photo(gray_arr, min_contour_area=min_contour_area)
    filled_strokes, binary = extract_filled_regions(binary)
    thin_strokes, binary = extract_thin_features(binary)
    skel = skeletonize(binary)
    print(f"  Skeleton: {np.count_nonzero(skel)} pixels")
    if prune > 0:
        skel = prune_skeleton_adaptive(skel, max_spur=prune)
        print(f"  Pruned: {np.count_nonzero(skel)} pixels")
    paths = extract_all_paths(skel)
    all_strokes = filled_strokes + thin_strokes + paths
    if not all_strokes:
        return [], {}
    smoothed = [smooth_path(s, sigma=defaults["sigma"]) for s in all_strokes]
    strokes = scale_to_canvas(smoothed, defaults["eps"], defaults["resample"])
    strokes = enforce_connectivity(strokes)
    strokes = optimize_stroke_order(strokes)
    return strokes, defaults


def run_comparison(gray_arr, output_path, lineart_threshold=None, min_contour_area=50, prune=5):
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
         threshold=None, min_contour_area=50, prune=2, compare=False, debug=False,
         min_component_pixels=15):
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
    gray_arr, orig_size = load_and_resize(image_path, max_dim)
    if compare:
        run_comparison(gray_arr, output_path, lineart_threshold=threshold, min_contour_area=min_contour_area, prune=prune)
        return
    print(f"Mode: {mode} | sigma={smooth_sigma} eps={simplify_eps} "
          f"resample={resample_n} max_dim={max_dim}")
    print("Binarizing...")
    if mode == "lineart":
        binary = binarize_lineart(gray_arr, threshold=threshold)
    else:
        binary = binarize_photo(gray_arr, min_contour_area=min_contour_area)
    print("Extracting filled regions (eyes, etc.)...")
    filled_strokes, binary = extract_filled_regions(binary)
    print("Extracting thin features (whiskers, etc.)...")
    thin_strokes, binary = extract_thin_features(binary)
    print("Skeletonizing...")
    skel = skeletonize(binary)
    print(f"Skeleton: {np.count_nonzero(skel)} pixels")
    if prune > 0:
        skel = prune_skeleton_adaptive(skel, max_spur=prune,
                                       min_component_pixels=min_component_pixels)
        print(f"Pruned: {np.count_nonzero(skel)} pixels (max_spur={prune})")
    if debug:
        save_debug_images(binary, skel, output_path)
    print("Tracing skeleton graph...")
    strokes_raw = extract_all_paths(skel)
    print(f"Extracted {len(strokes_raw)} skeleton paths")
    if filled_strokes:
        print(f"Adding {len(filled_strokes)} filled-region contour strokes")
    if thin_strokes:
        print(f"Adding {len(thin_strokes)} thin-feature strokes (whiskers)")
    strokes_raw = filled_strokes + thin_strokes + strokes_raw
    print(f"Total paths: {len(strokes_raw)}")
    if not strokes_raw:
        print("No strokes found!"); return
    print(f"Smoothing (sigma={smooth_sigma})...")
    strokes_smooth = [smooth_path(s, sigma=smooth_sigma) for s in strokes_raw]
    strokes = scale_to_canvas(strokes_smooth, simplify_eps, resample_n)
    total = sum(len(st["points"]) for st in strokes)
    print(f"Before connectivity: {len(strokes)} strokes, {total} points")
    print("Enforcing connectivity...")
    strokes = enforce_connectivity(strokes, connect_threshold=15)
    total = sum(len(st["points"]) for st in strokes)
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
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python image_to_trajectory.py unicorn.jpg output.json
  python image_to_trajectory.py photo.jpg photo.json --mode photo
  python image_to_trajectory.py sketch.png output.json --compare
  python image_to_trajectory.py portrait.jpg out.json --sigma 8 --eps 3
        """)
    parser.add_argument("input", help="Input image path")
    parser.add_argument("output", nargs="?", default=None,
                        help="Output JSON (default: derived from input)")
    parser.add_argument("--mode", choices=["auto", "lineart", "photo"],
                        default="auto", help="Processing mode (default: auto)")
    parser.add_argument("--sigma", type=float, default=None,
                        help="Gaussian smoothing sigma")
    parser.add_argument("--eps", type=float, default=None,
                        help="Douglas-Peucker simplification epsilon")
    parser.add_argument("--max-dim", type=int, default=None, dest="max_dim",
                        help="Max image dimension in pixels")
    parser.add_argument("--resample", type=int, default=None,
                        help="Target points per stroke")
    parser.add_argument("--prune", type=int, default=2,
                        help="Skeleton pruning iterations (default: 2)")
    parser.add_argument("--min-contour", type=int, default=50, dest="min_contour_area",
                        help="Min contour area to keep (photo mode, default: 50)")
    parser.add_argument("--min-component", type=int, default=15, dest="min_component_pixels",
                        help="Min component size for adaptive pruning (default: 15)")
    parser.add_argument("--threshold", type=int, default=None,
                        help="Manual threshold (lineart only)")
    parser.add_argument("--compare", action="store_true",
                        help="Run both modes, side-by-side comparison")
    parser.add_argument("--debug", action="store_true",
                        help="Save intermediate images")
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
        min_component_pixels=args.min_component_pixels,
    )
