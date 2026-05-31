# Informe de fuente: Emerald Publishing

## Resumen

La fuente cargada como `Emerald` apunta a:

```text
https://www.emeraldgrouppublishing.com/publish-with-us/calls-for-papers
```

La mejor via de acceso es HTML directo con selectores especificos sobre tarjetas Drupal y paginacion.

## Como se accede a la informacion

Se usa `GenericHtmlScraper` con `httpx` y BeautifulSoup. La pagina responde con HTML completo y contiene tarjetas de convocatoria como enlaces:

```text
a.node--type-call-for-papers
```

Configuracion optimizada:

```json
{
  "item_selector": "a.node--type-call-for-papers",
  "title_selector": ".cfp-card__content-title",
  "journal_selector": ".cfp-card__content-journal",
  "deadline_selector": ".cfp-card__active-dates-item time",
  "description_selector": ".cfp-card__content-body",
  "default_journal": "Emerald Publishing",
  "pagination_url_template": "https://www.emeraldgrouppublishing.com/publish-with-us/calls-for-papers?page={page}",
  "pagination_start": 1,
  "max_pages": 80,
  "concurrency": 8
}
```

## Problemas y limitaciones detectadas

- La configuracion anterior usaba `main li` y solo recuperaba 5 resultados.
- Las convocatorias no estan en `li`, sino en enlaces-tarjeta con clase `node--type-call-for-papers`.
- La paginacion usa indice base cero: la primera pagina es la URL base y las adicionales son `?page=1` hasta `?page=80`.
- Se detectaron duplicados entre paginas; el scraper los elimina por id.
- Si Emerald modifica las clases Drupal de las tarjetas, los selectores necesitaran ajuste.

## Resultado de la ultima prueba

Prueba individual mediante `/api/sources/11/test`:

```text
success=true
count=481
```
