from __future__ import annotations

import uuid
from typing import Any


class HumanReviewManager:
    """Manages non-blocking human review for tools.

    When requireHumanReview is true, generates review API endpoints
    and tracks pending reviews without blocking the workflow.

    Attributes:
        _pending_reviews: Dict mapping review IDs to review info.
    """

    def __init__(self) -> None:
        """Initialize the HumanReviewManager with no pending reviews."""
        self._pending_reviews: dict[str, dict[str, Any]] = {}

    def create_review(self, tool_name: str) -> dict[str, Any]:
        """Create a pending human review for a tool.

        Args:
            tool_name: Name of the tool requiring review.

        Returns:
            A dict with review_id, review_url, and tool_name.
        """
        review_id = str(uuid.uuid4())[:8]
        review_url = f"/api/reviews/{review_id}"
        review_info = {
            "review_id": review_id,
            "tool_name": tool_name,
            "review_url": review_url,
            "status": "pending",
        }
        self._pending_reviews[review_id] = review_info
        return review_info

    def submit_review(self, review_id: str, approved: bool, comment: str = "") -> dict[str, Any] | None:
        """Submit a human review result.

        Args:
            review_id: The unique review identifier.
            approved: Whether the tool was approved.
            comment: Optional review comment.

        Returns:
            The updated review info, or None if review_id not found.
        """
        review = self._pending_reviews.get(review_id)
        if review is None:
            return None
        review["status"] = "approved" if approved else "rejected"
        review["comment"] = comment
        del self._pending_reviews[review_id]
        return review

    def get_pending_reviews(self) -> list[dict[str, Any]]:
        """Get all pending reviews.

        Returns:
            A list of pending review info dicts.
        """
        return list(self._pending_reviews.values())

    def get_review(self, review_id: str) -> dict[str, Any] | None:
        """Get a specific review by ID.

        Args:
            review_id: The review identifier.

        Returns:
            The review info dict, or None if not found.
        """
        return self._pending_reviews.get(review_id)
