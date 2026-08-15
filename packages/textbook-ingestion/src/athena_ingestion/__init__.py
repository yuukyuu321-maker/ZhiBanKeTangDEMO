"""Page-aware textbook import and local evidence retrieval."""

from .importer import ImportRequest, ImportResult, TextbookImporter
from .models import ImportStatus, QualityStatus, RenderMode
from .postgres_activation import (
    ActivationResult,
    TeachingGrantResult,
    activate_and_assign_bundle,
    grant_principal_teaching_scope,
)
from .postgres_registration import RegistrationResult, register_promoted_bundle
from .promotion import (
    PromotionResult,
    bundle_content_sha256,
    promote_bundle,
    validate_approved_bundle,
)
from .review import REQUIRED_REVIEW_CATEGORIES, record_review
from .review_sampling import build_review_plan, write_review_plan
from .search import EvidenceIndex, SearchResult

__all__ = [
    "ActivationResult",
    "EvidenceIndex",
    "ImportRequest",
    "ImportResult",
    "ImportStatus",
    "PromotionResult",
    "QualityStatus",
    "RegistrationResult",
    "REQUIRED_REVIEW_CATEGORIES",
    "RenderMode",
    "SearchResult",
    "TeachingGrantResult",
    "TextbookImporter",
    "activate_and_assign_bundle",
    "build_review_plan",
    "bundle_content_sha256",
    "grant_principal_teaching_scope",
    "promote_bundle",
    "record_review",
    "register_promoted_bundle",
    "validate_approved_bundle",
    "write_review_plan",
]
