# Integrated Prompt-to-API Workflow

This skill joins two stages that normally require separate tools:

1. Qwen-Image-2.1 prompt construction from `t2i_rules.md` or `edit_rules.md`.
2. Remote generation/editing through the USTC Python client.

The prompt references are copied from the user's `qwen-image-2-1-prompter` skill. Treat them as the prompt authority; this file only defines how their JSON output becomes a real API request.

## Internal spec shape

Generation:

```json
{"rewritten_prompt": "<one dense English paragraph>", "wh_ratio": "3:2"}
```

Edit:

```json
{"rewritten_prompt": "<edit instruction>", "wh_ratio": "", "ratio_follow": "<image1>"}
```

Do not show this JSON to an ordinary interactive user. It is an internal handoff. The client does not persist the prompt in a metadata sidecar.

## Field-to-CLI mapping

| Prompt rule output | Client argument |
|---|---|
| `rewritten_prompt` | UTF-8 file passed via `--prompt-file` |
| `wh_ratio` (generation or edit) | `--aspect-ratio "<ratio>"` |
| `ratio_follow` (edit) | omit both `--size` and `--aspect-ratio` |
| User-supplied exact dimensions | `--size WIDTHxHEIGHT` |
| Input images in order | repeated `--image` flags in the same order |

If both `wh_ratio` and `ratio_follow` are unexpectedly populated, treat the prompt spec as invalid and resolve it before calling the API.

## Aspect ratio mapping

The client maps common Qwen ratios to balanced preview/final sizes:

| Ratio | Size | Ratio | Size |
|---|---|---|---|
| 1:1 | 1024x1024 | 21:9 | 1680x720 |
| 3:2 | 1536x1024 | 9:21 | 720x1680 |
| 2:3 | 1024x1536 | 4:5 | 1024x1280 |
| 4:3 | 1280x960 | 5:4 | 1280x1024 |
| 3:4 | 960x1280 | 5:7 | 800x1120 |
| 16:9 | 1536x864 | 7:5 | 1120x800 |
| 9:16 | 864x1536 | 9:5 | 1440x800 |
| 2:1 | 1440x720 | 7:3 | 1680x720 |
| 1:2 | 720x1440 | 18:39 | 720x1560 |
| 3:1 | 1536x512 | 9:20 | 720x1600 |
| 1:3 | 512x1536 | | |

If the user explicitly asks for high-resolution output, pass exact Qwen-Image-2.1 2K dimensions with `--size` instead:

- 1:1: 2048x2048
- 4:3: 2400x1792
- 3:4: 1792x2400
- 3:2: 2528x1696
- 2:3: 1696x2528
- 16:9: 2752x1536
- 9:16: 1536x2752

An unsupported ratio or exact pixel request should use `--size`, not a ratio approximation that changes the user's intent.

## Execution sequence

1. Inspect all input images in edit mode.
2. Produce the internal prompt spec.
3. Write only `rewritten_prompt` to a UTF-8 file under the workspace, such as `tmp/qwen-image/prompt.txt`.
4. Call the Python client:

```powershell
python "<skill-dir>\scripts\generate_image.py" `
  --prompt-file "<workspace>\tmp\qwen-image\prompt.txt" `
  --aspect-ratio "3:2"
```

For edits, add one `--image` per reference file and preserve text-tag order. Use `--aspect-ratio` only when the prompt spec has `wh_ratio`; omit size flags when it has `ratio_follow`.

Images are saved to the system-configured Downloads folder by default. The output directory resolution order is `--out-dir`, `USTC_QWEN_IMAGE_OUT_DIR`, `output_dir` in `config.json`, then the platform Downloads location (Windows Known Folder/registry, or POSIX XDG, then `~/Downloads`). Add `--out-dir <path>` only when a different destination is requested.

5. Read the client's stdout JSON, inspect the saved image, and compare it with the source and original brief.
6. If a targeted correction is needed, rewrite only the affected sentence or constraint and rerun. Avoid blind repeat calls.

## Final response

In image-generation mode, the deliverable is the image and its output path, not the internal prompt. Include the optimized prompt only on request, and never expose credentials or raw authorization headers.
