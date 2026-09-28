from fastapi import Request

from app.services.pipeline import AnalysisService


def get_service(request: Request) -> AnalysisService:
    return request.app.state.service
