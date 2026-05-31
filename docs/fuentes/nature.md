# Informe de fuente: Nature / Scientific Reports

## Resumen

La fuente cargada como `Nature` apunta a:

```text
https://www.nature.com/srep/calls-for-papers
```

El contenido corresponde a calls for papers de `Scientific Reports`. La mejor via de acceso es HTML directo con selectores especificos y paginacion.

## Como se accede a la informacion

Se usa `GenericHtmlScraper` con `httpx` y BeautifulSoup. La pagina responde correctamente con HTML estatico; no hizo falta Playwright ni servicios externos.

Configuracion optimizada:

```json
{
  "item_selector": "li.app-article-list-row__item",
  "title_selector": "[data-test='link-title'], h2 a, h3 a",
  "url_selector": "[data-test='link-title'], h2 a, h3 a",
  "deadline_selector": "[data-test='end-date']",
  "description_selector": "[data-test='description'], .c-card__summary",
  "default_journal": "Scientific Reports",
  "pagination_url_template": "https://www.nature.com/srep/calls-for-papers?page={page}",
  "pagination_start": 2,
  "max_pages": 63,
  "concurrency": 8
}
```

## Problemas y limitaciones detectadas

- La version inicial solo leia la primera pagina y recuperaba 10 resultados.
- La pagina publica expone paginacion hasta la pagina 63. Sin paginacion se pierde la mayor parte de la fuente.
- Si Nature cambia los atributos `data-test` o la clase `app-article-list-row__item`, los selectores pueden dejar de funcionar.
- La configuracion actual fija `max_pages=63`; si Nature añade mas paginas, habra que actualizar ese limite o implementar deteccion automatica.

## Resultado de la ultima prueba

Prueba individual mediante `/api/sources/10/test`:

```text
success=true
count=627
```
