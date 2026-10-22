"""AI 评估实时阶段回传（ai_task.progress_stage）。

评估执行链路较长（快照加载 → LLM 调用 → 解析 → 评分换算 → 落库），
前端轮询时只看到 queued/running 两个粗粒度状态。本模块维护五个关键
阶段文案，执行器/worker 在进入每个阶段时把文案写入 ai_task.progress_stage，
GET /ai/evaluation-tasks/{taskId} 原样返回，前端据此展示真实进度
（无 progress_stage 时前端退回本地模拟文案）。

设计约定：
- 阶段文案即对外展示文案，直接存库（VARCHAR(64)），不做 code→text 映射，
  API 无需翻译层，前端无需维护文案表
- set_stage 为 best-effort：进度写库失败只记日志，绝不打断评估主流程
- 仅更新 running 任务（SQL 带 status='running' 条件）：超时看门狗/清理器
  把任务置 failed 后，迟到的进度写回会被丢弃，不污染终态
- 本模块导入无副作用（db 惰性导入），provider 可安全引用阶段常量
"""
from __future__ import annotations

import logging

logger = logging.getLogger("nanshan.ai.progress")

# 五阶段文案（顺序即执行顺序；与前端 ai-eval-detail 展示口径一致）
STAGE_READING = "正在读取成果数据"      # 阶段1：快照加载
STAGE_ANALYZING = "AI正在分析技术内容"  # 阶段2：LLM 调用中
STAGE_REPORT = "正在生成评价报告"       # 阶段3：解析 LLM 输出
STAGE_SCORING = "正在计算综合评分"      # 阶段4：evaluation 模块评分换算
STAGE_SAVING = "正在保存评估结果"       # 阶段5：写入数据库

STAGES = (STAGE_READING, STAGE_ANALYZING, STAGE_REPORT, STAGE_SCORING, STAGE_SAVING)

# 对外暴露的字段别名：API 同时返回 progressStage（驼峰，项目命名约定）
# 与 progress_stage（下划线，与库列/需求文档一致），前端两者取其一即可。


def set_stage(task_id: int, stage: str) -> bool:
    """把指定 running 任务的实时阶段写库。返回是否写入成功。

    best-effort：任何异常只记日志并返回 False，调用方无需 try/except。
    """
    if not isinstance(task_id, int) or task_id <= 0 or not stage:
        return False
    from db import get_cursor  # 惰性导入：保持本模块导入无副作用

    try:
        with get_cursor(commit=True) as cur:
            cur.execute(
                """
                UPDATE ai_task
                SET progress_stage = %s
                WHERE id = %s AND task_type = 'evaluation' AND status = 'running'
                """,
                (stage[:64], task_id),
            )
        return True
    except Exception:
        logger.exception("ai progress update failed task=%s stage=%s", task_id, stage)
        return False
