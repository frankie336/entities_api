import os
import io
import time
import json
import httpx
import binascii
import platform
import urllib.parse
from os import PathLike
from pathlib import Path
from copy import deepcopy
from hashlib import sha256
from base64 import b64encode, b64decode
from typing import Any, AnyStr, Union, Optional, Sequence, Mapping, Literal, overload, List, Dict

import sys

if sys.version_info < (3, 9):
    from typing import Iterator, AsyncIterator
else:
    from collections.abc import Iterator, AsyncIterator

from importlib import metadata

try:
    __version__ = metadata.version('ollama')
except metadata.PackageNotFoundError:
    __version__ = '0.0.0'

from ollama._types import Message, Options, RequestError, ResponseError, Tool

from services.loggin_service import LoggingUtility

# Initialize logging utility
logging_utility = LoggingUtility()

# BaseClient class
class BaseClient:
    def __init__(self, client, host: Optional[str] = None, follow_redirects: bool = True, timeout: Any = None, **kwargs) -> None:
        headers = kwargs.pop('headers', {})
        headers['Content-Type'] = 'application/json'
        headers['Accept'] = 'application/json'
        headers['User-Agent'] = f'ollama-python/{__version__} ({platform.machine()} {platform.system().lower()}) Python/{platform.python_version()}'

        self._client = client(
            base_url=_parse_host(host or os.getenv('OLLAMA_HOST')),
            follow_redirects=follow_redirects,
            timeout=timeout,
            headers=headers,
            **kwargs,
        )
        logging_utility.info("Initialized BaseClient with headers: %s", headers)

# Client class
class Client(BaseClient):
    def __init__(self, host: Optional[str] = None, **kwargs) -> None:
        super().__init__(httpx.Client, host, **kwargs)

    def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        logging_utility.info("Sending request: %s %s", method, url)
        response = self._client.request(method, url, **kwargs)

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            logging_utility.error("HTTPStatusError: %s", e)
            raise ResponseError(e.response.text, e.response.status_code) from None

        logging_utility.info("Received response: %s", response.text)
        return response

    def _stream(self, method: str, url: str, **kwargs) -> Iterator[Mapping[str, Any]]:
        logging_utility.info("Starting stream: %s %s", method, url)
        with self._client.stream(method, url, **kwargs) as r:
            try:
                r.raise_for_status()
            except httpx.HTTPStatusError as e:
                e.response.read()
                logging_utility.error("HTTPStatusError: %s", e)
                raise ResponseError(e.response.text, e.response.status_code) from None

            for line in r.iter_lines():
                partial = json.loads(line)
                if e := partial.get('error'):
                    logging_utility.error("Stream error: %s", e)
                    raise ResponseError(e)
                yield partial

    def _request_stream(self, *args, stream: bool = False, **kwargs) -> Union[Mapping[str, Any], Iterator[Mapping[str, Any]]]:
        logging_utility.debug("Request stream with args: %s, kwargs: %s, stream: %s", args, kwargs, stream)
        return self._stream(*args, **kwargs) if stream else self._request(*args, **kwargs).json()

    @overload
    def generate(self, model: str = '', prompt: str = '', suffix: str = '', system: str = '', template: str = '', context: Optional[Sequence[int]] = None, stream: Literal[False] = False, raw: bool = False, format: Literal['', 'json'] = '', images: Optional[Sequence[AnyStr]] = None, options: Optional[Options] = None, keep_alive: Optional[Union[float, str]] = None,) -> Mapping[str, Any]: ...

    @overload
    def generate(self, model: str = '', prompt: str = '', suffix: str = '', system: str = '', template: str = '', context: Optional[Sequence[int]] = None, stream: Literal[True] = True, raw: bool = False, format: Literal['', 'json'] = '', images: Optional[Sequence[AnyStr]] = None, options: Optional[Options] = None, keep_alive: Optional[Union[float, str]] = None,) -> Iterator[Mapping[str, Any]]: ...

    def generate(self, model: str = '', prompt: str = '', suffix: str = '', system: str = '', template: str = '', context: Optional[Sequence[int]] = None, stream: bool = False, raw: bool = False, format: Literal['', 'json'] = '', images: Optional[Sequence[AnyStr]] = None, options: Optional[Options] = None, keep_alive: Optional[Union[float, str]] = None,) -> Union[Mapping[str, Any], Iterator[Mapping[str, Any]]]:
        if not model:
            logging_utility.error("RequestError: must provide a model")
            raise RequestError('must provide a model')

        logging_utility.info("Generating response with model: %s, prompt: %s", model, prompt)
        return self._request_stream(
            'POST',
            '/api/generate',
            json={
                'model': model,
                'prompt': prompt,
                'suffix': suffix,
                'system': system,
                'template': template,
                'context': context or [],
                'stream': stream,
                'raw': raw,
                'images': [_encode_image(image) for image in images or []],
                'format': format,
                'options': options or {},
                'keep_alive': keep_alive,
            },
            stream=stream,
        )

    @overload
    def chat(self, model: str = '', messages: Optional[Sequence[Message]] = None, tools: Optional[Sequence[Tool]] = None, stream: Literal[False] = False, format: Literal['', 'json'] = '', options: Optional[Options] = None, keep_alive: Optional[Union[float, str]] = None,) -> Mapping[str, Any]: ...

    @overload
    def chat(self, model: str = '', messages: Optional[Sequence[Message]] = None, tools: Optional[Sequence[Tool]] = None, stream: Literal[True] = True, format: Literal['', 'json'] = '', options: Optional[Options] = None, keep_alive: Optional[Union[float, str]] = None,) -> Iterator[Mapping[str, Any]]: ...

    def chat(self, model: str = '', messages: Optional[Sequence[Message]] = None, tools: Optional[Sequence[Tool]] = None, stream: bool = False, format: Literal['', 'json'] = '', options: Optional[Options] = None, keep_alive: Optional[Union[float, str]] = None,) -> Union[Mapping[str, Any], Iterator[Mapping[str, Any]]]:
        if not model:
            logging_utility.error("RequestError: must provide a model")
            raise RequestError('must provide a model')

        logging_utility.info("Chat request with model: %s, messages: %s", model, messages)
        messages = deepcopy(messages)

        for message in messages or []:
            if images := message.get('images'):
                message['images'] = [_encode_image(image) for image in images]

        return self._request_stream(
            'POST',
            '/api/chat',
            json={
                'model': model,
                'messages': messages,
                'tools': tools or [],
                'stream': stream,
                'format': format,
                'options': options or {},
                'keep_alive': keep_alive,
            },
            stream=stream,
        )

    def embed(self, model: str = '', input: Union[str, Sequence[AnyStr]] = '', truncate: bool = True, options: Optional[Options] = None, keep_alive: Optional[Union[float, str]] = None,) -> Mapping[str, Any]:
        if not model:
            logging_utility.error("RequestError: must provide a model")
            raise RequestError('must provide a model')

        logging_utility.info("Embedding request with model: %s, input: %s", model, input)
        return self._request(
            'POST',
            '/api/embed',
            json={
                'model': model,
                'input': input,
                'truncate': truncate,
                'options': options or {},
                'keep_alive': keep_alive,
            },
        ).json()

    def embeddings(self, model: str = '', prompt: str = '', options: Optional[Options] = None, keep_alive: Optional[Union[float, str]] = None,) -> Mapping[str, Sequence[float]]:
        logging_utility.info("Embeddings request with model: %s, prompt: %s", model, prompt)
        return self._request(
            'POST',
            '/api/embeddings',
            json={
                'model': model,
                'prompt': prompt,
                'options': options or {},
                'keep_alive': keep_alive,
            },
        ).json()

    @overload
    def pull(self, model: str, insecure: bool = False, stream: Literal[False] = False,) -> Mapping[str, Any]: ...

    @overload
    def pull(self, model: str, insecure: bool = False, stream: Literal[True] = True,) -> Iterator[Mapping[str, Any]]: ...

    def pull(self, model: str, insecure: bool = False, stream: bool = False,) -> Union[Mapping[str, Any], Iterator[Mapping[str, Any]]]:
        logging_utility.info("Pull request for model: %s, insecure: %s, stream: %s", model, insecure, stream)
        return self._request_stream(
            'POST',
            '/api/pull',
            json={
                'name': model,
                'insecure': insecure,
                'stream': stream,
            },
            stream=stream,
        )

    @overload
    def push(self, model: str, insecure: bool = False, stream: Literal[False] = False,) -> Mapping[str, Any]: ...

    @overload
    def push(self, model: str, insecure: bool = False, stream: Literal[True] = True,) -> Iterator[Mapping[str, Any]]: ...

    def push(self, model: str, insecure: bool = False, stream: bool = False,) -> Union[Mapping[str, Any], Iterator[Mapping[str, Any]]]:
        logging_utility.info("Push request for model: %s, insecure: %s, stream: %s", model, insecure, stream)
        return self._request_stream(
            'POST',
            '/api/push',
            json={
                'name': model,
                'insecure': insecure,
                'stream': stream,
            },
            stream=stream,
        )

    @overload
    def create(self, model: str, path: Optional[Union[str, PathLike]] = None, modelfile: Optional[str] = None, quantize: Optional[str] = None, stream: Literal[False] = False,) -> Mapping[str, Any]: ...

    @overload
    def create(self, model: str, path: Optional[Union[str, PathLike]] = None, modelfile: Optional[str] = None, quantize: Optional[str] = None, stream: Literal[True] = True,) -> Iterator[Mapping[str, Any]]: ...

    def create(self, model: str, path: Optional[Union[str, PathLike]] = None, modelfile: Optional[str] = None, quantize: Optional[str] = None, stream: bool = False,) -> Union[Mapping[str, Any], Iterator[Mapping[str, Any]]]:
        if (realpath := _as_path(path)) and realpath.exists():
            modelfile = self._parse_modelfile(realpath.read_text(), base=realpath.parent)
        elif modelfile:
            modelfile = self._parse_modelfile(modelfile)
        else:
            logging_utility.error("RequestError: must provide either path or modelfile")
            raise RequestError('must provide either path or modelfile')

        logging_utility.info("Create request for model: %s, path: %s, modelfile: %s", model, path, modelfile)
        return self._request_stream(
            'POST',
            '/api/create',
            json={
                'name': model,
                'modelfile': modelfile,
                'stream': stream,
                'quantize': quantize,
            },
            stream=stream,
        )

    def _parse_modelfile(self, modelfile: str, base: Optional[Path] = None) -> str:
        base = Path.cwd() if base is None else base

        out = io.StringIO()
        for line in io.StringIO(modelfile):
            command, _, args = line.partition(' ')
            if command.upper() not in ['FROM', 'ADAPTER']:
                print(line, end='', file=out)
                continue

            path = Path(args.strip()).expanduser()
            path = path if path.is_absolute() else base / path
            if path.exists():
                args = f'@{self._create_blob(path)}\n'
            print(command, args, end='', file=out)

        return out.getvalue()

    def _create_blob(self, path: Union[str, Path]) -> str:
        sha256sum = sha256()
        with open(path, 'rb') as r:
            while True:
                chunk = r.read(32 * 1024)
                if not chunk:
                    break
                sha256sum.update(chunk)

        digest = f'sha256:{sha256sum.hexdigest()}'

        try:
            self._request('HEAD', f'/api/blobs/{digest}')
        except ResponseError as e:
            if e.status_code != 404:
                logging_utility.error("ResponseError: %s", e)
                raise

            with open(path, 'rb') as r:
                self._request('POST', f'/api/blobs/{digest}', content=r)

        logging_utility.info("Created blob with digest: %s", digest)
        return digest

    def delete(self, model: str) -> Mapping[str, Any]:
        logging_utility.info("Delete request for model: %s", model)
        response = self._request('DELETE', '/api/delete', json={'name': model})
        return {'status': 'success' if response.status_code == 200 else 'error'}

    def list(self) -> Mapping[str, Any]:
        logging_utility.info("List models request")
        return self._request('GET', '/api/tags').json()

    def copy(self, source: str, destination: str) -> Mapping[str, Any]:
        logging_utility.info("Copy request from source: %s to destination: %s", source, destination)
        response = self._request('POST', '/api/copy', json={'source': source, 'destination': destination})
        return {'status': 'success' if response.status_code == 200 else 'error'}

    def show(self, model: str) -> Mapping[str, Any]:
        logging_utility.info("Show request for model: %s", model)
        return self._request('POST', '/api/show', json={'name': model}).json()

    def ps(self) -> Mapping[str, Any]:
        logging_utility.info("PS request")
        return self._request('GET', '/api/ps').json()


class RunService:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url
        self.api_key = api_key
        self.client = httpx.Client(base_url=base_url, headers={"Authorization": f"Bearer {api_key}"})

    def create_run(self, assistant_id: str, thread_id: str, instructions: str, meta_data: Optional[Dict[str, Any]] = {}) -> Dict[str, Any]:
        run_data = {
            "id": f"run_{assistant_id}_{thread_id}",
            "assistant_id": assistant_id,
            "thread_id": thread_id,
            "instructions": instructions,
            "meta_data": meta_data,
            "cancelled_at": None,
            "completed_at": None,
            "created_at": int(time.time()),
            "expires_at": int(time.time()) + 3600,
            "failed_at": None,
            "incomplete_details": None,
            "last_error": None,
            "max_completion_tokens": 1000,
            "max_prompt_tokens": 500,
            "model": "gpt-4",
            "object": "run",
            "parallel_tool_calls": False,
            "required_action": None,
            "response_format": "text",
            "started_at": None,
            "status": "pending",
            "tool_choice": "none",
            "tools": [],
            "truncation_strategy": {},
            "usage": None,
            "temperature": 0.7,
            "top_p": 0.9,
            "tool_resources": {}
        }
        response = self.client.post("/v1/runs", json=run_data)
        print(f"Request payload: {run_data}")
        print(f"Response status code: {response.status_code}")
        print(f"Response text: {response.text}")
        response.raise_for_status()
        return response.json()

    def retrieve_run(self, run_id: str) -> Dict[str, Any]:
        response = self.client.get(f"/v1/runs/{run_id}")
        response.raise_for_status()
        return response.json()

    def update_run(self, run_id: str, **updates) -> Dict[str, Any]:
        response = self.client.put(f"/v1/runs/{run_id}", json=updates)
        response.raise_for_status()
        return response.json()

    def list_runs(self, limit: int = 20, order: str = "asc") -> List[Dict[str, Any]]:
        params = {"limit": limit, "order": order}
        response = self.client.get("/v1/runs", params=params)
        response.raise_for_status()
        return response.json()

    def delete_run(self, run_id: str) -> Dict[str, Any]:
        response = self.client.delete(f"/v1/runs/{run_id}")
        response.raise_for_status()
        return response.json()

    def generate(self, run_id: str, model: str, prompt: str, stream: bool = False) -> Dict[str, Any]:
        run = self.retrieve_run(run_id)
        response = self.client.post(
            "/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": stream,
                "context": run.get("context", []),
                "options": run.get("options", {}),
                "keep_alive": run.get("keep_alive"),
                "format": "json",
            }
        )
        response.raise_for_status()
        return response.json()

    def chat(self, run_id: str, model: str, messages: List[Dict[str, Any]], stream: bool = False) -> Union[httpx.Response, Iterator[Dict[str, Any]]]:
        run = self.retrieve_run(run_id)
        response = self.client.post(
            "/v1/chat",
            json={
                "model": model,
                "messages": messages,
                "stream": stream,
                "tools": run.get("tools", []),
                "format": "json",
                "options": run.get("options", {}),
                "keep_alive": run.get("keep_alive"),
            }
        )
        response.raise_for_status()
        if stream:
            return response.iter_lines()
        return response.json()

# OllamaClient class


class OllamaClient(BaseClient):
    def __init__(self, base_url: str, api_key: str, run_service: RunService):
        super().__init__(httpx.Client, base_url)
        self.run_service = run_service
        self.api_key = api_key
        logging_utility.info("Initialized OllamaClient with base_url: %s", base_url)

    def create_run(self, assistant_id: str, thread_id: str, instructions: str, meta_data: Dict[str, Any] = {}) -> Dict[str, Any]:
        logging_utility.info("Creating run for assistant ID: %s, thread ID: %s", assistant_id, thread_id)
        return self.run_service.create_run(assistant_id, thread_id, instructions, meta_data)

    def generate(self, run_id: str, prompt: str, stream: bool = False) -> Dict[str, Any]:
        logging_utility.info("Generating response for run ID: %s with prompt: %s", run_id, prompt)
        run = self.retrieve_run(run_id)
        return self.run_service.generate(run_id, run["model"], prompt, stream)

    def chat(self, run_id: str, model: str, messages: List[Dict[str, Any]], stream: bool = False) -> Union[Dict[str, Any], Iterator[Dict[str, Any]]]:
        logging_utility.info("Chatting for run ID: %s with model: %s", run_id, model)
        run = self.retrieve_run(run_id)
        return self.run_service.chat(run_id, model, messages, stream)

    def update_run(self, run_id: str, **updates) -> Dict[str, Any]:
        logging_utility.info("Updating run ID: %s with updates: %s", run_id, updates)
        return self.run_service.update_run(run_id, **updates)

    def retrieve_run(self, run_id: str) -> Dict[str, Any]:
        logging_utility.info("Retrieving run ID: %s", run_id)
        return self.run_service.retrieve_run(run_id)

# Helper functions
def _encode_image(image) -> str:
    logging_utility.debug("Encoding image")
    if p := _as_path(image):
        return b64encode(p.read_bytes()).decode('utf-8')

    try:
        b64decode(image, validate=True)
        return image if isinstance(image, str) else image.decode('utf-8')
    except (binascii.Error, TypeError):
        ...

    if b := _as_bytesio(image):
        return b64encode(b.read()).decode('utf-8')

    logging_utility.error("RequestError: image must be bytes, path-like object, or file-like object")
    raise RequestError('image must be bytes, path-like object, or file-like object')

def _as_path(s: Optional[Union[str, PathLike]]) -> Union[Path, None]:
    logging_utility.debug("Converting to path")
    if isinstance(s, str) or isinstance(s, Path):
        try:
            if (p := Path(s)).exists():
                return p
        except Exception:
            ...
    return None

def _as_bytesio(s: Any) -> Union[io.BytesIO, None]:
    logging_utility.debug("Converting to BytesIO")
    if isinstance(s, io.BytesIO):
        return s
    elif isinstance(s, bytes):
        return io.BytesIO(s)
    return None

def _parse_host(host: Optional[str]) -> str:
    logging_utility.debug("Parsing host")
    host, port = host or '', 11434
    scheme, _, hostport = host.partition('://')
    if not hostport:
        scheme, hostport = 'http', host
    elif scheme == 'http':
        port = 80
    elif scheme == 'https':
        port = 443

    split = urllib.parse.urlsplit('://'.join([scheme, hostport]))
    host = split.hostname or '127.0.0.1'
    port = split.port or port

    return f'{scheme}://{host}:{port}'
