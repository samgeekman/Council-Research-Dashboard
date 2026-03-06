# Council Research (GitHub Pages Bundle)

This `docs/` folder is ready for GitHub Pages publishing.

## Publish Steps

1. Push this repository to GitHub.
2. In GitHub: `Settings` -> `Pages`.
3. Under **Build and deployment**:
   - **Source**: `Deploy from a branch`
   - **Branch**: your branch (for example `main`)
   - **Folder**: `/docs`
4. Save and wait for Pages to publish.

The site entrypoint is `docs/index.html`.

## Included Runtime Files

- `index.html`
- `council_research_database.js`
- `boundaries/index.json`
- `boundaries/*.geojson`
- `.nojekyll`

## Local Preview

From repository root:

```bash
python3 -m http.server 8000
```

Open: `http://localhost:8000/docs/`
