# Call for Papers Explorer

Aplicación web para explorar y visualizar convocatorias de publicación científica (*Calls for Papers*) extraídas de fuentes editoriales configurables.

La aplicación se inicializa con dos fuentes por defecto:

- **Taylor & Francis** — 580+ special issues activos vía API REST pública de `think.taylorandfrancis.com`
- **APA** — página de convocatorias en `apa.org/pubs/journals/resources/calls-for-papers` (requiere scraping web)

## Capturas de datos

| Fuente | Método | Resultados típicos |
|--------|--------|--------------------|
| Taylor & Francis | API REST de WordPress (`think.taylorandfrancis.com/wp-json/wp/v2/special_issues`) + scraping concurrente de páginas individuales para journal/descripción | ~583 CFPs |
| APA | Playwright headless (bypass de WAF Incapsula) → BeautifulSoup | Variable (10–100+) |

## Características

- CRUD de fuentes desde la interfaz web
- Alta rápida de fuentes con solo alias + URL y autodescubrimiento de scraper/configuración
- CRUD de búsquedas con nombre, correo electrónico y palabras clave
- Avisos por correo HTML cuando una actualización de CFPs encuentra coincidencias
- Persistencia de fuentes en SQLite
- Carga dinámica de scrapers activos desde base de datos
- Scraper HTML genérico configurable mediante selectores CSS
- Scraping asíncrono y robusto con múltiples estrategias de extracción
- Caché en memoria (TTL 1 hora) para no sobrecargar las fuentes
- Si una fuente falla, la otra sigue mostrando sus resultados con un indicador de error claro
- Búsqueda en tiempo real por título, revista y descripción
- Filtro por fuente (Taylor & Francis / APA)
- Botón de actualización forzada
- Indicadores de estado por fuente
- Diseño responsive, limpio y usable
- Sin dependencias de frontend (HTML/CSS/JS vanilla)

## Requisitos

- Python 3.11 o superior
- pip
- Conexión a internet

## Estructura del proyecto

```
CALL_OF_PAPERS/
├── backend/
│   ├── main.py                  # App FastAPI + rutas API
│   ├── database.py              # Persistencia SQLite de fuentes y búsquedas
│   ├── models.py                # Modelos Pydantic
│   ├── scraper_factory.py       # Registro y creación dinámica de scrapers
│   ├── source_discovery.py       # Autodetección de fuentes
│   ├── search_notifications.py   # Coincidencias de búsquedas + envío SMTP
│   ├── scrapers/
│   │   ├── __init__.py
│   │   ├── base.py              # BaseScraper, utilidades de parsing
│   │   ├── taylor_francis.py    # Scraper T&F via API REST + scraping
│   │   ├── apa.py               # Scraper APA via Playwright
│   │   └── generic_html.py      # Scraper genérico con selectores CSS
│   ├── data/
│   │   └── call_of_papers.sqlite3  # Se crea automáticamente
│   └── requirements.txt
├── frontend/
│   ├── index.html
│   ├── style.css
│   └── app.js
└── README.md
```

## Instalación

```bash
# 1. Descomprimir / clonar el proyecto
cd CALL_OF_PAPERS

# 2. Crear entorno virtual (recomendado)
python -m venv venv

# Windows
venv\Scripts\activate

# macOS/Linux
source venv/bin/activate

# 3. Instalar dependencias Python
cd backend
pip install -r requirements.txt

# 4. Instalar el navegador Chromium para Playwright
playwright install chromium
```

## Ejecución

```bash
# Desde la carpeta backend/
python main.py
```

O con uvicorn directamente:

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Abrir en el navegador: **http://localhost:8000**

> La primera carga puede tardar 60–90 segundos mientras el scraper obtiene datos de ~583 special issues de Taylor & Francis (60 páginas individuales en paralelo + API paginada).

La base SQLite se crea automáticamente en `backend/data/call_of_papers.sqlite3`.

### Configuración de correo

Las búsquedas se pueden crear sin configurar correo, pero los avisos solo se enviarán cuando el servidor tenga datos SMTP. Crear un archivo `.env` en la raíz del proyecto o configurar estas variables antes de arrancar la aplicación:

```bash
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USERNAME=usuario@example.com
SMTP_PASSWORD=clave-o-app-password
SMTP_FROM=usuario@example.com
SMTP_FROM_NAME="Call for Papers Explorer"
SMTP_TLS=true
SMTP_SSL=false
```

`SMTP_TLS=true` cubre el caso habitual de puerto 587 con STARTTLS. Para proveedores que usen SSL directo en puerto 465, usar `SMTP_SSL=true`.

## Endpoints disponibles

| Método | Ruta | Descripción |
|--------|------|-------------|
| `GET` | `/` | Interfaz web (frontend) |
| `GET` | `/api/cfp` | Listado de CFPs (con caché 1h) |
| `GET` | `/api/cfp?refresh=true` | Fuerza actualización desde las fuentes |
| `GET` | `/api/cfp?source=APA` | Filtrar por fuente |
| `GET` | `/api/cfp?q=texto` | Búsqueda por texto libre |
| `GET` | `/api/health` | Estado del servidor y caché |
| `GET` | `/api/source-types` | Tipos de scraper disponibles |
| `GET` | `/api/sources` | Listado de fuentes configuradas |
| `POST` | `/api/sources` | Crear fuente. Si solo se envía `name` + `url`, autodescubre tipo y configuración |
| `GET` | `/api/sources/{id}` | Obtener fuente |
| `PUT` | `/api/sources/{id}` | Actualizar fuente |
| `PATCH` | `/api/sources/{id}/enable` | Activar fuente |
| `PATCH` | `/api/sources/{id}/disable` | Desactivar fuente |
| `DELETE` | `/api/sources/{id}` | Borrar fuente |
| `POST` | `/api/sources/{id}/test` | Probar fuente y devolver muestra |
| `POST` | `/api/sources/{id}/refresh` | Refrescar una fuente |
| `GET` | `/api/searches` | Listado de búsquedas configuradas |
| `POST` | `/api/searches` | Crear búsqueda |
| `GET` | `/api/searches/{id}` | Obtener búsqueda |
| `PUT` | `/api/searches/{id}` | Actualizar búsqueda |
| `PATCH` | `/api/searches/{id}/enable` | Activar búsqueda |
| `PATCH` | `/api/searches/{id}/disable` | Desactivar búsqueda |
| `DELETE` | `/api/searches/{id}` | Borrar búsqueda |

### Ejemplo de respuesta `/api/cfp`

```json
{
  "data": [
    {
      "id": "abc123...",
      "title": "Special Issue: Advances in NLP",
      "source": "Taylor & Francis",
      "journal": "Journal of Computational Linguistics",
      "deadline": "March 31, 2026",
      "description": "We invite submissions on...",
      "url": "https://think.taylorandfrancis.com/special_issues/..."
    }
  ],
  "meta": {
    "total": 583,
    "cached_at": "2025-05-17T10:30:00",
    "statuses": [
      { "source": "Taylor & Francis", "success": true, "count": 583, "error": null },
      { "source": "APA", "success": true, "count": 45, "error": null }
    ]
  }
}
```

## Limitaciones conocidas

### Taylor & Francis
- La página principal de `authorservices.taylorandfrancis.com/call-for-papers/` usa una aplicación React con consent management (Transcend CMP) y Cloudflare Bot Management que impiden el scraping automático de ese frontal. La aplicación accede en su lugar a la **API REST pública** de `think.taylorandfrancis.com` que expone los mismos special issues de forma estructurada.
- La primera carga tarda ~60–90 segundos porque obtiene hasta 60 páginas individuales de forma concurrente para extraer journal names y descripciones.

### APA
- La web de APA está protegida por **Incapsula WAF**. El scraper usa Playwright (Chromium headless) para emular un navegador real y superar el bloqueo.
- Si el sistema detecta el scraping por IP o por fingerprint, el scraper devuelve `success=false` con un mensaje de error claro, pero la aplicación sigue mostrando los datos de T&F.
- Las convocatorias de APA están en su mayor parte como texto en HTML estático; la estructura puede variar si APA rediseña su página.

### General
- **Caché**: Los datos se cachean 1 hora en memoria. Reiniciar el servidor limpia el caché.
- **Fuentes**: Las fuentes se persisten en SQLite. Crear, editar, activar, desactivar o borrar una fuente invalida el caché.
- **Búsquedas**: Las búsquedas se persisten en SQLite. En cada actualización real de CFPs se separan las palabras clave por comas, punto y coma, saltos de línea o espacios si no hay separadores explícitos.
- **Correo**: Si una búsqueda encuentra coincidencias y SMTP no está configurado, la comprobación queda registrada con error pero la actualización de CFPs no falla.
- **Paginación**: El scraper de T&F obtiene hasta 1000 special issues (10 páginas × 100 items). Los detalles completos (journal, descripción) solo se obtienen para los 60 más recientes; el resto usa solo los metadatos de la API.
- **Datos parciales**: Si un campo no está disponible en el HTML/API, se muestra "No disponible".
- **Rate limiting**: Se usan peticiones concurrentes con semáforo (máx. 8 en paralelo) para no sobrecargar las fuentes.

### Scraper HTML genérico
Para fuentes simples, el alta desde el frontal solo pide alias y URL. La aplicación intenta detectar automáticamente selectores habituales. Las fuentes conocidas, como Nature, APA y Taylor & Francis, tienen reglas específicas.

Si hace falta ajustar una fuente manualmente, abrir "Configuración avanzada" en el formulario y editar los selectores CSS:

```json
{
  "item_selector": "article",
  "title_selector": "h2 a",
  "url_selector": "h2 a",
  "journal_selector": ".journal",
  "deadline_selector": ".deadline",
  "description_selector": ".summary"
}
```

Si no se define `item_selector`, el scraper intenta estrategias básicas por listas, encabezados y enlaces.

## Desarrollo

Para ajustar el TTL de caché, en `backend/main.py`:
```python
CACHE_TTL = timedelta(hours=1)
```

Para cambiar cuántos T&F items obtienen detalles completos, en `backend/scrapers/taylor_francis.py`:
```python
_MAX_DETAIL_FETCH = 60   # páginas individuales a scrape con detalle
_CONCURRENCY = 8         # peticiones paralelas
```
