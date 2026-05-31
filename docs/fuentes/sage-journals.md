# Informe de fuente: Sage Journals

## Resumen

La fuente cargada como `Sage Journals` apunta a:

```text
https://journals.sagepub.com/open-call-for-papers
```

El acceso directo esta bloqueado por una verificacion anti-bot. `httpx`, Playwright y `curl_cffi` recibieron respuestas 403 o paginas de verificacion. La via funcional encontrada es usar `r.jina.ai` como lector Markdown.

## Como se accede a la informacion

El scraper implementado es `SageScraper`, definido en `backend/scrapers/sage.py`.

Consulta:

```text
https://r.jina.ai/http://https://journals.sagepub.com/open-call-for-papers
```

El lector devuelve una version Markdown de la pagina. El scraper:

1. Localiza secciones por disciplina.
2. Detecta revistas por enlaces a `/home/<codigo>`.
3. Detecta convocatorias por enlaces a `call`, `special issue`, `cfp`, `author-instructions`, `special-issues` o `why-publish`.
4. Extrae deadlines desde lineas `Submission deadline: ...`.
5. Limpia parametros de tracking `_gl` y `_ga` en URLs.

## Problemas y limitaciones detectadas

- El sitio original bloquea acceso automatizado directo con 403.
- Playwright headless no supera la verificacion.
- `curl_cffi` tampoco supera Sage en este entorno.
- El fallback `r.jina.ai` es un servicio externo y puede devolver contenido cacheado, incompleto o cambiar formato.
- Las descripciones no aparecen de forma consistente en el Markdown; se dejan como `No disponible`.
- Algunas llamadas generales comparten URL de instrucciones de autor y pueden ser menos especificas que una convocatoria de special issue.

## Resultado de la ultima prueba

Prueba individual mediante `/api/sources/12/test`:

```text
success=true
count=75
```
