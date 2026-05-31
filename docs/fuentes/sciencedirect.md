# Informe de fuente: ScienceDirect

## Resumen

ScienceDirect esta soportada como tipo de fuente especializado. La via principal actual accede a la pagina publica de calls for papers:

```text
https://www.sciencedirect.com/browse/calls-for-papers
```

El acceso con `httpx` y Playwright queda bloqueado por la proteccion anti-bot de Elsevier, pero el acceso con `curl_cffi` e impersonacion Chrome devuelve el HTML completo. La API de Scopus queda como fallback si esa via directa falla.

## Como se accede a la informacion

El scraper implementado es `ScienceDirectScraper`, definido en `backend/scrapers/sciencedirect.py`.

La via principal usa `curl_cffi` con `impersonate="chrome124"` contra:

```text
https://www.sciencedirect.com/browse/calls-for-papers
```

La pagina incluye un script `window.INITIAL_STATE` con datos estructurados. El scraper lee:

```text
callsForPapers.cfpList
```

Campos extraidos:

- `title`
- `journal.displayName`
- `submissionDeadline`
- `summary`
- `contentId`
- `url`

La URL final se construye como:

```text
https://www.sciencedirect.com/special-issue/<contentId>/<slug>
```

## Requisitos de configuracion

La via directa no necesita clave de API. Si falla, el scraper intenta fallback mediante Scopus Search API. Para ese fallback necesita una clave de API de Elsevier/Scopus. El scraper la busca en:

1. Variable de entorno `API_KEY_ELSEVIER`.
2. Campo `api_key` dentro de `settings`.

Parametros configurables:

```json
{
  "count": 200,
  "months": 12
}
```

Valores por defecto:

- `count`: maximo de CFPs a recuperar. Si se deja vacio en la via directa, se recupera todo el browse.
- `months=12`: ventana temporal aproximada hacia atras.
- `_PAGE_SIZE=25`: tamano de pagina usado por la API.

## Fallback Scopus

Si la via directa falla, cada entrada de Scopus se transforma en convocatoria solo si cumple:

- Tiene titulo de al menos 10 caracteres.
- El subtipo esta en `ed`, `no`, `le` o `sh`.
- El titulo contiene alguna expresion relacionada con calls:
  - `call for papers`
  - `call for submissions`
  - `special issue`

La URL se construye preferentemente con DOI:

```text
https://doi.org/<doi>
```

Si no hay DOI, se intenta usar el enlace web de Scopus.

## Problemas y limitaciones detectadas

- La pagina publica de ScienceDirect no se puede leer con `httpx` ni Playwright en este entorno; requiere `curl_cffi` por fingerprint TLS/navegador.
- La estructura `window.INITIAL_STATE` puede cambiar si ScienceDirect rediseña la pagina.
- La fuente solo depende de API key si se usa fallback Scopus.
- Una clave puede no tener permisos suficientes. En caso de `401`, el scraper devuelve un mensaje especifico de API key no autorizada.
- Puede haber limites de cuota, rate limits o restricciones asociadas al plan de la API.
- La busqueda no representa necesariamente todos los calls visibles en ScienceDirect; solo recupera registros indexados en Scopus que coincidan con la consulta.
- En la via directa si se extrae `submissionDeadline`. La descripcion disponible es `summary`, normalmente nombres de editores o texto corto.
- La ventana temporal se calcula de forma aproximada por meses convertidos a dias y luego a anio, por lo que puede ser mas amplia de lo esperado.
- El filtro por subtipo puede excluir convocatorias validas si Scopus las clasifica de otra forma.
- La construccion manual de URL evita problemas de codificacion, pero es mas sensible a cambios de formato exigidos por la API.

## Estado esperado en caso de error

Si falta la clave:

```text
API_KEY_ELSEVIER no configurada en .env
```

Si la clave no esta autorizada:

```text
API key no autorizada para Scopus Search. Verifica API_KEY_ELSEVIER en .env.
```

Otros errores HTTP o de parsing quedan envueltos como:

```text
Error Scopus API: <detalle>
```

## Resultado de la ultima prueba

Prueba individual mediante `/api/sources/14/test`:

```text
success=true
count=2777
```
