#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""生成随机 ``FARM_SECRET_KEY`` 并写入项目根目录的 ``.env``。

用法::

    python tools/gen_secret.py            # 生成并写入 .env
    python tools/gen_secret.py --force    # 覆盖已存在的 .env

规则：``.env`` 已存在时**默认不覆盖**，只提示用户当前已有密钥，
避免把别人正在使用的会话密钥换掉导致全部用户掉线。
"""

from __future__ import annotations

import argparse
import os
import secrets
import sys

#: .env 中密钥的键名
SECRET_KEY_NAME = "FARM_SECRET_KEY"
#: 随机密钥字节数（token_urlsafe 输出长度约为 4/3 倍）
SECRET_KEY_BYTES = 48

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(PROJECT_ROOT, ".env")
ENV_EXAMPLE_PATH = os.path.join(PROJECT_ROOT, ".env.example")


def generate_secret(nbytes: int = SECRET_KEY_BYTES) -> str:
    """生成 URL 安全的随机密钥字符串。"""
    return secrets.token_urlsafe(nbytes)


def build_env_content(secret: str, template_path: str | None = None) -> str:
    """基于 ``.env.example`` 模板生成 .env 内容，并把密钥占位替换为真实值。

    模板缺失时退化为一份最小可用内容。
    """
    template_path = template_path or ENV_EXAMPLE_PATH
    try:
        with open(template_path, "r", encoding="utf-8") as fh:
            content = fh.read()
    except OSError:
        content = (
            "# 青禾智灌环境变量\n"
            f"{SECRET_KEY_NAME}={secret}\n"
            "FARM_DB_PATH=qinghe.db\n"
            "HOST=0.0.0.0\n"
            "PORT=5000\n"
            "FARM_DEBUG=0\n"
        )
        return content

    lines = []
    replaced = False
    for line in content.splitlines():
        if line.strip().startswith(f"{SECRET_KEY_NAME}="):
            lines.append(f"{SECRET_KEY_NAME}={secret}")
            replaced = True
        else:
            lines.append(line)
    if not replaced:
        lines.append(f"{SECRET_KEY_NAME}={secret}")
    return "\n".join(lines) + "\n"


def write_env(secret: str, env_path: str | None = None, force: bool = False) -> bool:
    """把密钥写入 ``.env``。

    :return: 写入成功返回 True；文件已存在且未加 ``--force`` 时返回 False。
    """
    env_path = env_path or ENV_PATH
    if os.path.exists(env_path) and not force:
        return False
    content = build_env_content(secret)
    with open(env_path, "w", encoding="utf-8") as fh:
        fh.write(content)
    return True


def main(argv=None) -> int:
    """命令行入口：生成密钥并落盘。"""
    parser = argparse.ArgumentParser(description="生成 FARM_SECRET_KEY 并写入 .env")
    parser.add_argument("--force", action="store_true", help="覆盖已存在的 .env")
    args = parser.parse_args(argv)

    secret = generate_secret()

    if os.path.exists(ENV_PATH) and not args.force:
        print(f"[跳过] {ENV_PATH} 已存在，未覆盖。")
        print("       如需重新生成密钥，请运行：python tools/gen_secret.py --force")
        print("       （注意：更换密钥会让所有已登录用户的会话失效）")
        return 0

    write_env(secret, force=args.force)
    print(f"[完成] 已生成随机密钥并写入 {ENV_PATH}")
    print(f"       {SECRET_KEY_NAME}={secret[:8]}...（已隐藏中间部分）")
    print("       该文件已被 .gitignore 忽略，不会提交到仓库。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
