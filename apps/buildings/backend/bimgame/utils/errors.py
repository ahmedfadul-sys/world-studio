"""Structured application errors: what failed, where, why, and how to fix it."""
from __future__ import annotations


class AppError(Exception):
    status = 400

    def __init__(self, what: str, where: str = "", why: str = "", fix: str = "", status: int | None = None):
        super().__init__(what)
        self.what, self.where, self.why, self.fix = what, where, why, fix
        if status is not None:
            self.status = status

    def to_dict(self) -> dict:
        return {"error": {"what": self.what, "where": self.where, "why": self.why, "fix": self.fix}}


class NotFound(AppError):
    status = 404


class Conflict(AppError):
    status = 409


class DependencyError(AppError):
    status = 503


class BuildError(AppError):
    status = 500
