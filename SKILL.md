---
name: ustc-qwen-image
description: Turn image briefs into optimized Qwen-Image-2.1 prompts and generate or edit images through USTC's remote OpenAI-compatible endpoint. Use when the user requests Qwen-Image-2.1, the school image model, image creation or editing through ustc-qwen-image, or Chinese requests such as 用学校模型生成图片, 千问2.1出图, 改图, 多图合成. The default behavior is to optimize the prompt internally and execute the API call, not to hand back a prompt. Do not use for deterministic SVG, HTML, or canvas assets, or when a different image model is explicitly required.
---

# USTC Qwen Image

Provide one end-to-end workflow: interpret the brief, write the strongest Qwen-Image-2.1 prompt, call the university endpoint with Python, verify the result, and deliver the image.

**Default behavior:** optimize the prompt and generate the image. Do not stop after producing a prompt unless the user explicitly asks for prompt-only output.

## Routing

1. If the user supplies or references one or more images to modify, reuse, or composite, use **edit mode**.
2. Otherwise use **generation mode**.
3. If the user explicitly asks for only a prompt, a prompt rewrite, or prompt-only API JSON, do not call the API. Follow the prompt-only instructions below.
4. Do not substitute the built-in `image_gen` tool or a different model when this skill applies. Use the bundled USTC client.

Read the relevant references before writing the prompt:

- Generation: `references/t2i_rules.md`
- Editing or compositing: `references/edit_rules.md`
- Vocabulary and aspect-ratio examples: `references/cheat_sheet.md`
- Prompt-to-API handoff and size mapping: `references/integration.md`
- Endpoint contract and errors: `references/api.md`

## End-to-end workflow

1. **Inspect inputs.** In edit mode, use an available vision tool to inspect every source image before rewriting the instruction. Note identity, pose, products, text, layout, canvas, and regions the user marked.
2. **Build the internal prompt spec.** Apply the appropriate reference rules in full. Do not show the internal reasoning or JSON in normal interactive use.
   - Generation: `{"rewritten_prompt": "...", "wh_ratio": "3:2"}`
   - Edit: `{"rewritten_prompt": "...", "wh_ratio": "", "ratio_follow": "<image1>"}`
3. **Preserve intent.** Keep user-fixed objects, counts, text, positions, colors, identities, and invariants. For edits, apply named changes strongly while locking everything untargeted.
4. **Choose the canvas.**
   - A T2I `wh_ratio` becomes `--aspect-ratio`.
   - An edit `wh_ratio` becomes `--aspect-ratio`; an edit `ratio_follow` means omit both size flags.
   - If the user gave exact pixel dimensions, pass them unchanged with `--size` instead.
5. **Write the prompt to a UTF-8 file.** Long prompts should never be forced through fragile shell quoting. Put the file under the workspace, for example `tmp/qwen-image/prompt.txt`.
6. **Execute the client.** Pass every input image with a separate `--image` flag, in the same order as `<image1>`, `<image2>`, and so on. Images are saved to the system-configured Downloads folder by default; add `--out-dir` only when the user names another folder.
7. **Verify the actual image.** Check that the API returned a valid image, open it, and compare it with the brief. For edits, compare the result with the inputs and check identity, geometry, text, and preserved regions. If one aspect fails, change only that part of the prompt and retry deliberately.
8. **Deliver.** Show the image inline, give absolute output paths, and state the mode, model, dimensions, and any material caveat. Do not paste the full internal prompt unless the user asks for it.

## Commands

Generation after prompt optimization:

```powershell
python "<skill-dir>\scripts\generate_image.py" `
  --prompt-file "<workspace>\tmp\qwen-image\prompt.txt" `
  --aspect-ratio "3:2" `
  --n 1
```

Single-image edit after prompt optimization:

```powershell
python "<skill-dir>\scripts\generate_image.py" `
  --prompt-file "<workspace>\tmp\qwen-image\prompt.txt" `
  --image "<workspace>\input.png"
```

Multi-reference edit: repeat `--image` in prompt order. Omit `--size` and `--aspect-ratio` when the edit rules specify `ratio_follow`.

By default, generated images are written to the system-configured Downloads folder. The client resolves the output directory in this order: `--out-dir`, the `USTC_QWEN_IMAGE_OUT_DIR` environment variable, an `output_dir` string in `config.json`, then the platform default. On Windows the platform default comes from the Known Folder API, with registry and `USERPROFILE`/`HOMEDRIVE`/`HOMEPATH` fallbacks; on POSIX it checks `XDG_DOWNLOAD_DIR`, `user-dirs.dirs`, then `~/Downloads`.

The client reads the fixed API key from `config.json`; `USTC_LLM_API_KEY` can override it. Never print the key. `--dry-run` previews the sanitized request without spending a generation.

## Prompt construction rules

- **T2I prose:** always English. Write one dense paragraph of roughly 400–500 words, using an observer's present-tense description. Use 8–14 spatial anchors, concrete materials, explicit lighting, exact quoted in-image text, and a final composition summary. Put aspect ratio only in `wh_ratio`, never in the prose.
- **Edit prose language:** Chinese when the user's instruction is Chinese; English when it is English or any other language.
- **Rendered text language:** prioritize exact user text, then the dominant language of existing text in the input image, then the user's instruction language. Keep each quoted string monolingual.
- **Image tags:** for one input image, refer naturally to "the image"; for two or more, use `<image1>`, `<image2>`, and so on and state each role.
- **Editing strength:** push the named edit to an unmistakable degree; preserve untargeted content without over-describing it into a redraw.
- **No quality filler:** avoid "masterpiece", "8K", "best quality", and similar empty boosters.

Local edits can be guided by circles, arrows, or painted annotations drawn onto a copy of the input image. The current client sends image files plus the prompt; it does not expose a separate mask form field.

## Prompt-only mode

Only when the user explicitly requests prompt-only output:

- Do not call the API or create an image.
- Keep the same routing and prompt rules.
- For an interactive response, provide the prompt plus a concise explanation of ratio/dimensions and key decisions.
- If the user asks for JSON/API format, return only the single-line prompt spec with `rewritten_prompt` and the applicable `wh_ratio`/`ratio_follow` fields.

## Credentials, output, and failures

- The skill's `config.json` contains a local credential. Do not share or publish that file. `.gitignore` excludes it.
- Successful runs create versioned image files only; no JSON metadata sidecar is written.
- Never report success without verifying the saved image. If the API fails, preserve the sanitized error, do not fabricate output, and do not delete the user's source images.
- `401`/`403`: check `config.json` or an overriding `USTC_LLM_API_KEY`.
- `400`: inspect the API message for an unsupported size, count, image field, or prompt field.
