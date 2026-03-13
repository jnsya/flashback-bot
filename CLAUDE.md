# Flashback Bot

Read `README.md` for project structure, configuration, env vars, and deployment commands.

## Deployment (Railway)

This project is deployed on Railway with a persistent volume mounted at `/data`.

When debugging deployment issues, use the Railway CLI to inspect the live environment:

```bash
railway status                    # check linked project/service
railway variables                 # list env vars
railway ssh ls /data/             # list files on the volume
railway ssh <command>             # run any command in the deployed container
railway logs                      # view recent logs
```

The app directory on Railway is `/app/`. Content lives on the volume at `/data/`.
A common gotcha: the bot discovers folders from `DATA_DIR`, not from hardcoded paths — if files exist on the volume but the bot can't see them, check that `DATA_DIR` is set correctly.
