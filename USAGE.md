# 糖画轨迹生成使用文档

## 概述

本工具从参考图像生成糖画轨迹 JSON 文件，并可视化为 PNG/SVG/GIF。

## 文件说明

| 文件 | 功能 |
|------|------|
| `image_to_trajectory.py` | 核心：图像→轨迹 JSON |
| `add_face.py` | 添加面部细节（眼睛、鼻子、嘴巴） |
| `render.py` | 生成 PNG + SVG 静态图 |
| `trajectory_gif.py` | 生成绘制过程 GIF 动画 |

## 完整流程

### 1. 生成基础轨迹

```bash
python image_to_trajectory.py <输入图片> <输出JSON> [参数]
```

**示例：**
```bash
python image_to_trajectory.py unicorn_ref.jpg unicorn_trace.json --max-dim 150 --sigma 6 --eps 1.2 --resample 80
```

**参数说明：**

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--max-dim` | 200 | 图像最大尺寸（像素） |
| `--sigma` | 4.0 | 平滑强度（越大越平滑） |
| `--eps` | 1.5 | Douglas-Peucker 简化阈值 |
| `--resample` | 100 | 每笔画重采样点数 |

**输出：**
- `unicorn_trace.json` - 轨迹数据
- `unicorn_trace.png` - 静态预览
- `unicorn_trace.svg` - 矢量图

### 2. 生成可视化

# 生成 GIF 动画
python trajectory_gif.py unicorn_trace.json
```

**GIF 参数：**

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--speed` | 15 | 每点绘制时间（毫秒） |
| `--size` | 600 | 画布尺寸（像素） |

**示例：**
```bash
python trajectory_gif.py unicorn_trace.json --speed 10 --size 800
```

## JSON 格式

```json
{
  "description": "Unicorn trace (18 strokes)",
  "strokes": [
    {
      "points": [[x1, y1], [x2, y2], ...]
    },
    ...
  ]
}
```

**坐标系统：**
- 范围：±240
- X=0：竹签位置（左侧）
- Y 轴：向上为正

## 糖画连接规则

1. **笔画连接**：所有笔画通过 15 单位阈值物理连接
2. **整体连通**：整个结构形成单一连通分量
3. **竹签附着**：结构至少有一个点接触 X=0
4. **桥接笔画**：自动添加桥接笔画连接断开部分

## 快速开始

```bash
# 一键生成（图像→JSON→GIF）
python image_to_trajectory.py unicorn_ref.jpg unicorn_trace.json --max-dim 150 --sigma 6 --eps 1.2 --resample 80
python trajectory_gif.py unicorn_trace.json

# 打开预览
start unicorn_trace.gif
```

## 依赖

```bash
pip install numpy Pillow
```
