"""
モデル定義モジュール
APIで使用するPydanticモデルを定義します
"""
from typing import Dict, List, Optional, Any, Union
from datetime import datetime
from pydantic import BaseModel, HttpUrl, EmailStr

# ユーザー認証関連モデル
class UserLogin(BaseModel):
    email: str
    password: str

class UserRegister(BaseModel):
    email: str
    password: str
    name: str

class UserResponse(BaseModel):
    id: str
    email: str
    name: str
    role: str
    created_at: datetime

class UsageLimit(BaseModel):
    document_uploads_used: int
    document_uploads_limit: int
    questions_used: int
    questions_limit: int
    is_unlimited: bool

class UserWithLimits(UserResponse):
    usage_limits: UsageLimit

# チャット関連モデル
class ChatMessage(BaseModel):
    text: str
    employee_id: Optional[str] = None
    employee_name: Optional[str] = None
    user_id: Optional[str] = None

class ChatResponse(BaseModel):
    response: str
    source: Optional[str] = None
    remaining_questions: Optional[int] = None
    limit_reached: Optional[bool] = None

class ChatHistoryItem(BaseModel):
    id: str
    user_message: str
    bot_response: str
    timestamp: datetime
    category: Optional[str] = None
    sentiment: Optional[str] = None
    employee_id: Optional[str] = None
    employee_name: Optional[str] = None
    source_document: Optional[str] = None
    source_page: Optional[str] = None

# 分析関連モデル
class AnalysisResult(BaseModel):
    category_distribution: Dict[str, int]
    sentiment_distribution: Dict[str, int]
    common_questions: List[Dict[str, Any]]
    insights: str

# 社員利用状況関連モデル
class EmployeeUsageItem(BaseModel):
    employee_id: str
    employee_name: str
    message_count: int
    last_activity: datetime
    top_categories: List[Dict[str, Any]]
    recent_questions: List[str]

class EmployeeUsageResult(BaseModel):
    employee_usage: List[EmployeeUsageItem]

# URL送信関連モデル
class UrlSubmission(BaseModel):
    url: str
    user_id: Optional[str] = None

# 会社名関連モデル
class CompanyNameResponse(BaseModel):
    company_name: str

class CompanyNameRequest(BaseModel):
    company_name: str

# アップロードリソース関連モデル
class ResourceItem(BaseModel):
    name: str
    type: str
    timestamp: datetime
    active: bool = True
    uploaded_by: Optional[str] = None

class ResourcesResult(BaseModel):
    resources: List[ResourceItem]
    message: str

class ResourceToggleResponse(BaseModel):
    name: str
    active: bool
    message: str

# デモ利用状況関連モデル
class DemoUsageStats(BaseModel):
    total_users: int
    active_users: int
    total_documents: int
    total_questions: int
    limit_reached_users: int

# 管理者関連モデル
class AdminUserCreate(BaseModel):
    email: str
    password: str
    name: str
    role: Optional[str] = "employee"  # "user" または "employee"