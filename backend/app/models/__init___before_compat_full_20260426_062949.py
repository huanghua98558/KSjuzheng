"""ORM 模型层 — 按 14 层架构组织.

L0  platform.py      平台超管 / 全局配置 / 服务状态
L1  organization.py  租户机构 (★ 数据隔离边界)
L2  user.py          用户
    role.py          角色
L3  account.py       软件账号 / KS 账号
L4  plan.py          计划业务
L5  task.py          任务执行
L6  income.py        收益结算
L7  content.py       内容资产
L8  audit.py         运维审计
L9-L11               AI 决策 / Agent / 记忆
L12 healing.py       风控自愈
L13 license.py       SaaS 卡密
"""

# Phase 1: L0 / L1 / L2 / L13
from app.models.platform import GlobalConfig, ServiceStatus  # noqa: F401
from app.models.organization import Organization  # noqa: F401
from app.models.user import User, UserSession  # noqa: F401
from app.models.role import Role, Permission, RolePermission, UserRole  # noqa: F401
from app.models.license import License  # noqa: F401

# Sprint 2A: L3 + 审计 + 用户级权限
from app.models.account import (  # noqa: F401
    Account,
    AccountGroup,
    KsAccount,
    CloudCookieAccount,
    McnAuthorization,
    InvitationRecord,
    AccountTaskRecord,
)
from app.models.audit import (  # noqa: F401
    OperationLog,
    UserPagePermission,
    UserButtonPermission,
    DefaultRolePermission,
)

# Sprint 2B: L7 内容资产
from app.models.content import (  # noqa: F401
    CollectPool,
    HighIncomeDrama,
    DramaLinkStatistic,
    DramaCollectionRecord,
    ExternalUrlStat,
)

# Sprint 2C: L4 计划成员 + L6 收益结算
from app.models.member import (  # noqa: F401
    OrgMember,
    SparkMember,
    FireflyMember,
    FluorescentMember,
    ViolationPhoto,
)
from app.models.income import (  # noqa: F401
    IncomeRecord,
    FireflyIncome,
    SparkIncome,
    FluorescentIncome,
    IncomeArchive,
    SettlementRecord,
    WalletProfile,
)

# Sprint 2D
from app.models.announcement import Announcement  # noqa: F401
from app.models.cxt import CxtUser, CxtVideo  # noqa: F401

# Phase 3: AI 自动化 L9-L12
from app.models.decision import (  # noqa: F401
    DailyCandidatePool,
    MatchScoreHistory,
    BurstDetection,
    AccountTierTransition,
    DailyPlan,
    DailyPlanItem,
)
from app.models.agent import (  # noqa: F401
    AgentRun,
    AutopilotCycle,
    AutopilotDiagnosis,
    AutopilotAction,
    AutopilotReport,
)
from app.models.memory import (  # noqa: F401
    AccountDecisionHistory,
    AccountStrategyMemory,
    AccountDiaryEntry,
    StrategyReward,
    ResearchNote,
)
from app.models.healing import (  # noqa: F401
    HealingPlaybook,
    HealingDiagnosis,
    RuleProposal,
    UpgradeProposal,
)
