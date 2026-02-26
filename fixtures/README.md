# Fixtures

Drop sample `userPrompt` inputs here so you can iterate on prompt outputs quickly from your computer.

Suggested structure:

- `fixtures/<appId>/opener/`
- `fixtures/<appId>/app_chat/`
- `fixtures/<appId>/reg_chat/`

Legacy layout is also supported by the CLI (for backwards compatibility):

- `fixtures/opener/`
- `fixtures/app_chat/`
- `fixtures/reg_chat/`

## Fixture formats

### `.txt` fixtures (legacy / still supported)
Each fixture can be a plain `.txt` file containing the exact text you want sent as the **user** message.

### `.json` fixtures (structured)
If your prompt file defines per-mode user templates (e.g. `prompts.openerUser`), you can use `.json` fixtures to provide variables for template rendering.

Common fields:
- `tie_in` (string, optional)
- `profile_text` (string, opener mode)
- `chat_transcript` (string, app_chat/reg_chat modes)

Optional override:
- `user_prompt` (string): if provided, this is sent as the **user** message verbatim.

Examples

Opener (`fixtures/rizzchatai/opener/example_01.json`):

```json
{
	"profile_text": "Name: Sam\nBio: Love hiking and sushi.",
	"tie_in": "their hiking photos"
}
```

App chat (`fixtures/rizzchatai/app_chat/example_01.json`):

```json
{
	"chat_transcript": "Her: how was your weekend?\nMe: pretty chill. you?",
	"tie_in": "ask about her favorite plan"
}
```

