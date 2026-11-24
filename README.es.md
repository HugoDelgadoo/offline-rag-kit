# Offline RAG Kit

[![CI](https://github.com/HugoDelgadoo/offline-rag-kit/actions/workflows/ci.yml/badge.svg)](https://github.com/HugoDelgadoo/offline-rag-kit/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/offline-rag-kit)](https://pypi.org/project/offline-rag-kit/)
[![Python](https://img.shields.io/pypi/pyversions/offline-rag-kit)](https://pypi.org/project/offline-rag-kit/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](https://github.com/HugoDelgadoo/offline-rag-kit/blob/main/LICENSE)

[English](https://github.com/HugoDelgadoo/offline-rag-kit/blob/main/README.md) | **Español**

**Búsqueda local de documentos, centrada en la privacidad, con citas de PDF y respuestas opcionales de una IA local.**

> **Estado: v0.1 alpha — un prototipo funcional centrado en la recuperación de información, todavía no un sistema RAG multimodal completo.**

Offline RAG Kit ayuda a encontrar evidencias en PDFs, Markdown y documentos de texto plano locales sin enviar archivos privados a la nube. Usa SQLite FTS5 para la búsqueda léxica, guarda el número de página y las coordenadas de bloque de los PDFs, y opcionalmente puede generar respuestas basadas en esas evidencias con un modelo de Ollama que se ejecuta en tu equipo.

> Nota: esta traducción puede ir por detrás de la versión en inglés ([README.md](https://github.com/HugoDelgadoo/offline-rag-kit/blob/main/README.md)), que es la de referencia. El resto de la documentación (hoja de ruta, arquitectura, guía de contribución) está solo en inglés.

## ¿Por qué este proyecto?

- **Local primero:** los archivos y el índice se quedan en tu máquina.
- **Fuentes verificables:** los resultados de PDF incluyen la página y el cuadro delimitador (x0,y0,x1,y1).
- **Fácil de ejecutar:** Python, PyMuPDF y SQLite; no hace falta ninguna cuenta externa.
- **Sin inferencia en la nube:** la generación opcional solo llama a `127.0.0.1:11434`.
- **Una buena base:** la hoja de ruta incluye recuperación híbrida vectorial/BM25, OCR, audio, reordenación y evaluaciones automáticas.

## Inicio rápido (Windows PowerShell)

Requisitos: Python 3.10 o superior.

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install offline-rag-kit
offline-rag ingest .\demo
offline-rag search "SQLite"
```

Buscar en tus propios archivos:

```powershell
offline-rag ingest "C:\Users\TuUsuario\Documents\conocimiento"
offline-rag search "política de retención"
```

Para hacer preguntas con un modelo local, primero [instala Ollama](https://ollama.com/) y descarga un modelo:

```powershell
ollama pull llama3.2
offline-rag ask "¿Cómo se citan los PDFs?" --model llama3.2
```

El comando `ask` usa **solo** un servidor Ollama local. No puede garantizar que el modelo nunca se invente cosas; comprueba las citas antes de fiarte de las respuestas generadas.

## Referencia de comandos

```text
offline-rag [--db RUTA] [--json] ingest CARPETA
offline-rag [--db RUTA] [--json] search "TÉRMINOS" [--limit 5] [--mode lexical|vector|hybrid]
offline-rag [--db RUTA] [--json] embed [--model bge-m3] [--rebuild] [--ollama-host URL] [--allow-remote]
offline-rag [--db RUTA] [--json] ask "PREGUNTA" [--limit 5] [--model llama3.2]
                                     [--ollama-host URL] [--allow-remote]
```

Volver a ejecutar `ingest` es incremental: los archivos sin cambios (según el hash de su contenido) no se vuelven a procesar.

`ask` se conecta a `127.0.0.1:11434` por defecto. Usa `OLLAMA_HOST` o `--ollama-host` para otro puerto. Los servidores que no sean locales se rechazan salvo que pases `--allow-remote`, porque los fragmentos recuperados saldrían de tu equipo.

### Búsqueda semántica opcional (Ollama local)

La búsqueda normal (`search`) es léxica y funciona totalmente sin conexión. Para que además encuentre por significado (por ejemplo "trabajar desde casa" ~ "teletrabajo"), crea los embeddings **de forma explícita** con un modelo local de Ollama y elige un modo:

```powershell
ollama pull bge-m3                       # un modelo de embeddings multilingüe
offline-rag embed --model bge-m3         # paso explícito; solo procesa los pasajes nuevos
offline-rag search "trabajar desde casa" --mode hybrid   # BM25 + vectores fusionados (RRF)
offline-rag search "trabajar desde casa" --mode vector   # solo vectores
```

- `ingest` nunca llama a Ollama y el modo por defecto sigue siendo `lexical`. Los modos semánticos necesitan Ollama en marcha al buscar, porque la pregunta también debe convertirse en vector.
- El índice recuerda qué modelo creó sus vectores. Para cambiar de modelo hace falta `offline-rag embed --model NUEVO --rebuild`.
- Misma regla de privacidad que `ask`: solo se aceptan servidores locales salvo que pases `--allow-remote`.
- Los vectores se comparan con un recorrido completo, que va bien con miles de pasajes pero se vuelve lento en colecciones muy grandes. La velocidad de los embeddings depende de tu equipo y del modelo.
- **Todavía no se ha medido con un modelo real.** Usa `python -m offline_rag.eval --mode hybrid --model bge-m3` para ver qué hace con el conjunto de datos incluido.

`--json` (se coloca antes del subcomando) imprime un único documento JSON por la salida estándar, con el texto completo del pasaje, la página, el cuadro delimitador y la puntuación de cada resultado. Los errores y los códigos de salida no cambian y siguen yendo a la salida de errores.

## Capacidades y limitaciones actuales

| Capacidad | Estado |
| --- | --- |
| Indexar de forma recursiva PDF / Markdown / TXT | Soportado |
| Ranking léxico con SQLite FTS5 (BM25) | Soportado |
| Páginas de origen y cuadros delimitadores en PDF | Soportado |
| Generación de texto con Ollama local | Opcional, soportado |
| Recuperación semántica / vectorial | Opcional, con embeddings de Ollama local (aún sin evaluar) |
| OCR, comprensión de imágenes, transcripción de audio | Planificado |
| Panel web / autenticación de usuarios | Planificado |
| Evaluación fiable de la fundamentación por afirmación | Planificado |

La primera versión **no** hace OCR de PDFs escaneados. Las tablas que PyMuPDF detecta (con líneas y, a menudo, también las sin bordes bien alineadas) se indexan como un pasaje por tabla; la detección es heurística y puede fallar o interpretar mal diseños complejos. Las palabras partidas con un guion al final de la línea se vuelven a unir. Cada bloque de texto de un PDF es una unidad de recuperación, así que las coordenadas describen bloques y no fragmentos arbitrarios de la respuesta. Los archivos modificados se actualizan al volver a indexar y los borrados se eliminan del índice. Es un prototipo para desarrolladores y un solo usuario, no un servicio reforzado para varios usuarios.

## Evaluación

```powershell
python -m offline_rag.eval
```

Mide recall@k y MRR sobre un pequeño conjunto de datos incluido (`eval/`). Consulta [docs/EVALUATION.md](https://github.com/HugoDelgadoo/offline-rag-kit/blob/main/docs/EVALUATION.md) (en inglés) para ver la línea base actual.

## Desarrollo

```powershell
python -m pip install -e .
python -m unittest discover -s tests -v
```

Consulta la [hoja de ruta](https://github.com/HugoDelgadoo/offline-rag-kit/blob/main/ROADMAP.md), la [arquitectura](https://github.com/HugoDelgadoo/offline-rag-kit/blob/main/docs/ARCHITECTURE.md) y la [guía de contribución](https://github.com/HugoDelgadoo/offline-rag-kit/blob/main/CONTRIBUTING.md) (todas en inglés). Se agradecen contribuciones, informes de errores reproducibles y pequeños conjuntos de datos de prueba reales (sin contenido confidencial).

## Mantenedor

Creado y mantenido por [@HugoDelgadoo](https://github.com/HugoDelgadoo). Consulta el [registro de cambios](https://github.com/HugoDelgadoo/offline-rag-kit/blob/main/CHANGELOG.md) para ver las notas de cada versión.

## Licencia

MIT — consulta [LICENSE](https://github.com/HugoDelgadoo/offline-rag-kit/blob/main/LICENSE).
