"""实验调度器 - 负责任务分发和运行"""

import asyncio
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Awaitable, Any

from experiment_docker.orchestrator.config import ExperimentConfig, ExperimentResult
from experiment_docker.orchestrator.batch_executor import execute_in_batches


class ExperimentOrchestrator:
    """实验调度器 - 支持多种运行模式"""

    MODES = ["docker-sdk", "cli", "local"]

    def __init__(
        self,
        base_dir: Path,
        max_concurrent: int = 4,
        mode: str = "cli",
        image_name: str = "nanobot:experiment",
    ):
        if mode not in self.MODES:
            raise ValueError(f"mode must be one of {self.MODES}")

        self.base_dir = Path(base_dir)
        self.max_concurrent = max_concurrent
        self.mode = mode
        self.image_name = image_name

        self.results_dir = self.base_dir / "results"
        self.raw_dir = self.results_dir / "raw"
        self.report_dir = self.results_dir / "report"
        self.shared_configs = self.base_dir / "shared" / "configs"
        self.shared_data = self.base_dir / "shared" / "data"

        for d in [self.results_dir, self.raw_dir, self.report_dir]:
            d.mkdir(parents=True, exist_ok=True)

        self._docker_client = None

    def _get_docker_client(self):
        """延迟初始化 Docker client"""
        if self._docker_client is None:
            import docker
            self._docker_client = docker.from_env()
        return self._docker_client

    def _is_docker_available(self) -> bool:
        """检查 docker 命令是否可用"""
        try:
            result = subprocess.run(
                ["docker", "info"],
                capture_output=True,
                timeout=5,
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

    def build_image(self, force: bool = False) -> None:
        """构建 Docker 镜像"""
        if self.mode == "local":
            print("Local mode: skipping Docker image build")
            return

        if not self._is_docker_available():
            print("Warning: Docker not available, falling back to local mode")
            self.mode = "local"
            return

        dockerfile_path = self.base_dir / "Dockerfile"
        if not dockerfile_path.exists():
            raise FileNotFoundError(f"Dockerfile not found at {dockerfile_path}")

        if self.mode == "cli":
            if force:
                subprocess.run(["docker", "rmi", "-f", self.image_name],
                             capture_output=True, check=False)

            print(f"Building Docker image: {self.image_name}")
            subprocess.run([
                "docker", "build",
                "-t", self.image_name,
                "-f", str(dockerfile_path),
                str(self.base_dir.parent),
            ], check=True)
            print(f"Image built successfully: {self.image_name}")

        elif self.mode == "docker-sdk":
            client = self._get_docker_client()
            if force:
                try:
                    client.images.remove(self.image_name, force=True)
                except Exception:
                    pass

            print(f"Building Docker image: {self.image_name}")
            client.images.build(
                path=str(self.base_dir.parent),
                dockerfile=str(dockerfile_path.relative_to(self.base_dir.parent)),
                tag=self.image_name,
                rm=True,
            )
            print(f"Image built successfully: {self.image_name}")

    def _get_container_name(self, config: ExperimentConfig) -> str:
        """生成容器名称"""
        return f"nanobot_exp_{config.full_key}"

    def _prepare_env_vars(self, config: ExperimentConfig) -> dict:
        """准备环境变量"""
        return {
            "SESSION_KEY": config.session_key,
            "MEMORY_CONFIG": config.memory_config,
            "TOOL_CONFIG": config.tool_config,
            "TASK_NAME": config.task_name,
            "NANOBOT_MODEL": config.model,
            "RESULT_DIR": str(self.raw_dir / config.session_key),
            "LOG_LEVEL": "INFO",
            # 关键：为每个实验设置独立的工作空间
            "NANOBOT_WORKSPACE": f"/root/.nanobot/workspaces/{config.session_key}",
        }

    def _prepare_volumes(self, config: ExperimentConfig) -> dict:
        """准备卷挂载 - 为每个实验创建独立的 workspace"""
        # 创建日志目录
        log_path = self.raw_dir / config.session_key
        log_path.mkdir(parents=True, exist_ok=True)
        
        # 创建独立的 workspace 目录（关键：上下文隔离）
        workspace_path = self.base_dir / "workspaces" / config.session_key
        workspace_path.mkdir(parents=True, exist_ok=True)
        
        # 创建 memory 子目录
        memory_dir = workspace_path / "memory"
        memory_dir.mkdir(parents=True, exist_ok=True)
        
        # 创建空的 MEMORY.md 和 HISTORY.md（如果不存在）
        (memory_dir / "MEMORY.md").touch()
        (memory_dir / "HISTORY.md").touch()
        
        # 创建 skills 子目录
        skills_dir = workspace_path / "skills"
        skills_dir.mkdir(parents=True, exist_ok=True)
        
        # 复制共享配置文件到 workspace
        config_file = self._get_config_file(config)
        if config_file and config_file.exists():
            import shutil
            target_config = workspace_path / "config.json"
            if not target_config.exists():
                shutil.copy2(config_file, target_config)
        
        return {
            str(log_path): {"bind": "/app/personal/logs", "mode": "rw"},
            str(workspace_path): {"bind": f"/root/.nanobot/workspaces/{config.session_key}", "mode": "rw"},
        }

    def _get_config_file(self, config: ExperimentConfig) -> Optional[Path]:
        """获取配置文件路径"""
        config_map = {
            ("VR", "CG"): "Agent_VR_CG.json",
            ("VR", "FG"): "Agent_VR_FG.json",
            ("SW", "CG"): "Agent_SW_CG.json",
            ("SW", "FG"): "Agent_SW_FG.json",
        }
        config_file = config_map.get((config.memory_config, config.tool_config))
        if config_file:
            return self.shared_configs / config_file
        return None

    async def run_single_experiment(
        self,
        config: ExperimentConfig,
        timeout: int = 1800,
    ) -> ExperimentResult:
        """运行单个实验"""
        start_time = time.time()
        error_message = None

        effective_mode = self.mode
        if effective_mode == "cli" and not self._is_docker_available():
            print(f"Warning: Docker not available for {config.session_key}, falling back to local mode")
            effective_mode = "local"

        try:
            if effective_mode == "local":
                result = await self._run_local(config, timeout)
            elif effective_mode == "cli":
                result = await self._run_cli(config, timeout)
            elif effective_mode == "docker-sdk":
                result = await self._run_docker_sdk(config, timeout)
            else:
                raise ValueError(f"Unknown mode: {effective_mode}")

            return result

        except Exception as e:
            error_message = str(e)
            return ExperimentResult(
                session_key=config.session_key,
                memory_config=config.memory_config,
                tool_config=config.tool_config,
                task_name=config.task_name,
                model=config.model,
                success=False,
                total_tokens=0,
                prompt_tokens=0,
                completion_tokens=0,
                request_count=0,
                execution_time=time.time() - start_time,
                estimated_tokens=0,
                error_message=error_message,
            )

    async def run_experiments_in_batches(
        self,
        configs: List[ExperimentConfig],
        timeout: int = 1800,
        batch_size: int = 10,
        delay_between_batches: float = 2.0,
    ) -> List[ExperimentResult]:
        """
        分批执行多个实验，避免超时
        
        Args:
            configs: 实验配置列表
            timeout: 每个实验的超时时间（秒）
            batch_size: 每批实验数量（默认 10 个）
            delay_between_batches: 批次间延迟秒数（默认 2 秒）
        
        Returns:
            所有实验的结果列表
        """
        print(f"\n{'='*80}")
        print(f"分批执行实验：共 {len(configs)} 个实验，每批 {batch_size} 个")
        print(f"超时设置：{timeout}秒/实验")
        print(f"{'='*80}\n")
        
        # 创建任务函数
        async def run_single(config: ExperimentConfig) -> ExperimentResult:
            return await self.run_single_experiment(config, timeout)
        
        # 创建任务列表
        tasks = [run_single(config) for config in configs]
        
        # 分批执行
        raw_results = await execute_in_batches(
            tasks,
            batch_size=batch_size,
            delay_between_batches=delay_between_batches
        )
        
        # 处理异常，转换为 ExperimentResult
        results = []
        for i, result in enumerate(raw_results):
            if isinstance(result, Exception):
                # 如果任务是异常，创建失败的 ExperimentResult
                config = configs[i] if i < len(configs) else None
                results.append(ExperimentResult(
                    session_key=config.session_key if config else f"unknown_{i}",
                    memory_config=config.memory_config if config else "UNKNOWN",
                    tool_config=config.tool_config if config else "UNKNOWN",
                    task_name=config.task_name if config else "UNKNOWN",
                    model=config.model if config else "UNKNOWN",
                    success=False,
                    total_tokens=0,
                    prompt_tokens=0,
                    completion_tokens=0,
                    request_count=0,
                    execution_time=0.0,
                    estimated_tokens=0,
                    error_message=str(result),
                ))
            else:
                results.append(result)
        
        # 统计结果
        success_count = sum(1 for r in results if r.success)
        print(f"\n{'='*80}")
        print(f"执行完成：{success_count}/{len(results)} 成功")
        print(f"{'='*80}\n")
        
        return results

    async def _run_local(
        self,
        config: ExperimentConfig,
        timeout: int,
    ) -> ExperimentResult:
        """本地模式：直接使用 Provider 调用 LLM API"""
        start_time = time.time()
        
        try:
            from nanobot.providers import set_current_session_config
            from nanobot.providers.openai_compat_provider import OpenAICompatProvider
        except ImportError as e:
            return ExperimentResult(
                session_key=config.session_key,
                memory_config=config.memory_config,
                tool_config=config.tool_config,
                task_name=config.task_name,
                model=config.model,
                success=False,
                total_tokens=0,
                prompt_tokens=0,
                completion_tokens=0,
                request_count=0,
                execution_time=0.0,
                estimated_tokens=0,
                error_message=f"Failed to import nanobot: {e}",
            )

        log_path = self.raw_dir / config.session_key
        log_path.mkdir(parents=True, exist_ok=True)

        # 设置会话配置
        session_config = {
            "session_key": config.session_key,
            "api_type": self._get_provider_type(config.model),
        }
        set_current_session_config(session_config)

        task_content = self._get_task_content(config.task_name)
        
        # 估算 token 数量
        estimated_tokens = self._estimate_tokens(task_content)
        print(f"[{config.session_key}] 估算 tokens: {estimated_tokens}")

        try:
            provider = OpenAICompatProvider()
            messages = [
                {"role": "system", "content": "你是一个专业的数据分析助手。请用中文回答。"},
                {"role": "user", "content": task_content}
            ]
            
            response = await provider.chat(messages=messages, max_tokens=8000)
            
            # 从 response 中读取 token 使用
            total_tokens = response.usage.get("total_tokens", 0) if response.usage else 0
            prompt_tokens = response.usage.get("prompt_tokens", 0) if response.usage else 0
            completion_tokens = response.usage.get("completion_tokens", 0) if response.usage else 0
            request_count = 1
            
            success = total_tokens > 0
            print(f"[{config.session_key}] [OK] 成功 | Tokens: {total_tokens}")

        except Exception as e:
            success = False
            total_tokens = 0
            prompt_tokens = 0
            completion_tokens = 0
            request_count = 0
            print(f"[{config.session_key}] [ERROR] {e}")
            
        finally:
            set_current_session_config(None)

        execution_time = time.time() - start_time

        return ExperimentResult(
            session_key=config.session_key,
            memory_config=config.memory_config,
            tool_config=config.tool_config,
            task_name=config.task_name,
            model=config.model,
            success=success,
            total_tokens=total_tokens,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            request_count=request_count,
            execution_time=execution_time,
            estimated_tokens=estimated_tokens,
        )

    def _get_provider_type(self, model: str) -> str:
        """根据模型名获取 provider 类型"""
        if "deepseek" in model:
            return "deepseek"
        elif "qwen" in model or "dashscope" in model.lower():
            return "dashscope"
        elif "kimi" in model or "moonshot" in model.lower():
            return "moonshot"
        else:
            return "deepseek"  # 默认

    async def _run_cli(
        self,
        config: ExperimentConfig,
        timeout: int,
    ) -> ExperimentResult:
        """CLI 模式：使用 docker 命令行"""
        start_time = time.time()
        
        container_name = self._get_container_name(config)
        log_path = self.raw_dir / config.session_key
        log_path.mkdir(parents=True, exist_ok=True)

        env = self._prepare_env_vars(config)
        volume_src = str(log_path)
        volume_dst = "/app/personal/logs"

        # 获取任务内容并估算 token
        task_content = self._get_task_content(config.task_name)
        estimated_tokens = self._estimate_tokens(task_content)
        print(f"[{config.session_key}] 估算 tokens: {estimated_tokens}")

        cmd = [
            "docker", "run",
            "--name", container_name,
            "-e", f"SESSION_KEY={config.session_key}",
            "-e", f"MEMORY_CONFIG={config.memory_config}",
            "-e", f"TOOL_CONFIG={config.tool_config}",
            "-e", f"TASK_NAME={config.task_name}",
            "-e", f"NANOBOT_MODEL={config.model}",
            "-v", f"{volume_src}:{volume_dst}",
            "--rm",
            self.image_name,
        ]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            exit_code = proc.returncode
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            return ExperimentResult(
                session_key=config.session_key,
                memory_config=config.memory_config,
                tool_config=config.tool_config,
                task_name=config.task_name,
                model=config.model,
                success=False,
                total_tokens=0,
                prompt_tokens=0,
                completion_tokens=0,
                request_count=0,
                execution_time=timeout,
                estimated_tokens=estimated_tokens,
                error_message="Timeout",
            )

        logs = stdout.decode("utf-8", errors="replace")
        log_file = log_path / "experiment.log"
        log_file.write_text(logs)

        # 从日志目录读取 token 统计（优先从 token_usage 文件读取）
        total_tokens, prompt_tokens, completion_tokens, request_count = self._read_tokens_from_log(log_path)
        
        # 如果 token_usage 文件不存在，尝试从日志中解析
        if total_tokens == 0:
            total_tokens, request_count = self._parse_tokens_from_logs(logs)
            prompt_tokens = 0
            completion_tokens = 0
        
        success = exit_code == 0 and total_tokens > 0
        execution_time = time.time() - start_time

        return ExperimentResult(
            session_key=config.session_key,
            memory_config=config.memory_config,
            tool_config=config.tool_config,
            task_name=config.task_name,
            model=config.model,
            success=success,
            total_tokens=total_tokens,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            request_count=request_count,
            execution_time=execution_time,
            estimated_tokens=estimated_tokens,
        )

    async def _run_docker_sdk(
        self,
        config: ExperimentConfig,
        timeout: int,
    ) -> ExperimentResult:
        """Docker SDK 模式：使用 docker Python SDK"""
        start_time = time.time()
        
        client = self._get_docker_client()
        container_name = self._get_container_name(config)

        env = self._prepare_env_vars(config)
        volumes = self._prepare_volumes(config)
        
        # 获取任务内容并估算 token
        task_content = self._get_task_content(config.task_name)
        estimated_tokens = self._estimate_tokens(task_content)
        print(f"[{config.session_key}] 估算 tokens: {estimated_tokens}")

        try:
            container = client.containers.run(
                image=self.image_name,
                name=container_name,
                environment=env,
                volumes=volumes,
                detach=True,
                remove=False,
                mem_limit="2g",
                cpus=2,
            )

            result = container.wait(timeout=timeout)
            exit_code = result.get("StatusCode", -1)

            logs = container.logs(stdout=True, stderr=True).decode("utf-8")
            log_file = self.raw_dir / config.session_key / "experiment.log"
            log_file.parent.mkdir(parents=True, exist_ok=True)
            log_file.write_text(logs)

            container.remove(force=True)

            # 从日志目录读取 token 统计（优先从 token_usage 文件读取）
            log_path = self.raw_dir / config.session_key
            total_tokens, prompt_tokens, completion_tokens, request_count = self._read_tokens_from_log(log_path)
            
            # 如果 token_usage 文件不存在，尝试从日志中解析
            if total_tokens == 0:
                total_tokens, request_count = self._parse_tokens_from_logs(logs)
                prompt_tokens = 0
                completion_tokens = 0
            
            success = exit_code == 0 and total_tokens > 0

        except Exception as e:
            return ExperimentResult(
                session_key=config.session_key,
                memory_config=config.memory_config,
                tool_config=config.tool_config,
                task_name=config.task_name,
                model=config.model,
                success=False,
                total_tokens=0,
                prompt_tokens=0,
                completion_tokens=0,
                request_count=0,
                execution_time=timeout,
                estimated_tokens=estimated_tokens,
                error_message=str(e),
            )

        execution_time = time.time() - start_time

        return ExperimentResult(
            session_key=config.session_key,
            memory_config=config.memory_config,
            tool_config=config.tool_config,
            task_name=config.task_name,
            model=config.model,
            success=success,
            total_tokens=total_tokens,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            request_count=request_count,
            execution_time=execution_time,
            estimated_tokens=estimated_tokens,
        )

    def _read_tokens_from_log(self, log_path: Path) -> tuple[int, int, int, int]:
        """从日志目录读取 token 统计"""
        total_tokens = 0
        prompt_tokens = 0
        completion_tokens = 0
        request_count = 0

        # 查找所有 token 使用记录文件
        token_files = list(log_path.glob("*token_usage*.txt")) + list(log_path.glob("*token_usage*.json"))
        
        for token_file in token_files:
            if token_file.exists():
                try:
                    content = token_file.read_text(encoding="utf-8")
                    # 尝试按行解析 JSONL 格式
                    for line in content.strip().split("\n"):
                        if line.strip():
                            try:
                                record = json.loads(line)
                                total_tokens += record.get("total_tokens", 0)
                                prompt_tokens += record.get("prompt_tokens", 0)
                                completion_tokens += record.get("completion_tokens", 0)
                                request_count += 1
                            except json.JSONDecodeError:
                                pass
                except Exception as e:
                    print(f"Warning: Failed to read token file {token_file}: {e}")

        return total_tokens, prompt_tokens, completion_tokens, request_count

    def _parse_tokens_from_logs(self, logs: str) -> tuple[int, int]:
        """从日志字符串中解析 token 统计"""
        total_tokens = 0
        request_count = 0

        for line in logs.split("\n"):
            if "total_tokens" in line and line.strip().startswith("{"):
                try:
                    record = json.loads(line)
                    total_tokens += record.get("total_tokens", 0)
                    request_count += 1
                except json.JSONDecodeError:
                    pass

        return total_tokens, request_count

    def _get_task_content(self, task_name: str) -> str:
        """获取任务内容（从共享数据目录读取）"""
        data_dir = self.shared_data
        if not data_dir.exists():
            return f"Task: {task_name}\nPlease process the data."

        # 新任务映射（4 个新任务）
        task_map = {
            "Task1_Sales": ("sales.csv", "销售数据分析"),
            "Task2_User": ("user_behavior.csv", "用户行为分析"),
            "Task3_Finance": ("financial.csv", "财务数据清洗"),
            "Task4_Review": ("reviews.csv", "评论情感分析"),
            # 兼容旧任务
            "Task1": ("income.csv", "收入数据分析"),
            "Task2": ("clean.csv", "数据清洗"),
            "Task4": ("preferences.csv", "偏好分析"),
        }

        if task_name in task_map:
            file_name, task_desc = task_map[task_name]
            csv_file = data_dir / file_name
            if csv_file.exists():
                content = csv_file.read_text(encoding="utf-8")
                
                # 为每个任务定义具体的分析指令
                task_instructions = {
                    "Task1_Sales": """请分析这份销售数据，包括：
1. 计算总销售额和总销售量
2. 按产品类别分析销售表现
3. 识别销售趋势（按月）
4. 比较不同地区的销售情况
5. 分析企业客户和个人客户的购买行为差异

请提供详细的分析报告和关键洞察。""",
                    
                    "Task2_User": """请分析这份用户行为数据，包括：
1. 计算平均停留时长和点击次数
2. 分析不同页面类型的用户参与度
3. 识别用户活跃时段（上午/下午/晚上）
4. 比较不同设备类型的用户行为
5. 找出用户流失的关键页面

请提供详细的分析报告和优化建议。""",
                    
                    "Task3_Finance": """请清洗这份财务数据，包括：
1. 填补缺失的金额数据（使用合理方法）
2. 检测并处理异常值（如负数收入）
3. 标准化交易状态（完成/处理中）
4. 按类别和账户汇总收支情况
5. 计算每月净收入

请提供清洗后的数据和分析结果。""",
                    
                    "Task4_Review": """请分析这份产品评论数据，包括：
1. 计算平均评分
2. 分析评论的情感倾向（正面/负面/中性）
3. 提取关键词和常见主题
4. 识别用户最满意和最不满意的方面
5. 按评分分组分析评论特征

请提供详细的情感分析报告。""",
                }
                
                instruction = task_instructions.get(task_name, "请分析这份数据。")
                return f"""任务：{task_desc}

数据内容：
{content[:2000]}

{instruction}"""

        return f"Task: {task_name}"

    def _estimate_tokens(self, text: str) -> int:
        """
        估算文本的 token 数量
        
        估算规则（基于中文和英文混合）：
        - 中文字符：每个汉字约 1.5 个 token
        - 英文字符：每 4 个字符约 1 个 token
        - 标点符号：每个约 0.5 个 token
        
        简化估算：总字符数 / 2（适用于中文为主的文本）
        """
        if not text:
            return 0
        
        # 简单估算：中文字符数 + 英文字符数/4
        chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        english_chars = sum(1 for c in text if c.isascii() and c.isalpha())
        
        # 中文约 1.5 token/字，英文约 0.25 token/字符
        estimated = int(chinese_chars * 1.5 + english_chars * 0.25)
        
        # 加上系统 prompt 和指令的固定开销（约 200 tokens）
        estimated += 200
        
        return estimated

    async def run_batch(
        self,
        configs: list[ExperimentConfig],
        repetitions: int = 10,
    ) -> list[ExperimentResult]:
        """批量运行实验"""
        all_configs = []
        for config in configs:
            for rep in range(1, repetitions + 1):
                rep_config = ExperimentConfig(
                    session_key=f"{config.memory_config}_{config.tool_config}_{config.task_name}_rep{rep}",
                    memory_config=config.memory_config,
                    tool_config=config.tool_config,
                    task_name=config.task_name,
                    model=config.model,
                    repetition=rep,
                )
                all_configs.append(rep_config)

        semaphore = asyncio.Semaphore(self.max_concurrent)

        async def run_with_semaphore(c: ExperimentConfig):
            async with semaphore:
                return await self.run_single_experiment(c)

        print(f"Running {len(all_configs)} experiments with {self.max_concurrent} concurrent workers...")
        print(f"Mode: {self.mode}")

        tasks = [run_with_semaphore(c) for c in all_configs]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        valid_results = []
        for r in results:
            if isinstance(r, Exception):
                print(f"Experiment failed: {r}")
            else:
                valid_results.append(r)

        return valid_results

    def save_results(self, results: list[ExperimentResult], filename: Optional[str] = None) -> Path:
        """保存结果到文件"""
        if filename is None:
            filename = f"results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

        output_file = self.raw_dir / filename
        data = {
            "timestamp": datetime.now().isoformat(),
            "total_experiments": len(results),
            "successful": sum(1 for r in results if r.success),
            "results": [r.to_dict() for r in results],
        }
        output_file.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        print(f"Results saved to: {output_file}")
        return output_file


def generate_experiment_configs() -> list[ExperimentConfig]:
    """
    生成 LLM Backend 对比实验配置
    4 个任务 × 4 个 LLM Backend = 16 组实验
    
    任务设计：
    - Task1: 销售数据分析 (sales.csv)
    - Task2: 用户行为分析 (user_behavior.csv)
    - Task3: 财务数据清洗 (financial.csv)
    - Task4: 评论情感分析 (reviews.csv)
    
    LLM Backend:
    - deepseek-chat (DeepSeek)
    - qwen3-max-2026-01-23 (Qwen3-Max)
    - kimi-k2.5 (Kimi2.5)
    - minimax-m1 (MiniMax-M1)
    """
    # 定义 4 个新任务（使用统一的 VR_CG 配置，专注于 LLM 对比）
    tasks = [
        ("Task1_Sales", "sales.csv"),
        ("Task2_User", "user_behavior.csv"),
        ("Task3_Finance", "financial.csv"),
        ("Task4_Review", "reviews.csv"),
    ]
    
    # 定义 4 个 LLM Backend
    llm_backends = [
        ("deepseek-chat", "deepseek"),
        ("qwen3-max", "dashscope"),
        ("kimi-k2.5", "moonshot"),
        ("MiniMax-M1", "minimax"),
    ]
    
    # 生成 16 组实验配置（4 任务 × 4LLM）
    configs = []
    for task_name, data_file in tasks:
        for model, provider in llm_backends:
            # 使用统一的 VR_CG 配置，确保实验变量只有 LLM
            configs.append(ExperimentConfig(
                session_key=f"VR_CG_{task_name}_{model.replace('-', '_')}",
                memory_config="VR",
                tool_config="CG",
                task_name=task_name,
                model=model,
                repetition=1,
            ))
    
    return configs
