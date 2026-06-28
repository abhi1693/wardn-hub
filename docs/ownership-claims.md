# Wardn ownership claims

Wardn Hub can verify a server owner through a `wardn.json` file in the linked
GitHub repository or at the root of the server website. This proves the Wardn
user can write to the upstream source or official site, which is stronger than a
registry submission alone.

Place `wardn.json` at the repository root, or at `https://example.com/wardn.json`
for website ownership verification:

```json
{
  "$schema": "https://wardn.ai/schemas/wardn.json",
  "servers": {
    "io.github.example/weather": {
      "owners": [
        {
          "userId": "00000000-0000-0000-0000-000000000000"
        }
      ]
    }
  }
}
```

The `userId` value is the signed-in Wardn user UUID generated into the Score tab
claim template. Wardn does not require exposing email addresses for this flow.

Supported shapes:

- `owners`: repo-wide owners.
- `ownerUserIds`: repo-wide UUID strings.
- `servers["server/name"].owners`: server-specific owners.
- `mcpServers["server/name"].owners`: server-specific owners.

Claim verification fetches only `wardn.json` from the linked GitHub repository
or the server website root. Website-root fetches reject private and link-local
hosts and validate redirect targets before following them. If the manifest lists
the signed-in Wardn user's UUID, Wardn records verified ownership for the server
and matching active versions from that source.
