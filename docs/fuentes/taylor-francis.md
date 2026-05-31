# Informe de fuente: Taylor & Francis

## Resumen

Taylor & Francis es una de las fuentes iniciales del sistema. Aunque la fuente visible para el usuario es `https://authorservices.taylorandfrancis.com/call-for-papers/`, el scraper no trabaja contra ese frontal. La aplicacion consulta la API publica de WordPress alojada en `think.taylorandfrancis.com` y, para una parte de los resultados, completa informacion visitando las paginas individuales de cada convocatoria.

## Como se accede a la informacion

El scraper implementado es `TaylorFrancisScraper`, definido en `backend/scrapers/taylor_francis.py`.

El acceso principal se hace mediante `httpx.AsyncClient` contra:

```text
https://think.taylorandfrancis.com/wp-json/wp/v2/special_issues
```

La consulta usa parametros de la API REST de WordPress:

```text
_fields=id,title,link,meta,special_issues
per_page=100
page=<numero>
orderby=date
order=desc
```

El scraper hace una primera peticion para obtener la primera pagina y leer las cabeceras `X-WP-Total` y `X-WP-TotalPages`. Despues solicita el resto de paginas en paralelo hasta el limite configurado.

## Enriquecimiento de detalles

La API devuelve datos suficientes para construir una convocatoria completa. El campo clave es `special_issues`, que contiene titulo, revista, deadlines y cuerpo HTML de la convocatoria.

El scraper usa estos campos:

- `_special_issues_title`
- `_special_issues_journal_title`
- `_special_issues_deadline`
- `_special_issues_deadline2`
- `_special_issues_copy`

Solo descarga paginas individuales si algun registro queda incompleto. En la prueba actual, la API estructurada cubrio revista, deadline y descripcion para todos los resultados, por lo que no fue necesario abrir paginas de detalle.

Como fallback, el limite de paginas individuales sigue siendo:

```text
max_detail_fetch=60
concurrency=8
```

En esas paginas se extraen:

- Revista: mediante texto cercano a `Submit a Manuscript to the Journal` o enlaces a `tandfonline.com/journals`.
- Fecha limite: prioriza `Manuscript deadline`, despues `Abstract deadline`, despues `meta-page-expiry-date` y por ultimo patrones genericos de fecha.
- Descripcion: primer parrafo sustancial, evitando lineas de contacto o editores.

## Configuracion usada

La fuente por defecto se crea en `backend/database.py` con:

```json
{
  "api_url": "https://think.taylorandfrancis.com/wp-json/wp/v2/special_issues",
  "page_size": 100,
  "max_pages": 10,
  "max_detail_fetch": 60,
  "concurrency": 8
}
```

Con `page_size=100` y `max_pages=10`, el sistema puede recuperar hasta 1000 entradas desde la API.

## Problemas y limitaciones detectadas

- El frontal `authorservices.taylorandfrancis.com/call-for-papers/` no es la fuente tecnica usada porque depende de una aplicacion React, gestion de consentimiento y protecciones anti-bot. Por eso se usa la API de `think.taylorandfrancis.com`.
- Si la API REST cambia, deja de exponer `special_issues` o modifica sus campos, la fuente puede fallar por completo.
- Las paginas individuales quedan como fallback, no como mecanismo principal.
- Si una pagina individual falla, el scraper no aborta toda la fuente: devuelve una convocatoria basica para esa entrada.
- La extraccion de revista, fecha y descripcion depende de patrones de texto del HTML. Un rediseño de las paginas individuales puede degradar esos campos.
- La deduplicacion se basa en un identificador generado a partir de `source + title`; si el titulo cambia ligeramente, puede aparecer como un item distinto.
- El scraping concurrente reduce tiempos, pero tambien puede verse afectado por timeouts, rate limiting o bloqueos temporales.

## Estado esperado en caso de error

Si falla la API principal, la fuente devuelve `success=false`, `count=0` y el mensaje de excepcion. Si fallan solo paginas individuales de detalle, el scraper mantiene el resultado usando los datos estructurados de la API.

## Resultado de la ultima prueba

Prueba individual mediante `/api/sources/1/test`:

```text
success=true
count=593
```
