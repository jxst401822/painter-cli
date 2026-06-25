# dayin.la Sugar Painting API Reference

Reverse-engineered from https://ai.dayin.la/sugar/ai-drawing

## API Base

```
https://ai.dayin.la
```

No authentication required. All endpoints return JSON with `errorCode: 0` on success.

## Endpoints

### 1. Submit Image Generation

```
POST /api/ai/image
Content-Type: application/json

{"msg": "龙"}
```

Response:
```json
{
  "errorCode": 0,
  "msg": "AI正在为你生成，请稍后",
  "data": {"id": 200433, "status": 0}
}
```

### 2. Poll Generation Status

```
GET /api/ai/queue-info?id={task_id}
```

Status values:
- `0` — queued
- `1` — generating
- `2` — complete (image_list available)
- `3` — failed

Response (status=2):
```json
{
  "errorCode": 0,
  "data": {
    "id": 200433,
    "status": 2,
    "image_list": [{
      "image_url": "https://web.dayinla.net/upload/attachment/image/2026-06/18/xxx.png",
      "print_goods_id": 131091,
      "print_goods_color_id": 418951,
      "price": 9.8
    }]
  }
}
```

Poll interval: 2 seconds. Typical generation time: 4-8 seconds.

### 3. Get AI Vocabulary (Prompt Suggestions)

```
GET /api/tanghua/text
```

Returns ~50 suggested prompts in `data.aiVocabularyData`:
- "穿着雨衣的蝴蝶", "玩滑板的中国龙", "骑着扫把的艾莎公主",
- "开摩托车的毛毛虫", "冲浪的机器人", "蜗牛", "海马看手机", etc.

### 4. Get Painting Patterns (Template Library)

```
GET /api/tanghua/painting-pattern
```

Returns categorized SVG templates (几何, 动物, etc.) with icon URLs.

### 5. Get AI Pattern Gallery

```
GET /api/tanghua/ai-list?goods_type_id=14&limit=10&is_rand=1
```

Returns community-generated patterns with image URLs, sell counts, thumbnails.

## Rate Limiting

The web app implements client-side cooldown that doubles with each use:
2, 4, 8, 16, 32, 64, 128, 256 seconds. The API itself may not enforce this,
but adding delays between calls is recommended for batch generation.

## Output Format

- Images are PNG, typically 600x600 pixels, ~10KB
- Black background with amber/orange lines
- Cartoon/kawaii style line art
- Suitable for sugar painting machines (糖画机)

## Full API Endpoint List (from JS bundle)

```
/api/ai/image          — Submit generation
/api/ai/queue-info     — Poll status
/api/ai/index          — List patterns
/api/ai/info           — Pattern details
/api/ai/do             — Action on pattern
/api/ai/photo          — Photo input
/api/ai/photo-line     — Photo line art
/api/ai/photo-frame-list — Frame templates
/api/tanghua/text      — Vocabulary suggestions
/api/tanghua/painting-pattern — Template library
/api/tanghua/ai-list   — Community gallery
/api/tanghua/goods-do  — Order action
/api/tanghua/save-goods — Save pattern
/api/tanghua/order-info — Order details
/api/tanghua/print-queue — Print queue
/api/tanghua/user-order — User orders
```
