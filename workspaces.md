# Hack on workspaces

1. Build docker image
```shell
cd ./packages/sandbox/src/lib/
docker build -t sandbox-test .
```
2. Run UI
```shell
pnpm i
pnpm run dev
```
3. Run nanobot with workspaces yaml
```shell
make
./bin/nanobot run ./workspaces.yaml
```
4. Open http://localhost:8080/workspace-test
