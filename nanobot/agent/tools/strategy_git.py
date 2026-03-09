"""策略 Git 版本管理 Tool"""
import os
import subprocess
from typing import Optional, List

from nanobot.agent.tools.base import Tool


class StrategyGitTool(Tool):
    """
    量化策略 Git 版本管理工具
    通过 Git 管理策略版本，支持分支、合并、回退
    """

    name = "strategy_git"
    description = (
        "管理量化策略的 Git 版本，支持提交、分支、合并、查看历史。"
        "使用 Git 分支管理策略版本，始终保持策略可追溯、可回退。"
    )

    STRATEGY_DIR = os.path.expanduser("~/.nanobot/strategies")

    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["init", "status", "commit", "branch", "merge", "log", "diff", "checkout", "list_branches"],
                "description": "操作类型"
            },
            "message": {"type": "string", "description": "提交信息"},
            "branch_name": {"type": "string", "description": "分支名"},
            "from_branch": {"type": "string", "description": "源分支"},
            "to_branch": {"type": "string", "description": "目标分支"},
            "file": {"type": "string", "description": "文件路径"},
            "commit": {"type": "string", "description": "commit hash"},
        },
        "required": ["action"],
    }

    def _run_git(self, args: List[str], cwd: Optional[str] = None) -> str:
        """执行 Git 命令"""
        try:
            result = subprocess.run(
                ["git"] + args,
                cwd=cwd or self.STRATEGY_DIR,
                capture_output=True,
                text=True,
                check=True
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            return f"Error: {e.stderr.strip()}"

    def _ensure_repo(self) -> bool:
        """确保 Git 仓库存在"""
        if not os.path.exists(self.STRATEGY_DIR):
            os.makedirs(self.STRATEGY_DIR, exist_ok=True)

        git_dir = os.path.join(self.STRATEGY_DIR, ".git")
        if not os.path.exists(git_dir):
            # 初始化仓库
            subprocess.run(["git", "init"], cwd=self.STRATEGY_DIR, check=True)
            # 创建 .gitignore
            with open(os.path.join(self.STRATEGY_DIR, ".gitignore"), "w") as f:
                f.write("backtest_results/\n__pycache__/\n*.pyc\n")
            return True
        return True

    async def execute(
        self,
        action: str,
        message: Optional[str] = None,
        branch_name: None,
        from_branch: Optional[str] = None,
        to_branch: Optional[str] = None,
        file: Optional[str] = None,
        commit: Optional[str] = None,
        **kwargs
    ) -> str:
        """执行操作"""

        self._ensure_repo()

        if action == "init":
            return await self._init()

        if action == "status":
            return await self._status()

        if action == "commit":
            if not message:
                return "Error: 需要提供 message 参数"
            return await self._commit(message, file)

        if action == "branch":
            if not branch_name:
                return "Error: 需要提供 branch_name 参数"
            return await self._branch(branch_name)

        if action == "merge":
            if not from_branch:
                return "Error: 需要提供 from_branch 参数"
            return await self._merge(from_branch, to_branch)

        if action == "log":
            return await self._log(file)

        if action == "diff":
            return await self._diff(file, commit)

        if action == "checkout":
            if not commit and not branch_name:
                return "Error: 需要提供 commit 或 branch_name 参数"
            return await self._checkout(commit, branch_name)

        if action == "list_branches":
            return await self._list_branches()

        return f"Error: 未知操作 {action}"

    async def _init(self) -> str:
        """初始化策略仓库"""
        # 确保 .gitignore 存在
        gitignore = os.path.join(self.STRATEGY_DIR, ".gitignore")
        if not os.path.exists(gitignore):
            with open(gitignore, "w") as f:
                f.write("backtest_results/\n__pycache__/\n*.pyc\n")

        return f"✅ 策略仓库已初始化: {self.STRATEGY_DIR}"

    async def _status(self) -> str:
        """查看状态"""
        result = self._run_git(["status", "--short"])
        branch = self._run_git(["branch", "--show-current"])

        output = [f"当前分支: {branch}"]
        if not result:
            output.append("\n工作区干净，无待提交变更")
        else:
            output.append(f"\n当前变更:\n{result}")

        return "\n".join(output)

    async def _commit(self, message: str, file: Optional[str]) -> str:
        """提交"""
        # 添加文件
        if file:
            self._run_git(["add", file])
        else:
            self._run_git(["add", "-A"])

        # 检查是否有变更
        status = self._run_git(["status", "--short"])
        if not status:
            return "没有需要提交的变更"

        # 提交
        result = self._run_git(["commit", "-m", message])
        return f"✅ 提交成功:\n{message}"

    async def _branch(self, branch_name: str) -> str:
        """创建分支"""
        # 检查分支是否已存在
        branches = self._run_git(["branch", "-a"])
        if branch_name in branches or f"remotes/origin/{branch_name}" in branches:
            # 切换到已存在的分支
            result = self._run_git(["checkout", branch_name])
            return f"✅ 切换到分支: {branch_name}"

        # 创建并切换新分支
        result = self._run_git(["checkout", "-b", branch_name])
        return f"✅ 创建并切换到分支: {branch_name}"

    async def _merge(self, from_branch: str, to_branch: Optional[str]) -> str:
        """合并分支"""
        target = to_branch or "main"

        # 先切换到目标分支
        self._run_git(["checkout", target])

        # 合并
        result = self._run_git(["merge", from_branch])
        return f"✅ {from_branch} 已合并到 {target}"

    async def _log(self, file: Optional[str]) -> str:
        """查看历史"""
        args = ["log", "--oneline", "-20"]
        if file:
            args.extend(["--", file])

        result = self._run_git(args)
        if not result:
            return "无提交历史"

        # 获取详细历史
        details = self._run_git(["log", "--oneline", "--graph", "-10"])
        return f"最近提交:\n{details}"

    async def _diff(self, file: Optional[str], commit: Optional[str]) -> str:
        """查看差异"""
        args = ["diff"]
        if commit:
            args.append(commit)
        if file:
            args.extend(["--", file])

        result = self._run_git(args)
        if not result:
            return "无差异"

        # 限制输出长度
        return f"差异:\n{result[:3000]}"

    async def _checkout(self, commit: Optional[str], branch_name: Optional[str]) -> str:
        """切换版本"""
        if branch_name:
            result = self._run_git(["checkout", branch_name])
        else:
            result = self._run_git(["checkout", commit])

        return f"✅ 已切换到: {branch_name or commit}"

    async def _list_branches(self) -> str:
        """列出所有分支"""
        local = self._run_git(["branch"])
        remote = self._run_git(["branch", "-r"])

        output = ["本地分支:"]
        output.append(local if local else "  (无)")
        output.append("\n远程分支:")
        output.append(remote if remote else "  (无)")

        return "\n".join(output)
