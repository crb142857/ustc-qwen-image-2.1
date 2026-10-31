#!/usr/bin/env python3
"""Generate or edit images with USTC's Qwen-Image-2.1 endpoint.

The client uses only the Python standard library. It resolves credentials in
this order: USTC_LLM_API_KEY, then config.json beside the skill.
"""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import re
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any


def _clean_path_value(value: str | None) -> str:
    if not value:
        return ""
    return os.path.expandvars(value.strip()).strip().strip('"')


def _windows_known_folder_downloads() -> Path | None:
    """Return the Windows Downloads known-folder path, if available."""
    try:
        import ctypes
        from ctypes import wintypes

        class GUID(ctypes.Structure):
            _fields_ = [
                ("Data1", wintypes.DWORD),
                ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD),
                ("Data4", ctypes.c_ubyte * 8),
            ]

        # FOLDERID_Downloads = {374DE290-123F-4565-9164-39C4925E467B}
        folder_id = GUID(
            0x374DE290,
            0x123F,
            0x4565,
            (ctypes.c_ubyte * 8)(0x91, 0x64, 0x39, 0xC4, 0x92, 0x5E, 0x46, 0x7B),
        )
        path_ptr = ctypes.c_wchar_p()
        shell32 = ctypes.windll.shell32
        shell32.SHGetKnownFolderPath.argtypes = [
            ctypes.POINTER(GUID),
            wintypes.DWORD,
            wintypes.HANDLE,
            ctypes.POINTER(ctypes.c_wchar_p),
        ]
        shell32.SHGetKnownFolderPath.restype = ctypes.c_long
        # KF_FLAG_DONT_VERIFY: return the configured path even before it exists.
        result = shell32.SHGetKnownFolderPath(
            ctypes.byref(folder_id), 0x00004000, None, ctypes.byref(path_ptr)
        )
        if result != 0 or not path_ptr.value:
            return None
        try:
            return Path(path_ptr.value)
        finally:
            ole32 = ctypes.windll.ole32
            ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
            ole32.CoTaskMemFree(ctypes.cast(path_ptr, ctypes.c_void_p))
    except Exception:
        return None


def _windows_registry_downloads() -> Path | None:
    """Read the per-user Downloads location Windows stores in the registry."""
    try:
        import winreg

        value_name = "{374DE290-123F-4565-9164-39C4925E467B}"
        key_paths = (
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders",
        )
        for key_path in key_paths:
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                    value, _ = winreg.QueryValueEx(key, value_name)
            except OSError:
                continue
            cleaned = _clean_path_value(str(value))
            if cleaned:
                return Path(cleaned)
    except Exception:
        return None
    return None


def _windows_downloads_dir() -> Path | None:
    for candidate in (
        _windows_known_folder_downloads(),
        _windows_registry_downloads(),
    ):
        if candidate:
            return candidate

    for env_name in ("USERPROFILE", "HOME"):
        home = _clean_path_value(os.environ.get(env_name))
        if home:
            return Path(home) / "Downloads"

    drive = _clean_path_value(os.environ.get("HOMEDRIVE"))
    home_path = _clean_path_value(os.environ.get("HOMEPATH"))
    if drive or home_path:
        return Path(drive + home_path) / "Downloads"
    return None


def _posix_downloads_dir() -> Path | None:
    direct = _clean_path_value(os.environ.get("XDG_DOWNLOAD_DIR"))
    if direct:
        return Path(direct).expanduser()

    config_home = _clean_path_value(os.environ.get("XDG_CONFIG_HOME"))
    config_dir = Path(config_home) if config_home else Path.home() / ".config"
    config_file = config_dir / "user-dirs.dirs"
    try:
        for line in config_file.read_text(encoding="utf-8", errors="replace").splitlines():
            stripped = line.strip()
            if not stripped.startswith("XDG_DOWNLOAD_DIR="):
                continue
            value = stripped.split("=", 1)[1].strip().strip('"')
            cleaned = _clean_path_value(value)
            if cleaned:
                return Path(cleaned).expanduser()
    except OSError:
        pass
    return Path.home() / "Downloads"


def _default_downloads_dir() -> Path:
    resolved = _windows_downloads_dir() if os.name == "nt" else _posix_downloads_dir()
    return resolved or (Path.home() / "Downloads")


SKILL_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = SKILL_ROOT / "config.json"
DEFAULT_BASE_URL = "https://api.llm.ustc.edu.cn/v1"
DEFAULT_MODEL = "qwen-image-2.1"
DEFAULT_SIZE = "1024x1024"
DEFAULT_OUT_DIR = str(_default_downloads_dir())
DEFAULT_TIMEOUT = 180.0
DEFAULT_MAX_ATTEMPTS = 3
API_KEY_ENV = "USTC_LLM_API_KEY"
OUTPUT_DIR_ENV = "USTC_QWEN_IMAGE_OUT_DIR"
MAX_EDIT_IMAGES = 10
MAX_ERROR_CHARS = 2400

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
JPEG_SIGNATURE = b"\xff\xd8\xff"
GIF_SIGNATURES = (b"GIF87a", b"GIF89a")
BMP_SIGNATURE = b"BM"

ASPECT_RATIO_SIZES = {
    "1:1": "1024x1024",
    "4:3": "1280x960",
    "3:4": "960x1280",
    "3:2": "1536x1024",
    "2:3": "1024x1536",
    "16:9": "1536x864",
    "9:16": "864x1536",
    "2:1": "1440x720",
    "1:2": "720x1440",
    "3:1": "1536x512",
    "1:3": "512x1536",
    "21:9": "1680x720",
    "9:21": "720x1680",
    "4:5": "1024x1280",
    "5:4": "1280x1024",
    "5:7": "800x1120",
    "7:5": "1120x800",
    "9:5": "1440x800",
    "7:3": "1680x720",
    "18:39": "720x1560",
    "9:20": "720x1600",
}


def _die(message: str, code: int = 1) -> None:
    print(f"Error: {message}", file=sys.stderr)
    raise SystemExit(code)


def _warn(message: str) -> None:
    print(f"Warning: {message}", file=sys.stderr)


def _read_prompt(prompt: str | None, prompt_file: str | None) -> str:
    if prompt and prompt_file:
        _die("Use --prompt or --prompt-file, not both.")
    if prompt_file:
        path = Path(prompt_file).expanduser()
        if not path.is_file():
            _die(f"Prompt file not found: {path}")
        value = path.read_text(encoding="utf-8-sig").strip()
    elif prompt:
        value = prompt.strip()
    else:
        _die("Missing prompt. Use --prompt or --prompt-file.")

    if not value:
        _die("The prompt is empty.")
    return value


def _load_config(config_path: str | None) -> dict[str, Any]:
    path = (
        Path(config_path).expanduser().resolve()
        if config_path
        else DEFAULT_CONFIG_PATH
    )
    if not path.is_file():
        if config_path:
            _die(f"Config file not found: {path}")
        return {}
    try:
        config = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        _die(f"Could not read config file {path}: {exc}")
    if not isinstance(config, dict):
        _die(f"Config file {path} must contain a JSON object.")
    return config


def _config_string(config: dict[str, Any], key: str) -> str | None:
    value = config.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        _die(f"Config key '{key}' must be a non-empty string.")
    return value.strip()


def _resolve_out_dir(args: argparse.Namespace, config: dict[str, Any]) -> str:
    if args.out_dir:
        return args.out_dir

    env_out_dir = _clean_path_value(os.environ.get(OUTPUT_DIR_ENV))
    if env_out_dir:
        return env_out_dir

    config_out_dir = _clean_path_value(_config_string(config, "output_dir"))
    if config_out_dir:
        return config_out_dir

    return DEFAULT_OUT_DIR


def _resolve_api_key(config: dict[str, Any]) -> str:
    api_key = os.getenv(API_KEY_ENV, "").strip() or _config_string(
        config, "api_key"
    )
    if not api_key:
        _die(
            f"No API key found. Set {API_KEY_ENV} or add 'api_key' to "
            f"{DEFAULT_CONFIG_PATH}."
        )
    return api_key


def _validate_size(size: str) -> str:
    value = size.strip().lower().replace("×", "x")
    match = re.fullmatch(r"([1-9][0-9]*)x([1-9][0-9]*)", value)
    if not match:
        _die("--size must be WIDTHxHEIGHT, for example 1024x1024.")
    return f"{int(match.group(1))}x{int(match.group(2))}"


def _size_from_ratio(ratio: str) -> str:
    normalized = ratio.strip().replace(" ", "").replace("：", ":")
    if normalized in ASPECT_RATIO_SIZES:
        return ASPECT_RATIO_SIZES[normalized]
    supported = ", ".join(ASPECT_RATIO_SIZES)
    _die(
        f"Unsupported --aspect-ratio '{ratio}'. Use one of {supported}, "
        "or pass an explicit --size WIDTHxHEIGHT."
    )


def _normalize_base_url(value: str) -> str:
    normalized = value.strip().rstrip("/")
    if not normalized.startswith(("https://", "http://")):
        _die("--base-url must start with http:// or https://.")
    return normalized


def _api_endpoint(base_url: str, operation: str) -> str:
    return f"{base_url}/images/{operation}"


def _validate_edit_images(raw_paths: list[str]) -> list[Path]:
    if len(raw_paths) > MAX_EDIT_IMAGES:
        _die(f"Qwen-Image-2.1 supports at most {MAX_EDIT_IMAGES} input images.")
    resolved: list[Path] = []
    for raw in raw_paths:
        path = Path(raw).expanduser().resolve()
        if not path.is_file():
            _die(f"Input image not found: {path}")
        resolved.append(path)
    return resolved


def _content_type(path: Path) -> str:
    media_type = mimetypes.guess_type(path.name)[0]
    if media_type and media_type.startswith("image/"):
        return media_type
    return "application/octet-stream"


def _encode_multipart(
    fields: list[tuple[str, str]], files: list[tuple[str, Path]]
) -> tuple[bytes, str]:
    boundary = f"----ustc-qwen-image-{uuid.uuid4().hex}"
    body = bytearray()

    for name, value in fields:
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8")
        )
        body.extend(value.encode("utf-8"))
        body.extend(b"\r\n")

    for field_name, path in files:
        safe_name = path.name.replace('"', "'").replace("\r", " ").replace("\n", " ")
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(
            (
                f'Content-Disposition: form-data; name="{field_name}"; '
                f'filename="{safe_name}"\r\n'
            ).encode("utf-8")
        )
        body.extend(f"Content-Type: {_content_type(path)}\r\n\r\n".encode("utf-8"))
        body.extend(path.read_bytes())
        body.extend(b"\r\n")

    body.extend(f"--{boundary}--\r\n".encode("utf-8"))
    return bytes(body), f"multipart/form-data; boundary={boundary}"


def _scrub_secret(text: str, secret: str) -> str:
    if not text:
        return text
    if secret:
        text = text.replace(secret, "[REDACTED]")
    return text[:MAX_ERROR_CHARS]


def _post_json_bytes(
    endpoint: str,
    api_key: str,
    request_body: bytes,
    content_type: str,
    timeout: float,
    max_attempts: int,
) -> dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": content_type,
        "Accept": "application/json",
        "User-Agent": "ustc-qwen-image/1.1",
    }

    for attempt in range(1, max_attempts + 1):
        request = urllib.request.Request(
            endpoint,
            data=request_body,
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            body = ""
            try:
                body = exc.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            message = _scrub_secret(body, api_key)
            if exc.code in {429, 500, 502, 503, 504} and attempt < max_attempts:
                delay = min(2 ** (attempt - 1), 8)
                _warn(
                    f"HTTP {exc.code}; retrying in {delay}s "
                    f"({attempt}/{max_attempts})."
                )
                time.sleep(delay)
                continue
            hint = ""
            if exc.code in {401, 403}:
                hint = " Check config.json and USTC_LLM_API_KEY."
            elif exc.code == 404:
                hint = " Check that --base-url includes /v1."
            detail = f" Response: {message}" if message else ""
            _die(f"HTTP {exc.code} from the image endpoint.{hint}{detail}")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            if attempt < max_attempts:
                delay = min(2 ** (attempt - 1), 8)
                _warn(
                    f"Request failed ({exc}); retrying in {delay}s "
                    f"({attempt}/{max_attempts})."
                )
                time.sleep(delay)
                continue
            _die(f"Request failed after {max_attempts} attempts: {exc}")

        if not raw:
            _die("The API returned an empty response.")
        try:
            decoded = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            preview = _scrub_secret(raw.decode("utf-8", errors="replace"), api_key)
            _die(f"The API response was not JSON ({exc}). Response: {preview}")
        if not isinstance(decoded, dict):
            _die("The API response JSON is not an object.")
        return decoded

    _die("The request exhausted all attempts.")
    return {}


def _request_generation(
    endpoint: str,
    api_key: str,
    payload: dict[str, Any],
    timeout: float,
    max_attempts: int,
) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return _post_json_bytes(
        endpoint, api_key, body, "application/json", timeout, max_attempts
    )


def _request_edit(
    endpoint: str,
    api_key: str,
    fields: list[tuple[str, str]],
    images: list[Path],
    timeout: float,
    max_attempts: int,
) -> dict[str, Any]:
    image_field = "image" if len(images) == 1 else "image[]"
    files = [(image_field, path) for path in images]
    body, content_type = _encode_multipart(fields, files)
    return _post_json_bytes(
        endpoint, api_key, body, content_type, timeout, max_attempts
    )


def _response_items(response: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[Any] = []
    for key in ("data", "images"):
        value = response.get(key)
        if isinstance(value, list):
            candidates = value
            break

    if not candidates:
        output = response.get("output")
        if isinstance(output, dict) and isinstance(output.get("results"), list):
            candidates = output["results"]

    if not candidates:
        if response.get("b64_json") or response.get("url"):
            candidates = [response]

    items: list[dict[str, Any]] = []
    for candidate in candidates:
        if isinstance(candidate, str):
            items.append({"b64_json": candidate})
        elif isinstance(candidate, dict):
            items.append(candidate)

    if not items:
        message = response.get("message") or response.get("error")
        if message:
            _die(f"The API returned no image payload: {message}")
        _die("The API returned no image payload in a recognized response shape.")
    return items


def _decode_base64(value: str) -> bytes:
    encoded = value.strip()
    if encoded.startswith("data:"):
        if "," not in encoded:
            _die("The API returned a malformed data URL.")
        encoded = encoded.split(",", 1)[1]
    try:
        data = base64.b64decode(encoded, validate=False)
    except (ValueError, TypeError) as exc:
        _die(f"Could not decode the Base64 image: {exc}")
    if not data:
        _die("The decoded image is empty.")
    return data


def _download_image(url: str, timeout: float) -> bytes:
    if url.startswith("data:"):
        return _decode_base64(url)
    if not url.startswith(("https://", "http://")):
        _die("The API returned an unsupported image URL.")
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "ustc-qwen-image/1.1"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        _die(f"Could not download the generated image: {exc}")
    if not data:
        _die("The generated image URL returned no data.")
    return data


def _image_extension(data: bytes) -> str | None:
    if data.startswith(PNG_SIGNATURE):
        return ".png"
    if data.startswith(JPEG_SIGNATURE):
        return ".jpg"
    if data.startswith(GIF_SIGNATURES):
        return ".gif"
    if data.startswith(BMP_SIGNATURE):
        return ".bmp"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    if len(data) >= 12 and data[4:12] in {b"ftypavif", b"ftypavis"}:
        return ".avif"
    return None


def _unique_path(directory: Path, stem: str, suffix: str) -> Path:
    candidate = directory / f"{stem}{suffix}"
    version = 2
    while candidate.exists():
        candidate = directory / f"{stem}-v{version}{suffix}"
        version += 1
    return candidate


def _image_bytes(item: dict[str, Any], timeout: float) -> bytes:
    encoded = item.get("b64_json") or item.get("base64") or item.get("image_base64")
    if isinstance(encoded, str) and encoded.strip():
        return _decode_base64(encoded)
    url = item.get("url")
    if isinstance(url, str) and url.strip():
        return _download_image(url.strip(), timeout)
    _die("An image item contains neither Base64 data nor a URL.")
    return b""


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate or edit images with USTC Qwen-Image-2.1."
    )
    parser.add_argument("--prompt", help="Image prompt")
    parser.add_argument("--prompt-file", help="UTF-8 file containing the image prompt")
    parser.add_argument(
        "--image",
        action="append",
        dest="images",
        help="Input image for editing; repeat for up to 10 reference images",
    )
    parser.add_argument(
        "--size",
        help="Explicit WIDTHxHEIGHT; overrides --aspect-ratio",
    )
    parser.add_argument(
        "--aspect-ratio",
        help="Qwen wh_ratio such as 3:2 or 16:9; mapped to a compatible pixel size",
    )
    parser.add_argument("--n", type=int, default=1, help="Number of images")
    parser.add_argument(
        "--out-dir",
        help=(
            "Output directory (default: USTC_QWEN_IMAGE_OUT_DIR, config "
            "'output_dir', or the system-configured Downloads folder)"
        ),
    )
    parser.add_argument("--model", help="Model name; defaults from config")
    parser.add_argument("--base-url", help="API base URL; defaults from config")
    parser.add_argument("--config", help="Alternative JSON config path")
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help="Request timeout in seconds",
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=DEFAULT_MAX_ATTEMPTS,
        help="Maximum attempts for retryable failures",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the request without calling the API",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    prompt = _read_prompt(args.prompt, args.prompt_file)
    config = _load_config(args.config)
    args.out_dir = _resolve_out_dir(args, config)

    base_url = _normalize_base_url(
        args.base_url
        or _config_string(config, "base_url")
        or DEFAULT_BASE_URL
    )
    model = (
        args.model
        or _config_string(config, "model")
        or DEFAULT_MODEL
    ).strip()
    if not model:
        _die("The model name cannot be empty.")

    if not 1 <= args.n <= 10:
        _die("--n must be between 1 and 10.")
    if args.timeout <= 0:
        _die("--timeout must be greater than 0.")
    if not 1 <= args.max_attempts <= 5:
        _die("--max-attempts must be between 1 and 5.")
    if args.size and args.aspect_ratio:
        _die("Use --size or --aspect-ratio, not both.")

    edit_mode = bool(args.images)
    image_paths = _validate_edit_images(args.images or [])
    if edit_mode:
        if args.size:
            size = _validate_size(args.size)
        elif args.aspect_ratio:
            size = _size_from_ratio(args.aspect_ratio)
        else:
            size = None
        endpoint = _api_endpoint(base_url, "edits")
        fields = [
            ("model", model),
            ("prompt", prompt),
            ("n", str(args.n)),
            ("response_format", "b64_json"),
        ]
        if size:
            fields.append(("size", size))
        if args.dry_run:
            print(
                json.dumps(
                    {
                        "dry_run": True,
                        "mode": "edit",
                        "endpoint": endpoint,
                        "aspect_ratio": args.aspect_ratio,
                        "out_dir": str(Path(args.out_dir).expanduser().resolve()),
                        "image_field": "image" if len(image_paths) == 1 else "image[]",
                        "input_images": [str(path) for path in image_paths],
                        "fields": dict(fields),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
    else:
        if args.size:
            size = _validate_size(args.size)
        elif args.aspect_ratio:
            size = _size_from_ratio(args.aspect_ratio)
        else:
            size = DEFAULT_SIZE
        endpoint = _api_endpoint(base_url, "generations")
        payload = {
            "model": model,
            "prompt": prompt,
            "n": args.n,
            "size": size,
            "extra_body": {"response_format": "b64_json"},
        }
        if args.dry_run:
            print(
                json.dumps(
                    {
                        "dry_run": True,
                        "mode": "generate",
                        "endpoint": endpoint,
                        "aspect_ratio": args.aspect_ratio,
                        "out_dir": str(Path(args.out_dir).expanduser().resolve()),
                        "payload": payload,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0

    api_key = _resolve_api_key(config)
    if edit_mode:
        print(
            f"Editing with {model} using {len(image_paths)} input image(s)...",
            file=sys.stderr,
        )
        response = _request_edit(
            endpoint=endpoint,
            api_key=api_key,
            fields=fields,
            images=image_paths,
            timeout=args.timeout,
            max_attempts=args.max_attempts,
        )
    else:
        print(
            f"Requesting {model} at {size} "
            f"({args.n} image{'s' if args.n != 1 else ''})...",
            file=sys.stderr,
        )
        response = _request_generation(
            endpoint=endpoint,
            api_key=api_key,
            payload=payload,
            timeout=args.timeout,
            max_attempts=args.max_attempts,
        )

    items = _response_items(response)
    if len(items) < args.n:
        _warn(f"Requested {args.n} image(s), but the API returned {len(items)}.")

    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    prefix = "qwen-image-edit" if edit_mode else "qwen-image"
    saved_files: list[str] = []

    for index, item in enumerate(items, start=1):
        image_data = _image_bytes(item, args.timeout)
        extension = _image_extension(image_data)
        if extension is None:
            _die(
                "The API returned bytes that are not a recognized PNG, JPEG, "
                "WebP, GIF, BMP, or AVIF image."
            )
        suffix = f"-{index:02d}" if len(items) > 1 else ""
        path = _unique_path(out_dir, f"{prefix}-{timestamp}{suffix}", extension)
        path.write_bytes(image_data)
        saved_files.append(str(path))
        print(f"Saved {path}", file=sys.stderr)

    print(
        json.dumps(
            {
                "mode": "edit" if edit_mode else "generate",
                "model": model,
                "requested_size": size or "service-default",
                "response_size": response.get("size"),
                "files": saved_files,
                "out_dir": str(out_dir),
                "response_id": response.get("id"),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
