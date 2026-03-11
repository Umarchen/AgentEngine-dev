import uuid
from sqlalchemy import BigInteger, Boolean, Column, Float, Index, Integer, String, DateTime, Text, func
from sqlalchemy.dialects import mysql
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import declarative_base
Base = declarative_base()

class AgentTypeDBModel(Base):
    __tablename__ = 't_sys_agent_types'
    agent_type_id = Column(String(255), primary_key=True)
    agent_type_name = Column(String(255), nullable=False)
    agent_template_id = Column(String(255))
    create_time = Column(DateTime, default=func.now())
    update_time = Column(DateTime, default=func.now(), onupdate=func.now())


class AgentTemplateDBModel(Base):
    __tablename__ = 't_sys_agent_templates'

    agent_template_id = Column(String(255), primary_key=True)
    agent_type_id = Column(String(255), nullable=False)
    agent_type_name = Column(String(255), nullable=False)
    model_config = Column(Text)  # JSON stored as TEXT
    prompt_config = Column(Text)  # JSON stored as TEXT
    mcp_tool_config = Column(Text)  # JSON stored as TEXT
    mcp_server_config = Column(Text)  # JSON stored as TEXT
    create_time = Column(DateTime, default=func.now())
    update_time = Column(DateTime, default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("agent_template_type_id", agent_type_id),
        Index("agent_template_type_name", agent_type_name),
    )

class AgentConfigDBModel(Base):
    __tablename__ = 't_sys_agents_configs'
    agent_config_id = Column(String(255), primary_key=True)
    agent_id = Column(String(255), nullable=False)
    agent_type_id = Column(String(255), nullable=False)
    agent_type_name = Column(String(255), nullable=False)
    description = Column(Text)
    config_schema = Column(Text)  # JSON格式的配置信息
    create_time = Column(DateTime, default=func.now())
    update_time = Column(DateTime, default=func.now(), onupdate=func.now())
    model_ids = Column(Text)
    prompt_ids = Column(Text)
    mcp_ids = Column(Text)
    mcp_server_ids = Column(Text)

    # 在类属性中直接定义索引：Index('索引名', 字段名.desc())
    __table_args__ = (
        Index("agent_config_agent_id", agent_id),
        Index("agent_config_create_time_desc", create_time.desc()),
    )

class AgentDBModel(Base):
    __tablename__ = 't_sys_agent'
    agent_id = Column(String(255), primary_key=True)
    agent_type_id = Column(String(255), nullable=False)
    agent_type_name = Column(String(255), nullable=False)
    agent_config_id = Column(String(255), nullable=False)
    uptime_seconds = Column(Integer)
    start_time = Column(DateTime)
    create_time = Column(DateTime, default=func.now())
    update_time = Column(DateTime, default=func.now(), onupdate=func.now())

    # 在类属性中直接定义索引：Index('索引名', 字段名.desc())
    __table_args__ = (
        Index("agent_create_time_desc", create_time.desc()),
        Index("agent_config_id_idx", agent_config_id),
    )

class AgentHealthStatusDBModel(Base):
    __tablename__ = 'T_AGENT_STATUS'

    status_id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    agent_id = Column(String(255), nullable=False)
    agent_type_name = Column(String(255), nullable=False)
    agent_status = Column(String(255))
    uptime_seconds = Column(Float)
    start_time = Column(DateTime)
    checked_at = Column(DateTime)
    checks = Column(Text)  # Assuming JSON stored as TEXT

    # 在类属性中直接定义索引：Index('索引名', 字段名.desc())
    __table_args__ = (
        Index("agent_health_status_agent_id", agent_id),
        Index("agent_health_status_checked_at_desc", checked_at.desc()),
    )

class AgentTrajectoryDBModel(Base):
    __tablename__ = 'T_AGENT_TRAJECTORY'

    # 自增ID
    trajectory_id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    agent_id = Column(String(255), nullable=False)
    user_id = Column(String(255), nullable=False)
    session_id = Column(String(255), nullable=False)
    trajectory = Column(Text().with_variant(mysql.LONGTEXT(), "mysql"))  # Assuming JSON stored as TEXT
    evaluation = Column(Text().with_variant(mysql.LONGTEXT(), "mysql"))  # Assuming JSON stored as TEXT
    create_time = Column(DateTime, default=func.now())
    update_time = Column(DateTime, default=func.now(), onupdate=func.now())

    # 在类属性中直接定义索引：Index('索引名', 字段名.desc())
    __table_args__ = (
        Index("agent_trajectory_agent_id", agent_id),
        Index("agent_trajectory_session_id", session_id),
        Index("agent_trajectory_create_time_desc", create_time.desc()),
    )

class AgentTrajectoryEvaluationDBModel(Base):
    """轨迹评估结果表"""
    __tablename__ = 'T_AGENT_TRAJECTORY_EVALUATION'

    # 自增ID
    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    agent_id = Column(String(255), nullable=False)
    user_id = Column(String(255), nullable=False)
    session_id = Column(String(255), nullable=False)
    trajectory = Column(Text().with_variant(mysql.LONGTEXT(), "mysql"), nullable=False)  # JSON格式：汇总后的轨迹数据
    evaluation = Column(Text().with_variant(mysql.LONGTEXT(), "mysql"), nullable=False)  # JSON格式：评估结果(overall + steps)
    evaluated_at = Column(DateTime, default=func.now())
    evaluator_model = Column(String(255))  # 使用的评估模型名称
    evaluation_prompt_version = Column(String(50))  # 评估Prompt版本

    # 在类属性中直接定义索引：Index('索引名', 字段名.desc())
    __table_args__ = (
        Index("evaluation_agent_id", agent_id),
        Index("evaluation_session_id", session_id),
        Index("evaluation_evaluated_at_desc", evaluated_at.desc()),
    )

class AgentTaskDBModel(Base):
    __tablename__ = 't_agent_task'

    # 定义表字段
    task_id = Column(String(255), primary_key=True, default=lambda: str(uuid.uuid4()))  # Agent执行任务ID，主键
    agent_id = Column(String(255), nullable=False)  # Agent ID，关联agent表
    user_id = Column(String(255))  # 预留，可为空
    session_id = Column(String(255), nullable=False)  # 会话ID
    task_status = Column(String(255))  # Task任务执行结果，可为空
    token_count = Column(Integer)  # token数，可为空
    create_time = Column(DateTime, default=func.now())  # Task任务创建时间，自动设置为当前时间
    context_content = Column(Text().with_variant(mysql.LONGTEXT(), "mysql"), nullable=False)  # Context内容
    update_time = Column(DateTime, default=func.now(), onupdate=func.now())  # 更新时间，自动设置为当前时间

    # 定义索引
    __table_args__ = (
        Index('task_agent_id', agent_id),
        Index('task_session_id', session_id),
        Index('task_create_time_desc', create_time.desc()),
    )

class SessionDBModel(Base):
    __tablename__ = 't_agent_session'
    
    # 定义表字段
    session_id = Column(String(255), primary_key=True)  # 会话ID，主键
    agent_ids = Column(Text)  # 会话相关的所有Agent ID
    user_ids = Column(Text)  # 会话相关的所有User ID
    task_ids = Column(Text)  # 会话相关的所有Task ID
    conversation_history = Column(Text().with_variant(mysql.LONGTEXT(), "mysql"))  # 历史对话信息
    update_time = Column(DateTime, default=func.now(), onupdate=func.now())  # 更新时间
    create_time = Column(DateTime, default=func.now())  # 创建时间
    session_ended = Column(Boolean, default=False)  # 会话是否结束
    
    # 定义索引
    __table_args__ = (
        Index('session_create_time_desc', create_time.desc()),
    )


class SkillExeInfoDBModel(Base):
    __tablename__ = 't_skill_exe_info'

    skill_name = Column(String(255), primary_key=True)
    executable = Column(Boolean, default=False, nullable=False)
    entry_module = Column(String(512))
    entry_function = Column(String(255))
    input_schema = Column(Text)

    trace_id = Column(String(255))
    arguments_preview = Column(Text)
    executed = Column(Boolean)
    duration_ms = Column(Float)
    result_size = Column(Integer)
    error_message = Column(Text)
    executed_at = Column(DateTime)

    create_time = Column(DateTime, default=func.now())
    update_time = Column(DateTime, default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index('skill_exe_update_time_desc', update_time.desc()),
    )
    
async def init_db_table(engine: AsyncEngine):
    """
    数据库表初始化

    1.如果表不存在：它会根据模型定义创建表。

    2.如果表已经存在：它不会做任何更新。也就是说，如果表已经存在，即使模型定义有更改（例如添加了新的列），create_all也不会更新表结构。
    """
    async with engine.begin() as conn:
        # run_sync 接收一个同步函数，并将 conn 转换为同步兼容模式传入
        await conn.run_sync(Base.metadata.create_all)
