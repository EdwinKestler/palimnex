# GitHub Pages site

The Palimnex project site is a dependency-free static page at `docs/index.html`.
It uses repository-local CSS and the existing documentation; it makes no model,
analytics, font, CDN, or database request. The page describes source discovery,
durable memory, authorized erasure, the replicable audit graph, and the optional
Semantica projection extra.

## Local preview

From the repository root:

```bash
python3 -m http.server 8080 --directory docs
```

Then open `http://127.0.0.1:8080/`. Stop the server with `Ctrl-C`.

## GitHub Pages activation

Publishing is separate from building the site and requires explicit authority.
The preferred deployment path is the repository's static Pages workflow:

1. Ensure the checkout includes `.github/workflows/jekyll-gh-pages.yml`.
2. Keep its artifact upload path set to `./docs`.
3. In **Settings → Pages**, select **GitHub Actions** as the source.
4. Commit and push the reviewed site and workflow together.
5. Wait for the workflow deployment job to report the live URL.

An authorized maintainer may instead choose branch publishing from `main` and
`/docs`; do not enable both deployment paths at the same time.

The expected project URL is `https://edwinkestler.github.io/palimnex/`. Treat it
as live only after GitHub reports a successful deployment and the rendered page
is checked directly.

## Deployment boundary

- The static page is not a Palimnex runtime dependency.
- Publishing does not initialize Redis or the durable ledger.
- The page contains no credential, key, pack, database, or live runtime state.
- A local preview or committed source tree is not evidence of a live deployment.
