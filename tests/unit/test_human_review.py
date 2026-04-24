from __future__ import annotations

from src.workflows.human_review import HumanReviewManager


class TestHumanReviewManager:
    def test_create_review(self) -> None:
        mgr = HumanReviewManager()
        review = mgr.create_review("tool_analyzer")
        assert review["tool_name"] == "tool_analyzer"
        assert review["status"] == "pending"
        assert "review_id" in review
        assert "/api/reviews/" in review["review_url"]

    def test_submit_review_approved(self) -> None:
        mgr = HumanReviewManager()
        review = mgr.create_review("tool_test")
        result = mgr.submit_review(review["review_id"], True, "Good")
        assert result["status"] == "approved"
        assert result["comment"] == "Good"

    def test_submit_review_rejected(self) -> None:
        mgr = HumanReviewManager()
        review = mgr.create_review("tool_test")
        result = mgr.submit_review(review["review_id"], False, "Bad")
        assert result["status"] == "rejected"

    def test_submit_review_not_found(self) -> None:
        mgr = HumanReviewManager()
        result = mgr.submit_review("nonexistent", True)
        assert result is None

    def test_get_pending_reviews(self) -> None:
        mgr = HumanReviewManager()
        mgr.create_review("tool_a")
        mgr.create_review("tool_b")
        pending = mgr.get_pending_reviews()
        assert len(pending) == 2

    def test_get_review(self) -> None:
        mgr = HumanReviewManager()
        review = mgr.create_review("tool_test")
        found = mgr.get_review(review["review_id"])
        assert found is not None
        assert found["tool_name"] == "tool_test"

    def test_get_review_not_found(self) -> None:
        mgr = HumanReviewManager()
        assert mgr.get_review("nonexistent") is None

    def test_review_removed_after_submit(self) -> None:
        mgr = HumanReviewManager()
        review = mgr.create_review("tool_test")
        mgr.submit_review(review["review_id"], True)
        assert mgr.get_review(review["review_id"]) is None
        assert mgr.get_pending_reviews() == []
