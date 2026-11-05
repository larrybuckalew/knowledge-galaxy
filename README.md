# Knowledge Galaxy

A 3D note graph you can talk to, and a butler who can telephone you.

Two apps, one corpus of notes:

| Where | Port | What it is |
|---|---|---|
| root | `:4703` | **Jarvis** — voice in and out, guarded PC control, and a telephone (Retell) that rings your cell with the day's brief |
| `galaxy/` | `:4700` | **The brain** — a registry of 52 model routes, retrieval that proves which note an answer came from, and a chip that names the route that actually answered |

Both read the same 28 notes. Both keep their keys in a gitignored `config.json`; a clone with no key says so plainly rather than pretending to work.

## Run

```powershell
# Jarvis
python build.py
python server.py            # http://127.0.0.1:4703

# The brain
cd galaxy
python build.py
python server.py            # http://127.0.0.1:4700
```

## Keys

Neither app will talk to you without a key, and neither will invent one. Write your own into `config.json` (root) or `galaxy/config.json` (the brain):

```json
{
  "model": "free/glm-5.3",
  "anthropic_api_key": "...",
  "openrouter_api_key": "...",
  "nvidia_api_key": "...",
  "vercel_api_key": "..."
}
```

For the brain, `vercel` needs a credit card on file before it serves anything, and every route that cannot answer is refused with its reason rather than offered as though it worked.

## The telephone

Jarvis can ring you. Retell is the provider, and it needs three things in `config.json`:

```json
"telephony": { "api_key": "retell_...", "from": "+1 your Retell number", "callback": "+1 your cell" }
```

then

```powershell
python setup_phone.py        # creates the agent; safe to run twice
python setup_phone.py --dry  # shows what it would do and touches nothing
```

and say **"call me"**. The agent is handed the headline and the notes in the prompt itself, so it can only ever answer from what it was given. The call is watched by polling — never a webhook, because a webhook is a door anyone on the internet can knock on, and a forged "call ended" would put a lie on the desk. When the call ends, one spoken line is left on the desk.

## Tests

```powershell
python galaxy/brain_test.py       # registry, resolver, and the refusals
python galaxy/retrieval_test.py   # retrieval names one source, never a guess
python phone_test.py              # the telephone, against a stubbed Retell
```
