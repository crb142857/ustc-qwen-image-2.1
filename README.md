# USTC Qwen Image

基于中国科学技术大学（USTC）OpenAI 兼容图片网关的 Qwen-Image-2.1 生成与编辑技能。

这个技能把「理解需求、优化提示词、调用远端模型、保存并检查图片」串成一个流程。默认行为是直接生成或编辑图片，而不是只返回一段提示词。

## 主要功能

- **文生图**：根据中文或英文需求生成 Qwen-Image-2.1 图片。
- **图片编辑**：上传一张图片，按指令修改姿势、服装、背景、风格、文字或局部内容。
- **多图参考**：一次提交最多 10 张参考图，用于换装、换背景、人物合成、风格迁移、多图组合等任务。
- **提示词优化**：遵循内置的 Qwen-Image-2.1 文生图与编辑提示词规则，自动补充构图、材质、光线、空间关系和需要保留的内容。
- **尺寸与批量**：支持常用宽高比、精确像素尺寸和 2K 尺寸；单次可请求 1–10 张输出。
- **输出管理**：默认保存到系统配置的下载文件夹，文件名带时间戳，避免覆盖旧图；不再生成 JSON 元数据 sidecar。
- **请求预检**：`--dry-run` 可以查看将要发送的请求，不实际调用 API。
- **提示词-only 模式**：明确要求“只写提示词”时，不调用 API、不生成图片。

## 适用范围

### 适合

- 通过学校 Qwen-Image-2.1 接口进行通用文生图。
- 基于已有图片的编辑、改图、换装、换背景、扩图和多图合成。
- 商品静物、场景概念、海报/信息图、人物写真等需要较强提示词控制的图片。
- 需要在远端完成推理、不想在本机安装 ComfyUI 或下载大模型的场景。
- 需要一次生成多张候选图，或需要精确指定输出尺寸的场景。

### 不适合

- 需要固定 seed、steps、CFG、sampler 等参数并精确复现结果的任务；当前远端接口没有暴露这些参数。
- 需要提交独立 mask 文件进行像素级局部编辑的任务；客户端只发送原图和文字指令，可在图上预先画标注，但没有单独的 mask 表单字段。
- 需要离线运行，或明确要求使用其他图片模型的任务。
- 违反学校服务条款、侵犯隐私或未经授权使用他人肖像的内容。

## 目录结构

```text
ustc-qwen-image/
├─ SKILL.md                 # Codex 技能入口与工作流规则
├─ README.md                # 本文件
├─ config.json              # 本地 API 凭据与可选 output_dir（不要公开）
├─ scripts/
│  └─ generate_image.py     # 文生图 / 图片编辑客户端
├─ references/
│  ├─ t2i_rules.md          # 文生图提示词规则
│  ├─ edit_rules.md         # 编辑与多图提示词规则
│  ├─ cheat_sheet.md        # 词汇和宽高比速查
│  ├─ integration.md        # 提示词到 API 的字段映射
│  └─ api.md                # 接口契约与错误处理
├─ examples/                # 历史示例图与示例记录
└─ agents/openai.yaml       # Codex 展示信息
```

`examples/` 中的 JSON 是早期示例记录；当前客户端运行时不会创建新的元数据文件。

## 依赖

- Python 3.10 或更新版本。
- 校园网
- 有效的 API key，放在 `config.json` 的 `api_key`，或通过 `USTC_LLM_API_KEY` 环境变量提供。
- 只使用 Python 标准库，不需要 GPU、PyTorch、ComfyUI 或额外 `pip` 包。

## 使用方法

以下命令中的 `<skill-dir>` 指本目录。

### 文生图

```powershell
python "<skill-dir>\scripts\generate_image.py" `
  --prompt-file "<workspace>\prompt.txt" `
  --aspect-ratio "3:2" `
  --n 1
```

### 单图编辑

```powershell
python "<skill-dir>\scripts\generate_image.py" `
  --prompt-file "<workspace>\edit-prompt.txt" `
  --image "<workspace>\input.png"
```

### 多图参考

按 `<image1>`、`<image2>` 的顺序重复传入 `--image`：

```powershell
python "<skill-dir>\scripts\generate_image.py" `
  --prompt-file "<workspace>\edit-prompt.txt" `
  --image "<workspace>\image1.png" `
  --image "<workspace>\image2.png"
```

### 只查看请求，不调用 API

```powershell
python "<skill-dir>\scripts\generate_image.py" `
  --prompt "A blue ceramic cup on a pale table" `
  --aspect-ratio "1:1" `
  --dry-run
```

### 指定输出目录

```powershell
python "<skill-dir>\scripts\generate_image.py" `
  --prompt-file "<workspace>\prompt.txt" `
  --out-dir "D:\somewhere"
```

## 输出目录与配置

输出目录按以下优先级解析：

1. 命令行 `--out-dir`
2. 环境变量 `USTC_QWEN_IMAGE_OUT_DIR`
3. `config.json` 中的 `output_dir`
4. 系统配置的下载文件夹

系统下载文件夹的解析方式：

- Windows：Known Folder API；失败时回退到注册表，再回退到 `USERPROFILE` / `HOMEDRIVE` + `HOMEPATH` / `HOME`。
- Linux/macOS 等 POSIX 系统：`XDG_DOWNLOAD_DIR`、`user-dirs.dirs`，最后回退到 `~/Downloads`。

示例 `config.json`（不要把真实 key 提交到公开仓库）：

```json
{
  "api_key": "<your-api-key>",
  "base_url": "https://api.llm.ustc.edu.cn/v1",
  "model": "qwen-image-2.1",
  "output_dir": "D:\\Downloads"
}
```

`output_dir` 是可选的；不配置时使用系统下载文件夹。

## 输出与限制

- 图片保存为 PNG、JPEG、WebP、GIF、BMP 或 AVIF 等接口返回的实际格式，扩展名根据文件签名推断。
- 不生成 `.json` 元数据 sidecar；命令执行完只在本行输出中打印结果摘要。
- 远端接口不提供 seed、steps、CFG、sampler、negative prompt 或 LoRA 参数，因此不能保证与本地 ComfyUI 结果一致，也不能保证重复请求得到完全相同的图片。
- 编辑接口没有独立 mask 字段；需要局部修改时，可以在输入图上画圈、箭头或涂色标注，再配合文字指令提交。
- 遇到 `401`/`403` 检查凭据；遇到 `400` 检查尺寸、图片数量或提示词字段；`429`/`5xx` 会有限重试，重试可能产生额外调用。
- 使用学校服务前请确认内容符合服务条款，并避免上传敏感或未经授权的个人图像。

## 相关文件

- 完整工作流与提示词规则：`SKILL.md`
- 接口细节：`references/api.md`
- 提示词到 API 的字段映射：`references/integration.md`
- 客户端实现：`scripts/generate_image.py`

## 致谢

- 感谢中科大词元计划对本项目的支持。
- 感谢 [qwen-image-2-skill](https://github.com/iamyoki/qwen-image-2.1-skill)，本项目参考了该技能。
