# CDS Soberanos — Panel SoyRGB

Panel público de Credit Default Swaps soberanos a 5 años. Se actualiza solo
mediante GitHub Actions y se publica gratis con GitHub Pages.

## Qué hace cada pieza

| Archivo | Rol |
|---|---|
| `fetch_sovereign_cds.py` | Baja los datos (POST al endpoint de worldgovernmentbonds) y escribe `sovereign_cds.json` + `.csv` |
| `.github/workflows/update-cds.yml` | Corre el fetcher en automático (cron diario L-V) y commitea el JSON |
| `index.html` | El panel. Lee `sovereign_cds.json` del mismo dominio; si falla, usa un snapshot embebido |
| `sovereign_cds.json` | El dato vivo. Lo regenera el workflow |

## Puesta en marcha (una vez, ~5 min)

1. **Crea un repo** en tu cuenta/organización (ej. `rafargb-tech/cds-panel`) y sube estos archivos.
2. **Actions → Enable** si te lo pide. En **Settings → Actions → General → Workflow permissions**, marca **Read and write permissions** (para que el bot pueda commitear el JSON).
3. **Settings → Pages → Build and deployment → Deploy from a branch → `main` / `(root)`**. En ~1 min tendrás la URL: `https://<usuario>.github.io/cds-panel/`.
4. **Actions → Update sovereign CDS → Run workflow** para lanzarlo a mano la primera vez. A partir de ahí corre solo cada día hábil.

## Publicar en Substack

Substack **no** permite incrustar HTML/iframe. Dos opciones:
- Pega el **link** a la URL de Pages en tu post o en la sección "About".
- Sube un **screenshot** del panel y enlázalo abajo.

## Notas honestas

- El cron de GitHub **puede retrasarse** unos minutos; para datos de cierre da igual.
- GitHub **desactiva** workflows programados tras ~60 días sin actividad en el repo; un commit cualquiera lo reactiva.
- La fuente es un **agregador** (worldgovernmentbonds), no origen. Válido para divulgación; revisa sus términos antes de monetizar directamente encima.
- Solo cubre **soberanos**. Single-names e índices (CDX/iTraxx) salen del tape del DTCC — es otro pipeline.

## Correr en local

```bash
pip install requests
python3 fetch_sovereign_cds.py     # genera el JSON
python3 -m http.server 8000        # abre http://localhost:8000
```
