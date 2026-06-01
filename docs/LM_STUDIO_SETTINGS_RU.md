# Рекомендуемые настройки LM Studio для AI Truck Radio

Для обычного live-эфира:

- Enable Thinking: OFF или ON, если вставки готовятся заранее.
- Temperature: 0.70–0.82.
- Top P: 0.90–0.95.
- Repeat penalty: 1.10–1.14.
- Limit response: ON.
- Max response length: 800–1200 tokens.
- Max Concurrent Predictions: 1.
- CPU threads: 2–4, если параллельно играешь в VR.

Для планового режима на 15–120 минут:

- Enable Thinking: ON.
- Temperature: 0.72–0.86.
- Max response length: 1000–1400 tokens.
- Не включай `/no_think` в панели радио.

Почему так: в плановом режиме радио ждёт, пока модель подготовит текст и TTS, поэтому можно позволить модели подумать. В live-режиме лучше не задерживать эфир.
