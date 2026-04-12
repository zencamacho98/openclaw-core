# tests/test_frank_lloyd_provider_router.py
#
# Unit tests for frank_lloyd/provider_router.py
#
# Coverage:
#   - fl_route(): correct tier/model for each task class, stage enforcement,
#     risk_override upgrades only, error shape
#   - FLLMHelper.routing_decision(): delegation to fl_route()
#   - FLLMHelper.call(): stage restriction honored, delegates to LMHelper with
#     correct model_override and force_tier
#   - FL_PROVIDER_REGISTRY: approval requirements per tier
#   - FL_TASK_POLICY: stage restrictions, tier assignments
#   - get_fl_policy_report(): structure and completeness

import unittest
from unittest.mock import MagicMock, patch

from frank_lloyd.provider_router import (
    FLLMHelper,
    FLProviderTier,
    FLRoutingDecision,
    FLTaskClass,
    FL_PROVIDER_REGISTRY,
    FL_TASK_POLICY,
    _tier_rank,
    fl_route,
    get_fl_policy_report,
)


# ── fl_route() per task class ──────────────────────────────────────────────────

class TestFlRouteSpecDraft(unittest.TestCase):
    def test_routes_to_cheap_tier(self):
        d = fl_route(FLTaskClass.SPEC_DRAFT, stage=1)
        self.assertEqual(d.provider_tier, FLProviderTier.CHEAP)

    def test_stage_1_allowed(self):
        d = fl_route(FLTaskClass.SPEC_DRAFT, stage=1)
        self.assertTrue(d.stage_allowed)
        self.assertEqual(d.error, "")

    def test_stage_2_blocked(self):
        d = fl_route(FLTaskClass.SPEC_DRAFT, stage=2)
        self.assertFalse(d.stage_allowed)
        self.assertIn("Stage", d.error)
        self.assertEqual(d.model, "")

    def test_no_operator_approval_required(self):
        d = fl_route(FLTaskClass.SPEC_DRAFT, stage=1)
        self.assertFalse(d.operator_approval_required)

    def test_model_is_non_empty(self):
        d = fl_route(FLTaskClass.SPEC_DRAFT, stage=1)
        self.assertTrue(len(d.model) > 0)

    def test_model_is_openai_by_default(self):
        d = fl_route(FLTaskClass.SPEC_DRAFT, stage=1)
        # Default cheap model is openai/gpt-4o-mini (unless FL_CHEAP_MODEL env override)
        self.assertNotIn("anthropic", d.model.lower())


class TestFlRouteCodeDraftLow(unittest.TestCase):
    def test_routes_to_cheap_tier(self):
        d = fl_route(FLTaskClass.CODE_DRAFT_LOW, stage=2)
        self.assertEqual(d.provider_tier, FLProviderTier.CHEAP)

    def test_stage_2_allowed(self):
        d = fl_route(FLTaskClass.CODE_DRAFT_LOW, stage=2)
        self.assertTrue(d.stage_allowed)

    def test_stage_1_blocked(self):
        d = fl_route(FLTaskClass.CODE_DRAFT_LOW, stage=1)
        self.assertFalse(d.stage_allowed)

    def test_no_operator_approval_required(self):
        d = fl_route(FLTaskClass.CODE_DRAFT_LOW, stage=2)
        self.assertFalse(d.operator_approval_required)


class TestFlRouteCodeDraftMedium(unittest.TestCase):
    def test_routes_to_coding_tier(self):
        d = fl_route(FLTaskClass.CODE_DRAFT_MEDIUM, stage=2)
        self.assertEqual(d.provider_tier, FLProviderTier.CODING)

    def test_stage_2_allowed(self):
        d = fl_route(FLTaskClass.CODE_DRAFT_MEDIUM, stage=2)
        self.assertTrue(d.stage_allowed)

    def test_stage_1_blocked(self):
        d = fl_route(FLTaskClass.CODE_DRAFT_MEDIUM, stage=1)
        self.assertFalse(d.stage_allowed)

    def test_operator_approval_required(self):
        d = fl_route(FLTaskClass.CODE_DRAFT_MEDIUM, stage=2)
        self.assertTrue(d.operator_approval_required)

    def test_model_is_openai_by_default(self):
        d = fl_route(FLTaskClass.CODE_DRAFT_MEDIUM, stage=2)
        # Coding lane defaults to openai/gpt-4o
        self.assertNotIn("anthropic", d.model.lower())


class TestFlRouteCodeDraftCritical(unittest.TestCase):
    def test_routes_to_codex_supervised_tier(self):
        d = fl_route(FLTaskClass.CODE_DRAFT_CRITICAL, stage=2)
        self.assertEqual(d.provider_tier, FLProviderTier.CODEX_SUPERVISED)

    def test_stage_2_allowed(self):
        d = fl_route(FLTaskClass.CODE_DRAFT_CRITICAL, stage=2)
        self.assertTrue(d.stage_allowed)

    def test_stage_1_blocked(self):
        d = fl_route(FLTaskClass.CODE_DRAFT_CRITICAL, stage=1)
        self.assertFalse(d.stage_allowed)

    def test_operator_approval_required(self):
        d = fl_route(FLTaskClass.CODE_DRAFT_CRITICAL, stage=2)
        self.assertTrue(d.operator_approval_required)

    def test_model_is_not_claude_by_default(self):
        d = fl_route(FLTaskClass.CODE_DRAFT_CRITICAL, stage=2)
        self.assertNotIn("anthropic", d.model.lower())


class TestFlRouteReviewProof(unittest.TestCase):
    def test_routes_to_critical_tier(self):
        d = fl_route(FLTaskClass.REVIEW_PROOF, stage=2)
        self.assertEqual(d.provider_tier, FLProviderTier.CRITICAL)

    def test_stage_2_allowed(self):
        d = fl_route(FLTaskClass.REVIEW_PROOF, stage=2)
        self.assertTrue(d.stage_allowed)

    def test_stage_1_blocked(self):
        d = fl_route(FLTaskClass.REVIEW_PROOF, stage=1)
        self.assertFalse(d.stage_allowed)

    def test_operator_approval_required(self):
        d = fl_route(FLTaskClass.REVIEW_PROOF, stage=2)
        self.assertTrue(d.operator_approval_required)

    def test_model_is_claude_opus_by_default(self):
        d = fl_route(FLTaskClass.REVIEW_PROOF, stage=2)
        self.assertIn("opus", d.model.lower())


# ── fl_route() risk_override ───────────────────────────────────────────────────

class TestFlRouteRiskOverride(unittest.TestCase):
    def test_override_upgrades_cheap_to_coding(self):
        d = fl_route(FLTaskClass.SPEC_DRAFT, stage=1,
                     risk_override=FLProviderTier.CODING)
        # SPEC_DRAFT is Stage 1 only and CODING has no Stage 1 restriction via override
        # Actually: spec_draft stage_allowed=True for stage=1; risk_override upgrades tier
        self.assertEqual(d.provider_tier, FLProviderTier.CODING)

    def test_override_upgrades_cheap_to_strong(self):
        d = fl_route(FLTaskClass.CODE_DRAFT_LOW, stage=2,
                     risk_override=FLProviderTier.STRONG)
        self.assertEqual(d.provider_tier, FLProviderTier.STRONG)

    def test_override_never_downgrades(self):
        """risk_override=CHEAP should not downgrade a CODEX_SUPERVISED task."""
        d = fl_route(FLTaskClass.CODE_DRAFT_CRITICAL, stage=2,
                     risk_override=FLProviderTier.CHEAP)
        self.assertEqual(d.provider_tier, FLProviderTier.CODEX_SUPERVISED)

    def test_override_same_tier_unchanged(self):
        d = fl_route(FLTaskClass.CODE_DRAFT_MEDIUM, stage=2,
                     risk_override=FLProviderTier.CODING)
        self.assertEqual(d.provider_tier, FLProviderTier.CODING)

    def test_override_does_not_affect_blocked_stage(self):
        """Stage restriction still applies even with a risk override."""
        d = fl_route(FLTaskClass.CODE_DRAFT_MEDIUM, stage=1,
                     risk_override=FLProviderTier.CRITICAL)
        self.assertFalse(d.stage_allowed)


# ── fl_route() routing decision shape ─────────────────────────────────────────

class TestFlRoutingDecisionShape(unittest.TestCase):
    def test_successful_decision_fields(self):
        d = fl_route(FLTaskClass.SPEC_DRAFT, stage=1)
        self.assertIsInstance(d, FLRoutingDecision)
        self.assertIsInstance(d.task_class, FLTaskClass)
        self.assertIsInstance(d.provider_tier, FLProviderTier)
        self.assertIsInstance(d.model, str)
        self.assertIsInstance(d.stage_allowed, bool)
        self.assertIsInstance(d.operator_approval_required, bool)
        self.assertIsInstance(d.description, str)
        self.assertIsInstance(d.error, str)

    def test_blocked_decision_has_empty_model(self):
        d = fl_route(FLTaskClass.CODE_DRAFT_LOW, stage=1)
        self.assertFalse(d.stage_allowed)
        self.assertEqual(d.model, "")
        self.assertTrue(len(d.error) > 0)

    def test_error_mentions_stage_on_block(self):
        d = fl_route(FLTaskClass.CODE_DRAFT_MEDIUM, stage=1)
        self.assertIn("Stage", d.error)
        self.assertIn("2", d.error)


# ── Tier rank ordering ────────────────────────────────────────────────────────

class TestTierRank(unittest.TestCase):
    def test_cheap_lowest(self):
        self.assertEqual(_tier_rank(FLProviderTier.CHEAP), 0)

    def test_coding_above_cheap(self):
        self.assertGreater(
            _tier_rank(FLProviderTier.CODING),
            _tier_rank(FLProviderTier.CHEAP),
        )

    def test_strong_above_coding(self):
        self.assertGreater(
            _tier_rank(FLProviderTier.STRONG),
            _tier_rank(FLProviderTier.CODING),
        )

    def test_critical_highest(self):
        self.assertGreater(
            _tier_rank(FLProviderTier.CRITICAL),
            _tier_rank(FLProviderTier.STRONG),
        )


# ── FL_PROVIDER_REGISTRY ──────────────────────────────────────────────────────

class TestFLProviderRegistry(unittest.TestCase):
    def test_all_tiers_registered(self):
        for tier in FLProviderTier:
            self.assertIn(tier, FL_PROVIDER_REGISTRY)

    def test_cheap_no_approval_required(self):
        self.assertFalse(FL_PROVIDER_REGISTRY[FLProviderTier.CHEAP].operator_approval_required)

    def test_coding_approval_required(self):
        self.assertTrue(FL_PROVIDER_REGISTRY[FLProviderTier.CODING].operator_approval_required)

    def test_strong_approval_required(self):
        self.assertTrue(FL_PROVIDER_REGISTRY[FLProviderTier.STRONG].operator_approval_required)

    def test_critical_approval_required(self):
        self.assertTrue(FL_PROVIDER_REGISTRY[FLProviderTier.CRITICAL].operator_approval_required)

    def test_all_tiers_have_non_empty_model(self):
        for tier, cfg in FL_PROVIDER_REGISTRY.items():
            self.assertTrue(len(cfg.model) > 0, f"Empty model for {tier}")

    def test_cheap_and_coding_are_openai(self):
        """Cheap and coding lanes default to OpenAI models (not Claude)."""
        cheap_model  = FL_PROVIDER_REGISTRY[FLProviderTier.CHEAP].model
        coding_model = FL_PROVIDER_REGISTRY[FLProviderTier.CODING].model
        self.assertNotIn("anthropic", cheap_model.lower())
        self.assertNotIn("anthropic", coding_model.lower())

    def test_strong_and_critical_are_claude(self):
        """Strong and critical lanes default to Claude models."""
        strong_model   = FL_PROVIDER_REGISTRY[FLProviderTier.STRONG].model
        critical_model = FL_PROVIDER_REGISTRY[FLProviderTier.CRITICAL].model
        self.assertIn("anthropic", strong_model.lower())
        self.assertIn("anthropic", critical_model.lower())

    def test_cost_order_roughly_ascending(self):
        """Higher tiers should not be cheaper than lower tiers."""
        cheap  = FL_PROVIDER_REGISTRY[FLProviderTier.CHEAP].cost_per_1m_input
        coding = FL_PROVIDER_REGISTRY[FLProviderTier.CODING].cost_per_1m_input
        strong = FL_PROVIDER_REGISTRY[FLProviderTier.STRONG].cost_per_1m_input
        critical = FL_PROVIDER_REGISTRY[FLProviderTier.CRITICAL].cost_per_1m_input
        self.assertLessEqual(cheap, coding)
        self.assertLessEqual(strong, critical)


# ── FL_TASK_POLICY ────────────────────────────────────────────────────────────

class TestFLTaskPolicy(unittest.TestCase):
    def test_all_task_classes_have_policy(self):
        for tc in FLTaskClass:
            self.assertIn(tc, FL_TASK_POLICY)

    def test_spec_draft_stage_1_only(self):
        p = FL_TASK_POLICY[FLTaskClass.SPEC_DRAFT]
        self.assertIn(1, p.stages_allowed)
        self.assertNotIn(2, p.stages_allowed)

    def test_code_tasks_stage_2_only(self):
        for tc in (
            FLTaskClass.CODE_DRAFT_LOW,
            FLTaskClass.CODE_DRAFT_MEDIUM,
            FLTaskClass.CODE_DRAFT_CRITICAL,
            FLTaskClass.REVIEW_PROOF,
        ):
            p = FL_TASK_POLICY[tc]
            self.assertIn(2, p.stages_allowed, f"{tc} should allow Stage 2")
            self.assertNotIn(1, p.stages_allowed, f"{tc} should not allow Stage 1")

    def test_approval_policy_consistency(self):
        """operator_approval_required in task policy matches the provider registry."""
        for tc, p in FL_TASK_POLICY.items():
            provider_cfg = FL_PROVIDER_REGISTRY[p.provider_tier]
            self.assertEqual(
                p.operator_approval_required,
                provider_cfg.operator_approval_required,
                f"Mismatch for {tc}",
            )

    def test_escalating_risk_levels(self):
        """Task classes should use non-decreasing tier ranks."""
        spec_rank     = _tier_rank(FL_TASK_POLICY[FLTaskClass.SPEC_DRAFT].provider_tier)
        low_rank      = _tier_rank(FL_TASK_POLICY[FLTaskClass.CODE_DRAFT_LOW].provider_tier)
        medium_rank   = _tier_rank(FL_TASK_POLICY[FLTaskClass.CODE_DRAFT_MEDIUM].provider_tier)
        critical_rank = _tier_rank(FL_TASK_POLICY[FLTaskClass.CODE_DRAFT_CRITICAL].provider_tier)
        proof_rank    = _tier_rank(FL_TASK_POLICY[FLTaskClass.REVIEW_PROOF].provider_tier)
        self.assertLessEqual(spec_rank, low_rank)
        self.assertLessEqual(low_rank, medium_rank)
        self.assertLessEqual(medium_rank, critical_rank)
        self.assertLessEqual(critical_rank, proof_rank)


# ── FLLMHelper ────────────────────────────────────────────────────────────────

class TestFLLMHelperRoutingDecision(unittest.TestCase):
    def test_routing_decision_delegates_to_fl_route(self):
        helper = FLLMHelper(FLTaskClass.SPEC_DRAFT)
        d = helper.routing_decision(stage=1)
        self.assertEqual(d.task_class, FLTaskClass.SPEC_DRAFT)
        self.assertTrue(d.stage_allowed)
        self.assertEqual(d.provider_tier, FLProviderTier.CHEAP)

    def test_routing_decision_blocked_stage(self):
        helper = FLLMHelper(FLTaskClass.CODE_DRAFT_MEDIUM)
        d = helper.routing_decision(stage=1)
        self.assertFalse(d.stage_allowed)

    def test_routing_decision_with_override(self):
        helper = FLLMHelper(FLTaskClass.CODE_DRAFT_LOW)
        d = helper.routing_decision(stage=2, risk_override=FLProviderTier.STRONG)
        self.assertEqual(d.provider_tier, FLProviderTier.STRONG)


class TestFLLMHelperCall(unittest.TestCase):

    def _make_mock_lm_result(self, ok=True, content="response", error=""):
        mock = MagicMock()
        mock.ok            = ok
        mock.content       = content
        mock.model_used    = "openai/gpt-4o-mini"
        mock.tier_used     = "cheap"
        mock.reason        = "test"
        mock.error         = error
        mock.input_tokens  = 10
        mock.output_tokens = 5
        mock.cost_usd      = 0.0001
        return mock

    def test_stage_restriction_returns_error_result(self):
        """call() on a wrong-stage task returns ok=False without hitting LM."""
        helper = FLLMHelper(FLTaskClass.CODE_DRAFT_MEDIUM)
        with patch("app.cost_warden.LMHelper") as mock_lm_cls:
            result = helper.call(system="sys", user="usr", stage=1)
        # LMHelper should NOT have been instantiated
        mock_lm_cls.assert_not_called()
        self.assertFalse(result.ok)
        self.assertIn("Stage", result.error)

    def test_cheap_task_dispatches_with_correct_tier(self):
        """SPEC_DRAFT (cheap) passes force_tier='cheap' to LMHelper."""
        helper = FLLMHelper(FLTaskClass.SPEC_DRAFT, max_tokens=700)
        captured = {}

        def _capture_lm_helper(agent_name, task, max_tokens, temperature, force_tier, model_override):
            captured["force_tier"]     = force_tier
            captured["model_override"] = model_override
            captured["task"]           = task
            mock_instance = MagicMock()
            mock_instance.call.return_value = self._make_mock_lm_result()
            return mock_instance

        with patch("frank_lloyd.provider_router.FLLMHelper.call",
                   wraps=helper.call) as _:
            with patch("app.cost_warden.LMHelper", side_effect=_capture_lm_helper):
                result = helper.call(system="sys", user="usr", stage=1)

        self.assertEqual(captured.get("force_tier"), "cheap")
        self.assertEqual(captured.get("task"), FLTaskClass.SPEC_DRAFT.value)
        # model_override should be the cheap lane model (not empty)
        self.assertTrue(len(captured.get("model_override", "")) > 0)

    def test_coding_task_dispatches_with_strong_tier_and_override(self):
        """CODE_DRAFT_MEDIUM (coding tier) passes force_tier='strong' + model_override."""
        helper = FLLMHelper(FLTaskClass.CODE_DRAFT_MEDIUM, max_tokens=500)
        captured = {}

        def _capture_lm_helper(agent_name, task, max_tokens, temperature, force_tier, model_override):
            captured["force_tier"]     = force_tier
            captured["model_override"] = model_override
            mock_instance = MagicMock()
            mock_instance.call.return_value = self._make_mock_lm_result()
            return mock_instance

        with patch("app.cost_warden.LMHelper", side_effect=_capture_lm_helper):
            result = helper.call(system="sys", user="usr", stage=2)

        # Coding tier → warden tier "strong", model_override = FL_CODING_MODEL
        self.assertEqual(captured.get("force_tier"), "strong")
        model_ov = captured.get("model_override", "")
        self.assertNotIn("anthropic", model_ov.lower(), "Coding lane should not use Claude")

    def test_critical_task_returns_error_not_callable(self):
        """CODE_DRAFT_CRITICAL is external_supervised — FLLMHelper must refuse without API call."""
        helper = FLLMHelper(FLTaskClass.CODE_DRAFT_CRITICAL, max_tokens=500)

        with patch("app.cost_warden.LMHelper") as mock_lm_cls:
            result = helper.call(system="sys", user="usr", stage=2)

        # LMHelper must NOT be called — no API call for external_supervised lanes
        mock_lm_cls.assert_not_called()
        self.assertFalse(result.ok)
        self.assertIn("external_supervised", result.error)
        self.assertIn("codex_supervised", result.error)

    def test_successful_call_returns_ok(self):
        helper = FLLMHelper(FLTaskClass.SPEC_DRAFT)

        def _make_lm(*a, **kw):
            mock_instance = MagicMock()
            mock_instance.call.return_value = self._make_mock_lm_result(content="good spec")
            return mock_instance

        with patch("app.cost_warden.LMHelper", side_effect=_make_lm):
            result = helper.call(system="sys", user="usr", stage=1)

        self.assertTrue(result.ok)
        self.assertEqual(result.content, "good spec")

    def test_lm_error_propagated(self):
        helper = FLLMHelper(FLTaskClass.SPEC_DRAFT)

        def _make_lm(*a, **kw):
            mock_instance = MagicMock()
            mock_instance.call.return_value = self._make_mock_lm_result(ok=False, error="API error")
            return mock_instance

        with patch("app.cost_warden.LMHelper", side_effect=_make_lm):
            result = helper.call(system="sys", user="usr", stage=1)

        self.assertFalse(result.ok)
        self.assertIn("API error", result.error)


# ── get_fl_policy_report() ────────────────────────────────────────────────────

class TestGetFLPolicyReport(unittest.TestCase):
    def setUp(self):
        self.report = get_fl_policy_report()

    def test_has_provider_registry(self):
        self.assertIn("provider_registry", self.report)

    def test_has_all_provider_tiers(self):
        registry = self.report["provider_registry"]
        for tier in FLProviderTier:
            self.assertIn(tier.value, registry)

    def test_has_task_policy(self):
        self.assertIn("task_policy", self.report)

    def test_has_all_task_classes(self):
        policy = self.report["task_policy"]
        for tc in FLTaskClass:
            self.assertIn(tc.value, policy)

    def test_has_active_lanes(self):
        self.assertIn("active_lanes", self.report)
        lanes = self.report["active_lanes"]
        for key in ("cheap", "coding", "codex", "strong", "critical"):
            self.assertIn(key, lanes)
            self.assertTrue(len(lanes[key]) > 0)

    def test_has_env_overrides(self):
        self.assertIn("env_overrides", self.report)
        overrides = self.report["env_overrides"]
        for key in ("FL_CHEAP_MODEL", "FL_CODING_MODEL", "FL_CODEX_MODEL",
                    "FL_STRONG_MODEL", "FL_CRITICAL_MODEL"):
            self.assertIn(key, overrides)

    def test_stage_1_active_tasks(self):
        self.assertIn("stage_1_active_tasks", self.report)
        self.assertIn(FLTaskClass.SPEC_DRAFT.value, self.report["stage_1_active_tasks"])
        # No Stage 2 code tasks in Stage 1
        for tc in (FLTaskClass.CODE_DRAFT_LOW, FLTaskClass.CODE_DRAFT_MEDIUM,
                   FLTaskClass.CODE_DRAFT_CRITICAL, FLTaskClass.REVIEW_PROOF):
            self.assertNotIn(tc.value, self.report["stage_1_active_tasks"])

    def test_stage_2_ready_tasks(self):
        self.assertIn("stage_2_ready_tasks", self.report)
        for tc in (FLTaskClass.CODE_DRAFT_LOW, FLTaskClass.CODE_DRAFT_MEDIUM,
                   FLTaskClass.CODE_DRAFT_CRITICAL, FLTaskClass.REVIEW_PROOF):
            self.assertIn(tc.value, self.report["stage_2_ready_tasks"])
        self.assertNotIn(FLTaskClass.SPEC_DRAFT.value, self.report["stage_2_ready_tasks"])

    def test_task_policy_entries_have_expected_fields(self):
        policy = self.report["task_policy"]
        for tc_name, entry in policy.items():
            self.assertIn("provider_tier", entry, f"Missing provider_tier for {tc_name}")
            self.assertIn("model", entry, f"Missing model for {tc_name}")
            self.assertIn("stages_allowed", entry, f"Missing stages_allowed for {tc_name}")
            self.assertIn("operator_approval_required", entry)
            self.assertIn("description", entry)

    def test_cheap_lane_not_claude(self):
        cheap_model = self.report["active_lanes"]["cheap"]
        self.assertNotIn("anthropic", cheap_model.lower())

    def test_coding_lane_not_claude(self):
        coding_model = self.report["active_lanes"]["coding"]
        self.assertNotIn("anthropic", coding_model.lower())

    def test_strong_lane_is_claude(self):
        strong_model = self.report["active_lanes"]["strong"]
        self.assertIn("anthropic", strong_model.lower())

    def test_critical_lane_is_claude_opus(self):
        critical_model = self.report["active_lanes"]["critical"]
        self.assertIn("anthropic", critical_model.lower())
        self.assertIn("opus", critical_model.lower())


# ── LMHelper model_override integration ──────────────────────────────────────

class TestLMHelperModelOverride(unittest.TestCase):
    """Verify that cost_warden.LMHelper honours model_override."""

    def test_model_override_replaces_decision_model(self):
        """When model_override is set, the specified model is used in the call."""
        from app.cost_warden import LMHelper

        captured_model = {}

        def _fake_openrouter_call(model, system, user, max_tokens, temperature, json_mode=False):
            captured_model["model"] = model
            return {"content": "ok", "input_tokens": 10, "output_tokens": 5}

        with patch("app.cost_warden._openrouter_call", side_effect=_fake_openrouter_call):
            with patch("app.cost_warden._load_api_key", return_value="fake-key"):
                with patch("app.cost_warden._log_usage"):
                    helper = LMHelper(
                        "test_agent", "spec_draft",
                        force_tier="cheap",
                        model_override="openai/gpt-4o",
                    )
                    result = helper.call(system="sys", user="usr")

        self.assertTrue(result.ok)
        self.assertEqual(captured_model.get("model"), "openai/gpt-4o")

    def test_no_model_override_uses_default(self):
        """Without model_override, the tier-resolved model is used."""
        from app.cost_warden import LMHelper, CHEAP_MODEL

        captured_model = {}

        def _fake_openrouter_call(model, system, user, max_tokens, temperature, json_mode=False):
            captured_model["model"] = model
            return {"content": "ok", "input_tokens": 10, "output_tokens": 5}

        with patch("app.cost_warden._openrouter_call", side_effect=_fake_openrouter_call):
            with patch("app.cost_warden._load_api_key", return_value="fake-key"):
                with patch("app.cost_warden._log_usage"):
                    helper = LMHelper("test_agent", "spec_draft", force_tier="cheap")
                    result = helper.call(system="sys", user="usr")

        self.assertTrue(result.ok)
        self.assertEqual(captured_model.get("model"), CHEAP_MODEL)


# ── TestFlRouteCodexSupervised ────────────────────────────────────────────────

class TestFlRouteCodexSupervised(unittest.TestCase):
    """Routing tests specific to the CODEX_SUPERVISED tier."""

    def test_code_draft_critical_routes_to_codex_supervised(self):
        d = fl_route(FLTaskClass.CODE_DRAFT_CRITICAL, stage=2)
        self.assertEqual(d.provider_tier, FLProviderTier.CODEX_SUPERVISED)

    def test_codex_supervised_stage_2_only(self):
        d = fl_route(FLTaskClass.CODE_DRAFT_CRITICAL, stage=1)
        self.assertFalse(d.stage_allowed)

    def test_codex_supervised_approval_required(self):
        d = fl_route(FLTaskClass.CODE_DRAFT_CRITICAL, stage=2)
        self.assertTrue(d.operator_approval_required)

    def test_codex_supervised_executability_is_external_supervised(self):
        d = fl_route(FLTaskClass.CODE_DRAFT_CRITICAL, stage=2)
        self.assertEqual(d.executability, "external_supervised")

    def test_codex_supervised_transport_is_supervised_external(self):
        d = fl_route(FLTaskClass.CODE_DRAFT_CRITICAL, stage=2)
        self.assertEqual(d.transport_mode, "supervised_external")

    def test_codex_supervised_provider_family_is_codex(self):
        d = fl_route(FLTaskClass.CODE_DRAFT_CRITICAL, stage=2)
        self.assertEqual(d.provider_family, "codex")

    def test_override_to_codex_from_coding(self):
        d = fl_route(FLTaskClass.CODE_DRAFT_MEDIUM, stage=2,
                     risk_override=FLProviderTier.CODEX_SUPERVISED)
        self.assertEqual(d.provider_tier, FLProviderTier.CODEX_SUPERVISED)
        self.assertEqual(d.executability, "external_supervised")


# ── TestFLProviderMetadata ─────────────────────────────────────────────────────

class TestFLProviderMetadata(unittest.TestCase):
    """provider_family, transport_mode, executability for all registry tiers."""

    def test_cheap_provider_family_openrouter(self):
        cfg = FL_PROVIDER_REGISTRY[FLProviderTier.CHEAP]
        self.assertEqual(cfg.provider_family, "openrouter")

    def test_cheap_transport_api(self):
        cfg = FL_PROVIDER_REGISTRY[FLProviderTier.CHEAP]
        self.assertEqual(cfg.transport_mode, "api")

    def test_cheap_executability_executable(self):
        cfg = FL_PROVIDER_REGISTRY[FLProviderTier.CHEAP]
        self.assertEqual(cfg.executability, "executable")

    def test_coding_provider_family_openrouter(self):
        cfg = FL_PROVIDER_REGISTRY[FLProviderTier.CODING]
        self.assertEqual(cfg.provider_family, "openrouter")

    def test_coding_transport_api(self):
        cfg = FL_PROVIDER_REGISTRY[FLProviderTier.CODING]
        self.assertEqual(cfg.transport_mode, "api")

    def test_coding_executability_config_only(self):
        cfg = FL_PROVIDER_REGISTRY[FLProviderTier.CODING]
        self.assertEqual(cfg.executability, "config_only")

    def test_codex_supervised_provider_family_codex(self):
        cfg = FL_PROVIDER_REGISTRY[FLProviderTier.CODEX_SUPERVISED]
        self.assertEqual(cfg.provider_family, "codex")

    def test_codex_supervised_transport_supervised_external(self):
        cfg = FL_PROVIDER_REGISTRY[FLProviderTier.CODEX_SUPERVISED]
        self.assertEqual(cfg.transport_mode, "supervised_external")

    def test_codex_supervised_executability_external_supervised(self):
        cfg = FL_PROVIDER_REGISTRY[FLProviderTier.CODEX_SUPERVISED]
        self.assertEqual(cfg.executability, "external_supervised")

    def test_codex_supervised_cost_is_zero(self):
        cfg = FL_PROVIDER_REGISTRY[FLProviderTier.CODEX_SUPERVISED]
        self.assertEqual(cfg.cost_per_1m_input, 0.0)
        self.assertEqual(cfg.cost_per_1m_output, 0.0)

    def test_strong_provider_family_claude(self):
        cfg = FL_PROVIDER_REGISTRY[FLProviderTier.STRONG]
        self.assertEqual(cfg.provider_family, "claude")

    def test_strong_transport_api(self):
        cfg = FL_PROVIDER_REGISTRY[FLProviderTier.STRONG]
        self.assertEqual(cfg.transport_mode, "api")

    def test_strong_executability_executable(self):
        cfg = FL_PROVIDER_REGISTRY[FLProviderTier.STRONG]
        self.assertEqual(cfg.executability, "executable")

    def test_critical_provider_family_claude(self):
        cfg = FL_PROVIDER_REGISTRY[FLProviderTier.CRITICAL]
        self.assertEqual(cfg.provider_family, "claude")

    def test_critical_transport_api(self):
        cfg = FL_PROVIDER_REGISTRY[FLProviderTier.CRITICAL]
        self.assertEqual(cfg.transport_mode, "api")

    def test_critical_executability_executable(self):
        cfg = FL_PROVIDER_REGISTRY[FLProviderTier.CRITICAL]
        self.assertEqual(cfg.executability, "executable")


# ── TestFLLMHelperExecutabilityEnforcement ────────────────────────────────────

class TestFLLMHelperExecutabilityEnforcement(unittest.TestCase):
    """external_supervised lanes must return ok=False without making any API call."""

    def test_code_draft_critical_refused_without_api_call(self):
        helper = FLLMHelper(FLTaskClass.CODE_DRAFT_CRITICAL)
        with patch("app.cost_warden.LMHelper") as mock_lm_cls:
            result = helper.call(system="sys", user="usr", stage=2)
        mock_lm_cls.assert_not_called()
        self.assertFalse(result.ok)

    def test_refused_error_mentions_external_supervised(self):
        helper = FLLMHelper(FLTaskClass.CODE_DRAFT_CRITICAL)
        with patch("app.cost_warden.LMHelper"):
            result = helper.call(system="sys", user="usr", stage=2)
        self.assertIn("external_supervised", result.error)

    def test_refused_error_mentions_codex(self):
        helper = FLLMHelper(FLTaskClass.CODE_DRAFT_CRITICAL)
        with patch("app.cost_warden.LMHelper"):
            result = helper.call(system="sys", user="usr", stage=2)
        self.assertIn("codex_supervised", result.error)

    def test_refused_tier_used_is_codex_supervised(self):
        helper = FLLMHelper(FLTaskClass.CODE_DRAFT_CRITICAL)
        with patch("app.cost_warden.LMHelper"):
            result = helper.call(system="sys", user="usr", stage=2)
        self.assertEqual(result.tier_used, FLProviderTier.CODEX_SUPERVISED.value)

    def test_override_to_codex_supervised_also_refused(self):
        """A risk_override that resolves to codex_supervised is still refused."""
        helper = FLLMHelper(FLTaskClass.CODE_DRAFT_MEDIUM)
        with patch("app.cost_warden.LMHelper") as mock_lm_cls:
            result = helper.call(system="sys", user="usr", stage=2,
                                 risk_override=FLProviderTier.CODEX_SUPERVISED)
        mock_lm_cls.assert_not_called()
        self.assertFalse(result.ok)
        self.assertIn("external_supervised", result.error)

    def test_non_external_lane_still_callable(self):
        """A non-external_supervised lane (e.g. CHEAP) must still reach LMHelper."""
        helper = FLLMHelper(FLTaskClass.SPEC_DRAFT)

        def _make_lm(*a, **kw):
            mock_instance = MagicMock()
            mock_instance.call.return_value = MagicMock(
                ok=True, content="ok", model_used="m", tier_used="cheap",
                reason="", error="", input_tokens=1, output_tokens=1, cost_usd=0.0,
            )
            return mock_instance

        with patch("app.cost_warden.LMHelper", side_effect=_make_lm) as mock_lm_cls:
            result = helper.call(system="sys", user="usr", stage=1)
        mock_lm_cls.assert_called_once()
        self.assertTrue(result.ok)


# ── TestStrongTierNotInDefaultPolicy ─────────────────────────────────────────

class TestStrongTierNotInDefaultPolicy(unittest.TestCase):
    """STRONG tier must not appear in any FL_TASK_POLICY default assignment."""

    def test_strong_not_in_any_task_policy(self):
        for tc, p in FL_TASK_POLICY.items():
            self.assertNotEqual(
                p.provider_tier, FLProviderTier.STRONG,
                f"STRONG tier found in default policy for {tc} — should be explicit-only",
            )

    def test_strong_reachable_via_override(self):
        """STRONG is accessible via risk_override — just not a default."""
        d = fl_route(FLTaskClass.CODE_DRAFT_LOW, stage=2,
                     risk_override=FLProviderTier.STRONG)
        self.assertEqual(d.provider_tier, FLProviderTier.STRONG)


# ── TestTierRank (codex_supervised) ──────────────────────────────────────────

class TestTierRankCodexSupervised(unittest.TestCase):
    def test_codex_supervised_between_coding_and_strong(self):
        self.assertGreater(
            _tier_rank(FLProviderTier.CODEX_SUPERVISED),
            _tier_rank(FLProviderTier.CODING),
        )
        self.assertLess(
            _tier_rank(FLProviderTier.CODEX_SUPERVISED),
            _tier_rank(FLProviderTier.STRONG),
        )

    def test_full_rank_order(self):
        ranks = [
            _tier_rank(FLProviderTier.CHEAP),
            _tier_rank(FLProviderTier.CODING),
            _tier_rank(FLProviderTier.CODEX_SUPERVISED),
            _tier_rank(FLProviderTier.STRONG),
            _tier_rank(FLProviderTier.CRITICAL),
        ]
        self.assertEqual(ranks, sorted(ranks), "Tier ranks must be strictly ascending")
        self.assertEqual(len(set(ranks)), 5, "All tier ranks must be unique")


# ── TestFlRoutingDecisionMetadata ─────────────────────────────────────────────

class TestFlRoutingDecisionMetadata(unittest.TestCase):
    """New metadata fields (provider_family, transport_mode, executability) in decisions."""

    def test_cheap_decision_has_metadata(self):
        d = fl_route(FLTaskClass.SPEC_DRAFT, stage=1)
        self.assertEqual(d.provider_family, "openrouter")
        self.assertEqual(d.transport_mode, "api")
        self.assertEqual(d.executability, "executable")

    def test_coding_decision_has_metadata(self):
        d = fl_route(FLTaskClass.CODE_DRAFT_MEDIUM, stage=2)
        self.assertEqual(d.provider_family, "openrouter")
        self.assertEqual(d.transport_mode, "api")
        self.assertEqual(d.executability, "config_only")

    def test_codex_supervised_decision_has_metadata(self):
        d = fl_route(FLTaskClass.CODE_DRAFT_CRITICAL, stage=2)
        self.assertEqual(d.provider_family, "codex")
        self.assertEqual(d.transport_mode, "supervised_external")
        self.assertEqual(d.executability, "external_supervised")

    def test_strong_override_decision_has_metadata(self):
        d = fl_route(FLTaskClass.CODE_DRAFT_LOW, stage=2,
                     risk_override=FLProviderTier.STRONG)
        self.assertEqual(d.provider_family, "claude")
        self.assertEqual(d.transport_mode, "api")
        self.assertEqual(d.executability, "executable")

    def test_critical_decision_has_metadata(self):
        d = fl_route(FLTaskClass.REVIEW_PROOF, stage=2)
        self.assertEqual(d.provider_family, "claude")
        self.assertEqual(d.transport_mode, "api")
        self.assertEqual(d.executability, "executable")

    def test_blocked_stage_decision_has_metadata(self):
        """Blocked decisions must still populate provider_family/transport_mode/executability."""
        d = fl_route(FLTaskClass.CODE_DRAFT_CRITICAL, stage=1)
        self.assertFalse(d.stage_allowed)
        self.assertIsInstance(d.provider_family, str)
        self.assertTrue(len(d.provider_family) > 0)
        self.assertIsInstance(d.transport_mode, str)
        self.assertIsInstance(d.executability, str)

    def test_policy_report_task_entries_have_metadata(self):
        report = get_fl_policy_report()
        for tc_name, entry in report["task_policy"].items():
            self.assertIn("provider_family", entry, f"Missing provider_family for {tc_name}")
            self.assertIn("transport_mode", entry, f"Missing transport_mode for {tc_name}")
            self.assertIn("executability", entry, f"Missing executability for {tc_name}")

    def test_policy_report_provider_entries_have_metadata(self):
        report = get_fl_policy_report()
        for tier_name, entry in report["provider_registry"].items():
            self.assertIn("provider_family", entry, f"Missing provider_family for {tier_name}")
            self.assertIn("transport_mode", entry, f"Missing transport_mode for {tier_name}")
            self.assertIn("executability", entry, f"Missing executability for {tier_name}")


if __name__ == "__main__":
    unittest.main()
