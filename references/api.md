# USTC Qwen-Image-2.1 API Reference

The school gateway exposes two OpenAI-compatible operations for `qwen-image-2.1`. Both were verified against `api.llm.ustc.edu.cn` on 2026-10-31.

## Credentials

The bundled client resolves the bearer token in this order:

1. `USTC_LLM_API_KEY` environment variable, when set.
2. `api_key` in `config.json` beside the skill.

The fixed local key is intentionally stored in `config.json` for this skill. Treat that file as a credential: it is excluded by `.gitignore`, but it must not be shared or published with the skill folder.

## Text-to-image endpoint

```text
POST https://api.llm.ustc.edu.cn/v1/images/generations
Authorization: Bearer <key>
Content-Type: application/json
```

The school's working example uses this shape:

```json
{
  "model": "qwen-image-2.1",
  "prompt": "A blue ceramic cup on a white table, soft studio lighting, simple clean background.",
  "n": 1,
  "size": "1024x1024",
  "extra_body": {
    "response_format": "b64_json"
  }
}
```

Keep `extra_body.response_format` nested for generation. The client defaults generation to `1024x1024`; override it with `--size`.

The optional `--aspect-ratio` argument is a client-side convenience: it maps the prompt rules' `wh_ratio` to a balanced pixel size before sending the request. An explicit `--size` takes precedence and is the correct choice for exact dimensions or high-resolution output.

## Image-edit endpoint

```text
POST https://api.llm.ustc.edu.cn/v1/images/edits
Authorization: Bearer <key>
Content-Type: multipart/form-data
```

Form fields verified with the school gateway:

- `model`: `qwen-image-2.1`
- `prompt`: edit instruction
- `image`: the input file for a single-image edit
- `image[]`: repeated input files for a multi-reference edit
- `n`: requested output count
- `size`: optional `WIDTHxHEIGHT`; omit it to let the service choose from the input canvas
- `response_format`: `b64_json`

For a single image the client sends `image`; for two or more it sends repeated `image[]` parts. Qwen-Image-2.1 supports up to 10 reference images according to its model card.

The edit endpoint does not need the generation endpoint's nested `extra_body` object. Use the top-level `response_format` field shown above.

## Responses

The client accepts the common OpenAI image response forms:

- `data[].b64_json`
- `data[].url`
- a data URL in a Base64 field

The verified school responses may also contain `size`, `output_format`, `usage`, and per-image `revised_prompt` or `provider_specific_fields`. Base64 bytes are decoded locally and the extension is inferred from the image signature. URL responses are downloaded. The client fails rather than writing a non-image payload to disk.

The client writes image files only. It does not create a JSON metadata sidecar; the only JSON it prints is the short command result on stdout. Credentials are never included.

## Error handling

- `400`: request field or parameter rejected; show the API's message.
- `401`/`403`: check `config.json` or an overriding `USTC_LLM_API_KEY`. Do not print the key.
- `404`: verify the base URL includes `/v1` and that the gateway exposes the requested image operation.
- `405` on a non-POST request: the edit endpoint exists and accepts POST.
- `429` or `5xx`: the client retries a bounded number of times. A retry can bill a second generation, so do not increase attempts blindly.
- Response not JSON or no image payload: preserve the response text, redact credentials, and report the failure.

## Capability references

- Model card: https://huggingface.co/Qwen/Qwen-Image-2.1
- Official project README: https://github.com/QwenLM/Qwen-Image-2.1

The model card documents unified generation/editing, local edits via annotations or masks, RGBA edits, and up to 10 reference images. The school gateway contract above is specific to this skill and was tested with the bundled Python client.
