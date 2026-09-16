"""Wire schemas for the five endpoints.

Request models are deliberately permissive: the judge is the source of truth and
a push we cannot parse is still a push we must accept gracefully.  Rejecting a
slightly-unexpected payload with a 422 costs us the context *and* the points.

Response models are strict, because a malformed response is scored -2 and an
empty `body` on an `action: send` is treated as malformed.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


# --------------------------------------------------------------------------
# POST /v1/context
# --------------------------------------------------------------------------


class ContextPush(BaseModel):
    model_config = ConfigDict(extra="allow")

    scope: str
    context_id: str
    version: int = 1
    payload: dict[str, Any] = Field(default_factory=dict)
    delivered_at: str | None = None


class ContextAccepted(BaseModel):
    accepted: Literal[True] = True
    ack_id: str
    stored_at: str


class ContextRejected(BaseModel):
    accepted: Literal[False] = False
    reason: str
    current_version: int | None = None
    details: str | None = None


# --------------------------------------------------------------------------
# POST /v1/tick
# --------------------------------------------------------------------------


class TickRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    now: str | None = None
    available_triggers: list[str] = Field(default_factory=list)


class Action(BaseModel):
    """One proactive send.

    `rationale` is not a comment: the judge is shown it and scores whether it
    matches the body it accompanies.  A stub string here is forfeited points.
    """

    conversation_id: str
    merchant_id: str
    customer_id: str | None = None
    send_as: Literal["vera", "merchant_on_behalf"] = "vera"
    trigger_id: str
    template_name: str | None = None
    template_params: list[str] = Field(default_factory=list)
    body: str = Field(min_length=1)
    cta: str = "open_ended"
    suppression_key: str = ""
    rationale: str = ""


class TickResponse(BaseModel):
    actions: list[Action] = Field(default_factory=list)


# --------------------------------------------------------------------------
# POST /v1/reply
# --------------------------------------------------------------------------


class ReplyRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    conversation_id: str
    merchant_id: str | None = None
    customer_id: str | None = None
    from_role: str = "merchant"
    message: str = ""
    received_at: str | None = None
    turn_number: int = 1


class ReplySend(BaseModel):
    action: Literal["send"] = "send"
    body: str = Field(min_length=1)
    cta: str = "open_ended"
    rationale: str = ""


class ReplyWait(BaseModel):
    action: Literal["wait"] = "wait"
    wait_seconds: int = 1800
    rationale: str = ""


class ReplyEnd(BaseModel):
    action: Literal["end"] = "end"
    rationale: str = ""


# --------------------------------------------------------------------------
# GET /v1/healthz, GET /v1/metadata
# --------------------------------------------------------------------------


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    uptime_seconds: int
    contexts_loaded: dict[str, int]


class MetadataResponse(BaseModel):
    team_name: str
    team_members: list[str]
    model: str
    approach: str
    contact_email: str
    version: str
    submitted_at: str
