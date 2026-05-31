# Informe de fuente: HTML generico

## Resumen

El tipo `generic_html` permite dar de alta fuentes que no tienen scraper especifico. Esta pensado para paginas HTML relativamente simples, donde las convocatorias aparecen como articulos, listas, encabezados o enlaces.

Tambien se usa para reglas especificas ligeras, como el caso de Nature cuando la URL contiene `nature.com` y `calls-for-papers`.

## Como se accede a la informacion

El scraper implementado es `GenericHtmlScraper`, definido en `backend/scrapers/generic_html.py`.

El acceso se hace con `BaseScraper.fetch()`, que usa `httpx.AsyncClient` con cabeceras de navegador, redirecciones habilitadas y timeout de 30 segundos. El HTML recibido se parsea con BeautifulSoup usando `lxml`.

No se ejecuta JavaScript. El scraper solo ve el HTML que devuelve la peticion HTTP inicial.

## Autodescubrimiento de configuracion

Cuando se crea una fuente nueva con nombre y URL, `backend/source_discovery.py` intenta detectar el tipo:

- Dominios de Taylor & Francis: `taylor_francis`.
- APA con `calls-for-papers`: `apa`.
- ScienceDirect con `calls-for-papers`: `sciencedirect`.
- Nature con `calls-for-papers`: `generic_html` con selectores predefinidos.
- Resto de URLs: `generic_html` con autodescubrimiento por candidatos.

Para URLs genericas, el sistema descarga la pagina, prueba varios conjuntos de selectores y puntua cada candidato segun:

- Numero de CFPs validos.
- Numero de CFPs con fecha.
- Numero de CFPs con descripcion.

El candidato con mejor puntuacion se guarda como configuracion.

## Configuracion soportada

Los selectores disponibles son:

```json
{
  "item_selector": "selector CSS para cada convocatoria",
  "title_selector": "selector CSS del titulo dentro del item",
  "url_selector": "selector CSS del enlace dentro del item",
  "journal_selector": "selector CSS de revista",
  "deadline_selector": "selector CSS de fecha limite",
  "description_selector": "selector CSS de descripcion",
  "default_journal": "nombre por defecto de revista/fuente"
}
```

Si se define `item_selector`, el scraper itera cada item y aplica los selectores internos. Si no se define, aplica estrategias de fallback:

1. Elementos `li`.
2. Encabezados `h2`, `h3`, `h4` con enlaces.
3. Enlaces cuyo texto o URL parezcan relacionados con calls, papers, special issues o submissions.

## Paginacion opcional

El scraper generico soporta paginacion cuando la fuente define:

```json
{
  "pagination_url_template": "https://example.com/calls?page={page}",
  "pagination_start": 2,
  "max_pages": 10,
  "concurrency": 8
}
```

La primera pagina se obtiene desde `url`. Las paginas adicionales se construyen con `pagination_url_template` y se descargan en paralelo hasta `max_pages`.

Tambien se soportan items que son ellos mismos enlaces (`<a href="...">...</a>`), como ocurre en Emerald.

## Campos extraidos

Para cada item intenta construir:

- Titulo.
- URL absoluta, resolviendo enlaces relativos contra la URL de la fuente.
- Revista, desde `journal_selector` o `default_journal`.
- Fecha limite, desde `deadline_selector` o patrones genericos de fecha.
- Descripcion, desde `description_selector` o texto restante del contexto.

## Problemas y limitaciones detectadas

- No sirve bien para paginas que renderizan el contenido exclusivamente con JavaScript.
- Puede fallar en paginas con protecciones anti-bot, WAF, cookies obligatorias o consent managers que oculten el contenido.
- El autodescubrimiento no garantiza precision; puede elegir selectores que devuelvan resultados incompletos o falsos positivos.
- Si una pagina cambia su estructura HTML, los selectores configurados pueden dejar de funcionar.
- La deteccion de fechas es generica y principalmente orientada a formatos en ingles. Fechas muy especificas o localizadas pueden quedar como `No disponible`.
- La estrategia por enlaces es amplia y puede capturar enlaces que no sean convocatorias.
- Si no hay `item_selector`, el scraper limita resultados de estrategias genericas a 100 elementos.
- Si la paginacion configurada es incorrecta, puede repetir resultados o omitir paginas.
- Si la fuente devuelve HTML valido pero sin coincidencias, el scraper marca la fuente como fallida con el mensaje de que no se encontraron convocatorias.
- Al aceptar URLs configuradas por usuario, conviene endurecer validaciones si la app se publica, para evitar que el servidor consulte destinos internos o no deseados.

## Estado esperado en caso de error

Errores habituales:

```text
La fuente no tiene URL
```

```text
No se pudo acceder a la pagina
```

```text
Error al parsear HTML: <detalle>
```

```text
No se encontraron convocatorias con la configuracion actual
```

En todos esos casos la fuente devuelve `success=false`, `count=0` y el mensaje de error correspondiente.
