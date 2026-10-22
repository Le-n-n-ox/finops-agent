from __future__ import annotations
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.models.schemas import (
    InputBundle,
    OptimizationProposal,
    WorkloadResult,
    AgentAuditLog,
    ToolCall,
    DecisionStatus,
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
from app.services import adversarial_service


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
    MAX_CRITIC_ITERATIONS = 4
    MAX_JUDGE_ITERATIONS = 3

    def __init__(self, bundle: InputBundle, llm_client: Any, store: Any = None):
        self.bundle = bundle
        self.llm = llm_client  # Assume an LLM client that supports tool use
        self.toolbox = AgentToolbox(bundle)
        self.verifier = VerificationService()
        self.store = store

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
    async def _chat(self, system: str, user: str, history: List[tuple]) -> Any:
        """Call the LLM and normalise the response.

        The LLM client may return a dict or an object; both are supported so a real client and the
        simulated one can be dropped in interchangeably.
        """
        response = await self.llm.chat(
            system=system,
            user=user,
            tools=self.toolbox.get_tool_definitions(),
            history=history,
        )
        if isinstance(response, dict):
            return {
                "content": response.get("content"),
                "tool_call": response.get("tool_call"),
                "thought": response.get("thought"),
                "conclusion": bool(response.get("conclusion")),
            }
        return {
            "content": getattr(response, "content", None),
            "tool_call": getattr(response, "tool_call", None),
            "thought": getattr(response, "thought", None),
            "conclusion": bool(getattr(response, "conclusion", False)),
        }

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
                         current_context: str) -> str:
        """Apply one LLM turn to a phase.

        Returns the updated context. The subtle case is a response that carries BOTH a tool call
        and a conclusion: the model is saying "run this tool, and here is my answer". The tool must
        still run - the conclusion is often premised on its result - but the phase is finished
        afterwards. Treating the conclusion as an immediate stop would silently skip the
        mandatory validate_policy call.
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
            return current_context

        # No tool call: the model has finished (or given up).
        cycle.summary = response["content"] or cycle.summary
        return current_context

    # ------------------------------------------------------------------ phase 1: proposer
    async def _run_proposer(self, audit_log: AgentAuditLog, workload_id: str, lessons: List[str]) -> ReviewCycle:
        """Gather evidence with tools and state a case. The cycle ends when the agent concludes."""
        cycle = ReviewCycle(role="proposer")
        system_prompt = self._proposer_prompt(workload_id, lessons)
        current_context = f"Analyze workload: {workload_id}. Find safe savings."
        history: List[tuple] = []

        for _ in range(self.MAX_PROPOSER_ITERATIONS):
            response = await self._chat(system_prompt, current_context, history)
            if response["thought"]:
                history.append((response["thought"], ""))
            before = len(cycle.steps)
            current_context = self._handle_response(response, cycle, audit_log, current_context)
            if len(cycle.steps) > before and response["conclusion"]:
                # The final tool ran; the proposal is complete.
                break
            if not response["tool_call"]:
                break

        if not cycle.summary:
            cycle.summary = "The proposer reached its iteration limit without concluding."
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
        history: List[tuple] = []

        for _ in range(self.MAX_CRITIC_ITERATIONS):
            response = await self._chat(system_prompt, current_context, history)
            if response["thought"]:
                history.append((response["thought"], ""))
            before = len(cycle.steps)
            current_context = self._handle_response(response, cycle, audit_log, current_context)
            if len(cycle.steps) > before and response["conclusion"]:
                break
            if not response["tool_call"]:
                break

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
                         formal: WorkloadResult | None) -> ReviewCycle:
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
            response = await self._chat(system_prompt, user, [])
            if response.get("content"):
                cycle.summary = f"{cycle.summary} {response['content']}"
        except Exception:  # noqa: BLE001 - narration is optional; the deterministic ruling stands
            pass

        cycle.completed_at = datetime.now(timezone.utc)
        return cycle

    # ------------------------------------------------------------------ entry point
    async def analyze_workload_agentic(self, workload_id: str) -> tuple[WorkloadResult, AgentAuditLog]:
        session_id = str(uuid.uuid4())
        audit_log = AgentAuditLog(session_id=session_id, workload_id=workload_id)

        lessons = self._historical_lessons(workload_id)
        audit_log.historical_lessons = lessons

        # --- Phase 1: Proposer -------------------------------------------------------
        proposer = await self._run_proposer(audit_log, workload_id, lessons)
        audit_log.cycles.append(proposer)

        formal = self._get_last_policy_result(audit_log)

        # --- Phase 2: Critic ---------------------------------------------------------
        critic = await self._run_critic(audit_log, workload_id, proposer, formal)
        audit_log.cycles.append(critic)

        # --- Phase 3: Judge ----------------------------------------------------------
        judge = await self._run_judge(workload_id, proposer, critic, formal)
        audit_log.cycles.append(judge)

        # --- Assemble the final result ----------------------------------------------
        verification = self.verifier.verify_report(proposer.summary or "", audit_log.steps)
        audit_log.verification_report = [
            VerificationStep(claimed_value=step.claimed_value, status=step.status)
            for step in _verification_steps(verification)
        ]
        confidence, basis = self._score_confidence(verification, formal, critic.objections)
        audit_log.confidence_score = confidence
        audit_log.evidence_trail = self.verifier.evidence_trail(audit_log.steps)

        final_result = self._apply_judgment(formal, critic, judge, confidence, basis, audit_log)
        audit_log.final_decision = final_result.decision
        return final_result, audit_log

    # ------------------------------------------------------------------ helpers
    def _score_confidence(self, verification: VerificationResult, formal: WorkloadResult,
                          objections: List[CriticObjection] | None = None) -> tuple[float, str]:
        """Blend number traceability with the evidence quality the proposal was built on."""
        proposal = formal.proposal
        metrics = proposal.metrics
        age_hours = None
        now = self.bundle.policy.simulation_now or datetime.now(timezone.utc)
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
        for step in reversed(audit_log.steps):
            if step.tool == "validate_policy":
                return step.result
        # Fallback: create a dummy needs_review result if the agent skipped the policy check
        return WorkloadResult(
            workload_id=audit_log.workload_id,
            decision=DecisionStatus.NEEDS_REVIEW,
            risk_level="high",
            reason="Agent failed to perform mandatory policy validation.",
            checks=[],
            proposal=OptimizationProposal(
                proposal_id="err", workload_id=audit_log.workload_id,
                status="needs_review", current=ResourceSettings(), metrics=UsageMetrics(), created_at=datetime.now(timezone.utc)
            )
        )


def _verification_steps(verification: VerificationResult) -> List[VerificationStep]:
    """Rebuild verification steps from the result counts (the service returns aggregates)."""
    steps = [VerificationStep(claimed_value="verified", status="verified") for _ in range(verification.verified_count)]
    steps += [VerificationStep(claimed_value="unverified", status="unverified") for _ in range(verification.unverified_count)]
    return steps
