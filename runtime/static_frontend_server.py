"""生产候选前端静态文件服务器，支持 SPA 路由回退。"""

from __future__ import annotations

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit


class SpaRequestHandler(SimpleHTTPRequestHandler):
    """静态资源按原路径读取，前端路由统一回退到 index.html。"""

    def send_head(self):
        """资源不存在且不是 API 请求时返回 SPA 入口。"""
        if resolve_static_target(self.directory, self.path) == "index.html":
            self.path = "/index.html"
        return super().send_head()


def resolve_static_target(directory: str | Path, request_path: str) -> str:
    """解析静态资源目标；未知前端路由回退，API 路径保持 404。"""
    relative = urlsplit(request_path).path.lstrip("/")
    requested = Path(directory) / relative
    if relative and not requested.exists() and not relative.startswith("api/"):
        return "index.html"
    return relative


def serve_frontend(directory: str | Path, host: str = "127.0.0.1", port: int = 5173) -> None:
    """启动无开发依赖的静态前端服务。"""
    dist = Path(directory).expanduser().resolve()
    index_path = dist / "index.html"
    if not index_path.exists():
        raise FileNotFoundError(f"前端构建产物不存在: {index_path}，请先执行 npm run build:pre")
    handler = partial(SpaRequestHandler, directory=str(dist))
    server = ThreadingHTTPServer((host, port), handler)
    print(f"Quant frontend serving {dist} at http://{host}:{port}")
    try:
        server.serve_forever()
    finally:
        server.server_close()


def main() -> None:
    """命令行入口。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5173)
    args = parser.parse_args()
    serve_frontend(args.directory, args.host, args.port)


if __name__ == "__main__":
    main()
