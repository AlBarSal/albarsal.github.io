# Informe de fuente: APA

## Resumen

APA es una de las fuentes iniciales del sistema. La informacion se obtiene desde la pagina publica de llamadas a articulos de APA:

```text
https://www.apa.org/pubs/journals/resources/calls-for-papers
```

Esta fuente se trata como scraping web renderizado porque la pagina esta protegida por Incapsula WAF. El scraper intenta acceder primero con Playwright y Chromium headless, despues con `httpx`, y si ambos accesos quedan bloqueados usa un fallback de lectura Markdown mediante `r.jina.ai`.

## Como se accede a la informacion

El scraper implementado es `APAScraper`, definido en `backend/scrapers/apa.py`.

El flujo principal es:

1. Arrancar Chromium mediante Playwright en modo headless.
2. Crear un contexto de navegador con viewport, user-agent, locale y cabeceras similares a navegador real.
3. Navegar a la URL de APA con `wait_until="domcontentloaded"` y timeout de 30 segundos.
4. Esperar 2 segundos adicionales para que cargue contenido.
5. Obtener el HTML renderizado con `page.content()`.
6. Parsear el HTML con BeautifulSoup usando `lxml`.

Si Playwright no esta instalado o falla, el scraper intenta una peticion HTTP normal mediante `BaseScraper.fetch()`. Si el HTML recibido contiene bloqueo de Incapsula o no trae contenido util, se consulta:

```text
https://r.jina.ai/http://https://www.apa.org/pubs/journals/resources/calls-for-papers
```

Ese endpoint devuelve una representacion Markdown de la pagina original. No es una fuente primaria directa, sino un fallback cuando APA bloquea el acceso automatizado.

## Estrategias de extraccion HTML

Una vez obtenido el HTML, el scraper aplica varias estrategias en orden:

1. Bloques tipo Drupal Views (`views-row`, `view-content`).
2. Elementos de lista (`li`) dentro de `main` o contenedores de contenido.
3. Encabezados (`h2`, `h3`, `h4`) con enlaces.
4. Enlaces sueltos que parezcan relacionados con journals, publicaciones o calls.

Para cada convocatoria intenta extraer:

- Titulo.
- URL absoluta.
- Revista, si aparece en clases relacionadas con journal o publication.
- Fecha limite, con clases relacionadas con deadline/date/due o con patrones genericos de fecha.
- Descripcion, normalmente desde body, summary, teaser o el primer parrafo.

## Estrategia de extraccion Markdown

Cuando se usa el fallback Markdown, el parser recorre la pagina linea a linea:

- Detecta encabezados de revistas como lineas de texto.
- Detecta convocatorias como enlaces Markdown.
- Recoge lineas de fecha con formato `Month day, year`.
- Prioriza deadlines relacionados con manuscritos o full submission frente a abstract, proposal, notification o publication.
- Marca llamadas generales sin fecha como `Sin fecha límite`.

## Configuracion usada

La fuente por defecto se crea en `backend/database.py` con:

```json
{}
```

No necesita parametros especificos en `settings`, pero requiere que Playwright y Chromium esten instalados para tener la mayor probabilidad de acceso.

## Problemas y limitaciones detectadas

- La pagina esta protegida por Incapsula WAF. En la prueba actual, Playwright y `httpx` quedaron bloqueados.
- Si Playwright no esta instalado, el fallback con `httpx` puede recibir una pagina bloqueada o incompleta.
- Si el HTML devuelto contiene `incapsula` o es demasiado corto, el scraper lo considera bloqueo.
- El fallback `r.jina.ai` depende de un servicio externo. Si ese servicio cambia, limita el acceso o devuelve contenido cacheado/desactualizado, la fuente puede fallar o traer datos incompletos.
- La espera fija de 2 segundos puede ser insuficiente si APA cambia la carga de contenido o usa mas JavaScript.
- Las estrategias de parsing son defensivas, pero dependen de la estructura del HTML. Un rediseño de APA puede reducir resultados o mapear mal campos.
- La estrategia final por enlaces puede introducir falsos positivos si la pagina contiene enlaces relacionados pero no son convocatorias.
- La fecha limite no siempre esta estructurada; puede quedar como `No disponible` si no encaja en los patrones soportados.

## Estado esperado en caso de error

Si APA queda bloqueada o no se puede acceder a la pagina, la fuente devuelve `success=false`, `count=0` y un error como:

```text
No se pudo acceder a la pagina (bloqueado por WAF)
```

o:

```text
Acceso bloqueado por el WAF de APA. Playwright es requerido.
```

Si Playwright obtiene HTML valido pero no encuentra elementos, el scraper intenta el fallback Markdown antes de fallar.

## Resultado de la ultima prueba

Prueba individual mediante `/api/sources/2/test`:

```text
success=true
count=77
```
