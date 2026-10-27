# Pull request

## Tier

- [ ] Solo (CLI / local store / scoring / judge)
- [ ] Team (Supabase schema / web app / smoke)

## Checklist

- [ ] Synthetic data only — no real comments, usernames or media
- [ ] `ruff check persocial tests scripts evals examples` passes
- [ ] Pure tests pass (`pytest -m "not db"`); DB tests pass if schema touched
- [ ] `npm run build` passes if `web/` touched
- [ ] Docs updated if a command, format or setting changed
