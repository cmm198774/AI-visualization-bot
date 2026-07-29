"""
Redis 持久化存储模块
提供 LangGraph checkpointer 的 Redis 实现，支持 per-user 对话状态隔离。
"""
import pickle
from typing import Any, Iterator, Optional, Sequence

import redis
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
)

from sys_logger import setup_global_logger


# ==========================================
# 模块级 logger
# ==========================================
logger = setup_global_logger()


# ==========================================
# RedisSaver 类
# ==========================================
class RedisSaver(BaseCheckpointSaver):
    """
    基于 Redis 的 LangGraph checkpoint 存储。
    使用 thread_id 作为主键，支持多用户对话状态隔离。
    支持自动清理旧 checkpoints，防止数据无限增长。
    """

    # ==========================================
    # 初始化
    # ==========================================
    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        *,
        prefix: str = "langgraph",
        max_checkpoints: int = 5,
    ):
        """
        初始化 RedisSaver。

        Args:
            redis_url: Redis 服务器地址 (str)
            prefix: Redis 键前缀 (str)，默认 "langgraph"
            max_checkpoints: 每个 thread 最多保留的 checkpoint 数量 (int)，默认 5
        """
        super().__init__()
        # 使用 RESP2 协议（兼容 Redis 5.0）
        self.client = redis.from_url(redis_url, protocol=2)
        self.prefix = prefix
        self.max_checkpoints = max_checkpoints

    # ==========================================
    # 生成 Redis 键名
    # ==========================================
    def _get_checkpoint_key(self, thread_id: str, checkpoint_id: str) -> str:
        """
        生成 checkpoint 的 Redis 键。

        Args:
            thread_id: 线程 ID (str)
            checkpoint_id: checkpoint ID (str)

        Returns:
            str: Redis 键
        """
        return f"{self.prefix}:checkpoint:{thread_id}:{checkpoint_id}"

    def _get_writes_key(self, thread_id: str, checkpoint_id: str, task_id: str) -> str:
        """
        生成 writes 的 Redis 键。

        Args:
            thread_id: 线程 ID (str)
            checkpoint_id: checkpoint ID (str)
            task_id: 任务 ID (str)

        Returns:
            str: Redis 键
        """
        return f"{self.prefix}:writes:{thread_id}:{checkpoint_id}:{task_id}"

    def _get_index_key(self, thread_id: str) -> str:
        """
        生成 checkpoint 索引列表的 Redis 键。

        Args:
            thread_id: 线程 ID (str)

        Returns:
            str: Redis 键
        """
        return f"{self.prefix}:index:{thread_id}"

    # ==========================================
    # 清理旧 checkpoints
    # ==========================================
    def _cleanup_old_checkpoints(self, thread_id: str) -> None:
        """
        清理旧的 checkpoints，只保留最近的 max_checkpoints 个。

        Args:
            thread_id: 线程 ID (str)
        """
        index_key = self._get_index_key(thread_id)
        all_ids = self.client.lrange(index_key, 0, -1)

        if len(all_ids) <= self.max_checkpoints:
            return

        old_ids = all_ids[self.max_checkpoints:]
        logger.debug(f"清理旧 checkpoints: 保留 {self.max_checkpoints} 个，删除 {len(old_ids)} 个")

        for cp_id_bytes in old_ids:
            checkpoint_id = cp_id_bytes.decode("utf-8")
            cp_key = self._get_checkpoint_key(thread_id, checkpoint_id)
            self.client.delete(cp_key)

            writes_prefix = f"{self.prefix}:writes:{thread_id}:{checkpoint_id}"
            for writes_key in self.client.scan_iter(f"{writes_prefix}:*"):
                self.client.delete(writes_key)

        self.client.ltrim(index_key, 0, self.max_checkpoints - 1)

    # ==========================================
    # 加载 checkpoint
    # ==========================================
    def get_tuple(self, config: RunnableConfig) -> Optional[CheckpointTuple]:
        """
        根据 config 加载最新的 checkpoint。

        Args:
            config: 配置，包含 thread_id 和可选的 checkpoint_id (RunnableConfig)

        Returns:
            Optional[CheckpointTuple]: checkpoint 元组，不存在返回 None
        """
        thread_id = config["configurable"]["thread_id"]
        checkpoint_id = config["configurable"].get("checkpoint_id")

        if checkpoint_id:
            key = self._get_checkpoint_key(thread_id, checkpoint_id)
            data = self.client.get(key)
            if not data:
                return None
            checkpoint, metadata = pickle.loads(data)
        else:
            index_key = self._get_index_key(thread_id)
            checkpoint_ids = self.client.lrange(index_key, 0, 0)
            if not checkpoint_ids:
                return None
            checkpoint_id = checkpoint_ids[0].decode("utf-8")
            key = self._get_checkpoint_key(thread_id, checkpoint_id)
            data = self.client.get(key)
            if not data:
                return None
            checkpoint, metadata = pickle.loads(data)

        # 获取 pending_writes
        pending_writes = []
        writes_prefix = f"{self.prefix}:writes:{thread_id}:{checkpoint_id}"
        for key in self.client.scan_iter(f"{writes_prefix}:*"):
            writes_data = self.client.get(key)
            if writes_data:
                loaded_writes = pickle.loads(writes_data)
                for write in loaded_writes:
                    if len(write) == 2:
                        task_id = key.decode("utf-8").split(":")[-1]
                        channel, value = write
                        pending_writes.append((task_id, channel, value))
                    else:
                        pending_writes.append(write)

        result_config = {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_id": checkpoint_id,
            }
        }

        parent_checkpoint_id = metadata.get("parent_id")
        parent_config = None
        if parent_checkpoint_id:
            parent_config = {
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_id": parent_checkpoint_id,
                }
            }

        return CheckpointTuple(
            config=result_config,
            checkpoint=checkpoint,
            metadata=metadata,
            parent_config=parent_config,
            pending_writes=pending_writes if pending_writes else None,
        )

    # ==========================================
    # 保存 checkpoint
    # ==========================================
    def put(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        """
        保存 checkpoint 到 Redis。

        Args:
            config: 配置，包含 thread_id (RunnableConfig)
            checkpoint: 要保存的 checkpoint (Checkpoint)
            metadata: checkpoint 元数据 (CheckpointMetadata)
            new_versions: 新的 channel 版本 (ChannelVersions)

        Returns:
            RunnableConfig: 更新后的配置
        """
        thread_id = config["configurable"]["thread_id"]
        checkpoint_id = checkpoint["id"]

        # 保存 parent_id
        parent_checkpoint_id = config["configurable"].get("checkpoint_id")
        if parent_checkpoint_id:
            metadata["parent_id"] = parent_checkpoint_id

        # 序列化并保存
        key = self._get_checkpoint_key(thread_id, checkpoint_id)
        data = pickle.dumps((checkpoint, dict(metadata)))
        self.client.set(key, data)

        # 更新索引
        index_key = self._get_index_key(thread_id)
        self.client.lpush(index_key, checkpoint_id)

        # 清理旧数据
        self._cleanup_old_checkpoints(thread_id)

        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_id": checkpoint_id,
            }
        }

    # ==========================================
    # 保存中间写入
    # ==========================================
    def put_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        """
        保存中间写入数据（工具调用结果等）。

        Args:
            config: 配置，包含 thread_id 和 checkpoint_id (RunnableConfig)
            writes: 要保存的写入列表 (Sequence[tuple[str, Any]])
            task_id: 任务 ID (str)
            task_path: 任务路径 (str)
        """
        thread_id = config["configurable"]["thread_id"]
        checkpoint_id = config["configurable"]["checkpoint_id"]

        key = self._get_writes_key(thread_id, checkpoint_id, task_id)
        writes_with_task_id = [(task_id, channel, value) for channel, value in writes]

        existing = self.client.get(key)
        if existing:
            current_writes = pickle.loads(existing)
            current_writes.extend(writes_with_task_id)
            self.client.set(key, pickle.dumps(current_writes))
        else:
            self.client.set(key, pickle.dumps(writes_with_task_id))

    # ==========================================
    # 列出 checkpoints
    # ==========================================
    def list(
        self,
        config: Optional[RunnableConfig],
        *,
        filter: Optional[dict[str, Any]] = None,
        before: Optional[RunnableConfig] = None,
        limit: Optional[int] = None,
    ) -> Iterator[CheckpointTuple]:
        """
        列出指定 thread 的所有 checkpoints。

        Args:
            config: 配置，包含 thread_id (Optional[RunnableConfig])
            filter: 过滤条件 (Optional[dict])
            before: 在此 checkpoint 之前的 (Optional[RunnableConfig])
            limit: 最大返回数量 (Optional[int])

        Yields:
            CheckpointTuple: checkpoint 元组
        """
        if not config:
            return

        thread_id = config["configurable"]["thread_id"]
        index_key = self._get_index_key(thread_id)
        checkpoint_ids = self.client.lrange(index_key, 0, -1)

        count = 0
        for cp_id_bytes in checkpoint_ids:
            if limit and count >= limit:
                break

            checkpoint_id = cp_id_bytes.decode("utf-8")

            if before:
                before_id = before["configurable"].get("checkpoint_id")
                if before_id and checkpoint_id != before_id:
                    continue
                elif before_id and checkpoint_id == before_id:
                    before = None
                    continue

            key = self._get_checkpoint_key(thread_id, checkpoint_id)
            data = self.client.get(key)
            if not data:
                continue

            checkpoint, metadata = pickle.loads(data)

            if filter:
                match = all(metadata.get(k) == v for k, v in filter.items())
                if not match:
                    continue

            result_config = {
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_id": checkpoint_id,
                }
            }

            parent_checkpoint_id = metadata.get("parent_id")
            parent_config = None
            if parent_checkpoint_id:
                parent_config = {
                    "configurable": {
                        "thread_id": thread_id,
                        "checkpoint_id": parent_checkpoint_id,
                    }
                }

            yield CheckpointTuple(
                config=result_config,
                checkpoint=checkpoint,
                metadata=metadata,
                parent_config=parent_config,
                pending_writes=None,
            )
            count += 1

    # ==========================================
    # 异步方法（委托给同步方法，Redis 操作足够快）
    # ==========================================
    async def aget_tuple(self, config: RunnableConfig) -> Optional[CheckpointTuple]:
        """异步版本的 get_tuple"""
        return self.get_tuple(config)

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        """异步版本的 put"""
        return self.put(config, checkpoint, metadata, new_versions)

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        """异步版本的 put_writes"""
        return self.put_writes(config, writes, task_id, task_path)

    async def alist(
        self,
        config: Optional[RunnableConfig],
        *,
        filter: Optional[dict[str, Any]] = None,
        before: Optional[RunnableConfig] = None,
        limit: Optional[int] = None,
    ):
        """异步版本的 list"""
        for item in self.list(config, filter=filter, before=before, limit=limit):
            yield item

    # ==========================================
    # 清除用户所有 checkpoints
    # ==========================================
    def clear_thread(self, thread_id: str) -> int:
        """
        清除指定用户的所有 checkpoints 和相关数据。

        Args:
            thread_id: 线程 ID (str)

        Returns:
            int: 删除的 checkpoint 数量
        """
        # 获取 checkpoint 列表
        index_key = self._get_index_key(thread_id)
        checkpoint_ids = self.client.lrange(index_key, 0, -1)
        count = len(checkpoint_ids)

        if count == 0:
            # 即使没有 checkpoints，也清除 mood_override
            self.clear_mood_override(thread_id)
            return 0

        # 删除所有 checkpoints
        for cp_id_bytes in checkpoint_ids:
            checkpoint_id = cp_id_bytes.decode("utf-8")
            cp_key = self._get_checkpoint_key(thread_id, checkpoint_id)
            self.client.delete(cp_key)

            # 删除 writes
            writes_prefix = f"{self.prefix}:writes:{thread_id}:{checkpoint_id}"
            for writes_key in self.client.scan_iter(f"{writes_prefix}:*"):
                self.client.delete(writes_key)

        # 删除索引
        self.client.delete(index_key)

        # 删除 mood_override
        self.clear_mood_override(thread_id)

        logger.info(f"清除用户 {thread_id} 的所有 checkpoints: {count} 个")
        return count

    # ==========================================
    # 情绪覆盖操作
    # ==========================================
    def set_mood_override(self, thread_id: str, mood: str) -> None:
        """
        设置情绪覆盖值。

        Args:
            thread_id: 线程 ID (str)
            mood: 情绪标签 (str)
        """
        key = f"{self.prefix}:mood_override:{thread_id}"
        self.client.set(key, mood)
        logger.info(f"设置用户 {thread_id} 情绪覆盖: {mood}")

    def get_mood_override(self, thread_id: str) -> Optional[str]:
        """
        获取情绪覆盖值。

        Args:
            thread_id: 线程 ID (str)

        Returns:
            Optional[str]: 情绪标签，无则返回 None
        """
        key = f"{self.prefix}:mood_override:{thread_id}"
        value = self.client.get(key)
        return value.decode("utf-8") if value else None

    def clear_mood_override(self, thread_id: str) -> None:
        """
        清除情绪覆盖。

        Args:
            thread_id: 线程 ID (str)
        """
        key = f"{self.prefix}:mood_override:{thread_id}"
        self.client.delete(key)
        logger.debug(f"清除用户 {thread_id} 情绪覆盖")

    # ==========================================
    # 获取 checkpoints 列表
    # ==========================================
    def get_checkpoints(self, thread_id: str) -> list:
        """
        获取用户的所有 checkpoints（元数据）。

        Args:
            thread_id: 线程 ID (str)

        Returns:
            list: checkpoint 元数据列表
        """
        index_key = self._get_index_key(thread_id)
        checkpoint_ids = self.client.lrange(index_key, 0, -1)

        checkpoints = []
        for cp_id_bytes in checkpoint_ids:
            checkpoint_id = cp_id_bytes.decode("utf-8")
            key = self._get_checkpoint_key(thread_id, checkpoint_id)
            data = self.client.get(key)
            if data:
                checkpoint, metadata = pickle.loads(data)
                checkpoints.append({
                    "checkpoint_id": checkpoint_id,
                    "checkpoint": checkpoint,
                    "metadata": metadata,
                })

        return checkpoints
