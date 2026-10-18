"""批处理脚本静态体检：编码、行尾与解析结果。

为什么需要它：仓库里的四个 .bat 是给校园网部署同学双击用的，
它们有三个容易踩的硬性约定（见 docs/部署说明_校园网服务器.md）：

1. 必须 **GBK(CP936) 无 BOM**——本机代码页是 936，用 UTF-8 存会让中文显示成乱码；
2. 必须 **CRLF 行尾**——cmd.exe 的解析器按字节偏移定位，裸 LF 会错位，
   把 rem 注释和 echo 文本当成命令执行，刷出一堆「不是内部或外部命令」；
3. **不要**写 `chcp 65001`——脚本正文是 GBK，切到 UTF-8 后脚本自己的中文 echo 会变乱码。
   Python 在 Windows 上按控制台代码页输出，控制台是 936 时它本来就用 GBK，无需干预。

第 2 条最隐蔽：服务照样能起来，只是屏幕上多一堆报错，很容易被当成"编码问题"
去改编码，结果越改越乱。所以这里把三条都做成断言。

用法：
    python tools/check_bat.py            # 体检全部 .bat
    python tools/check_bat.py run.bat    # 只体检指定脚本

退出码：0 = 全部通过，1 = 有问题。
"""

import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 会真正启动服务 / 改系统 / 阻塞等待的语句，体检时替换成 echo 占位，
# 这样既能走完整个解析流程，又不会真的起服务或改防火墙。
#
# 注意：`exit /b 1` 不能改写成带 `&` 的复合命令——它常出现在 if 块里，
# `&` 会把块解析拆开，报出 `'ho' 不是内部或外部命令` 这种假阳性。
SAFE_REWRITES = (
    (r'(?m)^\s*python\s+server\.py\s*$', 'echo [OK] python server.py 行可达'),
    (r'(?m)^\s*python\s+app\.py\s*$', 'echo [OK] python app.py 行可达'),
    (r'(?m)^\s*python\s+tools\\gen_secret\.py.*$', 'echo [OK] gen_secret 行可达'),
    (r'(?m)^\s*python\s+-m\s+pip.*$', 'echo [OK] pip 行可达'),
    (r'(?m)^\s*netsh\s+advfirewall.*$', 'echo [OK] netsh 行可达'),
    (r'(?m)^\s*taskkill.*$', 'echo [OK] taskkill 行可达'),
    (r'(?m)^\s*start\s+.*$', 'echo [OK] start 行可达'),
    (r'(?m)^\s*set /p CONFIRM.*$', 'set CONFIRM=N'),
    (r'(?m)^\s*pause\s*$', 'rem pause'),
    # 管理员检测在非管理员环境下必然走早退分支，后面的 netsh 行就永远跑不到。
    # 换成必然成功的 `ver`，让整份脚本的每一行都真正被 cmd 解析一遍。
    (r'(?m)^\s*net\s+session.*$', 'ver >nul'),
    (r'(?m)^\s*exit\s*/b\s+\d+\s*$', 'goto :eof'),
    (r'(?m)^\s*exit\s*$', 'goto :eof'),
)

# cmd.exe 解析失败时的典型报错（GBK 解码后）
PARSE_ERRORS = re.compile(
    r'不是内部或外部命令|not recognized|命令语法不正确|语法错误|'
    r'The syntax of the command is incorrect'
)


def batch_files():
    """返回仓库根目录下所有 .bat 文件名（排序）。"""
    return sorted(n for n in os.listdir(ROOT) if n.lower().endswith('.bat'))


def check_encoding(name):
    """检查编码与行尾，返回 (问题列表, 解码后的文本)。"""
    problems = []
    with open(os.path.join(ROOT, name), 'rb') as fh:
        raw = fh.read()

    if raw.startswith(b'\xef\xbb\xbf'):
        problems.append('带 UTF-8 BOM：cmd.exe 会把 BOM 当成命令的一部分')
    elif raw.startswith((b'\xff\xfe', b'\xfe\xff')):
        problems.append('是 UTF-16：cmd.exe 无法解析，必须转成 GBK 无 BOM')

    # 裸 LF（前面不是 CR）会让 cmd 解析错位，是本项目踩过的坑
    bare_lf = len(re.findall(rb'(?<!\r)\n', raw))
    if bare_lf:
        problems.append('有 %d 处裸 LF 行尾：cmd.exe 会解析错位，必须全部用 CRLF'
                        % bare_lf)
    if b'\r\n' not in raw:
        problems.append('完全没有 CRLF 行尾：请确认文件是批处理而不是文本')

    try:
        text = raw.decode('gbk')
    except UnicodeDecodeError as exc:
        problems.append('不是合法 GBK：%s（本机代码页 936，中文会乱码）' % exc)
        text = raw.decode('gbk', 'replace')

    if not text.lstrip().lower().startswith('@echo off'):
        problems.append('首行不是 @echo off：会把每条命令都回显出来')
    # chcp 65001 与 GBK 正文冲突：切到 UTF-8 后脚本自己的中文 echo 反而变乱码。
    # Python 按控制台代码页输出，控制台是 936 时本来就正常，不需要 chcp。
    if 'chcp 65001' in text:
        problems.append('写了 chcp 65001：与 GBK 正文冲突，脚本自己的中文 echo 会变乱码')

    return problems, text


def check_parse(name, text):
    """把脚本改写后交给 cmd 跑一遍，返回 (问题列表, 输出文本)。"""
    safe = text
    for pattern, repl in SAFE_REWRITES:
        safe = re.sub(pattern, repl, safe)

    tmp = os.path.join(tempfile.mkdtemp(prefix='qinghe_checkbat_'), 'chk.bat')
    with open(tmp, 'wb') as fh:
        fh.write(safe.encode('gbk', 'replace'))

    try:
        # 用 call 而不是直接引号路径：cmd /c 会把整串引号当成一个命令名，
        # 报「'"C:\...\chk.bat"' 不是内部或外部命令」——那是引号解析问题，
        # 会被误判成脚本本身有语法错。
        proc = subprocess.run(
            'chcp 936 >nul & call "%s"' % tmp,
            shell=True, capture_output=True, timeout=60,
        )
        out = (proc.stdout + proc.stderr).decode('gbk', 'replace')
    except (OSError, subprocess.SubprocessError) as exc:
        return ['无法执行体检：%s' % exc], ''
    finally:
        try:
            os.remove(tmp)
            os.rmdir(os.path.dirname(tmp))
        except OSError:
            pass

    hits = [line.strip() for line in out.splitlines() if PARSE_ERRORS.search(line)]
    problems = ['解析报错：%s' % line for line in hits[:5]]
    return problems, out


def main(argv):
    """体检入口，返回退出码。"""
    names = argv[1:] or batch_files()
    if not names:
        print('没有找到 .bat 文件')
        return 1

    print('仓库根：%s' % ROOT)
    failed = 0
    for name in names:
        path = os.path.join(ROOT, name)
        if not os.path.isfile(path):
            print('\n[跳过] %s：文件不存在' % name)
            failed += 1
            continue

        size = os.path.getsize(path)
        problems, text = check_encoding(name)
        parse_problems, out = check_parse(name, text)
        problems.extend(parse_problems)

        if problems:
            failed += 1
            print('\n[FAIL] %s（%d 字节）' % (name, size))
            for item in problems:
                print('       - %s' % item)
        else:
            print('\n[ OK ] %s（%d 字节）编码 GBK / 行尾 CRLF / 解析无报错'
                  % (name, size))

    print('\n%s：%d 个脚本，%d 个有问题' % (
        '全部通过' if not failed else '存在问题', len(names), failed))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
