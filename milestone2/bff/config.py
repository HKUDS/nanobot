# 配置管理

class Config:
    # Skill存储配置
    SKILL_STORAGE_TYPE = "database"  # database, filesystem, git
    SKILL_STORAGE_PATH = "/app/skills"  # 外部存储路径
    SKILL_EXPORT_ENABLED = True  # 是否启用外部导出
    
    # 其他配置
    DATABASE_PATH = "bff/bff.db"
    TZ_UTC8 = "Asia/Shanghai"