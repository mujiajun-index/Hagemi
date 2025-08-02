from typing import List, Dict, Optional, Union, Literal
from pydantic import BaseModel, Field

class Message(BaseModel):
    role: str
    content: Union[str, List[Dict]]

class ChatCompletionRequest(BaseModel):
    model: str
    messages: List[Message]
    temperature: float = 0.7
    top_p: Optional[float] = 1.0
    n: int = 1
    stream: bool = False
    stop: Optional[Union[str, List[str]]] = None
    max_tokens: Optional[int] = None
    presence_penalty: Optional[float] = 0.0
    frequency_penalty: Optional[float] = 0.0

class Choice(BaseModel):
    index: int
    message: Message
    finish_reason: Optional[str] = None

class Usage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

class ChatCompletionResponse(BaseModel):
    id: str
    object: Literal["chat.completion"]
    created: int
    model: str
    choices: List[Choice]
    usage: Usage = Field(default_factory=Usage)

class ErrorResponse(BaseModel):
    message: str
    type: str
    param: Optional[str] = None
    code: Optional[str] = None

class ModelList(BaseModel):
    object: str = "list"
    data: List[Dict]

class AccessKey(BaseModel):
    key: str
    name: Optional[str] = None
    usage_limit: Optional[int] = None
    usage_count: int = 0
    expires_at: Optional[int] = None
    is_active: bool = True

class AccessKeyCreate(BaseModel):
    name: Optional[str] = None
    usage_limit: Optional[int] = None
    expires_at: Optional[int] = None
    is_active: bool = True