from __future__ import annotations
import json
import logging
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from app.models.schemas import (
    InputBundle,
    OptimizationProposal,
    WorkloadResult,
    AgentAuditLog,
    ToolCall,
    DecisionStatus,
    ProposalStatus,
    ReviewCycle,
    CriticObjection,
    VerificationResult,
    VerificationStep,
    CriticCheck,
    CheckStatus,
    RiskLevel,
    ResourceSettings,
    UsageMetrics
)
from app.services.agent_tools import AgentToolbox
from app.services.verification_service import VerificationService
from app.services.redaction import scrub
from app.services import adversarial_service, critic_service, optimizer_service
from app.services.confidence_service import score_priority
from app.integrations.llm_client import LLMUnavailable

logger = logging.getLogger(__name__)


def _jsonable(value: Any) -> Any:
    """Convert a tool result into something `json.dumps` can handle.

    Tool results are pydantic models, lists of pydantic models and datetimes. Dumping them
    structurally keeps the model able to read the evidence; `default=str` on the final
    `json.dumps` is the last-resort net so a serialisation bug can never abort a cycle.
    """
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    return value


# How much of a tool result reaches the model. `get_workload_metrics` returns 720 usage rows;
# sending all of it on every turn, for every workload, is slow and mostly noise. The audit log
# keeps the complete result either way - this bounds only what the model reads.
MAX_TOOL_RESULT_CHARS = 20_000


def _truncate(text: str) -> str:
    """Bound a tool result, and say so rather than silently cutting it."""
    if len(text) <= MAX_TOOL_RESULT_CHARS:
        return text
    kept = text[:MAX_TOOL_RESULT_CHARS]
    return f"{kept}\n... [truncated: the full result is {len(text)} characters and is kept in the audit log]"


# A turn that calls a tool is never a conclusion, so the model has to end a phase in words.
# But a turn in words is not always a conclusion: a real model often opens with a PLAN
# ("first I will retrieve the metrics, then analyse the right-sizing") and expects the next
# turn to execute it. Treating that plan as the end of the phase leaves the workload with no
# evidence and no policy check - the cycle "succeeds" and decides nothing.
#
# The distinguishing signal is evidence: a text-only turn after the phase has used tools is a
# conclusion; a text-only turn before any tool has run is a plan.
PLAN_NUDGE = (
    "Your plan was stated but no tool was called. Call the first tool now and gather the "
    "evidence the plan depends on."
)

# The revision turn: the proposer answers the objections it never saw. The three answers are the
# only ones that exist, because anything else would be the model editing a number - which it may
# never do. "narrow" keeps one resource's reduction and gives the other back to its current
# value, so the numbers still come from the optimizer; the deterministic critic then decides the
# narrowed change on its own terms.
REVISION_SYSTEM = (
    "You are the FinOps analyst who proposed this change. The adversarial reviewer raised blocking "
    "objections that you have not answered. Answer them in one of three ways:\n"
    "  \"concede\" - withdraw the change; the objection is right and there is nothing safe to do.\n"
    "  \"narrow\"  - keep the reduction on ONE resource and leave the other at its current request.\n"
    "  \"keep\"    - stand by the change and name the evidence that answers the objection.\n"
    "You may not invent a number, a resource value or an incident. The deterministic critic "
    "re-decides whatever you choose.\n"
    "Reply with JSON only: {\"action\": \"concede\"|\"narrow\"|\"keep\", "
    "\"resource\": \"cpu\"|\"memory\"|null, \"reason\": \"<one sentence>\"}. "
    "\"resource\" is the one to KEEP when the action is \"narrow\"."
)


def _parse_revision(content: str | None) -> tuple[str, str | None, str]:
    """Read the revision turn's answer, and never let a broken one change the outcome.

    Anything unparseable means "keep": a garbled reply must not silently withdraw a real
    recommendation, and it must not be read as permission to drop half of it either.
    """
    text = (content or "").strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return "keep", None, "The revision answer was not usable, so the proposal stands."
    try:
        payload = json.loads(text[start:end + 1])
    except (TypeError, ValueError):
        return "keep", None, "The revision answer was not valid JSON, so the proposal stands."
    if not isinstance(payload, dict):
        return "keep", None, "The revision answer was not an object, so the proposal stands."

    action = str(payload.get("action") or "").strip().lower()
    resource = str(payload.get("resource") or "").strip().lower() or None
    reason = str(payload.get("reason") or "").strip()
    if action not in ("concede", "narrow", "keep"):
        return "keep", None, reason or "The revision answer named no action, so the proposal stands."
    if action == "narrow" and resource not in ("cpu", "memory"):
        return "keep", None, reason or "The revision named no resource to keep, so the proposal stands."
    return action, (resource if action == "narrow" else None), reason


REVIEW_ENGINES = ("native", "langgraph")


def review_engine() -> str:
    """Which engine runs the phases.

    `native` is the default: the phases are a sequence of calls. `langgraph` runs the same
    functions as a state machine whose conditional edge is the revision decision. Anything else -
    including a typo - falls back to native rather than failing a run over a setting.
    """
    engine = os.getenv("REVIEW_ENGINE", "native").strip().lower()
    return engine if engine in REVIEW_ENGINES else "native"


@dataclass
class ReviewRun:
    """What the phases produced, for the assembly step that turns it into a verdict."""
    proposer: ReviewCycle
    critic: ReviewCycle
    formal: WorkloadResult
    revision: ReviewCycle | None
    revised: bool
    judge: ReviewCycle


def deterministic_result(bundle: InputBundle, workload_id: str,
                          now: datetime | None = None) -> WorkloadResult:
    """The verdict for a workload with no agent involved at all.

    This is the same computation the non-agent pipeline runs: the optimizer produces the proposal
    and the deterministic Context Critic decides it. It exists so that a model outage costs a
    workload its *review*, not its *verdict* - and so that the agent path and the pipeline path
    cannot drift into computing different answers for the same workload.
    """
    from app.services.critic_service import evaluate
    from app.services.optimizer_service import analyze_workload

    spec = next((s for s in bundle.services if s.name == workload_id), None)
    if spec is None:
        raise KeyError(f"Unknown workload {workload_id}.")
    moment = now or bundle.policy.simulation_now or datetime.now(timezone.utc)
    proposal = analyze_workload(
        workload=spec,
        rows=[row for row in bundle.usage_rows if row.service == workload_id],
        policy=bundle.policy.optimizer,
        now=moment,
        cost_model=bundle.cost_model,
        incidents=bundle.incidents,
        events=bundle.events,
    )
    return evaluate(proposal, bundle, moment)


class AgentOrchestrator:
    """
    The 'Brain' of the FinOps Agent.

    Runs a three-phase review cycle per workload:
        Proposer -> gathers evidence with tools and states a case for (or against) a reduction.
        Critic   -> red-teams that case and raises typed, evidence-grounded objections.
        Judge    -> weighs the objections against the deterministic critic's result and rules.

    The deterministic Context Critic always owns the final status. The adversarial phase can only
    downgrade a recommendation or raise it for human review; it can never approve anything on its own.

    The cycle is bounded: each phase has a hard iteration cap, so a confused agent raises an error
    instead of looping forever.
    """
    MAX_PROPOSER_ITERATIONS = 10
    # The critic's objections are raised by the deterministic pass below, never by the model, so
    # its turns buy prose and nothing else. It used to spend four of them - half of a workload's
    # round-trips - narrating a verdict it does not decide. One turn is enough to state the
    # objections now that the evidence it would have fetched is already in the prompt.
    MAX_CRITIC_ITERATIONS = 1
    MAX_JUDGE_ITERATIONS = 3

    def __init__(self, bundle: InputBundle, llm_client: Any, store: Any = None):
        self.bundle = bundle
        self.llm = llm_client  # Assume an LLM client that supports tool use
        # The toolbox is replaced for every workload, in `analyze_workload_agentic`. It is
        # created here unbound only so the attribute always exists; nothing reads it before
        # the first workload's review starts.
        self.toolbox = AgentToolbox(bundle)
        self.verifier = VerificationService()
        self.store = store
        # Set when the model server goes away during a phase. It is reset per workload, because
        # one workload's outage says nothing about the next one's.
        self.model_outage: Optional[str] = None

    # ------------------------------------------------------------------ prompt construction
    def _historical_lessons(self, workload_id: str) -> List[str]:
        """Human rejections for this workload, turned into prompt-ready lessons."""
        if self.store is None:
            return []
        try:
            records = self.store.get_feedback_for_workload(workload_id)
        except Exception:  # noqa: BLE001 - a missing history must never abort an analysis
            return []
        lessons: List[str] = []
        for record in records:
            if record.action.value != "REJECTED":
                continue
            parts = []
            if record.rejection_reasons:
                parts.append("; ".join(record.rejection_reasons))
            elif record.comment:
                parts.append(record.comment)
            if record.resource:
                parts.append(f"(resource: {record.resource})")
            if record.reviewer_guidance:
                parts.append(f"guidance: {record.reviewer_guidance}")
            if parts:
                lessons.append(f"A human previously rejected a change to {workload_id}: " + " ".join(parts))
        return lessons

    def _proposer_prompt(self, workload_id: str, lessons: List[str]) -> str:
        prompt = (
            "You are a FinOps Expert Agent. Your goal is to recommend safe resource optimizations. "
            "You have access to tools to get metrics, analyze right-sizing, check policies, search logs, "
            "and map dependencies.\n"
            "CRITICAL RULES:\n"
            "1. Use tools to gather evidence. Do not guess numbers.\n"
            "2. Check for recurring business events and prior incidents before proposing a reduction.\n"
            "3. You MUST call 'validate_policy' as the final step before concluding.\n"
            "4. If 'validate_policy' rejects a proposal, you must report the rejection.\n"
            "5. Every number in your final summary must come from a tool result."
        )
        if lessons:
            prompt += ("\n\nHISTORICAL LESSONS (a human rejected these before; address them or do not repeat them):\n"
                       + "\n".join(f"- {lesson}" for lesson in lessons))
        return prompt

    # ------------------------------------------------------------------ LLM plumbing
    async def _chat(self, system: str, user: str, messages: List[Dict[str, Any]],
                    tools: List[Dict[str, Any]] | None = None) -> Dict[str, Any]:
        """Call the LLM and normalise the response.

        `messages` is the phase's own OpenAI-format message list (see `_record_turn`); it does NOT
        include the current user turn, which is passed separately as `user`.

        `tools` defaults to the whole toolbox. Pass an empty list for a phase that must not use
        tools - the Judge narrates a ruling it did not make, and offering it tools it will never
        run only invites a tool call whose result is discarded.

        The call is positional on purpose: the client owns the wire format, and the message list
        is the conversation so far.

        The LLM client may return a dict or an object; both are supported so a real client and the
        simulated one can be dropped in interchangeably.
        """
        response = await self.llm.chat(
            system,
            user,
            self.toolbox.get_tool_definitions() if tools is None else tools,
            messages,
        )
        if isinstance(response, dict):
            return {
                "content": response.get("content"),
                "tool_call": response.get("tool_call"),
                "thought": response.get("thought"),
                "conclusion": bool(response.get("conclusion")),
                "tool_call_id": response.get("tool_call_id"),
            }
        return {
            "content": getattr(response, "content", None),
            "tool_call": getattr(response, "tool_call", None),
            "thought": getattr(response, "thought", None),
            "conclusion": bool(getattr(response, "conclusion", False)),
            "tool_call_id": getattr(response, "tool_call_id", None),
        }

    def _record_turn(self, messages: List[Dict[str, Any]], response: Dict[str, Any],
                     step: ToolCall | None) -> None:
        """Append one model turn to the phase's OpenAI-format message list.

        The order matters and is fixed by the OpenAI chat-completions protocol:
          * a turn that called a tool becomes an `assistant` message carrying `tool_calls`, followed
            by the matching `role:"tool"` message that holds the result;
          * a turn that called no tool becomes a plain `assistant` message.

        The tool result is serialised with `json.dumps(..., default=str)` because tool results are
        pydantic models and datetimes, and a serialisation bug must never abort a review cycle.

        `step` is None when no tool ran. That happens in the Judge phase, which narrates and does
        not reason with tools: a tool call it asks for is not executed, so no `tool_calls` entry is
        recorded either - an assistant message announcing a call that never got an answer would be
        a lie the next turn of the conversation could read as evidence.
        """
        tool_call = response.get("tool_call")
        if tool_call and step is not None:
            arguments = tool_call.get("arguments") or {}
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except (TypeError, ValueError):
                    arguments = {"raw": arguments}
            call_id = response.get("tool_call_id") or f"call_{len(messages)}"
            messages.append({
                "role": "assistant",
                "content": response.get("content") or None,
                "tool_calls": [{
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": tool_call.get("name"),
                        "arguments": json.dumps(arguments, default=str),
                    },
                }],
            })
            messages.append({
                "role": "tool",
                "tool_call_id": call_id,
                "content": _truncate(json.dumps(_jsonable(step.result), default=str)),
            })
        else:
            messages.append({"role": "assistant", "content": response.get("content") or ""})

    def _execute_tool(self, tool_name: str, params: Dict[str, Any]) -> ToolCall:
        """Run one tool and record the call, whatever the outcome."""
        result = self.toolbox.call(tool_name, **params)
        if result.status == "error":
            return ToolCall(tool=tool_name, params=params, result={"error": result.error}, thought=None)
        return ToolCall(tool=tool_name, params=params, result=result.data, thought=None)

    def _run_tool(self, tool_name: str, params: Dict[str, Any], thought: str | None) -> ToolCall:
        """Execute a tool and append it to both the phase cycle and the audit log."""
        step = self._execute_tool(tool_name, params)
        step.thought = thought
        return step

    def _handle_response(self, response: Dict[str, Any], cycle: ReviewCycle, audit_log: AgentAuditLog,
                         current_context: str) -> tuple[str, ToolCall | None]:
        """Apply one LLM turn to a phase.

        Returns the updated context and the tool step that ran (None when the turn called no tool).
        The subtle case is a response that carries BOTH a tool call and a conclusion: the model is
        saying "run this tool, and here is my answer". The tool must still run - the conclusion is
        often premised on its result - but the phase is finished afterwards. Treating the conclusion
        as an immediate stop would silently skip the mandatory validate_policy call.
        """
        if response["thought"]:
            current_context = f"{current_context}\nThought: {response['thought']}"

        tool_call = response["tool_call"]
        if tool_call:
            tool_name = tool_call.get("name")
            params = tool_call.get("arguments") or {}
            step = self._run_tool(tool_name, params, response["thought"])
            cycle.steps.append(step)
            audit_log.steps.append(step)
            current_context = f"{current_context}\nTool {tool_name} returned: {step.result}"
            if response["conclusion"]:
                # The tool ran; the phase is done.
                cycle.summary = response["content"] or cycle.summary
            return current_context, step

        # No tool call: the model has finished (or given up).
        cycle.summary = response["content"] or cycle.summary
        return current_context, None

    # ------------------------------------------------------------------ phase 1: proposer
    async def _run_proposer(self, audit_log: AgentAuditLog, workload_id: str, lessons: List[str]) -> ReviewCycle:
        """Gather evidence with tools and state a case. The cycle ends when the agent concludes."""
        cycle = ReviewCycle(role="proposer")
        system_prompt = self._proposer_prompt(workload_id, lessons)
        current_context = f"Analyze workload: {workload_id}. Find safe savings."
        messages: List[Dict[str, Any]] = []
        validated = False
        case = ""  # the model's own words alongside the deterministic verdict

        for _ in range(self.MAX_PROPOSER_ITERATIONS):
            was_validated = validated
            try:
                response = await self._chat(system_prompt, current_context, messages)
            except LLMUnavailable as exc:
                # The model server went away mid-phase. End the phase here rather than let the
                # outage unwind the whole workload: the evidence gathered so far is still good
                # evidence, and the deterministic critic still owns the decision.
                #
                # The cause is scrubbed. This summary is published in the API response, and a
                # transport error can carry a header the server echoed back - a token in the
                # response is a token in the log of whoever reads it.
                cause = scrub(f"{type(exc).__name__}: {exc}")
                self.model_outage = self.model_outage or cause
                cycle.summary = (f"The proposer stopped after {len(cycle.steps)} tool call(s) because the "
                                 f"model server became unavailable ({cause}).")
                break
            before = len(cycle.steps)

            if was_validated and response["tool_call"]:
                # The deterministic verdict is in hand and the model wants to call another tool.
                # The proposal cannot change from here, so the tool is not run and the phase ends.
                break

            current_context, step = self._handle_response(response, cycle, audit_log, current_context)
            self._record_turn(messages, response, step)

            if (step is not None and step.tool == "validate_policy"
                    and isinstance(step.result, WorkloadResult) and len(cycle.steps) > before):
                # Only a policy check that actually produced a verdict counts. A failed one -
                # the tool was called with a proposal that could not be validated, or with the
                # wrong workload - holds no verdict, and treating it as one ended the phase
                # before the model could act on the error and try again.
                validated = True
                # The content that came with the verdict is the model's case for the change.
                case = response["content"] or case

            if len(cycle.steps) > before and response["conclusion"]:
                # The final tool ran; the proposal is complete.
                break

            if not response["tool_call"]:
                if validated or cycle.steps:
                    # The model has evidence to conclude from, and it has just concluded.
                    break
                # A plan, not a conclusion: nothing has been called yet. Keep the phase alive
                # and let the model execute the plan it just described.
                cycle.summary = ""
                current_context = f"{current_context}\n{PLAN_NUDGE}"
                continue

        if not cycle.summary:
            cycle.summary = case or (
                "The proposer gathered evidence but never stated a conclusion."
                if cycle.steps else
                "The proposer never called a tool, so there was no evidence to reason from."
            )
        cycle.completed_at = datetime.now(timezone.utc)
        return cycle

    # ------------------------------------------------------------------ phase 2: critic
    async def _run_critic(self, audit_log: AgentAuditLog, workload_id: str,
                          proposer: ReviewCycle, formal: WorkloadResult | None) -> ReviewCycle:
        """Red-team the proposer's case. May call read-only tools to ground its objections."""
        cycle = ReviewCycle(role="critic")
        system_prompt = (
            "You are an adversarial reviewer for a FinOps Agent. Your job is to find the flaw in a "
            "proposed resource reduction. Challenge it with: Is a spike actually recurring? Is the "
            "container already being OOMKilled or throttled? Is there a prior incident on this exact "
            "reduction? Is an upstream dependency under pressure? Is the evidence sample too thin?\n"
            "Rules: use tools to check before objecting. Never invent an incident or a log line. "
            "Call 'validate_policy' to obtain the deterministic critic's verdict, then state your "
            "objections."
        )
        current_context = (
            f"Adversarially review the proposed change for workload: {workload_id}.\n"
            f"Proposer summary: {proposer.summary or '(none)'}\n"
            f"Tools already called: {', '.join(step.tool for step in proposer.steps) or '(none)'}."
        )
        # The evidence the objections are grounded in is gathered here, not left to the model.
        #
        # The log-pressure objection is a blocking one: reducing a container that is already
        # being OOMKilled is a reliability regression, not a saving. If it depended on the
        # model choosing to call `search_logs`, the model could suppress it by not calling -
        # and the deterministic critic has no log rule of its own to fall back on, so the
        # workload would be approved on the strength of an omission. The evidence is the same
        # either way, so it is retrieved every time and the model's objections are built on
        # top of it.
        for tool_name in ("search_logs", "get_dependencies"):
            step = self._run_tool(tool_name, {"workload_id": workload_id}, None)
            cycle.steps.append(step)
            audit_log.steps.append(step)
        current_context += (
            "\nThe container logs and the dependency map for this workload have already been "
            "retrieved and are in the evidence trail. Use them; do not fetch them again."
        )
        # Inline the evidence the prefetch just pulled. Without it the model could only see that
        # those tools ran, so it re-called them - which is why the critic needed four turns.
        for step in cycle.steps:
            digest = json.dumps(_jsonable(step.result), default=str)[:1200]
            current_context += f"\n{step.tool}({workload_id}) -> {digest}"
        messages: List[Dict[str, Any]] = []

        for _ in range(self.MAX_CRITIC_ITERATIONS):
            try:
                response = await self._chat(system_prompt, current_context, messages)
            except LLMUnavailable as exc:
                # Same as the proposer: the critic's objections are derived from the tool
                # evidence, not from the model's prose, so the review still has teeth without it.
                cause = scrub(f"{type(exc).__name__}: {exc}")
                self.model_outage = self.model_outage or cause
                cycle.summary = (f"The critic stopped after {len(cycle.steps)} tool call(s) because the "
                                 f"model server became unavailable ({cause}).")
                break
            before = len(cycle.steps)
            current_context, step = self._handle_response(response, cycle, audit_log, current_context)
            self._record_turn(messages, response, step)
            if len(cycle.steps) > before and response["conclusion"]:
                break
            if not response["tool_call"]:
                if cycle.steps:
                    # The critic has checked something and is now stating its objections.
                    break
                # A plan, not objections. Keep the phase alive so the critic can check.
                cycle.summary = ""
                current_context = f"{current_context}\n{PLAN_NUDGE}"
                continue

        # The deterministic objection pass runs on every cycle, whatever the LLM did. The LLM's
        # narrative can add colour; it can never remove a grounded objection.
        all_steps = proposer.steps + cycle.steps
        objections = adversarial_service.raise_objections(
            proposal=formal.proposal if formal else None,
            result=formal,
            steps=all_steps,
            bundle=self.bundle,
            workload_id=workload_id,
        )
        cycle.objections = objections
        if not cycle.summary:
            cycle.summary = (f"{len([o for o in objections if o.severity == 'blocking'])} blocking and "
                              f"{len([o for o in objections if o.severity != 'blocking'])} advisory "
                              f"objection(s) raised from the tool evidence.")
        cycle.completed_at = datetime.now(timezone.utc)
        return cycle

    # ------------------------------------------------------------------ phase 3: judge
    async def _run_judge(self, workload_id: str, proposer: ReviewCycle, critic: ReviewCycle,
                         formal: WorkloadResult | None, revision: ReviewCycle | None = None) -> ReviewCycle:
        """Weigh the objections and rule. The Judge can only downgrade; it cannot approve."""
        cycle = ReviewCycle(role="judge")
        verdict, rationale = adversarial_service.judge_verdict(critic.objections, formal)
        cycle.verdict = verdict
        cycle.objections = critic.objections
        cycle.summary = rationale

        # The Judge's own LLM pass is advisory narration over the deterministic verdict.
        try:
            system_prompt = (
                "You are the final judge of a FinOps review cycle. You have the proposer's case, the "
                "critic's objections, and the deterministic policy verdict. State in two sentences why "
                "the verdict is what it is. Do not introduce new facts and do not change the verdict."
            )
            user = (f"Workload: {workload_id}\n"
                    f"Deterministic verdict: {formal.decision.value if formal else 'unknown'}\n"
                    f"Proposer: {proposer.summary or '(none)'}\n"
                    f"Critic objections: " + ("; ".join(o.message for o in critic.objections) or "(none)") + "\n"
                    f"Ruling: {verdict} - {rationale}")
            if revision is not None:
                user = (f"{user}\nAfter the review the proposer was given one turn to answer those "
                        f"objections and chose '{revision.verdict}': {revision.summary}")
            # The Judge narrates; it does not reason with tools. Its message list is its own, and
            # the deterministic ruling above stands whatever the model says.
            messages: List[Dict[str, Any]] = []
            response = await self._chat(system_prompt, user, messages, tools=[])
            self._record_turn(messages, response, None)
            if response.get("content"):
                cycle.summary = f"{cycle.summary} {response['content']}"
        except Exception as exc:  # noqa: BLE001 - narration is optional; the deterministic ruling stands
            # The ruling stands either way, but a review that lost its narration is a shorter
            # review, and the report has to say so rather than let it pass unnoticed.
            if isinstance(exc, LLMUnavailable):
                cause = scrub(f"{type(exc).__name__}: {exc}")
                self.model_outage = self.model_outage or cause
                cycle.summary = (f"{cycle.summary} The judge could not narrate the ruling because the "
                                 f"model server became unavailable ({cause}).")
            else:
                logger.warning("The judge's narration failed for %s: %s", workload_id, scrub(str(exc)))

        cycle.completed_at = datetime.now(timezone.utc)
        return cycle

    # ------------------------------------------------------------------ phase 2b: revision
    def _needs_revision(self, critic: ReviewCycle, formal: WorkloadResult | None) -> bool:
        """Whether the review has something the proposer must answer.

        Referenced by both the native sequence and the graph's conditional edge, so the two
        engines cannot disagree about when the loop runs.
        """
        if formal is None or formal.proposal.proposed is None:
            return False
        return any(objection.severity == "blocking" for objection in critic.objections)

    async def _run_revision(self, workload_id: str, critic: ReviewCycle,
                            formal: WorkloadResult | None,
                            steps: List[ToolCall]) -> tuple[ReviewCycle | None, WorkloadResult | None]:
        """One turn for the proposer to answer the objections the critic raised.

        Without this the cycle is a one-way pipeline: the critic objects, the judge escalates, and
        the proposal that was never given a chance to answer is the one on screen. The proposer may
        concede, narrow the change to one resource, or stand by it - and the deterministic critic
        decides the result, so the model still never sets a number.

        Returns (cycle, revised result) where the result is None when nothing changed.
        """
        blocking = [objection for objection in critic.objections if objection.severity == "blocking"]
        # There has to be a change on the table to answer for. A workload the optimizer already
        # left alone has nothing to narrow, and an objection to it is not the proposer's to
        # resolve. Everything else - approved, deferred, held for review - gets its turn.
        if formal is None or not self._needs_revision(critic, formal):
            return None, None

        proposal = formal.proposal
        current, proposed = proposal.current, proposal.proposed
        if proposed is None:
            return None, None

        cycle = ReviewCycle(role="revision")
        user = (
            f"Workload: {workload_id}\n"
            f"Current requests: CPU {current.cpu_request_millicores} millicores, "
            f"memory {current.memory_request_mib} MiB.\n"
            f"Proposed requests: CPU {proposed.cpu_request_millicores} millicores, "
            f"memory {proposed.memory_request_mib} MiB.\n"
            f"Blocking objections:\n"
            + "\n".join(f"- [{o.code}] {o.message}" for o in blocking)
        )

        try:
            messages: List[Dict[str, Any]] = []
            response = await self._chat(REVISION_SYSTEM, user, messages, tools=[])
            action, resource, reason = _parse_revision(response.get("content"))
        except Exception as exc:  # noqa: BLE001 - a revision that cannot run leaves the review as it was
            if isinstance(exc, LLMUnavailable):
                cause = scrub(f"{type(exc).__name__}: {exc}")
                self.model_outage = self.model_outage or cause
                cycle.verdict = "unavailable"
                cycle.summary = (f"The proposer was not asked to answer the objections because the "
                                 f"model server became unavailable ({cause}).")
            else:
                logger.warning("The revision turn failed for %s: %s", workload_id, scrub(str(exc)))
                cycle.verdict = "unavailable"
                cycle.summary = "The proposer's revision turn failed, so the review stands as it was."
            cycle.completed_at = datetime.now(timezone.utc)
            return cycle, None

        revised: WorkloadResult | None = None
        if action == "narrow" and resource in ("cpu", "memory"):
            revised = self._narrowed(formal, keep=resource, reason=reason)
            cycle.verdict = "narrow"
            cycle.summary = (f"Kept the {resource} reduction and gave the other resource back to its "
                             f"current request: {reason}")
            if revised is not None and revised.decision is not DecisionStatus.APPROVED:
                cycle.summary = (f"{cycle.summary} The narrowed change did not pass the critic "
                                 f"({revised.decision.value}), so it is reported as such.")
        elif action == "concede":
            revised = self._withdrawn(formal, reason)
            cycle.verdict = "concede"
            cycle.summary = f"Withdrew the change after review: {reason}"
        else:
            cycle.verdict = "keep"
            cycle.summary = f"Stood by the change: {reason}"

        # The objections that survive are the ones that still apply to the proposal now on the
        # table. They are recomputed deterministically: dropping the memory change has to retire a
        # memory-pressure objection, or the judge would keep escalating a change nobody made.
        if revised is not None:
            cycle.objections = adversarial_service.raise_objections(
                proposal=revised.proposal,
                result=revised,
                steps=steps,
                bundle=self.bundle,
                workload_id=workload_id,
            )
        cycle.completed_at = datetime.now(timezone.utc)
        return cycle, revised

    def _narrowed(self, formal: WorkloadResult, *, keep: str, reason: str) -> WorkloadResult:
        """Keep one resource's reduction, give the other back, and re-price the result.

        The saving is recomputed rather than carried over: the critic reports whatever
        `estimated_monthly_saving_usd` says, and inheriting the two-resource figure for a
        one-resource change would overstate the money on the page.
        """
        proposal = formal.proposal
        current, proposed = proposal.current, proposal.proposed
        if proposed is None:
            return self._withdrawn(formal, reason)

        update = ({"memory_request_mib": current.memory_request_mib} if keep == "cpu"
                  else {"cpu_request_millicores": current.cpu_request_millicores})
        narrowed = proposed.model_copy(update=update)
        if (narrowed.cpu_request_millicores == current.cpu_request_millicores
                and narrowed.memory_request_mib == current.memory_request_mib):
            # Nothing left to change: the objection answered the whole proposal.
            return self._withdrawn(formal, reason)

        prior = proposal.savings_estimate
        estimate = optimizer_service.estimate_monthly_savings(
            current, narrowed, self.bundle.cost_model,
            replicas=prior.replicas if prior else 1,
            days=prior.days if prior else 30,
        )
        value_score = (estimate.monthly_savings_usd
                       if estimate.monthly_savings_usd is not None
                       else estimate.total_request_reduction_pct / 100.0)
        updated = proposal.model_copy(update={
            "proposed": narrowed,
            "estimated_monthly_saving_usd": estimate.monthly_savings_usd or 0.0,
            "savings_estimate": estimate,
            "reasons": [*proposal.reasons, f"Narrowed after review: {reason}"],
        })
        priority, breakdown = score_priority(
            updated, value_score, updated.confidence.score if updated.confidence else 0.0,
        )
        return critic_service.evaluate(
            updated.model_copy(update={"priority_score": priority, "priority_breakdown": breakdown}),
            self.bundle,
        )

    def _withdrawn(self, formal: WorkloadResult, reason: str) -> WorkloadResult:
        """The proposer conceded: no change, decided by the deterministic critic, not by prose."""
        withdrawn = formal.proposal.model_copy(update={
            "status": ProposalStatus.NO_CHANGE,
            "proposed": None,
            "estimated_monthly_saving_usd": 0.0,
            "priority_score": 0.0,
            "reasons": [*formal.proposal.reasons, f"Withdrawn after review: {reason}"],
        })
        return critic_service.evaluate(withdrawn, self.bundle)

    # ------------------------------------------------------------------ entry point
    async def analyze_workload_agentic(self, workload_id: str) -> tuple[WorkloadResult, AgentAuditLog]:
        """Review one workload: prepare, run the phases, assemble the verdict.

        The phases can run two ways. `REVIEW_ENGINE=native` (the default) runs them as a sequence
        of calls; `REVIEW_ENGINE=langgraph` runs the same functions as a LangGraph state machine
        whose conditional edge is the revision decision. The graph changes how the loop is
        expressed, not what decides anything: both paths call the same phase methods and the same
        deterministic critic, and the parity test keeps them producing the same verdicts.
        """
        audit_log, lessons = self._begin_review(workload_id)

        run: ReviewRun | None = None
        if review_engine() == "langgraph":
            try:
                from app.services.review_graph import run_review_graph

                run = await run_review_graph(self, workload_id, audit_log, lessons)
            except Exception as exc:  # noqa: BLE001 - a graph failure must not cost a workload its review
                logger.warning("The LangGraph engine failed for %s; using the native loop instead: %s",
                               workload_id, scrub(str(exc)))
                audit_log.cycles.clear()
        if run is None:
            run = await self._run_phases(workload_id, audit_log, lessons)

        return self._assemble(workload_id, audit_log, run)

    def _begin_review(self, workload_id: str) -> tuple[AgentAuditLog, List[str]]:
        """Fresh per-workload state: a new audit log, and a toolbox bound to this workload."""
        audit_log = AgentAuditLog(session_id=str(uuid.uuid4()), workload_id=workload_id)
        # One workload's outage says nothing about the next one's.
        self.model_outage = None
        # A toolbox per workload, bound to this workload.
        #
        # The toolbox remembers the last result of each tool, and `validate_policy` judges the
        # most recent `analyze_rightsizing` result. A shared toolbox would let one workload's
        # review validate another workload's proposal, and publish that verdict under this
        # workload's name - the model choosing which proposal the safety check judges, which
        # is the one thing the model must never do. A bound toolbox refuses the call instead.
        self.toolbox = AgentToolbox(self.bundle, workload_id=workload_id)
        lessons = self._historical_lessons(workload_id)
        audit_log.historical_lessons = lessons
        return audit_log, lessons

    async def _run_phases(self, workload_id: str, audit_log: AgentAuditLog,
                          lessons: List[str]) -> "ReviewRun":
        """The native engine: proposer, critic, revision, judge - in that order."""
        # --- Phase 1: Proposer -------------------------------------------------------
        proposer = await self._run_proposer(audit_log, workload_id, lessons)
        audit_log.cycles.append(proposer)

        formal = self._get_last_policy_result(audit_log)

        # --- Phase 2: Critic ---------------------------------------------------------
        critic = await self._run_critic(audit_log, workload_id, proposer, formal)
        audit_log.cycles.append(critic)

        # --- Phase 2b: Revision ------------------------------------------------------
        # The proposer answers the objections it never saw. Without this the cycle is a one-way
        # pipeline: the critic objects, the judge escalates, and the proposal that was never
        # allowed to respond is the one published.
        revision, revised = await self._run_revision(workload_id, critic, formal, audit_log.steps)
        if revision is not None:
            audit_log.cycles.append(revision)
        if revised is not None:
            formal = revised

        # The judge weighs the objections that survive, not the ones the revision retired. An
        # empty list is an answer: it means the revision answered all of them, and falling back to
        # the critic's list on falsiness would keep escalating a change nobody is making.
        effective_critic = (critic if revised is None or revision is None
                            else critic.model_copy(update={"objections": revision.objections}))

        # --- Phase 3: Judge ----------------------------------------------------------
        judge = await self._run_judge(workload_id, proposer, effective_critic, formal, revision)
        audit_log.cycles.append(judge)

        return ReviewRun(proposer=proposer, critic=critic, formal=formal, revision=revision,
                         revised=revised is not None, judge=judge)

    def _assemble(self, workload_id: str, audit_log: AgentAuditLog,
                  run: "ReviewRun") -> tuple[WorkloadResult, AgentAuditLog]:
        """Turn the phases into the verdict the report publishes."""
        revision = run.revision
        effective_critic = (run.critic if not run.revised or revision is None
                            else run.critic.model_copy(update={"objections": revision.objections}))

        verification = self.verifier.verify_report(run.proposer.summary or "", audit_log.steps)
        audit_log.verification_report = [
            VerificationStep(claimed_value=step.claimed_value, status=step.status)
            for step in _verification_steps(verification)
        ]
        confidence, basis = self._score_confidence(verification, run.formal, effective_critic.objections)
        audit_log.confidence_score = confidence
        audit_log.evidence_trail = self.verifier.evidence_trail(audit_log.steps)

        final_result = self._apply_judgment(run.formal, effective_critic, run.judge, confidence, basis, audit_log)
        if self.model_outage:
            # Say it on the result, not only in the cycle summary: this is the line a reviewer
            # reads next to the decision, and it must not let them believe a model reviewed
            # this workload when none did.
            note = ("The model server became unavailable during the review, so the agent cycle was cut "
                    "short and the deterministic critic decided this workload on its own.")
            final_result = final_result.model_copy(update={
                "confidence_basis": " ".join(part for part in (final_result.confidence_basis, note) if part),
            })
        audit_log.final_decision = final_result.decision
        return final_result, audit_log

    # ------------------------------------------------------------------ helpers
    def _now(self) -> datetime:
        """The analysis clock.

        The demo fixes it in policy.yaml so results are repeatable, and without it every metric
        looks stale relative to the wall clock. Every verdict this module produces is computed
        against this clock, so they cannot disagree with each other.
        """
        return self.bundle.policy.simulation_now or datetime.now(timezone.utc)

    def _score_confidence(self, verification: VerificationResult, formal: WorkloadResult,
                          objections: List[CriticObjection] | None = None) -> tuple[float, str]:
        """Blend number traceability with the evidence quality the proposal was built on."""
        proposal = formal.proposal
        metrics = proposal.metrics
        age_hours = None
        now = self._now()
        if metrics.last_observed_at is not None:
            observed = metrics.last_observed_at
            if observed.tzinfo is None:
                observed = observed.replace(tzinfo=timezone.utc)
            age_hours = max(0.0, (now - observed).total_seconds() / 3600)

        # The critic's min_samples is the floor for a *decision*; the optimizer's is the bar for a
        # *recommendation*. Confidence is measured against the stricter of the two, because a
        # recommendation built on fewer samples than the optimizer demands is not trustworthy.
        required = max(int(self.bundle.policy.critic.min_samples),
                       int(self.bundle.policy.optimizer.min_samples))
        risk_overlap = bool(proposal.incident_evidence) or any(
            check.code in {"PRIOR_INCIDENT_PATTERN", "HIGH_IMPACT_EVENT", "EVENT_FREEZE", "LOW_IMPACT_EVENT"}
            and check.status.value == "triggered" for check in formal.checks)
        objections = objections or []
        blocking = sum(1 for o in objections if o.severity == "blocking")
        advisory = sum(1 for o in objections if o.severity != "blocking")
        return self.verifier.score_confidence(
            verification,
            sample_count=metrics.sample_count,
            required_samples=required,
            age_hours=age_hours,
            max_age_hours=float(self.bundle.policy.critic.stale_after_hours),
            risk_overlap=risk_overlap,
            blocking_objections=blocking,
            advisory_objections=advisory,
        )

    def _apply_judgment(self, formal: WorkloadResult, critic: ReviewCycle, judge: ReviewCycle,
                        confidence: float, basis: str, audit_log: AgentAuditLog) -> WorkloadResult:
        """Fold the adversarial phase into the deterministic result.

        The Judge may only downgrade. An APPROVED decision with an unanswered blocking objection
        becomes NEEDS_REVIEW; it never becomes REJECTED, because the deterministic critic owns rejection.
        """
        blocking = [o for o in critic.objections if o.severity == "blocking"]
        result = formal.model_copy(update={
            "confidence_score": confidence,
            "confidence_basis": basis,
            "evidence_trail": audit_log.evidence_trail,
            "objections": critic.objections,
            "cycles": audit_log.cycles,
            "historical_lessons": audit_log.historical_lessons,
        })

        if not blocking or result.decision is not DecisionStatus.APPROVED:
            return result

        check = CriticCheck(
            name="adversarial_review",
            code="UNANSWERED_BLOCKING_OBJECTION",
            status=CheckStatus.TRIGGERED,
            message=("The adversarial review raised a blocking objection that the evidence does not answer: "
                     + "; ".join(o.message for o in blocking)),
            evidence={"severity": "review", "objections": [o.code for o in blocking]},
        )
        return result.model_copy(update={
            "decision": DecisionStatus.NEEDS_REVIEW,
            "risk_level": RiskLevel.MEDIUM,
            "reason": (f"Needs review: the deterministic checks passed, but the adversarial review raised "
                       f"{len(blocking)} blocking objection(s) — " + "; ".join(o.code for o in blocking) + "."),
            "monthly_savings_estimate_usd": 0.0,
            "checks": [*result.checks, check],
            "proposal": result.proposal.model_copy(update={"priority_score": 0.0}),
        })

    def _get_last_policy_result(self, audit_log: AgentAuditLog) -> WorkloadResult:
        """The deterministic critic's verdict for this workload.

        The verdict normally comes from the `validate_policy` tool, which runs the deterministic
        Context Critic over the proposal the optimizer produced. If the agent never called it -
        the model spent its budget on plans instead of tools - the deterministic critic still
        owns the decision, so it is run here over the same proposal. `validate_policy` validates
        the most recent `analyze_rightsizing` result when the model does not pass one of its
        own, so this is the same verdict the tool would have produced, not a second opinion.

        The only workload left without a verdict is one the agent never investigated at all, and
        that one is raised for a human rather than decided by the orchestrator.

        The one exception is a model outage: if the model server went away before the agent could
        gather anything, "the agent never investigated" is the wrong explanation - nobody chose
        anything. The deterministic pipeline decides that workload instead, exactly as it would
        have without an agent, and the result says the review was cut short.
        """
        for step in reversed(audit_log.steps):
            # A tool that failed holds `{"error": ...}`, not a verdict. Accepting one here used
            # to hand a dict to the rest of the cycle, which then died looking for `.proposal`
            # and cost the workload its whole review. The workload id is checked too: a verdict
            # about a different workload is not this workload's verdict.
            if (step.tool == "validate_policy"
                    and isinstance(step.result, WorkloadResult)
                    and step.result.workload_id == audit_log.workload_id):
                return step.result

        for step in reversed(audit_log.steps):
            if (step.tool == "analyze_rightsizing"
                    and isinstance(step.result, OptimizationProposal)
                    and step.result.workload_id == audit_log.workload_id):
                from app.services.critic_service import evaluate

                return evaluate(step.result, self.bundle, self._now())

        if self.model_outage:
            # The agent never got a turn. The deterministic critic still decides, and the
            # reviewer's report has to say that no model reviewed this workload.
            return deterministic_result(self.bundle, audit_log.workload_id, self._now())

        return WorkloadResult(
            workload_id=audit_log.workload_id,
            decision=DecisionStatus.NEEDS_REVIEW,
            risk_level=RiskLevel.HIGH,
            reason=("The agent never investigated this workload, so the deterministic policy "
                    "check was never run and there is no verdict to publish."),
            checks=[],
            proposal=OptimizationProposal(
                proposal_id="err", workload_id=audit_log.workload_id,
                status=ProposalStatus.NEEDS_REVIEW, current=ResourceSettings(), metrics=UsageMetrics(), created_at=self._now()
            )
        )


def _verification_steps(verification: VerificationResult) -> List[VerificationStep]:
    """Rebuild verification steps from the result counts (the service returns aggregates)."""
    steps = [VerificationStep(claimed_value="verified", status="verified") for _ in range(verification.verified_count)]
    steps += [VerificationStep(claimed_value="unverified", status="unverified") for _ in range(verification.unverified_count)]
    return steps
