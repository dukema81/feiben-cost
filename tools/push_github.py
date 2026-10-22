# -*- coding: utf-8 -*-
"""把飞奔成本管理系统推送到 GitHub（gh api contents 逐文件 PUT）。

为什么不用 git push：本机出口代理对 github.com:443 的 CONNECT 返回 502，
而 api.github.com 可用（gh 走 API）。逐文件 PUT 支持二进制（base64）。

用法：python tools/push_github.py [OWNER/REPO] [BRANCH]
"""
import base64
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = sys.argv[1] if len(sys.argv) > 1 else "dukema81/feiben-cost"
BRANCH = sys.argv[2] if len(sys.argv) > 2 else "main"
MSG = "feat: 飞奔成本管理系统 V1.0（标准成本卡 + 约当产量 + 五维差异 + 阶梯分摊 + 预算闸口 + 结账锁期）"


def gh(args, data=None):
    cmd = ["gh"] + args
    if data is not None:
        cmd += ["--input", "-"]
    proc = subprocess.run(cmd, cwd=ROOT, input=(json.dumps(data).encode() if data is not None else None),
                          capture_output=True)
    return proc.returncode, proc.stdout.decode("utf-8", "ignore"), proc.stderr.decode("utf-8", "ignore")


def remote_sha(path):
    code, out, _ = gh(["api", "repos/%s/contents/%s?ref=%s" % (REPO, path, BRANCH)])
    if code != 0:
        return None
    try:
        return json.loads(out).get("sha")
    except Exception:
        return None


def ensure_repo():
    code, out, err = gh(["api", "repos/%s" % REPO])
    if code == 0:
        print("仓库已存在：", json.loads(out)["full_name"])
        return True
    owner, name = REPO.split("/", 1)
    code, out, err = gh(["api", "--method", "POST", "user/repos"], data={
        "name": name, "description": "飞奔成本管理系统 — 标准成本、实际归集、差异分析、阶梯分摊、预算管控、期间结账",
        "private": False, "auto_init": True})
    if code == 0:
        print("仓库已创建：", REPO)
        return True
    print("创建仓库失败：", err[:300])
    return False


def main():
    if not ensure_repo():
        return 1
    raw = subprocess.run(["git", "-c", "core.quotepath=false", "ls-files", "-z"],
                         cwd=ROOT, capture_output=True).stdout
    files = [x for x in raw.decode("utf-8").split("\0") if x]
    print("待推送文件：%d" % len(files))
    ok = fail = 0
    for i, rel in enumerate(files, 1):
        full = os.path.join(ROOT, rel)
        with open(full, "rb") as f:
            content = base64.b64encode(f.read()).decode()
        body = {"message": "%s\n\n%s" % (MSG.split("\n")[0], rel), "content": content, "branch": BRANCH}
        sha = remote_sha(rel)
        if sha:
            body["sha"] = sha
        code, out, err = gh(["api", "--method", "PUT",
                             "repos/%s/contents/%s" % (REPO, rel.replace(os.sep, "/"))], data=body)
        if code == 0:
            ok += 1
            print("  [%2d/%2d] OK   %s" % (i, len(files), rel))
        else:
            fail += 1
            print("  [%2d/%2d] FAIL %s :: %s" % (i, len(files), rel, (err or out).strip()[:160]))
    print("\n成功 %d，失败 %d" % (ok, fail))
    print("仓库地址：https://github.com/%s" % REPO)
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
