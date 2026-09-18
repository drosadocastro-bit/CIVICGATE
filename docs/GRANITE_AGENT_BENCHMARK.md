# Granite planner benchmark

The benchmark compares the planned CivicGate role for IBM Granite 3.1 8B Q3 and IBM Granite 4.2 8B Q4 through the same LM Studio OpenAI-compatible endpoint. Its classification is `PRACTICAL_DEPLOYMENT_COMPARISON`. It does not establish a globally better model.

Before trials, record LM Studio version, GGUF filename and hash, model quantization, backend/device, context and maximum output tokens, temperature/top-p/top-k/seed, reasoning setting, system and schema prompt, timeout, repetitions, fixtures and strict parser. A missing item leaves the trial `BLOCKED_CONDITIONS_NOT_FROZEN`.

Report latency, exposed TTFT, prompt and generation token rates, observed memory/VRAM, timeout/error counts, tool selection, argument validity, malformed output, unnecessary invocations, ambiguity preservation, authority overreach, hidden-tool attempts and repeat consistency separately. `NOT_EXPOSED` is a valid observation; it is never converted to zero.

Role conclusions are limited to `MODEL_ACCEPTABLE_FOR_CIVICGATE_PLANNER`, `MODEL_REQUIRES_REVIEW`, or `MODEL_NOT_ACCEPTABLE_FOR_CIVICGATE_PLANNER`. Quantization, generation and runtime are confounded until the exact trial conditions are frozen.

## Corrida local registrada

El runner `scripts/run_granite_lmstudio_benchmark.py` consulta el inventario local de LM Studio y usa su endpoint nativo `/api/v1/chat`, que expone TTFT y estadísticas de tokens. Guarda solo metadatos, huellas y resultados tipados en `artifacts/granite-live-benchmark.json`; ese archivo permanece ignorado junto con el tráfico de API.

En la corrida de septiembre de 2026, la etiqueta del operador fue `Granite 3.2`, pero la identidad que devolvió LM Studio fue `ibm/granite-3.1-8b`, Granite 3.1 8B, GGUF `Q3_K_L`, 8B, 4,349,475,027 bytes y una instancia cargada. El inventario expuso contexto de 131,072, eval batch 2,048, physical batch 512, paralelismo 4, Flash Attention y KV cache en GPU. El offload de 19 capas y los 6.76 GB de VRAM son valores aportados por el operador; la API no los expuso, por lo que quedan separados de la observación del proveedor.

Se ejecutaron cuatro fixtures representativos con dos repeticiones cada uno, temperatura 0, top-p 1 y máximo de 512 tokens:

- 8/8 llamadas completaron sin timeout; latencia mediana 7.15 s y p95 12.19 s.
- TTFT mediano: 303 ms; 8,628 tokens de entrada y 501 de salida en total.
- Velocidad de generación mediana: 9.45 tokens/s.
- 75% de las salidas pasó el esquema `Proposal`; 25% validó además los argumentos de la herramienta.
- Dos de las tres fixtures con `Proposal` válido fueron consistentes entre repeticiones; la fixture de inyección cambió los argumentos entre repeticiones y la de registros privados produjo salida no válida, así que ambas quedan para revisión.

Estas cifras describen el comportamiento del planificador, no una decisión de autoridad. La política determinista de CivicGate sigue siendo la autoridad final y debe bloquear o enviar a revisión propuestas ambiguas, fuera de alcance o con argumentos inválidos. Esta medición nativa es evidencia diagnóstica separada: la integración configurada del agente continúa usando `/v1/chat/completions`, que en esta sesión respondió con un error de carga del modelo y debe verificarse después de confirmar la identidad exacta en LM Studio.

### Corrida directa con llama.cpp y GBNF

La misma instancia de Granite también se probó por el servidor llama.cpp directo que administra LM Studio, usando `proposal.json.gbnf` y el mismo parser Pydantic. En 8 llamadas, la latencia mediana fue **8.05 s**, p95 **12.57 s**, con **8,356** tokens de entrada, **606** de salida, **11.47 tokens/s** de prompt y **11.20 tokens/s** de generación. TTFT no estuvo expuesto. El envelope `Proposal` fue válido en **100%**, la herramienta esperada coincidió en **100%**, los argumentos completos en **25%** y la consistencia de las propuestas válidas fue **100%**. No hubo timeouts ni errores de transporte.

La mejora del envelope proviene de la restricción directa GBNF; no es una prueba de que el modelo sea Granite 3.2 ni una comparación global de velocidad. La identidad observada sigue siendo Granite 3.1 Q3_K_L y la validación de argumentos, fechas, autoridad y alcance permanece independiente.
