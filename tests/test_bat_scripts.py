"""批处理脚本契约测试：编码、行尾、chcp 与解析。

背景：`run.bat` 等四个 .bat 是给校园网部署同学双击用的，出过一次真实故障——
文件以 UTF-8 + 裸 LF 入库，双击后 cmd.exe 解析错位，满屏
`'鍦拌皟璇曞惎鍔（浠呬緵寮€鍙戣€呮湰鏈轰娇鐢級' 不是内部或外部命令`，
而服务其实起来了，很容易被误判成「编码问题」去改编码。

这里把三条约定钉成断言，并调用 tools/check_bat.py 真正跑一遍 cmd 解析，
防止再次回退成 LF 或 UTF-8。
"""

import os
import re
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BATS = ('run.bat', 'start_server.bat', 'stop_server.bat', 'firewall_allow.bat')

sys.path.insert(0, os.path.join(ROOT, 'tools'))
import check_bat  # noqa: E402


@pytest.mark.parametrize('name', BATS)
def test_bat_exists(name):
    """四个部署脚本都必须存在且非空。"""
    path = os.path.join(ROOT, name)
    assert os.path.isfile(path), '%s 不存在' % name
    assert os.path.getsize(path) > 0, '%s 是空文件' % name


@pytest.mark.parametrize('name', BATS)
def test_bat_is_gbk_without_bom(name):
    """必须是无 BOM 的 GBK：本机 cmd 代码页 936，UTF-8 存盘中文会乱码。"""
    with open(os.path.join(ROOT, name), 'rb') as fh:
        raw = fh.read()
    assert not raw.startswith(b'\xef\xbb\xbf'), '%s 带了 UTF-8 BOM' % name
    assert not raw.startswith((b'\xff\xfe', b'\xfe\xff')), '%s 是 UTF-16' % name
    # 不能抛 UnicodeDecodeError
    raw.decode('gbk')


@pytest.mark.parametrize('name', BATS)
def test_bat_uses_crlf_only(name):
    """必须全部 CRLF。

    这是本次故障的主因：cmd.exe 的解析器按字节偏移定位，裸 LF 会让它错位，
    把 rem 注释与 echo 文本当成命令执行。
    """
    with open(os.path.join(ROOT, name), 'rb') as fh:
        raw = fh.read()
    bare_lf = len(re.findall(rb'(?<!\r)\n', raw))
    assert bare_lf == 0, '%s 有 %d 处裸 LF 行尾' % (name, bare_lf)
    assert raw.count(b'\r\n') > 0, '%s 没有 CRLF 行尾' % name


@pytest.mark.parametrize('name', BATS)
def test_bat_has_no_chcp_65001(name):
    """不得写 chcp 65001。

    脚本正文是 GBK，切到 UTF-8 后脚本自己的中文 echo 反而变乱码；
    Python 在 Windows 上按控制台代码页输出，控制台是 936 时本来就正常。
    """
    with open(os.path.join(ROOT, name), 'rb') as fh:
        text = fh.read().decode('gbk')
    assert 'chcp 65001' not in text, '%s 写了 chcp 65001，会让正文中文变乱码' % name


@pytest.mark.parametrize('name', BATS)
def test_bat_starts_with_echo_off(name):
    """首行必须是 @echo off，否则每条命令都会回显。"""
    with open(os.path.join(ROOT, name), 'rb') as fh:
        text = fh.read().decode('gbk')
    assert text.lstrip().lower().startswith('@echo off'), '%s 首行不是 @echo off' % name


@pytest.mark.parametrize('name', BATS)
def test_bat_parses_cleanly_in_cmd(name):
    """把脚本交给真实 cmd.exe 解析一遍，不得出现「不是内部或外部命令」。

    体检时会把起服务 / 改防火墙 / 阻塞等待的语句换成占位，所以不会真起服务。
    """
    with open(os.path.join(ROOT, name), 'rb') as fh:
        text = fh.read().decode('gbk')
    problems, out = check_bat.check_parse(name, text)
    assert problems == [], '%s 解析报错：%s' % (name, problems)


def test_check_encoding_flags_bare_lf(tmp_path):
    """自检：体检函数真的能识别裸 LF 与 chcp，而不是永远返回通过。

    没有这条，`check_encoding` 一旦写错（比如正则写反），
    上面那批参数化用例会全部"通过"却什么都没检查到。
    """
    broken = tmp_path / 'broken.bat'
    broken.write_bytes('@echo off\nchcp 65001 >nul\ntitle 测试\n'.encode('gbk'))

    real_root, check_bat.ROOT = check_bat.ROOT, str(tmp_path)
    try:
        problems, _ = check_bat.check_encoding('broken.bat')
    finally:
        check_bat.ROOT = real_root

    joined = ' '.join(problems)
    assert '裸 LF' in joined, '应当识别出裸 LF，实际：%s' % problems
    assert 'chcp 65001' in joined, '应当识别出 chcp 65001，实际：%s' % problems


def test_check_encoding_accepts_healthy_file():
    """自检的另一面：真实脚本必须被判为健康（零问题）。"""
    for name in BATS:
        problems, _ = check_bat.check_encoding(name)
        assert problems == [], '%s 被误判：%s' % (name, problems)
