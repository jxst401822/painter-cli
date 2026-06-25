#!/usr/bin/env python3
"""
糖画图案生成器 (Sugar Painting Pattern Generator)

双引擎架构:
  1. dayin.la API  — 直接调用打印啦平台的 AI 糖画生成接口（无需认证）
  2. 火山引擎 ARK  — 使用 doubao-seedream-5.0-lite 生成 + PIL 后处理为糖画风格

糖画图案特征:
  - 纯黑背景
  - 琥珀色/橙色线条（模拟焦糖）
  - 连续线条画风格（模拟糖浆浇注）
  - 卡通可爱风格
  - 轮廓为主，极少填充

用法:
    python sugar_painting_gen.py --prompt "龙" --output dragon.png
    python sugar_painting_gen.py --prompt "蝴蝶" --engine dayinla
    python sugar_painting_gen.py --prompt "孙悟空" --engine ark --output swk.png
"""

import argparse
import json
import os
import sys
import time
import urllib.request

# PIL/numpy imported lazily inside postprocess_sugar_style() and ark_*() so the
# dayinla default path runs on devices without PIL/numpy (quantum-bot m310).

# ── dayin.la API ──────────────────────────────────────────────────────────────

DAYINLA_BASE = "https://ai.dayin.la"


def dayinla_generate(prompt: str, timeout: int = 120) -> str:
    """调用 dayin.la API 生成糖画图案，返回图片 URL。"""
    # Step 1: Submit prompt
    payload = json.dumps({"msg": prompt}).encode()
    req = urllib.request.Request(
        f"{DAYINLA_BASE}/api/ai/image",
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
    if data.get("errorCode") != 0:
        raise RuntimeError(f"dayin.la submit failed: {data.get('msg', 'unknown')}")

    task_id = data["data"]["id"]
    print(f"  [dayin.la] Task submitted, id={task_id}")

    # Step 2: Poll for result
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(2)
        req = urllib.request.Request(
            f"{DAYINLA_BASE}/api/ai/queue-info?id={task_id}",
            headers={"User-Agent": "Mozilla/5.0"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())

        status = data.get("data", {}).get("status", -1)
        if status == 2:
            image_list = data["data"].get("image_list", [])
            if image_list:
                url = image_list[0]["image_url"]
                print(f"  [dayin.la] Generation complete: {url[:80]}...")
                return url
            raise RuntimeError("dayin.la returned status 2 but no image_list")
        elif status == 3:
            raise RuntimeError("dayin.la generation failed (status=3)")
        print(f"  [dayin.la] Waiting... status={status}")

    raise TimeoutError(f"dayin.la generation timed out after {timeout}s")


def dayinla_get_prompts() -> list:
    """获取 dayin.la 的 AI 推荐词汇列表。"""
    req = urllib.request.Request(
        f"{DAYINLA_BASE}/api/tanghua/text",
        headers={"User-Agent": "Mozilla/5.0"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())
    return data.get("data", {}).get("aiVocabularyData", [])


# ── 火山引擎 ARK 引擎 ─────────────────────────────────────────────────────────

ARK_ENDPOINT = "https://ark.cn-beijing.volces.com/api/plan/v3/images/generations"
ARK_MODEL = "doubao-seedream-5.0-lite"
ARK_HELPER_CONFIG = os.path.expanduser("~/.ark-helper/config.yaml")


def ark_get_api_key() -> str:
    """从 ark-helper 配置读取 API key。"""
    import yaml
    if not os.path.exists(ARK_HELPER_CONFIG):
        raise FileNotFoundError(f"ark-helper config not found: {ARK_HELPER_CONFIG}")
    with open(ARK_HELPER_CONFIG) as f:
        cfg = yaml.safe_load(f)
    key = cfg.get("plans", {}).get("volcengine-agent-plan", {}).get("api_key")
    if not key:
        raise KeyError("volcengine-agent-plan api_key not found in ark-helper config")
    return key


def ark_generate(prompt: str, size: str = "2048x2048") -> str:
    """调用火山引擎 ARK 生成图片，返回图片 URL。"""
    import yaml

    api_key = ark_get_api_key()

    # 构造糖画风格 prompt
    sugar_prompt = (
        f"糖画风格图案：{prompt}。"
        "纯黑背景，琥珀色橙色发光线条，连续线条画风格，"
        "模拟用熔化的焦糖在黑色石板上浇注而成的传统中国糖画艺术。"
        "线条有粗细变化，圆润流畅，卡通可爱风格，轮廓为主极少填充，"
        "高对比度，简洁清晰，适合糖画制作。"
    )

    payload = json.dumps({
        "model": ARK_MODEL,
        "prompt": sugar_prompt,
        "size": size,
        "response_format": "url",
    }).encode()

    req = urllib.request.Request(
        ARK_ENDPOINT,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read())

    url = data["data"][0]["url"]
    print(f"  [ark] Generation complete: {url[:80]}...")
    return url


# ── PIL 后处理：将普通图片转为糖画风格 ────────────────────────────────────────

def postprocess_sugar_style(image_path: str, output_path: str,
                            line_color=(255, 165, 0),
                            bg_color=(0, 0, 0),
                            threshold=128):
    """
    将任意图片后处理为糖画风格：
    1. 转灰度
    2. 反色（如果是白底黑线）
    3. 边缘检测提取轮廓
    4. 阈值化为二值图
    5. 将线条着色为琥珀色，背景为纯黑
    6. 轻微模糊模拟糖浆流动感
    """
    from PIL import Image, ImageFilter, ImageEnhance, ImageOps
    import numpy as np

    img = Image.open(image_path).convert("RGB")

    # 如果背景是白色，先反色
    extrema = img.convert("L").getextrema()
    if extrema[0] > 200:  # 背景偏白
        img = ImageOps.invert(img)

    # 转灰度
    gray = img.convert("L")

    # 边缘检测（使用 FIND_EDGES）
    edges = gray.filter(ImageFilter.FIND_EDGES)

    # 增强边缘对比度
    enhancer = ImageEnhance.Contrast(edges)
    edges = enhancer.enhance(2.0)

    # 阈值化
    arr = np.array(edges)
    binary = np.where(arr > threshold, 255, 0).astype(np.uint8)

    # 创建彩色输出
    result = np.zeros((arr.shape[0], arr.shape[1], 3), dtype=np.uint8)
    mask = binary > 0
    result[mask] = line_color
    result[~mask] = bg_color

    # 轻微高斯模糊模拟糖浆边缘
    result_img = Image.fromarray(result)
    result_img = result_img.filter(ImageFilter.GaussianBlur(radius=0.8))

    # 增加一点发光效果
    glow = result_img.filter(ImageFilter.GaussianBlur(radius=2))
    glow = ImageEnhance.Brightness(glow).enhance(0.3)
    result_img = Image.blend(result_img, glow, 0.3)

    result_img.save(output_path)
    return output_path


# ── 下载工具 ──────────────────────────────────────────────────────────────────

def download_image(url: str, path: str) -> int:
    """下载图片到本地文件。"""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = resp.read()
    with open(path, "wb") as f:
        f.write(data)
    return len(data)


# ── 主入口 ────────────────────────────────────────────────────────────────────

def generate(prompt: str, output: str, engine: str = "dayinla",
             size: str = "2048x2048", postprocess: bool = False):
    """
    生成糖画图案。

    Args:
        prompt: 图案描述文字（如"龙"、"蝴蝶"、"孙悟空"）
        output: 输出文件路径
        engine: "dayinla" 或 "ark"
        size: ARK 引擎的图片尺寸
        postprocess: 是否对 ARK 生成的图片做 PIL 后处理
    """
    print(f"生成糖画图案: '{prompt}'")
    print(f"  引擎: {engine}")

    if engine == "dayinla":
        image_url = dayinla_generate(prompt)
    elif engine == "ark":
        image_url = ark_generate(prompt, size)
    else:
        raise ValueError(f"Unknown engine: {engine}")

    # 下载图片
    raw_path = output.replace(".png", "_raw.png") if postprocess else output
    file_size = download_image(image_url, raw_path)
    print(f"  图片已下载: {raw_path} ({file_size / 1024:.1f} KB)")

    # 后处理（仅 ARK 引擎需要）
    if postprocess and engine == "ark":
        postprocess_sugar_style(raw_path, output)
        print(f"  后处理完成: {output}")
        os.remove(raw_path)
    elif raw_path != output:
        os.rename(raw_path, output)

    print(f"\n完成！糖画图案已保存到: {os.path.abspath(output)}")
    return output


def main():
    parser = argparse.ArgumentParser(description="糖画图案生成器")
    parser.add_argument("--prompt", "-p", required=True, help="图案描述（如：龙、蝴蝶、孙悟空）")
    parser.add_argument("--output", "-o", default="sugar_painting.png", help="输出文件路径")
    parser.add_argument("--engine", "-e", choices=["dayinla", "ark"], default="dayinla",
                        help="生成引擎：dayinla（打印啦API）或 ark（火山引擎）")
    parser.add_argument("--size", "-s", default="2048x2048", help="ARK引擎图片尺寸")
    parser.add_argument("--postprocess", action="store_true", help="对ARK图片做糖画风格后处理")
    parser.add_argument("--random-prompt", action="store_true", help="使用dayin.la推荐随机词汇")
    args = parser.parse_args()

    prompt = args.prompt
    if args.random_prompt:
        prompts = dayinla_get_prompts()
        if prompts:
            import random
            prompt = random.choice(prompts)
            print(f"随机词汇: {prompt}")

    generate(prompt, args.output, args.engine, args.size, args.postprocess)


if __name__ == "__main__":
    main()
