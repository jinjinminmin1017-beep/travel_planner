from __future__ import annotations

from app.models.schemas import TravelPlan, TravelPlanResponse

PLANS: dict[str, TravelPlan] = {}
RESPONSES: dict[str, TravelPlanResponse] = {}


def save_response(response: TravelPlanResponse) -> None:
    RESPONSES[response.request_id] = response
    for plan in response.plans:
        PLANS[plan.plan_id] = plan


def get_plan(plan_id: str) -> TravelPlan | None:
    return PLANS.get(plan_id)


def update_plan(plan: TravelPlan) -> None:
    PLANS[plan.plan_id] = plan
